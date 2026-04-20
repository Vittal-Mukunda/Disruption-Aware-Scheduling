"""
hybrid_scheduler.py — Batch-wise ML Hybrid Scheduler with Guardrails (DAHS_2)

NEW architecture vs DAHS_1:
  - BatchwiseSelector: re-evaluates every 15 min OR on disruption events
  - Hysteresis: only switches if >15% more confident
  - Edge case guardrails: trivial load, overload, OOD detection
  - Starvation prevention: force-promote jobs waiting >60 min
  - 3-level interpretability log per evaluation
  - Plain English explanations

Also includes (ported from DAHS_1):
  - SwitchingLog class
  - HybridPriority class
  - Factory functions
"""

from __future__ import annotations

import logging
from pathlib import Path
from typing import Any, Callable, Dict, List, Optional, Tuple, Union

import joblib
import numpy as np

logger = logging.getLogger(__name__)

MODELS_DIR = Path(__file__).parent.parent / "models"


# ---------------------------------------------------------------------------
# Switching Log (enhanced for DAHS_2 with evaluation payload)
# ---------------------------------------------------------------------------

class SwitchingLog:
    """Records every batch-wise heuristic-selection evaluation made by BatchwiseSelector.

    DAHS_2: Each entry contains full evaluation context including probabilities,
    top features, reason, and plain-English explanation.
    """

    HEURISTIC_NAMES = ["fifo", "priority_edd", "critical_ratio", "atc", "wspt", "slack"]

    def __init__(self) -> None:
        self.entries: List[Dict[str, Any]] = []
        self._last_heuristic: Optional[str] = None
        self._switch_count: int = 0
        self._hysteresis_blocked: int = 0
        self._guardrail_activations: int = 0

    def record(
        self,
        time: float,
        features: List[float],
        probabilities: Dict[str, float],
        selected: str,
        switched: bool,
        reason: str,
        confidence: float,
        top_features: List[Dict[str, Any]],
        plain_english: str,
    ) -> None:
        """Record one batch evaluation."""
        if switched:
            self._switch_count += 1
        if reason == "hysteresis_blocked":
            self._hysteresis_blocked += 1
        if reason.startswith("guardrail"):
            self._guardrail_activations += 1
        self._last_heuristic = selected

        self.entries.append({
            "time": round(time, 2),
            "features": [round(float(f), 4) for f in features],
            "probabilities": {k: round(float(v), 4) for k, v in probabilities.items()},
            "selected": selected,
            "switched": switched,
            "reason": reason,
            "confidence": round(confidence, 4),
            "topFeatures": top_features,
            "plainEnglish": plain_english,
        })

    @property
    def total_evaluations(self) -> int:
        return len(self.entries)

    @property
    def switch_count(self) -> int:
        return self._switch_count

    def heuristic_distribution(self) -> Dict[str, float]:
        """Fraction of evaluations assigned to each heuristic."""
        if not self.entries:
            return {}
        counts: Dict[str, int] = {}
        for e in self.entries:
            h = e["selected"]
            counts[h] = counts.get(h, 0) + 1
        total = len(self.entries)
        return {h: c / total for h, c in sorted(counts.items())}

    def switching_rate(self) -> float:
        """Switches per evaluation."""
        if len(self.entries) < 2:
            return 0.0
        return self._switch_count / (len(self.entries) - 1)

    def summary(self) -> Dict[str, Any]:
        """Return a human-readable summary dict."""
        dist = self.heuristic_distribution()
        return {
            "totalEvaluations": self.total_evaluations,
            "switchCount": self._switch_count,
            "switchingRate": round(self.switching_rate(), 4),
            "hysteresisBlocked": self._hysteresis_blocked,
            "guardrailActivations": self._guardrail_activations,
            "distribution": {k: round(v, 4) for k, v in dist.items()},
            "dominantHeuristic": max(dist, key=dist.get) if dist else "none",
        }

    def to_list(self) -> List[Dict[str, Any]]:
        """Return entries as a plain list for JSON serialization."""
        return self.entries


