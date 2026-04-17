#!/usr/bin/env python3
"""
scripts/run_pipeline.py — DAHS_2 End-to-End Training Pipeline

Steps:
  1. Generate selector dataset (snapshot-fork, n_scenarios configurable)
  2. Generate priority dataset
  3. Train selector models (DT, RF, XGB)
  4. Train priority predictor (GBR)
  5. [Optional] Run benchmark evaluation (300 seeds)

Usage:
  python scripts/run_pipeline.py             # Full pipeline (1000 scenarios)
  python scripts/run_pipeline.py --quick     # Quick smoke test (50 scenarios, 20 seeds)
  python scripts/run_pipeline.py --eval-only # Run evaluation only (models must exist)
"""
from __future__ import annotations

import argparse
import logging
import sys
import time
from pathlib import Path

# Force UTF-8 stdout/stderr on Windows so unicode chars (✓, ×, →) don't
# crash the pipeline after hours of data generation.
for _stream in ("stdout", "stderr"):
    try:
        getattr(sys, _stream).reconfigure(encoding="utf-8", errors="replace")
    except Exception:
        pass

# Make sure src is importable from project root
ROOT = Path(__file__).parent.parent
sys.path.insert(0, str(ROOT))

(ROOT / "logs").mkdir(exist_ok=True)
(ROOT / "data" / "raw").mkdir(parents=True, exist_ok=True)
(ROOT / "models").mkdir(exist_ok=True)
(ROOT / "results" / "plots").mkdir(parents=True, exist_ok=True)

_stream_handler = logging.StreamHandler()
_file_handler = logging.FileHandler(ROOT / "logs" / "pipeline.log", mode="a", encoding="utf-8")
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s %(levelname)s %(message)s",
    handlers=[_stream_handler, _file_handler],
)
logger = logging.getLogger(__name__)


def step(n: int, label: str) -> None:
    print(f"\n{'=' * 60}")
    print(f"  STEP {n}: {label}")
    print(f"{'=' * 60}\n")


def main() -> None:
    parser = argparse.ArgumentParser(description="DAHS_2 Training Pipeline")
    parser.add_argument("--quick", action="store_true", help="Quick smoke test (50 scenarios, 20 eval seeds)")
    parser.add_argument("--eval-only", action="store_true", help="Skip training, run evaluation only")
    parser.add_argument("--no-eval", action="store_true", help="Skip benchmark evaluation")
    parser.add_argument("--workers", type=int, default=4, help="Number of parallel workers")
    parser.add_argument("--scenarios", type=int, default=None, help="Override number of scenarios")
    args = parser.parse_args()

    n_scenarios = args.scenarios or (50 if args.quick else 1000)
    n_eval_seeds = 20 if args.quick else 300
    n_workers = args.workers

    t_start = time.time()

    print("\n" + "=" * 60)
    print("  DAHS 2.0 — Full Training & Evaluation Pipeline")
    print(f"  Scenarios: {n_scenarios} | Workers: {n_workers}")
    print("=" * 60)

    if not args.eval_only:
        # ── Step 1: Selector dataset ─────────────────────────────────
        step(1, "Snapshot-Fork Selector Dataset")
        from src.data_generator import generate_selector_dataset
        t = time.time()
        df = generate_selector_dataset(n_scenarios=n_scenarios, n_workers=n_workers)
        logger.info("Selector dataset: %d rows in %.1fs", len(df), time.time() - t)
        print(f"  ✓ Selector dataset: {len(df):,} rows")

        # ── Step 2: Priority dataset ─────────────────────────────────
        step(2, "Priority Predictor Dataset")
        from src.data_generator import generate_priority_dataset
        t = time.time()
        priority_df = generate_priority_dataset(
            n_scenarios=min(n_scenarios * 5, 5_000),
            n_points_per=10,
            n_workers=n_workers,
        )
        logger.info("Priority dataset: %d rows in %.1fs", len(priority_df), time.time() - t)
        print(f"  ✓ Priority dataset: {len(priority_df):,} rows")

        # ── Step 3: Train selectors ──────────────────────────────────
        step(3, "Train Selector Models (DT + RF + XGB)")
        from src.train_selector import train_selector_models
        t = time.time()
        selector_models = train_selector_models()
        logger.info("Selector training done in %.1fs", time.time() - t)
        print(f"  ✓ Trained: {list(selector_models.keys())}")

        # ── Step 4: Train priority predictor ────────────────────────
        step(4, "Train Priority Predictor (GBR)")
        from src.train_priority import train_priority_model
        t = time.time()
        gbr = train_priority_model()
        logger.info("Priority training done in %.1fs", time.time() - t)
        print("  ✓ Priority GBR trained")

    # ── Step 5: Benchmark evaluation ─────────────────────────────────
    if not args.no_eval:
        step(5, "Benchmark Evaluation")
        from src.evaluator import run_full_evaluation
        t = time.time()
        eval_seeds = list(range(99000, 99000 + n_eval_seeds))
        results = run_full_evaluation(seeds=eval_seeds, n_workers=n_workers)
        logger.info("Evaluation done: %d seeds in %.1fs", n_eval_seeds, time.time() - t)
        print(f"  ✓ Evaluation complete ({n_eval_seeds} seeds)")

        # Print summary
        bench_df = results["benchmark"]
        if not bench_df.empty:
            print("\n  Performance Summary (mean total tardiness):")
            for method in sorted(bench_df["method"].unique()):
                mean_t = bench_df[bench_df["method"] == method]["total_tardiness"].mean()
                print(f"    {method:<20}: {mean_t:>8.1f}")

    elapsed = time.time() - t_start
    print(f"\n  Pipeline complete in {elapsed / 60:.1f} minutes.")
    print(f"  Artifacts saved to: {ROOT / 'models'} and {ROOT / 'results'}\n")


if __name__ == "__main__":
    main()
