# DAHS_2 — Complete Implementation Plan

> **How to use this file**: When you start a new Claude session, paste this message:
> "Read the file IMPLEMENTATION_PLAN.md in my project directory and implement the project phase by phase. Start with Phase 1."
> Claude will have all the context needed to build the entire project.

---

## What Is DAHS?

DAHS (Disruption-Aware Hybrid Scheduler) is an ML-enhanced warehouse job-shop scheduler that dynamically selects the best dispatching heuristic based on real-time warehouse state. Instead of using one fixed scheduling rule all day, it observes the current situation (queue sizes, breakdowns, job mix, time pressure) and picks whichever of 6 heuristics works best right now.

**Stack**: Python 3.10+ (SimPy + FastAPI + sklearn/XGBoost), React 18 + Vite + Tailwind frontend  
**Target**: College thesis, potential conference presentation  
**Key requirement**: NO BLACK BOX — judges interact with the software, everything must be transparent and explainable

---

## 5 Critical Improvements Over DAHS_1

### 1. Situation-Level Training (NOT day-level)
OLD: Run full 600-min sim with each heuristic, label which wins overall → 1 row per scenario  
NEW: Take snapshots every 10 min, fork 6 short sims (20 min each), label which wins per-window → 60 rows per scenario

### 2. Batch-wise Inference (NOT per-dispatch)
OLD: Call ML model at every single dispatch event → chaotic switching hundreds of times per hour  
NEW: Re-evaluate every 15 minutes OR on disruption events (breakdown, batch arrival, lunch) → stable, deliberate switching with hysteresis (only switch if >15% more confident)

### 3. Edge Case Guardrails
- Trivial load (< 5 jobs in system) → skip ML, use FIFO
- Overload (> 92% avg utilization) → lock to ATC + alert
- Out-of-distribution (features outside training range) → safe fallback to ATC
- Starvation prevention (job waiting > 60 min) → force-promote regardless of heuristic

### 4. 3-Level Interpretability
- Level 1: Plain English ("DAHS picked ATC because 45% of jobs are under time pressure")
- Level 2: Feature attribution bar chart (which of 22 features drove the decision)
- Level 3: Decision tree path, confidence probabilities for all 6 heuristics, what-if comparison

### 5. Educational Frontend (3 pages)
- Landing: headline result, calibrated metrics fetched from `/api/results`, calls to action
- Methodology: pipeline steps, design decisions, comparison with DAHS_1, statistical protocol
- Simulation: interactive demo with side-by-side baseline vs DAHS, real-time explainability log

(Earlier drafts described a 5-page site with separate Overview, Results, and
Architecture pages; those were merged into Landing + Methodology + Simulation
to avoid duplication. The Results page content is now served as JSON via
`GET /api/results` once `scripts/run_pipeline.py` has populated
`results/benchmark_summary.json` and `results/statistical_tests.json`.)

---

## Full Reconstruction Spec Reference

The complete DAHS specification (all algorithms, constants, data structures) is documented in the user's original spec. Key constants:

- 8 warehouse zones, 37 stations, 5 job types (A-E)
- 6 heuristics: FIFO, Priority-EDD, Critical Ratio, ATC (K=2.0), WSPT, Slack
- 22 scenario features + 7 job features = 29 total
- Scoring: 0.40*tardiness + 0.35*SLA + 0.25*cycle_time (no makespan)
- Models: DT(depth=10), RF(400 trees, depth=14), XGB(500 trees, lr=0.03, depth=8), GBR(300, depth=6, lr=0.05)
- Test: 300 seeds (99000-99299), Friedman + Nemenyi + Wilcoxon + Cohen's d + Bootstrap CI

---

## Directory Structure

