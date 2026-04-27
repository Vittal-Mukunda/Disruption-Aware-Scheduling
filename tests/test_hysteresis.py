"""Hysteresis tests for BatchwiseSelector.

DAHS_2.1 uses a *relative* margin: a switch is blocked unless the new
heuristic's confidence exceeds the current's by at least HYSTERESIS_MARGIN
(15% relative, calibration-invariant across RF and XGB predict_proba).

We feed the selector synthetic state with a stub model whose probabilities
we fully control, then assert the switch fires iff
    new_conf >= current_conf * (1 + HYSTERESIS_MARGIN).
"""
from __future__ import annotations

import numpy as np
import pytest

from src.features import FeatureExtractor, SCENARIO_FEATURE_NAMES
from src.hybrid_scheduler import BatchwiseSelector


N_FEATS = len(SCENARIO_FEATURE_NAMES)


class _StubModel:
    """Returns whatever predict_proba vector the test sets on .next_proba."""
    def __init__(self):
        self.next_proba = np.array([1.0, 0.0, 0.0, 0.0, 0.0, 0.0])

    def predict_proba(self, X):
        return self.next_proba.reshape(1, -1)


def _scenario_state(n_orders=50, util=0.5, n_broken=0, lunch=False):
    return {
        "current_time": 10.0,
        "n_orders_in_system": n_orders,
        "queue_sizes": {z: 5 for z in range(8)},
        "zone_utilization": {z: util for z in range(8)},
        "n_broken_stations": n_broken,
        "lunch_active": lunch,
        "surge_multiplier": 1.0,
        "completed_so_far": 0,
        "waiting_jobs": [],
        "completed_jobs": [],
        "all_jobs": {},
    }


def _make_selector():
    fe = FeatureExtractor()
    sel = BatchwiseSelector(
        model=_StubModel(),
        feature_extractor=fe,
        feature_importances=np.ones(N_FEATS) / N_FEATS,
        feature_names=list(SCENARIO_FEATURE_NAMES),
    )
    return sel, sel._model


def test_initial_evaluation_picks_argmax():
    sel, model = _make_selector()
    model.next_proba = np.array([0.05, 0.05, 0.05, 0.05, 0.75, 0.05])
    sel.update_state(_scenario_state())
    sel._reevaluate(now=0.0)
    assert sel._current_heuristic == "wspt"
    assert sel._current_confidence == pytest.approx(0.75, abs=1e-6)


def test_small_relative_advantage_blocked_by_hysteresis():
    sel, model = _make_selector()
    # Lock in WSPT at 0.55
    model.next_proba = np.array([0.05, 0.05, 0.05, 0.10, 0.55, 0.20])
    sel.update_state(_scenario_state())
    sel._reevaluate(now=0.0)
    assert sel._current_heuristic == "wspt"
    locked = sel._current_confidence  # 0.55

    # New top: Slack at 0.60. Threshold = 0.55 * 1.15 = 0.6325 → blocked.
    model.next_proba = np.array([0.05, 0.05, 0.05, 0.10, 0.15, 0.60])
    sel.update_state(_scenario_state())
    sel._reevaluate(now=20.0)
    assert sel._current_heuristic == "wspt", "Hysteresis should have blocked the switch"
    last = sel.switching_log.entries[-1]
    assert last["reason"] == "hysteresis_blocked"
    assert last["switched"] is False


def test_large_relative_advantage_triggers_switch():
    sel, model = _make_selector()
    # Lock in WSPT at 0.45
    model.next_proba = np.array([0.05, 0.05, 0.10, 0.10, 0.45, 0.25])
    sel.update_state(_scenario_state())
    sel._reevaluate(now=0.0)
    assert sel._current_heuristic == "wspt"
    locked = sel._current_confidence  # 0.45

    # ATC at 0.85 — 0.85 > 0.45 * 1.15 = 0.5175, so switch should fire.
    new_top = 0.85
    rest = (1.0 - new_top) / 5
    proba = np.full(6, rest)
    proba[3] = new_top
    model.next_proba = proba
    sel.update_state(_scenario_state())
    sel._reevaluate(now=20.0)
    assert sel._current_heuristic == "atc"
    last = sel.switching_log.entries[-1]
    assert last["switched"] is True
    assert last["reason"] == "ml_decision"


def test_same_heuristic_keeps_no_hysteresis_block():
    """If the model picks the same heuristic again, that's a 'hold', not a block."""
    sel, model = _make_selector()
    model.next_proba = np.array([0.05, 0.05, 0.05, 0.10, 0.55, 0.20])
    sel.update_state(_scenario_state())
    sel._reevaluate(now=0.0)
    sel._reevaluate(now=20.0)
    last = sel.switching_log.entries[-1]
    assert last["selected"] == "wspt"
    assert last["reason"] != "hysteresis_blocked"
