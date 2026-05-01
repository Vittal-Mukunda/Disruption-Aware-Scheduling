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

import hashlib
import json
import logging
import time
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
from sklearn.metrics import (
    accuracy_score,
    average_precision_score,
    balanced_accuracy_score,
    brier_score_loss,
    classification_report,
    cohen_kappa_score,
    confusion_matrix,
    f1_score,
    log_loss,
    matthews_corrcoef,
    precision_recall_fscore_support,
    roc_auc_score,
)
from sklearn.model_selection import StratifiedKFold, cross_val_score, train_test_split
from sklearn.preprocessing import label_binarize
from sklearn.tree import DecisionTreeClassifier, plot_tree
from xgboost import XGBClassifier

warnings.filterwarnings("ignore", category=UserWarning)

logger = logging.getLogger(__name__)

DATA_PATH    = Path(__file__).parent.parent / "data" / "raw" / "selector_dataset.csv"
MODELS_DIR   = Path(__file__).parent.parent / "models"
RESULTS_DIR  = Path(__file__).parent.parent / "results"
PLOTS_DIR    = RESULTS_DIR / "plots"

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


def _compute_classification_metrics(
    name: str,
    model: Any,
    X_train: np.ndarray,
    y_train: np.ndarray,
    X_test: np.ndarray,
    y_test: np.ndarray,
    cv_scores: np.ndarray,
    label_names: List[str],
) -> Dict[str, Any]:
    """Compute the full Q1 classification metric stack for one model.

    Returned dict is JSON-safe; all entries are scalars or lists of scalars.
    Decisions:
      * ROC-AUC and PR-AUC: one-vs-rest, macro AND weighted (Demsar-style).
      * Brier (multiclass): mean over classes of binary Brier on one-hot.
      * MCC + Cohen's kappa: chance-corrected agreement (kappa is reported
        because some scheduling reviewers prefer it over MCC).
      * Per-class precision/recall/F1/support — ablation rows in the paper.
      * Confusion matrix saved as PNG and as a list-of-lists in JSON.
    """
    n_classes = len(label_names)
    y_pred = model.predict(X_test)

    # predict_proba can be expensive on RF — compute once.
    try:
        y_proba = model.predict_proba(X_test)
    except Exception:
        y_proba = None

    metrics: Dict[str, Any] = {
        "model": name,
        "n_train": int(X_train.shape[0]),
        "n_test": int(X_test.shape[0]),
        "n_features": int(X_train.shape[1]),
        "n_classes": n_classes,
        "accuracy": float(accuracy_score(y_test, y_pred)),
        "balanced_accuracy": float(balanced_accuracy_score(y_test, y_pred)),
        "mcc": float(matthews_corrcoef(y_test, y_pred)),
        "cohens_kappa": float(cohen_kappa_score(y_test, y_pred)),
        "f1_macro":    float(f1_score(y_test, y_pred, average="macro", zero_division=0)),
        "f1_micro":    float(f1_score(y_test, y_pred, average="micro", zero_division=0)),
        "f1_weighted": float(f1_score(y_test, y_pred, average="weighted", zero_division=0)),
        "cv_accuracy_mean": float(cv_scores.mean()),
        "cv_accuracy_std":  float(cv_scores.std()),
        "cv_accuracy_folds": [float(s) for s in cv_scores],
    }

    # Per-class precision / recall / F1 / support
    p, r, f1, support = precision_recall_fscore_support(
        y_test, y_pred, labels=list(range(n_classes)), zero_division=0,
    )
    metrics["per_class"] = [
        {
            "class": label_names[i],
            "class_idx": i,
            "precision": float(p[i]),
            "recall": float(r[i]),
            "f1": float(f1[i]),
            "support": int(support[i]),
        }
        for i in range(n_classes)
    ]

    # Confusion matrix (rows = true, cols = predicted)
    cm = confusion_matrix(y_test, y_pred, labels=list(range(n_classes)))
    metrics["confusion_matrix"] = cm.astype(int).tolist()
    metrics["confusion_matrix_labels"] = label_names

    if y_proba is not None and y_proba.shape[1] == n_classes:
        try:
            metrics["log_loss"] = float(
                log_loss(y_test, y_proba, labels=list(range(n_classes)))
            )
        except Exception:
            metrics["log_loss"] = None
        # ROC-AUC OvR (macro + weighted)
        try:
            metrics["roc_auc_ovr_macro"] = float(
                roc_auc_score(y_test, y_proba, multi_class="ovr", average="macro")
            )
            metrics["roc_auc_ovr_weighted"] = float(
                roc_auc_score(y_test, y_proba, multi_class="ovr", average="weighted")
            )
        except Exception as e:  # noqa: BLE001
            metrics["roc_auc_error"] = str(e)
        # PR-AUC OvR (macro)
        try:
            y_oh = label_binarize(y_test, classes=list(range(n_classes)))
            metrics["pr_auc_macro"] = float(
                average_precision_score(y_oh, y_proba, average="macro")
            )
            metrics["pr_auc_weighted"] = float(
                average_precision_score(y_oh, y_proba, average="weighted")
            )
            # Multiclass Brier = mean over classes of binary Brier on one-hot
            briers = [
                brier_score_loss(y_oh[:, c], y_proba[:, c])
                for c in range(n_classes)
            ]
            metrics["brier_mean"] = float(np.mean(briers))
        except Exception as e:  # noqa: BLE001
            metrics["pr_auc_error"] = str(e)
    else:
        metrics["log_loss"] = None
        metrics["roc_auc_ovr_macro"] = None
        metrics["pr_auc_macro"] = None
        metrics["brier_mean"] = None

    # Confusion matrix plot
    try:
        fig, ax = plt.subplots(figsize=(7, 6))
        fig.patch.set_facecolor("#0f1117")
        ax.set_facecolor("#1a1d27")
        cm_norm = cm.astype(float) / np.clip(cm.sum(axis=1, keepdims=True), 1, None)
        im = ax.imshow(cm_norm, cmap="viridis", vmin=0, vmax=1)
        ax.set_xticks(range(n_classes)); ax.set_yticks(range(n_classes))
        ax.set_xticklabels(label_names, rotation=35, color="#e0e0e0")
        ax.set_yticklabels(label_names, color="#e0e0e0")
        ax.set_xlabel("Predicted", color="#e0e0e0")
        ax.set_ylabel("True", color="#e0e0e0")
        ax.set_title(f"{name.upper()} — Normalized Confusion Matrix", color="#e0e0e0")
        for i in range(n_classes):
            for j in range(n_classes):
                ax.text(j, i, f"{cm_norm[i, j]:.2f}", ha="center", va="center",
                        color="white" if cm_norm[i, j] < 0.5 else "black", fontsize=8)
        plt.colorbar(im, ax=ax, fraction=0.046, pad=0.04)
        plt.tight_layout()
        out = PLOTS_DIR / f"confusion_matrix_{name}.png"
        plt.savefig(out, dpi=150, facecolor="#0f1117")
        plt.close()
    except Exception as e:  # noqa: BLE001
        logger.warning("Confusion matrix plot for %s failed: %s", name, e)

    return metrics


