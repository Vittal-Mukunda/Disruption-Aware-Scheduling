"""
features.py — Feature Extraction for Hybrid Warehouse Scheduler

Implements a stateful FeatureExtractor that computes 29 features split into:
  - 22 scenario-level features describing system-wide state
       (including 4 disruption-aware features for adaptive scheduling)
  -  7 job-level features for per-job priority prediction
"""

from __future__ import annotations

import logging
import math
from collections import deque
from typing import Any, Dict, List

import numpy as np

logger = logging.getLogger(__name__)

# -------------------------------------------------------------------------
# Feature name lists (used for DataFrame column labeling)
# -------------------------------------------------------------------------

SCENARIO_FEATURE_NAMES: List[str] = [
    "n_orders_in_system",
    "n_express_orders_pct",
    "avg_due_date_tightness",
    "fraction_already_late",
    "zone_utilization_avg",
    "zone_utilization_std",
    "bottleneck_zone",
    "avg_remaining_proc_time",
    "std_remaining_proc_time",
    "throughput_last_30min",
    "breakdown_flag",
    "n_broken_stations",
    "lunch_break_flag",
    "surge_multiplier",
    "batch_pending_flag",
    "avg_priority_weight",
    "max_tardiness_so_far",
    "sla_breach_rate_current",
    # Disruption-aware features (novel contribution)
    "disruption_intensity",
    "queue_imbalance",
    "job_mix_entropy",
    "time_pressure_ratio",
]

JOB_FEATURE_NAMES: List[str] = [
    "job_type_encoded",
    "proc_time_next_station",
    "remaining_proc_time",
    "time_to_due",
    "time_in_system",
    "critical_ratio",
    "station_queue_at_next",
]

# Job type → integer encoding
_JOB_TYPE_ENC: Dict[str, int] = {"A": 0, "B": 1, "C": 2, "D": 3, "E": 4}

# Job type → priority weight (mirrors simulator definitions)
_JOB_PRIORITY_WEIGHT: Dict[str, float] = {
    "A": 2.0, "B": 1.5, "C": 1.0, "D": 0.8, "E": 3.0
}


