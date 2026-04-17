"""
server.py — DAHS_2 FastAPI Backend

Extended from DAHS_1 with:
  - BatchwiseSelector (15-min interval, guardrails, hysteresis)
  - Extended evaluation log in WebSocket payload
  - New REST endpoints: /api/feature-names, /api/heuristic-info, /api/model-info,
    /api/dt-structure, /api/results

Start with: python start.py
Visit:      http://localhost:8000
"""
from __future__ import annotations

import asyncio
import json
import logging
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from typing import Any, Dict, List, Optional

import joblib
import numpy as np
from fastapi import FastAPI, WebSocket, WebSocketDisconnect
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles
from fastapi.responses import FileResponse

from src.simulator import WarehouseSimulator
from src.features import FeatureExtractor, SCENARIO_FEATURE_NAMES, FEATURE_DESCRIPTIONS
from src.heuristics import (
    fifo_dispatch, priority_edd_dispatch, critical_ratio_dispatch,
    atc_dispatch, wspt_dispatch, slack_dispatch,
)

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
logger = logging.getLogger(__name__)

MODELS_DIR    = Path("models")
RESULTS_DIR   = Path("results")
SNAP_INTERVAL = 2.0
SIM_DURATION  = 600.0
EXECUTOR      = ThreadPoolExecutor(max_workers=4)

# ---------------------------------------------------------------------------
# App
# ---------------------------------------------------------------------------
app = FastAPI(title="DAHS_2 Simulation Backend", version="2.0")
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_methods=["*"],
    allow_headers=["*"],
)

_models: Dict[str, Any] = {}

@app.on_event("startup")
async def load_models() -> None:
    logger.info("Loading ML models…")
    for name in ("dt", "rf", "xgb"):
        p = MODELS_DIR / f"selector_{name}.joblib"
        if p.exists():
            _models[name] = joblib.load(p)
            logger.info("  selector_%s loaded", name)
    p = MODELS_DIR / "priority_gbr.joblib"
    if p.exists():
        _models["gbr"] = joblib.load(p)
        logger.info("  priority_gbr loaded")
    logger.info("Ready. Models: %s", list(_models.keys()))

@app.get("/health")
def health() -> Dict[str, Any]:
    return {"status": "ok", "models": list(_models.keys()), "version": "2.0"}

# ---------------------------------------------------------------------------
# REST endpoints
# ---------------------------------------------------------------------------

@app.get("/api/presets")
def get_presets() -> List[Dict[str, Any]]:
    from src.presets import get_all_presets
    return [
        {
            "name": p.name,
            "description": p.description,
            "favored_heuristic": p.favored_heuristic,
            "seed": p.seed,
            "why_it_favors": p.why_it_favors,
            "params": {
                "baseArrivalRate": p.base_arrival_rate,
                "breakdownProb": p.breakdown_prob,
                "batchArrivalSize": p.batch_arrival_size,
                "lunchPenalty": p.lunch_penalty_factor - 1.0,
            },
        }
        for p in get_all_presets()
    ]


@app.get("/api/feature-names")
def get_feature_names() -> List[Dict[str, Any]]:
    """Return feature names with descriptions and categories."""
    # Try loading from JSON artifact first
    json_path = MODELS_DIR / "feature_names.json"
    if json_path.exists():
        with open(json_path) as f:
            return json.load(f)

    # Fallback: generate from source
    return [
        {
            "name": name,
            "description": FEATURE_DESCRIPTIONS.get(name, name),
            "category": (
                "disruption" if name in ("disruption_intensity", "queue_imbalance", "job_mix_entropy", "time_pressure_ratio")
                else "system"
            ),
            "index": i,
        }
        for i, name in enumerate(SCENARIO_FEATURE_NAMES)
    ]


