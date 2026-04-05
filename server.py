"""
server.py — DAHS FastAPI Backend
Serves the React website AND runs the real ML simulation via WebSocket.
Start with: python3 start.py  (or: uvicorn server:app --port 8000)
Visit:      http://localhost:8000
"""
from __future__ import annotations

import asyncio
import logging
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from typing import Any, Dict, List

import joblib
import numpy as np
from fastapi import FastAPI, WebSocket, WebSocketDisconnect
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles
from fastapi.responses import FileResponse

from src.simulator import WarehouseSimulator
from src.features import FeatureExtractor
from src.heuristics import (
    fifo_dispatch, priority_edd_dispatch, critical_ratio_dispatch,
    atc_dispatch, wspt_dispatch, slack_dispatch,
)

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
logger = logging.getLogger(__name__)

MODELS_DIR    = Path("models")
SNAP_INTERVAL = 2.0    # sim-minutes between visual snapshots
SIM_DURATION  = 600.0
EXECUTOR      = ThreadPoolExecutor(max_workers=4)

# ---------------------------------------------------------------------------
# App
# ---------------------------------------------------------------------------
app = FastAPI(title="DAHS Simulation Backend", version="1.0")
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_methods=["*"],
    allow_headers=["*"],
)

_models: Dict[str, Any] = {}

@app.on_event("startup")
async def load_models() -> None:
    logger.info("Loading ML models …")
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
    return {"status": "ok", "models": list(_models.keys())}

# ---------------------------------------------------------------------------
# Inline selector that uses a pre-loaded model (avoids joblib.load per request)
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

class _SessionSelector:
    """Per-simulation ML selector using a pre-loaded classifier."""
    def __init__(self, model: Any, feat_ext: FeatureExtractor) -> None:
        self._model    = model
        self._feat_ext = feat_ext
        self._state: Dict[str, Any] | None = None

    def update(self, state: Dict[str, Any]) -> None:
        self._state = state

    def __call__(self, jobs: list, t: float, zone_id: int) -> list:
        if not jobs or self._state is None:
            return fifo_dispatch(jobs, t, zone_id)
        try:
            feats = self._feat_ext.extract_scenario_features(self._state).reshape(1, -1)
            idx   = int(self._model.predict(feats)[0])
            fn    = _DISPATCH_FNS.get(_HEURISTIC_MAP.get(idx, "fifo"), fifo_dispatch)
            return fn(jobs, t, zone_id)
        except Exception as exc:
            logger.debug("Selector error: %s", exc)
            return fifo_dispatch(jobs, t, zone_id)


class _SessionPriority:
    """Per-simulation GBR priority predictor using a pre-loaded regressor."""
    def __init__(self, model: Any, feat_ext: FeatureExtractor) -> None:
        self._model    = model
        self._feat_ext = feat_ext
        self._state: Dict[str, Any] | None = None

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
        except Exception as exc:
            logger.debug("Priority error: %s", exc)
            return fifo_dispatch(jobs, t, zone_id)


# ---------------------------------------------------------------------------
# Baseline dispatch lookup
# ---------------------------------------------------------------------------
_BASELINE_FNS: Dict[str, Any] = {
    "FIFO":           fifo_dispatch,
    "EDD":            priority_edd_dispatch,
    "Critical-Ratio": critical_ratio_dispatch,
    "ATC":            atc_dispatch,
    "WSPT":           wspt_dispatch,
    "Slack":          slack_dispatch,
}

# ---------------------------------------------------------------------------
# Blocking simulation runner (runs in ThreadPoolExecutor)
# ---------------------------------------------------------------------------
def _run_pair(config: Dict[str, Any]) -> Dict[str, Any]:
    seed       = int(config.get("seed", 42))
    model_name = str(config.get("model", "xgb"))
    base_code  = str(config.get("baseCode", "FIFO"))
    params     = config.get("params", {})

    sim_kw: Dict[str, Any] = {
        "base_arrival_rate":  float(params.get("baseArrivalRate", 2.5)),
        "breakdown_prob":     float(params.get("breakdownProb", 0.003)),
        "batch_arrival_size": int(params.get("batchArrivalSize", 30)),
        "lunch_penalty_factor": 1.0 + float(params.get("lunchPenalty", 0.3)),
    }

    # ── Baseline ──────────────────────────────────────────────────────
    base_fn  = _BASELINE_FNS.get(base_code, fifo_dispatch)
    base_sim = WarehouseSimulator(seed=seed, heuristic_fn=base_fn, **sim_kw)
    base_sim.init()

    # ── DAHS ──────────────────────────────────────────────────────────
    feat_ext = FeatureExtractor()
    dahs_sim = WarehouseSimulator(seed=seed, heuristic_fn=fifo_dispatch, **sim_kw)

    if model_name in ("dt", "rf", "xgb") and model_name in _models:
        selector = _SessionSelector(_models[model_name], feat_ext)
        def dahs_dispatch(jobs, t, zone_id):
            selector.update(dahs_sim.get_state_snapshot())
            return selector(jobs, t, zone_id)
        dahs_sim.heuristic_fn = dahs_dispatch

    elif model_name == "priority" and "gbr" in _models:
        priority = _SessionPriority(_models["gbr"], feat_ext)
        def dahs_dispatch(jobs, t, zone_id):         # type: ignore[misc]
            priority.update(dahs_sim.get_state_snapshot())
            return priority(jobs, t, zone_id)
        dahs_sim.heuristic_fn = dahs_dispatch

    else:
        # Fallback: WSPT if requested model isn't loaded
        dahs_sim.heuristic_fn = wspt_dispatch

    dahs_sim.init()

    # ── Step both sims, collect snapshots ────────────────────────────
    baseline_snaps: List[Dict] = []
    dahs_snaps:     List[Dict] = []

    # Capture t=0 snapshot before advancing (env.run requires until > current time)
    baseline_snaps.append(base_sim.get_visual_snapshot())
    dahs_snaps.append(dahs_sim.get_visual_snapshot())

    t = SNAP_INTERVAL
    while t <= SIM_DURATION:
        base_sim.step_to(t)
        dahs_sim.step_to(t)
        baseline_snaps.append(base_sim.get_visual_snapshot())
        dahs_snaps.append(dahs_sim.get_visual_snapshot())
        t += SNAP_INTERVAL

    return {"baseline": baseline_snaps, "dahs": dahs_snaps}


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

        loop   = asyncio.get_event_loop()
        result = await loop.run_in_executor(EXECUTOR, _run_pair, config)

        await ws.send_json({
            "type":     "snapshots",
            "baseline": result["baseline"],
            "dahs":     result["dahs"],
            "total":    len(result["baseline"]),
        })
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
    # Serve static assets (JS, CSS, images)
    app.mount("/assets", StaticFiles(directory=str(_DIST / "assets")), name="assets")

    @app.get("/{full_path:path}", include_in_schema=False)
    async def serve_spa(full_path: str):
        """Return index.html for any non-API route (React Router SPA fallback)."""
        return FileResponse(str(_DIST / "index.html"))
else:
    logger.warning("website/dist not found — frontend not served. Run: cd website && node vite build")
