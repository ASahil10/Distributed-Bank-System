
# Distributed Banking System API

## Branch Servers

Each branch runs independently.

| Branch | Port |
|--------|------|
| A | 5001 |
| B | 5002 |
| C | 5003 |

All monetary amounts are integer cents.

## GET /status

Returns the branch's current information.

Example:
GET http://127.0.0.1:5001/status

Response:
{
  "branch_id": "A",
  "cash": 5000000,
  "employees": 10,
  "minimum_reserve": 1000000,
  "reserve_warning": false
}

## POST /deposit

Adds cash to a branch.

Request:
{
  "amount": 50000
}

Response:
{
  "branch_id": "A",
  "cash": 5050000
}

## POST /withdraw

Removes cash from a branch if the
minimum reserve will still be maintained.

Request:
{
  "amount": 20000
}

Response:
{
  "branch_id": "A",
  "cash": 4980000
}

## Error Handling

400 - Invalid transaction amount

409 - Withdrawal would violate minimum reserve

## Current Limitations

- Branch state is stored in memory.
- Restarting a branch resets its balance.
- No inter-branch messaging yet.
- No concurrency protection yet.
- No authentication yet.

## Planned Integration

Banking:
Implement transaction persistence and banking rules.

Communication:
Implement messaging and synchronization between nodes.

Reliability:
Implement locking, failure detection, and recovery.

Dashboard:
Display branch information through the APIs.
