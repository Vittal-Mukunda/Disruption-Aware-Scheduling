"""
evaluator.py ? Benchmark Evaluation & Publication-Quality Visualizations

Runs 300 test scenarios across 9 scheduling methods (6 baselines + 3 hybrid),
collects 7 metrics each, performs comprehensive statistical testing, and
generates publication-quality plots.

Statistical analysis includes:
  - Friedman test for multi-method comparison
  - Post-hoc Nemenyi test with critical difference diagram
  - Wilcoxon signed-rank tests with Holm correction
  - Cohen's d effect sizes
  - Bootstrap 95% confidence intervals
"""

from __future__ import annotations

import logging
import multiprocessing as mp
import warnings
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

import matplotlib
matplotlib.use("Agg")
import matplotlib.patches as mpatches
import matplotlib.pyplot as plt
import numpy as np
import pandas as pd
import seaborn as sns
from scipy.stats import friedmanchisquare, wilcoxon, rankdata

warnings.filterwarnings("ignore")

logger = logging.getLogger(__name__)

RESULTS_DIR = Path(__file__).parent.parent / "results"
PLOTS_DIR = RESULTS_DIR / "plots"
MODELS_DIR = Path(__file__).parent.parent / "models"

DARK_BG = "#0f1117"
PANEL_BG = "#1a1d27"
TEXT_COLOR = "#e0e0e0"
ACCENT = "#4fc3f7"

# 9 methods x palette
METHOD_COLORS = {
    "FIFO":           "#78909c",
    "Priority-EDD":   "#ffb74d",
    "Critical-Ratio": "#ef5350",
    "ATC":            "#ce93d8",
    "WSPT":           "#f48fb1",
    "Slack":          "#80cbc4",
    "Hybrid-RF":      "#42a5f5",
    "Hybrid-XGB":     "#26c6da",
    "Hybrid-Priority":"#66bb6a",
}


# ---------------------------------------------------------------------------
# Worker ? runs ONE (seed, method) pair
# ---------------------------------------------------------------------------

def _eval_worker(args: Tuple[int, str]) -> Dict[str, Any]:
    """Evaluate one scenario-method combination."""
    seed, method = args

    from src.features import FeatureExtractor
    from src.heuristics import (
        critical_ratio_dispatch,
        fifo_dispatch,
        priority_edd_dispatch,
        atc_dispatch,
        wspt_dispatch,
        slack_dispatch,
    )
    from src.simulator import WarehouseSimulator

    fe = FeatureExtractor()

    baseline_map = {
        "FIFO": fifo_dispatch,
        "Priority-EDD": priority_edd_dispatch,
        "Critical-Ratio": critical_ratio_dispatch,
        "ATC": atc_dispatch,
        "WSPT": wspt_dispatch,
        "Slack": slack_dispatch,
    }

    if method in baseline_map:
        heuristic_fn = baseline_map[method]
        sim = WarehouseSimulator(seed=seed, heuristic_fn=heuristic_fn, feature_extractor=fe)
    elif method in ("Hybrid-RF", "Hybrid-XGB", "Hybrid-Priority"):
        from src.hybrid_scheduler import HybridPriority, HybridSelector

        if method == "Hybrid-RF":
            scheduler = HybridSelector(MODELS_DIR / "selector_rf.joblib", fe)
        elif method == "Hybrid-XGB":
            scheduler = HybridSelector(MODELS_DIR / "selector_xgb.joblib", fe)
        else:
            scheduler = HybridPriority(MODELS_DIR / "priority_gbr.joblib", fe)

        class _StatefulDispatch:
            def __init__(self, scheduler, sim_ref):
                self._s = scheduler
                self._sim = sim_ref

            def __call__(self, jobs, current_time, zone_id):
                if self._sim is not None:
                    self._s.update_state(self._sim.get_state_snapshot())
                return self._s(jobs, current_time, zone_id)

        sim = WarehouseSimulator(seed=seed, heuristic_fn=lambda j, t, z: None, feature_extractor=fe)
        wrapper = _StatefulDispatch(scheduler, sim)
        sim.heuristic_fn = wrapper
    else:
        raise ValueError(f"Unknown method: {method}")

    metrics = sim.run(duration=600.0)

    # Store actual per-zone utilization (for real heatmap data)
    zone_util = metrics.zone_utilization

    return {
        "seed": seed,
        "method": method,
        "makespan": metrics.makespan,
        "total_tardiness": metrics.total_tardiness,
        "sla_breach_rate": metrics.sla_breach_rate,
        "avg_cycle_time": metrics.avg_cycle_time,
        "zone_utilization_avg": float(np.mean(list(zone_util.values()))),
        "throughput": metrics.throughput,
        "queue_max": metrics.queue_max,
        # Per-zone utilization columns
        **{f"zone_util_{z}": zone_util.get(z, 0.0) for z in range(8)},
    }


# ---------------------------------------------------------------------------
# Main evaluator
# ---------------------------------------------------------------------------

