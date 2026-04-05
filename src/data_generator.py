"""
data_generator.py — Training Data Generation for ML Heuristic Selector & Priority Predictor

Generates two datasets by running the warehouse simulator across many seeds:
  1. selector_dataset.csv  — 22 scenario features + label (best of 6 heuristics)
  2. priority_dataset.csv  — 29 features + multi-criteria oracle priority score

The priority labels use a weighted multi-criteria composite that combines
urgency, job importance, efficiency, and congestion awareness — explicitly
designed to avoid circularity with any single baseline heuristic.
"""

from __future__ import annotations

import logging
import multiprocessing as mp
import os
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

import numpy as np
import pandas as pd
from tqdm import tqdm

logger = logging.getLogger(__name__)

# Paths
DATA_DIR = Path(__file__).parent.parent / "data" / "raw"

# All 6 baseline heuristic names (order matches label encoding)
HEURISTIC_NAMES = [
    "fifo",
    "priority_edd",
    "critical_ratio",
    "atc",
    "wspt",
    "slack",
]


# ---------------------------------------------------------------------------
# Worker helpers (must be top-level for multiprocessing pickling)
# ---------------------------------------------------------------------------

def run_single_scenario(args: Tuple[int, str]) -> Dict[str, Any]:
    """Multiprocessing worker: run one (seed, heuristic) simulation.

    Returns a flat dict with metrics (no sim object — pickling-safe).
    """
    seed, heuristic_name = args
    from src.heuristics import (
        fifo_dispatch, priority_edd_dispatch, critical_ratio_dispatch,
        atc_dispatch, wspt_dispatch, slack_dispatch,
    )
    from src.simulator import WarehouseSimulator
    from src.features import FeatureExtractor

    dispatch_map = {
        "fifo": fifo_dispatch,
        "priority_edd": priority_edd_dispatch,
        "critical_ratio": critical_ratio_dispatch,
        "atc": atc_dispatch,
        "wspt": wspt_dispatch,
        "slack": slack_dispatch,
    }
    heuristic_fn = dispatch_map[heuristic_name]
    fe = FeatureExtractor()
    sim = WarehouseSimulator(seed=seed, heuristic_fn=heuristic_fn, feature_extractor=fe)
    metrics = sim.run(duration=600.0)
    state = sim.get_state_snapshot()
    scenario_feats = fe.extract_scenario_features(state).tolist()

    return {
        "seed": seed,
        "heuristic": heuristic_name,
        "makespan": metrics.makespan,
        "total_tardiness": metrics.total_tardiness,
        "sla_breach_rate": metrics.sla_breach_rate,
        "avg_cycle_time": metrics.avg_cycle_time,
        "throughput": metrics.throughput,
        "completed_jobs": metrics.completed_jobs,
        "scenario_features": scenario_feats,
    }


