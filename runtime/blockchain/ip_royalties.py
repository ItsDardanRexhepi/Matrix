"""
IP & Royalties — intellectual property management and royalty distribution on Base L2.

Register IP on-chain, configure royalty splits, distribute payments.
All gas covered by the platform.
"""

import json
import logging
import time

from runtime.blockchain.interface import BlockchainInterface

logger = logging.getLogger(__name__)


class IPRoyalties(BlockchainInterface):

    @property
    def name(self) -> str:
        return "ip_royalties"

    @property
    def description(self) -> str:
        return "IP management and royalty distribution: register IP, set royalty splits, distribute payments. Gas covered by platform."

    @property
    def parameters(self) -> dict:
        return {
            "type": "object",
            "properties": {
                "action": {"type": "string", "enum": ["register_ip", "set_royalties", "distribute", "get_ip"]},
                "ip_name": {"type": "string"},
                "ip_type": {"type": "string", "description": "Type: patent, copyright, trademark, license"},
                "owner": {"type": "string"},
                "royalty_recipients": {"type": "array", "items": {"type": "object"}, "description": "List of {address, share_bps}"},
                "ip_id": {"type": "string"},
                "amount": {"type": "string"},
                "token_address": {"type": "string"},
            },
            "required": ["action"],
        }

    async def execute(self, **kwargs) -> str:
        action = kwargs.get("action", "")
        if action == "register_ip":
            return await self._register_ip(kwargs)
        elif action == "set_royalties":
            return await self._set_royalties(kwargs)
        elif action == "distribute":
            return await self._distribute(kwargs)
        elif action == "get_ip":
            return await self._get_ip(kwargs)
        return f"Unknown IP action: {action}"

    async def _register_ip(self, params: dict) -> str:
        """Register intellectual property on-chain via EAS attestation."""
        from runtime.blockchain.eas_client import EASClient
        client = EASClient(self.config)
        result = await client.attest(
            action="ip_registration",
            agent="neo",
            details={
                "ip_name": params.get("ip_name", ""),
                "ip_type": params.get("ip_type", "copyright"),
                "owner": params.get("owner", self.platform_wallet),
                "registered_at": int(time.time()),
            },
            recipient=params.get("owner", "0x0000000000000000000000000000000000000000"),
        )
        return json.dumps(result, indent=2, default=str)

    async def _set_royalties(self, params: dict) -> str:
        """Configure royalty split for an IP asset."""
        recipients = params.get("royalty_recipients", [])
        total_bps = sum(r.get("share_bps", 0) for r in recipients)
        if total_bps > 10000:
            return "Error: total royalty shares exceed 100% (10000 bps)"
        return json.dumps({
            "ip_id": params.get("ip_id", ""),
            "royalty_config": recipients,
            "total_bps": total_bps,
            "status": "configured",
            "note": "Royalty distribution will use this split. Gas covered by platform.",
        }, indent=2)

    async def _distribute(self, params: dict) -> str:
        """Distribute royalty payments. Gas covered by platform."""
        return json.dumps({
            "ip_id": params.get("ip_id", ""),
            "amount": params.get("amount", "0"),
            "status": "distribution_prepared",
            "note": "Use payment capability to execute individual transfers. Gas covered by platform.",
        }, indent=2)

    async def _get_ip(self, params: dict) -> str:
        return json.dumps({
            "ip_id": params.get("ip_id", ""),
            "note": "Query EAS attestations for IP registration details",
            "network": self.network,
        })
