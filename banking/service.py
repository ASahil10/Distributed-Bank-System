"""Core banking business logic for deposits, withdrawals, transfers, reserves, and staffing."""

import uuid
from typing import Optional
from banking.database import BranchDatabase


class BankingError(Exception):
    """Raised when a banking operation fails validation or business rules."""


def _require_positive_int(value: int, field_name: str = "amount") -> int:
    if isinstance(value, bool) or not isinstance(value, int) or value <= 0:
        raise BankingError(f"{field_name} must be a positive integer in cents.")
    return value


def _require_non_negative_int(value: int, field_name: str = "employees") -> int:
    if isinstance(value, bool) or not isinstance(value, int) or value < 0:
        raise BankingError(f"{field_name} must be a non-negative integer.")
    return value


class BankingService:
    """Executes transactional banking operations against a branch's SQLite database."""

    def __init__(self, db: BranchDatabase):
        self.db = db

    def get_status(self) -> dict:
        with self.db.get_connection() as conn:
            row = conn.execute(
                """
                SELECT branch_id, cash, minimum_reserve, employees, updated_at
                FROM branch_state
                WHERE branch_id = ?
                """,
                (self.db.branch_id,),
            ).fetchone()
            if not row:
                raise BankingError(f"Branch {self.db.branch_id} is not initialized.")

            status = dict(row)
            status["reserve_warning"] = status["cash"] < status["minimum_reserve"]
            return status

    def get_transactions(self, limit: int = 50) -> list[dict]:
        limit = _require_positive_int(limit, "limit")
        with self.db.get_connection() as conn:
            rows = conn.execute(
                """
                SELECT id, tx_id, tx_type, amount, peer_branch_id, status, note, created_at
                FROM transactions
                ORDER BY id DESC
                LIMIT ?
                """,
                (limit,),
            ).fetchall()
            return [dict(r) for r in rows]

    def deposit(self, amount: int, tx_id: Optional[str] = None, note: str = "") -> dict:
        amount = _require_positive_int(amount, "amount")
        tx_id = tx_id or str(uuid.uuid4())

        with self.db.get_connection() as conn:
            conn.execute("BEGIN IMMEDIATE;")
            try:
                existing = conn.execute(
                    "SELECT tx_id FROM transactions WHERE tx_id = ?",
                    (tx_id,),
                ).fetchone()
                if existing:
                    row = conn.execute(
                        "SELECT cash, minimum_reserve FROM branch_state WHERE branch_id = ?",
                        (self.db.branch_id,),
                    ).fetchone()
                    conn.execute("COMMIT;")
                    return {
                        "tx_id": tx_id,
                        "duplicate": True,
                        "status": "COMPLETED",
                        "cash": row["cash"] if row else None,
                    }

                conn.execute(
                    """
                    UPDATE branch_state
                    SET cash = cash + ?, updated_at = CURRENT_TIMESTAMP
                    WHERE branch_id = ?
                    """,
                    (amount, self.db.branch_id),
                )
                conn.execute(
                    """
                    INSERT INTO transactions (tx_id, tx_type, amount, note)
                    VALUES (?, 'DEPOSIT', ?, ?)
                    """,
                    (tx_id, amount, note),
                )
                row = conn.execute(
                    "SELECT cash, minimum_reserve FROM branch_state WHERE branch_id = ?",
                    (self.db.branch_id,),
                ).fetchone()
                conn.execute("COMMIT;")

                return {
                    "tx_id": tx_id,
                    "type": "DEPOSIT",
                    "amount": amount,
                    "cash": row["cash"],
                    "reserve_warning": row["cash"] < row["minimum_reserve"],
                }
            except Exception:
                conn.execute("ROLLBACK;")
                raise

    def withdraw(
        self,
        amount: int,
        allow_below_reserve: bool = False,
        tx_id: Optional[str] = None,
        note: str = "",
    ) -> dict:
        amount = _require_positive_int(amount, "amount")
        tx_id = tx_id or str(uuid.uuid4())

        with self.db.get_connection() as conn:
            conn.execute("BEGIN IMMEDIATE;")
            try:
                existing = conn.execute(
                    "SELECT tx_id FROM transactions WHERE tx_id = ?",
                    (tx_id,),
                ).fetchone()
                if existing:
                    row = conn.execute(
                        "SELECT cash FROM branch_state WHERE branch_id = ?",
                        (self.db.branch_id,),
                    ).fetchone()
                    conn.execute("COMMIT;")
                    return {
                        "tx_id": tx_id,
                        "duplicate": True,
                        "status": "COMPLETED",
                        "cash": row["cash"] if row else None,
                    }

                state = conn.execute(
                    "SELECT cash, minimum_reserve FROM branch_state WHERE branch_id = ?",
                    (self.db.branch_id,),
                ).fetchone()
                if not state:
                    raise BankingError(f"Branch {self.db.branch_id} state not found.")

                new_cash = state["cash"] - amount
                if new_cash < 0:
                    raise BankingError("insufficient cash above minimum reserve")

                if not allow_below_reserve and new_cash < state["minimum_reserve"]:
                    raise BankingError("insufficient cash above minimum reserve")

                conn.execute(
                    """
                    UPDATE branch_state
                    SET cash = ?, updated_at = CURRENT_TIMESTAMP
                    WHERE branch_id = ?
                    """,
                    (new_cash, self.db.branch_id),
                )
                conn.execute(
                    """
                    INSERT INTO transactions (tx_id, tx_type, amount, note)
                    VALUES (?, 'WITHDRAWAL', ?, ?)
                    """,
                    (tx_id, amount, note),
                )
                conn.execute("COMMIT;")

                return {
                    "tx_id": tx_id,
                    "type": "WITHDRAWAL",
                    "amount": amount,
                    "cash": new_cash,
                    "reserve_warning": new_cash < state["minimum_reserve"],
                }
            except Exception:
                conn.execute("ROLLBACK;")
                raise

    def transfer_out(
        self,
        amount: int,
        target_branch_id: str,
        allow_below_reserve: bool = False,
        tx_id: Optional[str] = None,
    ) -> dict:
        if not target_branch_id or target_branch_id == self.db.branch_id:
            raise BankingError("target_branch_id must be a different branch.")
        amount = _require_positive_int(amount, "amount")
        tx_id = tx_id or str(uuid.uuid4())

        with self.db.get_connection() as conn:
            conn.execute("BEGIN IMMEDIATE;")
            try:
                existing = conn.execute(
                    "SELECT tx_id FROM transactions WHERE tx_id = ?",
                    (tx_id,),
                ).fetchone()
                if existing:
                    row = conn.execute(
                        "SELECT cash FROM branch_state WHERE branch_id = ?",
                        (self.db.branch_id,),
                    ).fetchone()
                    conn.execute("COMMIT;")
                    return {
                        "tx_id": tx_id,
                        "duplicate": True,
                        "status": "COMPLETED",
                        "cash": row["cash"] if row else None,
                    }

                state = conn.execute(
                    "SELECT cash, minimum_reserve FROM branch_state WHERE branch_id = ?",
                    (self.db.branch_id,),
                ).fetchone()
                if not state:
                    raise BankingError(f"Branch {self.db.branch_id} state not found.")

                new_cash = state["cash"] - amount
                if new_cash < 0 or (not allow_below_reserve and new_cash < state["minimum_reserve"]):
                    raise BankingError("insufficient cash above minimum reserve")

                conn.execute(
                    """
                    UPDATE branch_state
                    SET cash = ?, updated_at = CURRENT_TIMESTAMP
                    WHERE branch_id = ?
                    """,
                    (new_cash, self.db.branch_id),
                )
                conn.execute(
                    """
                    INSERT INTO transactions (tx_id, tx_type, amount, peer_branch_id, note)
                    VALUES (?, 'TRANSFER_OUT', ?, ?, ?)
                    """,
                    (tx_id, amount, target_branch_id, f"Transfer to branch {target_branch_id}"),
                )
                conn.execute("COMMIT;")

                return {
                    "tx_id": tx_id,
                    "type": "TRANSFER_OUT",
                    "amount": amount,
                    "target_branch_id": target_branch_id,
                    "cash": new_cash,
                }
            except Exception:
                conn.execute("ROLLBACK;")
                raise

    def transfer_in(self, amount: int, source_branch_id: str, tx_id: str) -> dict:
        if not source_branch_id or source_branch_id == self.db.branch_id:
            raise BankingError("source_branch_id must be a different branch.")
        if not tx_id or not isinstance(tx_id, str):
            raise BankingError("tx_id is required for incoming transfers.")
        amount = _require_positive_int(amount, "amount")

        with self.db.get_connection() as conn:
            conn.execute("BEGIN IMMEDIATE;")
            try:
                existing = conn.execute(
                    "SELECT tx_id FROM transactions WHERE tx_id = ?",
                    (tx_id,),
                ).fetchone()
                if existing:
                    row = conn.execute(
                        "SELECT cash FROM branch_state WHERE branch_id = ?",
                        (self.db.branch_id,),
                    ).fetchone()
                    conn.execute("COMMIT;")
                    return {
                        "tx_id": tx_id,
                        "duplicate": True,
                        "status": "COMPLETED",
                        "cash": row["cash"] if row else None,
                    }

                conn.execute(
                    """
                    UPDATE branch_state
                    SET cash = cash + ?, updated_at = CURRENT_TIMESTAMP
                    WHERE branch_id = ?
                    """,
                    (amount, self.db.branch_id),
                )
                conn.execute(
                    """
                    INSERT INTO transactions (tx_id, tx_type, amount, peer_branch_id, note)
                    VALUES (?, 'TRANSFER_IN', ?, ?, ?)
                    """,
                    (tx_id, amount, source_branch_id, f"Transfer from branch {source_branch_id}"),
                )
                row = conn.execute(
                    "SELECT cash FROM branch_state WHERE branch_id = ?",
                    (self.db.branch_id,),
                ).fetchone()
                conn.execute("COMMIT;")

                return {
                    "tx_id": tx_id,
                    "type": "TRANSFER_IN",
                    "amount": amount,
                    "source_branch_id": source_branch_id,
                    "cash": row["cash"],
                }
            except Exception:
                conn.execute("ROLLBACK;")
                raise

    def set_employee_count(self, employees: int) -> dict:
        employees = _require_non_negative_int(employees, "employees")
        with self.db.get_connection() as conn:
            conn.execute("BEGIN IMMEDIATE;")
            try:
                conn.execute(
                    """
                    UPDATE branch_state
                    SET employees = ?, updated_at = CURRENT_TIMESTAMP
                    WHERE branch_id = ?
                    """,
                    (employees, self.db.branch_id),
                )
                conn.execute("COMMIT;")
                return {"branch_id": self.db.branch_id, "employees": employees}
            except Exception:
                conn.execute("ROLLBACK;")
                raise

    def upsert_staff_member(
        self,
        emp_id: str,
        name: str,
        role: str,
        shift: str = "DAY",
        active: int = 1,
    ) -> dict:
        if active not in (0, 1):
            raise BankingError("active must be 0 or 1.")
        with self.db.get_connection() as conn:
            conn.execute("BEGIN IMMEDIATE;")
            try:
                conn.execute(
                    """
                    INSERT INTO staff_members (emp_id, name, role, shift, active)
                    VALUES (?, ?, ?, ?, ?)
                    ON CONFLICT(emp_id) DO UPDATE SET
                        name = excluded.name,
                        role = excluded.role,
                        shift = excluded.shift,
                        active = excluded.active
                    """,
                    (emp_id, name, role, shift, active),
                )
                active_count = conn.execute(
                    "SELECT COUNT(*) AS cnt FROM staff_members WHERE active = 1"
                ).fetchone()["cnt"]
                conn.execute(
                    """
                    UPDATE branch_state
                    SET employees = ?, updated_at = CURRENT_TIMESTAMP
                    WHERE branch_id = ?
                    """,
                    (active_count, self.db.branch_id),
                )
                conn.execute("COMMIT;")
                return {"emp_id": emp_id, "employees": active_count}
            except Exception:
                conn.execute("ROLLBACK;")
                raise

    def list_staff_members(self) -> list[dict]:
        with self.db.get_connection() as conn:
            rows = conn.execute(
                "SELECT emp_id, name, role, shift, active FROM staff_members ORDER BY emp_id"
            ).fetchall()
            return [dict(r) for r in rows]