"""
Cross-Border Payments — international transfers via stablecoins on Base L2.

Send stablecoin payments across borders with on-chain attestation for
compliance and audit trails. Gas is sponsored within this deployment's
sponsorship policy (runtime/blockchain/sponsorship.py describe_gas_policy), and
the stablecoin transfer this hands off to charges its tiered transfer fee.
"""

import json
import logging
import time

from runtime.blockchain.interface import BlockchainInterface

logger = logging.getLogger(__name__)


class CrossBorderPayments(BlockchainInterface):

    @property
    def name(self) -> str:
        return "crossborder_payment"

    @property
    def description(self) -> str:
        return ("Cross-border payments via stablecoins with compliance attestations. "
                "Gas is sponsored within the deployment's sponsorship policy; the "
                "stablecoin transfer charges a tiered fee (see estimate).")

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
        return f"Unknown crossborder action: {action}"

    async def _send(self, params: dict) -> str:
        """Send a cross-border stablecoin payment with compliance attestation."""
        from runtime.blockchain.eas_client import EASClient

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

        return json.dumps({
            "status": "payment_attested",
            "attestation": attestation,
            "next_step": "Execute stablecoin transfer via stablecoin capability",
            "gas_paid_by": "platform (0pnMatrx)",
        }, indent=2, default=str)

    async def _estimate(self, params: dict) -> str:
        """Estimate cross-border payment cost.

        This used to quote "gas_cost: Covered by platform" and "transfer_fee:
        $0.00 (no platform fee)" unconditionally. Gas is sponsored only within
        the configured policy, and `_send` hands off to the stablecoin transfer,
        which deducts a tiered platform fee. Both are now derived: the gas
        statement from the sponsorship config, the fee from the same
        StablecoinService.get_fee the transfer charges with.
        """
        from runtime.blockchain.services.stablecoin.service import StablecoinService
        from runtime.blockchain.sponsorship import describe_gas_policy

        raw_amount = params.get("amount", "0")
        try:
            transfer_fee = await StablecoinService(self.config).get_fee(float(raw_amount))
        except (TypeError, ValueError):
            transfer_fee = {"fee": None, "rate": None, "tier": "invalid",
                            "reason": f"amount {raw_amount!r} is not a number"}
        return json.dumps({
            "token": params.get("token", "USDC"),
            "amount": raw_amount,
            "gas_policy": describe_gas_policy(self.config),
            "transfer_fee": transfer_fee,
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