def _shap_summary_for_xgb(model: Any, X_sample: np.ndarray, feature_names: List[str]) -> None:
    """SHAP beeswarm for the XGB selector — multiclass mean(|SHAP|)."""
    try:
        import shap as _shap
    except Exception:
        return
    try:
        sample = X_sample[: min(400, X_sample.shape[0])]
        explainer = _shap.TreeExplainer(model)
        shap_values = explainer.shap_values(sample)
        # Multiclass returns a list (n_classes,) of (n,n_feat) arrays
        if isinstance(shap_values, list):
            mean_abs = np.mean([np.abs(s) for s in shap_values], axis=0)
        else:
            mean_abs = np.abs(shap_values)
        fig, ax = plt.subplots(figsize=(10, 8))
        fig.patch.set_facecolor("#0f1117")
        ax.set_facecolor("#1a1d27")
        _shap.summary_plot(
            mean_abs, sample,
            feature_names=feature_names,
            plot_type="dot", show=False, color_bar=True, max_display=20,
        )
        plt.gcf().set_facecolor("#0f1117")
        plt.title("XGB Selector — SHAP (mean |value| over classes)",
                  color="white", fontsize=13, pad=12)
        plt.tight_layout()
        plt.savefig(PLOTS_DIR / "shap_selector_xgb.png", dpi=150,
                    bbox_inches="tight", facecolor="#0f1117")
        plt.close()
    except Exception as e:  # noqa: BLE001
        logger.warning("SHAP for XGB selector failed: %s", e)


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

    # Training-run hash binds every artifact in this run together so the
    # selector loader can detect a stale OOD ranges file or a feature-list
    # mismatch loudly rather than silently shifting baseline-vs-DAHS results.
    run_hash = hashlib.sha256(
        f"{time.time()}|{X.shape}|{','.join(feature_cols)}|{int(y.sum())}".encode()
    ).hexdigest()[:16]

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
    all_metrics: Dict[str, Any] = {
        "_meta": {"run_hash": run_hash, "label_names": LABEL_NAMES},
        "models": {},
    }

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
        # Tag the estimator with the training-run hash so loaders can verify
        # it matches the on-disk feature_ranges.json / feature_names.json.
        try:
            setattr(model, "_dahs_run_hash", run_hash)
        except Exception:
            pass
        joblib.dump(model, model_path)
        logger.info("Saved model -> %s", model_path)

        trained[name] = model

        # Comprehensive Q1 metric stack — saved per model.
        m_dict = _compute_classification_metrics(
            name, model, X_train, y_train, X_test, y_test, cv_scores, LABEL_NAMES,
        )
        all_metrics["models"][name] = m_dict
        print(
            f"[{name.upper()}] acc={m_dict['accuracy']:.4f} "
            f"bal_acc={m_dict['balanced_accuracy']:.4f} "
            f"f1_macro={m_dict['f1_macro']:.4f} "
            f"mcc={m_dict['mcc']:.4f} "
            f"roc_auc_macro={m_dict.get('roc_auc_ovr_macro') or float('nan'):.4f}"
        )

    # ------------------------------------------------------------------
    # NEW in DAHS_2: Export interpretability artifacts
    # ------------------------------------------------------------------

    # 1. Feature ranges (for OOD detection in BatchwiseSelector)
    feature_ranges = {}
    for i, name in enumerate(feature_cols):
        feature_ranges[name] = [float(X_train[:, i].min()), float(X_train[:, i].max())]
    feature_ranges_payload = {
        "_meta": {
            "run_hash": run_hash,
            "n_train": int(X_train.shape[0]),
            "feature_count": len(feature_cols),
        },
        "ranges": feature_ranges,
    }
    with open(MODELS_DIR / "feature_ranges.json", "w") as f:
        json.dump(feature_ranges_payload, f, indent=2)
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
    feature_names_payload = {
        "_meta": {"run_hash": run_hash},
        "features": feature_names_data,
    }
    with open(MODELS_DIR / "feature_names.json", "w") as f:
        json.dump(feature_names_payload, f, indent=2)
    logger.info("Saved feature_names.json -> %s", MODELS_DIR / "feature_names.json")

    # 3. Decision tree structure (for frontend glass-box)
    dt_structure = _extract_dt_structure(trained["dt"], feature_cols)
    dt_structure["_meta"] = {"run_hash": run_hash}
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

    # Persist the unified classification metrics JSON for the paper tables.
    RESULTS_DIR.mkdir(parents=True, exist_ok=True)
    with open(RESULTS_DIR / "selector_metrics.json", "w", encoding="utf-8") as f:
        json.dump(all_metrics, f, indent=2)
    logger.info("Saved selector_metrics.json")

    # Tabular CSV — paper-ready row per model.
    try:
        rows = []
        for mn, mt in all_metrics["models"].items():
            rows.append({
                "model": mn,
                "accuracy": mt["accuracy"],
                "balanced_accuracy": mt["balanced_accuracy"],
                "f1_macro": mt["f1_macro"],
                "f1_weighted": mt["f1_weighted"],
                "mcc": mt["mcc"],
                "cohens_kappa": mt["cohens_kappa"],
                "roc_auc_ovr_macro": mt.get("roc_auc_ovr_macro"),
                "pr_auc_macro": mt.get("pr_auc_macro"),
                "log_loss": mt.get("log_loss"),
                "brier_mean": mt.get("brier_mean"),
                "cv_acc_mean": mt["cv_accuracy_mean"],
                "cv_acc_std":  mt["cv_accuracy_std"],
            })
        pd.DataFrame(rows).to_csv(
            RESULTS_DIR / "selector_metrics_table.csv", index=False,
        )
    except Exception as e:  # noqa: BLE001
        logger.warning("Selector metrics CSV failed: %s", e)

    # SHAP for the headline classifier (XGB)
    _shap_summary_for_xgb(trained["xgb"], X_test, feature_cols)

    return trained


if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
    train_selector_models()
