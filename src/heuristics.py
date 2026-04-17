"""
heuristics.py — Dispatch Heuristics for Warehouse Job Shop Scheduling

Provides six industry-standard dispatch rules plus stub wrappers for
ML-driven hybrid dispatch (filled in by hybrid_scheduler.py).

Academic References
-------------------
- FIFO (First-In First-Out):
    Standard queue discipline; no specific citation needed.

- Priority-EDD (Earliest Due Date):
    Jackson, J.R. (1955). Scheduling a production line to minimize
    maximum tardiness. Management Research Project Report 43, UCLA.

- Critical Ratio (CR):
    Conway, R.W., Maxwell, W.L., & Miller, L.W. (1967). Theory of
    Scheduling. Addison-Wesley.
    Also: Pinedo, M.L. (2016). Scheduling: Theory, Algorithms, and
    Systems. Springer (5th ed.). doi:10.1007/978-3-319-26580-3.

- ATC (Apparent Tardiness Cost):
    Vepsalainen, A.P.J. & Morton, T.E. (1987). Priority rules for job
    shops with weighted tardiness costs. Management Science, 33(8),
    1035-1047. doi:10.1287/mnsc.33.8.1035.

- WSPT (Weighted Shortest Processing Time):
    Smith, W.E. (1956). Various optimizers for single-stage production.
    Naval Research Logistics Quarterly, 3(1-2), 59-66.
    doi:10.1002/nav.3800030106. [Optimal for weighted completion time.]

- Slack (Minimum Slack):
    Pinedo, M.L. (2016). Scheduling: Theory, Algorithms, and Systems.
    Springer (5th ed.). doi:10.1007/978-3-319-26580-3.

Hyper-heuristic framework (ML selection over these 6 rules):
    Burke, E.K. et al. (2013). Hyper-heuristics: A survey of the state
    of the art. JORS, 64(12), 1695-1724. doi:10.1057/jors.2013.71.
    Cowling, P., Kendall, G., & Soubeiga, E. (2001). A hyperheuristic
    approach to scheduling a sales summit. PATAT 2000, LNCS 2079.
"""

from __future__ import annotations

import math
import logging
from typing import Any, Dict, List

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
    """Return numeric priority class for a job type string."""
    return _PRIORITY_CLASS.get(job_type, 1)


def compute_critical_ratio(job: Any, current_time: float) -> float:
    """Compute the Critical Ratio for a job.

    CR = time_remaining_to_due / remaining_processing_time

    A CR < 1 means the job is behind schedule. Negative CR means already late.
    CR = 999.0 is returned when remaining_proc = 0 (done job — large finite value).
    """
    time_to_due = job.due_date - current_time
    remaining_proc = job.remaining_proc_time()

    if remaining_proc <= 0:
        return 999.0  # done job — large finite value, sorts last in ascending CR dispatch
    if time_to_due <= 0:
        return time_to_due / remaining_proc  # negative CR = already late

    return time_to_due / remaining_proc


# ---------------------------------------------------------------------------
# Baseline heuristics
# ---------------------------------------------------------------------------

# Ref: Standard queue discipline — no specific academic citation required.
def fifo_dispatch(jobs: List[Any], current_time: float, zone_id: int) -> List[Any]:
    """First-In First-Out dispatch: sort by arrival_time ascending."""
    return sorted(jobs, key=lambda j: j.arrival_time)


# Ref: Jackson (1955), "Scheduling a production line to minimize maximum tardiness",
#      Management Research Project Report 43, UCLA.
# Extended with priority classes for multi-tier fulfillment environments.
def priority_edd_dispatch(jobs: List[Any], current_time: float, zone_id: int) -> List[Any]:
    """Priority-EDD dispatch: sort by (priority_class DESC, due_date ASC)."""
    return sorted(
        jobs,
        key=lambda j: (-get_priority_class(j.job_type), j.due_date),
    )


# Ref: Conway et al. (1967), "Theory of Scheduling", Addison-Wesley.
# Also: Pinedo (2016), "Scheduling: Theory, Algorithms, and Systems", Springer 5th ed.
def critical_ratio_dispatch(jobs: List[Any], current_time: float, zone_id: int) -> List[Any]:
    """Critical Ratio dispatch: sort by CR ascending (most urgent first)."""
    return sorted(jobs, key=lambda j: compute_critical_ratio(j, current_time))


# Priority weight mapping (mirrors simulator definitions)
_PRIORITY_WEIGHT: Dict[str, float] = {
    "A": 2.0, "B": 1.5, "C": 1.0, "D": 0.8, "E": 3.0,
}


# Ref: Vepsalainen, A.P.J. & Morton, T.E. (1987). Priority rules for job shops
#      with weighted tardiness costs. Management Science, 33(8), 1035-1047.
#      doi:10.1287/mnsc.33.8.1035
def atc_dispatch(jobs: List[Any], current_time: float, zone_id: int) -> List[Any]:
    """Apparent Tardiness Cost (ATC) dispatch.

    ATC_i = (w_i / p_i) * exp(-max(0, d_i - p_i - t) / (K * p_avg))

    where K is the look-ahead parameter (K=2.0), p_avg is the average
    remaining processing time across waiting jobs.
    Higher ATC score → dispatch sooner.

    Reference: Vepsalainen & Morton (1987), Management Science 33(8):1035-1047.
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


# Ref: Smith, W.E. (1956). Various optimizers for single-stage production.
#      Naval Research Logistics Quarterly, 3(1-2), 59-66.
#      doi:10.1002/nav.3800030106
#      [Proven optimal for minimizing weighted completion time on a single machine.]
def wspt_dispatch(jobs: List[Any], current_time: float, zone_id: int) -> List[Any]:
    """Weighted Shortest Processing Time (WSPT) dispatch.

    Sort by w_i / p_i descending — prioritizes jobs with high
    priority-to-processing-time ratio.

    Reference: Smith (1956), Naval Research Logistics Quarterly 3(1-2):59-66.
    """
    def _wspt_score(job: Any) -> float:
        w = _PRIORITY_WEIGHT.get(job.job_type, 1.0)
        p = max(job.remaining_proc_time(), 0.001)
        return w / p

    return sorted(jobs, key=_wspt_score, reverse=True)


# Ref: Pinedo, M.L. (2016). Scheduling: Theory, Algorithms, and Systems.
#      Springer, 5th edition. doi:10.1007/978-3-319-26580-3.
def slack_dispatch(jobs: List[Any], current_time: float, zone_id: int) -> List[Any]:
    """Slack-based dispatch: sort by remaining slack ascending.

    Slack = (due_date - current_time) - remaining_proc_time
    Lower slack → less margin → dispatch sooner.

    Reference: Pinedo (2016), Scheduling: Theory, Algorithms, and Systems.
    """
    def _slack(job: Any) -> float:
        return (job.due_date - current_time) - job.remaining_proc_time()

    return sorted(jobs, key=_slack)


# Dispatch map for convenience
DISPATCH_MAP = {
    "fifo": fifo_dispatch,
    "priority_edd": priority_edd_dispatch,
    "critical_ratio": critical_ratio_dispatch,
    "atc": atc_dispatch,
    "wspt": wspt_dispatch,
    "slack": slack_dispatch,
}

ALL_HEURISTICS = list(DISPATCH_MAP.keys())
HEURISTIC_LABELS = ["FIFO", "Priority-EDD", "Critical-Ratio", "ATC", "WSPT", "Slack"]
