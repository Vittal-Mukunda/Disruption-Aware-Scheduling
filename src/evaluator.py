"""
evaluator.py — Benchmark & Statistical Analysis Pipeline (DAHS_2)

Port from DAHS_1 evaluator.py + extensions:
  - 300 test seeds (99000-99299) × 9 methods
  - Statistical tests: Friedman, Nemenyi, Wilcoxon, Cohen's d, Bootstrap CI
  - NEW: Switching analysis (evaluations, switches, hysteresis rate, distribution)
  - NEW: JSON export for frontend Results page
  - 11 dark-theme plots

Statistical Methodology References
-----------------------------------
- Friedman non-parametric test for k ≥ 3 related samples:
    Friedman, M. (1940). A comparison of alternative tests of significance
    for the problem of m rankings. Annals of Mathematical Statistics, 11(1), 86-92.
    Recommended protocol for ML comparison:
    Demsar, J. (2006). Statistical comparisons of classifiers over multiple
    data sets. Journal of Machine Learning Research, 7, 1-30.

- Nemenyi post-hoc pairwise test (Critical Difference diagram):
    Nemenyi, P. (1963). Distribution-free multiple comparisons.
    PhD thesis, Princeton University.
    Applied per: Demsar (2006), JMLR 7:1-30.

- Wilcoxon signed-rank test (pairwise DAHS vs each baseline):
    Wilcoxon, F. (1945). Individual comparisons by ranking methods.
    Biometrics Bulletin, 1(6), 80-83. doi:10.2307/3001968.

- Cohen's d effect size:
    Cohen, J. (1988). Statistical Power Analysis for the Behavioral
    Sciences. Lawrence Erlbaum Associates (2nd ed.).
    d > 0.2 small, d > 0.5 medium, d > 0.8 large.

- Holm-Bonferroni multiple comparison correction:
    Holm, S. (1979). A simple sequentially rejective multiple test
    procedure. Scandinavian Journal of Statistics, 6(2), 65-70.

- Bootstrap 95% CI (5,000 resamples):
    Efron, B. & Tibshirani, R.J. (1993). An Introduction to the
    Bootstrap. Chapman & Hall.
"""

from __future__ import annotations

import json
import logging
import math
import warnings
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
import numpy as np
import pandas as pd
from scipy import stats

warnings.filterwarnings("ignore")

logger = logging.getLogger(__name__)

RESULTS_DIR = Path(__file__).parent.parent / "results"
PLOTS_DIR   = RESULTS_DIR / "plots"
MODELS_DIR  = Path(__file__).parent.parent / "models"

HEURISTIC_NAMES = ["fifo", "priority_edd", "critical_ratio", "atc", "wspt", "slack"]
HEURISTIC_LABELS = ["FIFO", "Priority-EDD", "Critical-Ratio", "ATC", "WSPT", "Slack"]

DARK_BG  = "#0f1117"
DARK_AX  = "#1a1d27"
TEXT_COL = "#e0e0e0"

COLORS = ["#4fc3f7", "#81c784", "#ffb74d", "#e57373", "#ce93d8", "#80cbc4",
          "#fff176", "#ff8a65", "#90caf9", "#f48fb1"]


def _dark_fig(figsize=(12, 7)):
    fig, ax = plt.subplots(figsize=figsize)
    fig.patch.set_facecolor(DARK_BG)
    ax.set_facecolor(DARK_AX)
    ax.tick_params(colors=TEXT_COL)
    ax.xaxis.label.set_color(TEXT_COL)
    ax.yaxis.label.set_color(TEXT_COL)
    ax.title.set_color(TEXT_COL)
    for spine in ax.spines.values():
        spine.set_color("#333344")
    return fig, ax


def _dark_fig_multi(rows=1, cols=2, figsize=(16, 7)):
    fig, axes = plt.subplots(rows, cols, figsize=figsize)
    fig.patch.set_facecolor(DARK_BG)
    for ax in np.array(axes).flatten():
        ax.set_facecolor(DARK_AX)
        ax.tick_params(colors=TEXT_COL)
        ax.xaxis.label.set_color(TEXT_COL)
        ax.yaxis.label.set_color(TEXT_COL)
        ax.title.set_color(TEXT_COL)
        for spine in ax.spines.values():
            spine.set_color("#333344")
    return fig, axes


def _norm_min_max(arr: np.ndarray) -> np.ndarray:
    r = arr.max() - arr.min()
    if r < 1e-10:
        return np.zeros_like(arr)
    return (arr - arr.min()) / r


# ---------------------------------------------------------------------------
# Benchmark runner
# ---------------------------------------------------------------------------

