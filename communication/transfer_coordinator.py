"""Coordinates inter-branch transfers using stable transaction identifiers."""

import uuid

from banking.service import BankingError, BankingService
from communication.client import BranchClient, BranchCommunicationError


class TransferCoordinator:
    """Coordinates outgoing debit and incoming peer notification."""

    def __init__(
        self,
        branch_id: str,
        banking: BankingService,
        client: BranchClient,
    ):
        self.branch_id = branch_id
        self.banking = banking
        self.client = client

    def transfer(
        self,
        target_branch_id: str,
        amount: int,
        tx_id: str | None = None,
    ) -> dict:
        if target_branch_id == self.branch_id:
            raise BankingError("target_branch_id must be a different branch.")

        tx_id = tx_id or str(uuid.uuid4())

        # First, ask the destination to durably credit the transfer. Repeating
        # this message is safe because transfer_in() rejects duplicate tx_ids.
        incoming = self.client.send_transfer(
            target_branch_id=target_branch_id,
            source_branch_id=self.branch_id,
            amount=amount,
            tx_id=tx_id,
        )

        # Debit the source using the same stable transaction identifier.
        # The banking service also treats repeated tx_ids idempotently.
        try:
            outgoing = self.banking.transfer_out(
                amount=amount,
                target_branch_id=target_branch_id,
                allow_below_reserve=False,
                tx_id=tx_id,
            )
        except Exception as exc:
            # This implementation avoids losing money when a destination is
            # offline. A production system would add compensation or 2PC for
            # the case where the destination credit succeeds but this debit fails.
            raise BranchCommunicationError(
                "Destination accepted the transfer, but the source debit failed; "
                f"manual reconciliation is required for tx_id {tx_id}: {exc}"
            ) from exc

        return {
            "tx_id": tx_id,
            "source_branch_id": self.branch_id,
            "target_branch_id": target_branch_id,
            "amount": amount,
            "status": "COMPLETED",
            "source": outgoing,
            "destination": incoming,
        }