def _run_priority_scenario(args: Tuple[int, int]) -> List[Dict[str, Any]]:
    """Worker: run one seed with ALL heuristics, collect job-level feature rows.

    Uses a multi-criteria oracle label that combines urgency, job importance,
    processing efficiency, and congestion awareness.  This is NOT a monotone
    transform of any single heuristic (breaking the CR circularity).
    """
    seed, n_points = args
    from src.heuristics import (
        fifo_dispatch, priority_edd_dispatch, critical_ratio_dispatch,
        atc_dispatch, wspt_dispatch, slack_dispatch,
    )
    from src.simulator import WarehouseSimulator
    from src.features import FeatureExtractor

    # Priority weight mapping
    _PRIO_W = {"A": 2.0, "B": 1.5, "C": 1.0, "D": 0.8, "E": 3.0}
    # Due date offset mapping (must match simulator)
    _DD_OFFSET = {"A": 120, "B": 160, "C": 240, "D": 320, "E": 60}

    # Run with ATC (strongest single heuristic) as the base simulation
    fe = FeatureExtractor()
    sim = WarehouseSimulator(seed=seed, heuristic_fn=atc_dispatch, feature_extractor=fe)
    sim.run(duration=600.0)

    rows: List[Dict[str, Any]] = []
    state = sim.get_state_snapshot()
    completed = sim.completed_jobs

    if not completed:
        return rows

    # Sample n_points completed jobs
    rng = np.random.default_rng(seed)
    sampled = rng.choice(len(completed), size=min(n_points, len(completed)), replace=False)

    for idx in sampled:
        job = completed[int(idx)]
        scenario_feats = fe.extract_scenario_features(state)
        job_feats = fe.extract_job_features(job, state)

        # --- Multi-criteria oracle priority score ---
        # This composite breaks circularity by combining dimensions that
        # no single heuristic captures jointly.

        w = _PRIO_W.get(job.job_type, 1.0)
        dd_off = _DD_OFFSET.get(job.job_type, 120)
        cycle_time = job.completion_time - job.arrival_time
        tardiness = max(0.0, job.completion_time - job.due_date)

        # Component 1: Urgency (time-pressure at arrival relative to job complexity)
        remaining = job.remaining_proc_time()
        time_to_due = job.due_date - state["current_time"]
        urgency = 1.0 - min(1.0, max(0.0, time_to_due / max(dd_off, 1.0)))

        # Component 2: Importance (normalized priority weight)
        importance = w / 3.0  # max weight is 3.0 (type E)

        # Component 3: Efficiency (prefer jobs that can finish quickly)
        efficiency = 1.0 / (1.0 + remaining / 30.0)

        # Component 4: On-time delivery performance (retrospective oracle signal)
        # Uses actual simulation outcome — the model learns which jobs
        # benefited most from being prioritised
        delivery_perf = max(0.0, 1.0 - tardiness / max(dd_off, 1.0))

        # Weighted composite
        priority_score = float(
            0.30 * urgency
            + 0.25 * importance
            + 0.20 * efficiency
            + 0.25 * delivery_perf
        )

        row = {
            **{f"sf_{i}": float(v) for i, v in enumerate(scenario_feats)},
            **{f"jf_{i}": float(v) for i, v in enumerate(job_feats)},
            "priority_score": priority_score,
        }
        rows.append(row)

    return rows


# ---------------------------------------------------------------------------
# Dataset generators
# ---------------------------------------------------------------------------

