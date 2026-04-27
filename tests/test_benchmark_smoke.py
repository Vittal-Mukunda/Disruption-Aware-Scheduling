"""Smoke test for the per-seed benchmark worker.

The benchmark runs ~7 method variants per seed, swallowing exceptions so a
single broken row can't kill a 300-seed run. That defensive design is good
for production but bad for development — bugs in dahs_hybrid_* or
RollingHorizonOracle would just log warnings and silently halve the
benchmark output. This test catches that by:

  1. Running _benchmark_single_seed on one short seed.
  2. Asserting the six fixed-rule baselines all produced a row.
  3. Asserting the synthesised best_fixed_oracle row exists.
  4. Asserting wall-clock timing is captured on every row.

If models/ doesn't have selector_*.joblib (smoke-test environment), the
DAHS-* rows are skipped — but the baseline + oracle rows must still appear.
"""
from __future__ import annotations

import os
from pathlib import Path

import pytest

from src.evaluator import _benchmark_single_seed, _row


REQUIRED_BASELINES = {
    "fifo", "priority_edd", "critical_ratio", "atc", "wspt", "slack",
    "best_fixed_oracle",
}


@pytest.mark.timeout(300)
def test_benchmark_single_seed_produces_baselines_and_oracle(monkeypatch):
    # Use a small seed and shorter shift via env if the simulator supports it.
    rows = _benchmark_single_seed((42,))
    methods_seen = {r["method"] for r in rows}

    missing = REQUIRED_BASELINES - methods_seen
    assert not missing, f"benchmark missing baseline rows: {missing}"

    # Every row must carry timing + the canonical metric set.
    for r in rows:
        assert "elapsed_seconds" in r, r
        assert r["elapsed_seconds"] >= 0.0
        for field in ("makespan", "total_tardiness", "sla_breach_rate",
                      "avg_cycle_time", "throughput", "queue_max",
                      "completed_jobs"):
            assert field in r, (r["method"], field)


def test_oracle_row_has_winner_field():
    rows = _benchmark_single_seed((43,))
    oracle = next((r for r in rows if r["method"] == "best_fixed_oracle"), None)
    assert oracle is not None
    assert "best_fixed_winner" in oracle
    assert oracle["best_fixed_winner"] in {
        "fifo", "priority_edd", "critical_ratio", "atc", "wspt", "slack",
    }
    # Oracle tardiness must equal the minimum among the six baseline rows
    # on this seed (sanity check on the synthesis logic).
    fixed = {r["method"]: r["total_tardiness"]
             for r in rows
             if r["method"] in {"fifo", "priority_edd", "critical_ratio",
                                "atc", "wspt", "slack"}}
    if fixed:
        assert oracle["total_tardiness"] == pytest.approx(min(fixed.values()))


def test_row_helper_shape():
    """_row() output shape is the canonical contract every other writer uses."""
    class _M:
        makespan = 100.0
        total_tardiness = 5.0
        sla_breach_rate = 0.1
        avg_cycle_time = 30.0
        zone_utilization = {0: 0.5, 1: 0.6}
        throughput = 80.0
        queue_max = 12
        completed_jobs = 100

    r = _row(seed=7, method="t", m=_M(), elapsed=1.234)
    assert r["seed"] == 7
    assert r["method"] == "t"
    assert r["elapsed_seconds"] == 1.234
    assert 0.4 < r["zone_utilization_avg"] < 0.7
