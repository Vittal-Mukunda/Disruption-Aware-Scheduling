"""Tests for the four BatchwiseSelector edge-case guardrails.

Guardrails:
  - Trivial load (< TRIVIAL_LOAD jobs)         → FIFO
  - Overload (avg utilization > OVERLOAD_THRESHOLD) → ATC
  - Out-of-distribution (>10% beyond range)    → ATC
  - Starvation (job waiting > STARVATION_LIMIT)→ force-promote in dispatch
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import List

import numpy as np

from src.features import FeatureExtractor, SCENARIO_FEATURE_NAMES
from src.hybrid_scheduler import BatchwiseSelector

N_FEATS = len(SCENARIO_FEATURE_NAMES)


class _StubModel:
    """Always votes for WSPT (idx 4) — so any time we see ATC/FIFO selected,
    a guardrail must have fired."""
    def predict_proba(self, X):
        proba = np.zeros((1, 6))
        proba[0, 4] = 1.0
        return proba


@dataclass
class _Op:
    zone_id: int = 0
    nominal_proc_time: float = 5.0


@dataclass
class _MiniJob:
    job_id: int
    job_type: str = "C"
    arrival_time: float = 0.0
    due_date: float = 100.0
    operations: list = field(default_factory=lambda: [_Op()])
    current_op_idx: int = 0
    status: str = "waiting"
    completion_time: float = -1.0

    @property
    def is_complete(self):
        return False

    def remaining_proc_time(self):
        return 5.0


def _state(n_orders=50, util=0.5, n_broken=0):
    waiting = [_MiniJob(job_id=i, due_date=100.0 + 50 * i) for i in range(min(n_orders, 4))]
    return {
        "current_time": 10.0,
        "n_orders_in_system": n_orders,
        "queue_sizes": {z: max(1, n_orders // 8) for z in range(8)},
        "zone_utilization": {z: util for z in range(8)},
        "n_broken_stations": n_broken,
        "lunch_active": False,
        "surge_multiplier": 1.0,
        "completed_so_far": 0,
        "waiting_jobs": waiting,
        "completed_jobs": [],
        "all_jobs": {j.job_id: j for j in waiting},
    }


def _wide_ranges():
    """Permissive ranges so OOD does NOT fire on baseline state. Tests that
    target OOD override specific entries."""
    return {n: (-1e6, 1e6) for n in SCENARIO_FEATURE_NAMES}


def _selector_with_ranges(ranges=None):
    fe = FeatureExtractor()
    fe.set_feature_ranges(ranges if ranges is not None else _wide_ranges())
    return BatchwiseSelector(
        model=_StubModel(),
        feature_extractor=fe,
        feature_importances=np.ones(N_FEATS) / N_FEATS,
        feature_names=list(SCENARIO_FEATURE_NAMES),
    )


def test_trivial_load_forces_fifo():
    sel = _selector_with_ranges()
    sel.update_state(_state(n_orders=3, util=0.4))
    sel._reevaluate(now=0.0)
    assert sel._current_heuristic == "fifo"
    last = sel.switching_log.entries[-1]
    assert last["reason"].startswith("guardrail")


def test_overload_locks_to_atc():
    sel = _selector_with_ranges()
    sel.update_state(_state(n_orders=80, util=0.95))
    sel._reevaluate(now=0.0)
    assert sel._current_heuristic == "atc"
    last = sel.switching_log.entries[-1]
    assert last["reason"].startswith("guardrail")


def test_ood_falls_back_to_atc():
    # Ranges where util is in [0.10, 0.70] but state has util=0.85 (>10% over).
    ranges = _wide_ranges()
    ranges["zone_utilization_avg"] = (0.10, 0.70)
    sel = _selector_with_ranges(ranges)
    sel.update_state(_state(n_orders=50, util=0.85))
    sel._reevaluate(now=0.0)
    # Trivial load false (50 > 5), overload false (<0.92), so OOD must fire.
    assert sel._current_heuristic == "atc"
    last = sel.switching_log.entries[-1]
    assert last["reason"].startswith("guardrail")


def test_no_guardrail_uses_ml_choice():
    sel = _selector_with_ranges()
    sel.update_state(_state(n_orders=30, util=0.5))
    sel._reevaluate(now=0.0)
    assert sel._current_heuristic == "wspt"  # the stub's argmax
    last = sel.switching_log.entries[-1]
    assert last["reason"] == "ml_decision"


# ---------------------------------------------------------------------------
# Starvation prevention
# ---------------------------------------------------------------------------

@dataclass
class _FakeJob:
    job_id: int
    arrival_time: float
    job_type: str = "C"
    due_date: float = 9999.0
    operations: list = field(default_factory=list)
    current_op_idx: int = 0
    status: str = "waiting"

    @property
    def is_complete(self):
        return False

    def remaining_proc_time(self):
        return 5.0


def test_starvation_promotes_old_jobs_to_front():
    sel = _selector_with_ranges()
    sel._current_heuristic = "fifo"  # simple ordering for the assertion
    now = 200.0
    young = _FakeJob(job_id=1, arrival_time=now - 10.0)
    old = _FakeJob(job_id=2, arrival_time=now - 90.0)
    middle = _FakeJob(job_id=3, arrival_time=now - 30.0)
    ordered = sel.dispatch([young, middle, old], current_time=now, zone_id=0)
    assert ordered[0].job_id == 2
    rest_ids = [j.job_id for j in ordered[1:]]
    assert rest_ids == [3, 1]
