#!/usr/bin/env python3
"""
scripts/foolproof_retrain.py — Failure-tolerant GBR retrain pipeline.

Pipeline:
  Step 0: Backup current model -> priority_gbr.backup.joblib
  Step 1: Generate targeted preset training data (rotating dispatchers)
  Step 2: Augment existing dataset (append, never replace)
  Step 3: Train candidate GBR -> priority_gbr.candidate.joblib
  Step 4: Verify A: preset benchmark (7 presets) - candidate must hit >= preset_floor wins
  Step 5: Verify B: random-seed benchmark (20 seeds) - candidate must hit >= random_floor wins
  Step 6: Promote candidate or rollback to backup

Worst-case outcome: original priority_gbr.joblib unchanged.

Usage:
    python scripts/foolproof_retrain.py
    python scripts/foolproof_retrain.py --preset-floor 7 --random-floor 19
"""
from __future__ import annotations

import argparse
import json
import logging
import multiprocessing as mp
import os
import shutil
import sys
import time
from pathlib import Path
from typing import Any, Dict, List, Tuple

import joblib
import numpy as np
import pandas as pd

ROOT = Path(__file__).parent.parent
sys.path.insert(0, str(ROOT))

# Force UTF-8 stdout on Windows
for _stream in ("stdout", "stderr"):
    try:
        getattr(sys, _stream).reconfigure(encoding="utf-8", errors="replace")
    except Exception:
        pass

from src.simulator import WarehouseSimulator
from src.features import FeatureExtractor, SCENARIO_FEATURE_NAMES, JOB_FEATURE_NAMES
from src.heuristics import (
    fifo_dispatch, priority_edd_dispatch, critical_ratio_dispatch,
    atc_dispatch, wspt_dispatch, slack_dispatch,
)
from src.presets import PRESETS, get_preset

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
logger = logging.getLogger(__name__)

DISPATCH_FNS = {
    "fifo": fifo_dispatch,
    "priority_edd": priority_edd_dispatch,
    "critical_ratio": critical_ratio_dispatch,
    "atc": atc_dispatch,
    "wspt": wspt_dispatch,
    "slack": slack_dispatch,
}

MODELS_DIR = ROOT / "models"
DATA_DIR = ROOT / "data" / "raw"
RESULTS_DIR = ROOT / "results"

LIVE_MODEL = MODELS_DIR / "priority_gbr.joblib"
BACKUP_MODEL = MODELS_DIR / "priority_gbr.backup.joblib"
CANDIDATE_MODEL = MODELS_DIR / "priority_gbr.candidate.joblib"

ORIG_DATA = DATA_DIR / "priority_dataset.csv"
AUG_DATA = DATA_DIR / "priority_dataset_augmented.csv"

# Targeted scenario allocation
PRESET_SCENARIO_BUDGET = {
    "Preset-1-FIFO":         300,
    "Preset-2-Priority-EDD": 300,
    "Preset-3-CR":           300,
    "Preset-4-ATC":         1000,   # currently losing -> heavy
    "Preset-5-WSPT":        1000,   # currently losing -> heavy
    "Preset-6-Slack":        300,
    "Preset-7-RealData":     300,
}
N_POINTS_PER = 12
N_WORKERS = 4


# ============================================================================
# Worker (module-level for Windows spawn compatibility)
# ============================================================================