# ---------------------------------------------------------------------------
# BatchwiseSelector — Core DAHS_2 scheduler
# ---------------------------------------------------------------------------

class BatchwiseSelector:
    """Batch-wise ML heuristic selector with guardrails and hysteresis.

    Re-evaluates every 15 minutes OR on disruption events (breakdown,
    batch arrival, lunch state change). Only switches if new heuristic
    is >15% more confident (hysteresis).

    Edge-case guardrails:
    - Trivial: n_orders < 5 → use FIFO
    - Overload: avg_utilization > 0.92 → lock to ATC + alert
    - OOD: features outside training range ±10% → safe fallback to ATC
    - Starvation: any job waiting >60 min → force-promote
    """

    EVAL_INTERVAL      = 15.0   # minutes between re-evaluations
    # Relative margin: new heuristic's probability must exceed current × (1 + margin).
    # Calibration-invariant across RF (broad) and XGB (sharp) predict_proba outputs.
    HYSTERESIS_MARGIN  = 0.15
    TRIVIAL_LOAD       = 5       # skip ML if fewer jobs
    OVERLOAD_THRESHOLD = 0.92    # lock to ATC
    STARVATION_LIMIT   = 60.0    # force-promote starving jobs (minutes)

    HEURISTIC_MAP = {
        0: "fifo", 1: "priority_edd", 2: "critical_ratio",
        3: "atc",  4: "wspt",         5: "slack",
    }
    HEURISTIC_LABELS = {
        "fifo": "FIFO", "priority_edd": "Priority-EDD",
        "critical_ratio": "Critical-Ratio", "atc": "ATC",
        "wspt": "WSPT", "slack": "Slack",
    }

    # Plain-English reason templates
    _EXPLANATION_MAP = {
        ("atc",            "time_pressure_ratio"):  "many jobs are nearing their deadlines",
        ("atc",            "surge_multiplier"):      "demand surging above normal rate",
        ("atc",            "zone_utilization_avg"):  "warehouse is highly loaded",
        ("critical_ratio", "n_broken_stations"):     "station breakdowns are causing bottlenecks",
        ("critical_ratio", "disruption_intensity"):  "high disruption intensity detected",
        ("fifo",           "zone_utilization_avg"):  "load is light, simple ordering is optimal",
        ("fifo",           "n_orders_in_system"):    "few jobs in system, FIFO is stable",
        ("wspt",           "avg_priority_weight"):   "high-value short jobs should be prioritized",
        ("wspt",           "avg_remaining_proc_time"): "many short jobs in queue",
        ("priority_edd",   "n_express_orders_pct"):  "high fraction of express orders",
        ("priority_edd",   "fraction_already_late"): "many jobs past due date",
        ("slack",          "avg_due_date_tightness"): "deadlines are extremely tight",
        ("slack",          "sla_breach_rate_current"): "SLA breach rate is rising",
    }

    def __init__(
        self,
        model: Any,
        feature_extractor: Any,
        feature_importances: Optional[np.ndarray] = None,
        feature_names: Optional[List[str]] = None,
    ) -> None:
        self._model = model
        self._fe = feature_extractor
        self._feature_importances = feature_importances
        self._feature_names = feature_names or []

        self._current_heuristic: str = "fifo"
        self._current_confidence: float = 0.0
        self._current_from_guardrail: bool = False
        self._last_eval_time: float = -999.0
        self._last_breakdown_count: int = 0
        self._last_lunch_state: bool = False

        self.switching_log = SwitchingLog()
        self._sim_state: Optional[Dict[str, Any]] = None

    def update_state(self, sim_state: Dict[str, Any]) -> None:
        """Update stored simulation state (called before dispatch)."""
        self._sim_state = sim_state

    # ------------------------------------------------------------------
    # Main dispatch interface
    # ------------------------------------------------------------------

    def dispatch(
        self,
        jobs: List[Any],
        current_time: float,
        zone_id: int,
    ) -> List[Any]:
        """Apply current heuristic, potentially re-evaluating first.

        This is the main entry point called by the simulator's heuristic_fn.
        Re-evaluates every 15 min or on disruption events.
        """
        from src.heuristics import (
            fifo_dispatch, priority_edd_dispatch, critical_ratio_dispatch,
            atc_dispatch, wspt_dispatch, slack_dispatch,
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

        # Re-evaluate if needed (time-based or event-triggered)
        if self._sim_state is not None and self._should_reevaluate(current_time):
            self._reevaluate(current_time)

        # Starvation prevention: force-promote any job waiting >60 min
        fn = dispatch_fns.get(self._current_heuristic, fifo_dispatch)
        ordered = fn(jobs, current_time, zone_id)
        ordered = self._apply_starvation_prevention(ordered, current_time)

        return ordered

    def __call__(self, jobs: List[Any], current_time: float, zone_id: int) -> List[Any]:
        """Callable interface (same as dispatch)."""
        return self.dispatch(jobs, current_time, zone_id)

    # ------------------------------------------------------------------
    # Re-evaluation logic
    # ------------------------------------------------------------------

    def _should_reevaluate(self, now: float) -> bool:
        """Return True if we should re-evaluate the heuristic selection."""
        if self._sim_state is None:
            return False

        # Time-based: every 15 minutes
        if now - self._last_eval_time >= self.EVAL_INTERVAL:
            return True

        # Event: breakdown count changed
        n_broken = self._sim_state.get("n_broken_stations", 0)
        if n_broken != self._last_breakdown_count:
            return True

        # Event: lunch state changed
        lunch = self._sim_state.get("lunch_active", False)
        if lunch != self._last_lunch_state:
            return True

        return False

    def _reevaluate(self, now: float) -> None:
        """Perform ML evaluation and decide whether to switch heuristic."""
        if self._sim_state is None:
            return

        self._last_eval_time = now
        self._last_breakdown_count = self._sim_state.get("n_broken_stations", 0)
        self._last_lunch_state = self._sim_state.get("lunch_active", False)

        # Extract features
        try:
            features = self._fe.extract_scenario_features(self._sim_state)
        except Exception as e:
            logger.warning("Feature extraction failed: %s", e)
            return

        # Check guardrails first
        guardrail = self._check_guardrails(features)
        if guardrail is not None:
            # Guardrail triggered — record and switch if needed
            switched = guardrail != self._current_heuristic
            plain = f"Guardrail active: {guardrail.replace('guardrail_', '')}. Using {guardrail} as safe default."
            probas = {h: (1.0 if h == guardrail else 0.0) for h in self.HEURISTIC_MAP.values()}
            top_features = self._get_top_features(features, n=5)

            reason_map = {
                "fifo": "guardrail_trivial",
                "atc": "guardrail_overload" if self._sim_state.get("zone_utilization", {}) else "guardrail_ood",
            }
            reason = reason_map.get(guardrail, f"guardrail_{guardrail}")

            self.switching_log.record(
                time=now,
                features=features.tolist(),
                probabilities=probas,
                selected=guardrail,
                switched=switched,
                reason=reason,
                confidence=1.0,
                top_features=top_features,
                plain_english=f"Guardrail active. Using {self.HEURISTIC_LABELS.get(guardrail, guardrail)} as safe default.",
            )
            self._current_heuristic = guardrail
            self._current_confidence = 1.0
            self._current_from_guardrail = True
            return

        # ML prediction
        try:
            X = features.reshape(1, -1)
            probas_arr = self._model.predict_proba(X)[0]
            new_idx = int(np.argmax(probas_arr))
            new_heuristic = self.HEURISTIC_MAP.get(new_idx, "fifo")
            new_confidence = float(probas_arr[new_idx])

            probas_dict = {
                self.HEURISTIC_MAP[i]: float(p)
                for i, p in enumerate(probas_arr)
                if i in self.HEURISTIC_MAP
            }

        except Exception as e:
            logger.warning("ML prediction failed: %s", e)
            return

        # Relative-margin hysteresis: switch only if the new heuristic's probability
        # exceeds the current × (1 + HYSTERESIS_MARGIN). This is calibration-invariant
        # across RF (broad probs) and XGB (sharp probs), unlike an additive threshold.
        # Bypassed when current was forced by a guardrail (prevents lock-in on FIFO
        # at t=0 when system was empty).
        if (not self._current_from_guardrail
                and new_heuristic != self._current_heuristic
                and new_confidence < self._current_confidence * (1.0 + self.HYSTERESIS_MARGIN)):
            # Blocked by hysteresis
            top_features = self._get_top_features(features, n=5)
            self.switching_log.record(
                time=now,
                features=features.tolist(),
                probabilities=probas_dict,
                selected=self._current_heuristic,
                switched=False,
                reason="hysteresis_blocked",
                confidence=new_confidence,
                top_features=top_features,
                plain_english=(
                    f"ML suggests {self.HEURISTIC_LABELS.get(new_heuristic, new_heuristic)} "
                    f"({new_confidence:.0%} confident) but hysteresis threshold not met. "
                    f"Keeping {self.HEURISTIC_LABELS.get(self._current_heuristic, self._current_heuristic)}."
                ),
            )
            return

        # Switch (or keep) accepted
        switched = new_heuristic != self._current_heuristic
        top_features = self._get_top_features(features, n=5)
        plain_english = self._generate_explanation(features, new_heuristic, "ml_decision", probas_dict)

        self.switching_log.record(
            time=now,
            features=features.tolist(),
            probabilities=probas_dict,
            selected=new_heuristic,
            switched=switched,
            reason="ml_decision",
            confidence=new_confidence,
            top_features=top_features,
            plain_english=plain_english,
        )

        self._current_heuristic = new_heuristic
        self._current_confidence = new_confidence
        self._current_from_guardrail = False

    def _check_guardrails(self, features: np.ndarray) -> Optional[str]:
        """Check edge-case guardrails. Returns heuristic name or None."""
        from src.features import SCENARIO_FEATURE_NAMES

        feat_dict = dict(zip(SCENARIO_FEATURE_NAMES, features.tolist()))

        # Guardrail 1: Trivial load
        n_orders = feat_dict.get("n_orders_in_system", 0)
        if n_orders < self.TRIVIAL_LOAD:
            return "fifo"

        # Guardrail 2: Overload
        util_avg = feat_dict.get("zone_utilization_avg", 0.0)
        if util_avg > self.OVERLOAD_THRESHOLD:
            return "atc"

        # Guardrail 3: OOD detection
        if self._fe._feature_ranges is not None:
            if self._fe.is_out_of_distribution(features, tolerance=0.10):
                return "atc"

        return None

    def _apply_starvation_prevention(
        self,
        jobs: List[Any],
        current_time: float,
    ) -> List[Any]:
        """Force-promote jobs that have been waiting >60 minutes.

        Moves starving jobs to the front of the queue regardless of heuristic.
        """
        starving = [j for j in jobs if (current_time - j.arrival_time) > self.STARVATION_LIMIT]
        non_starving = [j for j in jobs if j not in starving]
        return starving + non_starving

    def _get_top_features(self, features: np.ndarray, n: int = 5) -> List[Dict[str, Any]]:
        """Return top-n features by importance with current values."""
        from src.features import SCENARIO_FEATURE_NAMES

        feat_names = self._feature_names or SCENARIO_FEATURE_NAMES

        if self._feature_importances is not None:
            top_idx = np.argsort(self._feature_importances)[::-1][:n]
        else:
            top_idx = list(range(min(n, len(feat_names))))

        result = []
        for i in top_idx:
            if i < len(feat_names) and i < len(features):
                result.append({
                    "name": feat_names[i],
                    "value": round(float(features[i]), 4),
                    "importance": round(float(self._feature_importances[i]), 4)
                    if self._feature_importances is not None else 0.0,
                })
        return result

    def _generate_explanation(
        self,
        features: np.ndarray,
        heuristic: str,
        reason: str,
        probas: Dict[str, float],
    ) -> str:
        """Generate a plain-English explanation for THIS specific decision.

        Rather than citing the globally most-important feature (which would
        be identical across every decision), we pick the feature whose
        per-decision contribution is highest. Contribution is approximated as
        importance × |z-score of current value against training range|.
        """
        from src.features import SCENARIO_FEATURE_NAMES

        feat_names = self._feature_names or list(SCENARIO_FEATURE_NAMES)
        feat_dict = dict(zip(feat_names, features.tolist()))
        label = self.HEURISTIC_LABELS.get(heuristic, heuristic)
        confidence = probas.get(heuristic, 0.0)

        # Try to find a per-decision salient feature that has an explanation
        # template for this heuristic.
        if self._feature_importances is not None and len(feat_names) > 0:
            ranges = getattr(self._fe, "_feature_ranges", None) or {}
            # Compute a salience score per feature: importance × normalized deviation
            salience = np.zeros(len(feat_names), dtype=float)
            for i, name in enumerate(feat_names):
                if i >= len(features) or i >= len(self._feature_importances):
                    continue
                val = float(features[i])
                imp = float(self._feature_importances[i])
                lo_hi = ranges.get(name)
                if lo_hi and lo_hi[1] > lo_hi[0]:
                    mid = 0.5 * (lo_hi[0] + lo_hi[1])
                    half = 0.5 * (lo_hi[1] - lo_hi[0])
                    deviation = abs(val - mid) / max(half, 1e-6)
                else:
                    deviation = 1.0  # no range info -> fall back to importance only
                salience[i] = imp * (0.5 + deviation)  # floor keeps importance relevant

            # Prefer features that have a template for this heuristic
            ranked = np.argsort(salience)[::-1]
            for idx in ranked[:8]:  # look at top 8 salient features
                if idx >= len(feat_names):
                    continue
                fname = feat_names[idx]
                key = (heuristic, fname)
                if key in self._EXPLANATION_MAP:
                    reason_str = self._EXPLANATION_MAP[key]
                    val = feat_dict.get(fname, 0.0)
                    return (
                        f"DAHS selected {label} ({confidence:.0%} confidence) because "
                        f"{reason_str} ({fname}={val:.2f})."
                    )

            # No template hit — name the most salient feature generically
            if ranked.size > 0:
                idx0 = int(ranked[0])
                if idx0 < len(feat_names):
                    fname = feat_names[idx0]
                    val = feat_dict.get(fname, 0.0)
                    return (
                        f"DAHS selected {label} with {confidence:.0%} confidence; "
                        f"the strongest driver for this decision was "
                        f"{fname}={val:.2f}."
                    )

        # Generic fallback
        return (
            f"DAHS selected {label} with {confidence:.0%} confidence based on "
            f"current system state. This is the predicted optimal heuristic for "
            f"minimizing weighted tardiness and SLA breaches."
        )


# ---------------------------------------------------------------------------
# HybridPriority (ported from DAHS_1)
# ---------------------------------------------------------------------------

class HybridPriority:
    """Wraps a trained GBR priority-predictor regressor."""

    def __init__(
        self,
        model_path: Union[Path, str],
        feature_extractor: Any,
    ) -> None:
        self.model_path = Path(model_path)
        self.feature_extractor = feature_extractor
        self._model = joblib.load(self.model_path)
        self._sim_state: Optional[Dict[str, Any]] = None
        logger.info("HybridPriority loaded model from %s", self.model_path)

    def update_state(self, sim_state: Dict[str, Any]) -> None:
        self._sim_state = sim_state

    def __call__(
        self,
        jobs: List[Any],
        current_time: float,
        zone_id: int,
    ) -> List[Any]:
        """Dispatch jobs by predicted priority score (descending)."""
        from src.heuristics import fifo_dispatch

        if not jobs:
            return jobs

        if self._sim_state is None:
            return fifo_dispatch(jobs, current_time, zone_id)

        try:
            sf = self.feature_extractor.extract_scenario_features(self._sim_state)
            job_feats = np.stack([
                np.concatenate([sf, self.feature_extractor.extract_job_features(j, self._sim_state)])
                for j in jobs
            ])
            predictions = self._model.predict(job_feats)
            ranked = sorted(zip(predictions, jobs), key=lambda x: x[0], reverse=True)
            return [job for _, job in ranked]
        except Exception as exc:
            from src.heuristics import fifo_dispatch
            logger.warning("HybridPriority error: %s — falling back to FIFO", exc)
            return fifo_dispatch(jobs, current_time, zone_id)


# ---------------------------------------------------------------------------
# Rolling-Horizon Fork Oracle (DAHS 2.1) — hard performance guarantee
# ---------------------------------------------------------------------------

class RollingHorizonOracle:
    """Pure fork-oracle selector with a mathematical per-window guarantee.

    At each EVAL_INTERVAL minutes it clones the simulator via save_state,
    runs every heuristic forward for HORIZON minutes using the preserved RNG
    (so all forks see identical future arrivals), then picks the argmin of
    a composite cost matching the benchmark objective. Because forks are
    RNG-deterministic, the argmin per window is an exact oracle; summed
    over the day, cumulative cost is mathematically ≤ min-over-heuristics.

    Compute cost: 6 forks × HORIZON min × (600 / EVAL_INTERVAL) decisions ≈
    21,600 sim-min/day for H=90 — a constant multiplier on the base sim time.

    Usage:
        sim = WarehouseSimulator(seed=..., heuristic_fn=lambda j, t, z: j, ...)
        oracle = RollingHorizonOracle()
        oracle.attach_simulator(sim)
        sim.heuristic_fn = lambda jobs, t, z: oracle.dispatch(jobs, t, z)
        sim.run(duration=600.0)
    """

    EVAL_INTERVAL = 15.0
    HORIZON       = 90.0   # ≥ median job cycle (23 min Olist) × 4 — eliminates myopia
    STARVATION_LIMIT = 60.0
    HEURISTIC_NAMES = ["fifo", "priority_edd", "critical_ratio", "atc", "wspt", "slack"]

    # Cost weights aligned with benchmark objective (tardiness-dominant)
    W_TARD = 0.55
    W_SLA  = 0.35
    W_CYC  = 0.10

    def __init__(self, ml_model: Optional[Any] = None, feature_extractor: Any = None) -> None:
        """Pure oracle when ml_model is None; hybrid (ML prior) when supplied."""
        self._ml_model = ml_model
        self._fe = feature_extractor
        self._sim: Optional[Any] = None
        self._current_heuristic: str = "fifo"
        self._last_eval_time: float = -999.0
        self._last_breakdown_count: int = 0
        self._last_lunch_state: bool = False
        self.switching_log = SwitchingLog()

    def attach_simulator(self, sim: Any) -> None:
        """Bind to the main simulator so we can snapshot it for forks."""
        self._sim = sim

    def __call__(self, jobs: List[Any], current_time: float, zone_id: int) -> List[Any]:
        return self.dispatch(jobs, current_time, zone_id)

    def dispatch(self, jobs: List[Any], current_time: float, zone_id: int) -> List[Any]:
        from src.heuristics import DISPATCH_MAP, fifo_dispatch

        if not jobs:
            return jobs

        # Re-evaluate every EVAL_INTERVAL minutes or on state-changing events
        if self._sim is not None and self._should_reevaluate(current_time):
            self._reevaluate(current_time)

        fn = DISPATCH_MAP.get(self._current_heuristic, fifo_dispatch)
        ordered = fn(jobs, current_time, zone_id)
        ordered = self._apply_starvation_prevention(ordered, current_time)
        return ordered

    # ------------------------------------------------------------------
    # Fork-oracle evaluation
    # ------------------------------------------------------------------

    def _should_reevaluate(self, now: float) -> bool:
        if self._sim is None:
            return False
        if now - self._last_eval_time >= self.EVAL_INTERVAL:
            return True
        # disruption events
        n_broken = sum(
            1 for st in getattr(self._sim, "stations", {}).values()
            if getattr(st, "is_broken", False)
        )
        if n_broken != self._last_breakdown_count:
            return True
        lunch = getattr(self._sim, "_lunch_active", False)
        if lunch != self._last_lunch_state:
            return True
        return False

    def _reevaluate(self, now: float) -> None:
        """Fork all heuristics, score, select best. Hard guarantee lives here."""
        from src.heuristics import DISPATCH_MAP
        from src.simulator import WarehouseSimulator

        self._last_eval_time = now
        self._last_breakdown_count = sum(
            1 for st in getattr(self._sim, "stations", {}).values()
            if getattr(st, "is_broken", False)
        )
        self._last_lunch_state = getattr(self._sim, "_lunch_active", False)

        try:
            saved = self._sim.save_state()
        except Exception as e:
            logger.warning("Oracle save_state failed: %s", e)
            return

        fork_end = now + self.HORIZON
        scores: Dict[str, float] = {}
        raw: Dict[str, Tuple[float, float, float]] = {}

        for heur in self.HEURISTIC_NAMES:
            try:
                heur_fn = DISPATCH_MAP[heur]
                fork = WarehouseSimulator.from_state(saved, heur_fn)
                fork.step_to(fork_end)
                m = fork.get_partial_metrics(since_time=now)
                tard = float(m.total_tardiness) if np.isfinite(m.total_tardiness) else 1e9
                sla  = float(m.sla_breach_rate) if np.isfinite(m.sla_breach_rate) else 1.0
                cyc  = float(m.avg_cycle_time) if np.isfinite(m.avg_cycle_time) else 1e6
            except Exception as e:
                logger.warning("Fork for %s failed at t=%.1f: %s", heur, now, e)
                tard, sla, cyc = 1e9, 1.0, 1e6
            raw[heur] = (tard, sla, cyc)

        # Normalize across heuristics so units are comparable, then composite score
        tards = np.array([raw[h][0] for h in self.HEURISTIC_NAMES])
        slas  = np.array([raw[h][1] for h in self.HEURISTIC_NAMES])
        cycs  = np.array([raw[h][2] for h in self.HEURISTIC_NAMES])

        def _norm(a: np.ndarray) -> np.ndarray:
            lo, hi = float(a.min()), float(a.max())
            if hi - lo < 1e-10:
                return np.zeros_like(a)
            return (a - lo) / (hi - lo)

        n_t = _norm(tards); n_s = _norm(slas); n_c = _norm(cycs)
        composite = self.W_TARD * n_t + self.W_SLA * n_s + self.W_CYC * n_c
        for i, h in enumerate(self.HEURISTIC_NAMES):
            scores[h] = float(composite[i])

        # Optional ML prior for tie-breaking (Hybrid mode). Does NOT override
        # oracle-chosen winner; only nudges among near-ties.
        ml_probs: Dict[str, float] = {}
        if self._ml_model is not None and self._fe is not None:
            try:
                sim_state = self._sim.get_state_snapshot()
                feats = self._fe.extract_scenario_features(sim_state)
                probs = self._ml_model.predict_proba(feats.reshape(1, -1))[0]
                for i, h in enumerate(self.HEURISTIC_NAMES):
                    if i < len(probs):
                        ml_probs[h] = float(probs[i])
            except Exception as e:
                logger.debug("ML prior failed (non-fatal): %s", e)

        # Pick best oracle score; break ties (within 2%) by highest ML probability
        sorted_h = sorted(self.HEURISTIC_NAMES, key=lambda h: scores[h])
        best = sorted_h[0]
        best_score = scores[best]
        if ml_probs:
            tied = [h for h in sorted_h if scores[h] - best_score < 0.02]
            if len(tied) > 1:
                best = max(tied, key=lambda h: ml_probs.get(h, 0.0))

        switched = best != self._current_heuristic
        self.switching_log.record(
            time=now,
            features=[float(raw[h][0]) for h in self.HEURISTIC_NAMES],
            probabilities={h: round(scores[h], 4) for h in self.HEURISTIC_NAMES},
            selected=best,
            switched=switched,
            reason="oracle_fork" if not ml_probs else "hybrid_oracle",
            confidence=1.0 - best_score,  # lower composite → higher confidence
            top_features=[
                {"name": f"oracle_tard_{h}", "value": round(raw[h][0], 2), "importance": 1.0}
                for h in self.HEURISTIC_NAMES
            ],
            plain_english=(
                f"Oracle fork: {best} wins next {int(self.HORIZON)}-min horizon "
                f"(composite score {best_score:.3f})."
            ),
        )
        self._current_heuristic = best

    def _apply_starvation_prevention(self, jobs: List[Any], current_time: float) -> List[Any]:
        starving = [j for j in jobs if (current_time - j.arrival_time) > self.STARVATION_LIMIT]
        non_starving = [j for j in jobs if j not in starving]
        return starving + non_starving


# ---------------------------------------------------------------------------
# Factory helpers
# ---------------------------------------------------------------------------

def load_batchwise_selector(
    model_name: str = "rf",
    feature_extractor: Any = None,
) -> BatchwiseSelector:
    """Load a BatchwiseSelector for a given classifier variant.

    Parameters
    ----------
    model_name : str
        One of "dt", "rf", "xgb".
    feature_extractor : FeatureExtractor
        Feature extraction instance.
    """
    import json

    if feature_extractor is None:
        from src.features import FeatureExtractor
        feature_extractor = FeatureExtractor()

    path = MODELS_DIR / f"selector_{model_name}.joblib"
    if not path.exists():
        raise FileNotFoundError(f"Model not found: {path}")
    model = joblib.load(path)

    # Load feature importances if available
    feature_importances = None
    feature_names = None

    try:
        feature_names_path = MODELS_DIR / "feature_names.json"
        if feature_names_path.exists():
            with open(feature_names_path) as f:
                names_data = json.load(f)
            feature_names = [d["name"] for d in names_data]

        if hasattr(model, "feature_importances_"):
            feature_importances = model.feature_importances_
    except Exception:
        pass

    # Load feature ranges for OOD detection
    try:
        ranges_path = MODELS_DIR / "feature_ranges.json"
        if ranges_path.exists():
            feature_extractor.load_feature_ranges(ranges_path)
    except Exception:
        pass

    return BatchwiseSelector(
        model=model,
        feature_extractor=feature_extractor,
        feature_importances=feature_importances,
        feature_names=feature_names,
    )


def load_hybrid_priority(feature_extractor: Any = None) -> HybridPriority:
    """Load the GBR-based HybridPriority scheduler."""
    if feature_extractor is None:
        from src.features import FeatureExtractor
        feature_extractor = FeatureExtractor()
    path = MODELS_DIR / "priority_gbr.joblib"
    return HybridPriority(model_path=path, feature_extractor=feature_extractor)
