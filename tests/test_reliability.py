"""Part 4 tests: concurrency control, transfer saga, failure detection, recovery."""

import threading
from unittest.mock import Mock, patch

import pytest

from banking.database import BranchDatabase
from banking.service import BankingError, BankingService
from communication.client import BranchCommunicationError, PeerRejectedError
from reliability.audit import local_audit
from reliability.failure_detector import DOWN, ONLINE, SUSPECTED, FailureDetector
from reliability.recovery import RecoveryWorker
from reliability.transfer_saga import COMPLETED, FAILED, PENDING, TransferSaga

START_CASH = 2_000_000
RESERVE = 500_000


@pytest.fixture
def db(tmp_path):
    database = BranchDatabase("C", db_dir=str(tmp_path))
    database.seed_from_config({"cash": START_CASH, "employees": 5, "minimum_reserve": RESERVE})
    return database


@pytest.fixture
def banking(db):
    return BankingService(db)


def cash(banking):
    return banking.get_status()["cash"]


# ---------------------------------------------------------------- concurrency


def test_concurrent_withdrawals_never_break_the_reserve(banking, db):
    """50 tellers withdraw $1,000 at the same moment; only 15 can fit above the reserve."""
    amount = 100_000
    barrier = threading.Barrier(50)
    ok, refused = [], []

    def teller():
        barrier.wait()  # release all threads at the same instant
        try:
            banking.withdraw(amount)
            ok.append(1)
        except BankingError:
            refused.append(1)

    threads = [threading.Thread(target=teller) for _ in range(50)]
    for t in threads:
        t.start()
    for t in threads:
        t.join()

    assert len(ok) == (START_CASH - RESERVE) // amount == 15
    assert len(refused) == 35
    assert cash(banking) == RESERVE
    assert local_audit(db, START_CASH)["ledger_consistent"]


def test_concurrent_transfers_cannot_overspend(banking, db):
    """20 simultaneous outgoing transfers of $1,000: only 15 may be debited."""
    client = Mock()
    client.send_transfer.return_value = {"status": "ok"}
    saga = TransferSaga("C", db, client)
    barrier = threading.Barrier(20)
    results = []

    def send(i):
        barrier.wait()
        try:
            results.append(saga.start("A", 100_000, tx_id=f"TX-{i}")["status"])
        except BankingError:
            results.append("REFUSED")

    threads = [threading.Thread(target=send, args=(i,)) for i in range(20)]
    for t in threads:
        t.start()
    for t in threads:
        t.join()

    assert results.count(COMPLETED) == 15
    assert results.count("REFUSED") == 5
    assert cash(banking) == RESERVE
    assert local_audit(db, START_CASH)["ledger_consistent"]


def test_duplicate_deposit_is_applied_once_under_concurrency(banking):
    barrier = threading.Barrier(10)

    def deposit():
        barrier.wait()
        banking.deposit(50_000, tx_id="SAME-DEPOSIT")

    threads = [threading.Thread(target=deposit) for _ in range(10)]
    for t in threads:
        t.start()
    for t in threads:
        t.join()

    assert cash(banking) == START_CASH + 50_000


# -------------------------------------------------------------- transfer saga


def test_overdraft_transfer_is_refused_before_contacting_destination(banking, db):
    """Regression test for the old bug: destination was credited first."""
    client = Mock()
    saga = TransferSaga("C", db, client)

    with pytest.raises(BankingError, match="minimum reserve"):
        saga.start("A", 1_900_000)

    client.send_transfer.assert_not_called()
    assert cash(banking) == START_CASH


def test_successful_transfer_is_completed(banking, db):
    client = Mock()
    saga = TransferSaga("C", db, client)

    result = saga.start("A", 300_000, tx_id="TX-OK")

    assert result["status"] == COMPLETED
    assert cash(banking) == START_CASH - 300_000
    client.send_transfer.assert_called_once_with(
        target_branch_id="A", source_branch_id="C", amount=300_000, tx_id="TX-OK"
    )


def test_unreachable_destination_keeps_transfer_pending(banking, db):
    client = Mock()
    client.send_transfer.side_effect = BranchCommunicationError("Branch A is unavailable")
    saga = TransferSaga("C", db, client)

    result = saga.start("A", 300_000, tx_id="TX-WAIT")

    assert result["status"] == PENDING
    assert cash(banking) == START_CASH - 300_000  # money is held, not lost
    assert [p["tx_id"] for p in saga.pending()] == ["TX-WAIT"]