```
DAHS_2/
├── start.py                          # Launcher
├── server.py                         # FastAPI + WebSocket
├── requirements.txt
├── IMPLEMENTATION_PLAN.md            # This file
│
├── src/
│   ├── __init__.py                   # Public API
│   ├── simulator.py                  # SimPy engine + save_state/from_state (NEW)
│   ├── heuristics.py                 # 6 dispatch functions
│   ├── features.py                   # 29-feature extractor + get_feature_ranges (NEW)
│   ├── hybrid_scheduler.py           # BatchwiseSelector + guardrails (NEW)
│   ├── data_generator.py             # Snapshot-fork training data (NEW)
│   ├── train_selector.py             # Train DT/RF/XGB + export artifacts
│   ├── train_priority.py             # Train GBR
│   ├── evaluator.py                  # Benchmark + stats + plots
│   └── presets.py                    # 6 preset scenarios
│
├── scripts/
│   └── run_full_pipeline.py          # 11-step orchestrator
│
├── data/raw/                         # Generated CSVs
├── models/                           # Trained models + interpretability artifacts
├── results/plots/                    # Generated plots
├── logs/                             # Pipeline logs
│
└── website/
    ├── package.json
    ├── vite.config.js
    ├── tailwind.config.js
    ├── postcss.config.js
    ├── index.html
    └── src/
        ├── main.jsx
        ├── App.jsx                   # 5 routes
        ├── index.css
        ├── components/
        │   ├── Navbar.jsx
        │   ├── Footer.jsx
        │   ├── WarehouseCanvas.jsx       # Reusable warehouse visualization
        │   ├── MetricsPanel.jsx          # Real-time metrics
        │   ├── SwitchingLog.jsx          # Real-time heuristic log
        │   ├── FeatureAttribution.jsx    # Level 2 explainability
        │   ├── DecisionExplainer.jsx     # Level 3 glass-box
        │   └── GuardrailIndicator.jsx    # Guardrail status badge
        ├── pages/
        │   ├── Overview.jsx              # Educational landing
        │   ├── Algorithms.jsx            # 6 heuristics explained
        │   ├── Simulation.jsx            # Main demo
        │   ├── Results.jsx               # Statistical dashboard
        │   └── Architecture.jsx          # System diagram
        └── simulation/
            └── engine.js                 # Client-side reference sim
```

---

## Phase 1: Project Scaffold + Backend Core
**Dependencies: None**

### Files to create (in order):

**1. `requirements.txt`**
```
simpy>=4.0
scikit-learn>=1.3
xgboost>=2.0
shap>=0.43
pandas>=2.0
numpy>=1.24
matplotlib>=3.7
seaborn>=0.12
joblib>=1.3
tqdm>=4.65
scipy>=1.10
fastapi>=0.110
uvicorn[standard]>=0.29
websockets>=12.0
```

**2. `src/heuristics.py`** — Port verbatim from `DAHS/src/heuristics.py` (~231 lines)
- 6 dispatch functions: fifo, priority_edd, critical_ratio, atc, wspt, slack
- Constants: _PRIORITY_CLASS, _PRIORITY_WEIGHT
- Helper: compute_critical_ratio()
- All functions signature: (jobs, current_time, zone_id) -> List[Job]

**3. `src/features.py`** — Port from `DAHS/src/features.py` (~368 lines) + add:
- `get_feature_ranges()` method on FeatureExtractor that returns {feature_name: (min, max)} from training data
- All 22 scenario features (F1-F22) and 7 job features exactly as specified
- Novel features: disruption_intensity (F19), queue_imbalance (F20), job_mix_entropy (F21), time_pressure_ratio (F22)

**4. `src/presets.py`** — Port verbatim from `DAHS/src/presets.py` (~416 lines)
- 6 PresetScenario configs, each tuned to favor one heuristic
- get_preset(), get_all_presets(), run_preset_demo(), run_all_preset_demos()

**5. `src/simulator.py`** — Port from `DAHS/src/simulator.py` (~674 lines) + add NEW methods:

