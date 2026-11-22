
"""Independent bank branch server."""

import os
from flask import Flask, jsonify, request
from branch_nodes.branch_config import get_branch_config

app = Flask(__name__)

# Identify which branch this server represents.
BRANCH_ID = os.getenv("BRANCH_ID", "A")
PORT = int(os.getenv("PORT", "5001"))

# Load the starting information for this branch.
config = get_branch_config(BRANCH_ID)

# Each server maintains its own local branch state.
state = {
    "branch_id": BRANCH_ID,
    "cash": config["cash"],
    "employees": config["employees"],
    "minimum_reserve": config["minimum_reserve"]
}


# Return the current branch information.
@app.get("/status")
def status():
    return jsonify({
        **state,
        "reserve_warning": state["cash"] < state["minimum_reserve"]
    })


# Add cash to the branch.
@app.post("/deposit")
def deposit():
    data = request.get_json(silent=True) or {}
    amount = data.get("amount")

    # Make sure the amount is valid.
    if type(amount) is not int or amount <= 0:
        return jsonify({
            "error": "amount must be a positive integer in cents"
        }), 400

    state["cash"] += amount

    return jsonify({
        "branch_id": BRANCH_ID,
        "cash": state["cash"]
    })


# Withdraw cash from the branch.
@app.post("/withdraw")
def withdraw():
    data = request.get_json(silent=True) or {}
    amount = data.get("amount")

    # Make sure the amount is valid.
    if type(amount) is not int or amount <= 0:
        return jsonify({
            "error": "amount must be a positive integer in cents"
        }), 400

    # Prevent withdrawals below the minimum reserve.
    if state["cash"] - amount < state["minimum_reserve"]:
        return jsonify({
            "error": "insufficient cash above minimum reserve"
        }), 409

    state["cash"] -= amount

    return jsonify({
        "branch_id": BRANCH_ID,
        "cash": state["cash"]
    })


# Start the branch server.
if __name__ == "__main__":
    app.run(host="127.0.0.1", port=PORT, debug=False)
