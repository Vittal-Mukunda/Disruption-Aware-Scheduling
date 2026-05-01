"""
train_priority.py — Train GBR Priority Predictor (port from DAHS_1)

Trains a GradientBoostingRegressor on the priority dataset to predict
a continuous job priority score used by the Hybrid-Priority scheduler.

Outputs:
  - models/priority_gbr.joblib
  - results/plots/shap_summary.png
"""

from __future__ import annotations

import logging
import warnings
from pathlib import Path

import json

import joblib
import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
import numpy as np
import pandas as pd
import shap
from scipy.stats import pearsonr, spearmanr
from sklearn.ensemble import GradientBoostingRegressor
from sklearn.metrics import (
    explained_variance_score,
    max_error,
    mean_absolute_error,
    mean_absolute_percentage_error,
    mean_squared_error,
    median_absolute_error,
    r2_score,
)
from sklearn.model_selection import KFold, cross_val_score, train_test_split

warnings.filterwarnings("ignore")

logger = logging.getLogger(__name__)

DATA_PATH    = Path(__file__).parent.parent / "data" / "raw" / "priority_dataset.csv"
MODELS_DIR   = Path(__file__).parent.parent / "models"
RESULTS_DIR  = Path(__file__).parent.parent / "results"
PLOTS_DIR    = RESULTS_DIR / "plots"


