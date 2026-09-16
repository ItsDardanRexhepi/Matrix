"""
Cross-Border Payments — international transfers via stablecoins on Base L2.

Send stablecoin payments across borders with on-chain attestation for
compliance and audit trails. All gas covered by the platform.
"""

import json
import logging
import time

from runtime.blockchain.interface import BlockchainInterface
from runtime.protocols.outcome_truth import refusal

logger = logging.getLogger(__name__)


class CrossBorderPayments(BlockchainInterface):

    @property
    def name(self) -> str:
        return "crossborder_payment"

    @property
    def description(self) -> str:
        return "Cross-border payments via stablecoins with compliance attestations. Gas covered by platform."

    @property
    def parameters(self) -> dict:
        return {
            "type": "object",
            "properties": {
                "action": {"type": "string", "enum": ["send", "estimate", "track", "compliance_check"]},
                "token": {"type": "string", "description": "Stablecoin (USDC, DAI)"},
                "amount": {"type": "string"},
                "to": {"type": "string"},
                "from_country": {"type": "string"},
                "to_country": {"type": "string"},
                "reference": {"type": "string", "description": "Payment reference/memo"},
                "tx_hash": {"type": "string"},
            },
            "required": ["action"],
        }

    async def execute(self, **kwargs) -> str:
        action = kwargs.get("action", "")
        if action == "send":
            return await self._send(kwargs)
        elif action == "estimate":
            return await self._estimate(kwargs)
        elif action == "track":
            return await self._track(kwargs)
        elif action == "compliance_check":
            return await self._compliance_check(kwargs)
        return refusal(
            f"Unknown crossborder action: {action}",
            code="unknown_action")

    async def _send(self, params: dict) -> str:
        """Prepare a cross-border stablecoin payment and attest it for compliance.

        TWO CLAIMS WERE BEING MADE THAT THIS METHOD CANNOT SUPPORT, and it had
        the evidence against both in hand.

        The status was the fixed string `"payment_attested"`. The attestation is
        RIGHT THERE in `attestation`, and `EASClient.attest` reports a refusal by
        RETURNING one — `{"status": "skipped", "reason": "blockchain not
        configured"}` on the shipped config, `{"status": "failed", "error": ...}`
        on a revert. Neither raises, so an unconfigured deployment answered every
        cross-border payment with "attested" and had attested nothing.

        And no transfer happens here on ANY path — the method's own `next_step`
        says the transfer is a different capability. `value_moved: False` is
        emitted unconditionally, so the dispatcher cannot EAS-attest this as a
        completed payment or announce it on the public feed as one, whatever the
        compliance attestation did.
        """
        from runtime.blockchain.eas_client import EASClient
        from runtime.protocols.outcome_truth import SUCCESS, report_of

        # First, attest the payment for compliance
        client = EASClient(self.config)
        attestation = await client.attest(
            action="crossborder_payment",
            agent="neo",
            details={
                "token": params.get("token", "USDC"),
                "amount": params.get("amount", "0"),
                "to": params.get("to", ""),
                "from_country": params.get("from_country", ""),
                "to_country": params.get("to_country", ""),
                "reference": params.get("reference", ""),
                "timestamp": int(time.time()),
            },
            recipient=params.get("to", "0x0000000000000000000000000000000000000000"),
        )

        attested = report_of(attestation) is SUCCESS
        common = {
            "attested": attested,
            "attestation": attestation,
            # Emitted on BOTH paths: no transfer is made by this call under any
            # circumstances, whatever the attestation did.
            "settled": False,
            "value_moved": False,
            "next_step": "Execute stablecoin transfer via stablecoin capability",
            "gas_paid_by": "platform (The Matrix)",
        }
        # `prepared` and `not_ready` are both already in the dispatcher's
        # `_NON_OUTCOME_STATUSES`: neither is a payment, and this method makes
        # no payment. Written as two literal branches rather than one
        # conditional so that the status-vocabulary walker in
        # tests/test_refusals_are_not_attested.py can still SEE them — a status
        # a census cannot read is a status nobody classifies.
        if attested:
            body = {
                "status": "prepared",
                **common,
                "disclosure": (
                    "No transfer was made by this call. The compliance "
                    "attestation was written on-chain; the stablecoin transfer "
                    "is a separate action."
                ),
            }
        else:
            body = {
                "status": "not_ready",
                **common,
                "disclosure": (
                    "No transfer was made by this call, and the compliance "
                    "attestation DID NOT complete — the payment is not cleared "
                    "to send."
                ),
            }
        return json.dumps(body, indent=2, default=str)

    async def _estimate(self, params: dict) -> str:
        """Estimate cross-border payment cost."""
        return json.dumps({
            "token": params.get("token", "USDC"),
            "amount": params.get("amount", "0"),
            "gas_cost": "Covered by platform (The Matrix)",
            "transfer_fee": "$0.00 (no platform fee)",
            "estimated_time": "< 2 minutes (Base L2 finality)",
            "network": self.network,
        }, indent=2)

    async def _track(self, params: dict) -> str:
        """Track a cross-border payment by transaction hash."""
        tx_hash = params.get("tx_hash", "")
        try:
            receipt = self.web3.eth.get_transaction_receipt(tx_hash)
            return json.dumps({
                "tx_hash": tx_hash,
                "status": "confirmed" if receipt["status"] == 1 else "failed",
                "block_number": receipt["blockNumber"],
                "gas_used": receipt["gasUsed"],
            })
        except Exception as e:
            return json.dumps({"tx_hash": tx_hash, "status": "not_found", "error": str(e)})

    async def _compliance_check(self, params: dict) -> str:
        """Check compliance for a cross-border payment."""
        return json.dumps({
            "from_country": params.get("from_country", ""),
            "to_country": params.get("to_country", ""),
            "amount": params.get("amount", "0"),
            "token": params.get("token", "USDC"),
            "compliance_status": "requires_review",
            "note": "Compliance verification should be performed before executing large transfers",
        }, indent=2)