def run_benchmark(
    seeds: Optional[List[int]] = None,
    n_workers: int = 4,
    save_csv: bool = True,
) -> pd.DataFrame:
    """Run benchmark across all seeds × 9 methods.

    Methods:
      0-5: 6 baselines (FIFO, Priority-EDD, CR, ATC, WSPT, Slack)
      6: Hybrid-Priority (GBR)
      7: DAHS-RF (Random Forest selector)
      8: DAHS-XGB (XGBoost selector)
    """
    import multiprocessing as mp
    from tqdm import tqdm

    if seeds is None:
        seeds = list(range(99000, 99300))  # 300 test seeds

    RESULTS_DIR.mkdir(parents=True, exist_ok=True)
    PLOTS_DIR.mkdir(parents=True, exist_ok=True)

    logger.info("Running benchmark: %d seeds × 9 methods", len(seeds))

    all_args = [(seed,) for seed in seeds]

    rows = []
    ctx = mp.get_context("spawn")
    with ctx.Pool(processes=n_workers) as pool:
        for result in tqdm(
            pool.imap_unordered(_benchmark_single_seed, all_args),
            total=len(all_args),
            desc="Benchmark",
        ):
            rows.extend(result)

    df = pd.DataFrame(rows)
    logger.info("Benchmark complete: %s rows", len(df))

    if save_csv:
        path = RESULTS_DIR / "benchmark_results.csv"
        df.to_csv(path, index=False)
        logger.info("Saved -> %s", path)

    return df


def _row(seed: int, method: str, m: Any, elapsed: float) -> Dict[str, Any]:
    """Build one benchmark row from a SimulationMetrics + wall-clock seconds.

    Wall-clock matters for paper review: a method that wins on tardiness but
    is 50× slower than ATC isn't deployable. We capture it on every row so
    "DAHS adds X ms per dispatch" claims are backed by data, not asserted.
    """
    util_vals = list(m.zone_utilization.values())
    return {
        "seed": seed,
        "method": method,
        "makespan": m.makespan,
        "total_tardiness": m.total_tardiness,
        "sla_breach_rate": m.sla_breach_rate,
        "avg_cycle_time": m.avg_cycle_time,
        "zone_utilization_avg": float(np.mean(util_vals)) if util_vals else 0.0,
        "throughput": m.throughput,
        "queue_max": m.queue_max,
        "completed_jobs": m.completed_jobs,
        "elapsed_seconds": round(float(elapsed), 4),
    }


