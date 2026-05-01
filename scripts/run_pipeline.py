#!/usr/bin/env python3
"""scripts/run_pipeline.py — DAHS_2 End-to-End Training Pipeline.

Steps:
  1. Generate selector dataset (snapshot-fork)
  2. Generate priority dataset
  3. Train selector models (DT, RF, XGB)
  4. Train priority predictor (GBR)
  5. Run benchmark evaluation

Each step is followed by an *incremental* Hub snapshot so partial progress
survives even if the Space runtime is killed mid-pipeline.
"""
from __future__ import annotations

import argparse
import json
import logging
import os
import platform
import socket
import subprocess
import sys
import time
from datetime import datetime, timezone
from pathlib import Path

for _stream in ("stdout", "stderr"):
    try:
        getattr(sys, _stream).reconfigure(encoding="utf-8", errors="replace")
    except Exception:
        pass

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


def _git_sha() -> str:
    try:
        out = subprocess.check_output(
            ["git", "rev-parse", "HEAD"], cwd=ROOT, stderr=subprocess.DEVNULL
        )
        return out.decode().strip()
    except Exception:
        return "unknown"


def _pip_freeze_to(path: Path) -> None:
    try:
        out = subprocess.check_output([sys.executable, "-m", "pip", "freeze"])
        path.write_text(out.decode(), encoding="utf-8")
    except Exception as e:  # noqa: BLE001
        logger.warning("pip freeze failed: %s", e)


def _write_run_manifest(args: argparse.Namespace, n_scenarios: int, n_eval_seeds: int) -> None:
    manifest = {
        "started_at": datetime.now(timezone.utc).isoformat(),
        "git_sha": _git_sha(),
        "host": socket.gethostname(),
        "platform": platform.platform(),
        "python": sys.version,
        "cpu_count": os.cpu_count(),
        "args": vars(args),
        "n_scenarios": n_scenarios,
        "n_eval_seeds": n_eval_seeds,
        "env": {
            "REPO_ID": os.environ.get("REPO_ID"),
            "SPACE_ID": os.environ.get("SPACE_ID"),
            "HF_TOKEN_set": bool(os.environ.get("HF_TOKEN")),
        },
    }
    try:
        import sklearn, xgboost, scipy, numpy, pandas  # noqa: I001
        manifest["versions"] = {
            "sklearn": sklearn.__version__,
            "xgboost": xgboost.__version__,
            "scipy": scipy.__version__,
            "numpy": numpy.__version__,
            "pandas": pandas.__version__,
        }
    except Exception:
        pass
    (ROOT / "results" / "run_manifest.json").write_text(
        json.dumps(manifest, indent=2), encoding="utf-8"
    )
    _pip_freeze_to(ROOT / "results" / "pip_freeze.txt")


def main() -> None:
    parser = argparse.ArgumentParser(description="DAHS_2 Training Pipeline")
    parser.add_argument("--quick", action="store_true", help="Quick smoke test")
    parser.add_argument("--eval-only", action="store_true", help="Skip training, run eval only")
    parser.add_argument("--no-eval", action="store_true", help="Skip benchmark evaluation")
    parser.add_argument("--workers", type=int, default=4, help="Parallel workers")
    parser.add_argument("--scenarios", type=int, default=None, help="Override scenario count")
    parser.add_argument("--eval-seeds", type=int, default=None, help="Override eval seed count")
    parser.add_argument("--snapshot-every-step", action="store_true", default=True,
                        help="Push to HF Hub after each pipeline step")
    args = parser.parse_args()

    n_scenarios = args.scenarios or (50 if args.quick else 1000)
    n_eval_seeds = args.eval_seeds or (20 if args.quick else 1000)
    n_workers = args.workers

    t_start = time.time()

    # Bulletproof Hub persistence — no-op if env vars unset (local runs).
    from src.hf_persistence import from_env
    persistor = from_env(require=False)
    persistor.install_signal_handlers()
    persistor.install_atexit()
    persistor.start_periodic(interval_seconds=300)  # every 5 min

    _write_run_manifest(args, n_scenarios, n_eval_seeds)
    persistor.snapshot("results", msg="run_start manifest")

    print("\n" + "=" * 60)
    print("  DAHS 2.0 — Full Training & Evaluation Pipeline")
    print(f"  Scenarios: {n_scenarios} | Eval seeds: {n_eval_seeds} | Workers: {n_workers}")
    print("=" * 60)

    if not args.eval_only:
        # Step 1
        step(1, "Snapshot-Fork Selector Dataset")
        from src.data_generator import generate_selector_dataset
        t = time.time()
        df = generate_selector_dataset(n_scenarios=n_scenarios, n_workers=n_workers)
        logger.info("Selector dataset: %d rows in %.1fs", len(df), time.time() - t)
        print(f"  ✓ Selector dataset: {len(df):,} rows")
        persistor.snapshot("data", msg="selector_dataset")

        # Step 2
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
        persistor.snapshot("data", msg="priority_dataset")

        # Step 3
        step(3, "Train Selector Models (DT + RF + XGB)")
        from src.train_selector import train_selector_models
        t = time.time()
        selector_models = train_selector_models()
        logger.info("Selector training done in %.1fs", time.time() - t)
        print(f"  ✓ Trained: {list(selector_models.keys())}")
        persistor.snapshot("models", msg="selector_models")
        persistor.snapshot("results", msg="selector_metrics")

        # Step 4
        step(4, "Train Priority Predictor (GBR)")
        from src.train_priority import train_priority_model
        t = time.time()
        gbr = train_priority_model()
        logger.info("Priority training done in %.1fs", time.time() - t)
        print("  ✓ Priority GBR trained")
        persistor.snapshot("models", msg="priority_model")
        persistor.snapshot("results", msg="priority_metrics")

    # Step 5
    if not args.no_eval:
        step(5, "Benchmark Evaluation")
        from src.evaluator import run_full_evaluation
        t = time.time()
        eval_seeds = list(range(99000, 99000 + n_eval_seeds))
        results = run_full_evaluation(seeds=eval_seeds, n_workers=n_workers)
        logger.info("Evaluation done: %d seeds in %.1fs", n_eval_seeds, time.time() - t)
        print(f"  ✓ Evaluation complete ({n_eval_seeds} seeds)")
        persistor.snapshot("results", msg="evaluation")

        bench_df = results["benchmark"]
        if not bench_df.empty:
            print("\n  Performance Summary (mean total tardiness):")
            for method in sorted(bench_df["method"].unique()):
                mean_t = bench_df[bench_df["method"] == method]["total_tardiness"].mean()
                print(f"    {method:<22}: {mean_t:>8.1f}")

    elapsed = time.time() - t_start
    print(f"\n  Pipeline complete in {elapsed / 60:.1f} minutes.")
    print(f"  Artifacts: {ROOT / 'models'}, {ROOT / 'results'}, {ROOT / 'data'}")

    # Final consolidated snapshot
    persistor.stop_periodic()
    persistor.snapshot(msg=f"pipeline_complete_{int(elapsed)}s")


if __name__ == "__main__":
    main()