def generate_selector_dataset(
    n_scenarios: int = 10_000,
    n_workers: int = 4,
    save: bool = True,
) -> pd.DataFrame:
    """Generate the heuristic selector training dataset.

    For each scenario seed, runs all 6 baselines and labels which
    heuristic achieves the best combined score.

    Combined score = 0.5 × norm_makespan + 0.3 × norm_tardiness + 0.2 × norm_sla
    (lower is better).

    Parameters
    ----------
    n_scenarios : int
        Number of scenario seeds to simulate.
    n_workers : int
        Number of parallel worker processes.
    save : bool
        Whether to save the CSV to data/raw/.

    Returns
    -------
    pd.DataFrame
        22 scenario feature columns + "label" (0-5, one per heuristic).
    """
    from src.features import SCENARIO_FEATURE_NAMES

    seeds = list(range(n_scenarios))

    all_args = [(seed, heur) for seed in seeds for heur in HEURISTIC_NAMES]

    logger.info("Generating selector dataset: %d scenarios × %d heuristics", n_scenarios, len(HEURISTIC_NAMES))

    results_by_seed: Dict[int, Dict[str, Dict]] = {s: {} for s in seeds}

    ctx = mp.get_context("spawn")
    with ctx.Pool(processes=n_workers) as pool:
        for result in tqdm(
            pool.imap_unordered(run_single_scenario, all_args),
            total=len(all_args),
            desc="Selector data gen",
        ):
            seed = result["seed"]
            heur = result["heuristic"]
            results_by_seed[seed][heur] = result

    rows = []
    for seed in seeds:
        seed_res = results_by_seed[seed]
        if len(seed_res) < len(HEURISTIC_NAMES):
            continue  # incomplete — skip

        makespans = np.array([seed_res[h]["makespan"] for h in HEURISTIC_NAMES])
        tardiness = np.array([seed_res[h]["total_tardiness"] for h in HEURISTIC_NAMES])
        sla_rates = np.array([seed_res[h]["sla_breach_rate"] for h in HEURISTIC_NAMES])

        # Normalize per-seed (min-max)
        def _norm(arr: np.ndarray) -> np.ndarray:
            rng_v = arr.max() - arr.min()
            if rng_v == 0:
                return np.zeros_like(arr)
            return (arr - arr.min()) / rng_v

        norm_mks = _norm(makespans)
        norm_trd = _norm(tardiness)
        norm_sla = _norm(sla_rates)
        scores = 0.5 * norm_mks + 0.3 * norm_trd + 0.2 * norm_sla
        label = int(np.argmin(scores))

        # Use scenario features from the FIFO run (state at end of shift)
        feats = seed_res["fifo"]["scenario_features"]
        if feats is None:
            continue

        row = {name: val for name, val in zip(SCENARIO_FEATURE_NAMES, feats)}
        row["label"] = label
        rows.append(row)

    df = pd.DataFrame(rows)
    logger.info("Selector dataset shape: %s", df.shape)
    logger.info("Label distribution: %s", dict(zip(*np.unique(df["label"].values, return_counts=True))))

    if save:
        DATA_DIR.mkdir(parents=True, exist_ok=True)
        path = DATA_DIR / "selector_dataset.csv"
        df.to_csv(path, index=False)
        logger.info("Saved selector dataset -> %s", path)

    return df


def generate_priority_dataset(
    n_scenarios: int = 5_000,
    n_points_per: int = 10,
    n_workers: int = 4,
    save: bool = True,
) -> pd.DataFrame:
    """Generate the priority predictor training dataset.

    Runs ATC baseline on each seed, samples n_points_per completed jobs,
    extracts 29 features and assigns a multi-criteria oracle priority_score.

    Parameters
    ----------
    n_scenarios : int
        Number of seeds.
    n_points_per : int
        Job samples per scenario.
    n_workers : int
        Parallel workers.
    save : bool
        Whether to save the CSV.

    Returns
    -------
    pd.DataFrame
        22 scenario + 7 job feature columns + "priority_score".
    """
    from src.features import SCENARIO_FEATURE_NAMES, JOB_FEATURE_NAMES

    seeds = list(range(20_000, 20_000 + n_scenarios))
    all_args = [(seed, n_points_per) for seed in seeds]

    logger.info("Generating priority dataset: %d scenarios × %d points", n_scenarios, n_points_per)

    all_rows: List[Dict] = []
    ctx = mp.get_context("spawn")
    with ctx.Pool(processes=n_workers) as pool:
        for batch in tqdm(
            pool.imap_unordered(_run_priority_scenario, all_args),
            total=len(all_args),
            desc="Priority data gen",
        ):
            all_rows.extend(batch)

    df = pd.DataFrame(all_rows)

    # Rename columns to proper names
    sf_names = {f"sf_{i}": name for i, name in enumerate(SCENARIO_FEATURE_NAMES)}
    jf_names = {f"jf_{i}": name for i, name in enumerate(JOB_FEATURE_NAMES)}
    df.rename(columns={**sf_names, **jf_names}, inplace=True)

    logger.info("Priority dataset shape: %s", df.shape)

    if save:
        DATA_DIR.mkdir(parents=True, exist_ok=True)
        path = DATA_DIR / "priority_dataset.csv"
        df.to_csv(path, index=False)
        logger.info("Saved priority dataset -> %s", path)

    return df
