"""
DataAggregator — collects and aggregates data from all 0pnMatrx services
for the unified dashboard.

For staking APY: uses Component 16's canonical APY calculator exclusively.
"""

from __future__ import annotations

import logging
import time
from typing import Any

logger = logging.getLogger(__name__)


class DataAggregator:
    """Aggregates portfolio and activity data across all platform components.

    Config keys (under ``config["dashboard"]``):
        activity_limit (int): Default activity items to return (default 50).
        cache_ttl (int): Seconds to cache aggregated data (default 30).

    The ``services`` dict maps component names to service instances.
    """

    def __init__(self, config: dict, services: dict[str, Any] | None = None) -> None:
        self._config = config
        d_cfg: dict[str, Any] = config.get("dashboard", {})

        self._activity_limit: int = int(d_cfg.get("activity_limit", 50))
        self._cache_ttl: int = int(d_cfg.get("cache_ttl", 30))

        self._services: dict[str, Any] = services or {}

        # Simple cache: key -> (timestamp, data)
        self._cache: dict[str, tuple[int, Any]] = {}

        logger.info(
            "DataAggregator initialised (services=%d, cache_ttl=%ds).",
            len(self._services), self._cache_ttl,
        )

    def register_service(self, name: str, service: Any) -> None:
        """Register a service for aggregation."""
        self._services[name] = service
        logger.info("Service registered: %s", name)

    def _get_cached(self, key: str) -> Any | None:
        """Return cached data if still fresh."""
        entry = self._cache.get(key)
        if entry is None:
            return None
        cached_at, data = entry
        if int(time.time()) - cached_at > self._cache_ttl:
            del self._cache[key]
            return None
        return data

    def _set_cached(self, key: str, data: Any) -> None:
        self._cache[key] = (int(time.time()), data)

    async def aggregate_portfolio(self, address: str) -> dict:
        """Aggregate portfolio across all components.

        Collects: tokens, NFTs, staking positions, DeFi positions,
        RWA holdings, securities, liquidity positions.

        For staking APY, this MUST use Component 16's canonical APY
        calculator exclusively.

        Returns:
            Unified portfolio dict.
        """
        cache_key = f"portfolio:{address}"
        cached = self._get_cached(cache_key)
        if cached is not None:
            return cached

        portfolio: dict[str, Any] = {
            "address": address,
            "tokens": [],
            "nfts": [],
            "staking_positions": [],
            "defi_positions": [],
            "rwa_holdings": [],
            "securities": [],
            "liquidity_positions": [],
            "total_value_usd": 0.0,
            "aggregated_at": int(time.time()),
        }

        # Staking positions (Component 16) — uses canonical APY calculator
        staking_svc = self._services.get("staking")
        if staking_svc is not None:
            try:
                positions = getattr(staking_svc, "_positions", {})
                for (staker, pool_id), pos in positions.items():
                    if staker != address:
                        continue
                    staking_entry = dict(pos)
                    # Use Component 16's canonical APY calculator exclusively
                    apy_calculator = staking_svc.apy_calculator
                    try:
                        apy_data = await apy_calculator.calculate_apy(pool_id)
                        staking_entry["apy"] = apy_data.get("apy", 0.0)
                    except Exception:
                        staking_entry["apy"] = 0.0
                    portfolio["staking_positions"].append(staking_entry)
            except Exception as exc:
                logger.warning("Failed to aggregate staking data: %s", exc)

        # DeFi positions (Component 14)
        defi_svc = self._services.get("defi")
        if defi_svc is not None:
            try:
                if hasattr(defi_svc, "get_positions"):
                    defi_positions = await defi_svc.get_positions(address)
                    portfolio["defi_positions"] = defi_positions if isinstance(defi_positions, list) else []
            except Exception as exc:
                logger.warning("Failed to aggregate DeFi data: %s", exc)

        # NFTs (Component 9)
        nft_svc = self._services.get("nft_services")
        if nft_svc is not None:
            try:
                if hasattr(nft_svc, "get_owned"):
                    nfts = await nft_svc.get_owned(address)
                    portfolio["nfts"] = nfts if isinstance(nfts, list) else []
            except Exception as exc:
                logger.warning("Failed to aggregate NFT data: %s", exc)

        # RWA holdings (Component 15)
        rwa_svc = self._services.get("rwa_tokenization")
        if rwa_svc is not None:
            try:
                if hasattr(rwa_svc, "get_holdings"):
                    holdings = await rwa_svc.get_holdings(address)
                    portfolio["rwa_holdings"] = holdings if isinstance(holdings, list) else []
            except Exception as exc:
                logger.warning("Failed to aggregate RWA data: %s", exc)

        # Securities (Component 18)
        securities_svc = self._services.get("securities_exchange")
        if securities_svc is not None:
            try:
                balances = getattr(securities_svc, "_balances", {})
                for (sec_id, holder), balance in balances.items():
                    if holder == address and balance > 0:
                        portfolio["securities"].append({
                            "security_id": sec_id,
                            "balance": balance,
                        })
            except Exception as exc:
                logger.warning("Failed to aggregate securities data: %s", exc)

        # DEX liquidity (Component 21)
        dex_svc = self._services.get("dex")
        if dex_svc is not None:
            try:
                if hasattr(dex_svc, "get_positions"):
                    lp_positions = await dex_svc.get_positions(address)
                    portfolio["liquidity_positions"] = lp_positions if isinstance(lp_positions, list) else []
            except Exception as exc:
                logger.warning("Failed to aggregate DEX data: %s", exc)

        self._set_cached(cache_key, portfolio)
        logger.info("Portfolio aggregated: address=%s", address)
        return portfolio

    async def aggregate_activity(self, address: str, limit: int | None = None) -> list:
        """Aggregate recent activity across all components.

        Returns:
            List of activity records sorted by timestamp (newest first).
        """
        if limit is None:
            limit = self._activity_limit

        cache_key = f"activity:{address}:{limit}"
        cached = self._get_cached(cache_key)
        if cached is not None:
            return cached

        activities: list[dict[str, Any]] = []

        # Collect from each registered service that exposes activity
        for svc_name, svc in self._services.items():
            try:
                if hasattr(svc, "get_activity"):
                    svc_activity = await svc.get_activity(address)
                    if isinstance(svc_activity, list):
                        for item in svc_activity:
                            item["component"] = svc_name
                            activities.append(item)
                elif hasattr(svc, "get_transactions"):
                    txs = await svc.get_transactions(address)
                    if isinstance(txs, list):
                        for tx in txs:
                            tx["component"] = svc_name
                            activities.append(tx)
            except Exception as exc:
                logger.warning(
                    "Failed to aggregate activity from %s: %s", svc_name, exc,
                )

        # Sort by timestamp, newest first
        activities.sort(
            key=lambda a: a.get("timestamp", a.get("created_at", 0)),
            reverse=True,
        )
        result = activities[:limit]

        self._set_cached(cache_key, result)
        return result