@app.get("/api/heuristic-info")
def get_heuristic_info() -> List[Dict[str, Any]]:
    """Return educational info about each heuristic."""
    return [
        {
            "name": "fifo",
            "label": "FIFO",
            "formula": "Sort by arrival_time ascending",
            "whenBest": "Uniform jobs, no urgency differentiation, light load",
            "whenWorst": "Mixed priorities, tight deadlines, heavy breakdowns",
            "color": "#94A3B8",
        },
        {
            "name": "priority_edd",
            "label": "Priority-EDD",
            "formula": "Sort by (-priority_class, due_date)",
            "whenBest": "High express ratio, tight deadlines, clear priority tiers",
            "whenWorst": "Uniform jobs, low time pressure",
            "color": "#64748B",
        },
        {
            "name": "critical_ratio",
            "label": "Critical Ratio",
            "formula": "CR = (due_date - now) / remaining_proc_time",
            "whenBest": "Station breakdowns causing dynamic time pressure shifts",
            "whenWorst": "Uniform jobs, stable conditions",
            "color": "#6B7280",
        },
        {
            "name": "atc",
            "label": "ATC",
            "formula": "(w/p) × exp(-max(0, d-p-t) / K×p_avg), K=2.0",
            "whenBest": "Heavy load, high-weight jobs, tight deadlines, congestion",
            "whenWorst": "Light load, uniform weights",
            "color": "#3B82F6",
        },
        {
            "name": "wspt",
            "label": "WSPT",
            "formula": "Sort by w/p descending",
            "whenBest": "Many short jobs, loose deadlines, throughput focus",
            "whenWorst": "Extreme deadline pressure, must avoid tardiness at all costs",
            "color": "#2563EB",
        },
        {
            "name": "slack",
            "label": "Slack",
            "formula": "slack = due_date - now - remaining_proc_time",
            "whenBest": "Recovery mode, very tight deadlines, backlog clearance",
            "whenWorst": "Loose deadlines, steady flow",
            "color": "#78716C",
        },
    ]


@app.get("/api/model-info")
def get_model_info() -> Dict[str, Any]:
    """Return model metadata."""
    result = {"models": {}, "hasModels": len(_models) > 0}
    for name, model in _models.items():
        info: Dict[str, Any] = {"type": type(model).__name__}
        if hasattr(model, "feature_importances_"):
            importances = model.feature_importances_.tolist()
            feat_names = SCENARIO_FEATURE_NAMES
            top_idx = sorted(range(len(importances)), key=lambda i: importances[i], reverse=True)[:10]
            info["featureImportances"] = [
                {"name": feat_names[i] if i < len(feat_names) else f"f{i}",
                 "importance": round(importances[i], 4)}
                for i in top_idx
            ]
        result["models"][name] = info
    return result


@app.get("/api/dt-structure")
def get_dt_structure() -> Dict[str, Any]:
    """Return decision tree structure for frontend glass-box visualization."""
    json_path = MODELS_DIR / "dt_structure.json"
    if json_path.exists():
        with open(json_path) as f:
            return json.load(f)
    return {"nodes": [], "error": "dt_structure.json not found. Run training pipeline first."}


@app.get("/api/references")
def get_references() -> Dict[str, Any]:
    """Return the full academic bibliography used in DAHS_2."""
    from src.references import REFERENCES
    return {"references": REFERENCES, "count": len(REFERENCES)}


@app.get("/api/results")
def get_results() -> Dict[str, Any]:
    """Return pre-computed benchmark results for Results page."""
    result = {}

    summary_path = RESULTS_DIR / "benchmark_summary.json"
    if summary_path.exists():
        with open(summary_path) as f:
            result["summary"] = json.load(f)

    stats_path = RESULTS_DIR / "statistical_tests.json"
    if stats_path.exists():
        with open(stats_path) as f:
            result["stats"] = json.load(f)

    switching_path = RESULTS_DIR / "switching_analysis.json"
    if switching_path.exists():
        with open(switching_path) as f:
            result["switching"] = json.load(f)

    if not result:
        return {"message": "No benchmark results found. Run the pipeline first."}

    return result


# ---------------------------------------------------------------------------
# Simulation session classes
# ---------------------------------------------------------------------------

