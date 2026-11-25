"""Automated tests for Part 2: distributed communication and synchronization."""

from unittest.mock import Mock, patch

import pytest
import requests

from communication.client import BranchClient, BranchCommunicationError
from communication.transfer_coordinator import TransferCoordinator


@pytest.fixture
def branch_urls():
    return {
        "A": "http://127.0.0.1:5001",
        "B": "http://127.0.0.1:5002",
        "C": "http://127.0.0.1:5003",
    }


def response(status_code, body):
    result = Mock()
    result.status_code = status_code
    result.json.return_value = body
    return result


def test_get_status_sends_http_message(branch_urls):
    client = BranchClient(branch_urls, max_retries=0)

    with patch("communication.client.requests.request") as request_mock:
        request_mock.return_value = response(200, {"branch_id": "B", "cash": 3000000})

        result = client.get_status("B")

    assert result["branch_id"] == "B"
    request_mock.assert_called_once_with(
        method="GET",
        url="http://127.0.0.1:5002/status",
        json=None,
        params=None,
        timeout=3.0,
    )


def test_send_transfer_uses_expected_message_format(branch_urls):
    client = BranchClient(branch_urls, max_retries=0)

    with patch("communication.client.requests.request") as request_mock:
        request_mock.return_value = response(
            200,
            {"branch_id": "B", "tx_id": "TX-001", "cash": 3100000},
        )

        result = client.send_transfer(
            target_branch_id="B",
            source_branch_id="A",
            amount=100000,
            tx_id="TX-001",
        )

    assert result["tx_id"] == "TX-001"
    request_mock.assert_called_once_with(
        method="POST",
        url="http://127.0.0.1:5002/internal/transfer-in",
        json={
            "source_branch_id": "A",
            "amount": 100000,
            "tx_id": "TX-001",
        },
        params=None,
        timeout=3.0,
    )


def test_timeout_is_retried_then_raises(branch_urls):
    client = BranchClient(branch_urls, timeout=0.1, max_retries=2, retry_delay=0)

    with patch("communication.client.requests.request") as request_mock:
        request_mock.side_effect = requests.Timeout("timed out")

        with pytest.raises(BranchCommunicationError):
            client.get_status("B")

    # Initial request plus two retry attempts.
    assert request_mock.call_count == 3


def test_client_error_is_not_retried(branch_urls):
    client = BranchClient(branch_urls, max_retries=2, retry_delay=0)

    with patch("communication.client.requests.request") as request_mock:
        request_mock.return_value = response(400, {"error": "bad request"})

        with pytest.raises(BranchCommunicationError, match="bad request"):
            client.get_status("B")

    assert request_mock.call_count == 1


def test_health_check_marks_unavailable_peer_offline(branch_urls):
    client = BranchClient(branch_urls, max_retries=0)

    def fake_status(branch_id):
        if branch_id == "B":
            raise BranchCommunicationError("Branch B is unavailable")
        return {"branch_id": branch_id, "cash": 2000000}

    client.get_status = fake_status
    result = client.health_check_all(current_branch_id="A")

    assert "A" not in result
    assert result["B"]["online"] is False
    assert result["C"]["online"] is True


def test_transfer_coordinator_uses_same_transaction_id():
    banking = Mock()
    banking.transfer_out.return_value = {
        "tx_id": "TX-SAME",
        "type": "TRANSFER_OUT",
        "cash": 4900000,
    }

    client = Mock()
    client.send_transfer.return_value = {
        "tx_id": "TX-SAME",
        "type": "TRANSFER_IN",
        "cash": 3100000,
    }

    coordinator = TransferCoordinator("A", banking, client)
    result = coordinator.transfer("B", 100000, tx_id="TX-SAME")

    client.send_transfer.assert_called_once_with(
        target_branch_id="B",
        source_branch_id="A",
        amount=100000,
        tx_id="TX-SAME",
    )
    banking.transfer_out.assert_called_once_with(
        amount=100000,
        target_branch_id="B",
        allow_below_reserve=False,
        tx_id="TX-SAME",
    )
    assert result["tx_id"] == "TX-SAME"
    assert result["status"] == "COMPLETED"