def test_rejected_transfer_is_refunded(banking, db):
    client = Mock()
    client.send_transfer.side_effect = PeerRejectedError("bad request")
    saga = TransferSaga("C", db, client)

    result = saga.start("A", 300_000, tx_id="TX-NO")

    assert result["status"] == FAILED
    assert cash(banking) == START_CASH
    assert saga.pending() == []
    assert local_audit(db, START_CASH)["ledger_consistent"]


def test_refund_happens_only_once_even_if_two_threads_race(banking, db):
    client = Mock()
    client.send_transfer.side_effect = BranchCommunicationError("down")
    saga = TransferSaga("C", db, client)
    saga.start("A", 300_000, tx_id="TX-RACE")

    client.send_transfer.side_effect = PeerRejectedError("rejected")
    threads = [threading.Thread(target=saga.deliver, args=("TX-RACE",)) for _ in range(5)]
    for t in threads:
        t.start()
    for t in threads:
        t.join()

    assert cash(banking) == START_CASH  # refunded exactly once, not 5 times


def test_retrying_same_tx_id_does_not_debit_twice(banking, db):
    client = Mock()
    saga = TransferSaga("C", db, client)

    saga.start("A", 300_000, tx_id="TX-ONCE")
    again = saga.start("A", 300_000, tx_id="TX-ONCE")

    assert again["duplicate"] is True
    assert cash(banking) == START_CASH - 300_000


def test_pending_transfer_survives_restart_and_is_recovered(tmp_path):
    """Simulate a crash: new objects on the same SQLite file pick up the outbox."""
    db1 = BranchDatabase("C", db_dir=str(tmp_path))
    db1.seed_from_config({"cash": START_CASH, "employees": 5, "minimum_reserve": RESERVE})
    down_client = Mock()
    down_client.send_transfer.side_effect = BranchCommunicationError("down")
    TransferSaga("C", db1, down_client).start("A", 300_000, tx_id="TX-CRASH")

    # "Restart" the branch: brand new objects, same database file.
    db2 = BranchDatabase("C", db_dir=str(tmp_path))
    up_client = Mock()
    saga2 = TransferSaga("C", db2, up_client)
    RecoveryWorker(saga2).run_once()

    up_client.send_transfer.assert_called_once()
    assert saga2.pending() == []
    assert saga2._get("TX-CRASH")["status"] == COMPLETED


def test_known_down_peer_is_queued_without_waiting(banking, db):
    client = Mock()
    detector = Mock()
    detector.is_down.return_value = True
    saga = TransferSaga("C", db, client, detector=detector)

    result = saga.start("A", 100_000)

    assert result["status"] == PENDING
    client.send_transfer.assert_not_called()


# ---------------------------------------------------------- failure detector


def make_detector(**kwargs):
    return FailureDetector(
        "A",
        {"A": "http://a", "B": "http://b", "C": "http://c"},
        suspect_after=1,
        down_after=3,
        **kwargs,
    )


def ok_response(started_at=1.0):
    resp = Mock()
    resp.raise_for_status.return_value = None
    resp.json.return_value = {"started_at": started_at}
    return resp


def test_detector_goes_online_suspected_down():
    detector = make_detector()
    with patch("reliability.failure_detector.requests.get") as get:
        get.return_value = ok_response()
        detector.check_once()
        assert detector.state("B") == ONLINE

        get.side_effect = ConnectionError("refused")
        detector.check_once()
        assert detector.state("B") == SUSPECTED
        detector.check_once()
        assert detector.state("B") == SUSPECTED
        detector.check_once()
        assert detector.state("B") == DOWN
        assert detector.is_down("B")


def test_detector_calls_on_recover_when_peer_comes_back():
    recovered = []
    detector = make_detector(on_recover=recovered.append)
    with patch("reliability.failure_detector.requests.get") as get:
        get.side_effect = ConnectionError("refused")
        for _ in range(3):
            detector.check_once()
        get.side_effect = None
        get.return_value = ok_response()
        detector.check_once()

    assert detector.state("B") == ONLINE
    assert sorted(recovered) == ["B", "C"]


def test_detector_notices_a_fast_restart():
    """Peer crashed and restarted between heartbeats: started_at changes."""
    recovered = []
    detector = make_detector(on_recover=recovered.append)
    with patch("reliability.failure_detector.requests.get") as get:
        get.return_value = ok_response(started_at=1.0)
        detector.check_once()
        get.return_value = ok_response(started_at=2.0)
        detector.check_once()

    assert "B" in recovered
