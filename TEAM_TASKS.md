
# Group 17 - Team Tasks and Responsibilities

## Project
Distributed Multi-Branch Bank Management System

Course: SOFE4790U - Distributed Systems
University: Ontario Tech University
Semester: Fall 2026

## Project Goal

Build a distributed banking simulation where three
independent bank branches communicate and coordinate
banking operations.

The project should demonstrate:
- Distributed nodes and message passing
- State synchronization
- Concurrency and consistency
- Fault tolerance and recovery
- System monitoring

Each member is responsible for approximately 20%
of the project implementation.

---

## Part 1 - Sahil Asifi
### Branch Nodes and System Architecture

Assigned folder: `branch_nodes/`

GitHub branch: `feature/branch-nodes`

### Completed
- [x] Created GitHub repository and project structure
- [x] Set up Python and Flask
- [x] Created three independent branch servers
- [x] Configured Branch A, B and C
- [x] Added branch configuration validation
- [x] Implemented GET /status
- [x] Added starter POST /deposit and POST /withdraw
- [x] Tested branch initialization and configuration

### Remaining
- [ ] Finalize shared API documentation
- [ ] Coordinate integration with other components
- [ ] Test integrated branch functionality
- [ ] Merge tested architecture into main

### Expected Deliverable
Three independently running branch servers with
configurable branch information and documented APIs.

---

## Part 2 - 
### Distributed Communication and Synchronization

Assigned folder: `communication/`

GitHub branch: `feature/distributed-communication`

### Tasks
- [ ] Implement HTTP messaging between branch nodes
- [ ] Create functions to send and receive messages
- [ ] Synchronize relevant branch state
- [ ] Implement communication for cash transfers
- [ ] Handle unavailable nodes and request timeouts
- [ ] Identify messages to prevent duplicate processing
- [ ] Test communication between Branch A, B and C

### Expected Deliverable
Branch nodes can exchange information and coordinate
inter-branch operations through network messages.

### Integration
Coordinate with Aditya on transfer request formats
and Burhanuddin on retries and duplicate processing.

---

## Part 3 - Burhanuddin Mohammed
### Banking Operations and Data Storage

Assigned folder: `banking/`

GitHub branch: `feature/banking-operations`

### Tasks
- [x] Create local SQLite database for each branch
- [x] Implement persistent cash balance storage
- [x] Implement deposit and withdrawal operations
- [x] Maintain transaction history
- [x] Enforce minimum cash reserve requirements
- [x] Track employee counts and staffing information
- [x] Implement banking rules for branch transfers
- [x] Integrate banking operations with Flask APIs
- [x] Test banking operations and persistence

### Expected Deliverable
Banking transactions work correctly and branch
records persist after restarting a server.

### Integration
Coordinate with Muhammad on transfers and
Burhanuddin on transaction locking.

---

## Part 4 - 
### Concurrency Control and Fault Tolerance

Assigned folder: `reliability/`

GitHub branch: `feature/reliability`

### Tasks
- [ ] Implement concurrency protection
- [ ] Prevent simultaneous withdrawals from causing
      incorrect balances
- [ ] Implement appropriate database transaction locking
- [ ] Detect branch server failures
- [ ] Handle network timeouts and failed requests
- [ ] Implement safe retry and recovery mechanisms
- [ ] Prevent duplicate transaction processing
- [ ] Test concurrent requests
- [ ] Test branch failures and recovery

### Expected Deliverable
The system maintains consistent banking records
during concurrent operations and handles node failures.

### Integration
Coordinate with Aditya on database transactions
and Muhammad on communication failures.

---

## Part 5 - Hanzlah Imran
### Admin Dashboard and System Integration 

Assigned folder: `dashboard/`

GitHub branch: `feature/dashboard`

### Tasks
- [ ] Create administrative dashboard interface
- [ ] Display all bank branches
- [ ] Display branch cash balances
- [ ] Display minimum reserve warnings
- [ ] Display employee information
- [ ] Display transaction and transfer history
- [ ] Display online/offline branch status
- [ ] Connect frontend to Flask APIs
- [ ] Help test the complete integrated system

### Expected Deliverable
A working administrative interface showing
live information from the distributed bank branches.

### Integration
Use the shared API documentation to retrieve
information from the branch servers.

---

## Shared Development Rules

1. Work primarily inside your assigned folder.
2. Create your feature branch from the latest main.
3. Do not directly push unfinished code to main.
4. Coordinate before modifying shared files.
5. Test your changes before submitting a pull request.
6. Use pull requests to merge completed features.
7. Keep your feature branch updated with main.
8. Document any new APIs or dependencies.
9. Inform the group when your component is ready.
10. Help with integration and final testing.

## Shared Files

The following files may be used by multiple members:

- branch_nodes/branch_server.py
- branch_nodes/branch_config.py
- API.md
- requirements.txt
- README.md

Changes to these files should be communicated
to the group to prevent merge conflicts.

---

## Final Integration Checklist

- [ ] Three independent branches start successfully
- [ ] Deposits and withdrawals work
- [ ] Cash reserves are enforced
- [ ] Transaction records persist
- [ ] Branches exchange messages
- [ ] Relevant branch information synchronizes
- [ ] Inter-branch transfers work safely
- [ ] Simultaneous transactions are handled correctly
- [ ] Failed branches are detected
- [ ] Recovery behavior is demonstrated
- [ ] Dashboard displays branch information
- [ ] All components are integrated and tested
- [ ] README contains final setup instructions
- [ ] Final report and presentation are completed

---

## Project Deadlines

Code submission: November 24, 2026

Final report: November 24, 2026

Presentation and demo: November 24 - December 7, 2026

Each member must contribute to the final presentation.

## Optional Enhancement

Machine-learning cash demand forecasting may be
considered only after the core functionality is complete.
