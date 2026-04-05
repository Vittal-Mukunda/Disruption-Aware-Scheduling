"""
generate_rf_dataset.py -- Abstract Single-Machine Scheduling Dataset Generator
for Random Forest Heuristic Selector

Pipeline
--------
  Step 1 -- Regime-based instance generation (WSPT, EDD, FIFO, Slack,
            Cost-skewed, ATC/Mixed) with controlled distributions.
  Step 2 -- Feature extraction (statistical descriptors of p, w, d, r, slack).
  Step 3 -- Labeling via weighted-tardiness simulation across 6 heuristics;
            gap-filtered and per-class capped for balance.
  Step 4 -- Output as a Pandas DataFrame + scikit-learn RF training utility.

Design notes
------------
ATC and COVERT are genuinely stronger than WSPT/EDD/FIFO/MST in most settings
(they subsume simpler rules as special cases). The natural label distribution
therefore skews heavily toward ATC/COVERT. The rebalancer caps every class at
`max_class_fraction` of the final dataset to enforce a learnable signal across
all six heuristics. Minority classes (WSPT, FIFO, MST) arise from extreme-regime
instances where the structural pressure is too one-dimensional for ATC/COVERT's
dual urgency-weight scoring to help.

Usage
-----
    python scripts/generate_rf_dataset.py
    from scripts.generate_rf_dataset import build_dataset, train_random_forest
"""

from __future__ import annotations

import os
import warnings
from collections import Counter
from typing import Dict, List, Optional, Tuple

import numpy as np
import pandas as pd
from scipy import stats
from sklearn.ensemble import RandomForestClassifier
from sklearn.model_selection import train_test_split
from sklearn.metrics import classification_report

warnings.filterwarnings("ignore")

# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

REGIMES = ["wspt", "edd", "fifo", "slack", "cost_skewed", "atc_mixed"]
HEURISTIC_NAMES = ["WSPT", "EDD", "FIFO", "MST", "ATC", "COVERT"]

FEATURE_COLS: List[str] = [
    "n_jobs",
    "p_mean", "p_var", "p_cv", "p_skew",
    "w_mean", "w_var", "w_cv", "w_skew",
    "d_mean", "d_var", "d_cv",
    "r_mean", "r_var",
    "slack_mean", "slack_var", "slack_min", "slack_cv",
    "tightness_ratio",
    "corr_wp", "corr_wd", "corr_pd",
    "wp_ratio_mean", "wp_ratio_var", "wp_ratio_max",
]


# ---------------------------------------------------------------------------
# Step 1: Regime-based Instance Generation
# ---------------------------------------------------------------------------

