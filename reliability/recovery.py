"""Background recovery worker.

Keeps retrying PENDING transfers (the outbox) until they are delivered:

- once at startup, so transfers left PENDING by a crash of THIS branch resume
  as soon as it comes back up;
- immediately when the failure detector reports that a peer recovered;
- every `interval` seconds as a safety net.
"""

import threading
from typing import Optional


class RecoveryWorker:
    def __init__(self, saga, interval: float = 5.0):
        self.saga = saga
        self.interval = interval
        self._wake = threading.Event()
        self._stop = threading.Event()
        self._thread: Optional[threading.Thread] = None
        self.last_run_results: list[dict] = []

    def trigger(self, peer_id: Optional[str] = None):
        """Ask the worker to run now (called by the failure detector on recovery)."""
        self._wake.set()

    def run_once(self) -> list[dict]:
        try:
            self.last_run_results = self.saga.retry_pending()
        except Exception as exc:  # never let the worker thread die
            self.last_run_results = [{"error": str(exc)}]
        return self.last_run_results

    def start(self):
        if self._thread and self._thread.is_alive():
            return
        self._stop.clear()
        self._thread = threading.Thread(target=self._run, name="recovery-worker", daemon=True)
        self._thread.start()

    def stop(self):
        self._stop.set()
        self._wake.set()

    def _run(self):
        while not self._stop.is_set():
            self.run_once()
            self._wake.wait(self.interval)
            self._wake.clear()
