"""
RevenueShare — split game revenue between developer, platform, and investors.

Platform takes a configurable percentage (default 5 %).
"""

from __future__ import annotations

import logging
import time
import uuid
from typing import Any

logger = logging.getLogger(__name__)

_DEFAULT_PLATFORM_PCT = 5.0


class RevenueShare:
    """Revenue sharing for games.

    Config keys (under ``config["gaming"]``):
        platform_fee_pct (float): Platform cut of all revenue (default 5).
        platform_wallet (str): Address receiving platform fees.
    """

    def __init__(self, config: dict) -> None:
        self._config = config
        g_cfg = config.get("gaming", {})

        self._platform_pct: float = float(
            g_cfg.get("platform_fee_pct", _DEFAULT_PLATFORM_PCT)
        )
        self._platform_wallet: str = (
            g_cfg.get("platform_wallet", "")
            or config.get("blockchain", {}).get("platform_wallet", "")
        )

        # game_id -> share configuration
        self._shares: dict[str, list[dict[str, Any]]] = {}
        # game_id -> list of distribution records
        self._distributions: dict[str, list[dict[str, Any]]] = {}

    async def configure(self, game_id: str, shares: list[dict]) -> dict:
        """Configure revenue shares for a game.

        Args:
            game_id: The game to configure.
            shares: List of dicts with ``address`` and ``percentage``.
                    Percentages must sum to 100 (platform share is taken
                    from total revenue first, remainder is split per config).

        Returns:
            Configuration record.
        """
        if not shares:
            raise ValueError("At least one share entry is required")

        total_pct = sum(float(s.get("percentage", 0)) for s in shares)
        if abs(total_pct - 100.0) > 0.01:
            raise ValueError(
                f"Share percentages must sum to 100, got {total_pct}"
            )

        validated: list[dict[str, Any]] = []
        for s in shares:
            validated.append({
                "address": s["address"],
                "percentage": float(s["percentage"]),
                "label": s.get("label", ""),
            })

        self._shares[game_id] = validated

        logger.info(
            "Revenue shares configured: game=%s entries=%d platform_pct=%.1f",
            game_id, len(validated), self._platform_pct,
        )
        return {
            "game_id": game_id,
            "shares": validated,
            "platform_fee_pct": self._platform_pct,
            "status": "configured",
        }

    async def distribute(self, game_id: str, revenue: float) -> dict:
        """Distribute revenue according to configured shares.

        Args:
            game_id: The game generating revenue.
            revenue: Total revenue to distribute.

        Returns:
            Distribution record with per-recipient amounts.
        """
        if revenue <= 0:
            raise ValueError("Revenue must be positive")

        shares = self._shares.get(game_id)
        if not shares:
            raise ValueError(
                f"No revenue shares configured for game {game_id}"
            )

        # Platform fee first
        platform_amount = revenue * (self._platform_pct / 100.0)
        distributable = revenue - platform_amount

        payouts: list[dict[str, Any]] = []

        # Platform payout
        payouts.append({
            "address": self._platform_wallet,
            "amount": round(platform_amount, 6),
            "label": "platform_fee",
            "percentage": self._platform_pct,
        })

        # Stakeholder payouts
        for share in shares:
            amount = distributable * (share["percentage"] / 100.0)
            payouts.append({
                "address": share["address"],
                "amount": round(amount, 6),
                "label": share.get("label", ""),
                "percentage": share["percentage"],
            })

        dist_id = f"dist_{uuid.uuid4().hex[:16]}"
        record: dict[str, Any] = {
            "distribution_id": dist_id,
            "game_id": game_id,
            "total_revenue": revenue,
            "platform_fee": round(platform_amount, 6),
            "distributed": round(distributable, 6),
            "payouts": payouts,
            "timestamp": int(time.time()),
        }

        self._distributions.setdefault(game_id, []).append(record)

        logger.info(
            "Revenue distributed: game=%s total=%.6f platform=%.6f",
            game_id, revenue, platform_amount,
        )
        return record

    async def get_distributions(self, game_id: str) -> list:
        """Get all distribution records for a game."""
        return self._distributions.get(game_id, [])