def _preset_worker(args: Tuple[int, int, str, str]) -> List[Dict[str, Any]]:
    """Run one (seed, preset, dispatcher) scenario, return ~n_points feature rows."""
    seed, n_points, preset_name, dispatcher_name = args

    p = get_preset(preset_name)
    dispatch_fn = DISPATCH_FNS[dispatcher_name]

    fe = FeatureExtractor()
    sim = WarehouseSimulator(
        seed=seed,
        heuristic_fn=dispatch_fn,
        feature_extractor=fe,
        base_arrival_rate=p.base_arrival_rate,
        breakdown_prob=p.breakdown_prob,
        batch_arrival_size=p.batch_arrival_size,
        lunch_penalty_factor=p.lunch_penalty_factor,
        job_type_frequencies=p.job_type_frequencies,
        due_date_tightness=p.due_date_tightness,
        processing_time_scale=p.processing_time_scale,
    )
    sim.run(duration=600.0)

    state = sim.get_state_snapshot()
    completed = sim.completed_jobs
    if not completed:
        return []

    _PRIO_W = {"A": 2.0, "B": 1.5, "C": 1.0, "D": 0.8, "E": 3.0}
    _DD_OFFSET = {"A": 120, "B": 160, "C": 240, "D": 320, "E": 60}

    rng = np.random.default_rng(seed)
    sampled = rng.choice(len(completed),
                         size=min(n_points, len(completed)), replace=False)

    rows: List[Dict[str, Any]] = []
    for idx in sampled:
        job = completed[int(idx)]
        sf = fe.extract_scenario_features(state)
        jf = fe.extract_job_features(job, state)

        w = _PRIO_W.get(job.job_type, 1.0)
        dd_off = _DD_OFFSET.get(job.job_type, 120)
        cycle = job.completion_time - job.arrival_time
        tard = max(0.0, job.completion_time - job.due_date)
        remaining = job.remaining_proc_time()
        time_to_due = job.due_date - state["current_time"]
        urgency = 1.0 - min(1.0, max(0.0, time_to_due / max(dd_off, 1.0)))
        importance = w / 3.0
        efficiency = 1.0 / (1.0 + remaining / 30.0)
        delivery_perf = max(0.0, 1.0 - tard / max(dd_off, 1.0))

        score = float(0.30*urgency + 0.25*importance + 0.20*efficiency + 0.25*delivery_perf)
        if not np.isfinite(score):
            continue

        row = {
            **{f"sf_{i}": float(v) for i, v in enumerate(sf)},
            **{f"jf_{i}": float(v) for i, v in enumerate(jf)},
            "priority_score": score,
        }
        rows.append(row)
    return rows


# ============================================================================
# Step 1+2: data generation + augmentation
# ============================================================================

def generate_augmented_dataset() -> pd.DataFrame:
    if not ORIG_DATA.exists():
        raise SystemExit(f"Missing original dataset: {ORIG_DATA}")

    logger.info("Loading original dataset: %s", ORIG_DATA)
    df_orig = pd.read_csv(ORIG_DATA)
    logger.info("  -> %d rows, %d cols", len(df_orig), df_orig.shape[1])

    # Build worker args: rotate dispatchers across seeds within each preset
    rotation = ["atc", "wspt", "fifo", "priority_edd", "critical_ratio", "slack"]
    args_list: List[Tuple[int, int, str, str]] = []
    seed_base = 50_000
    for preset_name, n_scen in PRESET_SCENARIO_BUDGET.items():
        for k in range(n_scen):
            seed = seed_base + k
            disp = rotation[k % len(rotation)]
            args_list.append((seed, N_POINTS_PER, preset_name, disp))
        seed_base += 100_000  # avoid collisions across presets

    total = len(args_list)
    logger.info("Generating %d preset scenarios with rotating dispatchers...", total)

    new_rows: List[Dict[str, Any]] = []
    t0 = time.time()
    ctx = mp.get_context("spawn")
    with ctx.Pool(processes=N_WORKERS) as pool:
        for i, batch in enumerate(pool.imap_unordered(_preset_worker, args_list), 1):
            new_rows.extend(batch)
            if i % 100 == 0:
                pct = 100 * i / total
                elapsed = time.time() - t0
                eta = elapsed * (total - i) / max(i, 1)
                logger.info("  progress: %d/%d (%.1f%%) elapsed=%.0fs eta=%.0fs",
                            i, total, pct, elapsed, eta)
    logger.info("Generated %d new rows in %.0fs", len(new_rows), time.time() - t0)

    if not new_rows:
        raise SystemExit("Preset data generation produced 0 rows -> abort")

    df_new = pd.DataFrame(new_rows)
    sf_names = {f"sf_{i}": name for i, name in enumerate(SCENARIO_FEATURE_NAMES)}
    jf_names = {f"jf_{i}": name for i, name in enumerate(JOB_FEATURE_NAMES)}
    df_new.rename(columns={**sf_names, **jf_names}, inplace=True)
    df_new = df_new.replace([np.inf, -np.inf], np.nan).dropna()

    # Align columns
    common_cols = [c for c in df_orig.columns if c in df_new.columns]
    if "priority_score" not in common_cols:
        common_cols.append("priority_score")
    df_orig_a = df_orig[common_cols]
    df_new_a = df_new[common_cols]

    df_aug = pd.concat([df_orig_a, df_new_a], ignore_index=True)
    logger.info("Augmented dataset: %d rows (orig=%d + new=%d)",
                len(df_aug), len(df_orig_a), len(df_new_a))

    DATA_DIR.mkdir(parents=True, exist_ok=True)
    df_aug.to_csv(AUG_DATA, index=False)
    logger.info("Wrote augmented dataset -> %s", AUG_DATA)
    return df_aug


