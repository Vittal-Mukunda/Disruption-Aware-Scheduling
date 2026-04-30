# DAHS 2.0: Disruption-Aware Hybrid Scheduler

DAHS 2.0 is an advanced, machine-learning-driven discrete-event simulation and scheduling framework for warehouse and manufacturing environments. It aims to solve the problem of dynamic job shop scheduling under chaotic conditions, such as sudden machine breakdowns, batch arrivals, or strict deadline pressures.

Rather than relying on a single static heuristic (like FIFO or WSPT), DAHS dynamically monitors the system state and employs **Meta-Selection** (switching between heuristics every 15 minutes) or **Job-Level Priority Ranking** (via Gradient Boosting) to minimize total job tardiness.

## 🏗️ Architecture Overview

The system is split into a **Python Simulation & ML Backend** and a **React-based Web Frontend**, running together in a unified architecture.

1. **Simulation Engine (`src/simulator.py`)**: A SimPy-based discrete-event simulator that tracks jobs, zones, routing, processing stations, and dynamic disruptions (breakdowns).
2. **Machine Learning Pipeline (`src/`)**: Extracts real-time features from the simulation state and trains scikit-learn/XGBoost models to predict optimal scheduling actions.
3. **FastAPI Backend (`server.py`)**: Serves the REST API for model metrics and a high-performance WebSocket connection to stream live simulation runs to the browser.
4. **React Frontend (`website/`)**: A rich, interactive dashboard built with Vite and Tailwind CSS. It visualizes the simulation live, compares DAHS against standard baselines, and explains ML decisions (Interpretability).

---

## 📂 Project Structure & File Functionality

### Root Files
- **`start.py`**: The main bootstrapper script. It automatically locates the correct Python environment, starts the FastAPI server (`server.py`) via Uvicorn, and opens the frontend in the user's default browser.
- **`server.py`**: The core FastAPI application. Handles REST endpoints (`/api/presets`, `/api/feature-names`, etc.) and manages the WebSocket `/ws/simulate` endpoint. It instantiates the `WarehouseSimulator` and `_BatchwiseSessionSelector` to run simulation battles (DAHS vs. Baseline) and stream the JSON results back to the frontend.
- **`requirements.txt`**: Standard Python dependencies (SimPy, Scikit-Learn, XGBoost, SHAP, FastAPI, Uvicorn, WebSockets).
- **`Dockerfile`**: For containerized deployment of the full stack.

### 🧠 Core Engine (`src/`)
- **`src/simulator.py`**: The `WarehouseSimulator` class. Manages the clock, job arrivals, zone queues, machine breakdowns, and applies the active dispatch heuristic whenever a machine frees up.
- **`src/features.py`**: The `FeatureExtractor`. Extracts 24 scenario-level features (e.g., utilization, time pressure, breakdown counts) and job-level features (e.g., slack, remaining operations) used by the ML models.
- **`src/heuristics.py`**: Implementations of classic Operations Research dispatch rules:
  - `fifo_dispatch` (First-In, First-Out)
  - `priority_edd_dispatch` (Earliest Due Date)
  - `critical_ratio_dispatch` (Time Remaining / Work Remaining)
  - `atc_dispatch` (Apparent Tardiness Cost - excellent for overloaded systems)
  - `wspt_dispatch` (Weighted Shortest Processing Time)
  - `slack_dispatch` (Slack time)
- **`src/data_generator.py`**: Runs thousands of parallel simulation episodes using different heuristics to generate a supervised learning dataset (`training_data.csv`).
- **`src/train_selector.py`**: Trains the **Meta-Selector** classifiers (Decision Tree, Random Forest, XGBoost) on the dataset. It learns which heuristic performs best given a specific system state.
- **`src/train_priority.py`**: Trains the **Priority Ranker** (Gradient Boosting Regressor) to assign absolute urgency scores to individual jobs.
- **`src/hybrid_scheduler.py`**: The offline evaluation harness for the Hybrid Scheduler, tracking state switching.
- **`src/evaluator.py`**: Compares trained ML models against static baselines across thousands of unseen test scenarios to generate rigorous statistical results.
- **`src/presets.py`**: Contains predefined simulation scenarios ("presets") like "Morning Rush," "Cascading Failure," or "The Lunch Crunch," with optimized parameters for the frontend.
- **`src/references.py`**: Bibliography and literature references used in the methodology.