def _benchmark_single_seed(args: Tuple) -> List[Dict[str, Any]]:
    """Worker: run all methods on one seed and return their metric rows."""
    (seed,) = args
    import time as _time
    from src.heuristics import (
        fifo_dispatch, priority_edd_dispatch, critical_ratio_dispatch,
        atc_dispatch, wspt_dispatch, slack_dispatch,
    )
    from src.simulator import WarehouseSimulator
    from src.features import FeatureExtractor

    rows: List[Dict[str, Any]] = []
    methods = [
        ("fifo",           fifo_dispatch),
        ("priority_edd",   priority_edd_dispatch),
        ("critical_ratio", critical_ratio_dispatch),
        ("atc",            atc_dispatch),
        ("wspt",           wspt_dispatch),
        ("slack",          slack_dispatch),
    ]

    # Capture per-baseline tardiness/SLA/cycle/throughput on this seed so we
    # can synthesise a "best fixed heuristic in hindsight" row at the end.
    # An operator picking the post-hoc best fixed rule is the natural lower
    # bound any learned scheduler must beat.
    baseline_metrics: Dict[str, Any] = {}

    for method_name, heur_fn in methods:
        try:
            fe = FeatureExtractor()
            sim = WarehouseSimulator(seed=seed, heuristic_fn=heur_fn, feature_extractor=fe)
            t0 = _time.perf_counter()
            m = sim.run(duration=600.0)
            elapsed = _time.perf_counter() - t0
            rows.append(_row(seed, method_name, m, elapsed))
            baseline_metrics[method_name] = m
        except Exception as e:
            logger.warning("[%s] %s failed: %s", seed, method_name, e)

    # Best-fixed-in-hindsight oracle: minimum tardiness across the six fixed
    # rules. For non-tardiness metrics we copy the corresponding metric from
    # the same winning method so SLA/cycle/throughput stay self-consistent.
    if baseline_metrics:
        winner_name = min(
            baseline_metrics,
            key=lambda k: baseline_metrics[k].total_tardiness,
        )
        wm = baseline_metrics[winner_name]
        rows.append({
            **_row(seed, "best_fixed_oracle", wm, 0.0),
            "best_fixed_winner": winner_name,
        })

    # Try hybrid methods if models exist.
    # For each trained model we run TWO variants:
    #   dahs_{name}       — greedy ML only (BatchwiseSelector), ablation baseline
    #   dahs_hybrid_{name} — ML + rolling-horizon fork oracle (guarantees ≥ best fixed)
    for model_name in ("rf", "xgb"):
        model_path = MODELS_DIR / f"selector_{model_name}.joblib"
        if not model_path.exists():
            continue
        try:
            import joblib
            from src.hybrid_scheduler import BatchwiseSelector, RollingHorizonOracle

            model = joblib.load(model_path)

            # ── (a) ML-only (greedy) — shows ML alone is insufficient ─────
            fe = FeatureExtractor()
            selector = BatchwiseSelector(model=model, feature_extractor=fe)
            sim = WarehouseSimulator(seed=seed, heuristic_fn=fifo_dispatch, feature_extractor=fe)

            def make_dispatch(sel, s):
                def _dispatch(jobs, t, zone_id):
                    sel.update_state(s.get_state_snapshot())
                    return sel.dispatch(jobs, t, zone_id)
                return _dispatch

            sim.heuristic_fn = make_dispatch(selector, sim)
            t0 = _time.perf_counter()
            m = sim.run(duration=600.0)
            rows.append(_row(seed, f"dahs_{model_name}", m, _time.perf_counter() - t0))

            # ── (b) Hybrid = ML prior + fork oracle (the guarantee) ────────
            fe2 = FeatureExtractor()
            oracle = RollingHorizonOracle(ml_model=model, feature_extractor=fe2)
            sim2 = WarehouseSimulator(seed=seed, heuristic_fn=fifo_dispatch, feature_extractor=fe2)
            oracle.attach_simulator(sim2)
            sim2.heuristic_fn = lambda jobs, t, z: oracle.dispatch(jobs, t, z)
            t0 = _time.perf_counter()
            m2 = sim2.run(duration=600.0)
            rows.append(_row(seed, f"dahs_hybrid_{model_name}", m2, _time.perf_counter() - t0))
        except Exception as e:
            logger.warning("[%s] dahs_%s failed: %s", seed, model_name, e)

    # ── DAHS-Oracle: pure fork oracle, no ML (theoretical ceiling) ──────
    try:
        from src.hybrid_scheduler import RollingHorizonOracle

        feo = FeatureExtractor()
        oracle = RollingHorizonOracle(ml_model=None, feature_extractor=None)
        simo = WarehouseSimulator(seed=seed, heuristic_fn=fifo_dispatch, feature_extractor=feo)
        oracle.attach_simulator(simo)
        simo.heuristic_fn = lambda jobs, t, z: oracle.dispatch(jobs, t, z)
        t0 = _time.perf_counter()
        mo = simo.run(duration=600.0)
        rows.append(_row(seed, "dahs_oracle", mo, _time.perf_counter() - t0))
    except Exception as e:
        logger.warning("[%s] dahs_oracle failed: %s", seed, e)

    # Priority hybrid (per-job GBR scorer). NOTE: held last in the headline
    # priority list because its training CV R² was 0.022 ± 0.717 — keep it
    # in the benchmark for completeness/ablation but do not let it lead.
    priority_path = MODELS_DIR / "priority_gbr.joblib"
    if priority_path.exists():
        try:
            import joblib
            from src.hybrid_scheduler import HybridPriority

            fe = FeatureExtractor()
            priority = HybridPriority(model_path=priority_path, feature_extractor=fe)
            sim = WarehouseSimulator(seed=seed, heuristic_fn=fifo_dispatch, feature_extractor=fe)

            def _priority_dispatch(jobs, t, zone_id):
                priority.update_state(sim.get_state_snapshot())
                return priority(jobs, t, zone_id)

            sim.heuristic_fn = _priority_dispatch
            t0 = _time.perf_counter()
            m = sim.run(duration=600.0)
            rows.append(_row(seed, "hybrid_priority", m, _time.perf_counter() - t0))
        except Exception as e:
            logger.warning("[%s] hybrid_priority failed: %s", seed, e)

    return rows


# ---------------------------------------------------------------------------
# Statistical analysis
# ---------------------------------------------------------------------------

# Direction of preference per metric. "lower" means smaller value is better
# (e.g. tardiness, SLA breach, cycle time); "higher" means larger is better
# (throughput, utilization). Used to set the alternative for the one-sided
# Wilcoxon and to sign Cohen's d so a positive value always means "DAHS wins."
METRIC_DIRECTIONS: Dict[str, str] = {
    "total_tardiness":      "lower",
    "sla_breach_rate":      "lower",
    "avg_cycle_time":       "lower",
    "makespan":             "lower",
    "throughput":           "higher",
    "zone_utilization_avg": "higher",
}


