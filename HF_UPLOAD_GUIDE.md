# DAHS_2 — Hugging Face Space Upload & Run Guide

End-to-end procedure to run the Q1 training pipeline on a Hugging Face Space
with bulletproof artifact persistence to a Hub model repo.

---

## 0. Recommended hardware tier

This project is **CPU-bound** (SimPy + scikit-learn + XGBoost on tabular data).
Do **NOT** select a GPU tier — it will burn your credits at 5–10× the cost
without any speedup.

| Tier                    | Approx $/hr | Pipeline time (5000 scen, 1000 eval seeds) |
|-------------------------|-------------|---------------------------------------------|
| **CPU upgrade (16 vCPU, 64 GB)**   | **~$0.05–0.10** | **~2–4 h** ← recommended       |
| CPU basic (2 vCPU, 16 GB) | free      | ~12 h (works, just slow)                    |
| Any GPU                  | $1+/hr     | identical wall time, all GPUs idle          |

At 16 vCPU you should finish a full Q1 run for **well under $1** of your $23.

---

## 1. Files to upload to the Space

Upload the **entire repository tree below**. Do NOT upload `__pycache__/`,
`.pytest_cache/`, `.git/`, `node_modules/`, `website/dist/`, or local
`models/`/`data/`/`results/` folders — those are produced by the run and
pushed to the model repo automatically.

```
DAHS_2/
├── Dockerfile
├── requirements.txt
├── README.md
├── HF_UPLOAD_GUIDE.md
├── server.py               # only needed if you also serve the demo from the Space
├── start.py
├── src/
│   ├── __init__.py
│   ├── data_generator.py
│   ├── evaluator.py
│   ├── features.py
│   ├── heuristics.py
│   ├── hf_persistence.py        ← new — bulletproof Hub uploader
│   ├── hybrid_scheduler.py
│   ├── presets.py
│   ├── references.py
│   ├── simulator.py
│   ├── train_priority.py
│   └── train_selector.py
├── scripts/
│   ├── hf_runner.py             ← Space entrypoint (matches Dockerfile CMD)
│   ├── run_pipeline.py
│   ├── calibrate_real_data.py
│   ├── foolproof_retrain.py
│   ├── run_preset_benchmark.py
│   └── download_hf_artifacts.py
├── tests/                       # optional but small; keep for paper reproducibility
└── data/                        # only data/benchmarks/* if you have curated benchmarks;
                                 # data/raw/ is regenerated each run
```

The pipeline writes to and pushes the following to your **model repo**:

```
<your-username>/DAHS-Models/
├── data/raw/selector_dataset.csv
├── data/raw/priority_dataset.csv
├── models/selector_dt.joblib
├── models/selector_rf.joblib
├── models/selector_xgb.joblib
├── models/priority_gbr.joblib
├── models/feature_names.json
├── models/feature_ranges.json
├── models/dt_structure.json
├── results/run_manifest.json
├── results/pip_freeze.txt
├── results/run_status.txt
├── results/selector_metrics.json
├── results/selector_metrics_table.csv
├── results/priority_metrics.json
├── results/benchmark_results.csv
├── results/benchmark_summary.json
├── results/statistical_tests.json
├── results/switching_analysis.json
├── results/paper_summary_table.csv
└── results/plots/*.png
```

---

## 2. Create the model repo (one-time)

This is where artifacts go and **survive runtime termination**.

1. Go to https://huggingface.co/new — choose **Model**, not Space.
2. Owner: your username. Name: `DAHS-Models`. Visibility: your choice.
3. Click **Create repository**. Done — keep it empty; the run populates it.

Note the full id: `your-username/DAHS-Models`.

---

## 3. Create a fine-grained access token

1. https://huggingface.co/settings/tokens → **Create new token** → **Fine-grained**.
2. **Repository permissions** → click **Add repository** → select `your-username/DAHS-Models` → check **Write access to contents and discussions**.
3. (Optional) also grant **Manage repo** to the Space if you want auto-pause on completion.
4. Copy the token starting with `hf_…` — you'll paste it in step 5.

---

## 4. Create the Space

1. https://huggingface.co/new-space → name `DAHS-Training`.
2. **SDK**: Docker.
3. **Hardware**: pick **CPU upgrade** (16 vCPU, 64 GB RAM).
4. Visibility: your choice. Click **Create Space**.

---

## 5. Configure secrets (Space → Settings → Variables and secrets)

