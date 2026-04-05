"""
train_priority.py ? Train GBR Priority Predictor

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

import joblib
import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
import numpy as np
import pandas as pd
import shap
from sklearn.ensemble import GradientBoostingRegressor
from sklearn.metrics import mean_absolute_error, mean_squared_error, r2_score
from sklearn.model_selection import KFold, cross_val_score, train_test_split

warnings.filterwarnings("ignore")

logger = logging.getLogger(__name__)

DATA_PATH = Path(__file__).parent.parent / "data" / "raw" / "priority_dataset.csv"
MODELS_DIR = Path(__file__).parent.parent / "models"
PLOTS_DIR = Path(__file__).parent.parent / "results" / "plots"


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
    df.dropna(inplace=True)

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

    # Test set metrics
    y_pred = model.predict(X_test)
    r2 = r2_score(y_test, y_pred)
    mae = mean_absolute_error(y_test, y_pred)
    rmse = float(np.sqrt(mean_squared_error(y_test, y_pred)))

    print(f"[GBR] Test R^2:   {r2:.4f}")
    print(f"[GBR] Test MAE:  {mae:.4f}")
    print(f"[GBR] Test RMSE: {rmse:.4f}")
    logger.info("GBR Test -> R^2=%.4f  MAE=%.4f  RMSE=%.4f", r2, mae, rmse)

    # 5-fold CV
    cv = KFold(n_splits=5, shuffle=True, random_state=42)
    cv_scores = cross_val_score(model, X_train, y_train, cv=cv, scoring="r2", n_jobs=-1)
    print(f"[GBR] 5-Fold CV R^2: {cv_scores.mean():.4f} +/- {cv_scores.std():.4f}")
    logger.info("GBR CV R^2: %.4f +/- %.4f", cv_scores.mean(), cv_scores.std())

    # Save model
    model_path = MODELS_DIR / "priority_gbr.joblib"
    joblib.dump(model, model_path)
    logger.info("Saved model -> %s", model_path)

    # ------------------------------------------------------------------
    # SHAP summary plot
    # ------------------------------------------------------------------
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
    plt.title("Priority GBR ? SHAP Feature Importance", color="white", fontsize=14, pad=12)
    plt.tight_layout()

    shap_path = PLOTS_DIR / "shap_summary.png"
    plt.savefig(shap_path, dpi=150, bbox_inches="tight", facecolor="#0f1117")
    plt.close()
    logger.info("Saved SHAP plot -> %s", shap_path)


if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
    train_priority_model()
