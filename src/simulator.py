"""
simulator.py — Discrete-Event Warehouse Simulation Engine (DAHS_2)

Implements a realistic e-commerce fulfillment warehouse with 8 zones,
37 stations, 5 job types, stochastic disruptions, and pluggable heuristics.

NEW in DAHS_2:
  - save_state() -> dict — snapshot full simulation state for fork training
  - from_state(state_dict, heuristic_fn) -> WarehouseSimulator (classmethod)
  - get_partial_metrics(since_time) -> SimulationMetrics — for 20-min fork windows
"""

from __future__ import annotations

import copy
import logging
from dataclasses import dataclass, field
from typing import Any, Callable, Dict, List, Optional, Tuple, Union

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
    name: str                           # "A" – "E"
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
    SimPy-based discrete-event simulator for an e-commerce fulfillment center.

    Simulation parameters are calibrated to published warehouse operations research:

    - Zone structure & station counts (37 total, 8 zones):
        De Koster et al. (2007), EJOR 182(2):481-501 — 20-50 stations typical for
        mid-scale distribution centers.
        Gu et al. (2010), EJOR 203(3):539-549 — warehouse design benchmarks.

    - Arrival rate (BASE_ARRIVAL_RATE = 1.5 jobs/min = 90/hr):
        Gu et al. (2010) — 60-150 orders/hour for mid-scale DCs.
        (Default constructor arg is 2.5, calibrated preset uses 1.5.)

    - Processing time ranges (Picking 5-18 min, Receiving 3-8 min):
        Tompkins et al. (2010), Facilities Planning, Wiley 4th ed.
        Bartholdi & Hackman (2019), Warehouse & Distribution Science, GT.

    - Breakdown frequency (BREAKDOWN_PROB = 0.003):
        Inman (1999), Prod. & Inv. Mgmt. Journal 40(2):67-71 — 2-5% of
        operational hours. 0.003/min × 37 stations × 600 min ≈ 2.7% exposure.

    - Repair time mean (18 min, Exponential):
        Goetschalckx & Ashayeri (1989) — 10-30 min MTTR for conveyor/AGV.

    - Batch arrival size (30 jobs, every 45 min):
        Bartholdi & Hackman (2019) — 20-60 items per truck unload;
        30-60 min between truck docks for mid-scale DC.

    - Processing time variability (lognormal σ = 0.30, CV ≈ 30%):
        De Koster et al. (2007) — CV of 20-35% for manual warehouse operations.

    - Lunch productivity penalty (1.3×, 30% slowdown):
        Garg et al. (2017), Int. J. Industrial Engineering 24(3):181-192 —
        20-40% productivity drop during scheduled breaks.

    - Worker utilization target (implicit 65-80%):
        Frazelle (2016), World-Class Warehousing, McGraw-Hill 2nd ed.

    - Due date SLA windows (60-320 min, spanning 1-5.3 hours):
        Industry standard SLA windows of 1-8 hours for e-commerce fulfillment.
        Frazelle (2016) — 2-10% SLA breach acceptable in well-run warehouses.

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
    # Total 37 stations within published 20-50 range for mid-scale DCs
    # Ref: De Koster et al. (2007), EJOR 182(2):481-501
    # Ref: Gu et al. (2010), EJOR 203(3):539-549
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

    # Job-type definitions (name, route, proc_time_ranges, due_date_offset_min, freq, prio_weight)
    # Processing time ranges (min, max) in minutes:
    #   Receiving ops (3-8 min): Bartholdi & Hackman (2019) — upper-end realistic with inspection
    #   Picking ops (5-18 min):  Tompkins et al. (2010), Facilities Planning — 2-15 min/order
    #   Value-Add (8-18 min):    Tompkins et al. (2010) — extended operations
    # Due date offsets (60-320 min, spanning 1-5.3 hours):
    #   Ref: Frazelle (2016) — typical SLA windows 1-8 hours for e-commerce fulfillment
    JOB_TYPE_SPECS = [
        ("A", [0, 1, 2, 6, 7], [(3,8),(2,5),(5,12),(4,9),(2,4)],  120,  0.25, 2.0),
        ("B", [0, 1, 3, 5, 6, 7], [(3,8),(2,5),(6,14),(3,7),(4,9),(2,4)], 160, 0.30, 1.5),
        ("C", [0, 1, 4, 5, 6, 7], [(3,8),(2,5),(8,18),(3,7),(4,9),(2,4)], 240, 0.20, 1.0),
        ("D", [0, 1, 2, 4, 5, 6, 7], [(3,8),(2,5),(5,12),(8,18),(3,7),(4,9),(2,4)], 320, 0.15, 0.8),
        ("E", [1, 3, 7], [(2,5),(4,10),(1,3)], 60, 0.10, 3.0),   # express — tight SLA
    ]

    # Base arrival rate: 2.5 jobs/min = 150/hr (peak); calibrated preset uses 1.5 (90/hr = mid-scale)
    # Published range: 60-150 orders/hour for mid-scale distribution centers
    # Ref: Gu et al. (2010), EJOR 203(3):539-549
    BASE_ARRIVAL_RATE = 2.5  # jobs per minute
    SIM_DURATION = 600.0  # minutes (one 10-hour shift)

    def __init__(
        self,
        seed: int,
        heuristic_fn: Callable,
        feature_extractor=None,
        # breakdown_prob: 0.003/min ≈ 2.7% exposure over 600 min × 37 stations
        # Published range: 2-5% of operational hours — Inman (1999)
        base_arrival_rate: float = 2.5,
        breakdown_prob: float = 0.003,
        # batch_arrival_size: 30 items per truck — within published 20-60 range
        # Ref: Bartholdi & Hackman (2019), Warehouse & Distribution Science
        batch_arrival_size: int = 30,
        # lunch_penalty_factor: 1.3x = 30% productivity drop during break
        # Published range: 20-40% — Garg et al. (2017), Int. J. Industrial Engineering
        lunch_penalty_factor: float = 1.3,
        # Preset overrides — leave empty/1.0 for default behavior
        job_type_frequencies: Optional[Dict[str, float]] = None,
        due_date_tightness: float = 1.0,
        processing_time_scale: float = 1.0,
    ) -> None:
        self.seed = seed
        self.heuristic_fn = heuristic_fn
        self.feature_extractor = feature_extractor
        self._base_arrival_rate    = base_arrival_rate
        self._breakdown_prob       = breakdown_prob
        self._batch_arrival_size   = batch_arrival_size
        self._lunch_penalty_factor = lunch_penalty_factor
        self._job_type_frequencies = job_type_frequencies or {}
        self._due_date_tightness   = due_date_tightness
        self._processing_time_scale = processing_time_scale

        # Validate preset frequency overrides sum to ~1.0
        if self._job_type_frequencies:
            total = sum(self._job_type_frequencies.values())
            if total > 0 and abs(total - 1.0) > 0.01:
                logger.warning("job_type_frequencies sum=%.3f (expected ~1.0)", total)

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
        self._lunch_active: bool = False

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
            effective_freq = self._job_type_frequencies.get(name, freq) if self._job_type_frequencies else freq
            effective_due = due_offset * self._due_date_tightness
            scaled_ranges = [
                (lo * self._processing_time_scale, hi * self._processing_time_scale)
                for lo, hi in proc_ranges
            ]
            self.job_types[name] = JobType(
                name=name,
                route=route,
                proc_time_ranges=scaled_ranges,
                due_date_offset=effective_due,
                frequency=effective_freq,
                priority_weight=prio_w,
            )

    # ------------------------------------------------------------------
    # Utility
    # ------------------------------------------------------------------

    def _next_job_id(self) -> int:
        jid = self._job_counter
        self._job_counter += 1
        return jid

    # Time-varying composition profile — reflects realistic daily order-mix shifts
    # observed in e-commerce fulfillment centres:
    #   morning        (0-120 min):  overnight standard-order backlog → Type A dominant
    #   mid-morning    (120-240):    diversifying mix — bulk Type B/C joins the floor
    #   afternoon      (240-420):    heavy bulk (C, D) as truck deliveries concentrate
    #   evening peak   (420-600):    same-day cut-off surge — Type E express dominates
    # Values are anchor points; _get_composition_profile interpolates linearly
    # between them so the distribution shifts smoothly rather than in hard steps.
    # Refs: Bartholdi & Hackman (2019) §6; De Koster et al. (2007) EJOR 182(2);
    #       Boysen et al. (2019) EJOR 277(2):396-411 — e-commerce warehousing patterns.
    _COMPOSITION_PROFILE = [
        (0.0,    {"A": 0.55, "B": 0.18, "C": 0.10, "D": 0.09, "E": 0.08}),
        (120.0,  {"A": 0.45, "B": 0.22, "C": 0.13, "D": 0.10, "E": 0.10}),
        (240.0,  {"A": 0.25, "B": 0.32, "C": 0.20, "D": 0.13, "E": 0.10}),
        (360.0,  {"A": 0.15, "B": 0.25, "C": 0.30, "D": 0.20, "E": 0.10}),
        (480.0,  {"A": 0.12, "B": 0.18, "C": 0.22, "D": 0.13, "E": 0.35}),
        (600.0,  {"A": 0.10, "B": 0.14, "C": 0.12, "D": 0.08, "E": 0.56}),
    ]

    # Composition noise: Gaussian perturbation σ applied per component, then
    # renormalised to sum to 1. Keeps the profile from being artificially smooth
    # while preserving the overall daily trend. Low enough (σ=0.03) that no single
    # solver is accidentally favoured by random fluctuations.
    _COMPOSITION_NOISE_SIGMA = 0.03

    # Intraday arrival-rate multiplier anchors (time in minutes from shift start).
    # Bimodal curve with a mild morning plateau, lunch dip, and a strong evening
    # peak reflecting the same-day cut-off surge that is characteristic of
    # e-commerce fulfilment centres. Values are interpolated linearly between
    # anchors and a small multiplicative noise band is applied per sample.
    # Refs: Boysen et al. (2019) EJOR 277(2); Bartholdi & Hackman (2019) §2.3;
    #       De Koster et al. (2007) EJOR 182(2) — workload profiles in DCs.
    _SURGE_PROFILE = [
        (0.0,   0.55),   # shift start — overnight backlog, still warming up
        (60.0,  0.95),   # morning ramp complete
        (120.0, 1.05),   # morning baseline
        (180.0, 1.15),   # pre-lunch mild peak
        (240.0, 0.60),   # lunch dip (productivity drop)
        (300.0, 0.95),   # post-lunch recovery
        (360.0, 1.20),   # afternoon ramp
        (420.0, 1.45),   # approaching evening peak
        (480.0, 1.65),   # evening peak — same-day cut-off surge
        (540.0, 1.50),   # late evening (still elevated)
        (600.0, 1.30),   # shift close (slight taper)
    ]
    # Multiplicative noise band applied per surge evaluation; keeps arrivals
    # stochastic without systematically biasing any heuristic.
    _SURGE_NOISE_LO = 0.93
    _SURGE_NOISE_HI = 1.07

    def _get_composition_profile(self, t: float) -> Dict[str, float]:
        """Per-type probability vector at time t.

        If the caller supplied explicit ``job_type_frequencies`` (used by
        calibration tests and heuristic-biased presets) those are returned
        verbatim. Otherwise the profile is **linearly interpolated** between the
        anchor points in ``_COMPOSITION_PROFILE`` and a small Gaussian noise
        term is added so the distribution is not artificially deterministic.
        The noisy vector is clipped to be non-negative and renormalised to 1.
        """
        if self._job_type_frequencies:
            return dict(self._job_type_frequencies)

        types = ("A", "B", "C", "D", "E")

        # Find the two anchor points bracketing t
        anchors = self._COMPOSITION_PROFILE
        if t <= anchors[0][0]:
            base = anchors[0][1]
        elif t >= anchors[-1][0]:
            base = anchors[-1][1]
        else:
            base = anchors[0][1]
            for (t_a, p_a), (t_b, p_b) in zip(anchors[:-1], anchors[1:]):
                if t_a <= t < t_b:
                    alpha = (t - t_a) / max(t_b - t_a, 1e-9)
                    base = {k: (1 - alpha) * p_a[k] + alpha * p_b[k] for k in types}
                    break

        # Stochastic perturbation for realism (seeded via self.rng).
        if self._COMPOSITION_NOISE_SIGMA > 0:
            noisy = {
                k: max(0.0, base[k] + float(self.rng.normal(0.0, self._COMPOSITION_NOISE_SIGMA)))
                for k in types
            }
            total = sum(noisy.values())
            if total > 0:
                return {k: v / total for k, v in noisy.items()}
        return dict(base)

    def _sample_job_type(self) -> str:
        profile = self._get_composition_profile(self.env.now)
        types = list(self.job_types.keys())
        weights = [profile.get(t, self.job_types[t].frequency) for t in types]
        total = sum(weights)
        if total <= 0:
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

    def _surge_base_rate(self, current_time: float) -> float:
        """Deterministic trend value of the surge multiplier at time ``t``.

        Pure anchor-point interpolation — no RNG calls, so this is safe to
        invoke from informational paths (state snapshots, feature extraction)
        without disturbing the arrival-process sample stream.
        """
        anchors = self._SURGE_PROFILE
        if current_time <= anchors[0][0]:
            return float(anchors[0][1])
        if current_time >= anchors[-1][0]:
            return float(anchors[-1][1])
        for (t_a, v_a), (t_b, v_b) in zip(anchors[:-1], anchors[1:]):
            if t_a <= current_time < t_b:
                alpha = (current_time - t_a) / max(t_b - t_a, 1e-9)
                return float((1.0 - alpha) * v_a + alpha * v_b)
        return float(anchors[-1][1])

    def _get_surge_multiplier(self, current_time: float) -> float:
        """Time-of-day arrival-rate multiplier (t in minutes from shift start).

        The curve is a linear interpolation between the anchor points in
        ``_SURGE_PROFILE`` plus a small multiplicative noise term drawn from
        ``U(_SURGE_NOISE_LO, _SURGE_NOISE_HI)`` — so the instantaneous rate is
        both deterministically trended (bimodal with evening peak) and
        stochastically perturbed each time the process samples an arrival.
        Returns a strictly positive multiplier.
        """
        base = self._surge_base_rate(current_time)
        noise = float(self.rng.uniform(self._SURGE_NOISE_LO, self._SURGE_NOISE_HI))
        return max(0.05, base * noise)

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
        """Truck arrival every 45 min delivering configurable batch of orders.

        Interval: 30-60 min between truck docks is typical for mid-scale DCs.
        Batch size: 20-60 items per truck unload.
        Ref: Bartholdi & Hackman (2019), Warehouse & Distribution Science.
        """
        while True:
            yield self.env.timeout(45.0)  # 45 min interval — within 30-60 min published range
            half = max(1, self._batch_arrival_size // 2)
            batch_size = int(self.rng.integers(half, self._batch_arrival_size + 1))
            for _ in range(batch_size):
                jt_name = self._sample_job_type()
                job = self._create_job(jt_name, self.env.now)
                self.all_jobs[job.job_id] = job
                self.env.process(self._process_job(job))

    def _station_breakdown_process(self, station: StationState):
        """Per-station breakdown process; rate and repair time are configurable.

        BREAKDOWN_PROB = 0.003/min: at 37 stations × 600 min, expected total
        breakdown exposure ≈ 2.7%, within published 2-5% range.
        Ref: Inman (1999), Prod. & Inv. Mgmt. Journal 40(2):67-71.

        Repair time mean = 18 min (Exponential): within 10-30 min MTTR for
        conveyor/AGV equipment in warehouse environments.
        Ref: Goetschalckx & Ashayeri (1989), Logistics World 2(2):99-106.
        """
        while True:
            ttf = float(self.rng.exponential(1.0 / max(self._breakdown_prob, 1e-9)))
            yield self.env.timeout(ttf)
            station.is_broken = True
            repair_time = float(self.rng.exponential(18.0))  # mean 18 min MTTR
            station.repair_end_time = self.env.now + repair_time
            yield self.env.timeout(repair_time)
            station.is_broken = False
            self._trigger_dispatcher(station.zone_id)

    def _lunch_break_process(self):
        """Lunch break from t=300 to t=360 (13:00-14:00)."""
        yield self.env.timeout(300.0)
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
            self.zone_queues[zone_id].append(job)
            job.status = "waiting"

            job._dispatch_event = self.env.event()
            self._trigger_dispatcher(zone_id)
            yield job._dispatch_event

            station_id = self._pick_station(zone_id)
            op.station_id = station_id
            resource = self.station_resources[station_id]
            st = self.stations[station_id]
            st.current_job = job.job_id

            with resource.request() as req:
                yield req
                # Re-check breakdown: station may have broken while job was queued.
                while st.is_broken:
                    wait_time = max(0.1, st.repair_end_time - self.env.now)
                    yield self.env.timeout(wait_time)

                job.status = "processing"
                job.current_op_idx = op_idx

                # Lognormal sigma = 0.30 → CV ≈ 30%, within published 20-35% range
                # Ref: De Koster et al. (2007), EJOR 182(2):481-501
                variability = float(self.rng.lognormal(0, 0.30))
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
        """Centralized dispatcher process for a zone."""
        while True:
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

                ordered = self.heuristic_fn(queue, self.env.now, zone_id)
                best_job = ordered[0]
                queue.remove(best_job)

                best_job._dispatch_event.succeed()
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
            zone_stations = [sid for sid, st in self.stations.items() if st.zone_id == zone_id]
        return min(zone_stations, key=lambda sid: self.stations[sid].busy_until)

    # ------------------------------------------------------------------
    # Streaming API (for WebSocket backend)
    # ------------------------------------------------------------------

    def init(self) -> None:
        """Set up all SimPy processes without running. Call step_to() to advance."""
        self._lunch_active = False
        self._processes_registered = True
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

        active_jobs: List[Dict[str, Any]] = []
        for zone_id, queue in self.zone_queues.items():
            for job in queue:
                active_jobs.append({
                    "id": job.job_id, "type": job.job_type,
                    "zoneId": zone_id, "status": "waiting",
                    "priority": job.priority,
                })

        for job in self.all_jobs.values():
            if job.status == "processing" and job.current_op_idx < len(job.operations):
                active_jobs.append({
                    "id": job.job_id, "type": job.job_type,
                    "zoneId": job.operations[job.current_op_idx].zone_id,
                    "status": "processing",
                    "priority": job.priority,
                })

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
                "completedJobs":  n,
                "totalTardiness": round(total_tard, 1),
                "slaBreachRate":  round(sla, 4),
                "avgCycleTime":   round(avg_cycle, 2),
                "throughput":     round(throughput, 2),
                "jobsPerHour":    round(throughput, 2),
            },
        }

    # ------------------------------------------------------------------
    # Run (batch mode)
    # ------------------------------------------------------------------

    def run(self, duration: float = 600.0) -> SimulationMetrics:
        """Execute a full shift simulation and return performance metrics."""
        if not hasattr(self, "_processes_registered") or not self._processes_registered:
            self.init()

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

        makespan = max((j.completion_time for j in completed), default=duration)

        total_tardiness = sum(
            max(0.0, j.completion_time - j.due_date) for j in completed
        )

        n_late = sum(1 for j in completed if j.completion_time > j.due_date)
        sla_breach_rate = n_late / n_completed if n_completed else 0.0

        avg_cycle_time = float(np.mean(
            [j.completion_time - j.arrival_time for j in completed]
        )) if completed else 0.0

        zone_utilization = {}
        for zone_id, zone in self.zones.items():
            busy = self._zone_busy_time.get(zone_id, 0.0)
            capacity = zone.num_stations * duration
            zone_utilization[zone_id] = min(1.0, busy / capacity) if capacity > 0 else 0.0

        throughput = (n_completed / duration) * 60.0

        queue_max = self._max_queue

        return SimulationMetrics(
            makespan=makespan,
            total_tardiness=total_tardiness,
            sla_breach_rate=sla_breach_rate,
            avg_cycle_time=avg_cycle_time,
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
            "lunch_active": self._lunch_active,
            "surge_multiplier": self._surge_base_rate(now),
            "completed_so_far": len(self.completed_jobs),
            "waiting_jobs": waiting_jobs,
            "completed_jobs": self.completed_jobs,
            "all_jobs": self.all_jobs,
            "zones": self.zones,
            "stations": self.stations,
        }

    # ------------------------------------------------------------------
    # NEW in DAHS_2: State save/restore for snapshot-fork training
    # ------------------------------------------------------------------

    @staticmethod
    def _serialize_job(job: Job) -> Dict[str, Any]:
        """Convert a Job to a plain dict (avoids deepcopy of SimPy events)."""
        return {
            "job_id": job.job_id,
            "job_type": job.job_type,
            "arrival_time": job.arrival_time,
            "due_date": job.due_date,
            "operations": [
                {
                    "zone_id": op.zone_id,
                    "nominal_proc_time": op.nominal_proc_time,
                    "actual_proc_time": op.actual_proc_time,
                    "start_time": op.start_time,
                    "end_time": op.end_time,
                    "station_id": op.station_id,
                }
                for op in job.operations
            ],
            "current_op_idx": job.current_op_idx,
            "priority": job.priority,
            "status": job.status,
            "completion_time": job.completion_time,
            "priority_escalated": job.priority_escalated,
        }

    @staticmethod
    def _deserialize_job(d: Dict[str, Any]) -> Job:
        """Reconstruct a Job from a plain dict."""
        ops = [
            Operation(
                zone_id=o["zone_id"],
                nominal_proc_time=o["nominal_proc_time"],
                actual_proc_time=o["actual_proc_time"],
                start_time=o["start_time"],
                end_time=o["end_time"],
                station_id=o["station_id"],
            )
            for o in d["operations"]
        ]
        job = Job(
            job_id=d["job_id"],
            job_type=d["job_type"],
            arrival_time=d["arrival_time"],
            due_date=d["due_date"],
            operations=ops,
            current_op_idx=d["current_op_idx"],
            priority=d["priority"],
            status=d["status"],
            completion_time=d["completion_time"],
            priority_escalated=d["priority_escalated"],
        )
        return job

    def save_state(self) -> Dict[str, Any]:
        """Capture complete simulation state for snapshot-fork training.

        Returns a pickling-safe dict (no SimPy objects) containing:
        - env.now (current time)
        - Serialized jobs, completed_jobs, zone_queues (as job IDs)
        - All station states (is_broken, repair_end_time, current_job, busy_until)
        - RNG state via rng.bit_generator.state
        - _job_counter, _zone_busy_time, _lunch_active, queue snapshot history

        NOTE: The from_state() classmethod creates a fresh SimPy environment and
        re-initializes processes from the saved data point.
        """
        state = {
            "env_time": self.env.now,
            "seed": self.seed,
            "_job_counter": self._job_counter,
            "_max_queue": self._max_queue,
            "_lunch_active": self._lunch_active,
            "_zone_busy_time": dict(self._zone_busy_time),
            "_queue_snapshots": list(self._queue_snapshots),
            "rng_state": self.rng.bit_generator.state,
            # Simulator config for reconstruction
            "_base_arrival_rate": self._base_arrival_rate,
            "_breakdown_prob": self._breakdown_prob,
            "_batch_arrival_size": self._batch_arrival_size,
            "_lunch_penalty_factor": self._lunch_penalty_factor,
            "_job_type_frequencies": dict(self._job_type_frequencies),
            "_due_date_tightness": self._due_date_tightness,
            "_processing_time_scale": self._processing_time_scale,
            # Serialized job data (can't deepcopy — SimPy events aren't picklable)
            "all_jobs": {
                jid: self._serialize_job(job)
                for jid, job in self.all_jobs.items()
            },
            "completed_jobs": [self._serialize_job(j) for j in self.completed_jobs],
            "zone_queues": {z: [j.job_id for j in q] for z, q in self.zone_queues.items()},
            # Station states
            "stations": {
                sid: {
                    "station_id": st.station_id,
                    "zone_id": st.zone_id,
                    "is_broken": st.is_broken,
                    "repair_end_time": st.repair_end_time,
                    "current_job": st.current_job,
                    "busy_until": st.busy_until,
                }
                for sid, st in self.stations.items()
            },
        }
        return state

    @classmethod
    def from_state(
        cls,
        state_dict: Dict[str, Any],
        heuristic_fn: Callable,
    ) -> "WarehouseSimulator":
        """Create a new simulator from a saved state (for fork evaluation).

        Creates a fresh SimPy environment initialized at saved_time,
        restores all job/station/queue data, and continues RNG from saved state.

        Parameters
        ----------
        state_dict : dict
            Output of save_state().
        heuristic_fn : Callable
            Dispatch function to use in the forked simulation.

        Returns
        -------
        WarehouseSimulator
            Ready to run from state_dict["env_time"] forward.
        """
        saved_time = state_dict["env_time"]

        # Reconstruct simulator with original config
        sim = cls(
            seed=state_dict["seed"],
            heuristic_fn=heuristic_fn,
            base_arrival_rate=state_dict["_base_arrival_rate"],
            breakdown_prob=state_dict["_breakdown_prob"],
            batch_arrival_size=state_dict["_batch_arrival_size"],
            lunch_penalty_factor=state_dict["_lunch_penalty_factor"],
            job_type_frequencies=state_dict["_job_type_frequencies"],
            due_date_tightness=state_dict["_due_date_tightness"],
            processing_time_scale=state_dict["_processing_time_scale"],
        )

        # Restore RNG from saved state (deterministic continuation)
        sim.rng.bit_generator.state = state_dict["rng_state"]

        # Restore job counter and metrics
        sim._job_counter = state_dict["_job_counter"]
        sim._max_queue = state_dict["_max_queue"]
        sim._lunch_active = state_dict["_lunch_active"]
        sim._zone_busy_time = dict(state_dict["_zone_busy_time"])
        sim._queue_snapshots = list(state_dict["_queue_snapshots"])

        # Restore jobs from serialized dicts
        sim.all_jobs = {
            jid: cls._deserialize_job(jdata)
            for jid, jdata in state_dict["all_jobs"].items()
        }
        sim.completed_jobs = [
            cls._deserialize_job(jdata)
            for jdata in state_dict["completed_jobs"]
        ]

        # Restore zone queues (using saved job IDs to reference restored jobs)
        job_by_id = sim.all_jobs
        for z, queue_job_ids in state_dict["zone_queues"].items():
            sim.zone_queues[int(z)] = [
                job_by_id[jid] for jid in queue_job_ids
                if jid in job_by_id
            ]

        # Restore station states
        for sid_str, st_data in state_dict["stations"].items():
            sid = int(sid_str)
            if sid in sim.stations:
                sim.stations[sid].is_broken = st_data["is_broken"]
                sim.stations[sid].repair_end_time = st_data["repair_end_time"]
                sim.stations[sid].current_job = st_data["current_job"]
                sim.stations[sid].busy_until = st_data["busy_until"]

        # Create a SimPy environment starting at saved_time
        sim.env = simpy.Environment(initial_time=saved_time)

        # Re-create SimPy resources for the new environment
        for sid in sim.stations:
            sim.station_resources[sid] = simpy.Resource(sim.env, capacity=1)

        # Re-create dispatcher trigger events for new environment
        for zone_id in sim.zones:
            sim.dispatcher_triggers[zone_id] = sim.env.event()

        # Re-register dispatchers and breakdown/arrival processes
        sim.env.process(sim._arrival_process())
        sim.env.process(sim._batch_arrival_process())
        sim.env.process(sim._priority_escalation_process())

        # Re-register lunch process correctly based on saved time
        if saved_time < 300.0:
            sim.env.process(sim._lunch_break_process())
        elif saved_time < 360.0:
            # Currently in lunch — restore the remaining lunch period
            remaining_lunch = 360.0 - saved_time

            def _remaining_lunch():
                yield sim.env.timeout(remaining_lunch)
                sim._lunch_active = False

            sim.env.process(_remaining_lunch())

        sim.env.process(sim._snapshot_process())

        for zone_id in sim.zones:
            sim.env.process(sim._zone_dispatcher(zone_id))

        for station in sim.stations.values():
            if station.is_broken:
                remaining_repair = max(0.1, station.repair_end_time - saved_time)

                def _resume_repair(st=station, t=remaining_repair):
                    yield sim.env.timeout(t)
                    st.is_broken = False
                    sim._trigger_dispatcher(st.zone_id)
                    # Continue with future breakdowns
                    while True:
                        ttf = float(sim.rng.exponential(1.0 / max(sim._breakdown_prob, 1e-9)))
                        yield sim.env.timeout(ttf)
                        st.is_broken = True
                        repair_time = float(sim.rng.exponential(18.0))
                        st.repair_end_time = sim.env.now + repair_time
                        yield sim.env.timeout(repair_time)
                        st.is_broken = False
                        sim._trigger_dispatcher(st.zone_id)

                sim.env.process(_resume_repair())
            else:
                sim.env.process(sim._station_breakdown_process(station))

        # Resume WAITING jobs in zone queues:
        # These need a full _process_job-like coroutine that waits for dispatch
        # then routes through remaining operations.
        for zone_id, queue in sim.zone_queues.items():
            for job in queue:
                job._dispatch_event = sim.env.event()
                sim.env.process(sim._resume_waiting_job(job, zone_id))
            if queue:
                sim._trigger_dispatcher(zone_id)

        # Resume PROCESSING jobs with correct remaining time:
        # At save time, op.start_time and op.actual_proc_time are set,
        # but op.end_time is still -1.0 (only set after timeout completes).
        # Remaining = (start_time + actual_proc_time) - saved_time
        for job in sim.all_jobs.values():
            if job.status == "processing" and job.current_op_idx < len(job.operations):
                op = job.operations[job.current_op_idx]
                if op.start_time >= 0 and op.actual_proc_time > 0:
                    expected_end = op.start_time + op.actual_proc_time
                    remaining = max(0.0, expected_end - saved_time)
                else:
                    remaining = 0.0
                sim.env.process(sim._resume_job(job, remaining))

        return sim

    def _resume_job(self, job: Job, remaining_time: float):
        """Continue processing a job that was in-progress at save_state time."""
        op_idx = job.current_op_idx
        op = job.operations[op_idx]

        yield self.env.timeout(remaining_time)
        op.end_time = self.env.now

        # Continue with remaining operations
        for next_op_idx in range(op_idx + 1, len(job.operations)):
            next_op = job.operations[next_op_idx]
            zone_id = next_op.zone_id

            self.zone_queues[zone_id].append(job)
            job.status = "waiting"
            job._dispatch_event = self.env.event()
            self._trigger_dispatcher(zone_id)
            yield job._dispatch_event

            station_id = self._pick_station(zone_id)
            next_op.station_id = station_id
            resource = self.station_resources[station_id]
            st = self.stations[station_id]
            st.current_job = job.job_id

            with resource.request() as req:
                yield req
                while st.is_broken:
                    wait_time = max(0.1, st.repair_end_time - self.env.now)
                    yield self.env.timeout(wait_time)

                job.status = "processing"
                job.current_op_idx = next_op_idx

                variability = float(self.rng.lognormal(0, 0.30))
                lunch_penalty = self._lunch_penalty_factor if self._lunch_active else 1.0
                actual_time = next_op.nominal_proc_time * variability * lunch_penalty

                next_op.actual_proc_time = actual_time
                next_op.start_time = self.env.now
                self._zone_busy_time[zone_id] = self._zone_busy_time.get(zone_id, 0.0) + actual_time

                yield self.env.timeout(actual_time)

                next_op.end_time = self.env.now
                st.busy_until = self.env.now
                st.current_job = None

            self._trigger_dispatcher(zone_id)

        job.status = "done"
        job.completion_time = self.env.now
        job.current_op_idx = len(job.operations)
        self.completed_jobs.append(job)

    def _resume_waiting_job(self, job: Job, current_zone_id: int):
        """Resume a job that was waiting in a zone queue at save_state time.

        This replaces the missing _process_job coroutine for waiting jobs
        restored via from_state(). The job waits for dispatch in its current
        zone, processes that operation, then routes through all remaining ops.
        """
        # Wait for dispatcher to select this job in the current zone
        yield job._dispatch_event

        # Process the current operation (the one the job was waiting for)
        op_idx = job.current_op_idx
        op = job.operations[op_idx]
        zone_id = current_zone_id

        station_id = self._pick_station(zone_id)
        op.station_id = station_id
        resource = self.station_resources[station_id]
        st = self.stations[station_id]
        st.current_job = job.job_id

        with resource.request() as req:
            yield req
            while st.is_broken:
                wait_time = max(0.1, st.repair_end_time - self.env.now)
                yield self.env.timeout(wait_time)

            job.status = "processing"
            job.current_op_idx = op_idx

            variability = float(self.rng.lognormal(0, 0.30))
            lunch_penalty = self._lunch_penalty_factor if self._lunch_active else 1.0
            actual_time = op.nominal_proc_time * variability * lunch_penalty

            op.actual_proc_time = actual_time
            op.start_time = self.env.now
            self._zone_busy_time[zone_id] = self._zone_busy_time.get(zone_id, 0.0) + actual_time

            yield self.env.timeout(actual_time)

            op.end_time = self.env.now
            st.busy_until = self.env.now
            st.current_job = None

        self._trigger_dispatcher(zone_id)

        # Continue with remaining operations (same as _resume_job)
        for next_op_idx in range(op_idx + 1, len(job.operations)):
            next_op = job.operations[next_op_idx]
            next_zone_id = next_op.zone_id

            self.zone_queues[next_zone_id].append(job)
            job.status = "waiting"
            job._dispatch_event = self.env.event()
            self._trigger_dispatcher(next_zone_id)
            yield job._dispatch_event

            station_id = self._pick_station(next_zone_id)
            next_op.station_id = station_id
            resource = self.station_resources[station_id]
            st = self.stations[station_id]
            st.current_job = job.job_id

            with resource.request() as req:
                yield req
                while st.is_broken:
                    wait_time = max(0.1, st.repair_end_time - self.env.now)
                    yield self.env.timeout(wait_time)

                job.status = "processing"
                job.current_op_idx = next_op_idx

                variability = float(self.rng.lognormal(0, 0.30))
                lunch_penalty = self._lunch_penalty_factor if self._lunch_active else 1.0
                actual_time = next_op.nominal_proc_time * variability * lunch_penalty

                next_op.actual_proc_time = actual_time
                next_op.start_time = self.env.now
                self._zone_busy_time[next_zone_id] = self._zone_busy_time.get(next_zone_id, 0.0) + actual_time

                yield self.env.timeout(actual_time)

                next_op.end_time = self.env.now
                st.busy_until = self.env.now
                st.current_job = None

            self._trigger_dispatcher(next_zone_id)

        job.status = "done"
        job.completion_time = self.env.now
        job.current_op_idx = len(job.operations)
        self.completed_jobs.append(job)

    # ------------------------------------------------------------------
    # NEW in DAHS_2: Partial metrics for fork evaluation windows
    # ------------------------------------------------------------------

    def get_partial_metrics(self, since_time: float) -> SimulationMetrics:
        """Compute metrics only for jobs completed between since_time and env.now.

        Used in the 20-minute fork evaluation window during data generation.

        Parameters
        ----------
        since_time : float
            Start of evaluation window (simulation time).

        Returns
        -------
        SimulationMetrics
            Metrics computed only over jobs completed in [since_time, now].
        """
        now = self.env.now
        window_jobs = [
            j for j in self.completed_jobs
            if j.completion_time >= since_time
        ]

        if not window_jobs:
            return SimulationMetrics(
                makespan=now,
                zone_utilization={z: 0.0 for z in self.zones},
            )

        n = len(window_jobs)
        total_tardiness = sum(max(0.0, j.completion_time - j.due_date) for j in window_jobs)
        n_late = sum(1 for j in window_jobs if j.completion_time > j.due_date)
        sla_breach_rate = n_late / n
        avg_cycle_time = float(np.mean([j.completion_time - j.arrival_time for j in window_jobs]))
        duration = max(now - since_time, 1.0)
        throughput = (n / duration) * 60.0

        zone_utilization = {
            z: min(1.0, self._zone_busy_time.get(z, 0.0) / max(1.0, now * self.zones[z].num_stations))
            for z in self.zones
        }

        return SimulationMetrics(
            makespan=max(j.completion_time for j in window_jobs),
            total_tardiness=total_tardiness,
            sla_breach_rate=sla_breach_rate,
            avg_cycle_time=avg_cycle_time,
            zone_utilization=zone_utilization,
            throughput=throughput,
            queue_max=self._max_queue,
            completed_jobs=n,
            total_jobs=len(self.all_jobs),
        )
