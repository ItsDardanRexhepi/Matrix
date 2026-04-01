"""
LifetimeBalanceTracker -- tracks cumulative transfer volumes per address.

Records inflows, outflows, and current balances per token. Provides
lifetime volume queries and tier classification based on total volume.
"""

from __future__ import annotations

import logging
import time
from typing import Any

logger = logging.getLogger(__name__)

# Volume tiers for classification
DEFAULT_VOLUME_TIERS: list[tuple[str, float]] = [
    ("bronze", 10_000.0),
    ("silver", 100_000.0),
    ("gold", 1_000_000.0),
    ("platinum", 10_000_000.0),
    ("diamond", float("inf")),
]


class LifetimeBalanceTracker:
    """
    Tracks lifetime transfer volumes, inflows, outflows, and current
    balances per address and token.

    Config keys (under config["stablecoin"]):
        volume_tiers -- optional list of (tier_name, upper_threshold) tuples
    """

    def __init__(self, config: dict[str, Any]) -> None:
        self.config = config
        sc = config.get("stablecoin", {})
        self.volume_tiers: list[tuple[str, float]] = sc.get(
            "volume_tiers", DEFAULT_VOLUME_TIERS
        )

        # address -> {token -> {inflow, outflow, balance, tx_count}}
        self._records: dict[str, dict[str, dict[str, float]]] = {}
        # address -> list of transfer records
        self._history: dict[str, list[dict[str, Any]]] = {}

        logger.info("LifetimeBalanceTracker initialised with %d tiers.", len(self.volume_tiers))

    async def record_transfer(
        self,
        address: str,
        token: str,
        amount: float,
        direction: str,
    ) -> dict[str, Any]:
        """
        Record a transfer for lifetime tracking.

        Args:
            address: Wallet address.
            token: Token symbol (e.g. "USDC").
            amount: Transfer amount (always positive).
            direction: "inflow" or "outflow".

        Returns:
            Dict with updated balance summary for this address/token.
        """
        token = token.upper()
        direction = direction.lower()

        if direction not in ("inflow", "outflow"):
            return {"status": "error", "error": f"Invalid direction: {direction}. Use 'inflow' or 'outflow'."}

        if amount <= 0:
            return {"status": "error", "error": "Amount must be positive"}

        # Initialise records
        if address not in self._records:
            self._records[address] = {}
        if token not in self._records[address]:
            self._records[address][token] = {
                "inflow": 0.0,
                "outflow": 0.0,
                "balance": 0.0,
                "tx_count": 0,
            }

        rec = self._records[address][token]
        rec[direction] += amount
        rec["tx_count"] += 1

        if direction == "inflow":
            rec["balance"] += amount
        else:
            rec["balance"] -= amount

        # Record history entry
        entry = {
            "address": address,
            "token": token,
            "amount": round(amount, 6),
            "direction": direction,
            "timestamp": int(time.time()),
            "running_balance": round(rec["balance"], 6),
        }
        self._history.setdefault(address, []).append(entry)

        logger.debug(
            "Recorded %s: %s %.6f %s for %s (balance=%.6f)",
            direction, token, amount, direction, address, rec["balance"],
        )

        return {
            "status": "recorded",
            "address": address,
            "token": token,
            "direction": direction,
            "amount": round(amount, 6),
            "inflow_total": round(rec["inflow"], 6),
            "outflow_total": round(rec["outflow"], 6),
            "balance": round(rec["balance"], 6),
            "tx_count": rec["tx_count"],
        }

    async def get_lifetime_volume(self, address: str) -> dict[str, Any]:
        """
        Get lifetime transfer volume across all tokens for an address.

        Args:
            address: Wallet address.

        Returns:
            Dict with total volume, per-token breakdown, and tier.
        """
        records = self._records.get(address, {})

        if not records:
            return {
                "address": address,
                "total_volume": 0.0,
                "total_inflow": 0.0,
                "total_outflow": 0.0,
                "total_tx_count": 0,
                "tokens": {},
                "tier": "bronze",
            }

        total_volume = 0.0
        total_inflow = 0.0
        total_outflow = 0.0
        total_tx = 0
        token_breakdown: dict[str, dict[str, float]] = {}

        for token, rec in records.items():
            vol = rec["inflow"] + rec["outflow"]
            total_volume += vol
            total_inflow += rec["inflow"]
            total_outflow += rec["outflow"]
            total_tx += int(rec["tx_count"])

            token_breakdown[token] = {
                "volume": round(vol, 6),
                "inflow": round(rec["inflow"], 6),
                "outflow": round(rec["outflow"], 6),
                "balance": round(rec["balance"], 6),
                "tx_count": int(rec["tx_count"]),
            }

        tier_info = await self.get_tier(address)

        return {
            "address": address,
            "total_volume": round(total_volume, 6),
            "total_inflow": round(total_inflow, 6),
            "total_outflow": round(total_outflow, 6),
            "total_tx_count": total_tx,
            "tokens": token_breakdown,
            "tier": tier_info["tier"],
        }

    async def get_tier(self, address: str) -> dict[str, Any]:
        """
        Determine the volume tier for an address based on lifetime volume.

        Args:
            address: Wallet address.

        Returns:
            Dict with tier name, volume, and thresholds.
        """
        records = self._records.get(address, {})
        total_volume = sum(
            rec["inflow"] + rec["outflow"] for rec in records.values()
        )

        tier_name = self.volume_tiers[0][0] if self.volume_tiers else "unknown"
        tier_threshold = 0.0

        for name, threshold in self.volume_tiers:
            if total_volume < threshold:
                tier_name = name
                tier_threshold = threshold
                break

        # Find next tier
        current_idx = next(
            (i for i, (n, _) in enumerate(self.volume_tiers) if n == tier_name),
            0,
        )
        next_tier = None
        volume_to_next = None
        if current_idx + 1 < len(self.volume_tiers):
            next_tier = self.volume_tiers[current_idx + 1][0]
            volume_to_next = round(tier_threshold - total_volume, 6)

        return {
            "address": address,
            "tier": tier_name,
            "total_volume": round(total_volume, 6),
            "tier_threshold": tier_threshold if tier_threshold != float("inf") else None,
            "next_tier": next_tier,
            "volume_to_next_tier": volume_to_next,
        }

    async def get_history(
        self, address: str, token: str | None = None, limit: int = 50
    ) -> list[dict[str, Any]]:
        """Get transfer history for an address, optionally filtered by token."""
        history = self._history.get(address, [])
        if token is not None:
            token = token.upper()
            history = [h for h in history if h["token"] == token]
        return history[-limit:]
