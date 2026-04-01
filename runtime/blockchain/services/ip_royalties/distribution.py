"""
RoyaltyDistribution — distributes accumulated royalties to beneficiaries.

Supports multiple beneficiaries with percentage splits and a claim-based
payout model.
"""

from __future__ import annotations

import logging
import time
import uuid
from typing import Any

logger = logging.getLogger(__name__)


class RoyaltyDistribution:
    """Manages royalty distribution and claiming.

    Royalties accumulate in pending balances and are released when
    beneficiaries call ``claim()``.
    """

    def __init__(self, config: dict) -> None:
        self._config = config

        # address -> pending balance
        self._pending: dict[str, float] = {}
        # address -> list of claim records
        self._claim_history: dict[str, list[dict[str, Any]]] = {}
        # ip_id -> list of distribution records
        self._distributions: dict[str, list[dict[str, Any]]] = {}

    async def distribute(self, ip_id: str, revenue: float) -> dict:
        """Distribute revenue for an IP among its beneficiaries.

        Reads the beneficiary configuration from the royalty enforcement
        module.  If no beneficiaries are configured, the full amount
        goes to a holding pool.

        Args:
            ip_id: The IP asset generating revenue.
            revenue: Total revenue amount.

        Returns:
            Distribution record.
        """
        if revenue <= 0:
            raise ValueError("Revenue must be positive")

        # Try to get beneficiary config from enforcement
        beneficiaries: list[dict[str, Any]] = []
        try:
            from runtime.blockchain.services.ip_royalties.royalty_enforcement import (
                RoyaltyEnforcement,
            )
            enforcement = RoyaltyEnforcement(self._config)
            config = await enforcement.get_config(ip_id)
            beneficiaries = config.get("beneficiaries", [])
        except Exception:
            pass

        payouts: list[dict[str, Any]] = []

        if beneficiaries:
            for b in beneficiaries:
                share = float(b.get("share_pct", 0))
                amount = revenue * (share / 100.0)
                address = b["address"]
                self._pending[address] = self._pending.get(address, 0.0) + amount
                payouts.append({
                    "address": address,
                    "amount": round(amount, 6),
                    "share_pct": share,
                })
        else:
            # No beneficiaries; hold in ip_id bucket
            self._pending[ip_id] = self._pending.get(ip_id, 0.0) + revenue
            payouts.append({
                "address": ip_id,
                "amount": round(revenue, 6),
                "share_pct": 100.0,
                "note": "No beneficiaries configured; held for IP owner",
            })

        dist_id = f"rdist_{uuid.uuid4().hex[:12]}"
        record: dict[str, Any] = {
            "distribution_id": dist_id,
            "ip_id": ip_id,
            "revenue": revenue,
            "payouts": payouts,
            "timestamp": int(time.time()),
        }
        self._distributions.setdefault(ip_id, []).append(record)

        logger.info(
            "Royalties distributed: ip=%s revenue=%.6f payouts=%d",
            ip_id, revenue, len(payouts),
        )
        return record

    async def get_pending(self, address: str) -> dict:
        """Get pending royalty balance for an address.

        Args:
            address: The beneficiary address.

        Returns:
            Dict with ``address``, ``pending_amount``, ``claim_count``.
        """
        pending = self._pending.get(address, 0.0)
        claims = self._claim_history.get(address, [])

        return {
            "address": address,
            "pending_amount": round(pending, 6),
            "total_claimed": round(
                sum(c.get("amount", 0) for c in claims), 6,
            ),
            "claim_count": len(claims),
        }

    async def claim(self, address: str) -> dict:
        """Claim all pending royalties for an address.

        Args:
            address: The beneficiary address.

        Returns:
            Claim record with amount.
        """
        pending = self._pending.get(address, 0.0)
        if pending <= 0:
            return {
                "status": "nothing_to_claim",
                "address": address,
                "amount": 0.0,
            }

        claim_id = f"rclm_{uuid.uuid4().hex[:12]}"
        now = int(time.time())

        record: dict[str, Any] = {
            "claim_id": claim_id,
            "address": address,
            "amount": round(pending, 6),
            "status": "claimed",
            "claimed_at": now,
        }

        self._pending[address] = 0.0
        self._claim_history.setdefault(address, []).append(record)

        logger.info(
            "Royalties claimed: address=%s amount=%.6f",
            address, pending,
        )
        return record
