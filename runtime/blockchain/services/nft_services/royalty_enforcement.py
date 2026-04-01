"""
RoyaltyEnforcement — ensure royalties are paid on every NFT sale.

ERC-2981 compliant royalty configuration and automatic distribution.
Attests royalty payments via the attestation service (Component 8)
for on-chain proof of payment.
"""

from __future__ import annotations

import logging
import time
import uuid
from typing import Any

logger = logging.getLogger(__name__)

# Maximum royalty: 25% (2500 bps)
_MAX_ROYALTY_BPS = 2500
# Minimum sale price to enforce royalties (dust prevention)
_MIN_SALE_PRICE = 0.0001


class RoyaltyEnforcement:
    """Enforce ERC-2981 royalty payments on NFT sales.

    Parameters
    ----------
    config : dict
        Platform config.  Reads:
        - ``blockchain.platform_wallet`` — platform fee recipient
        - ``blockchain.platform_fee_bps`` — platform fee (default 250)
        - ``nft.royalty.max_bps`` — maximum royalty (default 2500)
    attestation_service : object, optional
        AttestationService instance (Component 8) for recording
        royalty payment attestations.
    """

    def __init__(
        self,
        config: dict,
        attestation_service: Any = None,
    ) -> None:
        self._config = config
        self._attestation = attestation_service

        bc = config.get("blockchain", {})
        self._platform_wallet: str = bc.get("platform_wallet", "")
        self._platform_fee_bps: int = int(bc.get("platform_fee_bps", 250))
        self._max_royalty_bps: int = int(
            config.get("nft", {}).get("royalty", {}).get("max_bps", _MAX_ROYALTY_BPS)
        )

        # Royalty configurations: {collection:token_id: config}
        self._royalty_configs: dict[str, dict[str, Any]] = {}
        # Collection-level defaults
        self._collection_defaults: dict[str, dict[str, Any]] = {}
        # Sale records
        self._sales: list[dict[str, Any]] = []

    async def configure_royalty(
        self,
        collection: str,
        token_id: int,
        recipient: str,
        bps: int,
    ) -> dict[str, Any]:
        """Configure royalty for a specific token (ERC-2981 compatible).

        Parameters
        ----------
        collection : str
            Collection contract address.
        token_id : int
            Token ID. Use ``-1`` for collection-wide default.
        recipient : str
            Royalty recipient address.
        bps : int
            Royalty in basis points (100 = 1%).

        Returns
        -------
        dict
            Royalty configuration confirmation.
        """
        if not recipient or not recipient.startswith("0x"):
            raise ValueError("Valid recipient address required")
        if bps < 0 or bps > self._max_royalty_bps:
            raise ValueError(
                f"Royalty must be between 0 and {self._max_royalty_bps} bps "
                f"({self._max_royalty_bps / 100:.1f}%)"
            )

        now = int(time.time())
        config_entry = {
            "collection": collection,
            "token_id": token_id,
            "recipient": recipient,
            "bps": bps,
            "percentage": f"{bps / 100:.2f}%",
            "configured_at": now,
        }

        if token_id == -1:
            # Collection-wide default
            self._collection_defaults[collection] = config_entry
            logger.info(
                "Collection royalty set: %s -> %s at %d bps",
                collection[:10], recipient, bps,
            )
        else:
            key = f"{collection}:{token_id}"
            self._royalty_configs[key] = config_entry
            logger.info(
                "Token royalty set: %s #%d -> %s at %d bps",
                collection[:10], token_id, recipient, bps,
            )

        return {
            "status": "configured",
            **config_entry,
        }

    async def process_sale(
        self,
        collection: str,
        token_id: int,
        sale_price: float,
        seller: str,
        buyer: str,
    ) -> dict[str, Any]:
        """Process an NFT sale with automatic royalty distribution.

        Calculates and distributes:
        1. Creator royalty (ERC-2981)
        2. Platform fee
        3. Seller proceeds

        Parameters
        ----------
        collection : str
            Collection contract address.
        token_id : int
            Token ID.
        sale_price : float
            Sale price in ETH.
        seller : str
            Seller wallet address.
        buyer : str
            Buyer wallet address.

        Returns
        -------
        dict
            Sale breakdown with royalty, platform fee, and seller proceeds.
        """
        if sale_price < _MIN_SALE_PRICE:
            raise ValueError(
                f"Sale price {sale_price} is below minimum {_MIN_SALE_PRICE}"
            )

        # Get royalty configuration
        royalty_config = self._get_royalty_config(collection, token_id)
        royalty_bps = royalty_config.get("bps", 0) if royalty_config else 0
        royalty_recipient = royalty_config.get("recipient", "") if royalty_config else ""

        # Calculate amounts
        royalty_amount = (sale_price * royalty_bps) / 10000
        platform_fee = (sale_price * self._platform_fee_bps) / 10000
        seller_proceeds = sale_price - royalty_amount - platform_fee

        sale_id = f"sale_{uuid.uuid4().hex[:16]}"
        now = int(time.time())

        sale_record: dict[str, Any] = {
            "sale_id": sale_id,
            "collection": collection,
            "token_id": token_id,
            "sale_price": sale_price,
            "seller": seller,
            "buyer": buyer,
            "royalty": {
                "recipient": royalty_recipient,
                "bps": royalty_bps,
                "amount": round(royalty_amount, 8),
            },
            "platform_fee": {
                "recipient": self._platform_wallet,
                "bps": self._platform_fee_bps,
                "amount": round(platform_fee, 8),
            },
            "seller_proceeds": round(seller_proceeds, 8),
            "timestamp": now,
        }

        self._sales.append(sale_record)

        # Attest royalty payment via Component 8
        attestation_result = None
        if self._attestation is not None and royalty_amount > 0:
            try:
                attestation_result = await self._attestation.attest(
                    schema_uid="primary",
                    data={
                        "action": "royalty_payment",
                        "category": "royalty",
                        "sale_id": sale_id,
                        "collection": collection,
                        "token_id": token_id,
                        "sale_price": str(sale_price),
                        "royalty_amount": str(royalty_amount),
                        "royalty_recipient": royalty_recipient,
                        "seller": seller,
                        "buyer": buyer,
                    },
                    recipient=royalty_recipient,
                )
                sale_record["attestation"] = attestation_result
            except Exception as exc:
                logger.warning(
                    "Royalty attestation failed for sale %s: %s",
                    sale_id, exc,
                )
                sale_record["attestation"] = {
                    "status": "failed",
                    "error": str(exc),
                }

        logger.info(
            "Sale processed: id=%s %s #%d price=%.4f ETH "
            "royalty=%.4f platform=%.4f seller=%.4f",
            sale_id, collection[:10], token_id, sale_price,
            royalty_amount, platform_fee, seller_proceeds,
        )

        return sale_record

    async def get_royalty_info(
        self, collection: str, token_id: int, sale_price: float = 1.0
    ) -> dict[str, Any]:
        """ERC-2981 compatible royalty info query.

        Parameters
        ----------
        collection : str
            Collection address.
        token_id : int
            Token ID.
        sale_price : float
            Sale price to calculate royalty for.

        Returns
        -------
        dict
            Keys: ``receiver``, ``royalty_amount``, ``bps``.
        """
        config = self._get_royalty_config(collection, token_id)

        if config is None:
            return {
                "receiver": "",
                "royalty_amount": 0,
                "bps": 0,
            }

        amount = (sale_price * config["bps"]) / 10000
        return {
            "receiver": config["recipient"],
            "royalty_amount": round(amount, 8),
            "bps": config["bps"],
        }

    async def get_sales_history(
        self,
        collection: str | None = None,
        token_id: int | None = None,
        limit: int = 50,
    ) -> list[dict[str, Any]]:
        """Get sale history with royalty details."""
        results: list[dict[str, Any]] = []
        for sale in reversed(self._sales):
            if collection and sale["collection"] != collection:
                continue
            if token_id is not None and sale["token_id"] != token_id:
                continue
            results.append(sale)
            if len(results) >= limit:
                break
        return results

    async def get_total_royalties_paid(
        self, recipient: str
    ) -> dict[str, Any]:
        """Get total royalties paid to a specific recipient."""
        total = 0.0
        count = 0
        for sale in self._sales:
            if sale["royalty"]["recipient"] == recipient:
                total += sale["royalty"]["amount"]
                count += 1

        return {
            "recipient": recipient,
            "total_royalties_eth": round(total, 8),
            "num_sales": count,
        }

    # ── Internal ──────────────────────────────────────────────────────

    def _get_royalty_config(
        self, collection: str, token_id: int
    ) -> dict[str, Any] | None:
        """Get the applicable royalty config for a token.

        Checks token-specific config first, then collection default.
        """
        key = f"{collection}:{token_id}"
        config = self._royalty_configs.get(key)
        if config is not None:
            return config
        return self._collection_defaults.get(collection)