def _generate_instance(regime: str, n_jobs: int, rng: np.random.Generator) -> Dict:
    """
    Generate one scheduling instance for the requested regime.

    Regime pressure summary
    -----------------------
    wspt        Uniform small slack, high w/p variance.
                Urgency is equalized so ATC degenerates toward WSPT.
    edd         Strictly equal weights (1.0), high d variance, tight deadlines.
                Only the due-date order matters, not w/p.
    fifo        Near-constant p and w; staggered release times drive ordering.
                FIFO naturally respects machine-availability constraints.
    slack       Bimodal slack distribution: half the jobs already overdue at
                release, half comfortable. MST identifies the overdue half.
    cost_skewed Pareto-distributed weights, moderate p, semi-tight d.
                High-weight jobs need urgent but weighted dispatch.
    atc_mixed   Broad overlapping ranges on all dimensions -- ATC/COVERT's
                joint urgency+cost index should dominate.
    """
    if regime == "wspt":
        # Equalise urgency (uniform slack) so ATC ~ WSPT; vary w/p strongly.
        p = rng.uniform(1.0, 5.0, size=n_jobs)           # small, similar sizes
        w = rng.exponential(scale=5.0, size=n_jobs).clip(0.2)  # right-skewed
        r = rng.uniform(0.0, 3.0, size=n_jobs)
        # Uniform slack: same buffer for every job => equal urgency
        slack_val = rng.uniform(2.0, 8.0) * n_jobs * np.mean(p) / n_jobs
        d = r + p + slack_val + rng.normal(0, 0.5, size=n_jobs)  # tiny noise
        d = np.maximum(d, r + p + 0.1)

    elif regime == "edd":
        # Equal weights, variable tightness -- EDD's d ordering is the signal.
        p = rng.uniform(3.0, 7.0, size=n_jobs)           # small variance in p
        w = np.ones(n_jobs)                               # strictly equal
        r = rng.uniform(0.0, 5.0, size=n_jobs)
        # Mix of very tight and moderately tight due dates
        slack_fracs = rng.choice(
            [0.0, 0.1, 0.2, 0.5, 1.0, 2.0], size=n_jobs
        ).astype(float)
        d = r + p * (1.0 + slack_fracs)

    elif regime == "fifo":
        # Near-constant p, w; only r drives the ordering.
        p = rng.uniform(4.5, 5.5, size=n_jobs)            # ~constant
        w = rng.uniform(0.95, 1.05, size=n_jobs)          # ~constant
        r = np.sort(rng.uniform(0.0, 60.0, size=n_jobs))  # staggered arrivals
        horizon = p.sum()
        d = r + p + rng.uniform(0.3 * horizon, 0.9 * horizon, size=n_jobs)

    elif regime == "slack":
        # Bimodal: half jobs have negative static slack, half positive.
        p = rng.uniform(2.0, 15.0, size=n_jobs)
        w = rng.uniform(0.8, 1.2, size=n_jobs)
        r = rng.uniform(0.0, 10.0, size=n_jobs)
        n_tight = n_jobs // 2
        # Tight half: already overdue (negative slack) at release
        tight_slack = rng.uniform(-15.0, -0.5, size=n_tight)
        # Loose half: plenty of room
        loose_slack = rng.uniform(10.0, 50.0, size=n_jobs - n_tight)
        slack_arr = np.concatenate([tight_slack, loose_slack])
        rng.shuffle(slack_arr)
        d = r + p + slack_arr
        d = np.maximum(d, r + 0.05 * p)

    elif regime == "cost_skewed":
        # Pareto weights (power-law): a handful of very expensive jobs.
        p = rng.uniform(2.0, 10.0, size=n_jobs)
        w = (rng.pareto(a=1.5, size=n_jobs) + 1.0)        # heavy tail
        r = rng.uniform(0.0, 5.0, size=n_jobs)
        horizon = p.sum()
        # Tight deadlines that interact with weights
        d = r + p + rng.uniform(0.1 * horizon, 0.8 * horizon, size=n_jobs)

    else:  # atc_mixed
        # Wide, overlapping parameter ranges -- no structural shortcut.
        p = rng.uniform(1.0, 25.0, size=n_jobs)
        w = rng.uniform(0.5, 10.0, size=n_jobs)
        r = rng.uniform(0.0, 20.0, size=n_jobs)
        horizon = p.sum()
        d = r + p + rng.uniform(0.0, 0.7 * horizon, size=n_jobs)

    return {"p": p, "w": w, "d": d, "r": r, "n": n_jobs, "regime": regime}


def generate_instances(
    n_instances: int,
    n_jobs_range: Tuple[int, int] = (5, 50),
    seed: int = 42,
) -> List[Dict]:
    """Generate n_instances with balanced regime sampling."""
    rng = np.random.default_rng(seed)
    instances = []
    for _ in range(n_instances):
        regime = rng.choice(REGIMES)
        n_jobs = int(rng.integers(n_jobs_range[0], n_jobs_range[1] + 1))
        instances.append(_generate_instance(regime, n_jobs, rng))
    return instances


# ---------------------------------------------------------------------------
# Step 2: Single-Machine Scheduling Simulation
# ---------------------------------------------------------------------------