# ============================================================================
# Step 3: train candidate
# ============================================================================

def train_candidate(df: pd.DataFrame) -> None:
    from sklearn.ensemble import GradientBoostingRegressor
    from sklearn.metrics import mean_absolute_error, r2_score
    from sklearn.model_selection import train_test_split

    df = df.replace([np.inf, -np.inf], np.nan).dropna()
    feature_cols = [c for c in df.columns if c != "priority_score"]
    X = df[feature_cols].values.astype(np.float32)
    y = df["priority_score"].values.astype(np.float32)
    logger.info("Training data: X=%s y=%s", X.shape, y.shape)

    X_tr, X_te, y_tr, y_te = train_test_split(X, y, test_size=0.20, random_state=42)
    model = GradientBoostingRegressor(
        n_estimators=300, max_depth=6, learning_rate=0.05,
        subsample=0.8, min_samples_leaf=5, random_state=42,
    )
    t0 = time.time()
    model.fit(X_tr, y_tr)
    logger.info("Fit time: %.1fs", time.time() - t0)

    y_hat = model.predict(X_te)
    logger.info("Candidate metrics: R2=%.4f MAE=%.4f",
                r2_score(y_te, y_hat), mean_absolute_error(y_te, y_hat))

    joblib.dump(model, CANDIDATE_MODEL)
    logger.info("Saved candidate -> %s", CANDIDATE_MODEL)


# ============================================================================
# Step 4: preset benchmark (uses candidate model)
# ============================================================================

def _make_priority_dispatch(model, fe, sim_ref):
    def dispatch(jobs, t, zone_id):
        sim = sim_ref[0]
        if not jobs or sim is None:
            return fifo_dispatch(jobs, t, zone_id)
        try:
            state = sim.get_state_snapshot()
            sf = fe.extract_scenario_features(state)
            feats = np.stack([
                np.concatenate([sf, fe.extract_job_features(j, state)]) for j in jobs
            ])
            scores = model.predict(feats)
            return [j for _, j in sorted(zip(scores, jobs),
                                         key=lambda x: x[0], reverse=True)]
        except Exception:
            return fifo_dispatch(jobs, t, zone_id)
    return dispatch