_HEURISTIC_MAP = {
    0: "fifo", 1: "priority_edd", 2: "critical_ratio",
    3: "atc",  4: "wspt",         5: "slack",
}
_DISPATCH_FNS = {
    "fifo": fifo_dispatch, "priority_edd": priority_edd_dispatch,
    "critical_ratio": critical_ratio_dispatch, "atc": atc_dispatch,
    "wspt": wspt_dispatch, "slack": slack_dispatch,
}


class _BatchwiseSessionSelector:
    """Per-simulation BatchwiseSelector using pre-loaded classifier."""

    EVAL_INTERVAL = 15.0
    HYSTERESIS_THRESHOLD = 0.15
    TRIVIAL_LOAD = 5
    OVERLOAD_THRESHOLD = 0.92
    STARVATION_LIMIT = 60.0

    def __init__(self, model: Any, feat_ext: FeatureExtractor) -> None:
        self._model = model
        self._feat_ext = feat_ext
        self._state: Optional[Dict[str, Any]] = None
        self._current_heuristic = "fifo"
        self._current_confidence = 0.0
        self._last_eval_time = -999.0
        self._last_n_broken = 0
        self._last_lunch = False
        self._eval_log: List[Dict[str, Any]] = []
        self._switch_count = 0
        self._hysteresis_blocked = 0
        self._guardrail_activations = 0

    def update(self, state: Dict[str, Any]) -> None:
        self._state = state

    def __call__(self, jobs: list, t: float, zone_id: int) -> list:
        if not jobs:
            return jobs
        if self._state is not None and self._should_reevaluate(t):
            self._reevaluate(t)
        fn = _DISPATCH_FNS.get(self._current_heuristic, fifo_dispatch)
        ordered = fn(jobs, t, zone_id)
        # Starvation prevention
        starving = [j for j in ordered if (t - j.arrival_time) > self.STARVATION_LIMIT]
        non_starving = [j for j in ordered if j not in starving]
        return starving + non_starving

    def _should_reevaluate(self, now: float) -> bool:
        if now - self._last_eval_time >= self.EVAL_INTERVAL:
            return True
        if self._state:
            n_broken = self._state.get("n_broken_stations", 0)
            lunch = self._state.get("lunch_active", False)
            if n_broken != self._last_n_broken or lunch != self._last_lunch:
                return True
        return False

    def _reevaluate(self, now: float) -> None:
        if self._state is None:
            return
        self._last_eval_time = now
        self._last_n_broken = self._state.get("n_broken_stations", 0)
        self._last_lunch = self._state.get("lunch_active", False)

        try:
            features = self._feat_ext.extract_scenario_features(self._state)
        except Exception:
            return

        # Guardrails
        n_orders = features[0]  # F1: n_orders_in_system
        util_avg = features[4]  # F5: zone_utilization_avg

        if n_orders < self.TRIVIAL_LOAD:
            if self._current_heuristic != "fifo":
                self._switch_count += 1
            self._current_heuristic = "fifo"
            self._record_eval(now, features, "fifo", 1.0, "guardrail_trivial")
            return
        if util_avg > self.OVERLOAD_THRESHOLD:
            if self._current_heuristic != "atc":
                self._switch_count += 1
            self._current_heuristic = "atc"
            self._record_eval(now, features, "atc", 1.0, "guardrail_overload")
            return

        # ML prediction
        try:
            X = features.reshape(1, -1)
            probas = self._model.predict_proba(X)[0]
            new_idx = int(np.argmax(probas))
            new_h = _HEURISTIC_MAP.get(new_idx, "fifo")
            new_conf = float(probas[new_idx])
        except Exception:
            return

        # Hysteresis
        if (new_h != self._current_heuristic and
                new_conf < self._current_confidence + self.HYSTERESIS_THRESHOLD):
            self._hysteresis_blocked += 1
            self._record_eval(now, features, self._current_heuristic, new_conf, "hysteresis_blocked")
            return

        switched = new_h != self._current_heuristic
        if switched:
            self._switch_count += 1
        self._current_heuristic = new_h
        self._current_confidence = new_conf
        self._record_eval(now, features, new_h, new_conf, "ml_decision")

    def _record_eval(self, time: float, features: np.ndarray, heuristic: str, confidence: float, reason: str) -> None:
        probas_dict: Dict[str, float] = {}
        try:
            X = features.reshape(1, -1)
            pa = self._model.predict_proba(X)[0]
            probas_dict = {_HEURISTIC_MAP.get(i, f"h{i}"): round(float(p), 4) for i, p in enumerate(pa)}
        except Exception:
            probas_dict = {heuristic: round(confidence, 4)}

        # Top features by importance
        top_features = []
        if hasattr(self._model, "feature_importances_"):
            importances = self._model.feature_importances_
            top_idx = np.argsort(importances)[::-1][:5]
            for i in top_idx:
                if i < len(features) and i < len(SCENARIO_FEATURE_NAMES):
                    top_features.append({
                        "name": SCENARIO_FEATURE_NAMES[i],
                        "value": round(float(features[i]), 4),
                        "importance": round(float(importances[i]), 4),
                    })

        plain = self._generate_plain(heuristic, reason, confidence, features)

        switched = len(self._eval_log) > 0 and self._eval_log[-1]["heuristic"] != heuristic
        if reason.startswith("guardrail"):
            self._guardrail_activations += 1

        entry = {
            "time": round(time, 2),
            "heuristic": heuristic,
            "switched": switched,
            "reason": reason,
            "confidence": round(confidence, 4),
            "probabilities": probas_dict,
            "topFeatures": top_features,
            "guardrailActive": reason if reason.startswith("guardrail") else None,
            "plainEnglish": plain,
        }
        self._eval_log.append(entry)

    def _generate_plain(self, heuristic: str, reason: str, confidence: float, features: np.ndarray) -> str:
        labels = {"fifo": "FIFO", "priority_edd": "Priority-EDD",
                  "critical_ratio": "Critical-Ratio", "atc": "ATC",
                  "wspt": "WSPT", "slack": "Slack"}
        label = labels.get(heuristic, heuristic)
        feat_dict = dict(zip(SCENARIO_FEATURE_NAMES, features.tolist()))

        if reason == "guardrail_trivial":
            return f"Guardrail: Only {feat_dict.get('n_orders_in_system', 0):.0f} jobs in system — using FIFO (skip ML below threshold)."
        if reason == "guardrail_overload":
            return f"Guardrail: System overloaded (util={feat_dict.get('zone_utilization_avg', 0):.0%}) — locked to ATC."
        if reason == "hysteresis_blocked":
            return f"ML suggests switch but confidence gap ({confidence:.0%}) below 15% threshold — keeping current heuristic."

        # ML decision — pick top feature
        n_orders = feat_dict.get("n_orders_in_system", 0)
        time_pressure = feat_dict.get("time_pressure_ratio", 0)
        util = feat_dict.get("zone_utilization_avg", 0)
        n_broken = feat_dict.get("n_broken_stations", 0)

        if heuristic == "atc" and time_pressure > 0.4:
            return f"DAHS selected {label} ({confidence:.0%} confidence) because {time_pressure:.0%} of jobs are nearing deadlines."
        if heuristic == "critical_ratio" and n_broken > 0:
            return f"DAHS selected {label} ({confidence:.0%} confidence) because {n_broken:.0f} station(s) are broken, causing dynamic time pressure."
        if heuristic == "fifo" and n_orders < 20:
            return f"DAHS selected {label} ({confidence:.0%} confidence) — light load with only {n_orders:.0f} orders, simple ordering is optimal."
        return f"DAHS selected {label} with {confidence:.0%} confidence based on current warehouse state (util={util:.0%}, {n_orders:.0f} orders)."

    def get_summary(self) -> Dict[str, Any]:
        log = self._eval_log
        if not log:
            return {"totalEvaluations": 0, "switchCount": 0}
        total = len(log)
        dist: Dict[str, int] = {}
        for e in log:
            h = e["heuristic"]
            dist[h] = dist.get(h, 0) + 1
        return {
            "totalEvaluations": total,
            "switchCount": self._switch_count,
            "switchingRate": round(self._switch_count / max(total - 1, 1), 4),
            "hysteresisBlocked": self._hysteresis_blocked,
            "guardrailActivations": self._guardrail_activations,
            "distribution": {k: round(v / total, 4) for k, v in dist.items()},
            "dominantHeuristic": max(dist, key=dist.get) if dist else "none",
        }


