"""End-to-end fault tolerance test with three real branch server processes.

Scenario:
  1. Start A, B, C.
  2. Fire concurrent withdrawals at C, check the reserve holds.
  3. Try an overdraft transfer, check no money is created.
  4. Kill B. A sends B money: A is debited, transfer stays PENDING.
  5. A's failure detector marks B as DOWN.
  6. Restart B. A's recovery worker delivers the transfer automatically.
  7. Network audit: no money created or destroyed.

Takes about 10-15 seconds. Skip with:  pytest -m "not integration"
"""

import os
import socket
import subprocess
import sys
import time
from concurrent.futures import ThreadPoolExecutor

import pytest
import requests

from reliability.audit import network_audit

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
pytestmark = pytest.mark.integration


def free_port():
    with socket.socket() as s:
        s.bind(("127.0.0.1", 0))
        return s.getsockname()[1]


def wait_until(check, timeout=15.0, every=0.2):
    deadline = time.time() + timeout
    while time.time() < deadline:
        try:
            if check():
                return True
        except requests.RequestException:
            pass
        time.sleep(every)
    return False


@pytest.fixture
def cluster(tmp_path):
    ports = {b: free_port() for b in "ABC"}
    urls = {b: f"http://127.0.0.1:{p}" for b, p in ports.items()}
    env = {
        **os.environ,
        "PYTHONPATH": ROOT,
        "HEARTBEAT_INTERVAL": "0.5",
        "RECOVERY_INTERVAL": "1.0",
        **{f"BRANCH_{b}_URL": u for b, u in urls.items()},
    }
    procs = {}

    def start(branch):
        procs[branch] = subprocess.Popen(
            [sys.executable, "-m", "branch_nodes.branch_server"],
            cwd=str(tmp_path),  # SQLite files go in tmp_path/data
            env={**env, "BRANCH_ID": branch, "PORT": str(ports[branch])},
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
        )
        assert wait_until(lambda: requests.get(f"{urls[branch]}/health", timeout=1).ok)

    def kill(branch):
        procs[branch].kill()
        procs[branch].wait()

    for b in "ABC":
        start(b)

    yield {"urls": urls, "start": start, "kill": kill}

    for p in procs.values():
        p.kill()
        p.wait()


def test_full_fault_tolerance_scenario(cluster):
    urls, start, kill = cluster["urls"], cluster["start"], cluster["kill"]
    A, B, C = urls["A"], urls["B"], urls["C"]

    # 2. Concurrency: 30 parallel $1,000 withdrawals at C. Only 15 fit above the reserve.
    def withdraw(_):
        return requests.post(f"{C}/withdraw", json={"amount": 100_000}, timeout=10).status_code

    with ThreadPoolExecutor(max_workers=30) as pool:
        codes = list(pool.map(withdraw, range(30)))
    assert codes.count(200) == 15 and codes.count(409) == 15
    assert requests.get(f"{C}/status").json()["cash"] == 500_000

    # 3. Overdraft transfer from C is refused and A is NOT credited.
    r = requests.post(f"{C}/transfer", json={"target_branch_id": "A", "amount": 100_000})
    assert r.status_code == 409
    assert requests.get(f"{A}/status").json()["cash"] == 5_000_000

    # 4. Kill B, then send it money from A.
    kill("B")
    r = requests.post(f"{A}/transfer", json={"target_branch_id": "B", "amount": 250_000, "tx_id": "TX-FAILOVER"})
    assert r.status_code == 202 and r.json()["status"] == "PENDING"
    assert requests.get(f"{A}/status").json()["cash"] == 4_750_000
    assert len(requests.get(f"{A}/transfers/pending").json()["pending"]) == 1

    # 5. A's failure detector marks B as DOWN.
    assert wait_until(lambda: requests.get(f"{A}/cluster/health").json()["peers"]["B"]["state"] == "DOWN")

    # 6. Restart B. A delivers the pending transfer on its own.
    start("B")
    assert wait_until(lambda: requests.get(f"{A}/transfers/pending").json()["pending"] == [])
    assert requests.get(f"{B}/status").json()["cash"] == 3_250_000
    assert requests.get(f"{A}/cluster/health").json()["peers"]["B"]["state"] == "ONLINE"

    # 7. No money was created or destroyed anywhere in the network.
    report = network_audit(urls)
    assert report["money_conserved"], report
    assert all(b["ledger_consistent"] for b in report["branches"].values())
