"""HF Space wrapper around scripts/run_pipeline.py.

Hardened for the "runtime ended → models gone" failure mode:
  * Background HubPersistor uploads every 5 min (started by run_pipeline).
  * SIGTERM/SIGINT handlers do a final upload before exit.
  * `atexit` fallback if the OS kills us via SIGKILL after a SIGTERM warning.
  * `pip freeze` and `run_manifest.json` written for reproducibility.
  * Resilient: pipeline failure still triggers a best-effort artifact upload.

Required Space env vars (Settings → Variables and secrets):
  HF_TOKEN  — fine-grained token with WRITE access to the model repo
  REPO_ID   — target model repo, e.g. "your-username/DAHS-Models"
  SPACE_ID  — (optional) "your-username/your-space-name" for auto-pause
"""
from __future__ import annotations

import http.server
import os
import socketserver
import subprocess
import sys
import threading
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).parent.parent
sys.path.insert(0, str(ROOT))

HF_TOKEN = os.environ.get("HF_TOKEN")
REPO_ID = os.environ.get("REPO_ID")
SPACE_ID = os.environ.get("SPACE_ID")  # set automatically inside a Space

# CPU-upgrade tier: 16 vCPUs. The pipeline is multiprocessing-bound, so we
# leave 1 core for the periodic uploader thread and use the rest for sims.
CPU_COUNT = os.cpu_count() or 8
WORKERS = str(max(2, CPU_COUNT - 1))

# Q1 budget: 5000 scenarios → ~300k labeled snapshots; 1000 eval seeds
# (Friedman + Nemenyi over 1000 paired observations is well into asymptotic
# regime; Wilcoxon power on this n is essentially saturated).
SCENARIOS = os.environ.get("DAHS_SCENARIOS", "5000")
EVAL_SEEDS = os.environ.get("DAHS_EVAL_SEEDS", "1000")


def main() -> int:
    print("--- DAHS_2 HF RUNNER STARTING ---")
    print(f"Time : {datetime.now(timezone.utc).isoformat()}")
    print(f"CPUs : {CPU_COUNT}, workers={WORKERS}")
    print(f"Repo : {REPO_ID}")
    print(f"Space: {SPACE_ID}")

    if not HF_TOKEN or not REPO_ID:
        print("[FATAL] HF_TOKEN and REPO_ID env vars are required.")
        print("        Settings → Variables and secrets → add both.")
        return 1

    # Verify Hub access before burning compute.
    from src.hf_persistence import HubPersistor
    persistor = HubPersistor(repo_id=REPO_ID, token=HF_TOKEN)
    persistor.install_signal_handlers()
    persistor.install_atexit()
    persistor.start_periodic(interval_seconds=300)

    # Trick HF Space health check (port 7860 must respond to be "Running").
    def _start_dummy_server():
        try:
            handler = http.server.SimpleHTTPRequestHandler
            with socketserver.TCPServer(("", 7860), handler) as httpd:
                httpd.serve_forever()
        except Exception as e:  # noqa: BLE001
            print(f"[warn] dummy health server failed: {e}")

    threading.Thread(target=_start_dummy_server, daemon=True).start()
    print("[ok] dummy health server on :7860")

    print(
        f"\n--- PIPELINE: {SCENARIOS} scenarios, {EVAL_SEEDS} eval seeds, "
        f"{WORKERS} workers ---"
    )
    cmd = [
        sys.executable, "scripts/run_pipeline.py",
        "--scenarios",  SCENARIOS,
        "--eval-seeds", EVAL_SEEDS,
        "--workers",    WORKERS,
    ]

    rc = 1
    try:
        result = subprocess.run(cmd, cwd=str(ROOT))
        rc = result.returncode
    except Exception as e:  # noqa: BLE001
        print(f"[FATAL] pipeline subprocess raised: {e}")

    status = "SUCCESS" if rc == 0 else f"FAILED (exit {rc})"
    (ROOT / "results").mkdir(exist_ok=True)
    (ROOT / "results" / "run_status.txt").write_text(
        f"{status}\n{datetime.now(timezone.utc).isoformat()}\n",
        encoding="utf-8",
    )

    # Always do a final consolidated upload, success or fail.
    print("\n--- FINAL UPLOAD ---")
    persistor.stop_periodic()
    persistor.snapshot(msg=f"runner_final_{status.split()[0]}")

    # Pause the Space to stop billing — only after final upload.
    target_space = SPACE_ID
    if not target_space:
        print("[warn] SPACE_ID not set; skipping auto-pause. Pause manually in Settings.")
    else:
        try:
            persistor.api.pause_space(repo_id=target_space)
            print(f"[ok] paused {target_space}")
        except Exception as e:  # noqa: BLE001
            print(f"[warn] auto-pause failed: {e} — pause manually to stop billing.")

    return rc


if __name__ == "__main__":
    sys.exit(main())
