"""
PooledPurchase — group-buying mechanism for real-world assets.

Allows multiple contributors to pool funds towards purchasing an RWA.
When the target amount is met the pool finalises and ownership shares
are distributed proportionally.  If the deadline expires before the
target is reached, contributors can claim full refunds.
"""

import logging
import time
import uuid
from enum import Enum
from typing import Any

logger = logging.getLogger(__name__)

_SECONDS_PER_DAY = 86_400


class PoolStatus(str, Enum):
    OPEN = "open"
    FUNDED = "funded"
    FINALIZED = "finalized"
    REFUNDED = "refunded"
    EXPIRED = "expired"


class PooledPurchase:
    """Group-buying pools for RWA tokens.

    Parameters
    ----------
    config : dict
        Platform configuration.  Reads ``rwa.pool`` sub-key:

        - ``max_deadline_days`` (int, default 365)
        - ``platform_fee_pct`` (float, default 1.0) — fee taken on finalise
    """

    def __init__(self, config: dict) -> None:
        self._config = config
        pool_cfg = config.get("rwa", {}).get("pool", {})
        self._max_deadline_days: int = pool_cfg.get("max_deadline_days", 365)
        self._platform_fee_pct: float = pool_cfg.get("platform_fee_pct", 1.0)
        # pool_id -> pool record
        self._pools: dict[str, dict[str, Any]] = {}

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    async def create_pool(
        self,
        asset_id: str,
        target_amount: float,
        min_contribution: float,
        deadline_days: int,
    ) -> dict:
        """Open a new pooled-purchase pool.

        Parameters
        ----------
        asset_id : str
            Identifier of the target RWA or listing.
        target_amount : float
            Total funding required (in platform currency).
        min_contribution : float
            Minimum single contribution.
        deadline_days : int
            Number of days until the pool expires.
        """
        if target_amount <= 0:
            raise ValueError("target_amount must be positive")
        if min_contribution <= 0 or min_contribution > target_amount:
            raise ValueError(
                "min_contribution must be positive and <= target_amount"
            )
        if deadline_days <= 0 or deadline_days > self._max_deadline_days:
            raise ValueError(
                f"deadline_days must be 1..{self._max_deadline_days}"
            )

        pool_id = f"pool_{uuid.uuid4().hex[:12]}"
        now = time.time()

        pool = {
            "pool_id": pool_id,
            "asset_id": asset_id,
            "target_amount": target_amount,
            "min_contribution": min_contribution,
            "raised_amount": 0.0,
            "contributions": [],
            "deadline": now + deadline_days * _SECONDS_PER_DAY,
            "deadline_days": deadline_days,
            "status": PoolStatus.OPEN,
            "created_at": now,
            "updated_at": now,
            "shares": [],
        }
        self._pools[pool_id] = pool
        logger.info(
            "Pool %s created for asset %s — target %.2f, deadline %d days",
            pool_id, asset_id, target_amount, deadline_days,
        )
        return pool

    async def contribute(
        self, pool_id: str, contributor: str, amount: float
    ) -> dict:
        """Add a contribution to an open pool.

        Returns the updated pool record.
        """
        pool = self._get_pool(pool_id)

        if pool["status"] != PoolStatus.OPEN:
            raise ValueError(f"Pool {pool_id} is not open (status={pool['status']})")

        now = time.time()
        if now > pool["deadline"]:
            pool["status"] = PoolStatus.EXPIRED
            pool["updated_at"] = now
            raise ValueError(f"Pool {pool_id} has expired")

        if amount < pool["min_contribution"]:
            raise ValueError(
                f"Contribution {amount} is below minimum {pool['min_contribution']}"
            )

        remaining = pool["target_amount"] - pool["raised_amount"]
        effective = min(amount, remaining)

        contribution = {
            "contribution_id": f"contrib_{uuid.uuid4().hex[:10]}",
            "contributor": contributor,
            "amount": effective,
            "timestamp": now,
        }
        pool["contributions"].append(contribution)
        pool["raised_amount"] = round(pool["raised_amount"] + effective, 8)
        pool["updated_at"] = now

        if pool["raised_amount"] >= pool["target_amount"]:
            pool["status"] = PoolStatus.FUNDED
            logger.info("Pool %s is fully funded (%.2f)", pool_id, pool["raised_amount"])

        logger.info(
            "Contribution of %.2f to pool %s by %s (total %.2f / %.2f)",
            effective, pool_id, contributor, pool["raised_amount"], pool["target_amount"],
        )
        return {
            "pool": pool,
            "contribution": contribution,
            "overage_returned": round(amount - effective, 8) if amount > effective else 0.0,
        }

    async def finalize_pool(self, pool_id: str) -> dict:
        """Finalise a fully-funded pool, distribute ownership shares.

        The platform fee is deducted from the total raised amount before
        share calculation.
        """
        pool = self._get_pool(pool_id)

        if pool["status"] not in (PoolStatus.FUNDED, PoolStatus.OPEN):
            raise ValueError(
                f"Pool {pool_id} cannot be finalised (status={pool['status']})"
            )

        if pool["raised_amount"] < pool["target_amount"]:
            raise ValueError(
                f"Pool {pool_id} has not reached target "
                f"({pool['raised_amount']:.2f} / {pool['target_amount']:.2f})"
            )

        # Calculate platform fee
        fee = round(pool["raised_amount"] * self._platform_fee_pct / 100.0, 8)
        net_amount = round(pool["raised_amount"] - fee, 8)

        # Aggregate contributions per contributor
        totals: dict[str, float] = {}
        for c in pool["contributions"]:
            addr = c["contributor"]
            totals[addr] = totals.get(addr, 0.0) + c["amount"]

        # Distribute shares proportionally
        shares = []
        for addr, contributed in sorted(totals.items()):
            pct = round((contributed / pool["raised_amount"]) * 100.0, 6)
            shares.append({
                "address": addr,
                "contributed": round(contributed, 8),
                "percentage": pct,
            })

        pool["shares"] = shares
        pool["status"] = PoolStatus.FINALIZED
        pool["platform_fee"] = fee
        pool["net_amount"] = net_amount
        pool["finalized_at"] = time.time()
        pool["updated_at"] = pool["finalized_at"]

        logger.info(
            "Pool %s finalised — %d shareholders, fee=%.2f, net=%.2f",
            pool_id, len(shares), fee, net_amount,
        )
        return pool

    async def refund_pool(self, pool_id: str) -> dict:
        """Refund all contributors of a pool that did not meet its target.

        Can only be called on open or expired pools that have **not**
        reached their funding target.
        """
        pool = self._get_pool(pool_id)

        if pool["status"] == PoolStatus.FINALIZED:
            raise ValueError(f"Pool {pool_id} is already finalised, cannot refund")
        if pool["status"] == PoolStatus.REFUNDED:
            raise ValueError(f"Pool {pool_id} has already been refunded")

        if pool["raised_amount"] >= pool["target_amount"]:
            raise ValueError(
                f"Pool {pool_id} met its target — use finalize_pool instead"
            )

        refunds: list[dict] = []
        totals: dict[str, float] = {}
        for c in pool["contributions"]:
            totals[c["contributor"]] = totals.get(c["contributor"], 0.0) + c["amount"]

        for addr, amount in sorted(totals.items()):
            refunds.append({
                "recipient": addr,
                "amount": round(amount, 8),
                "refunded_at": time.time(),
            })

        pool["status"] = PoolStatus.REFUNDED
        pool["refunds"] = refunds
        pool["updated_at"] = time.time()

        logger.info(
            "Pool %s refunded — %d contributors, total %.2f returned",
            pool_id, len(refunds), pool["raised_amount"],
        )
        return pool

    # ------------------------------------------------------------------
    # Helpers
    # ------------------------------------------------------------------

    def _get_pool(self, pool_id: str) -> dict:
        pool = self._pools.get(pool_id)
        if pool is None:
            raise KeyError(f"Pool {pool_id} not found")
        return pool
