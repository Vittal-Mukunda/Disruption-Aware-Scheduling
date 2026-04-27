import os
import subprocess
from huggingface_hub import HfApi, login

# 1. Configuration
# We will pass the HF_TOKEN as an environment variable in the HF Job settings
HF_TOKEN = os.environ.get("HF_TOKEN")
REPO_ID = os.environ.get("REPO_ID") # e.g., "your-username/DAHS-Models"

def main():
    if not HF_TOKEN or not REPO_ID:
        print("ERROR: HF_TOKEN and REPO_ID environment variables must be set!")
        return

    print(f"Logging into Hugging Face...")
    login(token=HF_TOKEN)
    api = HfApi()

    # Make sure the repository exists
    try:
        api.create_repo(repo_id=REPO_ID, repo_type="model", exist_ok=True)
        print(f"Repository {REPO_ID} is ready.")
    except Exception as e:
        print(f"Failed to create/check repo: {e}")

    # 2. Run the heavy pipeline
    print("\n--- STARTING DAHS PIPELINE ---")
    # Using subprocess to run the pipeline exactly as you would locally
    result = subprocess.run(["python", "scripts/run_pipeline.py"])
    
    if result.returncode != 0:
        print("\nPipeline failed! Aborting upload.")
        return
    print("--- PIPELINE FINISHED SUCCESSFULY ---\n")

    # 3. Upload the trained models and results back to Hugging Face
    print(f"Uploading models and results to {REPO_ID}...")
    
    # Upload models directory
    if os.path.exists("models"):
        api.upload_folder(
            folder_path="models",
            repo_id=REPO_ID,
            repo_type="model",
            path_in_repo="models"
        )
        print("Successfully uploaded models/")

    # Upload results directory
    if os.path.exists("results"):
        api.upload_folder(
            folder_path="results",
            repo_id=REPO_ID,
            repo_type="model",
            path_in_repo="results"
        )
        print("Successfully uploaded results/")

    print("\nALL DONE! Your models are safely stored on Hugging Face.")

if __name__ == "__main__":
    main()