**NEW: `save_state() -> dict`**
Captures complete simulation state for snapshot-fork training:
- env.now (current time)
- Deep copies of all_jobs, completed_jobs, zone_queues
- All station states (is_broken, repair_end_time, current_job, busy_until)
- RNG state via rng.bit_generator.state
- _job_counter, _zone_busy_time, _lunch_active, queue snapshot history

**NEW: `from_state(state_dict, heuristic_fn) -> WarehouseSimulator`** (classmethod)
Creates a new simulator from a saved state:
- New simpy.Environment(initial_time=saved_time)
- Restores all job/station/queue data (deep copy)
- Re-registers all SimPy processes from the saved point
- Re-enqueues in-progress jobs with remaining processing time
- Continues RNG from saved state for deterministic continuation

**NEW: `get_partial_metrics(since_time) -> SimulationMetrics`**
Computes metrics only for jobs completed between since_time and env.now.
Needed for the 20-minute fork evaluation window in data generation.

**6. `src/__init__.py`** — Public API exports (all classes and functions)

### Verification:
- Simulator runs 600 min with FIFO, metrics non-zero
- save_state() at t=100, from_state() with same heuristic → metrics match continuous run
- Fork from same state with two different heuristics → metrics diverge

---

## Phase 2: Snapshot-Fork Data Generator
**Dependencies: Phase 1**

**7. `src/data_generator.py`** — Write fresh (~500 lines)

### Core algorithm:
```python
def generate_selector_dataset(n_scenarios=1000, n_workers=4):
    configs = _make_diverse_scenario_configs(n_scenarios, rng=np.random.default_rng(777))
    # Port 7-region config generator from DAHS_1
    
    # Parallel: each worker runs one full scenario
    with Pool(n_workers) as pool:
        results = pool.map(_run_snapshot_scenario, configs)
    
    # Flatten: each scenario produces ~60 rows
    # Save to data/raw/selector_dataset.csv

def _run_snapshot_scenario(config):
    # 1. Run base sim (FIFO) for 600 min
    sim = WarehouseSimulator(seed, fifo_dispatch, **config)
    sim.init()
    
    rows = []
    for t in range(10, 610, 10):  # every 10 minutes
        sim.step_to(t)
        state = sim.save_state()
        features = extract_scenario_features(sim.get_state_snapshot())
        
        # Fork 6 heuristics for 20 min each
        scores = []
        for heuristic in ALL_HEURISTICS:
            fork = WarehouseSimulator.from_state(state, heuristic)
            fork.step_to(t + 20)
            metrics = fork.get_partial_metrics(since_time=t)
            scores.append(composite_score(metrics))
        
        label = argmin(scores)  # best heuristic for THIS situation
        rows.append([*features, label])
    
    return rows
```

### Scoring formula (same as DAHS_1):
```
score = 0.40 * norm_tardiness + 0.35 * norm_sla + 0.25 * norm_cycle_time
```

### 7-region scenario diversity (port from DAHS_1):
- FIFO-friendly: low arrival, no breakdowns, loose deadlines
- P-EDD-friendly: express-heavy, tight deadlines
- CR-friendly: high breakdowns, diverse mix
- ATC-friendly: high load, tight deadlines
- WSPT-friendly: many short jobs, relaxed deadlines
- Slack-friendly: very tight deadlines, recovery mode
- Default: random Dirichlet mix

### Priority dataset (port from DAHS_1):
Same approach — ATC baseline, sample jobs, compute oracle score:
```
score = 0.30*urgency + 0.25*importance + 0.20*efficiency + 0.25*delivery
```
Save to data/raw/priority_dataset.csv

### Verification:
- 60 rows per scenario
- Label distribution: each heuristic >5%
- Features differ between t=100 and t=500

---

## Phase 3: Training Pipeline
**Dependencies: Phase 2**

**8. `src/train_selector.py`** — Port from DAHS_1 + additions (~220 lines)

