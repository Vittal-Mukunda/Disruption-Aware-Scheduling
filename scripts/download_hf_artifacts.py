import os
from huggingface_hub import snapshot_download

# Replace this with the REPO_ID you set in your Hugging Face Space
REPO_ID = "Vittal-M/DAHS-Models"  # <-- CHANGE THIS IF DIFFERENT

print(f"Downloading artifacts from {REPO_ID}...")
snapshot_download(
    repo_id=REPO_ID,
    repo_type="model",
    local_dir=".",
    allow_patterns=["models/*", "results/*", "data/*"]
)
print("Download complete! Your local 'models', 'results', and 'data' folders are now fully synced.")
