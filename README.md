# Distributed Multi-Branch Bank Management System
SOFE4790U group project starter. **Educational simulation only**; not a real banking system.

## Setup
Install Python 3.10+ and run from the repository root:

```powershell
py -m venv .venv
.\.venv\Scripts\Activate.ps1
pip install -r requirements.txt
```

## Run three independent branches (Windows PowerShell)
Open three terminals, activate the environment in each, then run:

```powershell
$env:BRANCH_ID="A"; $env:PORT="5001"; python -m branch_nodes.branch_server
```
```powershell
$env:BRANCH_ID="B"; $env:PORT="5002"; python -m branch_nodes.branch_server
```
```powershell
$env:BRANCH_ID="C"; $env:PORT="5003"; python -m branch_nodes.branch_server
```
Visit http://127.0.0.1:5001/status and ports 5002 and 5003.

## Test transactions
In a fourth PowerShell terminal:
```powershell
Invoke-RestMethod -Method Post -Uri http://127.0.0.1:5001/deposit -ContentType 'application/json' -Body '{"amount":500}'
Invoke-RestMethod -Method Post -Uri http://127.0.0.1:5001/withdraw -ContentType 'application/json' -Body '{"amount":200}'
```
Amounts are **integer cents**. Each node starts with 10000 cents ($100) and a 2000-cent ($20) reserve.

## Team component folders
- `branch_nodes/`: node setup and architecture
- `banking/`: ledger, reserves, employees, transactions
- `communication/`: peer messaging and synchronization
- `reliability/`: concurrency, failure detection, recovery
- `dashboard/`: admin UI and integration
- `tests/`: automated integration tests

## API contract (starter)
- `GET /status` returns `branch_id`, `cash`, `employees`, `minimum_reserve`, `reserve_warning`.
- `POST /deposit` with `{"amount":500}` deposits 500 cents.
- `POST /withdraw` with `{"amount":200}` withdraws 200 cents if reserves permit.
- Errors return JSON `{"error":"..."}` with an HTTP error status.

## Important limitations
This starter has **no peer messaging, persistent storage, account-level ledger, locking, transfer protocol, authentication, or failure recovery**. In-memory state is reset on restart and is not safe for concurrent transactions. Those features belong to the five implementation workstreams; do not claim they are complete.
