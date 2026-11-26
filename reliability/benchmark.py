"""Benchmark for the report: latency, throughput, failure detection and recovery.

Starts its own Branch A, B and C on free ports in a temporary folder, so it
never touches the real data/ databases. Run from the repository root:

    python -m reliability.benchmark

Takes about a minute.
"""

import os
import socket
import statistics
import subprocess
import sys
import tempfile
import time
from concurrent.futures import ThreadPoolExecutor

import requests

from reliability.audit import network_audit

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))


def free_port():
    with socket.socket() as s:
        s.bind(("127.0.0.1", 0))
        return s.getsockname()[1]


class Cluster:
    def __init__(self, workdir):
        self.workdir = workdir
        self.ports = {b: free_port() for b in "ABC"}
        self.urls = {b: f"http://127.0.0.1:{p}" for b, p in self.ports.items()}
        self.procs = {}
        self.env = {
            **os.environ,
            "PYTHONPATH": ROOT,
            **{f"BRANCH_{b}_URL": u for b, u in self.urls.items()},
        }

    def start(self, branch):
        self.procs[branch] = subprocess.Popen(
            [sys.executable, "-m", "branch_nodes.branch_server"],
            cwd=self.workdir,
            env={**self.env, "BRANCH_ID": branch, "PORT": str(self.ports[branch])},
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
        )
        started = time.perf_counter()
        while True:
            try:
                if requests.get(f"{self.urls[branch]}/health", timeout=0.5).ok:
                    return time.perf_counter() - started
            except requests.RequestException:
                time.sleep(0.05)

    def kill(self, branch):
        self.procs[branch].kill()
        self.procs[branch].wait()

    def stop_all(self):
        for p in self.procs.values():
            p.kill()
            p.wait()


def timed(fn):
    t = time.perf_counter()
    result = fn()
    return (time.perf_counter() - t) * 1000, result


def latency_stats(samples):
    samples = sorted(samples)
    return {
        "mean_ms": round(statistics.mean(samples), 2),
        "p95_ms": round(samples[int(len(samples) * 0.95) - 1], 2),
    }


def peer_state(cluster, observer, peer):
    return requests.get(f"{cluster.urls[observer]}/cluster/health", timeout=1).json()["peers"][peer]["state"]


def main():
    with tempfile.TemporaryDirectory() as workdir:
        c = Cluster(workdir)
        for b in "ABC":
            c.start(b)
        time.sleep(3)  # let heartbeats settle
        A, B, C = c.urls["A"], c.urls["B"], c.urls["C"]
        results = {}

        # 1. Latency of single operations (sequential).
        dep = [timed(lambda: requests.post(f"{A}/deposit", json={"amount": 100}))[0] for _ in range(200)]
        wd = [timed(lambda: requests.post(f"{A}/withdraw", json={"amount": 100}))[0] for _ in range(200)]
        tr = [
            timed(lambda: requests.post(f"{A}/transfer", json={"target_branch_id": "B", "amount": 100}))[0]
            for _ in range(200)
        ]
        st = [timed(lambda: requests.get(f"{A}/status"))[0] for _ in range(200)]
        results["latency"] = {
            "status": latency_stats(st),
            "deposit": latency_stats(dep),
            "withdraw": latency_stats(wd),
            "transfer (completed)": latency_stats(tr),
        }

        # 2. Throughput with concurrent clients.
        for clients in (1, 10, 25):
            n = 300
            t = time.perf_counter()
            with ThreadPoolExecutor(max_workers=clients) as pool:
                codes = list(pool.map(lambda _: requests.post(f"{A}/deposit", json={"amount": 100}).status_code, range(n)))
            elapsed = time.perf_counter() - t
            results[f"throughput_{clients}_clients"] = {
                "requests": n,
                "ok": codes.count(200),
                "req_per_sec": round(n / elapsed, 1),
            }

        # 3. Concurrency correctness: 50 simultaneous $1,000 withdrawals at C.
        with ThreadPoolExecutor(max_workers=50) as pool:
            codes = list(pool.map(lambda _: requests.post(f"{C}/withdraw", json={"amount": 100_000}).status_code, range(50)))
        results["concurrent_withdrawals"] = {
            "accepted": codes.count(200),
            "refused": codes.count(409),
            "final_cash": requests.get(f"{C}/status").json()["cash"],
            "minimum_reserve": requests.get(f"{C}/status").json()["minimum_reserve"],
        }

        # 4. Failure detection and recovery, 3 trials.
        trials = []
        for i in range(3):
            killed = time.perf_counter()
            c.kill("B")
            suspected = down = None
            while down is None:
                state = peer_state(c, "A", "B")
                now = time.perf_counter() - killed
                if state == "SUSPECTED" and suspected is None:
                    suspected = now
                if state == "DOWN":
                    down = now
                    suspected = suspected or now
                time.sleep(0.05)

            queued_ms, r = timed(
                lambda: requests.post(f"{A}/transfer", json={"target_branch_id": "B", "amount": 50_000, "tx_id": f"BENCH-{i}"})
            )
            assert r.json()["status"] == "PENDING", r.json()

            restarted = time.perf_counter()
            startup = c.start("B")
            while requests.get(f"{A}/transfers/pending").json()["pending"]:
                time.sleep(0.05)
            delivered = time.perf_counter() - restarted
            trials.append(
                {
                    "suspected_s": round(suspected, 2),
                    "down_s": round(down, 2),
                    "transfer_to_down_branch_ms": round(queued_ms, 1),
                    "branch_restart_s": round(startup, 2),
                    "pending_delivered_after_restart_s": round(delivered, 2),
                }
            )
            time.sleep(2.5)
        results["failure_trials"] = trials

        # 5. Consistency after everything.
        audit = network_audit(c.urls)
        results["final_audit"] = {k: audit[k] for k in ("total_cash", "in_transit", "expected_total", "money_conserved")}
        c.stop_all()

    for key, value in results.items():
        print(f"{key}: {value}")


if __name__ == "__main__":
    main()
