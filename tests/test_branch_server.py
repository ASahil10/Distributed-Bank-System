
import unittest
from unittest.mock import patch
from branch_nodes import branch_server
from banking.service import BankingError


class TestBranchServer(unittest.TestCase):

    def setUp(self):
        # Create a test client without starting the Flask server
        self.client = branch_server.app.test_client()

        # Mock the banking service so tests don't change real data
        patcher = patch.object(branch_server, "banking")
        self.mock_banking = patcher.start()
        self.addCleanup(patcher.stop)

        # Starting values for our test branch
        self.mock_banking.get_status.return_value = {
            "branch_id": "A",
            "cash": 10000,
            "employees": 5,
            "minimum_reserve": 2000,
            "reserve_warning": False
        }

    def test_status(self):
        # Check if the branch status is returned correctly
        response = self.client.get("/status")

        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.get_json()["cash"], 10000)
        self.assertEqual(response.get_json()["employees"], 5)

    def test_deposit(self):
        # Set the expected result of a successful deposit
        self.mock_banking.deposit.return_value = {
            "cash": 10500,
            "tx_id": "test-deposit"
        }

        response = self.client.post(
            "/deposit",
            json={"amount": 500}
        )

        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.get_json()["cash"], 10500)

        self.mock_banking.deposit.assert_called_once_with(
            amount=500,
            tx_id=None,
            note=""
        )

    def test_invalid_deposit(self):
        # Negative deposit amounts should be rejected
        response = self.client.post(
            "/deposit",
            json={"amount": -100}
        )

        self.assertEqual(response.status_code, 400)
        self.mock_banking.deposit.assert_not_called()

    def test_withdraw(self):
        # Set the expected result of a successful withdrawal
        self.mock_banking.withdraw.return_value = {
            "cash": 9500,
            "tx_id": "test-withdraw"
        }

        response = self.client.post(
            "/withdraw",
            json={"amount": 500}
        )

        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.get_json()["cash"], 9500)

        self.mock_banking.withdraw.assert_called_once_with(
            amount=500,
            allow_below_reserve=False,
            tx_id=None,
            note=""
        )

    def test_invalid_withdraw(self):
        # Negative withdrawal amounts should be rejected
        response = self.client.post(
            "/withdraw",
            json={"amount": -500}
        )

        self.assertEqual(response.status_code, 400)
        self.mock_banking.withdraw.assert_not_called()

    def test_minimum_reserve(self):
        # Simulate a withdrawal that breaks the reserve rule
        self.mock_banking.withdraw.side_effect = BankingError(
            "insufficient cash above minimum reserve"
        )

        response = self.client.post(
            "/withdraw",
            json={"amount": 9000}
        )

        self.assertEqual(response.status_code, 409)
        self.assertEqual(
            response.get_json()["error"],
            "insufficient cash above minimum reserve"
        )

    def test_transactions(self):
        # Check if the transactions endpoint works
        self.mock_banking.get_transactions.return_value = []

        response = self.client.get("/transactions")

        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.get_json()["transactions"], [])

        self.mock_banking.get_transactions.assert_called_once_with(
            limit=50
        )

    def test_update_employees(self):
        # Check if the employee count can be updated
        self.mock_banking.set_employee_count.return_value = {
            "branch_id": "A",
            "employees": 8
        }

        response = self.client.put(
            "/employees",
            json={"employees": 8}
        )

        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.get_json()["employees"], 8)

        self.mock_banking.set_employee_count.assert_called_once_with(
            8
        )


if __name__ == "__main__":
    unittest.main()