def _wilcoxon_for_metric(
    pivot: pd.DataFrame,
    available_methods: List[str],
    dahs_col: str,
    metric: str,
    direction: str,
) -> List[Dict[str, Any]]:
    """One-sided Wilcoxon DAHS-vs-baseline for a single metric.

    Lower-is-better metrics test H1: baseline > DAHS, so a small p-value means
    DAHS is significantly *lower* (better). Higher-is-better metrics test
    H1: DAHS > baseline. `diff` is always (better-side - worse-side) so the
    resulting Cohen's d is positive when DAHS wins, negative when it loses.
    Holm-Bonferroni is applied within each metric family by the caller.
    """
    rows: List[Dict[str, Any]] = []
    if dahs_col not in pivot.columns:
        return rows
    dahs_vals = pivot[dahs_col].values
    for method in available_methods:
        if method == dahs_col:
            continue
        try:
            base_vals = pivot[method].values
            if direction == "lower":
                stat, p = stats.wilcoxon(base_vals, dahs_vals, alternative="greater")
                diff = base_vals - dahs_vals
            else:
                stat, p = stats.wilcoxon(dahs_vals, base_vals, alternative="greater")
                diff = dahs_vals - base_vals
            d = float(np.mean(diff) / (np.std(diff) + 1e-10))
            boot_means = [
                np.mean(np.random.choice(diff, size=len(diff), replace=True))
                for _ in range(5000)
            ]
            ci_lo, ci_hi = np.percentile(boot_means, [2.5, 97.5])
            rows.append({
                "metric": metric,
                "direction": direction,
                "baseline": method,
                "dahs": dahs_col,
                "statistic": round(float(stat), 4),
                "p_value": float(p),
                "significant_holm": False,
                "cohens_d": round(d, 4),
                "ci_95_lo": round(float(ci_lo), 4),
                "ci_95_hi": round(float(ci_hi), 4),
            })
        except Exception as exc:
            logger.warning("Wilcoxon failed for %s on %s: %s", method, metric, exc)
    if rows:
        ps = [r["p_value"] for r in rows]
        n = len(ps)
        order = np.argsort(ps)
        for rank, idx in enumerate(order):
            rows[idx]["significant_holm"] = ps[idx] < (0.05 / (n - rank))
    return rows


def _nemenyi_critical_difference(k: int, n: int, alpha: float = 0.05) -> float:
    """Nemenyi critical-difference for k methods over n datasets at alpha=0.05.

    CD = q_alpha * sqrt(k*(k+1) / (6*n)) per Demsar (2006), JMLR 7:1-30.
    """
    Q_05 = {
        2: 1.960, 3: 2.343, 4: 2.569, 5: 2.728, 6: 2.850, 7: 2.949,
        8: 3.031, 9: 3.102, 10: 3.164,
    }
    q = Q_05.get(k, Q_05[10] + 0.05 * (k - 10))
    return float(q * math.sqrt(k * (k + 1) / (6.0 * n)))


def _nemenyi_pairwise(pivot: pd.DataFrame, available_methods: List[str]) -> Dict[str, Any]:
    """Nemenyi pairwise comparisons + critical difference for the primary metric."""
    if len(available_methods) < 3 or pivot.shape[0] < 2:
        return {"available": False, "reason": "need >=3 methods and >=2 seeds"}

    ranks = pivot[available_methods].rank(axis=1, method="average")
    mean_ranks = ranks.mean(axis=0).to_dict()
    n_seeds = ranks.shape[0]
    k = len(available_methods)
    cd = _nemenyi_critical_difference(k, n_seeds)

    matrix: List[Dict[str, Any]] = []
    for i, mi in enumerate(available_methods):
        for j, mj in enumerate(available_methods):
            if j <= i:
                continue
            diff = abs(mean_ranks[mi] - mean_ranks[mj])
            matrix.append({
                "method_a": mi,
                "method_b": mj,
                "rank_a": round(float(mean_ranks[mi]), 4),
                "rank_b": round(float(mean_ranks[mj]), 4),
                "rank_diff": round(float(diff), 4),
                "significant": bool(diff > cd),
            })
    return {
        "available": True,
        "alpha": 0.05,
        "k": k,
        "n_seeds": n_seeds,
        "critical_difference": round(cd, 4),
        "mean_ranks": {m: round(float(r), 4) for m, r in mean_ranks.items()},
        "pairwise": matrix,
    }


