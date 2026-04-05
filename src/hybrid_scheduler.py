"""
hybrid_scheduler.py ? ML Inference Wrappers for Hybrid Dispatch

Provides two high-level callables that wrap trained models and plug into
the WarehouseSimulator as heuristic_fn replacements.

  - HybridSelector  : uses a classifier to pick the best base heuristic
  - HybridPriority  : uses a GBR regressor to score each job's priority
"""

from __future__ import annotations

import logging
from pathlib import Path
from typing import Any, Callable, Dict, List, Optional

import joblib
import numpy as np

logger = logging.getLogger(__name__)

MODELS_DIR = Path(__file__).parent.parent / "models"


class HybridSelector:
    """Wraps a trained heuristic-selector classifier.

    At dispatch time, extracts scenario-level features from the current
    system state, predicts which base heuristic to apply, and delegates
    to that heuristic.

    Parameters
    ----------
    model_path : str or Path
        Path to a saved joblib classifier file.
    feature_extractor : FeatureExtractor
        Stateful 25-feature extractor instance.
    """

    _HEURISTIC_MAP: Dict[int, str] = {
        0: "fifo",
        1: "priority_edd",
        2: "critical_ratio",
        3: "atc",
        4: "wspt",
        5: "slack",
    }

    def __init__(self, model_path: Path | str, feature_extractor: Any) -> None:
        self.model_path = Path(model_path)
        self.feature_extractor = feature_extractor
        self._model = joblib.load(self.model_path)
        self._sim_state: Optional[Dict[str, Any]] = None
        logger.info("HybridSelector loaded model from %s", self.model_path)

    def update_state(self, sim_state: Dict[str, Any]) -> None:
        """Update stored simulation state (called from simulator before dispatch)."""
        self._sim_state = sim_state

    def __call__(
        self,
        jobs: List[Any],
        current_time: float,
        zone_id: int,
    ) -> List[Any]:
        """Dispatch jobs using the predicted best heuristic.

        Falls back to FIFO if prediction fails or state is unavailable.
        """
        from src.heuristics import (
            critical_ratio_dispatch,
            fifo_dispatch,
            priority_edd_dispatch,
            atc_dispatch,
            wspt_dispatch,
            slack_dispatch,
        )

        dispatch_fns: Dict[str, Callable] = {
            "fifo": fifo_dispatch,
            "priority_edd": priority_edd_dispatch,
            "critical_ratio": critical_ratio_dispatch,
            "atc": atc_dispatch,
            "wspt": wspt_dispatch,
            "slack": slack_dispatch,
        }

        if not jobs:
            return jobs

        if self._sim_state is None:
            logger.debug("HybridSelector: no sim_state ? using FIFO")
            return fifo_dispatch(jobs, current_time, zone_id)

        try:
            features = self.feature_extractor.extract_scenario_features(
                self._sim_state
            ).reshape(1, -1)
            heuristic_idx = int(self._model.predict(features)[0])
            heuristic_name = self._HEURISTIC_MAP.get(heuristic_idx, "fifo")
            return dispatch_fns[heuristic_name](jobs, current_time, zone_id)
        except Exception as exc:
            logger.warning("HybridSelector prediction error: %s ? falling back to FIFO", exc)
            return fifo_dispatch(jobs, current_time, zone_id)


class HybridPriority:
    """Wraps a trained GBR priority-predictor regressor.

    At dispatch time, extracts job-level features for every waiting job,
    predicts a continuous priority score, and returns jobs sorted by
    score descending (highest priority first).

    Parameters
    ----------
    model_path : str or Path
        Path to a saved joblib regressor file.
    feature_extractor : FeatureExtractor
        Stateful 25-feature extractor instance.
    """

    def __init__(self, model_path: Path | str, feature_extractor: Any) -> None:
        self.model_path = Path(model_path)
        self.feature_extractor = feature_extractor
        self._model = joblib.load(self.model_path)
        self._sim_state: Optional[Dict[str, Any]] = None
        logger.info("HybridPriority loaded model from %s", self.model_path)

    def update_state(self, sim_state: Dict[str, Any]) -> None:
        """Update stored simulation state."""
        self._sim_state = sim_state

    def __call__(
        self,
        jobs: List[Any],
        current_time: float,
        zone_id: int,
    ) -> List[Any]:
        """Dispatch jobs by predicted priority score (descending).

        Falls back to FIFO if prediction fails.
        """
        from src.heuristics import fifo_dispatch

        if not jobs:
            return jobs

        if self._sim_state is None:
            logger.debug("HybridPriority: no sim_state ? using FIFO")
            return fifo_dispatch(jobs, current_time, zone_id)

        try:
            # Extract scenario features once, then batch all job features
            sf = self.feature_extractor.extract_scenario_features(self._sim_state)
            job_feats = np.stack([
                np.concatenate([sf, self.feature_extractor.extract_job_features(job, self._sim_state)])
                for job in jobs
            ])
            predictions = self._model.predict(job_feats)
            ranked = sorted(zip(predictions, jobs), key=lambda x: x[0], reverse=True)
            return [job for _, job in ranked]
        except Exception as exc:
            logger.warning("HybridPriority prediction error: %s ? falling back to FIFO", exc)
            return fifo_dispatch(jobs, current_time, zone_id)


# ---------------------------------------------------------------------------
# Factory helpers
# ---------------------------------------------------------------------------

def load_hybrid_selector(model_name: str = "rf", feature_extractor: Any = None) -> HybridSelector:
    """Load a HybridSelector for a given classifier variant.

    Parameters
    ----------
    model_name : str
        One of "dt", "rf", "xgb".
    feature_extractor : FeatureExtractor
        Feature extraction instance.
    """
    if feature_extractor is None:
        from src.features import FeatureExtractor
        feature_extractor = FeatureExtractor()
    path = MODELS_DIR / f"selector_{model_name}.joblib"
    return HybridSelector(model_path=path, feature_extractor=feature_extractor)


def load_hybrid_priority(feature_extractor: Any = None) -> HybridPriority:
    """Load the GBR-based HybridPriority scheduler.

    Parameters
    ----------
    feature_extractor : FeatureExtractor
        Feature extraction instance.
    """
    if feature_extractor is None:
        from src.features import FeatureExtractor
        feature_extractor = FeatureExtractor()
    path = MODELS_DIR / "priority_gbr.joblib"
    return HybridPriority(model_path=path, feature_extractor=feature_extractor)
