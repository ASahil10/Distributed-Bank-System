
"""Independent bank branch server backed by SQLite persistence and peer communication."""
import os
import time

from flask import Flask, jsonify, request

from branch_nodes.branch_config import get_branch_config
from banking.database import BranchDatabase
from banking.service import BankingError, BankingService
from communication.client import BranchClient, BranchCommunicationError
from reliability.audit import local_audit
from reliability.failure_detector import FailureDetector
from reliability.recovery import RecoveryWorker
from reliability.transfer_saga import COMPLETED, PENDING, TransferSaga

app = Flask(__name__)

BRANCH_ID = os.getenv("BRANCH_ID", "A")
PORT = int(os.getenv("PORT", "5001"))

BRANCH_URLS = {
    "A": os.getenv("BRANCH_A_URL", "http://127.0.0.1:5001"),
    "B": os.getenv("BRANCH_B_URL", "http://127.0.0.1:5002"),
    "C": os.getenv("BRANCH_C_URL", "http://127.0.0.1:5003"),
}

config = get_branch_config(BRANCH_ID)
db = BranchDatabase(BRANCH_ID)
db.seed_from_config(config)
banking = BankingService(db)
communication = BranchClient(BRANCH_URLS, timeout=3.0, max_retries=2)

# Part 4: reliability. Background threads are only started in __main__,
# so importing this module in tests does not spawn them.
STARTED_AT = time.time()
detector = FailureDetector(
    BRANCH_ID,
    BRANCH_URLS,
    interval=float(os.getenv("HEARTBEAT_INTERVAL", "2.0")),
    timeout=1.0,
    suspect_after=1,
    down_after=3,
)
transfers = TransferSaga(BRANCH_ID, db, communication, detector=detector)
recovery = RecoveryWorker(transfers, interval=float(os.getenv("RECOVERY_INTERVAL", "5.0")))
detector.on_recover = recovery.trigger


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

    if type(amount) is not int or amount <= 0:
        return jsonify({"error": "amount must be a positive integer in cents"}), 400

    try:
        result = banking.deposit(amount=amount, tx_id=tx_id, note=note)
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

    if type(amount) is not int or amount <= 0:
        return jsonify({"error": "amount must be a positive integer in cents"}), 400

    try:
        result = banking.withdraw(
            amount=amount,
            allow_below_reserve=False,
            tx_id=tx_id,
            note=note,
        )
        return jsonify({
            "branch_id": BRANCH_ID,
            "cash": result["cash"],
            "tx_id": result["tx_id"],
        })
    except BankingError as exc:
        message = str(exc)
        if "minimum reserve" in message or "insufficient cash" in message:
            return jsonify({"error": "insufficient cash above minimum reserve"}), 409
        return jsonify({"error": message}), 400


@app.get("/transactions")
def transactions():
    limit = request.args.get("limit", default=50, type=int)
    if limit is None or limit <= 0:
        return jsonify({"error": "limit must be a positive integer"}), 400

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

    if type(employees) is not int or employees < 0:
        return jsonify({"error": "employees must be a non-negative integer"}), 400

    try:
        return jsonify(banking.set_employee_count(employees))
    except BankingError as exc:
        return jsonify({"error": str(exc)}), 400


# Part 2: communication and synchronization endpoints.
@app.get("/peers")
def peers():
    return jsonify({
        "branch_id": BRANCH_ID,
        "peers": communication.health_check_all(current_branch_id=BRANCH_ID),
    })


@app.get("/sync")
def sync():
    branches = {}

    try:
        branches[BRANCH_ID] = {
            "online": True,
            "status": banking.get_status(),
        }
    except BankingError as exc:
        branches[BRANCH_ID] = {"online": False, "error": str(exc)}

    branches.update(communication.health_check_all(current_branch_id=BRANCH_ID))

    return jsonify({
        "branch_id": BRANCH_ID,
        "branches": branches,
    })


@app.post("/internal/transfer-in")
def transfer_in():
    data = request.get_json(silent=True) or {}
    source_branch_id = data.get("source_branch_id")
    amount = data.get("amount")
    tx_id = data.get("tx_id")

    if source_branch_id not in BRANCH_URLS or source_branch_id == BRANCH_ID:
        return jsonify({"error": "source_branch_id must be another known branch"}), 400
    if type(amount) is not int or amount <= 0:
        return jsonify({"error": "amount must be a positive integer in cents"}), 400
    if not isinstance(tx_id, str) or not tx_id.strip():
        return jsonify({"error": "tx_id is required"}), 400

    try:
        result = banking.transfer_in(
            amount=amount,
            source_branch_id=source_branch_id,
            tx_id=tx_id,
        )
        return jsonify({"branch_id": BRANCH_ID, **result})
    except BankingError as exc:
        return jsonify({"error": str(exc)}), 400


@app.post("/transfer")
def transfer():
    data = request.get_json(silent=True) or {}
    target_branch_id = data.get("target_branch_id")
    amount = data.get("amount")
    tx_id = data.get("tx_id")

    if target_branch_id not in BRANCH_URLS or target_branch_id == BRANCH_ID:
        return jsonify({"error": "target_branch_id must be another known branch"}), 400
    if type(amount) is not int or amount <= 0:
        return jsonify({"error": "amount must be a positive integer in cents"}), 400
    if tx_id is not None and (not isinstance(tx_id, str) or not tx_id.strip()):
        return jsonify({"error": "tx_id must be a non-empty string"}), 400

    try:
        result = transfers.start(
            target_branch_id=target_branch_id,
            amount=amount,
            tx_id=tx_id,
        )
    except BankingError as exc:
        message = str(exc)
        if "minimum reserve" in message or "insufficient cash" in message:
            return jsonify({"error": "insufficient cash above minimum reserve"}), 409
        return jsonify({"error": message}), 400

    # 200 = delivered, 202 = debited and queued until the destination is back,
    # 409 = destination rejected it and the source was refunded.
    if result["status"] == COMPLETED:
        return jsonify(result), 200
    if result["status"] == PENDING:
        return jsonify(result), 202
    return jsonify(result), 409


# Part 4: reliability endpoints.
@app.get("/health")
def health():
    """Lightweight heartbeat target used by peers' failure detectors."""
    return jsonify({"branch_id": BRANCH_ID, "alive": True, "started_at": STARTED_AT})


@app.get("/cluster/health")
def cluster_health():
    """This branch's view of its peers: ONLINE / SUSPECTED / DOWN."""
    return jsonify({"branch_id": BRANCH_ID, "peers": detector.snapshot()})


@app.get("/transfers/pending")
def pending_transfers():
    return jsonify({"branch_id": BRANCH_ID, "pending": transfers.pending()})


@app.post("/transfers/retry")
def retry_transfers():
    """Manually flush the outbox (the recovery worker also does this on its own)."""
    return jsonify({"branch_id": BRANCH_ID, "results": transfers.retry_pending()})


@app.get("/audit")
def audit():
    return jsonify(local_audit(db, initial_cash=config["cash"]))


if __name__ == "__main__":
    detector.start()
    recovery.start()  # first run also resumes transfers left PENDING by a crash
    app.run(host="127.0.0.1", port=PORT, debug=False, threaded=True)
