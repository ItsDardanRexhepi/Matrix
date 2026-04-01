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
                self._web3 = Web3(Web3.HTTPProvider(self.rpc_url))
                if not self._web3.is_connected():
                    logger.warning(f"Web3 not connected to {self.rpc_url}")
            except ImportError:
                logger.error("web3 package not installed — run: pip install web3")
                raise
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
                f"Set these in openmatrix.config.json"
            )
