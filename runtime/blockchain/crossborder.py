"""
Cross-Border Payments — international transfers via stablecoins on Base L2.

Attest a cross-border stablecoin payment for compliance and audit trails, then
hand the transfer to the `stablecoin` tool. Gas is sponsored within this
deployment's sponsorship policy (runtime/blockchain/sponsorship.py
describe_gas_policy). The estimate quotes the fee on each path a payment can
take, each from the code that charges it: the `stablecoin` tool's transfer
(no platform fee), the `transfer_stablecoin` capability (tiered fee) and the
`send_payment` capability (cross-border fee, recorded and not settled).
"""

import json
import logging
import time

from runtime.blockchain.interface import BlockchainInterface
from runtime.blockchain.sponsorship import describe_gas_policy
from runtime.protocols.outcome_truth import refusal

logger = logging.getLogger(__name__)


class CrossBorderPayments(BlockchainInterface):

    @property
    def name(self) -> str:
        return "crossborder_payment"

    @property
    def description(self) -> str:
        return ("Cross-border payments via stablecoins with compliance attestations. "
                "Gas is sponsored within the deployment's sponsorship policy. Fees "
                "depend on the path; the estimate quotes each one.")

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

        # First, attest the payment for compliance. The attestation's on-chain
        # RECIPIENT is its subject, and this call pays nobody: naming the payee
        # there put a platform-signed "cross-border payment" on an address the
        # request chose, for a payment that was never made (register
        # entry::U-ATTEST-AXIS, the same axis as identity.register). The payee
        # is still in `details`, which describes what was prepared and which
        # EASClient does not write on-chain; the recipient is the zero address.
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
            recipient="0x0000000000000000000000000000000000000000",
            operation="crossborder.send",
        )

        attested = report_of(attestation) is SUCCESS
        common = {
            "attested": attested,
            "attestation": attestation,
            # Emitted on BOTH paths: no transfer is made by this call under any
            # circumstances, whatever the attestation did.
            "settled": False,
            "value_moved": False,
            "next_step": ("Execute the transfer with the `stablecoin` tool (action "
                          "transfer); it sends the full amount with no platform fee"),
            "gas_policy": describe_gas_policy(self.config),
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
        """Estimate cross-border payment cost.

        This used to quote "gas_cost: Covered by platform" and "transfer_fee:
        $0.00 (no platform fee)" unconditionally. A payment can take three
        paths with three different fees, so each is quoted from the code that
        charges it:

          * `stablecoin` tool transfer (what `_send` names): sends the full
            amount on-chain; no platform fee;
          * `transfer_stablecoin` capability: StablecoinService.get_fee;
          * `send_payment` capability: CrossBorderService.fee_for, on a payment
            that is recorded and not settled.
        """
        from runtime.blockchain.services.cross_border.service import CrossBorderService
        from runtime.blockchain.services.stablecoin.service import StablecoinService

        raw_amount = params.get("amount", "0")
        try:
            amount = float(raw_amount)
            capability_fee = await StablecoinService(self.config).get_fee(amount)
            send_payment_fee = CrossBorderService(self.config).fee_for(amount)
            fees = {
                "stablecoin_tool_transfer": {
                    "fee": 0.0,
                    "note": "the next step named by send: the full amount is transferred",
                },
                "transfer_stablecoin_capability": capability_fee,
                "send_payment_capability": {
                    **send_payment_fee,
                    "note": "recorded, not settled: no value moves",
                },
            }
            transfer_fee = fees["stablecoin_tool_transfer"]
        except (TypeError, ValueError):
            fees = None
            transfer_fee = {"fee": None, "rate": None, "tier": "invalid",
                            "reason": f"amount {raw_amount!r} is not a number"}
        return json.dumps({
            "token": params.get("token", "USDC"),
            "amount": raw_amount,
            "gas_policy": describe_gas_policy(self.config),
            "transfer_fee": transfer_fee,
            "fees_by_path": fees,
            "estimated_time": "< 2 minutes (Base L2 finality)",
            "network": self.network,
        }, indent=2, default=str)

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