class FeatureExtractor:
    """Stateful extractor that maintains running statistics across events.

    Call ``update(event_type, data)`` as events occur during simulation,
    then call ``extract_scenario_features`` or ``extract_job_features``
    to obtain the feature vectors.
    """

    # Window size for throughput tracking (minutes)
    THROUGHPUT_WINDOW = 30.0

    def __init__(self) -> None:
        # Circular buffer of (timestamp, job_id) for throughput window
        self._completion_times: deque = deque()
        # Batch pending flag set externally when a truck batch is imminent
        self.batch_pending: bool = False

    # ------------------------------------------------------------------
    # Event update
    # ------------------------------------------------------------------

    def update(self, event_type: str, data: Dict[str, Any]) -> None:
        """Update running statistics on job events.

        Parameters
        ----------
        event_type : str
            One of "job_complete", "job_arrival", "breakdown".
        data : dict
            Event-specific payload.
        """
        if event_type == "job_complete":
            self._completion_times.append(data.get("timestamp", 0.0))

    # ------------------------------------------------------------------
    # Scenario-level features (18)
    # ------------------------------------------------------------------

    def extract_scenario_features(self, sim_state: Dict[str, Any]) -> np.ndarray:
        """Extract 22 scenario-level features from a system state snapshot.

        Parameters
        ----------
        sim_state : dict
            Output of ``WarehouseSimulator.get_state_snapshot()``.

        Returns
        -------
        np.ndarray of shape (22,)
        """
        now: float = sim_state.get("current_time", 0.0)
        waiting_jobs: List[Any] = sim_state.get("waiting_jobs", [])
        completed_jobs: List[Any] = sim_state.get("completed_jobs", [])
        queue_sizes: Dict[int, int] = sim_state.get("queue_sizes", {})
        zone_util: Dict[int, float] = sim_state.get("zone_utilization", {})
        n_broken: int = sim_state.get("n_broken_stations", 0)
        lunch: bool = sim_state.get("lunch_active", False)
        surge: float = sim_state.get("surge_multiplier", 1.0)

        # F1: n_orders_in_system
        n_in_system = float(sim_state.get("n_orders_in_system", 0))

        # F2: n_express_orders_pct
        n_express = sum(1 for j in waiting_jobs if j.job_type == "E")
        n_express_pct = n_express / max(1.0, n_in_system)

        # F3: avg_due_date_tightness = avg(due_date - now) for waiting jobs
        if waiting_jobs:
            tightness = np.mean([j.due_date - now for j in waiting_jobs])
        else:
            tightness = 999.0

        # F4: fraction_already_late
        if waiting_jobs:
            frac_late = sum(1 for j in waiting_jobs if j.due_date < now) / len(waiting_jobs)
        else:
            frac_late = 0.0

        # F5/F6: zone utilization avg and std
        util_vals = list(zone_util.values())
        util_avg = float(np.mean(util_vals)) if util_vals else 0.0
        util_std = float(np.std(util_vals)) if util_vals else 0.0

        # F7: bottleneck_zone (zone with highest utilization, encoded as zone_id)
        if zone_util:
            bottleneck = float(max(zone_util, key=zone_util.get))
        else:
            bottleneck = 0.0

        # F8/F9: avg and std remaining proc time for waiting jobs
        rem_times = [j.remaining_proc_time() for j in waiting_jobs]
        avg_rem = float(np.mean(rem_times)) if rem_times else 0.0
        std_rem = float(np.std(rem_times)) if rem_times else 0.0

        # F10: throughput in last 30 min (completions per minute)
        cutoff = now - self.THROUGHPUT_WINDOW
        # prune old entries
        while self._completion_times and self._completion_times[0] < cutoff:
            self._completion_times.popleft()
        throughput_30 = len(self._completion_times) / self.THROUGHPUT_WINDOW

        # F11: breakdown_flag
        breakdown_flag = 1.0 if n_broken > 0 else 0.0

        # F12: n_broken_stations
        n_broken_f = float(n_broken)

        # F13: lunch_break_flag
        lunch_flag = 1.0 if lunch else 0.0

        # F14: surge_multiplier
        surge_f = float(surge)

        # F15: batch_pending_flag
        batch_flag = 1.0 if self.batch_pending else 0.0

        # F16: avg_priority_weight
        if waiting_jobs:
            avg_prio_w = float(np.mean([
                _JOB_PRIORITY_WEIGHT.get(j.job_type, 1.0) for j in waiting_jobs
            ]))
        else:
            avg_prio_w = 1.0

        # F17: max_tardiness_so_far
        if completed_jobs:
            max_tard = float(max(
                max(0.0, j.completion_time - j.due_date) for j in completed_jobs
            ))
        else:
            max_tard = 0.0

        # F18: sla_breach_rate_current
        if completed_jobs:
            breach_rate = sum(
                1 for j in completed_jobs if j.completion_time > j.due_date
            ) / len(completed_jobs)
        else:
            breach_rate = 0.0

        # F19: disruption_intensity — composite disruption score [0, 1]
        # Combines breakdowns, lunch penalty, and surge deviation into a single
        # indicator of how disrupted the current system state is.
        breakdown_severity = min(1.0, n_broken / 5.0)  # 5+ broken stations = max
        lunch_severity = 1.0 if lunch else 0.0
        surge_deviation = abs(surge - 1.0)  # deviation from normal rate
        disruption_intensity = 0.5 * breakdown_severity + 0.25 * lunch_severity + 0.25 * surge_deviation

        # F20: queue_imbalance — coefficient of variation of queue sizes
        q_vals = list(queue_sizes.values())
        if q_vals and np.mean(q_vals) > 0:
            queue_imbalance = float(np.std(q_vals) / np.mean(q_vals))
        else:
            queue_imbalance = 0.0

        # F21: job_mix_entropy — Shannon entropy of job type distribution in queue
        if waiting_jobs:
            type_counts: Dict[str, int] = {}
            for j in waiting_jobs:
                type_counts[j.job_type] = type_counts.get(j.job_type, 0) + 1
            total_w = len(waiting_jobs)
            job_mix_entropy = 0.0
            for cnt in type_counts.values():
                p = cnt / total_w
                if p > 0:
                    job_mix_entropy -= p * math.log2(p)
        else:
            job_mix_entropy = 0.0

        # F22: time_pressure_ratio — fraction of waiting jobs with CR < 1
        if waiting_jobs:
            n_under_pressure = 0
            for j in waiting_jobs:
                rem = j.remaining_proc_time()
                ttd = j.due_date - now
                cr = ttd / max(rem, 0.001) if rem > 0 else 0.0
                if cr < 1.0:
                    n_under_pressure += 1
            time_pressure_ratio = n_under_pressure / len(waiting_jobs)
        else:
            time_pressure_ratio = 0.0

        features = np.array([
            n_in_system,      # F1
            n_express_pct,    # F2
            tightness,        # F3
            frac_late,        # F4
            util_avg,         # F5
            util_std,         # F6
            bottleneck,       # F7
            avg_rem,          # F8
            std_rem,          # F9
            throughput_30,    # F10
            breakdown_flag,   # F11
            n_broken_f,       # F12
            lunch_flag,       # F13
            surge_f,          # F14
            batch_flag,       # F15
            avg_prio_w,       # F16
            max_tard,         # F17
            breach_rate,      # F18
            disruption_intensity,   # F19 (novel)
            queue_imbalance,        # F20 (novel)
            job_mix_entropy,        # F21 (novel)
            time_pressure_ratio,    # F22 (novel)
        ], dtype=np.float32)

        return features

    # ------------------------------------------------------------------
    # Job-level features (7)
    # ------------------------------------------------------------------

    def extract_job_features(self, job: Any, sim_state: Dict[str, Any]) -> np.ndarray:
        """Extract 7 job-level features for priority prediction.

        Parameters
        ----------
        job : Job
            The job to featurize.
        sim_state : dict
            Current system state snapshot.

        Returns
        -------
        np.ndarray of shape (7,)
        """
        now: float = sim_state.get("current_time", 0.0)
        queue_sizes: Dict[int, int] = sim_state.get("queue_sizes", {})

        # F19: job_type_encoded
        jt_enc = float(_JOB_TYPE_ENC.get(job.job_type, 0))

        # F20: proc_time_next_station
        if not job.is_complete:
            next_op = job.operations[job.current_op_idx]
            proc_next = float(next_op.nominal_proc_time)
        else:
            proc_next = 0.0

        # F21: remaining_proc_time (sum of remaining operations)
        rem_proc = float(job.remaining_proc_time())

        # F22: time_to_due
        time_to_due = float(job.due_date - now)

        # F23: time_in_system
        time_in_sys = float(now - job.arrival_time)

        # F24: critical_ratio
        if rem_proc > 0:
            cr = max(0.0, time_to_due / rem_proc)
        else:
            cr = 0.0

        # F25: station_queue_at_next (queue length at next zone)
        if not job.is_complete:
            next_zone = job.operations[job.current_op_idx].zone_id
            queue_at_next = float(queue_sizes.get(next_zone, 0))
        else:
            queue_at_next = 0.0

        features = np.array([
            jt_enc,
            proc_next,
            rem_proc,
            time_to_due,
            time_in_sys,
            cr,
            queue_at_next,
        ], dtype=np.float32)

        return features

    # ------------------------------------------------------------------
    # Feature names
    # ------------------------------------------------------------------

    def get_feature_names(self, level: str = "scenario") -> List[str]:
        """Return the ordered list of feature names.

        Parameters
        ----------
        level : str
            "scenario" for 18 scenario features, "job" for 7 job features,
            "all" for all 25 concatenated.

        Returns
        -------
        List[str]
        """
        if level == "scenario":
            return SCENARIO_FEATURE_NAMES
        elif level == "job":
            return JOB_FEATURE_NAMES
        elif level == "all":
            return SCENARIO_FEATURE_NAMES + JOB_FEATURE_NAMES
        else:
            raise ValueError(f"Unknown level: {level!r}. Use 'scenario', 'job', or 'all'.")
