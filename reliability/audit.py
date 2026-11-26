"""Consistency audits.

Local audit (per branch, served at GET /audit):
    Re-derives the cash balance from the ledger and checks it matches:
        initial_cash + deposits - withdrawals + transfers_in
                     - transfers_out (PENDING or COMPLETED)  ==  cash
    FAILED (refunded) transfers are excluded because their cash was returned.

Network audit (run from a terminal: python -m reliability.audit):
    Checks that no money was created or destroyed across all branches:
        sum(cash) + money_in_transit  ==  sum(initial_cash) + deposits - withdrawals
    "In transit" = PENDING outgoing transfers that the destination has not
    credited yet. A PENDING transfer the destination already credited (reply
    was lost) is not counted twice.
"""

import json
import os
import sys

import requests

from banking.database import BranchDatabase


def local_audit(db: BranchDatabase, initial_cash: int) -> dict:
    with db.get_connection() as conn:
        state = conn.execute(
            "SELECT cash, minimum_reserve FROM branch_state WHERE branch_id = ?",
            (db.branch_id,),
        ).fetchone()
        totals = {
            row["tx_type"]: row["total"]
            for row in conn.execute(
                """
                SELECT tx_type, COALESCE(SUM(amount), 0) AS total
                FROM transactions
                WHERE NOT (tx_type = 'TRANSFER_OUT' AND status = 'FAILED')
                GROUP BY tx_type
                """
            )
        }
        pending = [
            dict(r)
            for r in conn.execute(
                """
                SELECT tx_id, amount, peer_branch_id FROM transactions
                WHERE tx_type = 'TRANSFER_OUT' AND status = 'PENDING'
                """
            )
        ]
        received = [
            r["tx_id"]
            for r in conn.execute("SELECT tx_id FROM transactions WHERE tx_type = 'TRANSFER_IN'")
        ]

    deposits = totals.get("DEPOSIT", 0)
    withdrawals = totals.get("WITHDRAWAL", 0)
    transfers_in = totals.get("TRANSFER_IN", 0)
    transfers_out = totals.get("TRANSFER_OUT", 0)
    expected = initial_cash + deposits - withdrawals + transfers_in - transfers_out

    return {
        "branch_id": db.branch_id,
        "cash": state["cash"],
        "minimum_reserve": state["minimum_reserve"],
        "initial_cash": initial_cash,
        "deposits": deposits,
        "withdrawals": withdrawals,
        "transfers_in": transfers_in,
        "transfers_out": transfers_out,
        "expected_cash_from_ledger": expected,
        "ledger_consistent": expected == state["cash"],
        "reserve_respected": state["cash"] >= state["minimum_reserve"],
        "pending_out": pending,
        "received_tx_ids": received,
    }


def network_audit(branch_urls: dict[str, str], timeout: float = 3.0) -> dict:
    audits, unreachable = {}, []
    for branch_id, url in branch_urls.items():
        try:
            resp = requests.get(f"{url.rstrip('/')}/audit", timeout=timeout)
            resp.raise_for_status()
            audits[branch_id] = resp.json()
        except Exception:
            unreachable.append(branch_id)

    if unreachable:
        return {
            "complete": False,
            "unreachable": unreachable,
            "message": "Cannot audit the whole network while a branch is down.",
        }

    received = {tx for a in audits.values() for tx in a["received_tx_ids"]}
    in_transit = sum(
        p["amount"] for a in audits.values() for p in a["pending_out"] if p["tx_id"] not in received
    )
    total_cash = sum(a["cash"] for a in audits.values())
    expected = sum(a["initial_cash"] + a["deposits"] - a["withdrawals"] for a in audits.values())

    return {
        "complete": True,
        "total_cash": total_cash,
        "in_transit": in_transit,
        "expected_total": expected,
        "money_conserved": total_cash + in_transit == expected,
        "branches": {
            b: {
                "cash": a["cash"],
                "ledger_consistent": a["ledger_consistent"],
                "reserve_respected": a["reserve_respected"],
                "pending_out": len(a["pending_out"]),
            }
            for b, a in audits.items()
        },
    }


if __name__ == "__main__":
    urls = {
        "A": os.getenv("BRANCH_A_URL", "http://127.0.0.1:5001"),
        "B": os.getenv("BRANCH_B_URL", "http://127.0.0.1:5002"),
        "C": os.getenv("BRANCH_C_URL", "http://127.0.0.1:5003"),
    }
    report = network_audit(urls)
    print(json.dumps(report, indent=2))
    sys.exit(0 if report.get("money_conserved") else 1)
