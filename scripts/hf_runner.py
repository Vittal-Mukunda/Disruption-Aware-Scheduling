import os
import sys
import subprocess
import multiprocessing
import threading
import http.server
import socketserver
from datetime import datetime
from pathlib import Path
from huggingface_hub import HfApi, login

# 1. Configuration
# You must set these in Hugging Face Space Settings -> Variables and secrets
HF_TOKEN = os.environ.get("HF_TOKEN")
REPO_ID = os.environ.get("REPO_ID") # e.g., "Vittal-M/DAHS-Models"

def upload_artifacts(api: HfApi) -> None:
    """Upload data/, models/, results/ to REPO_ID. Best-effort — never raises."""
    print(f"Uploading artifacts to {REPO_ID}...")
    for folder in ("data", "models", "results"):
        if not os.path.exists(folder):
            print(f"[SKIP] {folder}/ does not exist")
            continue
        try:
            api.upload_folder(
                folder_path=folder,
                repo_id=REPO_ID,
                repo_type="model",
                path_in_repo=folder,
            )
            print(f"[SUCCESS] Uploaded {folder}/")
        except Exception as e:
            print(f"[ERROR] Failed to upload {folder}/: {e}")
    print("\n[DONE] Upload pass complete.")


def main():
    print("--- DAHS HF RUNNER STARTING ---")
    
    if not HF_TOKEN or not REPO_ID:
        print("[FATAL ERROR] HF_TOKEN and REPO_ID environment variables are missing!")
        print("Please go to Space Settings -> Variables and secrets, and add:")
        print("1. HF_TOKEN (Must be a Fine-grained token with 'Write' access to models)")
        print("2. REPO_ID (The exact name of the dataset/model repo, e.g., Vittal-M/DAHS-Models)")
        sys.exit(1)

    print(f"Logging into Hugging Face...")
    login(token=HF_TOKEN)
    api = HfApi()

    # 🚨 CRITICAL FIX: Fail FAST if the repo can't be created or accessed
    try:
        api.create_repo(repo_id=REPO_ID, repo_type="model", exist_ok=True)
        print(f"[SUCCESS] Repository {REPO_ID} is accessible and ready.")
    except Exception as e:
        print(f"[FATAL ERROR] Failed to create or access the repository {REPO_ID}.")
        print(f"Reason: {e}")
        print("ABORTING: We will not start the training to prevent wasting your time/credits.")
        sys.exit(1)

    # Trick Hugging Face Health Checks
    def start_dummy_server():
        Handler = http.server.SimpleHTTPRequestHandler
        with socketserver.TCPServer(("", 7860), Handler) as httpd:
            httpd.serve_forever()
    threading.Thread(target=start_dummy_server, daemon=True).start()
    print("Started dummy web server on port 7860 to bypass health check timeouts.")

    # 2. Run the heavy pipeline
    # Sized for Q1 results within ~12h compute budget on HF:
    #   2000 scenarios -> ~120k selector training rows
    #   500 eval seeds -> 4500 sims, plenty for Friedman/Nemenyi/Wilcoxon
    cores = "8"
    print(f"\n--- STARTING DAHS PIPELINE (2000 Scenarios, 500 Eval Seeds, {cores} Workers) ---")

    result = subprocess.run([
        "python", "scripts/run_pipeline.py",
        "--scenarios",  "2000",
        "--eval-seeds", "500",
        "--workers",    cores,
    ])

    status = "SUCCESS" if result.returncode == 0 else f"FAILED (exit {result.returncode})"
    Path("results").mkdir(exist_ok=True)
    (Path("results") / "run_status.txt").write_text(
        f"{status}\n{datetime.utcnow().isoformat()}Z\n"
    )

    if result.returncode == 0:
        print("--- PIPELINE FINISHED SUCCESSFULLY ---\n")
    else:
        print(f"\n[ERROR] Pipeline exited with code {result.returncode}. Uploading partial artifacts anyway.\n")

    # 3. Upload trained artifacts (always — even on partial failure)
    upload_artifacts(api)

    if result.returncode != 0:
        sys.exit(1)

    # 4. PAUSE THE SPACE TO SAVE CREDITS
    try:
        print("Pausing the Space to stop billing...")
        api.pause_space(repo_id=os.environ.get("SPACE_ID", REPO_ID))
    except Exception as e:
        print(f"Failed to pause space automatically: {e}")
        print("IMPORTANT: Please go to the Space Settings and pause it manually!")

if __name__ == "__main__":
    main()
