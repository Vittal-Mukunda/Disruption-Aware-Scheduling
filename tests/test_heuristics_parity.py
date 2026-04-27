"""Parity tests for the six dispatch heuristics.

For each baseline, two independently constructed simulators on the same seed
must produce identical SimulationMetrics. This catches hidden global state
that would silently bias the DAHS-vs-baselines comparison.

Short shifts (120-240 min) keep pytest under a few seconds; the full
benchmark uses 600-min × 300 seeds and is not exercised here.
"""
from __future__ import annotations

import math

import pytest

from src.heuristics import (
    fifo_dispatch,
    priority_edd_dispatch,
    critical_ratio_dispatch,
    atc_dispatch,
    wspt_dispatch,
    slack_dispatch,
)
from src.simulator import WarehouseSimulator


HEURISTICS = [
    ("fifo", fifo_dispatch),
    ("priority_edd", priority_edd_dispatch),
    ("critical_ratio", critical_ratio_dispatch),
    ("atc", atc_dispatch),
    ("wspt", wspt_dispatch),
    ("slack", slack_dispatch),
]


def _run(heur_fn, seed: int, duration: float):
    sim = WarehouseSimulator(seed=seed, heuristic_fn=heur_fn)
    return sim.run(duration=duration)


@pytest.mark.parametrize("name,heur_fn", HEURISTICS)
def test_heuristic_is_deterministic(name, heur_fn):
    """Two fresh simulators on the same seed produce identical metrics."""
    seed = 4242
    duration = 120.0
    m1 = _run(heur_fn, seed, duration)
    m2 = _run(heur_fn, seed, duration)
    assert m1.completed_jobs == m2.completed_jobs, name
    assert math.isclose(m1.makespan, m2.makespan, rel_tol=1e-9), name
    assert math.isclose(m1.total_tardiness, m2.total_tardiness, rel_tol=1e-9), name
    assert math.isclose(m1.sla_breach_rate, m2.sla_breach_rate, rel_tol=1e-9), name
    assert math.isclose(m1.avg_cycle_time, m2.avg_cycle_time, rel_tol=1e-9), name


def test_different_seeds_diverge():
    """Different seeds should not produce identical trajectories."""
    a = _run(fifo_dispatch, seed=1, duration=120.0)
    b = _run(fifo_dispatch, seed=2, duration=120.0)
    assert (a.completed_jobs != b.completed_jobs
            or not math.isclose(a.total_tardiness, b.total_tardiness, abs_tol=1e-3))


def test_heuristics_produce_distinct_results():
    """At least two heuristics must disagree on SOME metric on a non-trivial
    seed. If every heuristic returns identical metrics, dispatch ordering has
    no effect — meaning the simulator is not actually using heuristic_fn.
    """
    seed = 7
    duration = 240.0
    metrics_per = {name: _run(fn, seed, duration) for name, fn in HEURISTICS}
    fingerprints = {
        name: (
            round(m.total_tardiness, 2),
            round(m.avg_cycle_time, 2),
            round(m.makespan, 2),
            m.completed_jobs,
        )
        for name, m in metrics_per.items()
    }
    distinct = set(fingerprints.values())
    assert len(distinct) >= 2, f"All heuristics produced identical metrics: {fingerprints}"
