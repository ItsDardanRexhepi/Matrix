"""
ValuationEngine — estimate NFT value using multiple factors.

Factors considered:
  - Rarity score (trait-based statistical rarity)
  - Creator reputation (on-platform track record)
  - Collection floor price
  - Recent sales data
  - Collection age and volume
"""

from __future__ import annotations

import logging
import math
import time
from typing import Any

logger = logging.getLogger(__name__)

# Weight factors for valuation components
_WEIGHTS: dict[str, float] = {
    "rarity": 0.30,
    "creator_reputation": 0.15,
    "floor_price": 0.25,
    "recent_sales": 0.20,
    "collection_volume": 0.10,
}


class ValuationEngine:
    """Estimate NFT value based on multiple on-chain and off-chain factors.

    Parameters
    ----------
    config : dict
        Platform config.  Reads:
        - ``nft.valuation.weights`` — override factor weights
        - ``nft.valuation.min_sales_for_confidence`` (default 5)
    """

    def __init__(self, config: dict) -> None:
        self._config = config
        val_cfg = config.get("nft", {}).get("valuation", {})

        self._weights: dict[str, float] = {
            **_WEIGHTS,
            **val_cfg.get("weights", {}),
        }
        self._min_sales: int = int(val_cfg.get("min_sales_for_confidence", 5))

        # In-memory data stores (production: on-chain + indexer)
        self._sales_history: dict[str, list[dict[str, Any]]] = {}
        self._floor_prices: dict[str, float] = {}
        self._collection_volumes: dict[str, float] = {}
        self._creator_scores: dict[str, float] = {}

    async def estimate_value(
        self, collection: str, token_id: int
    ) -> dict[str, Any]:
        """Estimate the value of a specific NFT.

        Parameters
        ----------
        collection : str
            Collection contract address.
        token_id : int
            Token ID within the collection.

        Returns
        -------
        dict
            Keys: ``estimated_value_eth``, ``confidence``,
            ``factors``, ``methodology``.
        """
        key = f"{collection}:{token_id}"

        # Gather factors
        floor = self._floor_prices.get(collection, 0)
        volume = self._collection_volumes.get(collection, 0)

        # Recent sales for this specific token
        sales = self._sales_history.get(key, [])
        recent_avg = 0.0
        if sales:
            recent = sorted(sales, key=lambda s: s["timestamp"], reverse=True)[:10]
            recent_avg = sum(s["price"] for s in recent) / len(recent)

        # Rarity (placeholder — real implementation uses get_rarity_score)
        rarity_multiplier = 1.0

        # Creator reputation
        creator_rep = 0.5  # neutral default

        # Weighted valuation
        components: dict[str, float] = {}

        # Floor-based component
        components["floor_price"] = floor * self._weights["floor_price"]

        # Recent sales component
        if recent_avg > 0:
            components["recent_sales"] = recent_avg * self._weights["recent_sales"]
        else:
            components["recent_sales"] = floor * self._weights["recent_sales"]

        # Rarity premium
        components["rarity"] = (
            max(floor, recent_avg) * rarity_multiplier * self._weights["rarity"]
        )

        # Creator reputation
        components["creator_reputation"] = (
            max(floor, recent_avg) * (0.5 + creator_rep) * self._weights["creator_reputation"]
        )

        # Volume signal
        volume_factor = min(volume / 100, 2.0) if volume > 0 else 0.5
        components["collection_volume"] = (
            max(floor, recent_avg) * volume_factor * self._weights["collection_volume"]
        )

        estimated_value = sum(components.values())
        estimated_value = max(estimated_value, 0)

        # Confidence based on data availability
        confidence = self._calculate_confidence(
            has_floor=floor > 0,
            num_sales=len(sales),
            has_volume=volume > 0,
        )

        result = {
            "collection": collection,
            "token_id": token_id,
            "estimated_value_eth": round(estimated_value, 6),
            "confidence": confidence,
            "confidence_label": self._confidence_label(confidence),
            "factors": {
                "floor_price_eth": floor,
                "recent_sales_avg_eth": round(recent_avg, 6),
                "rarity_multiplier": rarity_multiplier,
                "creator_reputation": creator_rep,
                "collection_volume_eth": volume,
            },
            "component_contributions": {
                k: round(v, 6) for k, v in components.items()
            },
            "methodology": "weighted_multi_factor",
            "timestamp": int(time.time()),
        }

        logger.info(
            "Valuation: %s #%d = %.4f ETH (confidence=%.0f%%)",
            collection[:10], token_id, estimated_value, confidence * 100,
        )
        return result

    async def get_rarity_score(
        self,
        collection: str,
        token_id: int,
        total_supply: int,
        traits: dict[str, Any],
    ) -> dict[str, Any]:
        """Calculate rarity score for a token based on its traits.

        Uses the information-content method: rarer traits contribute
        more to the score (similar to rarity.tools methodology).

        Parameters
        ----------
        collection : str
            Collection contract address.
        token_id : int
            Token ID.
        total_supply : int
            Total number of tokens in the collection.
        traits : dict
            Token traits: ``{"trait_type": "value", ...}``.
            Each value should include count information for accurate
            scoring, e.g., ``{"Background": {"value": "Gold", "count": 50}}``.

        Returns
        -------
        dict
            Keys: ``rarity_score``, ``rank_estimate``, ``trait_scores``,
            ``rarest_trait``.
        """
        if total_supply <= 0:
            raise ValueError("total_supply must be positive")

        trait_scores: dict[str, float] = {}
        total_score = 0.0

        for trait_type, trait_info in traits.items():
            if isinstance(trait_info, dict):
                count = trait_info.get("count", total_supply // 2)
                value = trait_info.get("value", "")
            else:
                count = total_supply // 2  # assume average rarity
                value = str(trait_info)

            # Probability of this trait
            probability = count / total_supply if total_supply > 0 else 1.0
            probability = max(probability, 1e-10)  # prevent log(0)

            # Information content score: -log2(probability)
            score = -math.log2(probability)
            trait_scores[trait_type] = round(score, 4)
            total_score += score

        # Normalise to 0-100 scale
        max_possible = -math.log2(1 / total_supply) * len(traits) if traits else 1
        normalised_score = (total_score / max_possible * 100) if max_possible > 0 else 50

        # Find rarest trait
        rarest = max(trait_scores, key=trait_scores.get) if trait_scores else None  # type: ignore[arg-type]

        # Estimate rank (simplified: assume normal distribution)
        rank_estimate = max(1, int(total_supply * (1 - normalised_score / 100)))

        result = {
            "collection": collection,
            "token_id": token_id,
            "rarity_score": round(normalised_score, 2),
            "raw_score": round(total_score, 4),
            "rank_estimate": rank_estimate,
            "total_supply": total_supply,
            "trait_scores": trait_scores,
            "rarest_trait": rarest,
            "num_traits": len(traits),
        }

        logger.info(
            "Rarity score: %s #%d = %.1f (rank ~%d/%d)",
            collection[:10], token_id, normalised_score,
            rank_estimate, total_supply,
        )
        return result

    # ── Data management (for integration) ────────────────────────────

    def record_sale(
        self, collection: str, token_id: int, price: float
    ) -> None:
        """Record a sale for valuation tracking."""
        key = f"{collection}:{token_id}"
        sales = self._sales_history.setdefault(key, [])
        sales.append({
            "price": price,
            "timestamp": int(time.time()),
        })
        # Update collection volume
        self._collection_volumes[collection] = (
            self._collection_volumes.get(collection, 0) + price
        )

    def update_floor_price(self, collection: str, floor: float) -> None:
        """Update the floor price for a collection."""
        self._floor_prices[collection] = floor

    def update_creator_score(self, creator: str, score: float) -> None:
        """Update creator reputation score (0-1)."""
        self._creator_scores[creator] = max(0, min(1, score))

    # ── Helpers ───────────────────────────────────────────────────────

    def _calculate_confidence(
        self, has_floor: bool, num_sales: int, has_volume: bool
    ) -> float:
        """Calculate confidence score (0-1) based on data availability."""
        confidence = 0.0
        if has_floor:
            confidence += 0.3
        if num_sales >= self._min_sales:
            confidence += 0.4
        elif num_sales > 0:
            confidence += 0.2
        if has_volume:
            confidence += 0.2
        # Baseline confidence even with no data
        confidence = max(confidence, 0.1)
        return min(confidence, 1.0)

    @staticmethod
    def _confidence_label(confidence: float) -> str:
        if confidence >= 0.8:
            return "high"
        if confidence >= 0.5:
            return "medium"
        if confidence >= 0.3:
            return "low"
        return "very_low"
