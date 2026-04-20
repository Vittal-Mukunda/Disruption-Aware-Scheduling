#!/usr/bin/env python3
"""
scripts/run_preset_benchmark.py — Per-preset 3-arm benchmark.

For each preset in src/presets.py, run THREE simulations on the preset's seed:
  1. Baseline       = preset.favored_heuristic            (the home-turf specialist)
  2. DAHS-Priority  = priority GBR (single fixed model)   (one learned ranker)
  3. Meta-selector  = BatchwiseSelector + xgb model       (the actual product)

The 3-arm view honestly addresses No-Free-Lunch:
  - DAHS-Priority is allowed to lose to a hand-tuned specialist on its own preset.
  - The Meta-selector is the actual product — it should match or beat the
    specialist by switching to that heuristic when conditions match.

Write results/preset_benchmark.json — consumed by the Simulation page's
"3-arm preset benchmark" panel.

Usage:
    python scripts/run_preset_benchmark.py
"""
from __future__ import annotations

import json
import logging
import sys
from pathlib import Path
from typing import Any, Dict, List

import joblib
import numpy as np

ROOT = Path(__file__).parent.parent
sys.path.insert(0, str(ROOT))

from src.simulator import WarehouseSimulator
from src.features import FeatureExtractor
from src.heuristics import (
    fifo_dispatch, priority_edd_dispatch, critical_ratio_dispatch,
    atc_dispatch, wspt_dispatch, slack_dispatch,
)
from src.presets import PRESETS

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
logger = logging.getLogger(__name__)

DISPATCH_FNS = {
    "fifo": fifo_dispatch,
    "priority_edd": priority_edd_dispatch,
    "critical_ratio": critical_ratio_dispatch,
    "atc": atc_dispatch,
    "wspt": wspt_dispatch,
    "slack": slack_dispatch,
}


def _make_priority_dispatch(model, fe: FeatureExtractor, sim_ref: list):
    """Closure: priority-GBR dispatcher that scores jobs per call."""
    def dispatch(jobs, t, zone_id):
        sim = sim_ref[0]
        if not jobs or sim is None:
            return fifo_dispatch(jobs, t, zone_id)
        try:
            state = sim.get_state_snapshot()
            sf = fe.extract_scenario_features(state)
            feats = np.stack([
                np.concatenate([sf, fe.extract_job_features(j, state)])
                for j in jobs
            ])
            scores = model.predict(feats)
            return [j for _, j in sorted(zip(scores, jobs),
                                         key=lambda x: x[0], reverse=True)]
        except Exception as exc:
            logger.warning("priority dispatch fallback (%s)", exc)
            return fifo_dispatch(jobs, t, zone_id)
    return dispatch


def _preset_kwargs(p) -> Dict[str, Any]:
    return dict(
        base_arrival_rate=p.base_arrival_rate,
        breakdown_prob=p.breakdown_prob,
        batch_arrival_size=p.batch_arrival_size,
        lunch_penalty_factor=p.lunch_penalty_factor,
        job_type_frequencies=p.job_type_frequencies,
        due_date_tightness=p.due_date_tightness,
        processing_time_scale=p.processing_time_scale,
    )


def _make_meta_dispatch(selector, sim_ref: list):
    """Closure: BatchwiseSelector dispatcher that re-evaluates state per call."""
    def dispatch(jobs, t, zone_id):
        sim = sim_ref[0]
        if sim is None:
            return fifo_dispatch(jobs, t, zone_id)
        try:
            selector.update_state(sim.get_state_snapshot())
            return selector.dispatch(jobs, t, zone_id)
        except Exception as exc:
            logger.warning("meta dispatch fallback (%s)", exc)
            return fifo_dispatch(jobs, t, zone_id)
    return dispatch