def _plot_critical_difference_diagram(nemenyi: Dict[str, Any]) -> None:
    """Render a Demsar-style critical-difference diagram at results/plots/cd_diagram.png."""
    if not nemenyi.get("available"):
        return
    mean_ranks: Dict[str, float] = nemenyi["mean_ranks"]
    cd: float = nemenyi["critical_difference"]
    methods = sorted(mean_ranks.keys(), key=lambda m: mean_ranks[m])
    ranks = [mean_ranks[m] for m in methods]
    k = len(methods)

    PLOTS_DIR.mkdir(parents=True, exist_ok=True)
    fig, ax = _dark_fig(figsize=(12, 4 + 0.3 * k))
    rank_min = min(ranks) - 0.5
    rank_max = max(ranks) + 0.5
    ax.set_xlim(rank_min, rank_max)
    ax.set_ylim(0, k + 1)
    ax.invert_xaxis()
    ax.get_yaxis().set_visible(False)
    for side in ("left", "right", "top"):
        ax.spines[side].set_visible(False)

    for i, m in enumerate(methods):
        y = k - i
        x = mean_ranks[m]
        ax.plot([rank_min, x], [y, y], color="#445", linewidth=0.75)
        ax.plot([x], [y], "o", color=COLORS[i % len(COLORS)], markersize=8)
        ax.text(rank_min - 0.05 * (rank_max - rank_min), y,
                f"{m}  (rank {x:.2f})",
                ha="right", va="center", color=TEXT_COL, fontsize=10)

    cd_y = 0.5
    ax.plot([min(ranks), min(ranks) + cd], [cd_y, cd_y], color="#e57373", linewidth=2.5)
    ax.text(min(ranks) + cd / 2, cd_y - 0.25,
            f"CD = {cd:.3f} (Nemenyi, α=0.05)",
            ha="center", va="top", color="#e57373", fontsize=10)

    ax.set_xlabel("Mean rank (lower = better)")
    ax.set_title("Critical-Difference Diagram — total_tardiness", color=TEXT_COL, fontsize=13)
    plt.tight_layout()
    plt.savefig(PLOTS_DIR / "cd_diagram.png", dpi=150, facecolor=DARK_BG)
    plt.close()


def run_statistical_analysis(df: pd.DataFrame) -> Dict[str, Any]:
    """Run Friedman, Nemenyi post-hoc, direction-aware Wilcoxon, Cohen's d.

    See Demsar (2006) JMLR 7:1-30 for the full protocol. The Wilcoxon test is
    direction-aware: for lower-is-better metrics the alternative is
    H1: baseline > DAHS; for higher-is-better metrics it is H1: DAHS > baseline.
    Cohen's d is signed so positive d always means DAHS wins.
    Holm-Bonferroni controls FWER within each metric family.
    """
    methods = sorted(df["method"].unique())

    primary_metric = "total_tardiness"
    pivot = df.pivot_table(index="seed", columns="method", values=primary_metric)
    pivot.dropna(inplace=True)

    available_methods = [m for m in methods if m in pivot.columns]

    results: Dict[str, Any] = {"primary_metric": primary_metric}

    try:
        data_arrays = [pivot[m].values for m in available_methods]
        stat, p = stats.friedmanchisquare(*data_arrays)
        results["friedman"] = {
            "statistic": round(float(stat), 4),
            "p_value": float(p),
            "significant": bool(p < 0.05),
            "metric": primary_metric,
        }
        logger.info("Friedman test: chi2=%.4f, p=%.6f", stat, p)
    except Exception as e:
        results["friedman"] = {"error": str(e)}

    try:
        nemenyi = _nemenyi_pairwise(pivot, available_methods)
        results["nemenyi"] = nemenyi
        if nemenyi.get("available"):
            _plot_critical_difference_diagram(nemenyi)
            logger.info("Nemenyi: CD=%.4f over k=%d methods, n=%d seeds",
                        nemenyi["critical_difference"], nemenyi["k"], nemenyi["n_seeds"])
    except Exception as e:
        results["nemenyi"] = {"error": str(e)}

    # Pick the headline DAHS column. Order = best evidence first:
    #   1. dahs_hybrid_*  — ML prior + rolling-horizon fork oracle, the
    #                       method we want the paper to highlight (guarantees
    #                       at least best-fixed in expectation).
    #   2. dahs_oracle    — pure fork oracle, the upper-bound ablation.
    #   3. dahs_*         — greedy ML-only (BatchwiseSelector) ablation.
    #   4. hybrid_priority — per-job GBR scorer; held LAST because its
    #                        training CV R² was 0.022 ± 0.717. Keep it in
    #                        the benchmark for completeness but do not let
    #                        it lead headline numbers until regularised.
    _priority = [
        "dahs_hybrid_xgb", "dahs_hybrid_rf",
        "dahs_oracle",
        "dahs_xgb", "dahs_rf",
        "hybrid_priority",
    ]
    dahs_col = next((c for c in _priority if c in available_methods), None)
    results["headline_method"] = dahs_col
    if dahs_col is None:
        results["wilcoxon"] = []
        results["wilcoxon_secondary"] = {}
        results["per_seed_dominance"] = {}
    else:
        results["wilcoxon"] = _wilcoxon_for_metric(
            pivot, available_methods, dahs_col,
            primary_metric, METRIC_DIRECTIONS[primary_metric],
        )

        # Per-seed dominance: on what fraction of seeds does the headline
        # DAHS method beat each baseline on tardiness? This is the honest
        # answer to the "does it win on every seed" question.
        dominance: Dict[str, Any] = {"n_seeds": int(pivot.shape[0])}
        per_baseline: Dict[str, Dict[str, Any]] = {}
        beats_strongest_seeds = 0
        # Identify "best baseline per seed" so we can compute win-rate vs
        # the per-seed best fixed rule (the hardest comparison).
        baseline_only = [m for m in available_methods
                         if m not in (
                             "dahs_xgb", "dahs_rf",
                             "dahs_hybrid_xgb", "dahs_hybrid_rf",
                             "dahs_oracle", "hybrid_priority",
                             "best_fixed_oracle",
                         )]
        for method in available_methods:
            if method == dahs_col:
                continue
            wins = int((pivot[dahs_col] < pivot[method]).sum())
            ties = int((pivot[dahs_col] == pivot[method]).sum())
            per_baseline[method] = {
                "wins": wins,
                "ties": ties,
                "losses": int(pivot.shape[0] - wins - ties),
                "win_rate": round(wins / max(pivot.shape[0], 1), 4),
            }
        if baseline_only:
            best_per_seed = pivot[baseline_only].min(axis=1)
            beats_strongest_seeds = int((pivot[dahs_col] < best_per_seed).sum())
            dominance["wins_vs_best_fixed_per_seed"] = beats_strongest_seeds
            dominance["win_rate_vs_best_fixed_per_seed"] = round(
                beats_strongest_seeds / max(pivot.shape[0], 1), 4
            )
        dominance["per_baseline"] = per_baseline
        results["per_seed_dominance"] = dominance
        secondary: Dict[str, List[Dict[str, Any]]] = {}
        for metric, direction in METRIC_DIRECTIONS.items():
            if metric == primary_metric:
                continue
            piv_m = df.pivot_table(index="seed", columns="method", values=metric).dropna()
            avail_m = [m for m in methods if m in piv_m.columns]
            if dahs_col not in avail_m:
                continue
            secondary[metric] = _wilcoxon_for_metric(
                piv_m, avail_m, dahs_col, metric, direction
            )
        results["wilcoxon_secondary"] = secondary

    summary = []
    for method in available_methods:
        method_df = df[df["method"] == method]
        summary.append({
            "method": method,
            "n": len(method_df),
            "makespan_mean": round(float(method_df["makespan"].mean()), 2),
            "makespan_std": round(float(method_df["makespan"].std()), 2),
            "tardiness_mean": round(float(method_df["total_tardiness"].mean()), 2),
            "tardiness_std": round(float(method_df["total_tardiness"].std()), 2),
            "sla_mean": round(float(method_df["sla_breach_rate"].mean()), 4),
            "cycle_mean": round(float(method_df["avg_cycle_time"].mean()), 2),
            "throughput_mean": round(float(method_df["throughput"].mean()), 2),
        })
    results["summary"] = summary

    RESULTS_DIR.mkdir(parents=True, exist_ok=True)
    with open(RESULTS_DIR / "statistical_tests.json", "w") as f:
        json.dump(results, f, indent=2)
    logger.info("Saved statistical_tests.json")

    return results


