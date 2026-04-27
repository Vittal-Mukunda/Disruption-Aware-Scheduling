"""save_state / from_state round-trip tests.

The situation-level training contribution rests on the claim that a snapshot
taken mid-shift can be forked and continued under a different heuristic. We
require: (1) save_state produces a JSON-compatible dict, (2) from_state
reconstructs the same job/queue/station counts at the saved time, (3)
forks run forward to finite metrics without exceptions.
"""
from __future__ import annotations

import json
import math

from src.heuristics import fifo_dispatch, atc_dispatch
from src.simulator import WarehouseSimulator


def _run_to(t: float, seed: int = 99):
    sim = WarehouseSimulator(seed=seed, heuristic_fn=fifo_dispatch)
    sim.init()
    sim.step_to(t)
    return sim


def test_save_state_is_json_serializable():
    sim = _run_to(60.0)
    state = sim.save_state()
    def _coerce(o):
        if hasattr(o, "tolist"):
            return o.tolist()
        if isinstance(o, dict):
            return {k: _coerce(v) for k, v in o.items()}
        if isinstance(o, (list, tuple)):
            return [_coerce(v) for v in o]
        return o
    json.dumps(_coerce(state), default=str)


def test_from_state_preserves_counts_and_time():
    sim = _run_to(90.0, seed=11)
    state = sim.save_state()
    fork = WarehouseSimulator.from_state(state, heuristic_fn=atc_dispatch)
    assert math.isclose(fork.env.now, 90.0, abs_tol=1e-6)
    assert len(fork.all_jobs) == len(sim.all_jobs)
    assert len(fork.completed_jobs) == len(sim.completed_jobs)
    for z in sim.zones:
        assert len(fork.zone_queues[z]) == len(sim.zone_queues[z])
    assert fork._job_counter == sim._job_counter


def test_from_state_continues_to_finite_metrics():
    sim = _run_to(60.0, seed=21)
    state = sim.save_state()
    fork = WarehouseSimulator.from_state(state, heuristic_fn=atc_dispatch)
    fork.env.run(until=180.0)
    m = fork.get_partial_metrics(since_time=60.0)
    assert math.isfinite(m.total_tardiness)
    assert math.isfinite(m.avg_cycle_time)
    assert m.total_tardiness >= 0.0
    assert 0.0 <= m.sla_breach_rate <= 1.0


def test_two_forks_with_different_heuristics_run():
    sim = _run_to(60.0, seed=33)
    state = sim.save_state()
    f_fifo = WarehouseSimulator.from_state(state, heuristic_fn=fifo_dispatch)
    f_atc = WarehouseSimulator.from_state(state, heuristic_fn=atc_dispatch)
    f_fifo.env.run(until=120.0)
    f_atc.env.run(until=120.0)
    m_fifo = f_fifo.get_partial_metrics(since_time=60.0)
    m_atc = f_atc.get_partial_metrics(since_time=60.0)
    assert math.isfinite(m_fifo.total_tardiness)
    assert math.isfinite(m_atc.total_tardiness)