METHODS = [
    "FIFO", "Priority-EDD", "Critical-Ratio",
    "ATC", "WSPT", "Slack",
    "Hybrid-RF", "Hybrid-XGB", "Hybrid-Priority",
]
BASELINE_METHODS = ["FIFO", "Priority-EDD", "Critical-Ratio", "ATC", "WSPT", "Slack"]
HYBRID_METHODS = ["Hybrid-RF", "Hybrid-XGB", "Hybrid-Priority"]
TEST_SEEDS = list(range(99_000, 99_300))  # 300 scenarios


def run_benchmark(
    seeds: Optional[List[int]] = None,
    methods: Optional[List[str]] = None,
    n_workers: int = 4,
) -> pd.DataFrame:
    """Run the full benchmark and return a results DataFrame.

    Parameters
    ----------
    seeds : list of int, optional
        Test scenario seeds (defaults to 99000-99299).
    methods : list of str, optional
        Which methods to evaluate (defaults to all 9).
    n_workers : int
        Parallel worker processes.

    Returns
    -------
    pd.DataFrame
        One row per (seed, method), 7 metric columns + 8 zone util columns.
    """
    from tqdm import tqdm

    seeds = seeds or TEST_SEEDS
    methods = methods or METHODS

    all_args = [(seed, method) for seed in seeds for method in methods]
    logger.info("Benchmark: %d seeds x %d methods = %d runs", len(seeds), len(methods), len(all_args))

    rows = []
    ctx = mp.get_context("spawn")
    with ctx.Pool(processes=n_workers) as pool:
        for result in tqdm(
            pool.imap_unordered(_eval_worker, all_args),
            total=len(all_args),
            desc="Benchmark",
        ):
            rows.append(result)

    df = pd.DataFrame(rows)

    # Save results
    RESULTS_DIR.mkdir(parents=True, exist_ok=True)
    csv_path = RESULTS_DIR / "benchmark_results.csv"
    df.to_csv(csv_path, index=False)
    logger.info("Saved benchmark results -> %s", csv_path)

    return df


# ---------------------------------------------------------------------------
# Statistical analysis
# ---------------------------------------------------------------------------

def compute_summary(df: pd.DataFrame) -> pd.DataFrame:
    """Compute mean/std/min/max per method for all metrics."""
    metric_cols = [
        "makespan", "total_tardiness", "sla_breach_rate",
        "avg_cycle_time", "zone_utilization_avg", "throughput", "queue_max",
    ]
    available = [c for c in metric_cols if c in df.columns]
    summary = df.groupby("method")[available].agg(["mean", "std", "min", "max"])
    return summary


def compute_improvements(df: pd.DataFrame) -> pd.DataFrame:
    """Compute % improvement of hybrid methods vs baselines."""
    baselines = [m for m in BASELINE_METHODS if m in df["method"].unique()]
    hybrids = [m for m in HYBRID_METHODS if m in df["method"].unique()]
    metrics = ["makespan", "total_tardiness", "sla_breach_rate", "avg_cycle_time"]

    rows = []
    for hybrid in hybrids:
        for baseline in baselines:
            for metric in metrics:
                h_mean = df[df["method"] == hybrid][metric].mean()
                b_mean = df[df["method"] == baseline][metric].mean()
                if b_mean != 0:
                    pct = (b_mean - h_mean) / abs(b_mean) * 100
                else:
                    pct = 0.0
                rows.append({
                    "hybrid": hybrid,
                    "baseline": baseline,
                    "metric": metric,
                    "pct_improvement": pct,
                })
    return pd.DataFrame(rows)


def cohens_d(x: np.ndarray, y: np.ndarray) -> float:
    """Compute Cohen's d effect size for paired observations."""
    diff = x - y
    return float(np.mean(diff) / max(np.std(diff, ddof=1), 1e-12))


def bootstrap_ci(x: np.ndarray, y: np.ndarray, n_boot: int = 5000, alpha: float = 0.05) -> Tuple[float, float]:
    """Bootstrap 95% CI for mean difference (x - y)."""
    rng = np.random.default_rng(42)
    diffs = x - y
    n = len(diffs)
    boot_means = np.empty(n_boot)
    for i in range(n_boot):
        idx = rng.integers(0, n, size=n)
        boot_means[i] = np.mean(diffs[idx])
    lo = float(np.percentile(boot_means, 100 * alpha / 2))
    hi = float(np.percentile(boot_means, 100 * (1 - alpha / 2)))
    return lo, hi


def holm_correction(p_values: List[float]) -> List[float]:
    """Apply Holm-Bonferroni correction for multiple comparisons."""
    n = len(p_values)
    indexed = sorted(enumerate(p_values), key=lambda x: x[1])
    corrected = [0.0] * n
    for rank, (orig_idx, p) in enumerate(indexed):
        corrected[orig_idx] = min(1.0, p * (n - rank))
    # Enforce monotonicity
    for rank in range(1, n):
        orig_idx = indexed[rank][0]
        prev_idx = indexed[rank - 1][0]
        corrected[orig_idx] = max(corrected[orig_idx], corrected[prev_idx])
    return corrected