# ---------------------------------------------------------------------------
# Switching analysis (NEW in DAHS_2)
# ---------------------------------------------------------------------------

def run_switching_analysis(df: pd.DataFrame) -> Dict[str, Any]:
    """Analyze DAHS switching behavior by running sample seeds with switching logs enabled."""
    from src.heuristics import fifo_dispatch
    from src.simulator import WarehouseSimulator
    from src.features import FeatureExtractor
    from src.hybrid_scheduler import BatchwiseSelector
    import joblib as _joblib

    RESULTS_DIR.mkdir(parents=True, exist_ok=True)

    sample_seeds = list(range(99000, 99010))  # 10 representative seeds
    per_model: Dict[str, Any] = {}

    for model_name in ("rf", "xgb"):
        model_path = MODELS_DIR / f"selector_{model_name}.joblib"
        if not model_path.exists():
            logger.warning("Model not found: %s", model_path)
            continue

        model = _joblib.load(model_path)
        total_evals = 0
        total_switches = 0
        total_hysteresis = 0
        total_guardrails = 0
        heuristic_counts: Dict[str, int] = {}

        for seed in sample_seeds:
            try:
                fe = FeatureExtractor()
                selector = BatchwiseSelector(model=model, feature_extractor=fe)

                sim = WarehouseSimulator(seed=seed, heuristic_fn=fifo_dispatch, feature_extractor=fe)

                def _make_dispatch(sel, s):
                    def _d(jobs, t, zone_id):
                        sel.update_state(s.get_state_snapshot())
                        return sel.dispatch(jobs, t, zone_id)
                    return _d

                sim.heuristic_fn = _make_dispatch(selector, sim)
                sim.run(duration=600.0)

                summary = selector.switching_log.summary()
                n_evals = summary.get("totalEvaluations", 0)
                total_evals += n_evals
                total_switches += summary.get("switchCount", 0)
                total_hysteresis += summary.get("hysteresisBlocked", 0)
                total_guardrails += summary.get("guardrailActivations", 0)
                for h, frac in summary.get("distribution", {}).items():
                    heuristic_counts[h] = heuristic_counts.get(h, 0) + int(round(n_evals * frac))

            except Exception as e:
                logger.warning("Switching analysis seed %d (%s) failed: %s", seed, model_name, e)

        n = len(sample_seeds)
        total_h = sum(heuristic_counts.values())
        per_model[f"dahs_{model_name}"] = {
            "sample_seeds": n,
            "avg_evaluations_per_run": round(total_evals / max(n, 1), 1),
            "avg_switches_per_run": round(total_switches / max(n, 1), 1),
            "avg_hysteresis_blocked_per_run": round(total_hysteresis / max(n, 1), 1),
            "avg_guardrail_activations_per_run": round(total_guardrails / max(n, 1), 1),
            "switching_rate_per_interval": round(total_switches / max(total_evals - n, 1), 4),
            "heuristic_selection_distribution": {
                h: round(c / max(total_h, 1), 4)
                for h, c in sorted(heuristic_counts.items())
            },
        }

    analysis = {
        "description": "DAHS_2 batch-wise switching analysis (15-min intervals)",
        **per_model,
    }

    with open(RESULTS_DIR / "switching_analysis.json", "w") as f:
        json.dump(analysis, f, indent=2)
    logger.info("Saved switching_analysis.json")

    return analysis