def _simulate(
    p: np.ndarray,
    w: np.ndarray,
    d: np.ndarray,
    r: np.ndarray,
    priority_fn,
    **kwargs,
) -> float:
    """
    Simulate non-preemptive single-machine scheduling with release times.

    At each decision point the highest-priority available job is started.
    When no job is available the clock jumps to the next release time.

    Returns
    -------
    float
        Total weighted tardiness: sum_i  w_i * max(0, C_i - d_i).
    """
    remaining = list(range(len(p)))
    t = 0.0
    total_wt = 0.0

    while remaining:
        available = [j for j in remaining if r[j] <= t + 1e-9]
        if not available:
            t = min(r[j] for j in remaining)
            continue

        scores = priority_fn(available, t, p, w, d, r, **kwargs)
        chosen = available[int(np.argmax(scores))]

        remaining.remove(chosen)
        t = max(t, r[chosen]) + p[chosen]
        total_wt += w[chosen] * max(0.0, t - d[chosen])

    return total_wt


# Priority functions -- higher score => dispatched first ----------------------

def _wspt(available, t, p, w, d, r):
    """Weighted Shortest Processing Time: w_j / p_j."""
    return [w[j] / p[j] for j in available]

def _edd(available, t, p, w, d, r):
    """Earliest Due Date: smaller d_j => higher score."""
    return [-d[j] for j in available]

def _fifo(available, t, p, w, d, r):
    """First-In First-Out: smaller r_j => higher score."""
    return [-r[j] for j in available]

def _mst(available, t, p, w, d, r):
    """Minimum Static Slack: smaller (d - r - p) => higher priority."""
    return [-(d[j] - r[j] - p[j]) for j in available]

def _atc(available, t, p, w, d, r, k: float = 2.0):
    """
    Apparent Tardiness Cost (Vepsalainen & Morton, 1987).

        ATC_j = (w_j / p_j) * exp(-max(d_j - p_j - t, 0) / (k * p_avg))
    """
    p_avg = max(float(np.mean([p[j] for j in available])), 1e-9)
    return [
        (w[j] / p[j]) * np.exp(-max(d[j] - p[j] - t, 0.0) / (k * p_avg))
        for j in available
    ]

def _covert(available, t, p, w, d, r, h: float = 2.0):
    """
    COVERT -- Cost Over Time (Carroll, 1965).

        COVERT_j = (w_j / p_j) * max(0, 1 - max(d_j - p_j - t, 0) / (h * p_avg))
    """
    p_avg = max(float(np.mean([p[j] for j in available])), 1e-9)
    scores = []
    for j in available:
        slack = max(d[j] - p[j] - t, 0.0)
        urgency = max(0.0, 1.0 - slack / (h * p_avg))
        scores.append((w[j] / p[j]) * urgency)
    return scores


_HEURISTIC_FNS: Dict = {
    "WSPT":   _wspt,
    "EDD":    _edd,
    "FIFO":   _fifo,
    "MST":    _mst,
    "ATC":    _atc,
    "COVERT": _covert,
}


def evaluate_heuristics(inst: Dict) -> Dict[str, float]:
    """Run all six heuristics; return weighted tardiness per heuristic."""
    p, w, d, r = inst["p"], inst["w"], inst["d"], inst["r"]
    return {name: _simulate(p, w, d, r, fn) for name, fn in _HEURISTIC_FNS.items()}


# ---------------------------------------------------------------------------
# Step 3: Feature Extraction
# ---------------------------------------------------------------------------

