"""
run_full_pipeline.py ? End-to-End Orchestrator

Usage:
  python scripts/run_full_pipeline.py --quick     # 100 scenarios, ~15 min
  python scripts/run_full_pipeline.py --full      # 1000 scenarios, ~60 min
  python scripts/run_full_pipeline.py --eval-only # Skip data gen + training, run eval only
  python scripts/run_full_pipeline.py --seed 42   # Set global random seed
"""

from __future__ import annotations

import argparse
import logging
import os
import sys
import time
from datetime import datetime
from pathlib import Path

# Make project root importable
PROJECT_ROOT = Path(__file__).parent.parent
sys.path.insert(0, str(PROJECT_ROOT))

LOGS_DIR = PROJECT_ROOT / "logs"
LOGS_DIR.mkdir(parents=True, exist_ok=True)


def _setup_logging(timestamp: str) -> None:
    log_path = LOGS_DIR / f"pipeline_{timestamp}.log"
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s  %(levelname)-8s  %(name)s  %(message)s",
        handlers=[
            logging.StreamHandler(sys.stdout),
            logging.FileHandler(log_path, encoding="utf-8"),
        ],
    )
    logging.info("Log file: %s", log_path)


def _section(title: str) -> None:
    bar = "=" * 70
    print(f"\n{bar}\n  {title}\n{bar}")
    logging.info("STEP: %s", title)