# ---------------------------------------------------------------------------
# JSON export for frontend
# ---------------------------------------------------------------------------

def export_benchmark_json(df: pd.DataFrame) -> None:
    """Export summary JSON for the Results page frontend."""
    RESULTS_DIR.mkdir(parents=True, exist_ok=True)

    methods = sorted(df["method"].unique())
    summary = []
    for method in methods:
        mdf = df[df["method"] == method]
        summary.append({
            "method": method,
            "n": len(mdf),
            "tardiness": {"mean": float(mdf["total_tardiness"].mean()), "std": float(mdf["total_tardiness"].std())},
            "sla": {"mean": float(mdf["sla_breach_rate"].mean()), "std": float(mdf["sla_breach_rate"].std())},
            "cycle": {"mean": float(mdf["avg_cycle_time"].mean()), "std": float(mdf["avg_cycle_time"].std())},
            "throughput": {"mean": float(mdf["throughput"].mean()), "std": float(mdf["throughput"].std())},
            "makespan": {"mean": float(mdf["makespan"].mean()), "std": float(mdf["makespan"].std())},
        })

    with open(RESULTS_DIR / "benchmark_summary.json", "w") as f:
        json.dump(summary, f, indent=2)
    logger.info("Saved benchmark_summary.json")


# ---------------------------------------------------------------------------
# Plots (11 dark-theme plots)
# ---------------------------------------------------------------------------

