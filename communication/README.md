# Distributed Communication and Synchronization

This package implements Part 2 of the Distributed Multi-Branch Bank Management System.

## Responsibilities

- HTTP messaging between Branch A, B, and C
- Peer status and transaction retrieval
- Inter-branch transfer messages
- Stable transaction identifiers for idempotency
- Request timeouts and bounded retries
- Online/offline health reporting

## Files

- `client.py`: reusable HTTP client for peer communication
- `transfer_coordinator.py`: coordinates inter-branch transfers
- `__init__.py`: exports the public communication classes

## Branch URLs

The branch server reads the following optional environment variables:

- `BRANCH_A_URL`, default `http://127.0.0.1:5001`
- `BRANCH_B_URL`, default `http://127.0.0.1:5002`
- `BRANCH_C_URL`, default `http://127.0.0.1:5003`

## Communication endpoints

- `GET /peers`: returns online/offline information for peer branches
- `GET /sync`: retrieves the current state of all reachable branches
- `POST /transfer`: initiates an inter-branch transfer
- `POST /internal/transfer-in`: receives a transfer message from another branch

All money values are represented as integer cents.

## Idempotency

Every transfer uses a stable `tx_id`. The SQLite `transactions.tx_id` field is unique, and the banking service checks for an existing identifier before applying a transaction. Retrying the same incoming message therefore does not credit the destination twice.

## Current consistency limitation

This course implementation demonstrates message passing, timeout handling, retries, and duplicate protection. Complete atomicity across two independent SQLite databases would require an additional distributed transaction protocol or compensating transaction workflow.
