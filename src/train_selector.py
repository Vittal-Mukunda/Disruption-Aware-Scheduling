"""
train_selector.py ? Train Heuristic Selector Models

Trains three classifiers (Decision Tree, Random Forest, XGBoost) to predict
which of 6 heuristics achieves the best dispatching outcome for a given
system state.

Outputs:
  - models/selector_dt.joblib
  - models/selector_rf.joblib
  - models/selector_xgb.joblib
  - results/plots/feature_importance.png
  - results/plots/decision_tree.png
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
from sklearn.ensemble import RandomForestClassifier
from sklearn.metrics import classification_report
from sklearn.model_selection import StratifiedKFold, cross_val_score, train_test_split
from sklearn.tree import DecisionTreeClassifier, plot_tree
from xgboost import XGBClassifier

warnings.filterwarnings("ignore", category=UserWarning)

logger = logging.getLogger(__name__)

DATA_PATH = Path(__file__).parent.parent / "data" / "raw" / "selector_dataset.csv"
MODELS_DIR = Path(__file__).parent.parent / "models"
PLOTS_DIR = Path(__file__).parent.parent / "results" / "plots"

LABEL_NAMES = ["FIFO", "Priority-EDD", "Critical-Ratio", "ATC", "WSPT", "Slack"]


def train_selector_models(data_path: Path = DATA_PATH) -> dict:
    """Train all three selector classifiers and save artifacts.

    Returns
    -------
    dict
        Mapping model_name -> trained sklearn-compatible model.
    """
    MODELS_DIR.mkdir(parents=True, exist_ok=True)
    PLOTS_DIR.mkdir(parents=True, exist_ok=True)

    logger.info("Loading selector dataset from %s", data_path)
    df = pd.read_csv(data_path)

    feature_cols = [c for c in df.columns if c != "label"]
    X = df[feature_cols].values.astype(np.float32)
    y = df["label"].values.astype(int)

    logger.info("Dataset shape: X=%s, label distribution: %s",
                X.shape, dict(zip(*np.unique(y, return_counts=True))))

    X_train, X_test, y_train, y_test = train_test_split(
        X, y, test_size=0.20, random_state=42, stratify=y
    )

    cv = StratifiedKFold(n_splits=5, shuffle=True, random_state=42)

    models = {
        "dt": DecisionTreeClassifier(
            max_depth=10,
            class_weight="balanced",
            random_state=42,
        ),
        "rf": RandomForestClassifier(
            n_estimators=400,
            max_depth=14,
            class_weight="balanced",
            n_jobs=-1,
            random_state=42,
        ),
        "xgb": XGBClassifier(
            n_estimators=500,
            learning_rate=0.03,
            max_depth=8,
            num_class=len(LABEL_NAMES),
            n_jobs=-1,
            random_state=42,
            eval_metric="mlogloss",
            verbosity=0,
        ),
    }

    trained = {}

    for name, model in models.items():
        logger.info("Training %s ...", name.upper())
        model.fit(X_train, y_train)

        # 5-fold CV accuracy
        cv_scores = cross_val_score(model, X_train, y_train, cv=cv, scoring="accuracy", n_jobs=-1)
        logger.info("[%s] CV accuracy: %.4f +/- %.4f", name.upper(), cv_scores.mean(), cv_scores.std())
        print(f"[{name.upper()}] 5-Fold CV Accuracy: {cv_scores.mean():.4f} +/- {cv_scores.std():.4f}")

        # Test set classification report
        y_pred = model.predict(X_test)
        print(f"\n[{name.upper()}] Classification Report (Test Set):")
        print(classification_report(
            y_test, y_pred,
            labels=list(range(len(LABEL_NAMES))),
            target_names=LABEL_NAMES,
            zero_division=0,
        ))

        # Save model
        model_path = MODELS_DIR / f"selector_{name}.joblib"
        joblib.dump(model, model_path)
        logger.info("Saved model -> %s", model_path)

        trained[name] = model

    # ------------------------------------------------------------------
    # Feature importance plot (RF + XGB side-by-side)
    # ------------------------------------------------------------------
    feature_names = feature_cols
    rf_importances = trained["rf"].feature_importances_
    xgb_importances = trained["xgb"].feature_importances_

    fig, axes = plt.subplots(1, 2, figsize=(16, 8))
    fig.patch.set_facecolor("#0f1117")

    for ax, importances, title, color in zip(
        axes,
        [rf_importances, xgb_importances],
        ["Random Forest Feature Importance", "XGBoost Feature Importance"],
        ["#4fc3f7", "#a5d6a7"],
    ):
        ax.set_facecolor("#1a1d27")
        sorted_idx = np.argsort(importances)[-15:]  # top 15
        bars = ax.barh(
            [feature_names[i] for i in sorted_idx],
            importances[sorted_idx],
            color=color,
            alpha=0.85,
        )
        ax.set_title(title, color="white", fontsize=13, pad=10)
        ax.set_xlabel("Importance", color="#aaaaaa")
        ax.tick_params(colors="#cccccc", labelsize=9)
        ax.spines[:].set_color("#333344")
        for spine in ax.spines.values():
            spine.set_linewidth(0.5)

    fig.suptitle("Heuristic Selector ? Feature Importances", color="white", fontsize=15, y=1.01)
    plt.tight_layout()
    fi_path = PLOTS_DIR / "feature_importance.png"
    plt.savefig(fi_path, dpi=150, bbox_inches="tight", facecolor=fig.get_facecolor())
    plt.close()
    logger.info("Saved feature importance plot -> %s", fi_path)

    # ------------------------------------------------------------------
    # Decision tree visualization
    # ------------------------------------------------------------------
    fig, ax = plt.subplots(figsize=(24, 10))
    fig.patch.set_facecolor("#0f1117")
    ax.set_facecolor("#0f1117")
    plot_tree(
        trained["dt"],
        feature_names=feature_names,
        class_names=LABEL_NAMES,
        filled=True,
        max_depth=4,
        fontsize=7,
        ax=ax,
    )
    ax.set_title("Decision Tree Classifier (depth?4 shown)", color="white", fontsize=14)
    dt_path = PLOTS_DIR / "decision_tree.png"
    plt.savefig(dt_path, dpi=120, bbox_inches="tight", facecolor=fig.get_facecolor())
    plt.close()
    logger.info("Saved decision tree plot -> %s", dt_path)

    return trained


if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
    train_selector_models()
