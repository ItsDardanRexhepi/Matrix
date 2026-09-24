"""
BlockchainInterface — base class for all blockchain capabilities.

Every capability inherits from this and gets:
- Web3 connection via RPC
- A platform signer metered by the sponsorship policy (`_platform_signer`)
- Config-driven chain/contract addresses (no hardcoded values)

The base class writes no attestation. A capability that attests calls
EASClient itself, which signs outside the sponsorship policy;
docs/blockchain.md lists those actions.
"""

import json
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

    async def _receipt(self, tx_hash: Any, action: str):
        """The receipt of a transaction this capability SENT, or None.

        None means no receipt arrived within the wait, and the caller answers it
        with `_unconfirmed`, never with a refusal. Every capability used to call
        `self.web3.eth.wait_for_transaction_receipt` inside the same `try` as
        the send, so a wait that ran out was an exception, and the `except`
        answered "Stake failed" or "Transfer failed" — to the agent, and to
        outcome learning as a failure — for a transaction that was out and may
        be mined, without its hash. The wait also blocked the event loop for up
        to two minutes; `receipt_within` runs it off the loop.

        `action` is `<capability>.<method>`, for the log line.
        """
        from runtime.blockchain.web3_manager import receipt_within
        return await receipt_within(self.web3, tx_hash, 120, what=action)

    def _unconfirmed(self, tx_hash: Any, **fields: Any) -> str:
        """What a capability answers for a transaction it sent that no receipt
        has confirmed: `web3_manager.unconfirmed_broadcast`, with the hash, as
        JSON. Not a refusal, and not a success: outcome learning reads it as
        unknown."""
        from runtime.blockchain.web3_manager import unconfirmed_broadcast
        return json.dumps(unconfirmed_broadcast(
            tx_hash, {**fields, "gas_paid_by": "platform (The Matrix)"}), indent=2)

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
