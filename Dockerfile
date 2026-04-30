FROM python:3.12-slim

WORKDIR /app

# Copy the entire project
COPY . /app/

# Install requirements
RUN pip install --no-cache-dir -r requirements.txt
RUN pip install huggingface_hub>=0.20.0

# Run our wrapper script
CMD ["python", "scripts/hf_runner.py"]