def extract_features(inst: Dict) -> Dict[str, float]:
    """
    Compute 25 scalar features describing a scheduling instance.

    Features
    --------
    - Distributional moments of p, w, d: mean, variance, CV, skewness
    - Release time statistics: mean, variance
    - Static slack (d - r - p): mean, variance, min, CV
    - Tightness ratio: fraction of jobs where static slack < 0
    - Pairwise Pearson correlations: corr(w,p), corr(w,d), corr(p,d)
    - w/p ratio (WSPT index): mean, variance, max
    """
    p, w, d, r = inst["p"], inst["w"], inst["d"], inst["r"]
    n = inst["n"]
    slack = d - r - p

    def _cv(arr: np.ndarray) -> float:
        mu = float(np.mean(arr))
        return float(np.std(arr)) / (abs(mu) + 1e-9)

    def _corr(a: np.ndarray, b: np.ndarray) -> float:
        if n < 2:
            return 0.0
        c = float(np.corrcoef(a, b)[0, 1])
        return c if np.isfinite(c) else 0.0

    wp = w / np.maximum(p, 1e-9)

    raw = {
        "n_jobs":          float(n),
        "p_mean":          float(np.mean(p)),
        "p_var":           float(np.var(p)),
        "p_cv":            _cv(p),
        "p_skew":          float(stats.skew(p)),
        "w_mean":          float(np.mean(w)),
        "w_var":           float(np.var(w)),
        "w_cv":            _cv(w),
        "w_skew":          float(stats.skew(w)),
        "d_mean":          float(np.mean(d)),
        "d_var":           float(np.var(d)),
        "d_cv":            _cv(d),
        "r_mean":          float(np.mean(r)),
        "r_var":           float(np.var(r)),
        "slack_mean":      float(np.mean(slack)),
        "slack_var":       float(np.var(slack)),
        "slack_min":       float(np.min(slack)),
        "slack_cv":        _cv(slack),
        "tightness_ratio": float(np.mean(slack < 0.0)),
        "corr_wp":         _corr(w, p),
        "corr_wd":         _corr(w, d),
        "corr_pd":         _corr(p, d),
        "wp_ratio_mean":   float(np.mean(wp)),
        "wp_ratio_var":    float(np.var(wp)),
        "wp_ratio_max":    float(np.max(wp)),
    }
    return {k: (0.0 if not np.isfinite(v) else v) for k, v in raw.items()}


# ---------------------------------------------------------------------------
# Step 4: Labeling
# ---------------------------------------------------------------------------

def _label(costs: Dict[str, float], gap_threshold: float = 0.01) -> Optional[str]:
    """
    Return the best-heuristic label, or None when the margin is too small.

    Discards instance when:
        (second_best_cost - best_cost) / best_cost < gap_threshold

    A 1 % relative gap removes near-ties while retaining most informative
    instances. Trivial instances (all-zero tardiness) are always discarded.
    """
    ordered = sorted(costs.items(), key=lambda x: x[1])
    best_name, best_cost = ordered[0]
    _, second_cost = ordered[1]

    if best_cost < 1e-9 and second_cost < 1e-9:
        return None       # all heuristics tie at zero -- uninformative

    if best_cost < 1e-9:
        return best_name  # clear winner at zero vs positive second-best

    return best_name if (second_cost - best_cost) / best_cost >= gap_threshold else None


# ---------------------------------------------------------------------------
# Dataset Assembly
# ---------------------------------------------------------------------------

