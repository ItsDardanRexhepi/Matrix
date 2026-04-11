"""Real-time knowledge retriever for agent context enrichment.

Fetches live market data, network status, and user on-chain history
to inject into agent prompts.  Every source is optional, has a strict
2-second timeout, and fails silently.  Results are cached for 30 seconds
to avoid hammering external APIs.

This module is completely non-blocking: a failed knowledge fetch must
never delay or break a response.
"""

from __future__ import annotations

import asyncio
import logging
import time
from typing import Any

logger = logging.getLogger(__name__)

_CACHE_TTL_SECONDS = 30
_SOURCE_TIMEOUT_SECONDS = 2.0


class KnowledgeRetriever:
    """Retrieves real-time context from multiple knowledge sources."""

    def __init__(self, config: dict | None = None) -> None:
        self._config = config or {}
        self._cache: dict[str, tuple[float, dict]] = {}

    def _get_cached(self, key: str) -> dict | None:
        """Return cached result if still fresh, else None."""
        entry = self._cache.get(key)
        if entry is None:
            return None
        ts, data = entry
        if time.monotonic() - ts > _CACHE_TTL_SECONDS:
            del self._cache[key]
            return None
        return data

    def _set_cached(self, key: str, data: dict) -> None:
        self._cache[key] = (time.monotonic(), data)

    async def get_relevant_context(
        self,
        query: str,
        agent: str,
    ) -> list[dict]:
        """Fetch relevant knowledge for a query from all available sources.

        Returns a list of context dicts, each with ``source``, ``content``,
        and ``freshness`` keys.  Returns an empty list if all sources fail.
        """
        tasks = [
            self._fetch_eth_price(),
            self._fetch_base_status(),
            self._fetch_platform_activity(),
        ]

        results: list[dict] = []
        try:
            completed = await asyncio.wait_for(
                asyncio.gather(*tasks, return_exceptions=True),
                timeout=_SOURCE_TIMEOUT_SECONDS + 0.5,
            )
            for item in completed:
                if isinstance(item, dict) and item.get("content"):
                    results.append(item)
        except (asyncio.TimeoutError, Exception):
            logger.debug("Knowledge retrieval timed out or failed")

        return results

    async def _fetch_eth_price(self) -> dict:
        """Fetch current ETH price from CoinGecko free API."""
        cached = self._get_cached("eth_price")
        if cached:
            return cached

        try:
            import aiohttp

            url = "https://api.coingecko.com/api/v3/simple/price"
            params = {
                "ids": "ethereum",
                "vs_currencies": "usd",
                "include_24hr_change": "true",
            }
            async with aiohttp.ClientSession() as session:
                async with session.get(
                    url,
                    params=params,
                    timeout=aiohttp.ClientTimeout(total=_SOURCE_TIMEOUT_SECONDS),
                ) as resp:
                    if resp.status != 200:
                        return {}
                    data = await resp.json()

            eth = data.get("ethereum", {})
            price = eth.get("usd", 0)
            change = eth.get("usd_24h_change", 0)
            if not price:
                return {}

            sign = "+" if change >= 0 else ""
            result = {
                "source": "eth_price",
                "content": f"ETH: ${price:,.2f} ({sign}{change:.1f}% 24h)",
                "freshness": "live",
            }
            self._set_cached("eth_price", result)
            return result
        except Exception:
            logger.debug("ETH price fetch failed")
            return {}

    async def _fetch_base_status(self) -> dict:
        """Fetch Base L2 network status via public RPC."""
        cached = self._get_cached("base_status")
        if cached:
            return cached

        try:
            import aiohttp

            rpc_url = self._config.get("base_rpc_url", "https://mainnet.base.org")
            payload = {
                "jsonrpc": "2.0",
                "method": "eth_gasPrice",
                "params": [],
                "id": 1,
            }
            async with aiohttp.ClientSession() as session:
                async with session.post(
                    rpc_url,
                    json=payload,
                    timeout=aiohttp.ClientTimeout(total=_SOURCE_TIMEOUT_SECONDS),
                ) as resp:
                    if resp.status != 200:
                        return {}
                    data = await resp.json()

            gas_hex = data.get("result", "0x0")
            gas_wei = int(gas_hex, 16)
            gas_gwei = gas_wei / 1e9

            result = {
                "source": "base_status",
                "content": f"Base L2 gas: {gas_gwei:.3f} gwei",
                "freshness": "live",
            }
            self._set_cached("base_status", result)
            return result
        except Exception:
            logger.debug("Base status fetch failed")
            return {}

    async def _fetch_platform_activity(self) -> dict:
        """Summarise recent platform activity from local metrics."""
        cached = self._get_cached("platform_activity")
        if cached:
            return cached

        try:
            # If a monitoring module is available, pull recent stats
            from runtime.monitoring.metrics import MetricsCollector

            collector = MetricsCollector.instance()
            if collector is None:
                return {}

            snapshot = collector.snapshot()
            total = snapshot.get("requests_total", 0)
            if total == 0:
                return {}

            result = {
                "source": "platform_activity",
                "content": f"Platform: {total} requests processed",
                "freshness": "session",
            }
            self._set_cached("platform_activity", result)
            return result
        except Exception:
            logger.debug("Platform activity fetch failed")
            return {}
