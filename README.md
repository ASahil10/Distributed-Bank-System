# Bank Management System

SOFE4790U Distributed Systems, Fall 2026, Group 17

Three independent bank branches (A, B and C) each run as their own server with their own SQLite database. They communicate over HTTP to transfer cash, detect when another branch fails, and recover automatically when it comes back. An admin dashboard shows the whole network and lets you run transactions.

## Features

- Deposits, withdrawals, transfers and transaction history at each branch
- Minimum cash reserve enforced on every withdrawal and transfer
- Data saved in SQLite, so it survives restarts
- Concurrency control so simultaneous requests can't corrupt balances
- Safe transfers that never create or lose money, even if a branch fails mid-transfer
- Failure detection (ONLINE, SUSPECTED, DOWN) and automatic recovery
- Admin dashboard with live balances, transactions, transfers in transit and branch health

## How It Works

**Concurrency:** every database write locks the branch's database before reading the balance, so two requests can't both spend the same money.

**Transfers:** the sending branch debits itself and saves the transfer as PENDING, then sends it to the receiver. If the receiver accepts, it's COMPLETED. If the receiver rejects it, the sender is refunded. If the receiver is down, it stays PENDING and is delivered once the receiver is back. Each transfer has a unique ID, so retries are never applied twice.

**Failure detection:** each branch checks the others every 2 seconds. One missed check marks a branch SUSPECTED, three mark it DOWN.

## Setup

Requires Python 3.10+. From the repository root:

```powershell
py -m venv .venv
.\.venv\Scripts\Activate.ps1
pip install -r requirements.txt
```

If activation is blocked, run `Set-ExecutionPolicy -Scope Process -ExecutionPolicy Bypass` first.

## Running

Open four terminals, activate the environment in each, and run one command per terminal:

```powershell
$env:BRANCH_ID="A"; $env:PORT="5001"; python -m branch_nodes.branch_server
$env:BRANCH_ID="B"; $env:PORT="5002"; python -m branch_nodes.branch_server
$env:BRANCH_ID="C"; $env:PORT="5003"; python -m branch_nodes.branch_server
python dashboard/app.py
```

Open http://127.0.0.1:5050. To reset all balances, stop the servers and delete the `data` folder.

| Branch | Port | Starting cash | Minimum reserve |
|---|---|---|---|
| A | 5001 | $50,000 | $10,000 |
| B | 5002 | $30,000 | $7,500 |
| C | 5003 | $20,000 | $5,000 |

## Failure Demo

1. Transfer $2,500 from A to B on the dashboard. It completes immediately.
2. Stop Branch B with Ctrl + C. Within about 6 seconds it shows as DOWN.
3. Transfer $2,500 from A to B again. A is debited and the transfer shows under "Transfers in transit".
4. Restart Branch B. Within a few seconds the transfer is delivered and the total is back to $100,000.

## Tests and Tools

```powershell
python -m pytest                  # all 29 tests
python -m reliability.audit       # check no money was created or lost (branches must be running)
python -m reliability.benchmark   # measure speed, throughput and recovery time
```

## API

All amounts are in cents (`250000` = $2,500).

| Method | Path | Purpose |
|---|---|---|
| GET | `/status` | Branch cash, reserve and employees |
| POST | `/deposit`, `/withdraw` | `{"amount": 50000}` |
| GET | `/transactions` | Transaction history |
| POST | `/transfer` | `{"target_branch_id": "B", "amount": 250000}` |
| GET | `/cluster/health` | How this branch sees the others |
| GET | `/transfers/pending` | Transfers waiting for delivery |
| GET | `/audit` | Check the branch's balance against its ledger |

## Project Structure

| Folder | Contents |
|---|---|
| `branch_nodes/` | Branch server and configuration |
| `banking/` | Database, deposits, withdrawals, reserves |
| `communication/` | Messaging between branches |
| `reliability/` | Safe transfers, failure detection, recovery, audit |
| `dashboard/` | Admin dashboard |
| `tests/` | Automated tests |

## Team

| Member | Student ID |
|---|---|
| Sahil Asifi | 100914271 |
| Aditya Ramjas | 100916432 |
| Burhanuddin Mohammed | 100943760 |
| Muhammad Saad | 100916536 |
| Hanzlah Imran | 100912657 |