class _PrioritySession:
    """Per-simulation GBR priority predictor."""

    def __init__(self, model: Any, feat_ext: FeatureExtractor) -> None:
        self._model = model
        self._feat_ext = feat_ext
        self._state: Optional[Dict[str, Any]] = None

    def update(self, state: Dict[str, Any]) -> None:
        self._state = state

    def __call__(self, jobs: list, t: float, zone_id: int) -> list:
        if not jobs or self._state is None:
            return fifo_dispatch(jobs, t, zone_id)
        try:
            sf = self._feat_ext.extract_scenario_features(self._state)
            feats = np.stack([
                np.concatenate([sf, self._feat_ext.extract_job_features(j, self._state)])
                for j in jobs
            ])
            scores = self._model.predict(feats)
            return [j for _, j in sorted(zip(scores, jobs), key=lambda x: x[0], reverse=True)]
        except Exception:
            return fifo_dispatch(jobs, t, zone_id)


class _RuleBasedPredictor:
    """
    Fallback heuristic selector used when no trained ML model is available.
    Mimics the sklearn predict_proba interface so it works inside
    _BatchwiseSessionSelector unchanged — enabling the evaluation log,
    guardrails, and plain-English explanations even before training.

    Rules (mirroring the guardrails in _BatchwiseSessionSelector):
      F1  n_orders_in_system  → trivial load  → FIFO
      F5  zone_utilization_avg → overload      → ATC
      F19 time_pressure_ratio  → high pressure → ATC
      F9  n_broken_stations    → breakdowns    → Critical Ratio
      F5  util_avg moderate    → busy          → WSPT
      Otherwise                                → Slack
    """

    # Expose fake importances so the top-features panel in the UI has something
    # to display (highlights the 3 most diagnostic features).
    feature_importances_ = np.array([
        0.18,  # F1  n_orders_in_system
        0.05, 0.04, 0.05,
        0.14,  # F5  zone_utilization_avg
        0.03, 0.03, 0.03,
        0.10,  # F9  n_broken_stations
        0.03, 0.03, 0.03, 0.03, 0.03, 0.03, 0.03, 0.03, 0.03,
        0.12,  # F19 time_pressure_ratio
        0.05,  # F20 disruption_intensity
        0.03, 0.03,  # F21 F22
    ], dtype=float)

    def predict_proba(self, X: np.ndarray) -> np.ndarray:
        x = X[0]
        n_orders  = float(x[0])   if len(x) > 0  else 0.0   # F1
        util_avg  = float(x[4])   if len(x) > 4  else 0.0   # F5
        n_broken  = float(x[8])   if len(x) > 8  else 0.0   # F9
        t_press   = float(x[18])  if len(x) > 18 else 0.0   # F19
        # idx: 0=fifo 1=priority_edd 2=critical_ratio 3=atc 4=wspt 5=slack
        # Default mild prior with WSPT favored (strong general-purpose rule
        # for weighted tardiness per Smith 1956 / Vepsalainen & Morton 1987).
        p = np.array([0.04, 0.04, 0.06, 0.10, 0.70, 0.06], dtype=float)
        if n_orders < 8:
            # Trivial load — FIFO is optimal (no benefit from complex ordering)
            p = np.array([0.80, 0.04, 0.04, 0.04, 0.04, 0.04], dtype=float)
        elif util_avg > 0.85 and t_press > 0.35:
            # Overloaded AND deadline-pressured → ATC (Vepsalainen & Morton)
            p = np.array([0.03, 0.05, 0.08, 0.70, 0.10, 0.04], dtype=float)
        elif n_broken >= 3 and util_avg > 0.70:
            # Multiple breakdowns on a busy system → Critical Ratio adapts dynamically
            p = np.array([0.03, 0.05, 0.65, 0.10, 0.12, 0.05], dtype=float)
        elif t_press > 0.60:
            # Many jobs near deadline → Slack-first recovery
            p = np.array([0.03, 0.08, 0.10, 0.15, 0.15, 0.49], dtype=float)
        # otherwise: default WSPT-favored distribution stays
        p /= p.sum()
        return p.reshape(1, -1)