def run_preset(p, gbr_model, xgb_model) -> Dict[str, Any]:
    """Run all three arms on one preset and return a row dict."""
    from src.hybrid_scheduler import BatchwiseSelector

    sim_kw = _preset_kwargs(p)

    # ── Arm 1: Baseline (favored heuristic) ─────────────────────────────────
    fe1 = FeatureExtractor()
    base_fn = DISPATCH_FNS.get(p.favored_heuristic, fifo_dispatch)
    base_sim = WarehouseSimulator(seed=p.seed, heuristic_fn=base_fn,
                                  feature_extractor=fe1, **sim_kw)
    base_metrics = base_sim.run(duration=600.0)

    # ── Arm 2: DAHS-Priority (single fixed GBR) ─────────────────────────────
    fe2 = FeatureExtractor()
    sim_ref2: list = [None]
    dispatch2 = _make_priority_dispatch(gbr_model, fe2, sim_ref2)
    dahs_sim = WarehouseSimulator(seed=p.seed, heuristic_fn=dispatch2,
                                  feature_extractor=fe2, **sim_kw)
    sim_ref2[0] = dahs_sim
    dahs_metrics = dahs_sim.run(duration=600.0)

    # ── Arm 3: Meta-selector (BatchwiseSelector with xgb) ───────────────────
    fe3 = FeatureExtractor()
    selector = BatchwiseSelector(model=xgb_model, feature_extractor=fe3)
    sim_ref3: list = [None]
    dispatch3 = _make_meta_dispatch(selector, sim_ref3)
    meta_sim = WarehouseSimulator(seed=p.seed, heuristic_fn=dispatch3,
                                  feature_extractor=fe3, **sim_kw)
    sim_ref3[0] = meta_sim
    meta_metrics = meta_sim.run(duration=600.0)

    base_t = float(base_metrics.total_tardiness)
    dahs_t = float(dahs_metrics.total_tardiness)
    meta_t = float(meta_metrics.total_tardiness)
    dahs_imp = (base_t - dahs_t) / base_t * 100.0 if base_t > 0 else 0.0
    meta_imp = (base_t - meta_t) / base_t * 100.0 if base_t > 0 else 0.0

    # Snapshot which heuristics the meta-selector actually picked
    sw_log = selector.switching_log.entries if selector.switching_log else []
    picks = {}
    for entry in sw_log:
        h = entry.get("selected", "?")
        picks[h] = picks.get(h, 0) + 1
    top_picks = sorted(picks.items(), key=lambda x: x[1], reverse=True)[:3]

    return {
        "preset": p.name,
        "favored": p.favored_heuristic,
        "seed": int(p.seed),
        "baseline_tardiness": round(base_t, 2),
        "dahs_tardiness": round(dahs_t, 2),
        "meta_tardiness": round(meta_t, 2),
        "baseline_sla_breach": round(float(base_metrics.sla_breach_rate), 4),
        "dahs_sla_breach": round(float(dahs_metrics.sla_breach_rate), 4),
        "meta_sla_breach": round(float(meta_metrics.sla_breach_rate), 4),
        "baseline_completed": int(base_metrics.completed_jobs),
        "dahs_completed": int(dahs_metrics.completed_jobs),
        "meta_completed": int(meta_metrics.completed_jobs),
        "improvement_pct": round(dahs_imp, 2),       # back-compat: DAHS-Priority vs baseline
        "meta_improvement_pct": round(meta_imp, 2),  # meta-selector vs baseline
        "dahs_wins": dahs_t <= base_t,
        "meta_wins": meta_t <= base_t,
        "meta_top_picks": top_picks,                  # what did the selector actually pick?
        "meta_n_switches": len(sw_log),
    }


def main() -> None:
    gbr_path = ROOT / "models" / "priority_gbr.joblib"
    xgb_path = ROOT / "models" / "selector_xgb.joblib"
    if not gbr_path.exists():
        raise SystemExit(f"Missing model: {gbr_path}. Run scripts/run_pipeline.py first.")
    if not xgb_path.exists():
        raise SystemExit(f"Missing model: {xgb_path}. Run scripts/run_pipeline.py first.")

    logger.info("Loading priority GBR from %s", gbr_path)
    gbr_model = joblib.load(gbr_path)
    logger.info("Loading selector XGB from %s", xgb_path)
    xgb_model = joblib.load(xgb_path)

    rows: List[Dict[str, Any]] = []
    for p in PRESETS:
        logger.info("Running preset %s (favored=%s, seed=%d)",
                    p.name, p.favored_heuristic, p.seed)
        rows.append(run_preset(p, gbr_model, xgb_model))

    out_path = ROOT / "results" / "preset_benchmark.json"
    out_path.parent.mkdir(parents=True, exist_ok=True)
    out_path.write_text(json.dumps(rows, indent=2))
    logger.info("Wrote %s", out_path)

    print("\n" + "=" * 110)
    print(f"{'Preset':<22} {'Favored':<14} {'Baseline':>10} {'DAHS-Pri':>10} {'Meta-sel':>10} "
          f"{'DAHSwin':>8} {'Metawin':>8}")
    print("-" * 110)
    n_dahs = 0
    n_meta = 0
    for r in rows:
        if r["dahs_wins"]: n_dahs += 1
        if r["meta_wins"]: n_meta += 1
        print(f"{r['preset']:<22} {r['favored']:<14} "
              f"{r['baseline_tardiness']:>10.1f} {r['dahs_tardiness']:>10.1f} {r['meta_tardiness']:>10.1f} "
              f"{('YES' if r['dahs_wins'] else 'NO'):>8} {('YES' if r['meta_wins'] else 'NO'):>8}")
    print("=" * 110)
    print(f"DAHS-Priority wins: {n_dahs}/{len(rows)}   Meta-selector wins: {n_meta}/{len(rows)}\n")

    print("Meta-selector heuristic picks per preset:")
    for r in rows:
        picks = r.get("meta_top_picks", [])
        picks_str = ", ".join(f"{h}:{n}" for h, n in picks)
        print(f"  {r['preset']:<22} switches={r['meta_n_switches']:<3}  top_picks=[{picks_str}]")


if __name__ == "__main__":
    main()
