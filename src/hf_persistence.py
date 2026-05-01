"""hf_persistence.py — Bulletproof Hugging Face Hub persistence for DAHS_2.

Why this module exists
----------------------
Two prior HF Space runs lost every artifact when the runtime terminated. The
fix is a layered, redundant uploader:

  1. Incremental: every pipeline step (data gen, each model, evaluation)
     calls ``persistor.snapshot(folder)`` immediately after writing files.
  2. Periodic: a background thread re-uploads the full ``data/``, ``models/``,
     ``results/`` tree every N seconds so even mid-step crashes lose at most
     one period of work.
  3. Terminal: an ``atexit`` handler and a ``SIGTERM`` handler do a final
     full upload before the process dies. HF Spaces send SIGTERM on pause /
     hardware reclaim, so this is the path that catches "runtime ended"
     deletions.
  4. Resilient: every ``api.upload_folder`` call is retried with exponential
     backoff and is wrapped so a transient Hub error never stops the run.

Public API
----------
HubPersistor(repo_id, token, folders=("data", "models", "results"))
  .snapshot(folder=None, msg=None)        # one-shot upload
  .start_periodic(interval_seconds=300)   # background uploader thread
  .stop_periodic()
  .install_signal_handlers()              # SIGTERM/SIGINT -> final upload
  .install_atexit()                       # final upload at interpreter exit
"""

from __future__ import annotations

import atexit
import logging
import os
import signal
import threading
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Iterable, Optional

logger = logging.getLogger(__name__)

DEFAULT_FOLDERS = ("data", "models", "results", "logs")