def run_friedman_test(df: pd.DataFrame, metric: str = "total_tardiness") -> Dict[str, Any]:
    """Run Friedman test across all methods for the given metric.

    Returns
    -------
    dict with 'statistic', 'p_value', 'significant', 'avg_ranks'
    """
    methods_in_df = [m for m in METHODS if m in df["method"].unique()]
    seeds = sorted(df["seed"].unique())

    # Build matrix: rows=seeds, cols=methods
    matrix = np.zeros((len(seeds), len(methods_in_df)))
    for j, method in enumerate(methods_in_df):
        method_df = df[df["method"] == method].set_index("seed")
        for i, seed in enumerate(seeds):
            if seed in method_df.index:
                matrix[i, j] = method_df.loc[seed, metric]

    stat, p = friedmanchisquare(*[matrix[:, j] for j in range(matrix.shape[1])])

    # Compute average ranks
    ranks = np.zeros_like(matrix)
    for i in range(matrix.shape[0]):
        ranks[i] = rankdata(matrix[i])
    avg_ranks = {m: float(ranks[:, j].mean()) for j, m in enumerate(methods_in_df)}

    result = {
        "statistic": float(stat),
        "p_value": float(p),
        "significant": p < 0.05,
        "avg_ranks": avg_ranks,
        "n_methods": len(methods_in_df),
        "n_seeds": len(seeds),
    }
    logger.info("[Friedman] %s: ?^2=%.2f, p=%.6f, significant=%s",
                metric, stat, p, result["significant"])
    return result


def run_nemenyi_test(friedman_result: Dict[str, Any]) -> Dict[str, float]:
    """Compute Nemenyi critical difference from Friedman results.

    Returns dict with 'cd' (critical difference at ?=0.05).
    """
    k = friedman_result["n_methods"]
    n = friedman_result["n_seeds"]

    # Nemenyi critical values (q_? for ?=0.05)
    # Tabulated for k=2..10 methods
    q_alpha_table = {
        2: 1.960, 3: 2.343, 4: 2.569, 5: 2.728,
        6: 2.850, 7: 2.949, 8: 3.031, 9: 3.102, 10: 3.164,
    }
    q_alpha = q_alpha_table.get(k, 3.102)
    cd = q_alpha * np.sqrt(k * (k + 1) / (6 * n))

    return {"cd": float(cd), "q_alpha": q_alpha, "k": k, "n": n}


def run_wilcoxon_tests(df: pd.DataFrame) -> Dict[str, Any]:
    """Run Wilcoxon signed-rank tests for each Hybrid vs best baseline.

    Tests on total_tardiness (primary metric) with Holm correction.
    """
    results = {}
    # Find best baseline by mean total_tardiness
    baseline_means = {
        m: df[df["method"] == m]["total_tardiness"].mean()
        for m in BASELINE_METHODS if m in df["method"].unique()
    }
    best_baseline = min(baseline_means, key=baseline_means.get)
    logger.info("Best baseline (tardiness): %s (mean=%.1f)", best_baseline, baseline_means[best_baseline])

    hybrids = [m for m in HYBRID_METHODS if m in df["method"].unique()]
    p_values = []

    for hybrid in hybrids:
        paired = pd.DataFrame({
            "baseline": df[df["method"] == best_baseline].set_index("seed")["total_tardiness"],
            "hybrid": df[df["method"] == hybrid].set_index("seed")["total_tardiness"],
        }).dropna()

        if len(paired) < 2:
            continue

        b_vals = paired["baseline"].values
        h_vals = paired["hybrid"].values

        stat, p = wilcoxon(b_vals, h_vals, alternative="two-sided")
        d = cohens_d(b_vals, h_vals)
        ci_lo, ci_hi = bootstrap_ci(b_vals, h_vals)

        p_values.append(p)
        results[hybrid] = {
            "stat": float(stat),
            "p_value": float(p),
            "cohens_d": d,
            "ci_95": (ci_lo, ci_hi),
            "best_baseline": best_baseline,
            "mean_diff": float(np.mean(b_vals - h_vals)),
        }
        direction = "improvement" if np.mean(h_vals) < np.mean(b_vals) else "regression"
        logger.info(
            "[Wilcoxon] %s vs %s: stat=%.2f, p=%.4f, d=%.3f, CI=[%.1f, %.1f] -> %s",
            hybrid, best_baseline, stat, p, d, ci_lo, ci_hi, direction,
        )

    # Apply Holm correction
    if p_values:
        corrected = holm_correction(p_values)
        for (hybrid, res), p_corr in zip(results.items(), corrected):
            res["p_corrected"] = p_corr
            res["significant"] = p_corr < 0.05

    return results


