"""HTTP client used by bank branches to communicate with peer branches."""

import time
from typing import Optional

import requests


class BranchCommunicationError(Exception):
    """Raised when a peer branch cannot complete a communication request."""


class BranchClient:
    """Sends idempotent HTTP messages to configured peer branch servers."""

    def __init__(
        self,
        branch_urls: dict[str, str],
        timeout: float = 3.0,
        max_retries: int = 2,
        retry_delay: float = 0.5,
    ):
        self.branch_urls = {
            branch_id: url.rstrip("/")
            for branch_id, url in branch_urls.items()
        }
        self.timeout = timeout
        self.max_retries = max_retries
        self.retry_delay = retry_delay

    def _url(self, branch_id: str, path: str) -> str:
        if branch_id not in self.branch_urls:
            raise BranchCommunicationError(f"Unknown branch: {branch_id}")
        return f"{self.branch_urls[branch_id]}/{path.lstrip('/')}"

    def request(
        self,
        method: str,
        branch_id: str,
        path: str,
        json: Optional[dict] = None,
        params: Optional[dict] = None,
    ) -> dict:
        """Send a request with bounded retries for network/server failures."""
        url = self._url(branch_id, path)
        last_error = None

        for attempt in range(self.max_retries + 1):
            try:
                response = requests.request(
                    method=method,
                    url=url,
                    json=json,
                    params=params,
                    timeout=self.timeout,
                )

                try:
                    body = response.json()
                except ValueError:
                    body = {"error": "Peer returned a non-JSON response"}

                if 200 <= response.status_code < 300:
                    return body

                # Client/business-rule errors should not be retried.
                if 400 <= response.status_code < 500:
                    raise BranchCommunicationError(
                        body.get("error", f"Peer rejected request with HTTP {response.status_code}")
                    )

                last_error = BranchCommunicationError(
                    body.get("error", f"Peer failed with HTTP {response.status_code}")
                )
            except (requests.Timeout, requests.ConnectionError) as exc:
                last_error = BranchCommunicationError(
                    f"Branch {branch_id} is unavailable: {exc}"
                )

            if attempt < self.max_retries:
                time.sleep(self.retry_delay * (attempt + 1))

        raise last_error or BranchCommunicationError(
            f"Communication with branch {branch_id} failed"
        )

    def get_status(self, branch_id: str) -> dict:
        return self.request("GET", branch_id, "/status")

    def get_transactions(self, branch_id: str, limit: int = 50) -> dict:
        return self.request(
            "GET", branch_id, "/transactions", params={"limit": limit}
        )

    def send_transfer(
        self,
        target_branch_id: str,
        source_branch_id: str,
        amount: int,
        tx_id: str,
    ) -> dict:
        return self.request(
            "POST",
            target_branch_id,
            "/internal/transfer-in",
            json={
                "source_branch_id": source_branch_id,
                "amount": amount,
                "tx_id": tx_id,
            },
        )

    def health_check_all(self, current_branch_id: Optional[str] = None) -> dict:
        results = {}
        for branch_id in self.branch_urls:
            if branch_id == current_branch_id:
                continue
            try:
                results[branch_id] = {
                    "online": True,
                    "status": self.get_status(branch_id),
                }
            except BranchCommunicationError as exc:
                results[branch_id] = {"online": False, "error": str(exc)}
        return results
