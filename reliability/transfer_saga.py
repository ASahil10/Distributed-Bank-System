"""Safe inter-branch transfers using a saga with a durable outbox.

Why this exists
---------------
The original coordinator credited the destination first and debited the source
second. If the source could not afford the transfer, the destination had
already been credited and money was created out of nothing.

How it works now
----------------
1. DEBIT + OUTBOX (one local SQLite transaction, BEGIN IMMEDIATE):
   The source checks its minimum reserve, subtracts the cash, and records a
   TRANSFER_OUT row with status PENDING. The PENDING row is the outbox: it is
   on disk, so it survives a crash of the source branch.
2. DELIVER:
   The source sends /internal/transfer-in to the destination with the same
   tx_id. The destination ignores duplicate tx_ids, so delivery can be retried
   any number of times without double crediting (at-least-once delivery +
   idempotent receiver = effectively exactly-once).
3. OUTCOME:
   - Destination accepts           -> PENDING becomes COMPLETED.
   - Destination rejects (HTTP 4xx) -> compensating action: PENDING becomes
                                       FAILED and the cash is put back.
   - Destination unreachable        -> stays PENDING. The recovery worker
                                       retries it until the peer is back.

Every status change is a conditional update ("... WHERE status = 'PENDING'"),
so if the request thread and the recovery worker race on the same transfer,
only one of them can complete or refund it.
"""

import threading
import uuid
from typing import Optional

from banking.database import BranchDatabase
from banking.service import BankingError
from communication.client import BranchClient, BranchCommunicationError, PeerRejectedError

PENDING = "PENDING"
COMPLETED = "COMPLETED"
FAILED = "FAILED"