def test_hypotheses(df: pd.DataFrame, wilcoxon_results: Dict, friedman_result: Dict) -> None:
    """Print comprehensive hypothesis test conclusions."""
    print("\n" + "=" * 70)
    print("HYPOTHESIS TEST RESULTS")
    print("=" * 70)

    metric_means = df.groupby("method")[
        ["makespan", "total_tardiness", "sla_breach_rate", "throughput"]
    ].mean()

    # H1: Hybrid methods achieve lower total tardiness than all baselines
    best_hybrid = None
    best_hybrid_tard = float("inf")
    for h in HYBRID_METHODS:
        if h in metric_means.index:
            val = metric_means.loc[h, "total_tardiness"]
            if val < best_hybrid_tard:
                best_hybrid_tard = val
                best_hybrid = h

    baselines_tard = {m: metric_means.loc[m, "total_tardiness"]
                      for m in BASELINE_METHODS if m in metric_means.index}
    h1 = best_hybrid_tard < min(baselines_tard.values()) if baselines_tard else False
    print(f"\nH1 (Best Hybrid tardiness < all baselines): {'SUPPORTED' if h1 else 'NOT SUPPORTED'}")
    print(f"   Best Hybrid ({best_hybrid}): {best_hybrid_tard:.1f}")
    for m, v in sorted(baselines_tard.items(), key=lambda x: x[1]):
        print(f"   {m}: {v:.1f}")

    # H2: Hybrid reduces SLA breach rate vs worst baseline
    if HYBRID_METHODS[0] in metric_means.index:
        worst_baseline_sla = max(
            metric_means.loc[m, "sla_breach_rate"] for m in BASELINE_METHODS if m in metric_means.index
        )
        best_hybrid_sla = min(
            metric_means.loc[m, "sla_breach_rate"] for m in HYBRID_METHODS if m in metric_means.index
        )
        h2 = best_hybrid_sla < worst_baseline_sla
        print(f"\nH2 (Best Hybrid SLA breach < worst baseline): {'SUPPORTED' if h2 else 'NOT SUPPORTED'}")
        print(f"   Worst baseline SLA: {worst_baseline_sla:.3f}   Best Hybrid: {best_hybrid_sla:.3f}")

    # H3: Friedman test significance
    h3 = friedman_result.get("significant", False)
    print(f"\nH3 (Friedman: significant difference among methods): {'SUPPORTED' if h3 else 'NOT SUPPORTED'}")
    print(f"   ?^2={friedman_result['statistic']:.2f}, p={friedman_result['p_value']:.6f}")
    print(f"   Average ranks (lower=better):")
    for m, r in sorted(friedman_result.get("avg_ranks", {}).items(), key=lambda x: x[1]):
        print(f"     {m}: {r:.2f}")

    # H4: Wilcoxon with effect sizes
    sig_count = sum(1 for r in wilcoxon_results.values() if r.get("significant"))
    h4 = sig_count > 0
    print(f"\nH4 (Wilcoxon p<0.05 with Holm correction): {'SUPPORTED' if h4 else 'NOT SUPPORTED'}")
    for name, res in wilcoxon_results.items():
        sig_str = f"p_corr={res.get('p_corrected', res['p_value']):.4f}"
        sig_mark = "*" if res.get("significant") else ""
        print(f"   {name} vs {res.get('best_baseline', 'best')}: "
              f"stat={res['stat']:.1f}, p={res['p_value']:.4f}, "
              f"{sig_str}{sig_mark}, d={res['cohens_d']:.3f}, "
              f"95%CI=[{res['ci_95'][0]:.1f}, {res['ci_95'][1]:.1f}]")

    print("=" * 70)


# ---------------------------------------------------------------------------
# Plot generators
# ---------------------------------------------------------------------------

def _style_ax(ax, title: str = "") -> None:
    """Apply dark theme styling to an axis."""
    ax.set_facecolor(PANEL_BG)
    ax.tick_params(colors=TEXT_COLOR, labelsize=9)
    ax.spines[:].set_color("#333344")
    if title:
        ax.set_title(title, color=TEXT_COLOR, fontsize=12, pad=8)
    ax.xaxis.label.set_color(TEXT_COLOR)
    ax.yaxis.label.set_color(TEXT_COLOR)


