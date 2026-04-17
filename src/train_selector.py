"""
train_selector.py — Train Heuristic Selector Models (DAHS_2)

Trains three classifiers (Decision Tree, Random Forest, XGBoost) to predict
which of 6 heuristics achieves the best dispatching outcome for a given
system state (snapshot-fork labels).

NEW in DAHS_2:
  - Exports models/feature_ranges.json
  - Exports models/dt_structure.json (for frontend glass-box)
  - Exports models/feature_names.json

Outputs:
  - models/selector_dt.joblib
  - models/selector_rf.joblib
  - models/selector_xgb.joblib
  - models/feature_ranges.json
  - models/dt_structure.json
  - models/feature_names.json
  - results/plots/feature_importance.png
  - results/plots/decision_tree.png
"""

from __future__ import annotations

import json
import logging
import warnings
from pathlib import Path
from typing import Any, Dict, List

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

DATA_PATH  = Path(__file__).parent.parent / "data" / "raw" / "selector_dataset.csv"
MODELS_DIR = Path(__file__).parent.parent / "models"
PLOTS_DIR  = Path(__file__).parent.parent / "results" / "plots"

LABEL_NAMES = ["FIFO", "Priority-EDD", "Critical-Ratio", "ATC", "WSPT", "Slack"]


def _extract_dt_structure(dt: DecisionTreeClassifier, feature_names: List[str]) -> Dict[str, Any]:
    """Extract decision tree node structure for frontend glass-box visualization.

    Returns a dict with nodes list, each node having:
    {id, feature, threshold, left, right, class, samples, impurity}
    """
    tree = dt.tree_
    nodes = []

    def _recurse(node_id: int) -> None:
        feature_idx = int(tree.feature[node_id])
        threshold   = float(tree.threshold[node_id])
        left_child  = int(tree.children_left[node_id])
        right_child = int(tree.children_right[node_id])
        values      = tree.value[node_id][0]
        dominant    = int(np.argmax(values))
        samples     = int(tree.n_node_samples[node_id])
        impurity    = float(tree.impurity[node_id])

        node: Dict[str, Any] = {
            "id": node_id,
            "samples": samples,
            "impurity": round(impurity, 4),
            "class": LABEL_NAMES[dominant],
            "classIdx": dominant,
            "values": [int(v) for v in values],
        }

        if left_child != -1:  # not a leaf
            feat_name = feature_names[feature_idx] if feature_idx < len(feature_names) else f"f{feature_idx}"
            node["feature"] = feat_name
            node["featureIdx"] = feature_idx
            node["threshold"] = round(threshold, 4)
            node["left"] = left_child
            node["right"] = right_child
            _recurse(left_child)
            _recurse(right_child)

        nodes.append(node)

    _recurse(0)
    return {"nodes": nodes, "featureNames": feature_names, "classNames": LABEL_NAMES}


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
    # Sanitize: NaN/inf safety (training pipeline bug fix from DAHS_1)
    X = np.nan_to_num(X, nan=0.0, posinf=999.0, neginf=-999.0)
    y = df["label"].values.astype(int)

    logger.info("Dataset shape: X=%s, label distribution: %s",
                X.shape, dict(zip(*np.unique(y, return_counts=True))))

    X_train, X_test, y_train, y_test = train_test_split(
        X, y, test_size=0.20, random_state=42, stratify=y
    )

    # CV seed different from train/test split seed (bug fix)
    cv = StratifiedKFold(n_splits=5, shuffle=True, random_state=123)

    from sklearn.utils.class_weight import compute_sample_weight
    sample_weights_train = compute_sample_weight("balanced", y_train)

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
        if name == "xgb":
            model.fit(X_train, y_train, sample_weight=sample_weights_train)
        else:
            model.fit(X_train, y_train)

        # 5-fold CV accuracy
        cv_scores = cross_val_score(model, X_train, y_train, cv=cv, scoring="accuracy", n_jobs=-1)
        logger.info("[%s] CV accuracy: %.4f +/- %.4f", name.upper(), cv_scores.mean(), cv_scores.std())
        print(f"[{name.upper()}] 5-Fold CV Accuracy: {cv_scores.mean():.4f} +/- {cv_scores.std():.4f}")

        y_pred = model.predict(X_test)
        print(f"\n[{name.upper()}] Classification Report (Test Set):")
        print(classification_report(
            y_test, y_pred,
            labels=list(range(len(LABEL_NAMES))),
            target_names=LABEL_NAMES,
            zero_division=0,
        ))

        model_path = MODELS_DIR / f"selector_{name}.joblib"
        joblib.dump(model, model_path)
        logger.info("Saved model -> %s", model_path)

        trained[name] = model

    # ------------------------------------------------------------------
    # NEW in DAHS_2: Export interpretability artifacts
    # ------------------------------------------------------------------

    # 1. Feature ranges (for OOD detection in BatchwiseSelector)
    feature_ranges = {}
    for i, name in enumerate(feature_cols):
        feature_ranges[name] = [float(X_train[:, i].min()), float(X_train[:, i].max())]
    with open(MODELS_DIR / "feature_ranges.json", "w") as f:
        json.dump(feature_ranges, f, indent=2)
    logger.info("Saved feature_ranges.json -> %s", MODELS_DIR / "feature_ranges.json")

    # 2. Feature names with descriptions
    from src.features import FEATURE_DESCRIPTIONS
    feature_names_data = [
        {
            "name": name,
            "description": FEATURE_DESCRIPTIONS.get(name, name),
            "category": (
                "disruption" if name in ("disruption_intensity", "queue_imbalance", "job_mix_entropy", "time_pressure_ratio")
                else "utilization" if "utilization" in name or "bottleneck" in name
                else "timing" if "due" in name or "tard" in name or "sla" in name
                else "queue" if "queue" in name or "throughput" in name
                else "system"
            ),
            "index": i,
        }
        for i, name in enumerate(feature_cols)
    ]
    with open(MODELS_DIR / "feature_names.json", "w") as f:
        json.dump(feature_names_data, f, indent=2)
    logger.info("Saved feature_names.json -> %s", MODELS_DIR / "feature_names.json")

    # 3. Decision tree structure (for frontend glass-box)
    dt_structure = _extract_dt_structure(trained["dt"], feature_cols)
    with open(MODELS_DIR / "dt_structure.json", "w") as f:
        json.dump(dt_structure, f, indent=2)
    logger.info("Saved dt_structure.json -> %s", MODELS_DIR / "dt_structure.json")

    # ------------------------------------------------------------------
    # Feature importance plot (RF + XGB side-by-side, dark theme)
    # ------------------------------------------------------------------
    rf_importances  = trained["rf"].feature_importances_
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
        sorted_idx = np.argsort(importances)[-15:]
        ax.barh(
            [feature_cols[i] for i in sorted_idx],
            importances[sorted_idx],
            color=color,
            alpha=0.85,
        )
        ax.set_title(title, color="white", fontsize=13, pad=10)
        ax.set_xlabel("Importance", color="#aaaaaa")
        ax.tick_params(colors="#cccccc", labelsize=9)
        for spine in ax.spines.values():
            spine.set_color("#333344")
            spine.set_linewidth(0.5)

    fig.suptitle("Heuristic Selector — Feature Importances (DAHS_2)", color="white", fontsize=15, y=1.01)
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
        feature_names=feature_cols,
        class_names=LABEL_NAMES,
        filled=True,
        max_depth=4,
        fontsize=7,
        ax=ax,
    )
    ax.set_title("Decision Tree Classifier (depth≤4 shown)", color="white", fontsize=14)
    dt_path = PLOTS_DIR / "decision_tree.png"
    plt.savefig(dt_path, dpi=120, bbox_inches="tight", facecolor=fig.get_facecolor())
    plt.close()
    logger.info("Saved decision tree plot -> %s", dt_path)

    return trained


if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
    train_selector_models()