def build_dataset(
    n_instances: int = 8_000,
    n_jobs_range: Tuple[int, int] = (5, 50),
    gap_threshold: float = 0.01,
    seed: int = 42,
    rebalance: bool = True,
    max_class_fraction: float = 0.30,
) -> pd.DataFrame:
    """
    End-to-end pipeline: generate -> featurise -> simulate -> label -> DataFrame.

    Parameters
    ----------
    n_instances : int
        Raw instances to generate before filtering.
    n_jobs_range : tuple(int, int)
        Inclusive [min, max] number of jobs per instance.
    gap_threshold : float
        Minimum relative performance gap for an instance to be retained.
        Instances below this threshold are discarded as ambiguous.
    seed : int
        Master RNG seed for reproducibility.
    rebalance : bool
        If True, cap every class that exceeds ``max_class_fraction``
        of the dataset after filtering.
    max_class_fraction : float
        Maximum fraction any single label class may occupy (0 < f <= 1).
        Applied independently to each class, not just the global dominant.

    Returns
    -------
    pd.DataFrame
        Columns: FEATURE_COLS + ['label', 'regime']
    """
    print(f"Generating {n_instances} raw instances ...")
    instances = generate_instances(n_instances, n_jobs_range, seed)

    rows: List[Dict] = []
    label_counts: Counter = Counter()
    n_trivial = 0
    n_near_tie = 0

    for inst in instances:
        feats = extract_features(inst)
        costs = evaluate_heuristics(inst)
        label = _label(costs, gap_threshold)

        if label is None:
            best_cost = min(costs.values())
            if best_cost < 1e-9:
                n_trivial += 1
            else:
                n_near_tie += 1
            continue

        feats["label"] = label
        feats["regime"] = inst["regime"]
        rows.append(feats)
        label_counts[label] += 1

    total_retained = len(rows)
    print(
        f"  Retained : {total_retained}  "
        f"| Discarded (all-zero): {n_trivial}  "
        f"| Discarded (near-tie): {n_near_tie}"
    )

    if total_retained == 0:
        raise RuntimeError(
            "No instances survived filtering. "
            "Lower gap_threshold or tighten due-date generation."
        )

    df = pd.DataFrame(rows)

    if rebalance:
        cap = max(1, int(max_class_fraction * total_retained))
        frames = []
        for lbl, group in df.groupby("label"):
            if len(group) > cap:
                frames.append(group.sample(cap, random_state=seed))
                print(
                    f"  Rebalanced '{lbl}': {len(group)} -> {cap}"
                )
            else:
                frames.append(group)
        df = (
            pd.concat(frames)
            .sample(frac=1.0, random_state=seed)
            .reset_index(drop=True)
        )
        print(f"  Final size after rebalancing: {len(df)}")

    return df


# ---------------------------------------------------------------------------
# Step 5: Reporting
# ---------------------------------------------------------------------------

def print_label_distribution(df: pd.DataFrame) -> None:
    """Print a label distribution summary to stdout."""
    BAR_W = 30
    SEP = "-" * 55
    print(f"\n{SEP}")
    print("  Label Distribution")
    print(SEP)
    counts = df["label"].value_counts()
    total = len(df)
    for name, cnt in counts.items():
        pct = 100.0 * cnt / total
        bar = "#" * max(1, int(BAR_W * pct / 100))
        print(f"  {name:<8}  {cnt:>5}  ({pct:5.1f}%)  {bar}")
    print(SEP)
    print(f"  {'TOTAL':<8}  {total:>5}")
    print(SEP)

    print("\n  Label x Regime cross-tab")
    print(pd.crosstab(df["regime"], df["label"], margins=True).to_string())
    print()


# ---------------------------------------------------------------------------
# Step 6: Random Forest Classifier
# ---------------------------------------------------------------------------

def train_random_forest(
    df: pd.DataFrame,
    test_size: float = 0.20,
    n_estimators: int = 200,
    seed: int = 42,
) -> Tuple[RandomForestClassifier, np.ndarray, np.ndarray, List[str]]:
    """
    Train a RandomForestClassifier to select the best scheduling heuristic.

    The model predicts which of the six heuristics achieves minimum weighted
    tardiness given the 25 instance-level features.

    Parameters
    ----------
    df : pd.DataFrame
        Output of ``build_dataset()``.
    test_size : float
        Fraction held out for evaluation.
    n_estimators : int
        Number of trees in the ensemble.
    seed : int
        Random state.

    Returns
    -------
    clf : RandomForestClassifier
    X_test : np.ndarray
    y_test : np.ndarray
    feature_cols : List[str]
        Ordered feature names used at fit time.
    """
    feature_cols = [c for c in FEATURE_COLS if c in df.columns]
    X = df[feature_cols].to_numpy(dtype=float)
    y = df["label"].to_numpy()

    X_train, X_test, y_train, y_test = train_test_split(
        X, y, test_size=test_size, random_state=seed, stratify=y,
    )

    clf = RandomForestClassifier(
        n_estimators=n_estimators,
        max_depth=None,
        min_samples_leaf=2,
        class_weight="balanced",
        random_state=seed,
        n_jobs=-1,
    )
    clf.fit(X_train, y_train)
    y_pred = clf.predict(X_test)

    SEP = "-" * 62
    print(f"\n{SEP}")
    print("  Random Forest -- Classification Report")
    print(SEP)
    print(classification_report(y_test, y_pred, zero_division=0))

    importances = pd.Series(clf.feature_importances_, index=feature_cols)
    print("  Top 10 Feature Importances")
    print("  " + "-" * 42)
    max_imp = importances.max()
    for feat, score in importances.nlargest(10).items():
        bar = "|" * max(1, int(30 * score / max_imp))
        print(f"  {feat:<22}  {score:.4f}  {bar}")

    return clf, X_test, y_test, feature_cols