class TransferSaga:
    def __init__(
        self,
        branch_id: str,
        db: BranchDatabase,
        client: BranchClient,
        detector=None,
    ):
        self.branch_id = branch_id
        self.db = db
        self.client = client
        self.detector = detector
        # In-memory delivery stats, only used for display on the dashboard.
        self._attempts: dict[str, int] = {}
        self._last_error: dict[str, str] = {}
        self._stats_lock = threading.Lock()

    # ------------------------------------------------------------------ public

    def start(self, target_branch_id: str, amount: int, tx_id: Optional[str] = None) -> dict:
        """Start a transfer. Returns the transfer with status COMPLETED, PENDING or FAILED."""
        if not target_branch_id or target_branch_id == self.branch_id:
            raise BankingError("target_branch_id must be a different branch.")
        if isinstance(amount, bool) or not isinstance(amount, int) or amount <= 0:
            raise BankingError("amount must be a positive integer in cents.")
        tx_id = tx_id or str(uuid.uuid4())

        record = self._debit_into_outbox(tx_id, target_branch_id, amount)
        if record["status"] != PENDING:
            # Same tx_id was already finished earlier (client retried). Idempotent.
            return self._result(record, duplicate=True)

        if self.detector is not None and self.detector.is_down(target_branch_id):
            # Don't make the teller wait on a branch we already know is down.
            self._note_error(tx_id, f"Branch {target_branch_id} is DOWN; queued for recovery")
            return self._result(self._get(tx_id))

        return self.deliver(tx_id)

    def deliver(self, tx_id: str) -> dict:
        """Try to deliver one PENDING transfer to its destination."""
        record = self._get(tx_id)
        if record is None:
            raise BankingError(f"Unknown transfer {tx_id}.")
        if record["status"] != PENDING:
            return self._result(record)

        with self._stats_lock:
            self._attempts[tx_id] = self._attempts.get(tx_id, 0) + 1

        try:
            self.client.send_transfer(
                target_branch_id=record["peer_branch_id"],
                source_branch_id=self.branch_id,
                amount=record["amount"],
                tx_id=tx_id,
            )
        except PeerRejectedError as exc:
            # Definite "no" from the destination: undo the debit.
            self._compensate(tx_id, str(exc))
        except BranchCommunicationError as exc:
            # Unknown outcome (timeout / connection refused / 5xx): keep it PENDING.
            # Safe to retry later because the destination deduplicates by tx_id.
            self._note_error(tx_id, str(exc))
        else:
            self._transition(tx_id, PENDING, COMPLETED, "Delivered")
            with self._stats_lock:
                self._last_error.pop(tx_id, None)

        return self._result(self._get(tx_id))

    def retry_pending(self, only_target: Optional[str] = None) -> list[dict]:
        """Retry every PENDING transfer (optionally only those to one branch)."""
        results = []
        for record in self.pending():
            target = record["peer_branch_id"]
            if only_target and target != only_target:
                continue
            if self.detector is not None and self.detector.is_down(target):
                continue
            results.append(self.deliver(record["tx_id"]))
        return results

    def pending(self) -> list[dict]:
        with self.db.get_connection() as conn:
            rows = conn.execute(
                """
                SELECT tx_id, amount, peer_branch_id, status, note, created_at
                FROM transactions
                WHERE tx_type = 'TRANSFER_OUT' AND status = ?
                ORDER BY id
                """,
                (PENDING,),
            ).fetchall()
        out = []
        for row in rows:
            item = dict(row)
            with self._stats_lock:
                item["attempts"] = self._attempts.get(item["tx_id"], 0)
                item["last_error"] = self._last_error.get(item["tx_id"])
            out.append(item)
        return out

    # ----------------------------------------------------------------- private

    def _debit_into_outbox(self, tx_id: str, target_branch_id: str, amount: int) -> dict:
        """Atomically check the reserve, debit the cash and write the PENDING outbox row."""
        with self.db.get_connection() as conn:
            # BEGIN IMMEDIATE takes SQLite's write lock now, so no other
            # withdrawal/transfer can read the same balance until we commit.
            conn.execute("BEGIN IMMEDIATE;")
            try:
                existing = conn.execute(
                    "SELECT tx_id, tx_type, amount, peer_branch_id, status FROM transactions WHERE tx_id = ?",
                    (tx_id,),
                ).fetchone()
                if existing:
                    conn.execute("COMMIT;")
                    if existing["tx_type"] != "TRANSFER_OUT":
                        raise BankingError(f"tx_id {tx_id} is already used by another transaction.")
                    return dict(existing)

                state = conn.execute(
                    "SELECT cash, minimum_reserve FROM branch_state WHERE branch_id = ?",
                    (self.branch_id,),
                ).fetchone()
                if not state:
                    raise BankingError(f"Branch {self.branch_id} state not found.")

                new_cash = state["cash"] - amount
                if new_cash < state["minimum_reserve"]:
                    raise BankingError("insufficient cash above minimum reserve")

                conn.execute(
                    "UPDATE branch_state SET cash = ?, updated_at = CURRENT_TIMESTAMP WHERE branch_id = ?",
                    (new_cash, self.branch_id),
                )
                conn.execute(
                    """
                    INSERT INTO transactions (tx_id, tx_type, amount, peer_branch_id, status, note)
                    VALUES (?, 'TRANSFER_OUT', ?, ?, ?, ?)
                    """,
                    (tx_id, amount, target_branch_id, PENDING, f"Transfer to branch {target_branch_id}"),
                )
                conn.execute("COMMIT;")
            except Exception:
                if conn.in_transaction:
                    conn.execute("ROLLBACK;")
                raise
        return {"tx_id": tx_id, "amount": amount, "peer_branch_id": target_branch_id, "status": PENDING}

    def _transition(self, tx_id: str, from_status: str, to_status: str, note: str) -> bool:
        with self.db.get_connection() as conn:
            conn.execute("BEGIN IMMEDIATE;")
            try:
                cur = conn.execute(
                    """
                    UPDATE transactions SET status = ?, note = ?
                    WHERE tx_id = ? AND tx_type = 'TRANSFER_OUT' AND status = ?
                    """,
                    (to_status, note, tx_id, from_status),
                )
                conn.execute("COMMIT;")
                return cur.rowcount == 1
            except Exception:
                conn.execute("ROLLBACK;")
                raise

    def _compensate(self, tx_id: str, reason: str) -> bool:
        """Mark the transfer FAILED and give the cash back, in one local transaction."""
        with self.db.get_connection() as conn:
            conn.execute("BEGIN IMMEDIATE;")
            try:
                row = conn.execute(
                    "SELECT amount FROM transactions WHERE tx_id = ? AND tx_type = 'TRANSFER_OUT' AND status = ?",
                    (tx_id, PENDING),
                ).fetchone()
                if row is None:
                    conn.execute("COMMIT;")
                    return False  # someone else already finished it
                conn.execute(
                    "UPDATE transactions SET status = ?, note = ? WHERE tx_id = ?",
                    (FAILED, f"Refunded: destination rejected ({reason})", tx_id),
                )
                conn.execute(
                    "UPDATE branch_state SET cash = cash + ?, updated_at = CURRENT_TIMESTAMP WHERE branch_id = ?",
                    (row["amount"], self.branch_id),
                )
                conn.execute("COMMIT;")
                return True
            except Exception:
                conn.execute("ROLLBACK;")
                raise

    def _get(self, tx_id: str) -> Optional[dict]:
        with self.db.get_connection() as conn:
            row = conn.execute(
                """
                SELECT tx_id, amount, peer_branch_id, status, note
                FROM transactions WHERE tx_id = ? AND tx_type = 'TRANSFER_OUT'
                """,
                (tx_id,),
            ).fetchone()
        return dict(row) if row else None

    def _note_error(self, tx_id: str, message: str):
        with self._stats_lock:
            self._last_error[tx_id] = message

    def _result(self, record: dict, duplicate: bool = False) -> dict:
        tx_id = record["tx_id"]
        result = {
            "tx_id": tx_id,
            "source_branch_id": self.branch_id,
            "target_branch_id": record["peer_branch_id"],
            "amount": record["amount"],
            "status": record["status"],
        }
        if duplicate:
            result["duplicate"] = True
        if record.get("note"):
            result["note"] = record["note"]
        with self._stats_lock:
            if record["status"] == PENDING and tx_id in self._last_error:
                result["last_error"] = self._last_error[tx_id]
        return result