def train_priority_model(data_path: Path = DATA_PATH) -> GradientBoostingRegressor:
    """Train and evaluate the GBR priority predictor.

    Returns
    -------
    GradientBoostingRegressor
        Fitted model.
    """
    MODELS_DIR.mkdir(parents=True, exist_ok=True)
    PLOTS_DIR.mkdir(parents=True, exist_ok=True)

    logger.info("Loading priority dataset from %s", data_path)
    df = pd.read_csv(data_path)
    # Bug fix from DAHS_1: use replace + dropna (not nan_to_num alone)
    df = df.replace([np.inf, -np.inf], np.nan).dropna()

    feature_cols = [c for c in df.columns if c != "priority_score"]
    X = df[feature_cols].values.astype(np.float32)
    y = df["priority_score"].values.astype(np.float32)

    logger.info("Priority dataset shape: X=%s, y=%s", X.shape, y.shape)

    X_train, X_test, y_train, y_test = train_test_split(
        X, y, test_size=0.20, random_state=42
    )

    model = GradientBoostingRegressor(
        n_estimators=300,
        max_depth=6,
        learning_rate=0.05,
        subsample=0.8,
        min_samples_leaf=5,
        random_state=42,
    )

    logger.info("Training GradientBoostingRegressor ...")
    model.fit(X_train, y_train)

    y_pred = model.predict(X_test)
    residuals = y_test - y_pred
    r2   = float(r2_score(y_test, y_pred))
    mae  = float(mean_absolute_error(y_test, y_pred))
    medae = float(median_absolute_error(y_test, y_pred))
    rmse = float(np.sqrt(mean_squared_error(y_test, y_pred)))
    evs  = float(explained_variance_score(y_test, y_pred))
    maxe = float(max_error(y_test, y_pred))
    # MAPE: guard against zero targets
    try:
        mape = float(mean_absolute_percentage_error(
            np.where(np.abs(y_test) < 1e-6, 1e-6, y_test), y_pred
        ))
    except Exception:
        mape = float("nan")
    pearson_r, pearson_p   = pearsonr(y_test, y_pred)
    spearman_r, spearman_p = spearmanr(y_test, y_pred)

    print(f"[GBR] Test R^2:   {r2:.4f}")
    print(f"[GBR] Test MAE:   {mae:.4f}  (median: {medae:.4f})")
    print(f"[GBR] Test RMSE:  {rmse:.4f}")
    print(f"[GBR] Test MAPE:  {mape:.4f}")
    print(f"[GBR] Pearson r:  {pearson_r:.4f} (p={pearson_p:.2e})")
    print(f"[GBR] Spearman ρ: {spearman_r:.4f} (p={spearman_p:.2e})")
    logger.info("GBR Test -> R^2=%.4f MAE=%.4f RMSE=%.4f MAPE=%.4f", r2, mae, rmse, mape)

    cv = KFold(n_splits=5, shuffle=True, random_state=42)
    cv_r2  = cross_val_score(model, X_train, y_train, cv=cv, scoring="r2", n_jobs=-1)
    cv_mae = -cross_val_score(model, X_train, y_train, cv=cv,
                              scoring="neg_mean_absolute_error", n_jobs=-1)
    print(f"[GBR] 5-Fold CV R^2: {cv_r2.mean():.4f} +/- {cv_r2.std():.4f}")
    print(f"[GBR] 5-Fold CV MAE: {cv_mae.mean():.4f} +/- {cv_mae.std():.4f}")
    logger.info("GBR CV R^2: %.4f +/- %.4f", cv_r2.mean(), cv_r2.std())

    model_path = MODELS_DIR / "priority_gbr.joblib"
    joblib.dump(model, model_path)
    logger.info("Saved model -> %s", model_path)

    # ------------------------------------------------------------------
    # Persist comprehensive metrics JSON (paper-ready)
    # ------------------------------------------------------------------
    RESULTS_DIR.mkdir(parents=True, exist_ok=True)
    metrics = {
        "model": "GradientBoostingRegressor",
        "n_train": int(X_train.shape[0]),
        "n_test":  int(X_test.shape[0]),
        "n_features": int(X_train.shape[1]),
        "test": {
            "r2": r2,
            "explained_variance": evs,
            "mae": mae,
            "median_abs_err": medae,
            "rmse": rmse,
            "mape": mape,
            "max_error": maxe,
            "pearson_r": float(pearson_r),
            "pearson_p": float(pearson_p),
            "spearman_rho": float(spearman_r),
            "spearman_p": float(spearman_p),
        },
        "residuals": {
            "mean": float(residuals.mean()),
            "std":  float(residuals.std()),
            "p05":  float(np.percentile(residuals, 5)),
            "p50":  float(np.percentile(residuals, 50)),
            "p95":  float(np.percentile(residuals, 95)),
        },
        "cv": {
            "r2_mean":  float(cv_r2.mean()),
            "r2_std":   float(cv_r2.std()),
            "r2_folds": [float(s) for s in cv_r2],
            "mae_mean": float(cv_mae.mean()),
            "mae_std":  float(cv_mae.std()),
            "mae_folds": [float(s) for s in cv_mae],
        },
    }
    with open(RESULTS_DIR / "priority_metrics.json", "w", encoding="utf-8") as f:
        json.dump(metrics, f, indent=2)
    logger.info("Saved priority_metrics.json")

    # ------------------------------------------------------------------
    # Diagnostic plots: actual-vs-predicted + residuals
    # ------------------------------------------------------------------
    try:
        fig, axes = plt.subplots(1, 2, figsize=(14, 6))
        fig.patch.set_facecolor("#0f1117")
        for ax in axes:
            ax.set_facecolor("#1a1d27")
            ax.tick_params(colors="#cccccc")
        # Actual vs predicted
        ax = axes[0]
        ax.scatter(y_test, y_pred, s=8, alpha=0.4, color="#4fc3f7")
        lo, hi = float(min(y_test.min(), y_pred.min())), float(max(y_test.max(), y_pred.max()))
        ax.plot([lo, hi], [lo, hi], "--", color="#e57373", linewidth=1.5, label="y = x")
        ax.set_xlabel("Actual priority", color="#e0e0e0")
        ax.set_ylabel("Predicted priority", color="#e0e0e0")
        ax.set_title(f"GBR — Actual vs Predicted (R²={r2:.3f})", color="#e0e0e0")
        ax.legend()
        # Residuals
        ax = axes[1]
        ax.hist(residuals, bins=50, color="#81c784", alpha=0.85, edgecolor="#0f1117")
        ax.axvline(0, color="#e57373", linestyle="--", linewidth=1)
        ax.set_xlabel("Residual (actual − predicted)", color="#e0e0e0")
        ax.set_ylabel("Count", color="#e0e0e0")
        ax.set_title(f"Residuals (μ={residuals.mean():.3f}, σ={residuals.std():.3f})",
                     color="#e0e0e0")
        plt.tight_layout()
        plt.savefig(PLOTS_DIR / "priority_diagnostics.png", dpi=150, facecolor="#0f1117")
        plt.close()
    except Exception as e:  # noqa: BLE001
        logger.warning("Priority diagnostic plot failed: %s", e)

    _generate_shap_plot(model, X_test, feature_cols)

    return model


def _generate_shap_plot(
    model: GradientBoostingRegressor,
    X_sample: np.ndarray,
    feature_names: list,
) -> None:
    """Generate and save SHAP beeswarm summary plot."""
    logger.info("Computing SHAP values ...")
    sample_size = min(500, X_sample.shape[0])
    X_shap = X_sample[:sample_size]

    explainer = shap.TreeExplainer(model)
    shap_values = explainer.shap_values(X_shap)

    fig, ax = plt.subplots(figsize=(10, 8))
    fig.patch.set_facecolor("#0f1117")
    ax.set_facecolor("#1a1d27")

    shap.summary_plot(
        shap_values,
        X_shap,
        feature_names=feature_names,
        show=False,
        plot_type="dot",
        color_bar=True,
        max_display=18,
    )

    plt.gcf().set_facecolor("#0f1117")
    plt.title("Priority GBR — SHAP Feature Importance", color="white", fontsize=14, pad=12)
    plt.tight_layout()

    shap_path = PLOTS_DIR / "shap_summary.png"
    plt.savefig(shap_path, dpi=150, bbox_inches="tight", facecolor="#0f1117")
    plt.close()
    logger.info("Saved SHAP plot -> %s", shap_path)


if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
    train_priority_model()