def predict_best_heuristic(
    clf: RandomForestClassifier,
    feature_cols: List[str],
    p: np.ndarray,
    w: np.ndarray,
    d: np.ndarray,
    r: np.ndarray,
) -> Tuple[str, Dict[str, float]]:
    """
    Recommend the best dispatch heuristic for a new scheduling instance.

    Parameters
    ----------
    clf : RandomForestClassifier
        Trained model (output of ``train_random_forest``).
    feature_cols : List[str]
        Feature ordering used at training (returned by ``train_random_forest``).
    p, w, d, r : np.ndarray
        Processing times, weights, due dates, release times of the new instance.

    Returns
    -------
    predicted_heuristic : str
    probabilities : dict[str, float]
        Posterior probability for each of the six heuristics.
    """
    inst = {"p": p, "w": w, "d": d, "r": r, "n": len(p), "regime": "unknown"}
    feats = extract_features(inst)
    x = np.array([[feats.get(c, 0.0) for c in feature_cols]])
    predicted = clf.predict(x)[0]
    proba = dict(zip(clf.classes_, clf.predict_proba(x)[0]))
    return predicted, proba


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------

if __name__ == "__main__":
    # 1. Build dataset
    df = build_dataset(
        n_instances=8_000,
        n_jobs_range=(5, 50),
        gap_threshold=0.01,
        seed=42,
        rebalance=True,
        max_class_fraction=0.30,
    )
    print_label_distribution(df)

    # 2. Save to CSV
    out_dir = os.path.join("data", "raw")
    os.makedirs(out_dir, exist_ok=True)
    out_path = os.path.join(out_dir, "abstract_selector_dataset.csv")
    df.to_csv(out_path, index=False)
    print(f"Saved dataset -> {out_path}  ({df.shape[0]} rows x {df.shape[1]} cols)\n")

    # 3. Train Random Forest
    clf, X_test, y_test, feature_cols = train_random_forest(df, seed=42)

    # 4. Sanity check: EDD-pressure instance (all weights equal, varied due dates)
    print("\n  Sanity check: EDD-pressure instance (8 jobs, equal weights)")
    print("  " + "-" * 46)
    rng_ex = np.random.default_rng(7)
    n_ex = 8
    p_ex = rng_ex.uniform(3.0, 7.0, size=n_ex)
    w_ex = np.ones(n_ex)
    r_ex = rng_ex.uniform(0.0, 3.0, size=n_ex)
    slack_ex = rng_ex.choice([0.0, 0.1, 0.3, 1.0, 2.0], size=n_ex).astype(float)
    d_ex = r_ex + p_ex * (1.0 + slack_ex)

    actual_costs = evaluate_heuristics({"p": p_ex, "w": w_ex, "d": d_ex, "r": r_ex, "n": n_ex})
    actual_best = min(actual_costs, key=actual_costs.get)
    best_h, proba = predict_best_heuristic(clf, feature_cols, p_ex, w_ex, d_ex, r_ex)

    print(f"  Predicted : {best_h:<8}  |  Actual best: {actual_best}")
    print("  Heuristic costs (sorted):")
    for h, c in sorted(actual_costs.items(), key=lambda x: x[1]):
        marker = " <-- best" if h == actual_best else ""
        print(f"    {h:<8}  {c:10.3f}{marker}")
    top3 = sorted(proba.items(), key=lambda x: -x[1])[:3]
    print(f"  Top-3 predicted probs: {[(h, round(v, 2)) for h, v in top3]}")
