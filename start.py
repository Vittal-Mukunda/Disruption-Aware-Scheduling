#!/usr/bin/env python3
"""
start.py — Launch the DAHS_2 app (backend + frontend, single server)
Usage:  python start.py
Then open: http://localhost:8000
"""
import shutil
import subprocess
import sys
import time
import webbrowser
from pathlib import Path

ROOT = Path(__file__).parent.resolve()
PORT = 8000

PYTHON_CANDIDATES = [
    p for p in [
        sys.executable,
        shutil.which("python3"),
        shutil.which("python"),
    ] if p
]


def find_python() -> str:
    for py in PYTHON_CANDIDATES:
        p = Path(py)
        if not p.exists():
            continue
        result = subprocess.run(
            [str(p), "-c", "import fastapi, uvicorn"],
            capture_output=True, timeout=5
        )
        if result.returncode == 0:
            return str(p)
    return sys.executable


def main() -> None:
    python = find_python()
    print(f"\n  DAHS 2.0 — Disruption-Aware Hybrid Scheduler")
    print(f"  Using Python: {python}\n")

    proc = subprocess.Popen(
        [python, "-m", "uvicorn", "server:app",
         "--host", "0.0.0.0", "--port", str(PORT),
         "--ws-max-size", "16777216"],
        cwd=str(ROOT),
    )

    print(f"  Starting server…")
    time.sleep(3)

    if proc.poll() is not None:
        print(f"\n  ERROR: Server exited immediately (code {proc.returncode}).")
        print(f"  Try running manually:\n")
        print(f"    {python} -m uvicorn server:app --port {PORT}\n")
        sys.exit(1)

    url = f"http://localhost:{PORT}"
    print(f"  Website: {url}")
    print(f"  API:     {url}/health")
    print(f"\n  Opening browser… (Press Ctrl+C to stop)\n")
    webbrowser.open(url)

    try:
        proc.wait()
    except KeyboardInterrupt:
        print("\n  Shutting down…")
        proc.terminate()
        try:
            proc.wait(timeout=5)
        except subprocess.TimeoutExpired:
            proc.kill()
        print("  Done.")


if __name__ == "__main__":
    main()
