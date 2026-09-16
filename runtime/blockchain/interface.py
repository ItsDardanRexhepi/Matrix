"""
BlockchainInterface — base class for all blockchain capabilities.

Every capability inherits from this and gets:
- Web3 connection via RPC
- Gas sponsorship via ERC-4337 paymaster
- EAS attestation for every action
- Config-driven chain/contract addresses (no hardcoded values)
"""

import logging
from abc import ABC, abstractmethod
from typing import Any

logger = logging.getLogger(__name__)


class BlockchainInterface(ABC):
    """Base interface for all blockchain capabilities."""

    def __init__(self, config: dict):
        self.config = config
        bc = config.get("blockchain", {})
        self.rpc_url = bc.get("rpc_url", "")
        self.chain_id = bc.get("chain_id", 84532)
        self.network = bc.get("network", "base-sepolia")
        self.platform_wallet = bc.get("platform_wallet", "")
        self._web3 = None

    @property
    def web3(self):
        """Lazy-load Web3 connection."""
        if self._web3 is None:
            try:
                from web3 import Web3
            except ImportError:
                logger.error("web3 package not installed — run: pip install web3")
                raise

            if not self.rpc_url or str(self.rpc_url).startswith("YOUR_"):
                raise ConnectionError(
                    "blockchain.rpc_url is not configured. "
                    "Set a valid RPC URL in matrix.config.json "
                    "(e.g., https://sepolia.base.org for Base Sepolia)."
                )

            try:
                self._web3 = Web3(Web3.HTTPProvider(self.rpc_url))
            except Exception as e:
                raise ConnectionError(
                    f"Failed to create Web3 provider for {self.rpc_url}: {e}"
                ) from e

            if not self._web3.is_connected():
                raise ConnectionError(
                    f"Web3 cannot reach RPC at {self.rpc_url}. "
                    f"Check that the URL is correct and the node is running."
                )
        return self._web3

    @property
    @abstractmethod
    def name(self) -> str:
        """Capability name for tool registration."""
        ...

    @property
    @abstractmethod
    def description(self) -> str:
        """Human-readable description."""
        ...

    @property
    def schema(self) -> dict:
        """JSON schema for tool parameters."""
        return {
            "name": self.name,
            "description": self.description,
            "parameters": self.parameters,
        }

    @property
    @abstractmethod
    def parameters(self) -> dict:
        """JSON schema for the capability's parameters."""
        ...

    @abstractmethod
    async def execute(self, **kwargs) -> str:
        """Execute the capability. Returns a human-readable result string."""
        ...

    async def _platform_signer(self, action: str):
        """The platform signer for one operation, metered by the sponsorship
        policy (D-045).

        Replaces `Account.from_key(bc["paymaster_private_key"])`, which every
        capability used to call directly: 32 sites across 13 files, none of
        which saw an allowlist, a cap or a caller. The signature is authorised
        at `sign_transaction` time, when the transaction's real gas numbers
        exist, and raises SponsorshipDenied instead of signing when the
        configured daily cap would be crossed.

        `action` is `<capability>.<method>` — what the allowlist is checked
        against and what a denial names.
        """
        from runtime.blockchain.sponsorship import platform_signer
        return await platform_signer(self.config, action)

    def _require_config(self, *keys: str):
        """Validate that required config keys are present and not placeholder."""
        bc = self.config.get("blockchain", {})
        missing = []
        for key in keys:
            val = bc.get(key, "")
            if not val or str(val).startswith("YOUR_"):
                missing.append(key)
        if missing:
            raise ValueError(
                f"Missing blockchain config: {', '.join(missing)}. "
                f"Set these in matrix.config.json"
            )
