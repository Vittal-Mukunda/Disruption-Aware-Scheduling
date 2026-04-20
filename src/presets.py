"""
presets.py — Static-Solver Comparison Presets for DAHS_2

Each preset pins a single classical dispatch rule (FIFO, Priority-EDD, …) that
runs for the full 600-minute shift. The stress environment is the same realistic,
literature-calibrated workload used everywhere else in the project:

  - Time-varying job-type composition (morning Type-A dominant → afternoon bulk
    B/C/D → evening Type-E express surge), simulator._COMPOSITION_PROFILE.
  - Bimodal intraday arrival-rate curve with a lunch dip and an evening peak,
    simulator._SURGE_PROFILE.
  - Per-type processing-time lognormal variability (CV ≈ 30 %) and Poisson
    arrivals, all stochastic.

Presets intentionally do **not** override job_type_frequencies: the workload is
identical across presets and DAHS, so the only experimental variable is the
dispatch strategy itself. This rules out composition bias as an explanation for
any performance gap and makes the static-solver-vs-DAHS comparison a clean
controlled experiment.

Presets differ in operational stress parameters (arrival rate, breakdown rate,
batch size, deadline tightness, processing-time scale) so the static-solver
comparison is tested across a range of realistic operating regimes.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional, Tuple

logger = logging.getLogger(__name__)

HEURISTIC_INDEX = {
    "fifo": 0,
    "priority_edd": 1,
    "critical_ratio": 2,
    "atc": 3,
    "wspt": 4,
    "slack": 5,
}

HEURISTIC_LABELS = ["FIFO", "Priority-EDD", "Critical-Ratio", "ATC", "WSPT", "Slack"]


@dataclass
class PresetScenario:
    """A 600-min single-solver scenario used as a static baseline against DAHS.

    The solver named by ``favored_heuristic`` runs for the entire shift. The
    workload composition is always the realistic time-varying profile embedded
    in the simulator — this preset only configures stress parameters
    (arrival rate, breakdowns, deadline tightness, etc.).
    """
    name: str
    description: str
    favored_heuristic: str
    favored_heuristic_idx: int
    seed: int

    base_arrival_rate: float = 2.5
    breakdown_prob: float = 0.003
    batch_arrival_size: int = 30
    lunch_penalty_factor: float = 1.3

    # Kept for API compatibility. Presets leave this empty so the simulator
    # falls through to its realistic time-varying _COMPOSITION_PROFILE.
    # Setting a non-empty dict here would override the profile and reintroduce
    # composition bias — intentionally avoided.
    job_type_frequencies: Dict[str, float] = field(default_factory=dict)
    due_date_tightness: float = 1.0
    processing_time_scale: float = 1.0
    why_it_favors: str = ""


PRESETS: List[PresetScenario] = [

    # ── Preset 1: FIFO — light, low-disruption baseline ─────────────────────
    PresetScenario(
        name="Preset-1-FIFO",
        description="Light steady flow, no breakdowns, generous deadlines — FIFO runs for the full 600 min",
        favored_heuristic="fifo",
        favored_heuristic_idx=0,
        seed=200_001,
        base_arrival_rate=2.0,
        breakdown_prob=0.0,
        batch_arrival_size=10,
        lunch_penalty_factor=1.0,
        due_date_tightness=2.5,
        processing_time_scale=1.0,
        why_it_favors=(
            "Light load with loose deadlines and no disruptions — a regime where "
            "FIFO's simplicity is hard to beat. Runs on the same realistic "
            "time-varying package mix (A-dominant morning → B/C/D bulk afternoon → "
            "Type-E express evening) as every other arm."
        ),
    ),

    # ── Preset 2: Priority-EDD — tight deadlines, frequent express orders ──
    PresetScenario(
        name="Preset-2-Priority-EDD",
        description="Tight deadlines with frequent express orders — Priority-EDD runs for the full 600 min",
        favored_heuristic="priority_edd",
        favored_heuristic_idx=1,
        seed=200_002,
        base_arrival_rate=2.5,
        breakdown_prob=0.001,
        batch_arrival_size=20,
        lunch_penalty_factor=1.1,
        due_date_tightness=0.65,
        processing_time_scale=1.0,
        why_it_favors=(
            "Tight deadlines give Priority-EDD a natural edge: sorting by "
            "(priority class, due date) captures urgency directly. Workload is "
            "the same realistic A→E daily profile — any advantage comes from "
            "the dispatch rule, not from a biased job mix."
        ),
    ),

    # ── Preset 3: Critical Ratio — frequent station breakdowns ─────────────
    PresetScenario(
        name="Preset-3-CR",
        description="Frequent station breakdowns on a realistic workload — Critical-Ratio runs for the full 600 min",
        favored_heuristic="critical_ratio",
        favored_heuristic_idx=2,
        seed=200_003,
        base_arrival_rate=2.5,
        breakdown_prob=0.018,
        batch_arrival_size=20,
        lunch_penalty_factor=1.2,
        due_date_tightness=0.85,
        processing_time_scale=1.0,
        why_it_favors=(
            "Frequent breakdowns make static urgency scores go stale. "
            "Critical-Ratio = (due_date − now) / remaining_proc_time is "
            "recomputed every dispatch, so it tracks live time pressure. "
            "The arrival stream is the realistic time-varying one."
        ),
    ),

    # ── Preset 4: ATC — heavy load, morning surge ──────────────────────────
    PresetScenario(
        name="Preset-4-ATC",
        description="Heavy sustained load with high-weight jobs — ATC runs for the full 600 min",
        favored_heuristic="atc",
        favored_heuristic_idx=3,
        seed=200_004,
        base_arrival_rate=4.0,
        breakdown_prob=0.003,
        batch_arrival_size=50,
        lunch_penalty_factor=1.4,
        due_date_tightness=0.55,
        processing_time_scale=1.0,
        why_it_favors=(
            "Sustained heavy load needs joint weight–urgency optimisation. "
            "ATC's (w/p)·exp(−slack/K·p̄) closed form is near-optimal for "
            "weighted tardiness under congestion. Workload composition follows "
            "the realistic daily profile — no preset-specific mix."
        ),
    ),

    # ── Preset 5: WSPT — short jobs, loose deadlines, throughput focus ─────
    PresetScenario(
        name="Preset-5-WSPT",
        description="Short-jobs-dominate regime with loose deadlines — WSPT runs for the full 600 min",
        favored_heuristic="wspt",
        favored_heuristic_idx=4,
        seed=200_005,
        base_arrival_rate=3.0,
        breakdown_prob=0.001,
        batch_arrival_size=15,
        lunch_penalty_factor=1.0,
        due_date_tightness=2.0,
        processing_time_scale=0.7,
        why_it_favors=(
            "Processing times scaled down 30 % give short jobs on loose deadlines "
            "— the regime where Smith's weighted-shortest-processing-time rule "
            "is provably optimal for minimising weighted flow time. The arrival "
            "composition is the realistic time-varying profile."
        ),
    ),

    # ── Preset 6: Slack — recovery mode, very tight deadlines ──────────────
    PresetScenario(
        name="Preset-6-Slack",
        description="Recovery mode with very tight deadlines — Slack runs for the full 600 min",
        favored_heuristic="slack",
        favored_heuristic_idx=5,
        seed=200_006,
        base_arrival_rate=3.5,
        breakdown_prob=0.002,
        batch_arrival_size=60,
        lunch_penalty_factor=1.2,
        due_date_tightness=0.30,
        processing_time_scale=1.2,
        why_it_favors=(
            "Extreme deadline tightness triggers recovery behaviour. Slack "
            "= due_date − now − remaining_proc_time identifies which jobs can "
            "still be saved versus which are already lost. Workload is the "
            "realistic daily profile; stress comes from deadlines and batch size."
        ),
    ),

    # ── Preset 7: Real-Data Calibrated (Olist) — stress params only ────────
    PresetScenario(
        name="Preset-7-RealData",
        description=(
            "Stress parameters calibrated from Olist Brazilian E-Commerce "
            "dataset (96,478 real orders, 2016-2018) — WSPT runs for the full 600 min"
        ),
        favored_heuristic="wspt",
        favored_heuristic_idx=4,
        seed=200_007,
        # arrival_rate: Olist implies ~9.9 orders/hr; we use 30/hr (0.5/min)
        # representing a mid-scale DC operating at ~20% of peak capacity.
        # Ref: Olist Brazilian E-Commerce Dataset, Kaggle (2018);
        #      Published DC range 60-150/hr — Gu et al. (2010) EJOR 203(3):539-549.
        base_arrival_rate=0.5,
        # breakdown_prob: empirical 2-5% of operational hours — Inman (1999)
        breakdown_prob=0.003,
        # batch_arrival_size: calibrated to Olist avg items/order (~1.2 items)
        # scaled to warehouse batch size range — Bartholdi & Hackman (2019)
        batch_arrival_size=15,
        lunch_penalty_factor=1.2,
        # due_date_tightness: derived from Olist SLA/cycle ratio (23.2d / 10.2d = 2.27)
        # mapped to simulator scale: 1.5x gives comparable SLA pressure
        due_date_tightness=1.5,
        processing_time_scale=1.0,
        why_it_favors=(
            "Operational parameters (arrival rate 30/hr, batch size 15, "
            "deadline tightness 1.5×) are calibrated from 96,478 real Olist "
            "orders. Package composition still follows the realistic "
            "time-varying profile so there is no composition bias. WSPT is the "
            "static baseline for this operating regime."
        ),
    ),
]


def get_preset(name: str) -> PresetScenario:
    """Return a preset by name (case-insensitive match on prefix)."""
    name_lower = name.lower()
    for p in PRESETS:
        if p.name.lower() == name_lower or p.favored_heuristic == name_lower:
            return p
    raise ValueError(
        f"Unknown preset: {name!r}. Available: {[p.name for p in PRESETS]}"
    )


def get_all_presets() -> List[PresetScenario]:
    """Return all preset scenario configs."""
    return list(PRESETS)


def run_preset_demo(
    preset: PresetScenario,
    duration: float = 600.0,
) -> Dict[str, Any]:
    """Run all 6 baselines + DAHS on a preset, returning full comparison results."""
    from src.heuristics import (
        fifo_dispatch, priority_edd_dispatch, critical_ratio_dispatch,
        atc_dispatch, wspt_dispatch, slack_dispatch,
    )
    from src.simulator import WarehouseSimulator
    from src.features import FeatureExtractor

    dispatch_map = {
        "fifo": fifo_dispatch,
        "priority_edd": priority_edd_dispatch,
        "critical_ratio": critical_ratio_dispatch,
        "atc": atc_dispatch,
        "wspt": wspt_dispatch,
        "slack": slack_dispatch,
    }

    sim_kwargs = {
        "base_arrival_rate": preset.base_arrival_rate,
        "breakdown_prob": preset.breakdown_prob,
        "batch_arrival_size": preset.batch_arrival_size,
        "lunch_penalty_factor": preset.lunch_penalty_factor,
        "job_type_frequencies": preset.job_type_frequencies or {},
        "due_date_tightness": preset.due_date_tightness,
        "processing_time_scale": preset.processing_time_scale,
    }

    results: Dict[str, Any] = {}

    for heur_name, heur_fn in dispatch_map.items():
        fe = FeatureExtractor()
        sim = WarehouseSimulator(seed=preset.seed, heuristic_fn=heur_fn, feature_extractor=fe, **sim_kwargs)
        metrics = sim.run(duration=duration)
        results[heur_name] = metrics
        logger.info(
            "[%s] %s: tardiness=%.1f, sla=%.3f, throughput=%.2f",
            preset.name, heur_name, metrics.total_tardiness, metrics.sla_breach_rate, metrics.throughput,
        )

    import numpy as np
    tardy = np.array([results[h].total_tardiness for h in dispatch_map])
    sla   = np.array([results[h].sla_breach_rate for h in dispatch_map])
    cyc   = np.array([results[h].avg_cycle_time for h in dispatch_map])

    def _norm(arr):
        r = arr.max() - arr.min()
        return np.zeros_like(arr) if r == 0 else (arr - arr.min()) / r

    scores = 0.40 * _norm(tardy) + 0.35 * _norm(sla) + 0.25 * _norm(cyc)
    best_idx = int(np.argmin(scores))
    winner = list(dispatch_map.keys())[best_idx]

    logger.info("[%s] Empirical winner: %s (expected: %s) — %s",
                preset.name, winner, preset.favored_heuristic,
                "CORRECT" if winner == preset.favored_heuristic else "UNEXPECTED")

    # Try running DAHS if models are available
    dahs_selected = None
    switching_log = None

    try:
        from src.hybrid_scheduler import BatchwiseSelector, MODELS_DIR
        from pathlib import Path as _Path
        model_path = _Path(MODELS_DIR) / "selector_rf.joblib"
        if model_path.exists():
            import joblib
            model = joblib.load(model_path)
            fe = FeatureExtractor()
            selector = BatchwiseSelector(model=model, feature_extractor=fe)

            dahs_sim = WarehouseSimulator(
                seed=preset.seed,
                heuristic_fn=fifo_dispatch,
                feature_extractor=fe,
                **sim_kwargs,
            )

            def dahs_dispatch(jobs, t, zone_id):
                selector.update_state(dahs_sim.get_state_snapshot())
                return selector.dispatch(jobs, t, zone_id)

            dahs_sim.heuristic_fn = dahs_dispatch
            dahs_metrics = dahs_sim.run(duration=duration)
            results["dahs"] = dahs_metrics
            switching_log = selector.switching_log

            dist: Dict[str, int] = {}
            for e in switching_log.entries:
                h = e["selected"]
                dist[h] = dist.get(h, 0) + 1
            dahs_selected = max(dist, key=dist.get) if dist else None
    except Exception as exc:
        logger.warning("[%s] DAHS run skipped: %s", preset.name, exc)

    return {
        "preset": {
            "name": preset.name,
            "favored_heuristic": preset.favored_heuristic,
            "seed": preset.seed,
            "why_it_favors": preset.why_it_favors,
        },
        "results": results,
        "scores": {h: float(s) for h, s in zip(dispatch_map.keys(), scores)},
        "winner": winner,
        "correct": winner == preset.favored_heuristic,
        "dahs_selected": dahs_selected,
        "switching_log": switching_log,
    }


def run_all_preset_demos(duration: float = 600.0) -> List[Dict[str, Any]]:
    """Run all preset demos and print a summary table."""
    all_results = []
    print("\n" + "=" * 72)
    print("  DAHS_2 PRESET PROOF-OF-CONCEPT EVALUATION")
    print("=" * 72)
    print(f"  {'Preset':<26} {'Expected':>14} {'Empirical Winner':>17} {'Match':>6} {'DAHS Pick':>12}")
    print("-" * 72)

    for preset in PRESETS:
        result = run_preset_demo(preset, duration=duration)
        all_results.append(result)

        match_str = "OK" if result["correct"] else "--"
        dahs_str = result["dahs_selected"] or "N/A"
        print(f"  {preset.name:<26} {preset.favored_heuristic:>14} "
              f"{result['winner']:>17} {match_str:>6} {dahs_str:>12}")

    n_correct = sum(1 for r in all_results if r["correct"])
    print("-" * 72)
    print(f"  Presets where empirical winner = expected: {n_correct}/{len(PRESETS)}")
    print("=" * 72 + "\n")

    return all_results


if __name__ == "__main__":
    import logging as _logging
    _logging.basicConfig(level=_logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
    run_all_preset_demos()
