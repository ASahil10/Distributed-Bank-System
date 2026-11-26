# Part 4: Concurrency Control and Fault Tolerance

## Files

| File | What it does |
|------|--------------|
| `transfer_saga.py` | Safe inter-branch transfers (debit first, durable outbox, refund on rejection) |
| `failure_detector.py` | Heartbeat failure detector: ONLINE / SUSPECTED / DOWN per peer |
| `recovery.py` | Background worker that retries pending transfers until delivered |
| `audit.py` | Ledger audit per branch, and a network-wide "no money created or lost" check |

## Concurrency control

Each branch has its own SQLite database. Every write (deposit, withdrawal,
transfer debit, refund) runs inside `BEGIN IMMEDIATE`, which takes the
database write lock before reading the balance. Two tellers can never read
the same balance and both withdraw from it, so the minimum reserve can't be
broken by a race. Flask runs with `threaded=True`, so requests really do run
in parallel.

Duplicate requests are blocked by the unique `tx_id` on every transaction:
sending the same deposit or transfer twice only applies it once.

No distributed lock is needed: a transfer only locks the sender's database to
debit, and only the receiver's database to credit, so A->B and B->A at the
same time can't deadlock.

## Safe transfers (saga + outbox)

The old version credited the destination first, then debited the source. If
the source couldn't afford it, the destination kept the money and the
network gained cash out of nowhere. The new flow:

1. **Debit + outbox**: in one local transaction, the sender checks its reserve,
   subtracts the cash and saves the transfer as `PENDING`.
2. **Deliver**: send `/internal/transfer-in` with the same `tx_id`.
3. **Outcome**:
   - accepted: `COMPLETED` (HTTP 200)
   - rejected by destination: `FAILED`, cash refunded to sender (HTTP 409)
   - destination unreachable: stays `PENDING` (HTTP 202), retried later

Because the receiver ignores duplicate `tx_id`s, retrying is always safe
(at-least-once delivery + idempotent receiver). Status changes are
conditional (`WHERE status = 'PENDING'`), so a transfer can't be completed or
refunded twice even if two threads handle it at once.

## Failure detection and recovery

- Every branch pings its peers' `GET /health` every 2 seconds.
- 1 missed heartbeat: `SUSPECTED`. 3 in a row: `DOWN`.
- Transfers to a `DOWN` branch are queued immediately instead of making the
  teller wait for timeouts.
- When a peer comes back (or restarted, detected by a new `started_at`), the
  recovery worker immediately retries everything queued for it.
- The outbox is on disk, so if the *sender* crashes, its pending transfers
  are resumed when it restarts.
- Local operations keep working while other branches are down.

## Endpoints added

| Method | Path | Purpose |
|--------|------|---------|
| GET | `/health` | Heartbeat target |
| GET | `/cluster/health` | This branch's view of peers (state, missed beats, last seen) |
| GET | `/transfers/pending` | Transfers waiting for delivery |
| POST | `/transfers/retry` | Flush the outbox manually |
| GET | `/audit` | Recompute cash from the ledger and compare |

`POST /transfer` now returns 200 (delivered), 202 (queued) or 409 (refused/refunded).

## Tests

```powershell
python -m pytest                       # everything (~5 s)
python -m pytest -m "not integration"  # skip the live 3-server test
```

- `tests/test_reliability.py`: 50 concurrent withdrawals, 20 concurrent
  transfers, duplicate deposits, overdraft regression, refund race,
  crash/restart recovery, failure detector state changes.
- `tests/test_integration_failover.py`: starts A, B, C as real processes,
  kills B mid-transfer, restarts it and checks the money arrives and the
  network audit balances.

## Demo script (PowerShell, branches running on 5001-5003)

```powershell
# 1. Overdraft transfer is refused, nothing created
Invoke-RestMethod -Method Post -Uri http://127.0.0.1:5003/transfer -ContentType 'application/json' -Body '{"target_branch_id":"A","amount":1900000}'

# 2. Stop Branch B (Ctrl+C in its terminal), then send it money from A
Invoke-RestMethod -Method Post -Uri http://127.0.0.1:5001/transfer -ContentType 'application/json' -Body '{"target_branch_id":"B","amount":250000}'
Invoke-RestMethod http://127.0.0.1:5001/transfers/pending
Invoke-RestMethod http://127.0.0.1:5001/cluster/health | ConvertTo-Json -Depth 5

# 3. Restart Branch B, wait a few seconds, then check
Invoke-RestMethod http://127.0.0.1:5001/transfers/pending
Invoke-RestMethod http://127.0.0.1:5002/status

# 4. Prove no money was created or lost
python -m reliability.audit
```

## Known limitations (good for the report's future work section)

- Money is "in transit" while a destination is down (eventual consistency,
  not instant). We chose availability for local operations over blocking.
- No replication: if a branch's disk is lost, its data is lost. Future work:
  replicate each branch's ledger to a backup node.
- Heartbeat thresholds are fixed; an adaptive detector (e.g. phi-accrual)
  would cut false positives on slow networks.
- `/internal/transfer-in` has no authentication yet.
