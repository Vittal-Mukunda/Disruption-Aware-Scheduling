"""
simulator.py ? Discrete-Event Warehouse Simulation Engine

Implements a realistic e-commerce fulfillment warehouse with 8 zones,
37 stations, 5 job types, stochastic disruptions, and pluggable heuristics.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass, field
from typing import Any, Callable, Dict, List, Optional, Tuple

import numpy as np
import simpy

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Data Structures
# ---------------------------------------------------------------------------

@dataclass
class ZoneConfig:
    """Configuration for a single warehouse zone."""
    zone_id: int
    name: str
    num_stations: int
    zone_type: str  # e.g. "receiving", "picking", "packing", "shipping"


@dataclass
class JobType:
    """Specification for a category of warehouse jobs."""
    name: str                           # "A" ? "E"
    route: List[int]                    # ordered zone IDs
    proc_time_ranges: List[Tuple[float, float]]  # (min, max) minutes per zone
    due_date_offset: float              # minutes from arrival to due date
    frequency: float                    # relative arrival weight
    priority_weight: float              # higher = more important


@dataclass
class Operation:
    """One processing step of a job at a specific zone/station."""
    zone_id: int
    nominal_proc_time: float
    actual_proc_time: float = 0.0
    start_time: float = -1.0
    end_time: float = -1.0
    station_id: int = -1


@dataclass
class Job:
    """A single warehouse order moving through the system."""
    job_id: int
    job_type: str
    arrival_time: float
    due_date: float
    operations: List[Operation]
    current_op_idx: int = 0
    priority: int = 1                   # 1=standard, 2=expedited, 3=VIP
    status: str = "waiting"             # waiting / processing / done / late
    completion_time: float = -1.0
    priority_escalated: bool = False

    @property
    def is_complete(self) -> bool:
        return self.current_op_idx >= len(self.operations)

    @property
    def next_zone_id(self) -> Optional[int]:
        if self.is_complete:
            return None
        return self.operations[self.current_op_idx].zone_id

    def remaining_proc_time(self) -> float:
        """Sum of nominal proc times for all remaining operations."""
        return sum(op.nominal_proc_time for op in self.operations[self.current_op_idx:])


@dataclass
class StationState:
    """Runtime state of a single processing station."""
    station_id: int
    zone_id: int
    is_broken: bool = False
    repair_end_time: float = 0.0
    current_job: Optional[int] = None   # job_id or None
    busy_until: float = 0.0


@dataclass
class SimulationMetrics:
    """All performance metrics from one simulation run."""
    makespan: float = 0.0
    total_tardiness: float = 0.0
    sla_breach_rate: float = 0.0
    avg_cycle_time: float = 0.0
    zone_utilization: Dict[int, float] = field(default_factory=dict)
    throughput: float = 0.0
    queue_max: int = 0
    queue_history: List[Tuple[float, Dict[int, int]]] = field(default_factory=list)
    completed_jobs: int = 0
    total_jobs: int = 0


# ---------------------------------------------------------------------------
# Simulator
# ---------------------------------------------------------------------------

class WarehouseSimulator:
    """
    SimPy-based discrete-event simulator for an e-commerce warehouse.

    Parameters
    ----------
    seed : int
        Random seed for full reproducibility.
    heuristic_fn : Callable
        Dispatch function: (jobs, current_time, zone_id) -> ordered List[Job].
    feature_extractor : optional
        FeatureExtractor instance used when running in hybrid-ML mode.
    """

    # Zone configuration: 8 zones with station counts summing to 37
    ZONE_SPECS: List[Tuple[int, str, int, str]] = [
        (0, "Receiving",    3, "receiving"),
        (1, "Sorting",      4, "sorting"),
        (2, "Picking-A",    6, "picking"),
        (3, "Picking-B",    8, "picking"),
        (4, "Value-Add",    5, "value_add"),
        (5, "QC",           4, "quality"),
        (6, "Packing",      3, "packing"),
        (7, "Shipping",     4, "shipping"),
    ]

    # Job-type definitions (name, route, proc_time_ranges, due_date, freq, prio_weight)
    JOB_TYPE_SPECS = [
        ("A", [0, 1, 2, 6, 7], [(3,8),(2,5),(5,12),(4,9),(2,4)],  120,  0.25, 2.0),
        ("B", [0, 1, 3, 5, 6, 7], [(3,8),(2,5),(6,14),(3,7),(4,9),(2,4)], 160, 0.30, 1.5),
        ("C", [0, 1, 4, 5, 6, 7], [(3,8),(2,5),(8,18),(3,7),(4,9),(2,4)], 240, 0.20, 1.0),
        ("D", [0, 1, 2, 4, 5, 6, 7], [(3,8),(2,5),(5,12),(8,18),(3,7),(4,9),(2,4)], 320, 0.15, 0.8),
        ("E", [1, 3, 7], [(2,5),(4,10),(1,3)], 60, 0.10, 3.0),   # express
    ]

    BASE_ARRIVAL_RATE = 2.5  # jobs per minute

    def __init__(
        self,
        seed: int,
        heuristic_fn: Callable,
        feature_extractor=None,
        base_arrival_rate: float = 2.5,
        breakdown_prob: float = 0.003,
        batch_arrival_size: int = 30,
        lunch_penalty_factor: float = 1.3,
    ) -> None:
        self.seed = seed
        self.heuristic_fn = heuristic_fn
        self.feature_extractor = feature_extractor
        self._base_arrival_rate   = base_arrival_rate
        self._breakdown_prob      = breakdown_prob
        self._batch_arrival_size  = batch_arrival_size
        self._lunch_penalty_factor = lunch_penalty_factor
        self.rng = np.random.default_rng(seed)

        self.env = simpy.Environment()

        self.zones: Dict[int, ZoneConfig] = {}
        self.job_types: Dict[str, JobType] = {}
        self.stations: Dict[int, StationState] = {}
        self.station_resources: Dict[int, simpy.Resource] = {}

        # Zone-level queues (list of Job)
        self.zone_queues: Dict[int, List[Job]] = {}

        # Job registry
        self.all_jobs: Dict[int, Job] = {}
        self.completed_jobs: List[Job] = []
        self._job_counter = 0

        # Metrics tracking
        self._zone_busy_time: Dict[int, float] = {}
        self._queue_snapshots: List[Tuple[float, Dict[int, int]]] = []
        self._max_queue: int = 0

        self._setup_zones()
        self._setup_job_types()

    # ------------------------------------------------------------------
    # Setup helpers
    # ------------------------------------------------------------------

    def _setup_zones(self) -> None:
        station_id = 0
        self.dispatcher_triggers = {}
        for zone_id, name, n_stations, zone_type in self.ZONE_SPECS:
            self.zones[zone_id] = ZoneConfig(zone_id, name, n_stations, zone_type)
            self.zone_queues[zone_id] = []
            self.dispatcher_triggers[zone_id] = self.env.event()
            self._zone_busy_time[zone_id] = 0.0
            for _ in range(n_stations):
                st = StationState(station_id=station_id, zone_id=zone_id)
                self.stations[station_id] = st
                self.station_resources[station_id] = simpy.Resource(self.env, capacity=1)
                station_id += 1

    def _setup_job_types(self) -> None:
        for name, route, proc_ranges, due_offset, freq, prio_w in self.JOB_TYPE_SPECS:
            self.job_types[name] = JobType(
                name=name,
                route=route,
                proc_time_ranges=proc_ranges,
                due_date_offset=due_offset,
                frequency=freq,
                priority_weight=prio_w,
            )

    # ------------------------------------------------------------------
    # Utility
    # ------------------------------------------------------------------

    def _next_job_id(self) -> int:
        jid = self._job_counter
        self._job_counter += 1
        return jid

    def _sample_job_type(self) -> str:
        types = list(self.job_types.keys())
        weights = [self.job_types[t].frequency for t in types]
        total = sum(weights)
        probs = [w / total for w in weights]
        return self.rng.choice(types, p=probs)

    def _create_job(self, job_type_name: str, arrival_time: float) -> Job:
        jt = self.job_types[job_type_name]
        operations = []
        for zone_id, (lo, hi) in zip(jt.route, jt.proc_time_ranges):
            nominal = float(self.rng.uniform(lo, hi))
            operations.append(Operation(zone_id=zone_id, nominal_proc_time=nominal))
        return Job(
            job_id=self._next_job_id(),
            job_type=job_type_name,
            arrival_time=arrival_time,
            due_date=arrival_time + jt.due_date_offset,
            operations=operations,
            priority=3 if job_type_name == "E" else 1,
        )

    def _get_surge_multiplier(self, current_time: float) -> float:
        """Time-of-day arrival rate multiplier (time in minutes from shift start)."""
        if current_time < 60:       # 0-60 min: ramp up
            return 0.7 + 0.3 * (current_time / 60)
        elif current_time < 180:    # 60-180 min: morning surge
            return 1.4
        elif current_time < 240:    # 180-240 min: moderate
            return 1.0
        elif current_time < 300:    # 240-300 min: lunch dip
            return 0.7
        elif current_time < 420:    # 300-420 min: afternoon surge
            return 1.3
        elif current_time < 540:    # 420-540 min: steady
            return 1.1
        else:                       # 540-600 min: end-of-day wind-down
            return 0.8

    def _record_queue_snapshot(self) -> None:
        snapshot = {z: len(q) for z, q in self.zone_queues.items()}
        self._queue_snapshots.append((self.env.now, snapshot))
        total = sum(snapshot.values())
        if total > self._max_queue:
            self._max_queue = total

    # ------------------------------------------------------------------
    # SimPy processes
    # ------------------------------------------------------------------

    def _arrival_process(self):
        """Continuous Poisson arrival of individual jobs."""
        while True:
            surge = self._get_surge_multiplier(self.env.now)
            rate = self._base_arrival_rate * surge
            inter_arrival = float(self.rng.exponential(1.0 / rate))
            yield self.env.timeout(inter_arrival)

            jt_name = self._sample_job_type()
            job = self._create_job(jt_name, self.env.now)
            self.all_jobs[job.job_id] = job
            self.env.process(self._process_job(job))

    def _batch_arrival_process(self):
        """Truck arrival every 45 min delivering configurable batch of orders."""
        while True:
            yield self.env.timeout(45.0)
            half = max(1, self._batch_arrival_size // 2)
            batch_size = int(self.rng.integers(half, self._batch_arrival_size + 1))
            for _ in range(batch_size):
                jt_name = self._sample_job_type()
                job = self._create_job(jt_name, self.env.now)
                self.all_jobs[job.job_id] = job
                self.env.process(self._process_job(job))

    def _station_breakdown_process(self, station: StationState):
        """Per-station breakdown process; rate and repair time are configurable."""
        while True:
            ttf = float(self.rng.exponential(1.0 / max(self._breakdown_prob, 1e-9)))
            yield self.env.timeout(ttf)
            station.is_broken = True
            repair_time = float(self.rng.exponential(18.0))
            station.repair_end_time = self.env.now + repair_time
            yield self.env.timeout(repair_time)
            station.is_broken = False
            self._trigger_dispatcher(station.zone_id)

    def _lunch_break_process(self):
        """Reduce capacity of all zones from 13:00 (780min?) to 14:00.
        Shift starts at t=0 = 08:00, so lunch is at t=300 to t=360."""
        yield self.env.timeout(300.0)
        # release one station resource per zone if possible
        self._lunch_active = True
        yield self.env.timeout(60.0)
        self._lunch_active = False

    def _priority_escalation_process(self):
        """Every 5 minutes, escalate 5% of standard waiting jobs."""
        while True:
            yield self.env.timeout(5.0)
            waiting = [
                j for j in self.all_jobs.values()
                if j.status == "waiting" and j.priority == 1 and not j.priority_escalated
            ]
            n_escalate = max(0, int(len(waiting) * 0.05))
            if n_escalate:
                chosen = self.rng.choice(len(waiting), size=n_escalate, replace=False)
                for idx in chosen:
                    waiting[idx].priority = 2
                    waiting[idx].priority_escalated = True

    def _snapshot_process(self):
        """Record queue depths every 5 minutes."""
        while True:
            self._record_queue_snapshot()
            yield self.env.timeout(5.0)

    # ------------------------------------------------------------------
    # Job processing
    # ------------------------------------------------------------------

    def _process_job(self, job: Job):
        """Route a job through all its operations sequentially."""
        for op_idx, op in enumerate(job.operations):
            zone_id = op.zone_id
            # Add to zone queue
            self.zone_queues[zone_id].append(job)
            job.status = "waiting"

            # Wait to be dispatched from queue
            job._dispatch_event = self.env.event()
            self._trigger_dispatcher(zone_id)
            yield job._dispatch_event

            # Pick a free station in the zone
            station_id = self._pick_station(zone_id)
            op.station_id = station_id
            resource = self.station_resources[station_id]
            st = self.stations[station_id]
            st.current_job = job.job_id

            with resource.request() as req:
                yield req
                # Check if station broke while waiting ? if so, wait for repair
                if st.is_broken:
                    yield self.env.timeout(max(0, st.repair_end_time - self.env.now))

                job.status = "processing"
                job.current_op_idx = op_idx

                # Apply lognormal variability: nominal * lognormal(0, 0.15)
                variability = float(self.rng.lognormal(0, 0.15))
                # Lunch break penalty: +30% if active
                lunch_penalty = self._lunch_penalty_factor if self._lunch_active else 1.0
                actual_time = op.nominal_proc_time * variability * lunch_penalty

                op.actual_proc_time = actual_time
                op.start_time = self.env.now
                self._zone_busy_time[zone_id] = (
                    self._zone_busy_time.get(zone_id, 0.0) + actual_time
                )

                yield self.env.timeout(actual_time)

                op.end_time = self.env.now
                st.busy_until = self.env.now
                st.current_job = None
                
            self._trigger_dispatcher(zone_id)

        # Job fully processed
        job.status = "done"
        job.completion_time = self.env.now
        job.current_op_idx = len(job.operations)
        self.completed_jobs.append(job)

    def _trigger_dispatcher(self, zone_id: int):
        """Wake up the zone dispatcher if it's idle."""
        if not self.dispatcher_triggers[zone_id].triggered:
            self.dispatcher_triggers[zone_id].succeed()

    def _zone_dispatcher(self, zone_id: int):
        """Centralized dispatcher process for a zone to avoid O(N^2) polling."""
        while True:
            # Wait until there is a reason to check the queue (new job, or finished job)
            yield self.dispatcher_triggers[zone_id]
            self.dispatcher_triggers[zone_id] = self.env.event()
            
            while True:
                queue = self.zone_queues[zone_id]
                if not queue:
                    break
                    
                free_stations = [
                    sid for sid, st in self.stations.items()
                    if st.zone_id == zone_id and not st.is_broken
                    and self.station_resources[sid].count + len(self.station_resources[sid].queue) == 0
                ]
                
                if not free_stations:
                    break
                    
                # We have queue and free station(s). Sort exactly once per dispatch!
                ordered = self.heuristic_fn(queue, self.env.now, zone_id)
                best_job = ordered[0]
                queue.remove(best_job)
                
                # Awaken the job
                best_job._dispatch_event.succeed()
                
                # Yield 0 to allow the job to claim the resource and update count before next loop
                yield self.env.timeout(0)

    def _pick_station(self, zone_id: int) -> int:
        """Pick a free non-broken station, else fallback to least-busy."""
        free_stations = [
            sid for sid, st in self.stations.items()
            if st.zone_id == zone_id and not st.is_broken
            and self.station_resources[sid].count + len(self.station_resources[sid].queue) == 0
        ]
        if free_stations:
            return free_stations[0]
            
        zone_stations = [
            sid for sid, st in self.stations.items()
            if st.zone_id == zone_id and not st.is_broken
        ]
        if not zone_stations:
            # All broken ? pick any (will wait for repair inside _process_job)
            zone_stations = [sid for sid, st in self.stations.items() if st.zone_id == zone_id]
        return min(zone_stations, key=lambda sid: self.stations[sid].busy_until)

    # ------------------------------------------------------------------
    # Streaming API (for WebSocket backend)
    # ------------------------------------------------------------------

    def init(self) -> None:
        """Set up all SimPy processes without running. Call step_to() to advance."""
        self._lunch_active = False
        self.env.process(self._arrival_process())
        self.env.process(self._batch_arrival_process())
        self.env.process(self._priority_escalation_process())
        self.env.process(self._lunch_break_process())
        self.env.process(self._snapshot_process())
        for zone_id in self.zones:
            self.env.process(self._zone_dispatcher(zone_id))
        for station in self.stations.values():
            self.env.process(self._station_breakdown_process(station))

    def step_to(self, t: float) -> None:
        """Advance simulation to time t (must have called init() first)."""
        self.env.run(until=t)

    def get_visual_snapshot(self) -> Dict[str, Any]:
        """Return the current visual state for the frontend canvas."""
        now = self.env.now
        completed = self.completed_jobs
        n = len(completed)

        total_tard = sum(max(0.0, j.completion_time - j.due_date) for j in completed)
        n_late     = sum(1 for j in completed if j.completion_time > j.due_date)
        sla        = n_late / n if n else 0.0
        avg_cycle  = (sum(j.completion_time - j.arrival_time for j in completed) / n
                      if n else 0.0)
        throughput = (n / max(now, 0.001)) * 60.0

        # Waiting jobs: read directly from zone queues (accurate zone assignment)
        active_jobs: List[Dict[str, Any]] = []
        for zone_id, queue in self.zone_queues.items():
            for job in queue:
                active_jobs.append({
                    "id": job.job_id, "type": job.job_type,
                    "zoneId": zone_id, "status": "waiting",
                    "priority": job.priority,
                })

        # Processing jobs: current_op_idx points to active operation
        for job in self.all_jobs.values():
            if job.status == "processing" and job.current_op_idx < len(job.operations):
                active_jobs.append({
                    "id": job.job_id, "type": job.job_type,
                    "zoneId": job.operations[job.current_op_idx].zone_id,
                    "status": "processing",
                    "priority": job.priority,
                })

        # Cap at 50 to keep WebSocket payload under the 16 MB limit
        active_jobs = active_jobs[:50]

        zone_active = [
            sum(1 for j in self.all_jobs.values()
                if j.status == "processing"
                and j.current_op_idx < len(j.operations)
                and j.operations[j.current_op_idx].zone_id == z)
            for z in range(8)
        ]

        return {
            "time": round(now, 2),
            "activeJobs": active_jobs,
            "zoneQueueLengths": [len(self.zone_queues.get(z, [])) for z in range(8)],
            "zoneActiveCounts": zone_active,
            "metrics": {
                "completed":      n,
                "totalTardiness": round(total_tard, 1),
                "slaBreachRate":  round(sla, 4),
                "avgCycleTime":   round(avg_cycle, 2),
                "throughput":     round(throughput, 2),
            },
        }

    # ------------------------------------------------------------------
    # Run
    # ------------------------------------------------------------------

    def run(self, duration: float = 600.0) -> SimulationMetrics:
        """Execute a full shift simulation and return performance metrics."""
        self._lunch_active = False

        self.env.process(self._arrival_process())
        self.env.process(self._batch_arrival_process())
        self.env.process(self._priority_escalation_process())
        self.env.process(self._lunch_break_process())
        self.env.process(self._snapshot_process())

        # Start dispatchers
        for zone_id in self.zones:
            self.env.process(self._zone_dispatcher(zone_id))

        # Start per-station breakdown processes
        for station in self.stations.values():
            self.env.process(self._station_breakdown_process(station))

        self.env.run(until=duration)

        return self._compute_metrics(duration)

    def _compute_metrics(self, duration: float) -> SimulationMetrics:
        """Calculate all 7 performance metrics from the completed simulation."""
        completed = self.completed_jobs
        total_jobs = len(self.all_jobs)
        n_completed = len(completed)

        if not completed:
            return SimulationMetrics(
                makespan=duration,
                zone_utilization={z: 0.0 for z in self.zones},
                queue_history=self._queue_snapshots,
            )

        # Makespan: time when last job completed (or full duration)
        makespan = max((j.completion_time for j in completed), default=duration)

        # Tardiness: sum of max(0, completion - due_date) over all completed
        total_tardiness = sum(
            max(0.0, j.completion_time - j.due_date) for j in completed
        )

        # SLA breach rate: fraction of jobs completed after due_date
        n_late = sum(1 for j in completed if j.completion_time > j.due_date)
        sla_breach_rate = n_late / n_completed if n_completed else 0.0

        # Average cycle time
        avg_cycle_time = np.mean(
            [j.completion_time - j.arrival_time for j in completed]
        ) if completed else 0.0

        # Zone utilization: busy_time / (n_stations * duration)
        zone_utilization = {}
        for zone_id, zone in self.zones.items():
            busy = self._zone_busy_time.get(zone_id, 0.0)
            capacity = zone.num_stations * duration
            zone_utilization[zone_id] = min(1.0, busy / capacity) if capacity > 0 else 0.0

        # Throughput: jobs per hour
        throughput = (n_completed / duration) * 60.0

        # Max queue depth
        queue_max = self._max_queue

        return SimulationMetrics(
            makespan=makespan,
            total_tardiness=total_tardiness,
            sla_breach_rate=sla_breach_rate,
            avg_cycle_time=float(avg_cycle_time),
            zone_utilization=zone_utilization,
            throughput=throughput,
            queue_max=queue_max,
            queue_history=self._queue_snapshots,
            completed_jobs=n_completed,
            total_jobs=total_jobs,
        )

    def get_state_snapshot(self) -> Dict[str, Any]:
        """Return current system state for feature extraction."""
        now = self.env.now
        n_broken = sum(1 for st in self.stations.values() if st.is_broken)
        queue_sizes = {z: len(q) for z, q in self.zone_queues.items()}
        waiting_jobs = [j for j in self.all_jobs.values() if j.status == "waiting"]

        return {
            "current_time": now,
            "n_orders_in_system": len(waiting_jobs) + sum(
                1 for j in self.all_jobs.values() if j.status == "processing"
            ),
            "n_express_orders": sum(1 for j in waiting_jobs if j.job_type == "E"),
            "queue_sizes": queue_sizes,
            "zone_utilization": {
                z: min(1.0, self._zone_busy_time.get(z, 0.0) / max(1.0, now * self.zones[z].num_stations))
                for z in self.zones
            },
            "n_broken_stations": n_broken,
            "lunch_active": getattr(self, "_lunch_active", False),
            "surge_multiplier": self._get_surge_multiplier(now),
            "completed_so_far": len(self.completed_jobs),
            "waiting_jobs": waiting_jobs,
            "completed_jobs": self.completed_jobs,
            "all_jobs": self.all_jobs,
            "zones": self.zones,
            "stations": self.stations,
        }