def _run_one_preset(p, model) -> Dict[str, Any]:
    sim_kw = dict(
        base_arrival_rate=p.base_arrival_rate, breakdown_prob=p.breakdown_prob,
        batch_arrival_size=p.batch_arrival_size, lunch_penalty_factor=p.lunch_penalty_factor,
        job_type_frequencies=p.job_type_frequencies,
        due_date_tightness=p.due_date_tightness,
        processing_time_scale=p.processing_time_scale,
    )
    fe = FeatureExtractor()

    base_fn = DISPATCH_FNS.get(p.favored_heuristic, fifo_dispatch)
    base_sim = WarehouseSimulator(seed=p.seed, heuristic_fn=base_fn, **sim_kw)
    base_metrics = base_sim.run(duration=600.0)

    sim_ref = [None]
    dispatch = _make_priority_dispatch(model, fe, sim_ref)
    dahs_sim = WarehouseSimulator(seed=p.seed, heuristic_fn=dispatch,
                                  feature_extractor=fe, **sim_kw)
    sim_ref[0] = dahs_sim
    dahs_metrics = dahs_sim.run(duration=600.0)

    return {
        "preset": p.name,
        "favored": p.favored_heuristic,
        "baseline_tardiness": float(base_metrics.total_tardiness),
        "dahs_tardiness": float(dahs_metrics.total_tardiness),
        "wins": float(dahs_metrics.total_tardiness) <= float(base_metrics.total_tardiness),
    }


def verify_presets(model) -> Tuple[int, List[Dict[str, Any]]]:
    logger.info("VERIFY A: preset benchmark on candidate ...")
    rows: List[Dict[str, Any]] = []
    for p in PRESETS:
        rows.append(_run_one_preset(p, model))
    n_wins = sum(1 for r in rows if r["wins"])
    logger.info("VERIFY A: %d/%d preset wins", n_wins, len(rows))
    for r in rows:
        mark = "OK" if r["wins"] else "LOSS"
        logger.info("  [%s] %-22s base=%.0f dahs=%.0f",
                    mark, r["preset"], r["baseline_tardiness"], r["dahs_tardiness"])
    return n_wins, rows


# ============================================================================
# Step 5: random-seed benchmark (uses candidate model)
# ============================================================================

def _run_one_seed_all(seed: int, model) -> Dict[str, Any]:
    """Run all 6 baselines + DAHS-priority on one seed; return tardiness dict."""
    fe = FeatureExtractor()
    out = {"seed": seed}

    # baselines
    for name, fn in DISPATCH_FNS.items():
        sim = WarehouseSimulator(seed=seed, heuristic_fn=fn)
        m = sim.run(duration=600.0)
        out[name] = float(m.total_tardiness)

    # candidate priority
    sim_ref = [None]
    dispatch = _make_priority_dispatch(model, fe, sim_ref)
    sim = WarehouseSimulator(seed=seed, heuristic_fn=dispatch, feature_extractor=fe)
    sim_ref[0] = sim
    m = sim.run(duration=600.0)
    out["dahs_priority"] = float(m.total_tardiness)
    return out


def verify_random(model, n_seeds: int = 20) -> Tuple[int, List[Dict[str, Any]]]:
    logger.info("VERIFY B: random-seed benchmark on %d seeds ...", n_seeds)
    rows: List[Dict[str, Any]] = []
    for s in range(n_seeds):
        rows.append(_run_one_seed_all(s, model))
        if (s + 1) % 5 == 0:
            logger.info("  random verify: %d/%d done", s + 1, n_seeds)

    n_wins = 0
    for r in rows:
        baseline_tards = [r[h] for h in DISPATCH_FNS.keys()]
        if r["dahs_priority"] <= min(baseline_tards) + 1e-6:
            n_wins += 1
            r["wins"] = True
        else:
            r["wins"] = False

    logger.info("VERIFY B: %d/%d random-seed wins", n_wins, n_seeds)
    return n_wins, rows


# ============================================================================
# Main pipeline
# ============================================================================

