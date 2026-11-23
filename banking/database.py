"""SQLite persistence layer for an individual bank branch."""

import os
import sqlite3
from contextlib import contextmanager


class BranchDatabase:
    """Manages an isolated SQLite database for a single branch using integer cents."""

    def __init__(self, branch_id: str, db_dir: str = "data"):
        if not branch_id or not isinstance(branch_id, str):
            raise ValueError("branch_id must be a non-empty string.")
        self.branch_id = branch_id
        os.makedirs(db_dir, exist_ok=True)
        self.db_path = os.path.join(db_dir, f"branch_{branch_id}.db")
        self._init_db()

    @contextmanager
    def get_connection(self):
        conn = sqlite3.connect(self.db_path, timeout=10.0, isolation_level=None)
        conn.row_factory = sqlite3.Row
        conn.execute("PRAGMA journal_mode = WAL;")
        conn.execute("PRAGMA synchronous = NORMAL;")
        conn.execute("PRAGMA busy_timeout = 5000;")
        conn.execute("PRAGMA foreign_keys = ON;")
        try:
            yield conn
        finally:
            conn.close()

    def _init_db(self):
        with self.get_connection() as conn:
            conn.executescript(
                """
                CREATE TABLE IF NOT EXISTS branch_state (
                    branch_id TEXT PRIMARY KEY,
                    cash INTEGER NOT NULL CHECK (cash >= 0),
                    minimum_reserve INTEGER NOT NULL CHECK (minimum_reserve >= 0),
                    employees INTEGER NOT NULL DEFAULT 0 CHECK (employees >= 0),
                    updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
                );

                CREATE TABLE IF NOT EXISTS transactions (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    tx_id TEXT UNIQUE NOT NULL,
                    tx_type TEXT NOT NULL CHECK (
                        tx_type IN ('DEPOSIT', 'WITHDRAWAL', 'TRANSFER_IN', 'TRANSFER_OUT')
                    ),
                    amount INTEGER NOT NULL CHECK (amount > 0),
                    peer_branch_id TEXT,
                    status TEXT NOT NULL DEFAULT 'COMPLETED',
                    note TEXT,
                    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
                );

                CREATE TABLE IF NOT EXISTS staff_members (
                    emp_id TEXT PRIMARY KEY,
                    name TEXT NOT NULL,
                    role TEXT NOT NULL,
                    shift TEXT NOT NULL DEFAULT 'DAY',
                    active INTEGER NOT NULL DEFAULT 1 CHECK (active IN (0, 1))
                );
                """
            )

    def seed_from_config(self, config: dict):
        """Seeds initial branch state if not already persisted."""
        cash = config["cash"]
        minimum_reserve = config["minimum_reserve"]
        employees = config["employees"]

        for name, val in (("cash", cash), ("minimum_reserve", minimum_reserve), ("employees", employees)):
            if isinstance(val, bool) or not isinstance(val, int) or val < 0:
                raise ValueError(f"{name} must be a non-negative integer.")

        with self.get_connection() as conn:
            conn.execute("BEGIN IMMEDIATE;")
            try:
                conn.execute(
                    """
                    INSERT OR IGNORE INTO branch_state
                        (branch_id, cash, minimum_reserve, employees)
                    VALUES (?, ?, ?, ?)
                    """,
                    (self.branch_id, cash, minimum_reserve, employees),
                )
                conn.execute("COMMIT;")
            except Exception:
                conn.execute("ROLLBACK;")
                raise