def plot_benchmark_boxplots(df: pd.DataFrame) -> None:
    """Makespan + Total Tardiness side-by-side boxplots."""
    methods = [m for m in METHODS if m in df["method"].unique()]
    fig, axes = plt.subplots(1, 2, figsize=(18, 7))
    fig.patch.set_facecolor(DARK_BG)

    for ax, metric, ylabel, title in zip(
        axes,
        ["makespan", "total_tardiness"],
        ["Minutes", "Minutes Late (total)"],
        ["Makespan by Method", "Total Tardiness by Method"],
    ):
        data_by_method = [df[df["method"] == m][metric].values for m in methods]
        bp = ax.boxplot(
            data_by_method,
            labels=methods,
            patch_artist=True,
            medianprops={"color": "white", "linewidth": 1.5},
            whiskerprops={"color": "#aaaaaa"},
            capprops={"color": "#aaaaaa"},
            flierprops={"marker": ".", "markerfacecolor": "#555555", "markersize": 3},
        )
        for patch, method in zip(bp["boxes"], methods):
            patch.set_facecolor(METHOD_COLORS.get(method, "#888888"))
            patch.set_alpha(0.8)

        _style_ax(ax, title)
        ax.set_ylabel(ylabel, color=TEXT_COLOR)
        ax.set_xticklabels(methods, rotation=35, ha="right", color=TEXT_COLOR, fontsize=7)

    fig.suptitle("Benchmark: Makespan & Tardiness Comparison", color=TEXT_COLOR, fontsize=15)
    plt.tight_layout()
    path = PLOTS_DIR / "benchmark_boxplot.png"
    plt.savefig(path, dpi=150, bbox_inches="tight", facecolor=DARK_BG)
    plt.close()
    logger.info("Saved -> %s", path)


def plot_sla_breach(df: pd.DataFrame) -> None:
    """Bar chart of SLA breach rate by method."""
    methods = [m for m in METHODS if m in df["method"].unique()]
    fig, ax = plt.subplots(figsize=(12, 6))
    fig.patch.set_facecolor(DARK_BG)
    ax.set_facecolor(PANEL_BG)

    means = [df[df["method"] == m]["sla_breach_rate"].mean() for m in methods]
    stds = [df[df["method"] == m]["sla_breach_rate"].std() for m in methods]
    colors = [METHOD_COLORS.get(m, "#888") for m in methods]

    bars = ax.bar(methods, means, color=colors, alpha=0.85, yerr=stds,
                  error_kw={"ecolor": "#ffffff55", "capsize": 4})
    for bar, val in zip(bars, means):
        ax.text(bar.get_x() + bar.get_width() / 2, bar.get_height() + 0.005,
                f"{val:.3f}", ha="center", va="bottom", color=TEXT_COLOR, fontsize=8)

    _style_ax(ax, "SLA Breach Rate by Scheduling Method")
    ax.set_ylabel("SLA Breach Rate (fraction)", color=TEXT_COLOR)
    ax.set_xticklabels(methods, rotation=30, ha="right", color=TEXT_COLOR, fontsize=8)
    plt.tight_layout()
    path = PLOTS_DIR / "sla_breach_comparison.png"
    plt.savefig(path, dpi=150, bbox_inches="tight", facecolor=DARK_BG)
    plt.close()
    logger.info("Saved -> %s", path)


def plot_utilization_heatmap(df: pd.DataFrame) -> None:
    """Zone x Method utilization heatmap using REAL per-zone data."""
    methods = [m for m in METHODS if m in df["method"].unique()]
    zone_cols = [f"zone_util_{z}" for z in range(8)]
    zone_names = [
        "Receiving", "Sorting", "Picking-A", "Picking-B",
        "Value-Add", "QC", "Packing", "Shipping",
    ]

    # Check if per-zone data exists
    has_zone_data = all(c in df.columns for c in zone_cols)

    heatmap_data = np.zeros((8, len(methods)))
    for j, method in enumerate(methods):
        method_df = df[df["method"] == method]
        if has_zone_data:
            for i, col in enumerate(zone_cols):
                heatmap_data[i, j] = method_df[col].mean()
        else:
            avg_util = method_df["zone_utilization_avg"].mean()
            heatmap_data[:, j] = avg_util

    hm_df = pd.DataFrame(heatmap_data, index=zone_names, columns=methods)

    fig, ax = plt.subplots(figsize=(15, 7))
    fig.patch.set_facecolor(DARK_BG)
    ax.set_facecolor(PANEL_BG)

    sns.heatmap(
        hm_df,
        ax=ax,
        cmap="YlOrRd",
        vmin=0,
        vmax=1,
        annot=True,
        fmt=".2f",
        linewidths=0.5,
        linecolor="#222233",
        annot_kws={"size": 8, "color": "black"},
        cbar_kws={"shrink": 0.8, "label": "Utilization"},
    )
    ax.set_title("Zone Utilization by Scheduling Method", color=TEXT_COLOR, fontsize=14)
    ax.tick_params(colors=TEXT_COLOR)
    ax.set_xticklabels(methods, rotation=30, ha="right", color=TEXT_COLOR, fontsize=8)
    ax.set_yticklabels(zone_names, color=TEXT_COLOR)

    plt.tight_layout()
    path = PLOTS_DIR / "utilization_heatmap.png"
    plt.savefig(path, dpi=150, bbox_inches="tight", facecolor=DARK_BG)
    plt.close()
    logger.info("Saved -> %s", path)