def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--preset-floor", type=int, default=5,
                        help="Minimum preset wins required to promote (current=5)")
    parser.add_argument("--random-floor", type=int, default=18,
                        help="Minimum random-seed wins (out of 20) required to promote")
    parser.add_argument("--skip-data-gen", action="store_true",
                        help="Reuse existing augmented dataset if present")
    args = parser.parse_args()

    print("\n" + "=" * 88)
    print(" FOOLPROOF RETRAIN PIPELINE")
    print("=" * 88)
    print(f"  Preset floor: >= {args.preset_floor}/7 wins")
    print(f"  Random floor: >= {args.random_floor}/20 wins")
    print(f"  Live model:   {LIVE_MODEL}")
    print(f"  Backup will be: {BACKUP_MODEL}")
    print("=" * 88 + "\n")

    if not LIVE_MODEL.exists():
        raise SystemExit(f"No live model at {LIVE_MODEL}; nothing to back up.")

    # Step 0: Backup
    logger.info("STEP 0: Backing up live model -> %s", BACKUP_MODEL)
    shutil.copy2(LIVE_MODEL, BACKUP_MODEL)

    # Step 1+2: Augment data
    if args.skip_data_gen and AUG_DATA.exists():
        logger.info("STEP 1+2: Reusing existing %s", AUG_DATA)
        df_aug = pd.read_csv(AUG_DATA)
    else:
        logger.info("STEP 1+2: Generating augmented dataset")
        df_aug = generate_augmented_dataset()

    # Step 3: Train candidate
    logger.info("STEP 3: Training candidate GBR")
    train_candidate(df_aug)
    candidate = joblib.load(CANDIDATE_MODEL)

    # Step 4 + 5: Verify
    preset_wins, preset_rows = verify_presets(candidate)
    random_wins, random_rows = verify_random(candidate, n_seeds=20)

    # Step 6: Promote / rollback
    print("\n" + "=" * 88)
    print(" GATE DECISION")
    print("-" * 88)
    print(f"  Preset wins:  {preset_wins}/7   (floor: {args.preset_floor})")
    print(f"  Random wins:  {random_wins}/20  (floor: {args.random_floor})")

    promote = (preset_wins >= args.preset_floor) and (random_wins >= args.random_floor)

    gate_report = {
        "preset_wins": preset_wins,
        "random_wins": random_wins,
        "preset_floor": args.preset_floor,
        "random_floor": args.random_floor,
        "promoted": promote,
        "preset_rows": preset_rows,
        "random_rows": random_rows,
    }
    (RESULTS_DIR / "foolproof_retrain_report.json").write_text(
        json.dumps(gate_report, indent=2)
    )

    if promote:
        os.replace(str(CANDIDATE_MODEL), str(LIVE_MODEL))
        # Update preset_benchmark.json with new numbers
        out = []
        for r in preset_rows:
            base = r["baseline_tardiness"]
            dahs = r["dahs_tardiness"]
            imp = (base - dahs) / base * 100.0 if base > 0 else 0.0
            out.append({
                "preset": r["preset"],
                "favored": r["favored"],
                "baseline_tardiness": round(base, 2),
                "dahs_tardiness": round(dahs, 2),
                "improvement_pct": round(imp, 2),
                "dahs_wins": r["wins"],
            })
        (RESULTS_DIR / "preset_benchmark.json").write_text(json.dumps(out, indent=2))
        print("  RESULT: PROMOTED. New model is live.")
        print(f"  Old model preserved at: {BACKUP_MODEL}")
    else:
        try:
            CANDIDATE_MODEL.unlink()
        except FileNotFoundError:
            pass
        print("  RESULT: REJECTED. Live model unchanged.")
        print(f"  Reason:")
        if preset_wins < args.preset_floor:
            print(f"    - preset_wins={preset_wins} < floor={args.preset_floor}")
        if random_wins < args.random_floor:
            print(f"    - random_wins={random_wins} < floor={args.random_floor}")
    print("=" * 88 + "\n")

    sys.exit(0 if promote else 1)


if __name__ == "__main__":
    main()