_BASELINE_FNS: Dict[str, Any] = {
    "FIFO": fifo_dispatch,
    "EDD": priority_edd_dispatch,
    "Critical-Ratio": critical_ratio_dispatch,
    "ATC": atc_dispatch,
    "WSPT": wspt_dispatch,
    "Slack": slack_dispatch,
}


# ---------------------------------------------------------------------------
# Blocking simulation runner
# ---------------------------------------------------------------------------
def _run_pair(config: Dict[str, Any]) -> Dict[str, Any]:
    seed       = int(config.get("seed", 42))
    model_name = str(config.get("model", "xgb"))
    base_code  = str(config.get("baseCode", "FIFO"))
    params     = config.get("params", {})

    preset_name = config.get("preset")
    sim_kw: Dict[str, Any] = {}
    if preset_name:
        try:
            from src.presets import get_preset
            preset = get_preset(preset_name)
            seed = preset.seed
            sim_kw = {
                "base_arrival_rate":    preset.base_arrival_rate,
                "breakdown_prob":       preset.breakdown_prob,
                "batch_arrival_size":   preset.batch_arrival_size,
                "lunch_penalty_factor": preset.lunch_penalty_factor,
                "job_type_frequencies": preset.job_type_frequencies,
                "due_date_tightness":   preset.due_date_tightness,
                "processing_time_scale": preset.processing_time_scale,
            }
        except Exception:
            preset_name = None

    if not preset_name:
        sim_kw = {
            "base_arrival_rate":    float(params.get("baseArrivalRate", 2.5)),
            "breakdown_prob":       float(params.get("breakdownProb", 0.003)),
            "batch_arrival_size":   int(params.get("batchArrivalSize", 30)),
            "lunch_penalty_factor": 1.0 + float(params.get("lunchPenalty", 0.3)),
        }

    # Baseline
    base_fn  = _BASELINE_FNS.get(base_code, fifo_dispatch)
    base_sim = WarehouseSimulator(seed=seed, heuristic_fn=base_fn, **sim_kw)
    base_sim.init()

    # DAHS
    feat_ext = FeatureExtractor()
    dahs_sim = WarehouseSimulator(seed=seed, heuristic_fn=fifo_dispatch, **sim_kw)
    dahs_selector: Optional[_BatchwiseSessionSelector] = None

    if model_name in ("dt", "rf", "xgb") and model_name in _models:
        dahs_selector = _BatchwiseSessionSelector(_models[model_name], feat_ext)

        def dahs_dispatch(jobs, t, zone_id):
            dahs_selector.update(dahs_sim.get_state_snapshot())
            return dahs_selector(jobs, t, zone_id)

        dahs_sim.heuristic_fn = dahs_dispatch

    elif model_name == "priority" and "gbr" in _models:
        priority = _PrioritySession(_models["gbr"], feat_ext)

        def dahs_dispatch(jobs, t, zone_id):  # type: ignore[misc]
            priority.update(dahs_sim.get_state_snapshot())
            return priority(jobs, t, zone_id)

        dahs_sim.heuristic_fn = dahs_dispatch
    else:
        # No trained model — use rule-based fallback so the evaluation log,
        # guardrails and plain-English explanations are still visible.
        dahs_selector = _BatchwiseSessionSelector(_RuleBasedPredictor(), feat_ext)

        def dahs_dispatch(jobs, t, zone_id):  # type: ignore[misc]
            dahs_selector.update(dahs_sim.get_state_snapshot())
            return dahs_selector(jobs, t, zone_id)

        dahs_sim.heuristic_fn = dahs_dispatch

    dahs_sim.init()

    # Collect snapshots
    baseline_snaps: List[Dict] = []
    dahs_snaps:     List[Dict] = []

    baseline_snaps.append(base_sim.get_visual_snapshot())
    dahs_snaps.append(dahs_sim.get_visual_snapshot())

    t = SNAP_INTERVAL
    while t <= SIM_DURATION + 1e-9:
        base_sim.step_to(t)
        dahs_sim.step_to(t)
        baseline_snaps.append(base_sim.get_visual_snapshot())
        dahs_snaps.append(dahs_sim.get_visual_snapshot())
        t += SNAP_INTERVAL

    # Ensure final snapshot
    if abs(t - SNAP_INTERVAL - SIM_DURATION) > 0.5:
        base_sim.step_to(SIM_DURATION)
        dahs_sim.step_to(SIM_DURATION)
        baseline_snaps.append(base_sim.get_visual_snapshot())
        dahs_snaps.append(dahs_sim.get_visual_snapshot())

    # Evaluation log
    eval_log: List[Dict] = []
    switching_summary: Dict[str, Any] = {}

    if dahs_selector is not None:
        eval_log = dahs_selector._eval_log
        switching_summary = dahs_selector.get_summary()

    # Preset metadata
    preset_meta: Dict[str, Any] = {}
    if preset_name:
        try:
            from src.presets import get_preset as _gp
            _p = _gp(preset_name)
            preset_meta = {
                "presetName": _p.name,
                "presetFavoredHeuristic": _p.favored_heuristic,
                "presetWhyItFavors": _p.why_it_favors,
            }
        except Exception:
            pass

    return {
        "baseline":         baseline_snaps,
        "dahs":             dahs_snaps,
        "evaluationLog":    eval_log,
        "switchingSummary": switching_summary,
        **preset_meta,
    }