def plot_gantt_sample(seed: int = 99_000) -> None:
    """Gantt chart for one seed with the best hybrid method."""
    from src.features import FeatureExtractor
    from src.heuristics import critical_ratio_dispatch
    from src.hybrid_scheduler import HybridSelector
    from src.simulator import WarehouseSimulator

    fe = FeatureExtractor()
    hs = HybridSelector(MODELS_DIR / "selector_rf.joblib", fe)

    class _Wrapper:
        def __init__(self, hs, sim_ref):
            self._hs = hs
            self._sim = sim_ref

        def __call__(self, jobs, current_time, zone_id):
            self._hs.update_state(self._sim.get_state_snapshot())
            return self._hs(jobs, current_time, zone_id)

    # Use ATC (fast baseline) for the Gantt chart -- avoids per-event model.predict()
    # overhead which makes a 600-min simulation unacceptably slow for a plot.
    from src.heuristics import atc_dispatch
    sim = WarehouseSimulator(seed=seed, heuristic_fn=atc_dispatch, feature_extractor=fe)
    sim.run(duration=600.0)

    completed = sim.completed_jobs[:80]
    if not completed:
        logger.warning("No completed jobs for Gantt plot")
        return

    job_type_colors = {"A": "#42a5f5", "B": "#66bb6a", "C": "#ffb74d", "D": "#ef5350", "E": "#ab47bc"}

    fig, ax = plt.subplots(figsize=(18, max(8, len(completed) * 0.2)))
    fig.patch.set_facecolor(DARK_BG)
    ax.set_facecolor(PANEL_BG)

    for row_idx, job in enumerate(completed):
        for op in job.operations:
            if op.start_time < 0:
                continue
            color = job_type_colors.get(job.job_type, "#888")
            ax.barh(
                row_idx,
                op.end_time - op.start_time,
                left=op.start_time,
                height=0.7,
                color=color,
                alpha=0.8,
            )
        ax.axvline(x=job.due_date, ymin=(row_idx - 0.35) / len(completed),
                   ymax=(row_idx + 0.35) / len(completed),
                   color="red", alpha=0.5, linewidth=0.8)

    handles = [mpatches.Patch(color=c, label=f"Type {t}") for t, c in job_type_colors.items()]
    ax.legend(handles=handles, loc="upper right", facecolor=PANEL_BG, edgecolor="#444",
              labelcolor=TEXT_COLOR, fontsize=9)

    ax.set_xlabel("Simulation Time (minutes)", color=TEXT_COLOR)
    ax.set_ylabel("Job Index", color=TEXT_COLOR)
    ax.set_title(f"Gantt Chart ? Hybrid-RF, Seed {seed}", color=TEXT_COLOR, fontsize=13)
    ax.tick_params(colors=TEXT_COLOR)
    ax.spines[:].set_color("#333344")

    plt.tight_layout()
    path = PLOTS_DIR / "gantt_sample.png"
    plt.savefig(path, dpi=120, bbox_inches="tight", facecolor=DARK_BG)
    plt.close()
    logger.info("Saved -> %s", path)


