"""Heartbeat-based failure detector.

Each branch pings every peer's GET /health on a fixed interval. A peer moves
through three states based on consecutive missed heartbeats:

    ONLINE     -> answered the last heartbeat
    SUSPECTED  -> missed at least `suspect_after` heartbeats in a row
    DOWN       -> missed at least `down_after` heartbeats in a row

Using a SUSPECTED state instead of jumping straight to DOWN avoids declaring
a branch dead because of one slow or dropped packet (a classic trade-off
between detection speed and false positives).

Each /health reply carries the peer's `started_at` time. If it changes, the
peer crashed and restarted between two heartbeats, which also counts as a
recovery event even if we never saw it go DOWN.

When a peer recovers, `on_recover(peer_id)` is called so the recovery worker
can immediately flush transfers that were waiting for that branch.
"""

import threading
import time
from typing import Callable, Optional

import requests

ONLINE = "ONLINE"
SUSPECTED = "SUSPECTED"
DOWN = "DOWN"
UNKNOWN = "UNKNOWN"


class FailureDetector:
    def __init__(
        self,
        branch_id: str,
        branch_urls: dict[str, str],
        interval: float = 2.0,
        timeout: float = 1.0,
        suspect_after: int = 1,
        down_after: int = 3,
        on_recover: Optional[Callable[[str], None]] = None,
    ):
        self.branch_id = branch_id
        self.peers = {
            peer: url.rstrip("/") for peer, url in branch_urls.items() if peer != branch_id
        }
        self.interval = interval
        self.timeout = timeout
        self.suspect_after = suspect_after
        self.down_after = down_after
        self.on_recover = on_recover

        self._lock = threading.Lock()
        self._state = {
            peer: {
                "state": UNKNOWN,
                "missed": 0,
                "last_seen": None,
                "started_at": None,
                "last_error": None,
                "changed_at": time.time(),
            }
            for peer in self.peers
        }
        self._stop = threading.Event()
        self._thread: Optional[threading.Thread] = None

    # --------------------------------------------------------------- queries

    def state(self, peer: str) -> str:
        with self._lock:
            return self._state.get(peer, {}).get("state", UNKNOWN)

    def is_down(self, peer: str) -> bool:
        return self.state(peer) == DOWN

    def snapshot(self) -> dict:
        with self._lock:
            return {peer: dict(info) for peer, info in self._state.items()}

    # ------------------------------------------------------------- heartbeat

    def check_once(self):
        """Ping every peer once and update its state."""
        for peer, url in self.peers.items():
            try:
                resp = requests.get(f"{url}/health", timeout=self.timeout)
                resp.raise_for_status()
                body = resp.json()
                self._record_success(peer, body.get("started_at"))
            except Exception as exc:  # timeout, refused, bad JSON, 5xx...
                self._record_failure(peer, str(exc))

    def _record_success(self, peer: str, started_at):
        recovered = False
        with self._lock:
            info = self._state[peer]
            was = info["state"]
            restarted = info["started_at"] is not None and started_at != info["started_at"]
            recovered = was in (SUSPECTED, DOWN) or restarted
            if was != ONLINE:
                info["changed_at"] = time.time()
            info.update(
                state=ONLINE,
                missed=0,
                last_seen=time.time(),
                started_at=started_at,
                last_error=None,
            )
        if recovered and self.on_recover:
            self.on_recover(peer)

    def _record_failure(self, peer: str, error: str):
        with self._lock:
            info = self._state[peer]
            info["missed"] += 1
            info["last_error"] = error
            if info["missed"] >= self.down_after:
                new_state = DOWN
            elif info["missed"] >= self.suspect_after:
                new_state = SUSPECTED
            else:
                new_state = info["state"]
            if new_state != info["state"]:
                info["changed_at"] = time.time()
            info["state"] = new_state

    # -------------------------------------------------------------- lifecycle

    def start(self):
        if self._thread and self._thread.is_alive():
            return
        self._stop.clear()
        self._thread = threading.Thread(target=self._run, name="failure-detector", daemon=True)
        self._thread.start()

    def stop(self):
        self._stop.set()

    def _run(self):
        while not self._stop.is_set():
            self.check_once()
            self._stop.wait(self.interval)
