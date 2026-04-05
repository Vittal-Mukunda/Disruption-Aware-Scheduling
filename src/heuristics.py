"""
heuristics.py — Dispatch Heuristics for Warehouse Job Shop Scheduling

Provides six industry-standard baselines plus stub wrappers for
ML-driven hybrid dispatch (filled in by hybrid_scheduler.py).

Baselines:
  0 — FIFO (First-In First-Out)
  1 — Priority-EDD (Earliest Due Date with priority classes)
  2 — Critical Ratio (CR)
  3 — ATC (Apparent Tardiness Cost)
  4 — WSPT (Weighted Shortest Processing Time)
  5 — Slack-based dispatch
"""

from __future__ import annotations

import math
import logging
from typing import Any, Callable, Dict, List, Optional

logger = logging.getLogger(__name__)

# Priority class mapping (higher number = higher priority in dispatch)
_PRIORITY_CLASS: Dict[str, int] = {
    "E": 4,  # Express — highest
    "A": 3,
    "C": 2,
    "B": 1,
    "D": 0,  # Deferred — lowest
}


def get_priority_class(job_type: str) -> int:
    """Return numeric priority class for a job type string.

    Parameters
    ----------
    job_type : str
        One of "A", "B", "C", "D", "E".

    Returns
    -------
    int
        Priority class (higher = dispatch sooner in Priority-EDD).
    """
    return _PRIORITY_CLASS.get(job_type, 1)


def compute_critical_ratio(job: Any, current_time: float) -> float:
    """Compute the Critical Ratio for a job.

    CR = time_remaining_to_due / remaining_processing_time

    A CR < 1 means the job is already behind schedule.
    CR = 0 is returned when no time is remaining (avoids division by zero).

    Parameters
    ----------
    job : Job
        The job to evaluate.
    current_time : float
        Current simulation clock (minutes).

    Returns
    -------
    float
        Critical ratio (lower → more urgent).
    """
    time_to_due = job.due_date - current_time
    remaining_proc = job.remaining_proc_time()

    if remaining_proc <= 0:
        return 0.0  # edge case: job is essentially done — dispatch immediately
    if time_to_due <= 0:
        return 0.0  # already late — maximum urgency

    return time_to_due / remaining_proc


# ---------------------------------------------------------------------------
# Baseline heuristics
# ---------------------------------------------------------------------------

def fifo_dispatch(jobs: List[Any], current_time: float, zone_id: int) -> List[Any]:
    """First-In First-Out dispatch: sort by arrival_time ascending.

    Parameters
    ----------
    jobs : List[Job]
        Jobs currently waiting in the zone queue.
    current_time : float
        Current simulation clock (unused, present for API consistency).
    zone_id : int
        Zone identifier (unused, present for API consistency).

    Returns
    -------
    List[Job]
        Jobs sorted FIFO order (index 0 = next to dispatch).
    """
    return sorted(jobs, key=lambda j: j.arrival_time)


def priority_edd_dispatch(jobs: List[Any], current_time: float, zone_id: int) -> List[Any]:
    """Priority-EDD dispatch: sort by (priority_class DESC, due_date ASC).

    Higher priority class jobs are dispatched first; ties broken by
    earliest due date.

    Parameters
    ----------
    jobs : List[Job]
        Jobs currently waiting in the zone queue.
    current_time : float
        Current simulation clock (unused).
    zone_id : int
        Zone identifier (unused).

    Returns
    -------
    List[Job]
        Jobs in Priority-EDD order.
    """
    return sorted(
        jobs,
        key=lambda j: (-get_priority_class(j.job_type), j.due_date),
    )


def critical_ratio_dispatch(jobs: List[Any], current_time: float, zone_id: int) -> List[Any]:
    """Critical Ratio dispatch: sort by CR ascending (most urgent first).

    CR = (time remaining to due date) / (remaining processing time).
    Lower CR → dispatch sooner.

    Parameters
    ----------
    jobs : List[Job]
        Jobs currently waiting in the zone queue.
    current_time : float
        Current simulation clock.
    zone_id : int
        Zone identifier (unused).

    Returns
    -------
    List[Job]
        Jobs sorted by Critical Ratio ascending.
    """
    return sorted(jobs, key=lambda j: compute_critical_ratio(j, current_time))


# Priority weight mapping (mirrors simulator definitions)
_PRIORITY_WEIGHT: Dict[str, float] = {
    "A": 2.0, "B": 1.5, "C": 1.0, "D": 0.8, "E": 3.0,
}


def atc_dispatch(jobs: List[Any], current_time: float, zone_id: int) -> List[Any]:
    """Apparent Tardiness Cost (ATC) dispatch.

    ATC combines weighted shortest processing time with due-date urgency
    through an exponential look-ahead kernel:

        ATC_i = (w_i / p_i) * exp(-max(0, d_i - p_i - t) / (K * p_avg))

    where K is the look-ahead parameter (K=2.0), p_avg is the average
    remaining processing time across waiting jobs.

    Higher ATC score → dispatch sooner.

    References
    ----------
    Vepsalainen & Morton (1987). "Priority rules for job shops with
    weighted tardiness costs." Management Science, 33(8), 1035-1047.
    """
    if not jobs:
        return jobs

    p_vals = [max(j.remaining_proc_time(), 0.001) for j in jobs]
    p_avg = sum(p_vals) / len(p_vals)
    K = 2.0  # look-ahead parameter

    def _atc_score(job: Any) -> float:
        w = _PRIORITY_WEIGHT.get(job.job_type, 1.0)
        p = max(job.remaining_proc_time(), 0.001)
        slack = job.due_date - p - current_time
        urgency = math.exp(-max(0.0, slack) / max(K * p_avg, 0.001))
        return (w / p) * urgency

    return sorted(jobs, key=_atc_score, reverse=True)