def _elapsed(start: float) -> str:
    elapsed = time.time() - start
    mins, secs = divmod(int(elapsed), 60)
    return f"{mins}m {secs:02d}s"


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Hybrid ML Warehouse Scheduler ? Full Pipeline"
    )
    mode = parser.add_mutually_exclusive_group()
    mode.add_argument("--quick", action="store_true",
                      help="Quick mode: 100 scenarios for smoke-testing (~15 min)")
    mode.add_argument("--full", action="store_true",
                      help="Full mode: 1000 scenarios (~60 min)")
    parser.add_argument("--eval-only", action="store_true",
                        help="Skip data generation and training; only run evaluation")
    parser.add_argument("--analysis-only", action="store_true",
                        help="Skip everything and only run analysis from existing CSV")
    parser.add_argument("--seed", type=int, default=0, help="Global random seed")
    parser.add_argument("--workers", type=int, default=None,
                        help="Number of parallel workers (default: CPU count-1)")
    args = parser.parse_args()

    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    _setup_logging(timestamp)

    import multiprocessing
    n_workers = args.workers or max(1, multiprocessing.cpu_count() - 1)

    if args.full:
        n_selector = 1000
        n_priority = 500
        mode_str = "FULL"
    else:
        # Default to quick
        n_selector = 100
        n_priority = 50
        mode_str = "QUICK"

    logging.info("Pipeline mode: %s | seed=%d | workers=%d", mode_str, args.seed, n_workers)
    print(f"\n{'-'*70}")
    print(f"  Disruption-Aware Hybrid ML Warehouse Scheduler Pipeline")
    print(f"  Mode: {mode_str}  |  Seed: {args.seed}  |  Workers: {n_workers}")
    print(f"  Heuristics: 6 baselines + 3 hybrid methods = 9 total")
    print(f"{'-'*70}")

    pipeline_start = time.time()

    # ------------------------------------------------------------------
    # Step 0: Dependency check
    # ------------------------------------------------------------------
    _section("Step 0: Checking Dependencies")
    try:
        import simpy, sklearn, xgboost, shap, pandas, numpy, matplotlib, seaborn, joblib, tqdm, scipy
        print("All dependencies found.")
    except ImportError as e:
        print(f"Missing dependency: {e}")
        print("Run:  pip install -r requirements.txt")
        sys.exit(1)

    if not args.eval_only and not args.analysis_only:
        # ------------------------------------------------------------------
        # Step 1: Data Generation
        # ------------------------------------------------------------------
        _section("Step 1: Data Generation (6 heuristics per scenario)")
        t0 = time.time()

        from src.data_generator import generate_priority_dataset, generate_selector_dataset

        print(f"Generating selector dataset ({n_selector} scenarios x 6 heuristics) ...")
        generate_selector_dataset(n_scenarios=n_selector, n_workers=n_workers)
        print(f"Generating priority dataset ({n_priority} scenarios x 10 points) ...")
        generate_priority_dataset(n_scenarios=n_priority, n_workers=n_workers)

        print(f"\nData generation complete in {_elapsed(t0)}")

        # ------------------------------------------------------------------
        # Step 2: Train Selector Models (6-class)
        # ------------------------------------------------------------------
        _section("Step 2: Training Selector Models (DT / RF / XGB) ? 6 classes")
        t0 = time.time()

        from src.train_selector import train_selector_models
        train_selector_models()
        print(f"\nSelector training complete in {_elapsed(t0)}")

        # ------------------------------------------------------------------
        # Step 3: Train Priority Model
        # ------------------------------------------------------------------
        _section("Step 3: Training Priority Predictor (GBR) ? multi-criteria oracle labels")
        t0 = time.time()

        from src.train_priority import train_priority_model
        train_priority_model()
        print(f"\nPriority training complete in {_elapsed(t0)}")

    if not args.analysis_only:
        # ------------------------------------------------------------------
        # Step 4: Benchmark Evaluation
        # ------------------------------------------------------------------
        n_bench_seeds = 20 if not args.full else 300
        _section(f"Step 4: Running Benchmark ({n_bench_seeds} scenarios x 9 methods = {n_bench_seeds*9} sims)")
        t0 = time.time()

        from src.evaluator import (
            compute_improvements,
            compute_summary,
            generate_all_plots,
            run_benchmark,
            run_friedman_test,
            run_nemenyi_test,
            run_wilcoxon_tests,
            test_hypotheses,
            TEST_SEEDS,
        )

        bench_seeds = TEST_SEEDS[:n_bench_seeds]
        df = run_benchmark(seeds=bench_seeds, n_workers=n_workers)
        print(f"\nBenchmark complete in {_elapsed(t0)}")
    else:
        from src.evaluator import (
            compute_improvements,
            compute_summary,
            generate_all_plots,
            run_friedman_test,
            run_nemenyi_test,
            run_wilcoxon_tests,
            test_hypotheses,
        )
        import pandas as pd
        csv_path = PROJECT_ROOT / "results" / "benchmark_results.csv"
        print(f"Skipping Steps 1-4. Loading existing results from: {csv_path}")
        df = pd.read_csv(csv_path)

    # ------------------------------------------------------------------
    # Step 5: Statistical Analysis & Reporting
    # ------------------------------------------------------------------
    _section("Step 5: Comprehensive Statistical Analysis")

    summary = compute_summary(df)
    print("\n-- Summary Statistics (Total Tardiness) " + "-" * 30)
    import pandas as pd
    with pd.option_context("display.float_format", "{:.3f}".format, "display.max_columns", 20):
        if ("total_tardiness", "mean") in summary.columns:
            print(pd.DataFrame(summary["total_tardiness"]).to_string())
        else:
            print(summary.to_string())

    improvements = compute_improvements(df)
    print("\n-- % Improvement (Hybrid vs Baselines, Tardiness) " + "-" * 20)
    tard_impr = improvements[improvements["metric"] == "total_tardiness"]
    if not tard_impr.empty:
        print(tard_impr.pivot(index="hybrid", columns="baseline",
                              values="pct_improvement").round(2).to_string())

    # Friedman test (multi-method comparison)
    print("\n-- Friedman Test " + "-" * 53)
    friedman_result = run_friedman_test(df, metric="total_tardiness")

    # Post-hoc Nemenyi
    nemenyi_result = run_nemenyi_test(friedman_result)
    print(f"   Nemenyi CD = {nemenyi_result['cd']:.3f} (?=0.05)")

    # Wilcoxon with effect sizes and Holm correction
    print("\n-- Wilcoxon Signed-Rank Tests (Holm-corrected) " + "-" * 23)
    wilcoxon_results = run_wilcoxon_tests(df)

    # Hypothesis conclusions
    test_hypotheses(df, wilcoxon_results, friedman_result)

    # ------------------------------------------------------------------
    # Step 6: Publication-Quality Plots
    # ------------------------------------------------------------------
    _section("Step 6: Generating Publication-Quality Plots (8 figures)")
    t0 = time.time()
    generate_all_plots(df, friedman_result, nemenyi_result, wilcoxon_results)
    print(f"All plots generated in {_elapsed(t0)}")
    print(f"Plot directory: {PROJECT_ROOT / 'results' / 'plots'}")

    # ------------------------------------------------------------------
    # Summary
    # ------------------------------------------------------------------
    total = _elapsed(pipeline_start)
    print(f"\n{'='*70}")
    print(f"  Pipeline complete in {total}")
    print(f"  Results  -> {PROJECT_ROOT / 'results' / 'benchmark_results.csv'}")
    print(f"  Models   -> {PROJECT_ROOT / 'models'}/")
    print(f"  Plots    -> {PROJECT_ROOT / 'results' / 'plots'}/")
    print(f"  Log      -> {LOGS_DIR}/pipeline_{timestamp}.log")
    print(f"{'='*70}\n")


if __name__ == "__main__":
    # Required for Windows multiprocessing with spawn context
    import multiprocessing
    multiprocessing.freeze_support()
    main()
