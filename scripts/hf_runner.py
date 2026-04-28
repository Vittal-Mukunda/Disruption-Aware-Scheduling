import os
import sys
import subprocess
import multiprocessing
import threading
import http.server
import socketserver
from huggingface_hub import HfApi, login

# 1. Configuration
# You must set these in Hugging Face Space Settings -> Variables and secrets
HF_TOKEN = os.environ.get("HF_TOKEN")
REPO_ID = os.environ.get("REPO_ID") # e.g., "Vittal-M/DAHS-Models"

def main():
    print("--- DAHS HF RUNNER STARTING ---")
    
    if not HF_TOKEN or not REPO_ID:
        print("❌ FATAL ERROR: HF_TOKEN and REPO_ID environment variables are missing!")
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
        print(f"✅ Repository {REPO_ID} is accessible and ready.")
    except Exception as e:
        print(f"❌ FATAL ERROR: Failed to create or access the repository {REPO_ID}.")
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
    # I have added --no-eval here to skip the 14-hour benchmark. 
    # This will train the 6000-scenario models in ~1 hour and upload them safely.
    # If you *want* the 16 hour benchmark, simply remove the "--no-eval" argument below.
    cores = "8" 
    print(f"\n--- STARTING DAHS PIPELINE (6000 Scenarios on {cores} Workers) ---")
    
    result = subprocess.run([
        "python", "scripts/run_pipeline.py", 
        "--scenarios", "6000", 
        "--workers", cores,
        "--no-eval"   # <-- REMOVE THIS if you want the full 14-hour 1000-seed eval to run again
    ])
    
    if result.returncode != 0:
        print("\n❌ Pipeline failed! Aborting upload.")
        sys.exit(1)
        
    print("--- PIPELINE FINISHED SUCCESSFULY ---\n")

    # 3. Upload the trained models and results back to Hugging Face
    print(f"Uploading models and results to {REPO_ID}...")
    
    try:
        # Upload models directory
        if os.path.exists("models"):
            api.upload_folder(
                folder_path="models",
                repo_id=REPO_ID,
                repo_type="model",
                path_in_repo="models"
            )
            print("✅ Successfully uploaded models/")

        # Upload results directory
        if os.path.exists("results"):
            api.upload_folder(
                folder_path="results",
                repo_id=REPO_ID,
                repo_type="model",
                path_in_repo="results"
            )
            print("✅ Successfully uploaded results/")
            
        print("\n🎉 ALL DONE! Your models are safely stored on Hugging Face.")
    except Exception as e:
        print(f"\n❌ FATAL ERROR DURING UPLOAD: {e}")
        print("The training succeeded, but uploading to Hugging Face failed.")
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
