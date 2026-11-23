
import unittest

from branch_nodes import branch_server
from branch_nodes.branch_config import get_branch_config


class TestBranchServer(unittest.TestCase):

    def setUp(self):
        # Create a test client without starting a real server
        self.client = branch_server.app.test_client()

        # Save the original branch information
        self.original_state = branch_server.state.copy()

        # Set temporary values for testing
        branch_server.state["cash"] = 10000
        branch_server.state["minimum_reserve"] = 2000

    def tearDown(self):
        # Restore original values after each test
        branch_server.state.clear()
        branch_server.state.update(self.original_state)

    def test_branch_config(self):
        # Check that branches A, B and C exist
        for branch_id in ["A", "B", "C"]:
            config = get_branch_config(branch_id)

            self.assertIn("cash", config)
            self.assertIn("employees", config)
            self.assertIn("minimum_reserve", config)

    def test_invalid_branch(self):
        # Branch D should not exist
        with self.assertRaises(ValueError):
            get_branch_config("D")

    def test_status(self):
        # Check if the server returns its status
        response = self.client.get("/status")

        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json["cash"], 10000)

    def test_deposit(self):
        # Deposit 500 cents into the branch
        response = self.client.post(
            "/deposit",
            json={"amount": 500}
        )

        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json["cash"], 10500)

    def test_withdraw(self):
        # Withdraw 500 cents from the branch
        response = self.client.post(
            "/withdraw",
            json={"amount": 500}
        )

        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json["cash"], 9500)

    def test_minimum_reserve(self):
        # Try withdrawing too much money
        response = self.client.post(
            "/withdraw",
            json={"amount": 9000}
        )

        # Withdrawal should be rejected
        self.assertEqual(response.status_code, 409)
        self.assertEqual(branch_server.state["cash"], 10000)

    def test_invalid_deposit(self):
        # Negative deposits should not be allowed
        response = self.client.post(
            "/deposit",
            json={"amount": -100}
        )

        self.assertEqual(response.status_code, 400)

    def test_invalid_withdraw(self):
        # Zero-dollar withdrawals should not be allowed
        response = self.client.post(
            "/withdraw",
            json={"amount": 0}
        )

        self.assertEqual(response.status_code, 400)


if __name__ == "__main__":
    unittest.main()