### 📜 Automation & Scripts (`scripts/`)
- **`scripts/run_pipeline.py`**: The master script that executes data generation, model training, and evaluation in one continuous flow.
- **`scripts/foolproof_retrain.py`**: A robust fallback script to quickly retrain models and regenerate essential artifacts if `models/` directory gets corrupted.
- **`scripts/run_preset_benchmark.py`**: Evaluates DAHS specifically on the scenarios defined in `src/presets.py` and caches results.
- **`scripts/hf_runner.py`**: Integration for running the heavy training pipeline on Hugging Face cloud compute.
- **`scripts/calibrate_real_data.py`**: Pipeline for calibrating the simulation parameters against real-world warehouse dataset distributions.

### 🖥️ Frontend (`website/`)
Built with React, Vite, and Tailwind CSS.
- **`website/src/main.jsx` & `App.jsx`**: React entry points and routing definitions.
- **Pages (`website/src/pages/`)**:
  - `Landing.jsx`: Hero page introducing the tool.
  - `Overview.jsx`: Executive summary of how DAHS works and business impact.
  - `Simulation.jsx`: The crown jewel. Provides a dual-pane live visualization (Baseline vs. DAHS), parameter controls, and live ML decision logs.
  - `Interpretability.jsx`: "Glass-box" ML view showing SHAP values, feature importance, and interactive decision trees.
  - `Results.jsx`: Displays the pre-computed benchmark charts, win-rates, and statistical tests.
  - `Methodology.jsx`: Academic explanation of the operations research formulas and ML architecture.
- **Components (`website/src/components/`)**: Reusable UI elements (`Navbar.jsx`, `Footer.jsx`, `MetaSelectorAnimation.jsx`, etc.).

### 📁 Artifact Directories
- **`models/`**: Stores serialized models (`.joblib`), feature lists, and the decision tree structure.
- **`results/`**: Stores benchmarking metrics, statistical test JSONs, and matplotlib evaluation plots.
- **`data/`**: Stores raw generated CSVs from `data_generator.py`.

---

## ⚙️ How the Architecture Works (Execution Flow)

1. **Initialization**: Running `python start.py` spawns Uvicorn, which loads `server.py`. The server loads `.joblib` models from `models/` into memory.
2. **Frontend Request**: The React frontend opens and the user navigates to the Simulation tab. They tweak sliders (Breakdown Probability, Load, etc.) and hit "Run Simulation".
3. **WebSocket Streaming**: React opens a WebSocket to `ws://localhost:8000/ws/simulate`. The backend spins up a ThreadPool executor to avoid blocking the async loop.
4. **Parallel Simulation**: Two `WarehouseSimulator` instances are initialized with the identical random seed:
   - **Baseline Arm**: Fixed to a single heuristic (e.g., FIFO or WSPT) for the full 600 minutes.
   - **DAHS Arm**: Uses `_BatchwiseSessionSelector`. Every 15 simulation minutes, it queries `FeatureExtractor`, passes the 24-feature vector to the XGBoost Meta-Selector, and switches to the predicted best heuristic (e.g., switching to Critical Ratio when machines break down).
5. **Real-time Feedback**: Every 2 simulation seconds, `server.py` captures a state snapshot (queues, machines, tardiness metrics) and streams it over the WebSocket.
6. **Visualization**: React parses the WebSocket JSON frames to animate the queues and render the ML evaluation log in plain English ("*Switched to Critical-Ratio because 2 stations are broken*").

## 🚀 Getting Started

1. Install Python 3.9+ and run: `pip install -r requirements.txt`
2. Build frontend (optional, if modifying UI): `cd website && npm install && npm run build`
3. Launch app: `python start.py`
4. Visit `http://localhost:8000`