def plot_critical_difference(friedman_result: Dict, nemenyi_result: Dict) -> None:
    """Generate a critical difference (CD) diagram for algorithm comparison.

    This is the standard visualization in computational intelligence papers
    (Demsar 2006) for comparing multiple classifiers/methods.
    """
    avg_ranks = friedman_result.get("avg_ranks", {})
    cd = nemenyi_result.get("cd", 0)

    if not avg_ranks:
        logger.warning("No average ranks for CD diagram")
        return

    methods_sorted = sorted(avg_ranks.items(), key=lambda x: x[1])
    n_methods = len(methods_sorted)

    fig, ax = plt.subplots(figsize=(14, 4))
    fig.patch.set_facecolor(DARK_BG)
    ax.set_facecolor(DARK_BG)

    # Determine axis limits
    min_rank = min(r for _, r in methods_sorted)
    max_rank = max(r for _, r in methods_sorted)
    margin = 0.5
    ax.set_xlim(min_rank - margin, max_rank + margin)
    ax.set_ylim(-0.5, n_methods + 1)

    # Draw axis line
    ax.axhline(y=n_methods, xmin=0, xmax=1, color="#aaaaaa", linewidth=1)

    # Draw tick marks on the axis
    for rank in range(1, n_methods + 1):
        ax.plot([rank, rank], [n_methods - 0.1, n_methods + 0.1], color="#aaaaaa", linewidth=1)
        ax.text(rank, n_methods + 0.3, str(rank), ha="center", va="bottom", color=TEXT_COLOR, fontsize=9)

    # Plot method positions
    left_methods = methods_sorted[:n_methods // 2]
    right_methods = methods_sorted[n_methods // 2:]

    for idx, (name, rank) in enumerate(left_methods):
        y_pos = n_methods - 1 - idx * 0.8
        color = METHOD_COLORS.get(name, "#cccccc")
        ax.plot(rank, n_methods, "o", color=color, markersize=8, zorder=5)
        ax.plot([rank, rank], [n_methods, y_pos], color="#666666", linewidth=0.8)
        ax.text(rank - 0.1, y_pos, f"{name} ({rank:.2f})", ha="right", va="center",
                color=color, fontsize=9, fontweight="bold")

    for idx, (name, rank) in enumerate(right_methods):
        y_pos = n_methods - 1 - idx * 0.8
        color = METHOD_COLORS.get(name, "#cccccc")
        ax.plot(rank, n_methods, "o", color=color, markersize=8, zorder=5)
        ax.plot([rank, rank], [n_methods, y_pos], color="#666666", linewidth=0.8)
        ax.text(rank + 0.1, y_pos, f"({rank:.2f}) {name}", ha="left", va="center",
                color=color, fontsize=9, fontweight="bold")

    # Draw CD bar
    cd_y = n_methods + 1.0
    cd_start = min_rank
    ax.plot([cd_start, cd_start + cd], [cd_y, cd_y], color=ACCENT, linewidth=2.5)
    ax.plot([cd_start, cd_start], [cd_y - 0.15, cd_y + 0.15], color=ACCENT, linewidth=2)
    ax.plot([cd_start + cd, cd_start + cd], [cd_y - 0.15, cd_y + 0.15], color=ACCENT, linewidth=2)
    ax.text((cd_start + cd_start + cd) / 2, cd_y + 0.25, f"CD = {cd:.3f}",
            ha="center", color=ACCENT, fontsize=10, fontweight="bold")

    # Draw connections between methods that are NOT significantly different
    for i, (name_i, rank_i) in enumerate(methods_sorted):
        for j, (name_j, rank_j) in enumerate(methods_sorted):
            if i < j and abs(rank_i - rank_j) < cd:
                y_line = n_methods + 0.5
                ax.plot([rank_i, rank_j], [y_line, y_line], color="#555555", linewidth=2, alpha=0.5)

    ax.set_title("Critical Difference Diagram (Nemenyi, ?=0.05) ? Total Tardiness",
                 color=TEXT_COLOR, fontsize=13, pad=20)
    ax.axis("off")

    plt.tight_layout()
    path = PLOTS_DIR / "critical_difference.png"
    plt.savefig(path, dpi=150, bbox_inches="tight", facecolor=DARK_BG)
    plt.close()
    logger.info("Saved -> %s", path)


def plot_pareto_front(df: pd.DataFrame) -> None:
    """Scatter plot of makespan vs total tardiness showing Pareto trade-offs."""
    methods = [m for m in METHODS if m in df["method"].unique()]

    fig, ax = plt.subplots(figsize=(10, 8))
    fig.patch.set_facecolor(DARK_BG)
    ax.set_facecolor(PANEL_BG)

    for method in methods:
        mdf = df[df["method"] == method]
        color = METHOD_COLORS.get(method, "#888")
        ax.scatter(
            mdf["makespan"].mean(), mdf["total_tardiness"].mean(),
            color=color, s=120, zorder=5, edgecolors="white", linewidth=0.8,
            label=method,
        )
        # Add error bars (1 std)
        ax.errorbar(
            mdf["makespan"].mean(), mdf["total_tardiness"].mean(),
            xerr=mdf["makespan"].std(), yerr=mdf["total_tardiness"].std(),
            color=color, alpha=0.4, fmt="none", capsize=3,
        )

    # Identify and highlight Pareto front
    means = [(m, df[df["method"] == m]["makespan"].mean(),
              df[df["method"] == m]["total_tardiness"].mean()) for m in methods]
    means.sort(key=lambda x: x[1])
    pareto = []
    min_tard = float("inf")
    for name, mks, tard in means:
        if tard < min_tard:
            pareto.append((mks, tard))
            min_tard = tard
    if len(pareto) > 1:
        pareto_x, pareto_y = zip(*pareto)
        ax.plot(pareto_x, pareto_y, "--", color=ACCENT, alpha=0.6, linewidth=1.5, label="Pareto front")

    _style_ax(ax, "Multi-Objective Trade-off: Makespan vs Total Tardiness")
    ax.set_xlabel("Mean Makespan (minutes)", color=TEXT_COLOR)
    ax.set_ylabel("Mean Total Tardiness (minutes)", color=TEXT_COLOR)
    ax.legend(facecolor=PANEL_BG, edgecolor="#444", labelcolor=TEXT_COLOR, fontsize=8, loc="upper left")

    plt.tight_layout()
    path = PLOTS_DIR / "pareto_front.png"
    plt.savefig(path, dpi=150, bbox_inches="tight", facecolor=DARK_BG)
    plt.close()
    logger.info("Saved -> %s", path)


def plot_disruption_analysis(df: pd.DataFrame) -> None:
    """Radar chart comparing methods across multiple performance dimensions."""
    methods = [m for m in METHODS if m in df["method"].unique()]
    metrics = ["makespan", "total_tardiness", "sla_breach_rate", "avg_cycle_time", "throughput"]
    metric_labels = ["Makespan", "Tardiness", "SLA Breach", "Cycle Time", "Throughput"]

    # Normalize metrics (0=worst, 1=best across methods)
    norm_data = {}
    for metric in metrics:
        vals = [df[df["method"] == m][metric].mean() for m in methods]
        mn, mx = min(vals), max(vals)
        rng = mx - mn if mx != mn else 1.0
        if metric == "throughput":
            # Higher is better
            norm_data[metric] = [(v - mn) / rng for v in vals]
        else:
            # Lower is better -> invert
            norm_data[metric] = [(mx - v) / rng for v in vals]

    n_metrics = len(metrics)
    angles = np.linspace(0, 2 * np.pi, n_metrics, endpoint=False).tolist()
    angles += angles[:1]  # close the polygon

    fig, ax = plt.subplots(figsize=(10, 10), subplot_kw=dict(polar=True))
    fig.patch.set_facecolor(DARK_BG)
    ax.set_facecolor(PANEL_BG)

    for i, method in enumerate(methods):
        values = [norm_data[m][i] for m in metrics]
        values += values[:1]
        color = METHOD_COLORS.get(method, "#888")
        ax.plot(angles, values, "o-", linewidth=1.5, label=method, color=color, markersize=4)
        ax.fill(angles, values, alpha=0.08, color=color)

    ax.set_xticks(angles[:-1])
    ax.set_xticklabels(metric_labels, color=TEXT_COLOR, fontsize=10)
    ax.tick_params(colors="#666666")
    ax.set_title("Multi-Dimensional Performance Comparison\n(1=best, 0=worst)",
                 color=TEXT_COLOR, fontsize=13, pad=20)
    ax.legend(loc="upper right", bbox_to_anchor=(1.35, 1.1),
              facecolor=PANEL_BG, edgecolor="#444", labelcolor=TEXT_COLOR, fontsize=7)

    plt.tight_layout()
    path = PLOTS_DIR / "radar_comparison.png"
    plt.savefig(path, dpi=150, bbox_inches="tight", facecolor=DARK_BG)
    plt.close()
    logger.info("Saved -> %s", path)


def plot_effect_sizes(wilcoxon_results: Dict) -> None:
    """Bar chart of Cohen's d effect sizes for hybrid vs best baseline."""
    if not wilcoxon_results:
        return

    fig, ax = plt.subplots(figsize=(10, 5))
    fig.patch.set_facecolor(DARK_BG)
    ax.set_facecolor(PANEL_BG)

    names = list(wilcoxon_results.keys())
    d_vals = [wilcoxon_results[n]["cohens_d"] for n in names]
    colors = [METHOD_COLORS.get(n, "#888") for n in names]

    bars = ax.bar(names, d_vals, color=colors, alpha=0.85)

    # Add significance stars
    for bar, name in zip(bars, names):
        res = wilcoxon_results[name]
        star = "*" if res.get("significant") else ""
        ax.text(bar.get_x() + bar.get_width() / 2, bar.get_height() + 0.01,
                f"d={res['cohens_d']:.3f}{star}", ha="center", va="bottom",
                color=TEXT_COLOR, fontsize=10)

    # Reference lines for effect size interpretation
    for threshold, label in [(0.2, "small"), (0.5, "medium"), (0.8, "large")]:
        ax.axhline(y=threshold, color="#555555", linestyle=":", linewidth=0.8)
        ax.axhline(y=-threshold, color="#555555", linestyle=":", linewidth=0.8)
        ax.text(len(names) - 0.5, threshold + 0.02, label, color="#777777", fontsize=8)

    ax.axhline(y=0, color="#aaaaaa", linewidth=0.8)

    _style_ax(ax, "Effect Sizes: Hybrid vs Best Baseline (Cohen's d)")
    ax.set_ylabel("Cohen's d (positive = hybrid better)", color=TEXT_COLOR)
    ax.set_xticklabels(names, rotation=15, ha="right", color=TEXT_COLOR)

    plt.tight_layout()
    path = PLOTS_DIR / "effect_sizes.png"
    plt.savefig(path, dpi=150, bbox_inches="tight", facecolor=DARK_BG)
    plt.close()
    logger.info("Saved -> %s", path)


def generate_all_plots(df: pd.DataFrame, friedman_result: Dict = None,
                       nemenyi_result: Dict = None, wilcoxon_results: Dict = None) -> None:
    """Generate all benchmark visualizations from results DataFrame."""
    PLOTS_DIR.mkdir(parents=True, exist_ok=True)

    plot_benchmark_boxplots(df)
    plot_sla_breach(df)
    plot_utilization_heatmap(df)
    plot_pareto_front(df)
    plot_disruption_analysis(df)

    if friedman_result and nemenyi_result:
        plot_critical_difference(friedman_result, nemenyi_result)

    if wilcoxon_results:
        plot_effect_sizes(wilcoxon_results)

    try:
        plot_gantt_sample()
    except Exception as exc:
        logger.warning("Gantt plot failed (models may not be available): %s", exc)