# ---------------------------------------------------------------------------
# WebSocket endpoint
# ---------------------------------------------------------------------------
@app.websocket("/ws/simulate")
async def simulate_ws(ws: WebSocket) -> None:
    await ws.accept()
    logger.info("WebSocket client connected")
    try:
        config = await ws.receive_json()
        logger.info("Running simulation: seed=%s model=%s base=%s",
                    config.get("seed"), config.get("model"), config.get("baseCode"))

        await ws.send_json({"type": "status", "msg": "Running simulation…"})

        loop   = asyncio.get_running_loop()
        result = await loop.run_in_executor(EXECUTOR, _run_pair, config)

        payload: Dict[str, Any] = {
            "type":             "snapshots",
            "baseline":         result["baseline"],
            "dahs":             result["dahs"],
            "total":            len(result["baseline"]),
            "evaluationLog":    result.get("evaluationLog", []),
            "switchingSummary": result.get("switchingSummary", {}),
            # Legacy compat
            "switchingLog":     result.get("evaluationLog", []),
        }

        if result.get("presetName"):
            payload["presetName"]            = result["presetName"]
            payload["presetFavoredHeuristic"] = result.get("presetFavoredHeuristic", "")
            payload["presetWhyItFavors"]      = result.get("presetWhyItFavors", "")

        await ws.send_json(payload)
        logger.info("Sent %d snapshot pairs to client", len(result["baseline"]))

    except WebSocketDisconnect:
        logger.info("Client disconnected")
    except Exception as exc:
        logger.exception("Simulation failed: %s", exc)
        try:
            await ws.send_json({"type": "error", "msg": str(exc)})
        except Exception:
            pass


# ---------------------------------------------------------------------------
# Serve the built React frontend (website/dist) — must be LAST
# ---------------------------------------------------------------------------
_DIST = Path(__file__).parent / "website" / "dist"

if _DIST.exists():
    app.mount("/assets", StaticFiles(directory=str(_DIST / "assets")), name="assets")

    @app.get("/{full_path:path}", include_in_schema=False)
    async def serve_spa(full_path: str):
        return FileResponse(str(_DIST / "index.html"))
else:
    logger.warning("website/dist not found — frontend not served. Run: cd website && npm run build")