class HubPersistor:
    """Layered, retry-armoured uploader to a Hugging Face model repo."""

    def __init__(
        self,
        repo_id: str,
        token: Optional[str] = None,
        folders: Iterable[str] = DEFAULT_FOLDERS,
        repo_type: str = "model",
        max_retries: int = 4,
        retry_base_delay: float = 2.0,
    ) -> None:
        from huggingface_hub import HfApi, login

        self.repo_id = repo_id
        self.repo_type = repo_type
        self.folders = tuple(folders)
        self.max_retries = max_retries
        self.retry_base_delay = retry_base_delay

        if token:
            try:
                login(token=token, add_to_git_credential=False)
            except Exception as e:  # noqa: BLE001
                logger.warning("hf login() raised %s — proceeding with HfApi(token=...)", e)
        self.api = HfApi(token=token) if token else HfApi()

        try:
            self.api.create_repo(
                repo_id=repo_id, repo_type=repo_type, exist_ok=True
            )
        except Exception as e:  # noqa: BLE001
            # We don't raise here: the caller may want to keep running locally
            # even if the Hub is unreachable. Subsequent uploads will retry.
            logger.error("create_repo(%s) failed: %s", repo_id, e)

        self._lock = threading.Lock()
        self._stop = threading.Event()
        self._thread: Optional[threading.Thread] = None
        self._signals_installed = False
        self._atexit_installed = False
        self._last_upload_ts: float = 0.0

    # ------------------------------------------------------------------
    # Core upload
    # ------------------------------------------------------------------

    def snapshot(self, folder: Optional[str] = None, msg: Optional[str] = None) -> bool:
        """Upload one folder (or all configured folders). Never raises."""
        targets = (folder,) if folder else self.folders
        commit_msg = msg or f"DAHS_2 snapshot {datetime.now(timezone.utc).isoformat()}"
        any_ok = False
        with self._lock:
            for f in targets:
                if not f or not Path(f).exists():
                    continue
                ok = self._upload_with_retry(f, commit_msg)
                any_ok = any_ok or ok
            self._last_upload_ts = time.time()
        return any_ok

    def _upload_with_retry(self, folder: str, commit_msg: str) -> bool:
        delay = self.retry_base_delay
        for attempt in range(1, self.max_retries + 1):
            try:
                self.api.upload_folder(
                    folder_path=folder,
                    repo_id=self.repo_id,
                    repo_type=self.repo_type,
                    path_in_repo=folder,
                    commit_message=f"{commit_msg} [{folder}]",
                )
                logger.info("[hub] uploaded %s/ -> %s", folder, self.repo_id)
                return True
            except Exception as e:  # noqa: BLE001
                logger.warning(
                    "[hub] upload %s/ attempt %d/%d failed: %s",
                    folder, attempt, self.max_retries, e,
                )
                if attempt == self.max_retries:
                    return False
                time.sleep(delay)
                delay *= 2
        return False

    # ------------------------------------------------------------------
    # Single-file upload (fast path for tiny artifacts)
    # ------------------------------------------------------------------

    def upload_file(self, local_path: str, path_in_repo: Optional[str] = None) -> bool:
        if not Path(local_path).exists():
            return False
        target = path_in_repo or local_path
        for attempt in range(1, self.max_retries + 1):
            try:
                self.api.upload_file(
                    path_or_fileobj=local_path,
                    path_in_repo=target,
                    repo_id=self.repo_id,
                    repo_type=self.repo_type,
                    commit_message=f"upload {target}",
                )
                logger.info("[hub] uploaded file %s", target)
                return True
            except Exception as e:  # noqa: BLE001
                logger.warning("[hub] upload_file %s attempt %d failed: %s", target, attempt, e)
                if attempt == self.max_retries:
                    return False
                time.sleep(self.retry_base_delay * attempt)
        return False

    # ------------------------------------------------------------------
    # Background periodic uploader
    # ------------------------------------------------------------------

    def start_periodic(self, interval_seconds: int = 300) -> None:
        if self._thread is not None and self._thread.is_alive():
            return
        self._stop.clear()

        def _loop() -> None:
            logger.info("[hub] periodic uploader started (every %ds)", interval_seconds)
            while not self._stop.wait(interval_seconds):
                try:
                    self.snapshot(msg="periodic")
                except Exception as e:  # noqa: BLE001
                    logger.warning("[hub] periodic snapshot raised: %s", e)
            logger.info("[hub] periodic uploader stopped")

        self._thread = threading.Thread(target=_loop, name="HubPersistor", daemon=True)
        self._thread.start()

    def stop_periodic(self) -> None:
        self._stop.set()
        if self._thread is not None:
            self._thread.join(timeout=10)

    # ------------------------------------------------------------------
    # Terminal handlers
    # ------------------------------------------------------------------

    def install_atexit(self) -> None:
        if self._atexit_installed:
            return
        atexit.register(self._final_upload, "atexit")
        self._atexit_installed = True

    def install_signal_handlers(self) -> None:
        if self._signals_installed:
            return

        def _handler(signum, frame):  # noqa: ARG001
            logger.warning("[hub] signal %s received — final upload then exit", signum)
            self._final_upload(f"signal_{signum}")
            os._exit(0)  # bypass other atexit hooks; we already saved

        for sig in (signal.SIGTERM, signal.SIGINT):
            try:
                signal.signal(sig, _handler)
            except (ValueError, OSError):
                # Not running in main thread (some HF runners) — ignore.
                pass
        self._signals_installed = True

    def _final_upload(self, reason: str) -> None:
        try:
            logger.info("[hub] final upload triggered by %s", reason)
            self.stop_periodic()
            self.snapshot(msg=f"final-{reason}")
        except Exception as e:  # noqa: BLE001
            logger.error("[hub] final upload failed: %s", e)


# ---------------------------------------------------------------------------
# Helper: build a persistor from environment, or return a no-op stub.
# ---------------------------------------------------------------------------


class _NullPersistor:
    """Drop-in replacement when no HF credentials are configured."""

    def snapshot(self, *args, **kwargs) -> bool:  # noqa: D401, ARG002
        return False

    def upload_file(self, *args, **kwargs) -> bool:  # noqa: ARG002
        return False

    def start_periodic(self, *args, **kwargs) -> None:  # noqa: ARG002
        return None

    def stop_periodic(self) -> None:
        return None

    def install_atexit(self) -> None:
        return None

    def install_signal_handlers(self) -> None:
        return None


def from_env(require: bool = False):
    """Build a HubPersistor from HF_TOKEN + REPO_ID env vars.

    If ``require`` is False and either var is missing, returns a NullPersistor
    so callers can use the API unconditionally during local runs.
    """
    token = os.environ.get("HF_TOKEN")
    repo_id = os.environ.get("REPO_ID")
    if not token or not repo_id:
        if require:
            raise RuntimeError("HF_TOKEN and REPO_ID env vars are required.")
        logger.info("[hub] HF_TOKEN/REPO_ID not set — Hub persistence disabled.")
        return _NullPersistor()
    return HubPersistor(repo_id=repo_id, token=token)