def wspt_dispatch(jobs: List[Any], current_time: float, zone_id: int) -> List[Any]:
    """Weighted Shortest Processing Time (WSPT) dispatch.

    Sort by w_i / p_i descending — prioritizes jobs with high
    priority-to-processing-time ratio. Optimal for minimising total
    weighted completion time on a single machine.

    References
    ----------
    Smith (1956). "Various optimizers for single-stage production."
    Naval Research Logistics Quarterly, 3(1-2), 59-66.
    """
    def _wspt_score(job: Any) -> float:
        w = _PRIORITY_WEIGHT.get(job.job_type, 1.0)
        p = max(job.remaining_proc_time(), 0.001)
        return w / p

    return sorted(jobs, key=_wspt_score, reverse=True)


def slack_dispatch(jobs: List[Any], current_time: float, zone_id: int) -> List[Any]:
    """Slack-based dispatch: sort by remaining slack ascending.

    Slack = (due_date - current_time) - remaining_proc_time

    Lower slack → less margin → dispatch sooner. Jobs with negative
    slack are already behind schedule.

    References
    ----------
    Baker & Trietsch (2009). "Principles of Sequencing and Scheduling."
    Wiley.
    """
    def _slack(job: Any) -> float:
        return (job.due_date - current_time) - job.remaining_proc_time()

    return sorted(jobs, key=_slack)


# ---------------------------------------------------------------------------
# Hybrid dispatch wrappers (implemented fully in hybrid_scheduler.py)
# ---------------------------------------------------------------------------

def hybrid_selector_dispatch(
    jobs: List[Any],
    current_time: float,
    zone_id: int,
    model: Any = None,
    feature_extractor: Any = None,
    sim_state: Optional[Dict[str, Any]] = None,
) -> List[Any]:
    """ML Selector hybrid dispatch.

    Uses a trained classifier to pick the best base heuristic for the
    current system state, then applies that heuristic.

    Parameters
    ----------
    jobs : List[Job]
        Jobs in the zone queue.
    current_time : float
        Simulation clock.
    zone_id : int
        Zone identifier.
    model : sklearn/XGB classifier
        Trained heuristic-selector model.
    feature_extractor : FeatureExtractor
        Extracts scenario-level features from sim_state.
    sim_state : dict, optional
        Current system state snapshot.

    Returns
    -------
    List[Job]
        Ordered jobs according to whichever heuristic was selected.
    """
    if model is None or feature_extractor is None or sim_state is None:
        logger.debug("hybrid_selector_dispatch: missing model/state, falling back to FIFO")
        return fifo_dispatch(jobs, current_time, zone_id)

    try:
        features = feature_extractor.extract_scenario_features(sim_state).reshape(1, -1)
        heuristic_idx = int(model.predict(features)[0])
        _dispatch_map = {0: fifo_dispatch, 1: priority_edd_dispatch, 2: critical_ratio_dispatch}
        chosen = _dispatch_map.get(heuristic_idx, fifo_dispatch)
        return chosen(jobs, current_time, zone_id)
    except Exception as exc:
        logger.warning("hybrid_selector_dispatch error: %s — falling back to FIFO", exc)
        return fifo_dispatch(jobs, current_time, zone_id)


def hybrid_priority_dispatch(
    jobs: List[Any],
    current_time: float,
    zone_id: int,
    model: Any = None,
    feature_extractor: Any = None,
    sim_state: Optional[Dict[str, Any]] = None,
) -> List[Any]:
    """ML Priority hybrid dispatch.

    Uses a trained GBR regressor to predict a continuous priority score
    for each job, then dispatches in descending score order.

    Parameters
    ----------
    jobs : List[Job]
        Jobs in the zone queue.
    current_time : float
        Simulation clock.
    zone_id : int
        Zone identifier.
    model : sklearn GBR
        Trained priority predictor model.
    feature_extractor : FeatureExtractor
        Extracts job-level features for each waiting job.
    sim_state : dict, optional
        Current system state snapshot.

    Returns
    -------
    List[Job]
        Jobs ordered by predicted priority descending.
    """
    if model is None or feature_extractor is None or sim_state is None:
        logger.debug("hybrid_priority_dispatch: missing model/state, falling back to FIFO")
        return fifo_dispatch(jobs, current_time, zone_id)

    try:
        scores = []
        for job in jobs:
            feats = feature_extractor.extract_job_features(job, sim_state).reshape(1, -1)
            score = float(model.predict(feats)[0])
            scores.append((score, job))
        scores.sort(key=lambda x: x[0], reverse=True)
        return [job for _, job in scores]
    except Exception as exc:
        logger.warning("hybrid_priority_dispatch error: %s — falling back to FIFO", exc)
        return fifo_dispatch(jobs, current_time, zone_id)
