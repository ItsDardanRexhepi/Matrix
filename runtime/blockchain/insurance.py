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
            "properties": {
                "action": {"type": "string", "enum": ["create_policy", "file_claim", "get_policy", "process_payout"]},
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
        return json.dumps({
            "policy_id": params.get("policy_id", ""),
            "note": "Query EAS attestations for policy details",
            "network": self.network,
        })

    async def _process_payout(self, params: dict) -> str:
        return json.dumps({
            "policy_id": params.get("policy_id", ""),
            "status": "payout_prepared",
            "note": "Payout execution requires verified claim. Gas covered by platform.",
        })
