"""
Identity — on-chain identity verification and management.

Supports ENS-style name resolution, identity attestations via EAS,
and wallet-to-identity mapping. All gas covered by the platform.
"""

import json
import logging

from runtime.blockchain.interface import BlockchainInterface

logger = logging.getLogger(__name__)


class Identity(BlockchainInterface):

    @property
    def name(self) -> str:
        return "identity"

    @property
    def description(self) -> str:
        return "On-chain identity verification: resolve names, create identity attestations, manage wallet mappings. Gas covered by platform."

    @property
    def parameters(self) -> dict:
        return {
            "type": "object",
            "properties": {
                "action": {"type": "string", "enum": ["resolve", "register", "verify", "lookup"]},
                "name": {"type": "string", "description": "ENS/Basename to resolve or register"},
                "address": {"type": "string", "description": "Wallet address"},
                "claims": {"type": "object", "description": "Identity claims to attest"},
            },
            "required": ["action"],
        }

    async def execute(self, **kwargs) -> str:
        action = kwargs.get("action", "")
        if action == "resolve":
            return await self._resolve(kwargs)
        elif action == "register":
            return await self._register(kwargs)
        elif action == "verify":
            return await self._verify(kwargs)
        elif action == "lookup":
            return await self._lookup(kwargs)
        return f"Unknown identity action: {action}"

    async def _resolve(self, params: dict) -> str:
        """Resolve a name (ENS/Basename) to an address."""
        try:
            name = params.get("name", "")
            if not name:
                return "Error: name is required"
            address = self.web3.ens.address(name) if hasattr(self.web3, 'ens') and self.web3.ens else None
            if address:
                return json.dumps({"name": name, "address": address, "resolved": True})
            return json.dumps({"name": name, "resolved": False, "note": "Name not found or ENS not available on this network"})
        except Exception as e:
            return f"Resolve failed: {e}"

    async def _register(self, params: dict) -> str:
        """Register an identity attestation on-chain. Gas covered by platform."""
        name = params.get("name", "")
        address = params.get("address", self.platform_wallet)
        claims = params.get("claims", {})
        return json.dumps({
            "status": "registration_prepared",
            "name": name,
            "address": address,
            "claims": claims,
            "note": "Use EAS attestation to create on-chain identity record. Gas covered by platform.",
        }, indent=2)

    async def _verify(self, params: dict) -> str:
        """Verify an on-chain identity."""
        address = params.get("address", "")
        try:
            balance = self.web3.eth.get_balance(address) if address else 0
            code = self.web3.eth.get_code(address) if address else b""
            return json.dumps({
                "address": address,
                "is_contract": len(code) > 0,
                "has_balance": balance > 0,
                "balance_eth": str(self.web3.from_wei(balance, "ether")),
                "network": self.network,
            }, indent=2)
        except Exception as e:
            return f"Verify failed: {e}"

    async def _lookup(self, params: dict) -> str:
        """Reverse lookup — address to name."""
        address = params.get("address", "")
        try:
            name = self.web3.ens.name(address) if hasattr(self.web3, 'ens') and self.web3.ens else None
            return json.dumps({"address": address, "name": name or "not_found"})
        except Exception as e:
            return f"Lookup failed: {e}"