| Name        | Type   | Value                                           |
|-------------|--------|-------------------------------------------------|
| `HF_TOKEN`  | Secret | `hf_…` token from step 3                        |
| `REPO_ID`   | Variable | `your-username/DAHS-Models`                   |
| `SPACE_ID`  | Variable | `your-username/DAHS-Training` (auto-pause target) |
| `DAHS_SCENARIOS` | Variable (optional) | Override default 5000 scenarios |
| `DAHS_EVAL_SEEDS` | Variable (optional) | Override default 1000 eval seeds |

`SPACE_ID` controls auto-pause after the run; without it you must pause
manually to stop billing.

---

## 6. Push the code to the Space

From the project root, with your Hub credentials configured:

```bash
git lfs install                                    # only once per machine
git remote add space https://huggingface.co/spaces/your-username/DAHS-Training
git add Dockerfile requirements.txt src/ scripts/ tests/
git add README.md HF_UPLOAD_GUIDE.md server.py start.py
git commit -m "DAHS_2 Q1 pipeline"
git push space main
```

Alternatively, drag the files into the Space's web file browser. Either
way, the **Dockerfile** at the repo root is what the Space builds, and its
`CMD ["python", "scripts/hf_runner.py"]` is the entrypoint.

---

## 7. Watch the build and run

1. Space opens → **Logs** tab shows Docker build (3–5 min on first push).
2. Once the container starts you should see:
   ```
   --- DAHS_2 HF RUNNER STARTING ---
   CPUs : 16, workers=15
   Repo : your-username/DAHS-Models
   [hub] periodic uploader started (every 300s)
   [ok] dummy health server on :7860
   --- PIPELINE: 5000 scenarios, 1000 eval seeds, 15 workers ---
   ```
3. Within ~5 min the model repo should receive its first commit
   (`results/run_manifest.json` and `results/pip_freeze.txt`). Verify at
   `https://huggingface.co/your-username/DAHS-Models/commits/main`.
   **If no commit appears in 10 minutes — the token or REPO_ID is wrong.
   Stop the Space immediately and re-check step 3 / 5.**
4. New commits land every 5 minutes. Per-step commits (`selector_dataset`,
   `priority_dataset`, `selector_models`, `priority_model`, `evaluation`)
   land as each pipeline phase finishes.

Total expected wall time on 16 vCPU: **2–4 hours**.

---

## 8. After the run

* `results/run_status.txt` will read `SUCCESS` or `FAILED (exit N)`.
* The Space auto-pauses if `SPACE_ID` was set. Verify the **Status** badge
  shows `Paused` so you stop being billed.
* All artifacts are in `your-username/DAHS-Models`. Pull them locally with:
  ```bash
  python scripts/download_hf_artifacts.py
  ```
  or via:
  ```python
  from huggingface_hub import snapshot_download
  snapshot_download(repo_id="your-username/DAHS-Models",
                    local_dir="./pulled_artifacts")
  ```

---

## 9. What survives if the runtime is killed mid-run?

Three independent persistence layers protect against the previous "models
disappeared" failure:

| Layer | Trigger | What it uploads |
|-------|---------|------------------|
| **Per-step** | After each pipeline phase | The folder produced by that phase |
| **Periodic** | Every 5 min (background thread) | All of `data/`, `models/`, `results/`, `logs/` |
| **Terminal** | SIGTERM / SIGINT / `atexit` | Final consolidated upload |

Worst-case loss: ~5 min of work between periodic uploads, **never the whole
run**. Each upload is retried with exponential backoff (4 attempts) so a
flaky Hub call won't lose state.

---

## 10. Sanity-check checklist before clicking "Run"

Before you spend any credits, verify the local checks pass:

```bash
# from repo root
pip install -r requirements.txt
python -c "from src.hf_persistence import HubPersistor, from_env; print('OK')"
python -m pytest tests/ -q                 # unit tests
python scripts/run_pipeline.py --quick     # 50 scenarios, 20 eval seeds
                                           # finishes in ~2-3 minutes locally
```

If `--quick` produces `models/*.joblib`, `results/selector_metrics.json`,
`results/priority_metrics.json`, `results/benchmark_summary.json`, and
`results/paper_summary_table.csv`, the pipeline is verified end-to-end.
You can then push to the Space with confidence.

---

## 11. Re-running

To re-run with different scenario/seed counts without rebuilding:
1. Open the Space → **Settings → Variables and secrets**
2. Edit `DAHS_SCENARIOS` / `DAHS_EVAL_SEEDS`
3. **Restart Space** (not Factory rebuild — much faster)

Each re-run produces a new commit on the model repo, so you can compare
runs side-by-side without overwriting prior artifacts.