def generate_plots(df: pd.DataFrame) -> None:
    """Generate all 11 dark-theme benchmark plots."""
    PLOTS_DIR.mkdir(parents=True, exist_ok=True)

    methods = sorted(df["method"].unique())
    method_colors = {m: COLORS[i % len(COLORS)] for i, m in enumerate(methods)}

    # 1. Tardiness boxplot
    fig, ax = _dark_fig(figsize=(14, 7))
    data_by_method = [df[df["method"] == m]["total_tardiness"].dropna().values for m in methods]
    bp = ax.boxplot(data_by_method, labels=methods, patch_artist=True)
    for patch, method in zip(bp["boxes"], methods):
        patch.set_facecolor(method_colors[method])
        patch.set_alpha(0.75)
    ax.set_title("Total Tardiness — All Methods", fontsize=14)
    ax.set_xlabel("Method")
    ax.set_ylabel("Total Tardiness (min)")
    ax.tick_params(axis="x", rotation=35)
    plt.tight_layout()
    plt.savefig(PLOTS_DIR / "benchmark_tardiness.png", dpi=150, facecolor=DARK_BG)
    plt.close()

    # 2. SLA breach bar chart
    fig, ax = _dark_fig(figsize=(12, 6))
    sla_means = [df[df["method"] == m]["sla_breach_rate"].mean() * 100 for m in methods]
    bars = ax.bar(methods, sla_means, color=[method_colors[m] for m in methods], alpha=0.85)
    ax.set_title("Average SLA Breach Rate", fontsize=14)
    ax.set_ylabel("SLA Breach Rate (%)")
    ax.tick_params(axis="x", rotation=35)
    for bar, val in zip(bars, sla_means):
        ax.text(bar.get_x() + bar.get_width() / 2, bar.get_height() + 0.3,
                f"{val:.1f}%", ha="center", va="bottom", color=TEXT_COL, fontsize=9)
    plt.tight_layout()
    plt.savefig(PLOTS_DIR / "sla_breach_bar.png", dpi=150, facecolor=DARK_BG)
    plt.close()

    # 3. Zone utilization heatmap
    try:
        fig, ax = _dark_fig(figsize=(10, 6))
        util_data = []
        for m in methods:
            mdf = df[df["method"] == m]
            util_data.append([mdf["zone_utilization_avg"].mean()])
        import seaborn as sns
        sns.set_style("dark")
        hm = ax.imshow([[v[0] for v in util_data]], aspect="auto", cmap="coolwarm")
        ax.set_xticks(range(len(methods)))
        ax.set_xticklabels(methods, rotation=35)
        ax.set_yticklabels(["Avg Util"])
        plt.colorbar(hm, ax=ax, label="Zone Utilization")
        ax.set_title("Zone Utilization Heatmap", fontsize=14)
        plt.tight_layout()
        plt.savefig(PLOTS_DIR / "zone_utilization_heatmap.png", dpi=150, facecolor=DARK_BG)
        plt.close()
    except Exception:
        pass

    # 4. Radar chart
    try:
        categories = ["Tardiness↓", "SLA↓", "Cycle Time↓", "Throughput↑", "Utilization"]
        n_cats = len(categories)
        angles = np.linspace(0, 2 * np.pi, n_cats, endpoint=False).tolist()
        angles += angles[:1]

        fig = plt.figure(figsize=(10, 10))
        fig.patch.set_facecolor(DARK_BG)
        ax = fig.add_subplot(111, polar=True)
        ax.set_facecolor(DARK_AX)

        for i, method in enumerate(methods[:6]):
            mdf = df[df["method"] == method]
            values = [
                1 - float(np.clip(mdf["total_tardiness"].mean() / max(df["total_tardiness"].max(), 1e-9), 0, 1)),
                1 - float(mdf["sla_breach_rate"].mean()),
                1 - float(np.clip(mdf["avg_cycle_time"].mean() / df["avg_cycle_time"].max(), 0, 1)),
                float(np.clip(mdf["throughput"].mean() / df["throughput"].max(), 0, 1)),
                float(mdf["zone_utilization_avg"].mean()),
            ]
            values += values[:1]
            ax.plot(angles, values, color=COLORS[i], linewidth=2, label=method)
            ax.fill(angles, values, color=COLORS[i], alpha=0.1)

        ax.set_xticks(angles[:-1])
        ax.set_xticklabels(categories, color=TEXT_COL)
        ax.legend(loc="upper right", bbox_to_anchor=(1.3, 1.1))
        ax.set_title("Performance Radar Chart", color=TEXT_COL, fontsize=14, pad=20)
        plt.tight_layout()
        plt.savefig(PLOTS_DIR / "radar_chart.png", dpi=150, facecolor=DARK_BG)
        plt.close()
    except Exception:
        pass

    # 5. Pareto front (makespan vs tardiness)
    fig, ax = _dark_fig(figsize=(10, 7))
    for method in methods:
        mdf = df[df["method"] == method]
        ax.scatter(
            mdf["makespan"].mean(),
            mdf["total_tardiness"].mean(),
            color=method_colors[method],
            s=120, label=method, zorder=5,
        )
    ax.set_title("Pareto Front: Makespan vs Tardiness", fontsize=14)
    ax.set_xlabel("Mean Makespan (min)")
    ax.set_ylabel("Mean Total Tardiness (min)")
    ax.legend(facecolor=DARK_AX, labelcolor=TEXT_COL)
    plt.tight_layout()
    plt.savefig(PLOTS_DIR / "pareto_front.png", dpi=150, facecolor=DARK_BG)
    plt.close()

    # 6. Throughput comparison
    fig, ax = _dark_fig(figsize=(12, 6))
    thru_means = [df[df["method"] == m]["throughput"].mean() for m in methods]
    ax.bar(methods, thru_means, color=[method_colors[m] for m in methods], alpha=0.85)
    ax.set_title("Average Throughput (jobs/hour)", fontsize=14)
    ax.set_ylabel("Throughput (jobs/hr)")
    ax.tick_params(axis="x", rotation=35)
    plt.tight_layout()
    plt.savefig(PLOTS_DIR / "throughput_comparison.png", dpi=150, facecolor=DARK_BG)
    plt.close()

    logger.info("Generated plots in %s", PLOTS_DIR)


# ---------------------------------------------------------------------------
# Full evaluation pipeline
# ---------------------------------------------------------------------------

def run_full_evaluation(
    seeds: Optional[List[int]] = None,
    n_workers: int = 4,
) -> Dict[str, Any]:
    """Run complete evaluation: benchmark + stats + plots + JSON export."""
    df = run_benchmark(seeds=seeds, n_workers=n_workers)
    stats_results = run_statistical_analysis(df)
    switching = run_switching_analysis(df)
    export_benchmark_json(df)
    generate_plots(df)

    return {
        "benchmark": df,
        "stats": stats_results,
        "switching": switching,
    }


if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
    # Quick test with 20 seeds
    run_full_evaluation(seeds=list(range(99000, 99020)), n_workers=2)
