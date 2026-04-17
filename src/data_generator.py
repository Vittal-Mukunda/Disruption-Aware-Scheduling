"""
data_generator.py — Training Data Generation for DAHS_2

NEW in DAHS_2: Snapshot-fork algorithm
  Instead of running full simulations with each heuristic,
  this generator takes snapshots every 10 minutes, forks 6 short
  simulations (20 min each), and labels which heuristic wins per-window.
  Result: ~60 rows per scenario instead of 1, with situation-level labels.

Also generates:
  - priority_dataset.csv (same as DAHS_1)
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

DATA_DIR = Path(__file__).parent.parent / "data" / "raw"

HEURISTIC_NAMES = [
    "fifo",
    "priority_edd",
    "critical_ratio",
    "atc",
    "wspt",
    "slack",
]

SNAPSHOT_INTERVAL = 10.0   # minutes between snapshots
FORK_WINDOW = 20.0         # minutes per fork evaluation


# ---------------------------------------------------------------------------
# 7-region scenario diversity (ported from DAHS_1)
# ---------------------------------------------------------------------------

def _make_diverse_scenario_configs(n_scenarios: int, rng: np.random.Generator) -> List[Dict[str, Any]]:
    """Generate diverse simulator parameter configs to avoid class imbalance."""
    configs: List[Dict[str, Any]] = []

    regions = [
        # FIFO-friendly: low load, uniform jobs, loose deadlines
        {"arrival": (1.0, 2.0), "bkdown": (0.0, 0.001), "due": (1.8, 3.0),
         "batch": (5, 15), "lunch": (1.0, 1.1), "pscale": (0.8, 1.2),
         "mix": "uniform"},
        # Priority-EDD: high express, tight deadlines
        {"arrival": (2.0, 3.5), "bkdown": (0.0, 0.005), "due": (0.4, 0.8),
         "batch": (15, 40), "lunch": (1.0, 1.3), "pscale": (0.8, 1.2),
         "mix": "express_heavy"},
        # Critical-Ratio: high breakdowns, heterogeneous pressure
        {"arrival": (2.0, 3.0), "bkdown": (0.008, 0.020), "due": (0.6, 1.2),
         "batch": (20, 50), "lunch": (1.2, 1.6), "pscale": (1.0, 1.5),
         "mix": "diverse"},
        # ATC: heavy load + surge, weighted tardiness matters
        {"arrival": (3.0, 5.0), "bkdown": (0.001, 0.008), "due": (0.7, 1.1),
         "batch": (30, 80), "lunch": (1.2, 1.5), "pscale": (0.9, 1.3),
         "mix": "diverse"},
        # WSPT: many short jobs, steady flow
        {"arrival": (2.5, 4.0), "bkdown": (0.0, 0.003), "due": (1.0, 1.8),
         "batch": (10, 30), "lunch": (1.0, 1.2), "pscale": (0.5, 0.9),
         "mix": "short_heavy"},
        # Slack: tight deadlines, recovery-mode
        {"arrival": (2.5, 3.5), "bkdown": (0.003, 0.012), "due": (0.2, 0.5),
         "batch": (20, 50), "lunch": (1.3, 1.8), "pscale": (1.0, 1.4),
         "mix": "diverse"},
        # Default / general
        {"arrival": (1.5, 4.0), "bkdown": (0.0, 0.015), "due": (0.5, 2.0),
         "batch": (10, 60), "lunch": (1.0, 1.5), "pscale": (0.7, 1.3),
         "mix": "random"},
    ]

    mix_templates = {
        "uniform": {"A": 0.0, "B": 0.0, "C": 1.0, "D": 0.0, "E": 0.0},
        "express_heavy": {"A": 0.20, "B": 0.10, "C": 0.10, "D": 0.10, "E": 0.50},
        "short_heavy": {"A": 0.35, "B": 0.10, "C": 0.10, "D": 0.05, "E": 0.40},
        "diverse": {"A": 0.25, "B": 0.25, "C": 0.20, "D": 0.15, "E": 0.15},
    }

    per_region = n_scenarios // len(regions)
    remainder = n_scenarios - per_region * len(regions)

    seed_counter = 0
    for ri, region in enumerate(regions):
        count = per_region + (1 if ri < remainder else 0)
        for _ in range(count):
            ar  = rng.uniform(*region["arrival"])
            bk  = rng.uniform(*region["bkdown"])
            dd  = rng.uniform(*region["due"])
            bat = int(rng.uniform(*region["batch"]))
            lp  = rng.uniform(*region["lunch"])
            ps  = rng.uniform(*region["pscale"])

            if region["mix"] == "random":
                freqs_raw = rng.dirichlet([1, 1, 1, 1, 1])
                jt_freq = {k: float(v) for k, v in zip("ABCDE", freqs_raw)}
            elif region["mix"] in mix_templates:
                base = mix_templates[region["mix"]].copy()
                noise = rng.uniform(-0.05, 0.05, 5)
                vals = np.array([base[k] for k in "ABCDE"]) + noise
                vals = np.clip(vals, 0.01, None)
                vals /= vals.sum()
                jt_freq = {k: float(v) for k, v in zip("ABCDE", vals)}
            else:
                jt_freq = {}

            configs.append({
                "seed": seed_counter,
                "base_arrival_rate": round(ar, 2),
                "breakdown_prob": round(bk, 4),
                "batch_arrival_size": bat,
                "lunch_penalty_factor": round(lp, 2),
                "job_type_frequencies": jt_freq,
                "due_date_tightness": round(dd, 2),
                "processing_time_scale": round(ps, 2),
            })
            seed_counter += 1

    return configs


# ---------------------------------------------------------------------------
# NEW: Snapshot-fork worker (top-level for multiprocessing)
# ---------------------------------------------------------------------------

def _run_snapshot_scenario(args: Dict[str, Any]) -> List[Dict[str, Any]]:
    """Worker: run one full scenario with snapshot-fork labeling.

    Algorithm:
    1. Run base sim (FIFO) to each 10-minute snapshot
    2. At each snapshot, save state and fork 6 heuristics 20 min each
    3. Label the snapshot with the best-performing heuristic
    Returns ~60 rows per scenario.
    """
    config = args
    from src.heuristics import (
        fifo_dispatch, priority_edd_dispatch, critical_ratio_dispatch,
        atc_dispatch, wspt_dispatch, slack_dispatch, DISPATCH_MAP,
    )
    from src.simulator import WarehouseSimulator
    from src.features import FeatureExtractor, SCENARIO_FEATURE_NAMES

    sim_kw = {
        "base_arrival_rate":    config.get("base_arrival_rate", 2.5),
        "breakdown_prob":       config.get("breakdown_prob", 0.003),
        "batch_arrival_size":   config.get("batch_arrival_size", 30),
        "lunch_penalty_factor": config.get("lunch_penalty_factor", 1.3),
        "job_type_frequencies": config.get("job_type_frequencies", {}),
        "due_date_tightness":   config.get("due_date_tightness", 1.0),
        "processing_time_scale": config.get("processing_time_scale", 1.0),
    }

    seed = config["seed"]
    fe = FeatureExtractor()
    sim = WarehouseSimulator(seed=seed, heuristic_fn=fifo_dispatch, feature_extractor=fe, **sim_kw)
    sim.init()

    rows = []
    SIM_DURATION = 600.0

    for t in np.arange(SNAPSHOT_INTERVAL, SIM_DURATION, SNAPSHOT_INTERVAL):
        t = float(t)
        sim.step_to(t)
        state_snap = sim.get_state_snapshot()

        # Extract 22 scenario features from current state
        features = fe.extract_scenario_features(state_snap)
        if np.any(~np.isfinite(features)):
            continue  # skip bad windows

        # Save state for forking
        saved_state = sim.save_state()

        # Fork 6 heuristics for 20 min each
        fork_end = t + FORK_WINDOW
        scores = []
        for heur_name in HEURISTIC_NAMES:
            try:
                heur_fn = DISPATCH_MAP[heur_name]
                fork = WarehouseSimulator.from_state(saved_state, heur_fn)
                fork.step_to(fork_end)
                metrics = fork.get_partial_metrics(since_time=t)
                score = _composite_score(metrics)
            except Exception:
                score = float("inf")
            scores.append(score)

        # Label: best heuristic for THIS situation
        label = int(np.argmin(scores))

        row = {name: float(val) for name, val in zip(SCENARIO_FEATURE_NAMES, features)}
        row["label"] = label
        rows.append(row)

    return rows


def _composite_score(metrics) -> float:
    """Scoring formula: 0.40*tardiness + 0.35*sla + 0.25*cycle_time (normalized)."""
    # Raw (unnormalized) — normalization happens across heuristics in the caller
    tard = metrics.total_tardiness if metrics.total_tardiness != float("inf") else 1e9
    sla = metrics.sla_breach_rate if metrics.sla_breach_rate != float("inf") else 1.0
    cyc = metrics.avg_cycle_time if metrics.avg_cycle_time != float("inf") else 1e6
    return 0.40 * tard + 0.35 * sla * 1000 + 0.25 * cyc


# ---------------------------------------------------------------------------
# Priority dataset worker (ported from DAHS_1)
# ---------------------------------------------------------------------------

def _run_priority_scenario(args: Tuple[int, int]) -> List[Dict[str, Any]]:
    """Worker: run one seed with ATC baseline, collect job-level feature rows."""
    seed, n_points = args
    from src.heuristics import atc_dispatch
    from src.simulator import WarehouseSimulator
    from src.features import FeatureExtractor

    _PRIO_W = {"A": 2.0, "B": 1.5, "C": 1.0, "D": 0.8, "E": 3.0}
    _DD_OFFSET = {"A": 120, "B": 160, "C": 240, "D": 320, "E": 60}

    fe = FeatureExtractor()
    sim = WarehouseSimulator(seed=seed, heuristic_fn=atc_dispatch, feature_extractor=fe)
    sim.run(duration=600.0)

    rows: List[Dict[str, Any]] = []
    state = sim.get_state_snapshot()
    completed = sim.completed_jobs

    if not completed:
        return rows

    rng = np.random.default_rng(seed)
    sampled = rng.choice(len(completed), size=min(n_points, len(completed)), replace=False)

    for idx in sampled:
        job = completed[int(idx)]
        scenario_feats = fe.extract_scenario_features(state)
        job_feats = fe.extract_job_features(job, state)

        w = _PRIO_W.get(job.job_type, 1.0)
        dd_off = _DD_OFFSET.get(job.job_type, 120)
        cycle_time = job.completion_time - job.arrival_time
        tardiness = max(0.0, job.completion_time - job.due_date)

        remaining = job.remaining_proc_time()
        time_to_due = job.due_date - state["current_time"]
        urgency = 1.0 - min(1.0, max(0.0, time_to_due / max(dd_off, 1.0)))
        importance = w / 3.0
        efficiency = 1.0 / (1.0 + remaining / 30.0)
        delivery_perf = max(0.0, 1.0 - tardiness / max(dd_off, 1.0))

        priority_score = float(
            0.30 * urgency
            + 0.25 * importance
            + 0.20 * efficiency
            + 0.25 * delivery_perf
        )

        if not np.isfinite(priority_score):
            continue

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
    n_scenarios: int = 1000,
    n_workers: int = 4,
    save: bool = True,
) -> pd.DataFrame:
    """Generate the heuristic selector training dataset using snapshot-fork algorithm.

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
        ~60 rows per scenario (one per 10-min snapshot).
    """
    from src.features import SCENARIO_FEATURE_NAMES

    master_rng = np.random.default_rng(777)
    configs = _make_diverse_scenario_configs(n_scenarios, master_rng)

    logger.info(
        "Generating selector dataset (snapshot-fork): %d scenarios × ~60 snapshots each",
        n_scenarios
    )

    all_rows: List[Dict[str, Any]] = []
    ctx = mp.get_context("spawn")
    with ctx.Pool(processes=n_workers) as pool:
        for rows in tqdm(
            pool.imap_unordered(_run_snapshot_scenario, configs),
            total=len(configs),
            desc="Snapshot-fork data gen",
        ):
            all_rows.extend(rows)

    df = pd.DataFrame(all_rows)

    # Sanitize
    df = df.replace([np.inf, -np.inf], np.nan).fillna(0.0)

    logger.info("Selector dataset shape: %s", df.shape)
    if "label" in df.columns:
        label_counts = df["label"].value_counts().to_dict()
        logger.info("Label distribution: %s", label_counts)

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
    """Generate the priority predictor training dataset (ported from DAHS_1)."""
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
    df = df.replace([np.inf, -np.inf], np.nan).dropna()

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


if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
    generate_selector_dataset(n_scenarios=50, n_workers=2)
