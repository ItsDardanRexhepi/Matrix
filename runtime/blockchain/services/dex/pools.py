"""
LiquidityPoolManager — constant product AMM (x*y=k) pool management
for the 0pnMatrx native DEX.

Used as fallback when Uniswap pools are not available.
"""

from __future__ import annotations

import logging
import math
import time
import uuid
from typing import Any

logger = logging.getLogger(__name__)


def _pool_key(token_a: str, token_b: str) -> tuple[str, str]:
    """Canonical token pair ordering (alphabetical)."""
    return (min(token_a, token_b), max(token_a, token_b))


class LiquidityPoolManager:
    """Constant product AMM pool manager.

    Config keys (under ``config["dex"]``):
        default_fee_tier (int): Fee in basis points (default 3000 = 0.3%).
        min_liquidity (float): Minimum initial liquidity (default 100).
    """

    def __init__(self, config: dict) -> None:
        self._config = config
        d_cfg: dict[str, Any] = config.get("dex", {})

        self._default_fee: int = int(d_cfg.get("default_fee_tier", 3000))
        self._min_liquidity: float = float(d_cfg.get("min_liquidity", 100.0))

        # pool_id -> pool record
        self._pools: dict[str, dict[str, Any]] = {}
        # (token_a, token_b) -> pool_id  (canonical ordering)
        self._pair_index: dict[tuple[str, str], str] = {}
        # (pool_id, provider) -> LP position
        self._lp_positions: dict[tuple[str, str], dict[str, Any]] = {}

        logger.info(
            "LiquidityPoolManager initialised (default_fee=%d bps).",
            self._default_fee,
        )

    async def create_pool(
        self, token_a: str, token_b: str, fee_tier: int = 3000
    ) -> dict:
        """Create a new liquidity pool.

        Args:
            token_a: First token address/symbol.
            token_b: Second token address/symbol.
            fee_tier: Fee in basis points (default 3000 = 0.3%).

        Returns:
            Pool record.
        """
        if token_a == token_b:
            raise ValueError("Cannot create pool with identical tokens")

        key = _pool_key(token_a, token_b)
        if key in self._pair_index:
            raise ValueError(
                f"Pool already exists for {key[0]}/{key[1]}: "
                f"id={self._pair_index[key]}"
            )

        pool_id = str(uuid.uuid4())
        now = int(time.time())

        pool = {
            "pool_id": pool_id,
            "token_a": key[0],
            "token_b": key[1],
            "reserve_a": 0.0,
            "reserve_b": 0.0,
            "k": 0.0,  # x * y = k
            "fee_tier": fee_tier,
            "fee_pct": fee_tier / 1_000_000,  # e.g., 3000 -> 0.003
            "total_lp_shares": 0.0,
            "volume_24h": 0.0,
            "total_volume": 0.0,
            "swap_count": 0,
            "created_at": now,
            "updated_at": now,
            "status": "active",
        }

        self._pools[pool_id] = pool
        self._pair_index[key] = pool_id

        logger.info(
            "Pool created: id=%s pair=%s/%s fee=%d bps",
            pool_id, key[0], key[1], fee_tier,
        )
        return dict(pool)

    async def get_pool(self, pool_id: str) -> dict:
        """Get pool details by ID."""
        pool = self._pools.get(pool_id)
        if not pool:
            raise ValueError(f"Pool {pool_id} not found")
        return dict(pool)

    def get_pool_by_pair(self, token_a: str, token_b: str) -> dict | None:
        """Get pool by token pair (returns None if not found)."""
        key = _pool_key(token_a, token_b)
        pool_id = self._pair_index.get(key)
        if pool_id is None:
            return None
        return dict(self._pools[pool_id])

    async def get_pool_stats(self, pool_id: str) -> dict:
        """Get detailed pool statistics."""
        pool = self._pools.get(pool_id)
        if not pool:
            raise ValueError(f"Pool {pool_id} not found")

        reserve_a = pool["reserve_a"]
        reserve_b = pool["reserve_b"]

        price_a_in_b = reserve_b / reserve_a if reserve_a > 0 else 0.0
        price_b_in_a = reserve_a / reserve_b if reserve_b > 0 else 0.0

        return {
            "pool_id": pool_id,
            "token_a": pool["token_a"],
            "token_b": pool["token_b"],
            "reserve_a": reserve_a,
            "reserve_b": reserve_b,
            "price_a_in_b": price_a_in_b,
            "price_b_in_a": price_b_in_a,
            "k": pool["k"],
            "total_lp_shares": pool["total_lp_shares"],
            "volume_24h": pool["volume_24h"],
            "total_volume": pool["total_volume"],
            "swap_count": pool["swap_count"],
            "fee_tier": pool["fee_tier"],
        }

    async def list_pools(self) -> list:
        """List all pools."""
        return [dict(p) for p in self._pools.values()]

    async def add_liquidity(
        self,
        pool_id: str,
        provider: str,
        amount_a: float,
        amount_b: float,
    ) -> dict:
        """Add liquidity to a pool.

        Returns:
            LP position with shares minted.
        """
        pool = self._pools.get(pool_id)
        if not pool:
            raise ValueError(f"Pool {pool_id} not found")
        if amount_a <= 0 or amount_b <= 0:
            raise ValueError("Both amounts must be positive")

        # If pool has existing reserves, enforce ratio
        if pool["reserve_a"] > 0 and pool["reserve_b"] > 0:
            ratio = pool["reserve_b"] / pool["reserve_a"]
            expected_b = amount_a * ratio
            # Allow 1% tolerance
            if abs(amount_b - expected_b) / expected_b > 0.01:
                raise ValueError(
                    f"Amounts must match pool ratio. "
                    f"For {amount_a:.4f} of {pool['token_a']}, "
                    f"provide ~{expected_b:.4f} of {pool['token_b']}"
                )

        # Calculate LP shares
        if pool["total_lp_shares"] == 0:
            # Initial liquidity: shares = sqrt(a * b)
            shares = math.sqrt(amount_a * amount_b)
        else:
            # Proportional: shares based on smaller ratio
            ratio_a = amount_a / pool["reserve_a"]
            ratio_b = amount_b / pool["reserve_b"]
            shares = min(ratio_a, ratio_b) * pool["total_lp_shares"]

        # Update pool
        pool["reserve_a"] += amount_a
        pool["reserve_b"] += amount_b
        pool["k"] = pool["reserve_a"] * pool["reserve_b"]
        pool["total_lp_shares"] += shares
        pool["updated_at"] = int(time.time())

        # Record LP position
        lp_key = (pool_id, provider)
        existing = self._lp_positions.get(lp_key)
        if existing:
            existing["shares"] += shares
            existing["deposited_a"] += amount_a
            existing["deposited_b"] += amount_b
        else:
            self._lp_positions[lp_key] = {
                "pool_id": pool_id,
                "provider": provider,
                "shares": shares,
                "deposited_a": amount_a,
                "deposited_b": amount_b,
                "added_at": int(time.time()),
            }

        logger.info(
            "Liquidity added: pool=%s provider=%s shares=%.6f",
            pool_id, provider, shares,
        )
        return {
            "pool_id": pool_id,
            "provider": provider,
            "shares_minted": shares,
            "total_shares": self._lp_positions[lp_key]["shares"],
            "amount_a": amount_a,
            "amount_b": amount_b,
        }

    async def remove_liquidity(
        self, pool_id: str, provider: str, percentage: float
    ) -> dict:
        """Remove liquidity from a pool.

        Args:
            pool_id: Pool to withdraw from.
            provider: LP address.
            percentage: 0-100, percentage of position to remove.

        Returns:
            Amounts withdrawn.
        """
        if not 0 < percentage <= 100:
            raise ValueError("Percentage must be between 0 and 100")

        pool = self._pools.get(pool_id)
        if not pool:
            raise ValueError(f"Pool {pool_id} not found")

        lp_key = (pool_id, provider)
        position = self._lp_positions.get(lp_key)
        if not position:
            raise ValueError(f"No LP position for {provider} in pool {pool_id}")

        fraction = percentage / 100.0
        shares_to_burn = position["shares"] * fraction

        # Calculate withdrawal amounts proportionally
        share_of_pool = shares_to_burn / pool["total_lp_shares"]
        amount_a = pool["reserve_a"] * share_of_pool
        amount_b = pool["reserve_b"] * share_of_pool

        # Update pool
        pool["reserve_a"] -= amount_a
        pool["reserve_b"] -= amount_b
        pool["k"] = pool["reserve_a"] * pool["reserve_b"]
        pool["total_lp_shares"] -= shares_to_burn
        pool["updated_at"] = int(time.time())

        # Update position
        position["shares"] -= shares_to_burn
        if position["shares"] <= 1e-12:
            del self._lp_positions[lp_key]

        logger.info(
            "Liquidity removed: pool=%s provider=%s pct=%.1f%%",
            pool_id, provider, percentage,
        )
        return {
            "pool_id": pool_id,
            "provider": provider,
            "shares_burned": shares_to_burn,
            "amount_a": amount_a,
            "amount_b": amount_b,
            "token_a": pool["token_a"],
            "token_b": pool["token_b"],
        }

    def calculate_swap_output(
        self, pool_id: str, token_in: str, amount_in: float
    ) -> dict:
        """Calculate output amount for a swap using x*y=k.

        Returns:
            Dict with amount_out, price_impact, and effective_price.
        """
        pool = self._pools.get(pool_id)
        if not pool:
            raise ValueError(f"Pool {pool_id} not found")
        if pool["reserve_a"] == 0 or pool["reserve_b"] == 0:
            raise ValueError("Pool has no liquidity")

        # Determine direction
        if token_in == pool["token_a"]:
            reserve_in = pool["reserve_a"]
            reserve_out = pool["reserve_b"]
        elif token_in == pool["token_b"]:
            reserve_in = pool["reserve_b"]
            reserve_out = pool["reserve_a"]
        else:
            raise ValueError(f"Token {token_in} is not in pool {pool_id}")

        # Apply fee
        fee_pct = pool["fee_pct"]
        amount_in_after_fee = amount_in * (1 - fee_pct)

        # x * y = k  =>  new_reserve_out = k / new_reserve_in
        new_reserve_in = reserve_in + amount_in_after_fee
        new_reserve_out = pool["k"] / new_reserve_in
        amount_out = reserve_out - new_reserve_out

        # Price impact
        spot_price = reserve_out / reserve_in
        effective_price = amount_out / amount_in if amount_in > 0 else 0
        price_impact = abs(1 - (effective_price / spot_price)) * 100 if spot_price > 0 else 0

        return {
            "amount_out": max(0.0, amount_out),
            "effective_price": effective_price,
            "spot_price": spot_price,
            "price_impact_pct": price_impact,
            "fee_amount": amount_in * fee_pct,
        }

    def execute_swap(self, pool_id: str, token_in: str, amount_in: float) -> dict:
        """Execute a swap and update pool reserves."""
        result = self.calculate_swap_output(pool_id, token_in, amount_in)
        pool = self._pools[pool_id]

        if token_in == pool["token_a"]:
            pool["reserve_a"] += amount_in
            pool["reserve_b"] -= result["amount_out"]
        else:
            pool["reserve_b"] += amount_in
            pool["reserve_a"] -= result["amount_out"]

        pool["k"] = pool["reserve_a"] * pool["reserve_b"]
        pool["swap_count"] += 1
        pool["total_volume"] += amount_in
        pool["volume_24h"] += amount_in
        pool["updated_at"] = int(time.time())

        return result