### Models (same hyperparameters as DAHS_1):
- DT: max_depth=10, class_weight="balanced", random_state=42
- RF: n_estimators=400, max_depth=14, class_weight="balanced", n_jobs=-1, random_state=42
- XGB: n_estimators=500, lr=0.03, max_depth=8, eval_metric="mlogloss", random_state=42

### Training:
- train_test_split: test_size=0.20, random_state=42, stratify=y
- CV: StratifiedKFold(n_splits=5, shuffle=True, random_state=123)
- Sanitize: np.nan_to_num(X, nan=0.0, posinf=999.0, neginf=-999.0)
- XGB: fit with compute_sample_weight("balanced", y_train)

### NEW artifact exports:
- `models/feature_ranges.json`: {feature_name: [min, max]} from X_train
- `models/dt_structure.json`: Extract DT nodes (feature, threshold, children, class) for frontend
- `models/feature_names.json`: Ordered list with human-readable descriptions

### Plots:
- Feature importance (RF + XGB, side-by-side, dark theme bg=#0f1117)
- Decision tree visualization (max_depth=4)

**9. `src/train_priority.py`** — Port verbatim from DAHS_1 (~145 lines)
- GBR: n_estimators=300, max_depth=6, lr=0.05, subsample=0.8, min_samples_leaf=5
- SHAP summary plot

---

## Phase 4: Batch-wise Hybrid Scheduler with Guardrails
**Dependencies: Phase 3**

**10. `src/hybrid_scheduler.py`** — Write fresh (~450 lines)

### Core: `BatchwiseSelector`
```python
class BatchwiseSelector:
    EVAL_INTERVAL = 15.0         # minutes between re-evaluations
    HYSTERESIS_THRESHOLD = 0.15  # only switch if >15% more confident
    TRIVIAL_LOAD = 5             # skip ML if fewer jobs
    OVERLOAD_THRESHOLD = 0.92    # lock to ATC
    STARVATION_LIMIT = 60.0      # force-promote starving jobs

    HEURISTIC_MAP = {
        0: "fifo", 1: "priority_edd", 2: "critical_ratio",
        3: "atc", 4: "wspt", 5: "slack"
    }
```

### Evaluation flow:
1. `_should_reevaluate(sim_state)`:
   - Time: `now - last_eval >= 15.0`
   - Events: breakdown count changed, batch arrived, lunch state changed
2. `_check_guardrails(sim_state, features)`:
   - Trivial: n_orders_in_system < 5 → return "fifo"
   - Overload: avg utilization > 0.92 → return "atc"
   - OOD: any feature outside training range ±10% → return "atc"
3. `_evaluate(sim_state)`:
   - Extract 22 features → model.predict_proba → probabilities
4. Hysteresis:
   - If new_heuristic != current AND new_conf < current_conf + 0.15 → keep current
5. Starvation: any job waiting > 60 min → force to front of sorted list

### Evaluation log (for frontend interpretability):
Every evaluation records:
```python
{
    "time": float,
    "features": list[float],        # all 22
    "probabilities": dict,           # all 6 heuristic probs
    "selected": str,                 # heuristic name
    "switched": bool,
    "reason": str,                   # "ml_decision" | "hysteresis_blocked" | "guardrail_trivial" | "guardrail_overload" | "guardrail_ood"
    "confidence": float,
    "topFeatures": list[dict],       # top 5 by importance
    "plainEnglish": str              # human-readable explanation
}
```

### Plain English generator:
```python
def _generate_explanation(features, heuristic, reason, probas):
    if reason.startswith("guardrail"):
        return f"Guardrail active: {reason}. Using {heuristic} as safe default."
    
    # Map top features to natural language
    explanations = {
        ("atc", "time_pressure_ratio"): "many jobs are nearing their deadlines",
        ("atc", "surge_multiplier"): "demand is surging",
        ("critical_ratio", "n_broken_stations"): "station breakdowns are causing bottlenecks",
        ("fifo", "zone_utilization_avg"): "load is light, simple ordering is sufficient",
        ("wspt", "avg_priority_weight"): "high-value short jobs should be prioritized",
        # ... more mappings
    }
```

### Also include (port from DAHS_1):
- `SwitchingLog` class
- `HybridPriority` class (GBR per-job scoring)
- Factory functions

### Integration with simulator:
- Add `_batchwise_eval_process` as a SimPy process in simulator.init()
- Hook disruption events to trigger immediate re-evaluation
- Single heuristic across ALL zones between evaluations

---

## Phase 5: FastAPI Server
**Dependencies: Phase 4**

**11. `server.py`** — Port from DAHS_1 + extensions (~450 lines)

### REST endpoints:
```python
GET /health              → {"status": "ok", "models": [...]}
GET /api/presets          → [preset configs with params]
GET /api/feature-names    → [{name, description, category}]
GET /api/heuristic-info   → [{name, formula, whenBest, whenWorst}]
GET /api/model-info       → {type, accuracy, featureImportances}
GET /api/dt-structure     → {nodes: [{feature, threshold, left, right, class}]}
GET /api/results          → pre-computed benchmark JSON for Results page
```

### WebSocket `/ws/simulate`:
Runs paired simulation (baseline vs DAHS), streams snapshots every 2 sim-minutes.

Extended payload:
```json
{
  "type": "snapshots",
  "baseline": [301 snapshots],
  "dahs": [301 snapshots],
  "evaluationLog": [
    {
      "time": 15.0,
      "heuristic": "atc",
      "switched": true,
      "reason": "ml_decision",
      "confidence": 0.73,
      "probabilities": {"fifo": 0.05, "priority_edd": 0.08, "critical_ratio": 0.06, "atc": 0.73, "wspt": 0.05, "slack": 0.03},
      "topFeatures": [
        {"name": "time_pressure_ratio", "value": 0.45, "importance": 0.32},
        {"name": "zone_utilization_avg", "value": 0.78, "importance": 0.21}
      ],
      "guardrailActive": null,
      "plainEnglish": "DAHS picked ATC because 45% of jobs are under time pressure and warehouse utilization is high at 78%"
    }
  ],
  "switchingSummary": {
    "totalEvaluations": 40,
    "switchCount": 7,
    "switchingRate": 0.175,
    "hystersisBlocked": 12,
    "guardrailActivations": 3,
    "distribution": {"atc": 0.42, "cr": 0.23, ...}
  }
}
```

**12. `start.py`** — Port from DAHS_1 (~85 lines), update banner

---

## Phase 6: Frontend
**Dependencies: Phase 5**

### Setup (port from DAHS_1):
- package.json, vite.config.js, tailwind.config.js, postcss.config.js, index.html
- main.jsx, index.css (dark theme, bg=#0f1117)

### App.jsx (5 routes):
```jsx
<Routes>
  <Route path="/" element={<Overview />} />
  <Route path="/algorithms" element={<Algorithms />} />
  <Route path="/simulation" element={<Simulation />} />
  <Route path="/results" element={<Results />} />
  <Route path="/architecture" element={<Architecture />} />
</Routes>
```

### Pages:

**Overview.jsx** (~400 lines) — Educational landing page:
1. Hero: "Disruption-Aware Hybrid Scheduling" with animated warehouse
2. "What is Job-Shop Scheduling?" — simple Gantt chart example
3. "Why Adaptive?" — visual: same warehouse, different disruptions → different best heuristic
4. "How DAHS Works" — 3-step: Observe → Decide → Execute
5. "Key Innovation" — situation-level training diagram
6. Navigation cards to other pages

**Algorithms.jsx** (~800 lines) — Each heuristic explained:
- Port animated demos from DAHS_1's Baselines.jsx
- For each of 6 heuristics: plain English description, formula, animated sorting demo, "when it works best" / "when it fails"
- Interactive: click a heuristic to see it sort a sample queue

**Simulation.jsx** (~600 lines) — Main interactive demo:
- Controls: preset dropdown, model selector, baseline heuristic, param sliders, play/pause/reset
- Side-by-side: WarehouseCanvas (baseline) | WarehouseCanvas (DAHS)
- Below canvases: 4 panels
  - MetricsPanel: completed jobs, on-time %, tardiness, cycle time, throughput
  - SwitchingLog: scrollable table of every evaluation (time, heuristic, switched?, reason, confidence)
  - FeatureAttribution: horizontal bar chart of top features driving current decision
  - DecisionExplainer: 3 tabs (English / Features / Glass-Box with DT path + probabilities)
- GuardrailIndicator: status badge (green=ML active, yellow=trivial, red=overload, orange=OOD)
- Timeline scrubber: click to jump to any point

**Results.jsx** (~500 lines) — Pre-computed statistical dashboard:
- Summary table: 9 methods × 7 metrics
- Box plots (makespan, tardiness)
- Radar chart (5 normalized dimensions)
- SLA breach bar chart
- Friedman test result + Nemenyi CD diagram
- Wilcoxon test table with effect sizes
- Switching analysis: distribution pie, rate over time, transition heatmap

**Architecture.jsx** (~300 lines) — System diagram:
- SVG architecture diagram: Simulator → Features → BatchwiseSelector → Dispatch
- Training pipeline flow: Scenarios → Snapshots → Forks → Labels → Models
- Data flow: WebSocket streaming diagram
- Technology stack badges
- "What makes DAHS_2 different" comparison table

### Components:
- **WarehouseCanvas.jsx** (~300 lines): 8 zones in U-shape, station circles (green/yellow/red), job dots colored by type, queue strips
- **MetricsPanel.jsx** (~150 lines): animated counters for each metric
- **SwitchingLog.jsx** (~150 lines): scrollable table, color-coded rows (green=switch, yellow=blocked, red=guardrail)
- **FeatureAttribution.jsx** (~200 lines): horizontal bar chart, top 8 features, SHAP-style coloring
- **DecisionExplainer.jsx** (~350 lines): 3-tab interface with DT path rendering, probability bars, what-if
- **GuardrailIndicator.jsx** (~80 lines): animated status badge with tooltip

### Judge UX Flow:
1. **Overview** (2 min) → Learn what JSSP is, why it matters
2. **Algorithms** (3 min) → See each heuristic animated, understand tradeoffs
3. **Simulation** (5 min) → Pick preset, run, watch DAHS adapt in real-time
   - See switching log update live
   - Click any switch → see 3-level explanation
   - See guardrails activate during edge cases
   - Final metrics: DAHS beats baseline by X%
4. **Results** (2 min) → See statistical proof across 300 scenarios
5. **Architecture** (1 min) → Understand the system isn't a black box

---

## Phase 7: Evaluation Pipeline + Polish
**Dependencies: Phase 4 (partially parallel with Phase 5-6)**

**13. `src/evaluator.py`** — Port from DAHS_1 + extensions (~600 lines)

### Benchmark:
- 300 test seeds (99000-99299) × 9 methods
- Metrics: makespan, total_tardiness, sla_breach_rate, avg_cycle_time, zone_utilization_avg, throughput, queue_max
- Save to results/benchmark_results.csv

### Statistical tests:
- Friedman χ² (multi-way comparison)
- Nemenyi post-hoc (critical difference diagram)
- Wilcoxon signed-rank (paired, alternative="greater", Holm correction)
- Cohen's d (effect sizes)
- Bootstrap CI (5000 resamples)

### NEW: Switching analysis
- Average evaluations per simulation
- Average switches per simulation
- Hysteresis block rate
- Guardrail activation rate
- Heuristic distribution binned by shift phase

### NEW: JSON export for frontend
- results/benchmark_summary.json
- results/statistical_tests.json
- results/switching_analysis.json

### Plots (dark theme, bg=#0f1117):
1. Benchmark boxplots (makespan + tardiness)
2. SLA breach bar chart
3. Zone utilization heatmap
4. Gantt chart (sample seed)
5. Critical difference diagram
6. Pareto front (makespan vs tardiness)
7. Radar chart
8. Effect sizes with significance stars
9. Switching distribution
10. Switching timeseries
11. Switching rate histogram

**14. `scripts/run_full_pipeline.py`** — Port + adjust (~330 lines)

### Steps:
1. Import check
2. Generate selector dataset (snapshot-fork)
3. Generate priority dataset
4. Train selector models (DT, RF, XGB)
5. Train priority model (GBR)
6. Export interpretability artifacts
7. Run benchmark (300 seeds × 9 methods)
8. Statistical analysis
9. Generate plots
10. Switching analysis
11. Preset demos
12. Export results JSON

### CLI:
- `--quick`: 50 scenarios, 20 bench seeds
- `--full`: 1000 scenarios, 300 bench seeds
- `--eval-only`: skip steps 1-5
- `--analysis-only`: skip steps 1-7

---

## 15 DAHS_1 Bugs to Avoid

1. F7 bottleneck = `max(zone_util.values())` NOT zone_id
2. Dispatch map must have all 6 entries (0: fifo through 5: slack)
3. Use `Union[Path, str]` not `Path | str` (Python <3.10 compat)
4. Use `Optional[Dict[str, Any]]` not `Dict | None`
5. CR done jobs return 999.0 not float('inf')
6. Training: `np.nan_to_num(X, nan=0.0, posinf=999.0, neginf=-999.0)`
7. Priority: `df.replace([np.inf, -np.inf], np.nan).dropna()`
8. Broken station wait INSIDE `with resource.request()` block
9. Lognormal sigma = 0.30 (not 0.15)
10. Wilcoxon `alternative="greater"` (tests baseline > hybrid)
11. CV `random_state=123` (different from split seed 42)
12. Features from best heuristic's run, not always FIFO
13. Queue imbalance guard: `mean > 1e-6` not `> 0`
14. Python detection: `shutil.which("python3")`
15. Final snapshot reaches exactly SIM_DURATION=600

---

## Build Order (Critical Path)

```
Phase 1 (scaffold + core)         ← START HERE
    ↓
Phase 2 (data generator)
    ↓
Phase 3 (training pipeline)
    ↓
Phase 4 (hybrid scheduler)  ──→  Phase 7 (evaluation, can start here)
    ↓
Phase 5 (server)
    ↓
Phase 6 (frontend)
    ↓
Phase 7 (remaining: plots, JSON export)
    ↓
Final: npm run build, test end-to-end
```

---

## Quick Start (after full build)

```bash
pip install -r requirements.txt
cd website && npm install && npm run build && cd ..
python scripts/run_full_pipeline.py --quick    # ~30 min
python start.py                                 # opens http://localhost:8000
```

---

## Key Source Files to Reference from DAHS_1

All at `C:/Users/vitta/OneDrive/Desktop/Projects/DAHS/`:
- `src/simulator.py` (674 lines) — core to port, add save/restore
- `src/heuristics.py` (231 lines) — port verbatim
- `src/features.py` (368 lines) — port + add get_feature_ranges
- `src/presets.py` (416 lines) — port verbatim
- `src/hybrid_scheduler.py` (305 lines) — reference for SwitchingLog, rewrite BatchwiseSelector
- `src/data_generator.py` (487 lines) — reference for 7-region configs, rewrite core algorithm
- `src/train_selector.py` (197 lines) — port + add artifact exports
- `src/train_priority.py` (144 lines) — port verbatim
- `src/evaluator.py` (1077 lines) — port + add switching analysis
- `server.py` (330 lines) — port + extend WebSocket payload
- `website/src/pages/Simulation.jsx` (1323 lines) — decompose into components
- `website/src/pages/Baselines.jsx` (1817 lines) — port heuristic animations
- `website/src/simulation/engine.js` (538 lines) — port verbatim
