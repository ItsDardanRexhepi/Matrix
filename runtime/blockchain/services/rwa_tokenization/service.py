from __future__ import annotations

"""
RWAService — main entry point for the Real-World Asset Tokenization component.

Coordinates asset-specific tokenizers, joint ownership, legal bridging,
and pooled purchases under a single config-driven service.
"""

import logging
import time
from typing import Any

from .joint_ownership import JointOwnership
from .legal_bridge import LegalBridge
from .pooled_purchase import PooledPurchase
from .tokenizers import get_tokenizer

logger = logging.getLogger(__name__)

VALID_ASSET_TYPES = {"property", "vehicle", "art", "commodity", "equipment"}


class RWAService:
    """Unified service for real-world asset tokenization.

    Parameters
    ----------
    config : dict
        Full platform configuration.  The service reads:

        - ``blockchain.chain_id``
        - ``rwa.*`` — sub-keys for tokenization, legal, pool, etc.

    Example config snippet::

        {
            "blockchain": {
                "rpc_url": "...",
                "chain_id": 8453,
                "platform_wallet": "0x..."
            },
            "rwa": {
                "min_share_pct": 0.01,
                "legal": {
                    "default_jurisdiction": "US-DE"
                },
                "pool": {
                    "max_deadline_days": 365,
                    "platform_fee_pct": 1.0
                }
            }
        }
    """

    def __init__(self, config: dict) -> None:
        self._config = config
        self._chain_id: int = config.get("blockchain", {}).get("chain_id", 8453)

        # Sub-components
        self.joint_ownership = JointOwnership(config)
        self.legal_bridge = LegalBridge(config)
        self.pooled_purchase = PooledPurchase(config)

        # In-memory token store: token_id -> token record
        self._tokens: dict[str, dict[str, Any]] = {}
        # Event log for cross-component integration (Component 12 supply chain, etc.)
        self._events: list[dict] = []

        logger.info("RWAService initialised (chain_id=%d)", self._chain_id)

    # ------------------------------------------------------------------
    # Core token operations
    # ------------------------------------------------------------------

    async def tokenize_asset(
        self,
        owner: str,
        asset_type: str,
        metadata: dict,
        valuation: float,
    ) -> dict:
        """Tokenize a real-world asset.

        Parameters
        ----------
        owner : str
            Wallet address of the asset owner.
        asset_type : str
            One of ``property``, ``vehicle``, ``art``, ``commodity``, ``equipment``.
        metadata : dict
            Asset-specific metadata (validated by the corresponding tokenizer).
        valuation : float
            Assessed value in platform currency.

        Returns
        -------
        dict
            The minted token record.
        """
        if asset_type not in VALID_ASSET_TYPES:
            raise ValueError(
                f"Invalid asset_type '{asset_type}'. Must be one of {sorted(VALID_ASSET_TYPES)}"
            )
        if valuation <= 0:
            raise ValueError("Valuation must be positive")
        if not owner:
            raise ValueError("Owner address is required")

        tokenizer = get_tokenizer(asset_type)
        token = await tokenizer.tokenize(owner, metadata)
        token["valuation"] = valuation
        token["chain_id"] = self._chain_id

        self._tokens[token["token_id"]] = token

        self._emit_event("asset_tokenized", {
            "token_id": token["token_id"],
            "owner": owner,
            "asset_type": asset_type,
            "valuation": valuation,
        })

        logger.info(
            "Asset tokenized: %s (type=%s, owner=%s, valuation=%.2f)",
            token["token_id"], asset_type, owner, valuation,
        )
        return token

    async def transfer_ownership(
        self, token_id: str, from_addr: str, to_addr: str
    ) -> dict:
        """Transfer full ownership of a tokenized asset.

        Emits an ``ownership_transferred`` event consumed by Component 12
        (supply chain tracking).
        """
        token = self._get_token(token_id)

        if token["owner"] != from_addr:
            raise ValueError(
                f"Token {token_id} is owned by {token['owner']}, not {from_addr}"
            )
        if not to_addr:
            raise ValueError("Destination address is required")
        if from_addr == to_addr:
            raise ValueError("Cannot transfer to the same address")

        previous_owner = token["owner"]
        token["owner"] = to_addr
        token["updated_at"] = time.time()

        transfer_record = {
            "token_id": token_id,
            "from": previous_owner,
            "to": to_addr,
            "asset_type": token["asset_type"],
            "valuation": token.get("valuation"),
            "transferred_at": token["updated_at"],
        }

        # Emit event for Component 12 supply chain and other listeners
        self._emit_event("ownership_transferred", transfer_record)

        logger.info(
            "Ownership transferred: token %s from %s to %s",
            token_id, previous_owner, to_addr,
        )
        return transfer_record

    async def get_asset(self, token_id: str) -> dict:
        """Retrieve a tokenized asset by its token ID."""
        return self._get_token(token_id)

    # ------------------------------------------------------------------
    # Event helpers (for Component 12 integration)
    # ------------------------------------------------------------------

    def _emit_event(self, event_type: str, data: dict) -> None:
        event = {
            "event_type": event_type,
            "data": data,
            "chain_id": self._chain_id,
            "timestamp": time.time(),
        }
        self._events.append(event)
        logger.debug("Event emitted: %s", event_type)

    def get_events(self, event_type: str | None = None) -> list[dict]:
        """Return emitted events, optionally filtered by type."""
        if event_type is None:
            return list(self._events)
        return [e for e in self._events if e["event_type"] == event_type]

    # ------------------------------------------------------------------
    # Internal
    # ------------------------------------------------------------------

    def _get_token(self, token_id: str) -> dict:
        token = self._tokens.get(token_id)
        if token is None:
            raise KeyError(f"Token {token_id} not found")
        return token
