"""
Insurance — on-chain insurance policy management on Base L2.

Create policies, file claims, process payouts via smart contracts.
All gas covered by the platform.
"""

import json
import logging
import time

from runtime.blockchain.interface import BlockchainInterface

logger = logging.getLogger(__name__)


class Insurance(BlockchainInterface):

    @property
    def name(self) -> str:
        return "insurance"

    @property
    def description(self) -> str:
        return "On-chain insurance: create policies, file claims, process payouts. Gas covered by platform."

    @property
    def parameters(self) -> dict:
        return {
            "type": "object",
            # NEW-76: "process_payout" removed from this enum — it sent
            # platform funds to a caller-supplied address with no policy or
            # claim verification. Disabled at the leaf in _process_payout.
            "properties": {
                "action": {"type": "string", "enum": ["create_policy", "file_claim", "get_policy"]},
                "policy_contract": {"type": "string"},
                "policy_id": {"type": "string"},
                "coverage_amount": {"type": "string"},
                "premium": {"type": "string"},
                "beneficiary": {"type": "string"},
                "claim_details": {"type": "object"},
            },
            "required": ["action"],
        }

    async def execute(self, **kwargs) -> str:
        action = kwargs.get("action", "")
        if action == "create_policy":
            return await self._create_policy(kwargs)
        elif action == "file_claim":
            return await self._file_claim(kwargs)
        elif action == "get_policy":
            return await self._get_policy(kwargs)
        elif action == "process_payout":
            return await self._process_payout(kwargs)
        return f"Unknown insurance action: {action}"

    async def _create_policy(self, params: dict) -> str:
        """Create an insurance policy attested on-chain."""
        from runtime.blockchain.eas_client import EASClient
        client = EASClient(self.config)
        result = await client.attest(
            action="insurance_policy_create",
            agent="neo",
            details={
                "coverage_amount": params.get("coverage_amount", "0"),
                "premium": params.get("premium", "0"),
                "beneficiary": params.get("beneficiary", ""),
                "created_at": int(time.time()),
            },
            recipient=params.get("beneficiary", "0x0000000000000000000000000000000000000000"),
        )
        return json.dumps(result, indent=2, default=str)

    async def _file_claim(self, params: dict) -> str:
        """File an insurance claim attested on-chain."""
        from runtime.blockchain.eas_client import EASClient
        client = EASClient(self.config)
        result = await client.attest(
            action="insurance_claim",
            agent="neo",
            details={
                "policy_id": params.get("policy_id", ""),
                "claim_details": params.get("claim_details", {}),
                "filed_at": int(time.time()),
            },
        )
        return json.dumps(result, indent=2, default=str)

    async def _get_policy(self, params: dict) -> str:
        """Query an insurance policy by verifying its EAS attestation on-chain."""
        try:
            policy_id = params.get("policy_id", "")
            if not policy_id:
                return json.dumps({"status": "error", "error": "policy_id (EAS attestation UID) is required"})

            from runtime.blockchain.eas_client import EASClient
            client = EASClient(self.config)
            result = await client.verify(policy_id)

            return json.dumps({
                "policy_id": policy_id,
                "attestation": result,
                "network": self.network,
            }, indent=2, default=str)
        except Exception as e:
            return json.dumps({
                "policy_id": params.get("policy_id", ""),
                "status": "error",
                "error": str(e),
                "hint": "Ensure blockchain.eas_contract and blockchain.rpc_url are configured.",
            }, indent=2)

    async def _process_payout(self, params: dict) -> str:
        """DISABLED (NEW-76). Refuses; sends no value.

        WHAT THIS USED TO DO, and why it is the most severe finding of the
        census: it took ``beneficiary`` and ``coverage_amount`` FROM THE
        CALLER, signed with ``blockchain.paymaster_private_key``, and
        broadcast a real ETH transfer:

            beneficiary = params.get("beneficiary", "")
            amount      = params.get("coverage_amount", "0")
            tx = {"to": Web3.to_checksum_address(beneficiary),
                  "value": self.web3.to_wei(float(amount), "ether"), ...}
            signed  = account.sign_transaction(tx)
            tx_hash = self.web3.eth.send_raw_transaction(signed.raw_transaction)

        There was NO policy lookup, NO claim verification, NO attestation
        check, and NO ownership check. ``policy_id`` was accepted and used
        only to decorate the attestation written AFTER the money left — a
        receipt naming a policy nobody ever read. This is not insurance with
        weak verification; it is an unauthenticated withdrawal on the platform
        treasury wearing an insurance name, callable with an arbitrary
        destination address and an arbitrary amount.

        HOW IT WAS REACHED, and why seven domains of surface-tracing missed
        it: ``process_payout`` appears on NONE of the five surfaces this audit
        had been tracing — not ACTION_MAP, the capability catalog, the gateway
        route tables, the intent table, or extensions/registry.json. It is
        reachable through the AGENT TOOL surface (registry.py registers this
        class for ToolDispatcher), a different dispatcher entirely. Tracing
        one dispatcher is not tracing reachability.

        It was not live only because ``_require_config`` rejects the shipped
        placeholder credentials — armed-on-CREDENTIAL, and credentials land
        earlier in a deployment than contracts do.

        Disabled at the LEAF rather than only unadvertised, because an
        unregistered path is still a callable path. The action is also removed
        from the tool's parameter enum so the model is not offered it.

        LIFTING CONDITION — all four, not any:
          1. the payout resolves a real policy record and verifies it exists;
          2. it verifies an APPROVED claim against that policy, decided by an
             authority the beneficiary does not control;
          3. the destination is taken FROM the policy, never from the caller;
          4. the amount is taken from the policy's coverage, never from the
             caller, and is checked against remaining coverage.
        Until all four hold, this must not send value. Pinned by
        tests/test_insurance_payout_disabled.py.
        """
        return json.dumps({
            "status": "error",
            "error_category": "not_implemented",
            "success": False,
            "value_moved": False,
            "error": (
                "Insurance payout is disabled. This entry point transferred "
                "platform funds to a caller-supplied address with no policy "
                "lookup, no claim verification and no ownership check. It "
                "will not send value until payouts are resolved from a "
                "verified policy and an approved claim."
            ),
            "disabled_by": "NEW-76",
        }, indent=2)
