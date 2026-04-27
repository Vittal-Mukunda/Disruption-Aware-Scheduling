"""Statistical-analysis tests for the evaluator.

  1. Wilcoxon direction is correct for both lower-is-better and higher-is-
     better metrics, and Cohen's d is positive when DAHS wins.
  2. Nemenyi post-hoc returns mean ranks, a critical difference, and a
     pairwise matrix consistent with those ranks.
"""
from __future__ import annotations

import numpy as np
import pandas as pd

from src.evaluator import (
    METRIC_DIRECTIONS,
    _wilcoxon_for_metric,
    _nemenyi_pairwise,
)


def _synthetic_df(n_seeds: int = 30) -> pd.DataFrame:
    """DAHS dominates on tardiness, loses on throughput — synthetic fixture."""
    rng = np.random.default_rng(0)
    seeds = list(range(n_seeds))
    rows = []
    for s in seeds:
        rows.append({"seed": s, "method": "dahs_xgb",
                     "total_tardiness": 50 + rng.normal(0, 5),
                     "throughput":      75 + rng.normal(0, 2)})
        rows.append({"seed": s, "method": "fifo",
                     "total_tardiness": 200 + rng.normal(0, 10),
                     "throughput":      90 + rng.normal(0, 2)})
        rows.append({"seed": s, "method": "atc",
                     "total_tardiness": 120 + rng.normal(0, 10),
                     "throughput":      85 + rng.normal(0, 2)})
    return pd.DataFrame(rows)


def test_wilcoxon_lower_metric_dahs_wins():
    df = _synthetic_df()
    pivot = df.pivot_table(index="seed", columns="method", values="total_tardiness")
    avail = list(pivot.columns)
    rows = _wilcoxon_for_metric(pivot, avail, "dahs_xgb",
                                "total_tardiness", METRIC_DIRECTIONS["total_tardiness"])
    assert rows
    for r in rows:
        assert r["p_value"] < 1e-3, r
        assert r["cohens_d"] > 0, r
        assert r["significant_holm"] is True, r


def test_wilcoxon_higher_metric_dahs_loses():
    df = _synthetic_df()
    pivot = df.pivot_table(index="seed", columns="method", values="throughput")
    avail = list(pivot.columns)
    rows = _wilcoxon_for_metric(pivot, avail, "dahs_xgb",
                                "throughput", METRIC_DIRECTIONS["throughput"])
    for r in rows:
        assert r["cohens_d"] < 0, r
        assert r["p_value"] > 0.05, r


def test_nemenyi_returns_consistent_ranks():
    df = _synthetic_df(n_seeds=40)
    pivot = df.pivot_table(index="seed", columns="method", values="total_tardiness").dropna()
    avail = list(pivot.columns)
    out = _nemenyi_pairwise(pivot, avail)
    assert out["available"]
    ranks = out["mean_ranks"]
    assert ranks["dahs_xgb"] < ranks["atc"] < ranks["fifo"]
    assert out["critical_difference"] > 0.0
    for cell in out["pairwise"]:
        if cell["rank_diff"] > out["critical_difference"]:
            assert cell["significant"], cell
