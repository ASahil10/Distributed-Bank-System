
"""Independent bank branch server backed by SQLite banking persistence."""

import os
from flask import Flask, jsonify, request
from branch_nodes.branch_config import get_branch_config
from banking.database import BranchDatabase
from banking.service import BankingError, BankingService

app = Flask(__name__)

# Identify which branch this server represents.
BRANCH_ID = os.getenv("BRANCH_ID", "A")
PORT = int(os.getenv("PORT", "5001"))

# Load starting configuration and initialize SQLite storage.
config = get_branch_config(BRANCH_ID)
db = BranchDatabase(BRANCH_ID)
db.seed_from_config(config)
banking = BankingService(db)


@app.get("/status")
def status():
    try:
        current = banking.get_status()

        return jsonify({
            "branch_id": current["branch_id"],
            "cash": current["cash"],
            "employees": current["employees"],
            "minimum_reserve": current["minimum_reserve"],
            "reserve_warning": current["reserve_warning"],
        })

    except BankingError as exc:
        return jsonify({"error": str(exc)}), 400


@app.post("/deposit")
def deposit():
    data = request.get_json(silent=True) or {}
    amount = data.get("amount")
    tx_id = data.get("tx_id")
    note = data.get("note", "")

    # Make sure the deposit amount is valid.
    if type(amount) is not int or amount <= 0:
        return jsonify({
            "error": "amount must be a positive integer in cents"
        }), 400

    try:
        result = banking.deposit(
            amount=amount,
            tx_id=tx_id,
            note=note
        )

        return jsonify({
            "branch_id": BRANCH_ID,
            "cash": result["cash"],
            "tx_id": result["tx_id"],
        })

    except BankingError as exc:
        return jsonify({"error": str(exc)}), 400


@app.post("/withdraw")
def withdraw():
    data = request.get_json(silent=True) or {}
    amount = data.get("amount")
    tx_id = data.get("tx_id")
    note = data.get("note", "")

    # Make sure the withdrawal amount is valid.
    if type(amount) is not int or amount <= 0:
        return jsonify({
            "error": "amount must be a positive integer in cents"
        }), 400

    try:
        result = banking.withdraw(
            amount=amount,
            allow_below_reserve=False,
            tx_id=tx_id,
            note=note
        )

        return jsonify({
            "branch_id": BRANCH_ID,
            "cash": result["cash"],
            "tx_id": result["tx_id"],
        })

    except BankingError as exc:
        message = str(exc)

        # Reject withdrawals that violate minimum reserve rules.
        if "minimum reserve" in message or "insufficient cash" in message:
            return jsonify({
                "error": "insufficient cash above minimum reserve"
            }), 409

        return jsonify({"error": message}), 400


@app.get("/transactions")
def transactions():
    limit = request.args.get("limit", default=50, type=int)

    if limit is None or limit <= 0:
        return jsonify({
            "error": "limit must be a positive integer"
        }), 400

    try:
        return jsonify({
            "branch_id": BRANCH_ID,
            "transactions": banking.get_transactions(limit=limit),
        })

    except BankingError as exc:
        return jsonify({"error": str(exc)}), 400


@app.put("/employees")
def update_employees():
    data = request.get_json(silent=True) or {}
    employees = data.get("employees")

    # Employee count cannot be negative.
    if type(employees) is not int or employees < 0:
        return jsonify({
            "error": "employees must be a non-negative integer"
        }), 400

    try:
        updated = banking.set_employee_count(employees)
        return jsonify(updated)

    except BankingError as exc:
        return jsonify({"error": str(exc)}), 400


if __name__ == "__main__":
    app.run(host="127.0.0.1", port=PORT, debug=False)
