"""
StakingPool management — create, configure, and query staking pools.

Pool configs: reward_token, reward_rate, lock_period, min_stake.
"""

from __future__ import annotations

import logging
import time
import uuid
from typing import Any

logger = logging.getLogger(__name__)

_DEFAULT_POOL: dict[str, Any] = {
    "pool_id": "default",
    "name": "Default Staking Pool",
    "reward_token": "ETH",
    "reward_rate": 0.1,       # tokens per day emitted to pool
    "lock_period": 0,         # seconds; 0 = no lock
    "min_stake": 1.0,         # 1 ETH minimum
    "total_staked": 0.0,
    "staker_count": 0,
    "status": "active",
    "created_at": 0,
}


class StakingPoolManager:
    """Manages staking pools.

    Config keys (under ``config["staking"]``):
        default_reward_rate (float): Default daily reward emission.
        default_lock_period (int): Default lock period in seconds.
        min_stake (float): Default minimum stake (1 ETH).
    """

    def __init__(self, config: dict) -> None:
        self._config = config
        s_cfg = config.get("staking", {})

        self._default_reward_rate: float = float(
            s_cfg.get("default_reward_rate", 0.1)
        )
        self._default_lock: int = int(s_cfg.get("default_lock_period", 0))
        self._min_stake: float = float(s_cfg.get("min_stake", 1.0))

        # pool_id -> pool record
        self._pools: dict[str, dict[str, Any]] = {}

        # Ensure default pool exists
        default = dict(_DEFAULT_POOL)
        default["reward_rate"] = self._default_reward_rate
        default["lock_period"] = self._default_lock
        default["min_stake"] = self._min_stake
        default["created_at"] = int(time.time())
        self._pools["default"] = default

    async def create_pool(self, config: dict) -> dict:
        """Create a new staking pool.

        Args:
            config: Dict with ``name``, ``reward_token``, ``reward_rate``,
                    ``lock_period``, ``min_stake``.

        Returns:
            Created pool record.
        """
        pool_id = config.get("pool_id", f"pool_{uuid.uuid4().hex[:12]}")
        if pool_id in self._pools:
            raise ValueError(f"Pool {pool_id} already exists")

        now = int(time.time())
        pool: dict[str, Any] = {
            "pool_id": pool_id,
            "name": config.get("name", f"Pool {pool_id}"),
            "reward_token": config.get("reward_token", "ETH"),
            "reward_rate": float(config.get("reward_rate", self._default_reward_rate)),
            "lock_period": int(config.get("lock_period", self._default_lock)),
            "min_stake": float(config.get("min_stake", self._min_stake)),
            "total_staked": 0.0,
            "staker_count": 0,
            "status": "active",
            "created_at": now,
        }
        self._pools[pool_id] = pool

        logger.info(
            "Pool created: id=%s name=%s rate=%.6f lock=%ds",
            pool_id, pool["name"], pool["reward_rate"], pool["lock_period"],
        )
        return pool

    async def get_pool(self, pool_id: str) -> dict:
        """Retrieve a pool by ID."""
        pool = self._pools.get(pool_id)
        if not pool:
            raise ValueError(f"Pool {pool_id} not found")
        return pool

    async def list_pools(self) -> list:
        """List all staking pools."""
        return list(self._pools.values())

    async def add_stake(self, pool_id: str, amount: float) -> None:
        """Record additional stake in pool totals."""
        pool = self._pools.get(pool_id)
        if pool:
            pool["total_staked"] += amount
            pool["staker_count"] = pool.get("staker_count", 0) + 1

    async def remove_stake(self, pool_id: str, amount: float) -> None:
        """Record removed stake in pool totals."""
        pool = self._pools.get(pool_id)
        if pool:
            pool["total_staked"] = max(0.0, pool["total_staked"] - amount)
