"""Real-time knowledge retriever for agent context enrichment.

Fetches live market data, network status, and user on-chain history
to inject into agent prompts.  Every source is optional, has a strict
2-second timeout, and fails silently.  Results are cached for 30 seconds
to avoid hammering external APIs.

This module is completely non-blocking: a knowledge fetch must never
delay or break a response.

That sentence used to be false in the way that costs the most, because it
was false on the slow path. :meth:`KnowledgeRetriever.get_relevant_context`
was awaited INLINE in front of the model call
(``runtime/protocols/integration.py``), bounded by a 2.5-second ``wait_for`` —
so one unreachable source added up to two and a half seconds to every reply.
The 30-second cache that would have hidden most of it never hit once, for a
reason no TTL tuning would have fixed: the caller builds a NEW retriever on
every turn and the cache was an instance attribute, so it arrived empty every
time. A cache discarded before it can expire is not a cache.

Two changes make the sentence true rather than aspirational:

  * the cache is process-wide, so it outlives the per-turn instance and the
    30-second TTL is reachable;
  * ``get_relevant_context`` reads the cache and returns. Nothing is awaited on
    the caller's path. When an entry is missing or stale it SCHEDULES a
    refresh, which lands in the cache for the next turn.

The cost of that is honest and worth naming: the first turn after a cold start
or an expiry carries no live data. Enrichment is a nice-to-have and a reply is
not — a turn that waits on CoinGecko to say something friendlier has made the
wrong trade, and this module said so before it did it.
"""

from __future__ import annotations

import asyncio
import logging
import time
from typing import Any

logger = logging.getLogger(__name__)

_CACHE_TTL_SECONDS = 30
_SOURCE_TIMEOUT_SECONDS = 2.0

# The keys :meth:`KnowledgeRetriever._refresh` writes and
# :meth:`KnowledgeRetriever.get_relevant_context` reads, in the order they are
# offered to the agent.
_SOURCE_KEYS = ("eth_price", "base_status", "platform_activity")

# Process-wide, because the caller builds a retriever per turn. Instance-local
# state here is state that never survives to be used.
_SHARED_CACHE: dict[str, tuple[float, dict]] = {}

# Strong references to in-flight refreshes. asyncio only holds a weak one, so a
# task with no other referent can be garbage-collected mid-await.
_REFRESH_TASKS: set[asyncio.Task] = set()


def clear_cache() -> None:
    """Drop every cached entry and cancel any refresh in flight.

    Exists for tests and for an operator who wants the next turn to re-fetch;
    a process-wide cache that nothing can reset is a process-wide problem.
    """
    _SHARED_CACHE.clear()
    for task in list(_REFRESH_TASKS):
        try:
            task.cancel()
        except RuntimeError:
            # Its loop is already closed — the task is going nowhere either way,
            # and a cleanup helper that raises is worse than a task that lingers.
            pass
    _REFRESH_TASKS.clear()


class KnowledgeRetriever:
    """Retrieves real-time context from multiple knowledge sources."""

    def __init__(self, config: dict | None = None, *,
                 cache: dict[str, tuple[float, dict]] | None = None) -> None:
        self._config = config or {}
        # Shared by default — see the module docstring. Pass ``cache={}`` for an
        # isolated one.
        self._cache = _SHARED_CACHE if cache is None else cache

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
        """Return the knowledge already on hand. Never waits for a source.

        Returns a list of context dicts, each with ``source``, ``content``,
        and ``freshness`` keys. Returns an empty list when nothing fresh is
        cached — which is the honest answer on a cold start, and a far better
        one than a reply that arrived two and a half seconds late.

        A missing or expired entry schedules :meth:`_refresh`, whose result
        lands in the cache for the next turn. The caller's path does not await
        it, and an exception inside it cannot reach the caller.
        """
        results: list[dict] = []
        for key in _SOURCE_KEYS:
            cached = self._get_cached(key)
            if cached and cached.get("content"):
                results.append(cached)

        if len(results) < len(_SOURCE_KEYS):
            self._schedule_refresh()
        return results

    def _schedule_refresh(self) -> None:
        """Start a background refresh, unless one is already running.

        No loop means no caller to delay either — a synchronous context gets
        the cache as it stands and no error.
        """
        try:
            loop = asyncio.get_running_loop()
        except RuntimeError:
            logger.debug("no running loop — knowledge refresh not scheduled")
            return
        # Drop anything finished, and anything belonging to a loop that has
        # since closed — a test process and a reloaded gateway both do that,
        # and a stale entry here would block every future refresh forever.
        for stale in [t for t in _REFRESH_TASKS
                      if t.done() or t.get_loop() is not loop]:
            _REFRESH_TASKS.discard(stale)
        if _REFRESH_TASKS:
            return
        task = loop.create_task(self._refresh())
        _REFRESH_TASKS.add(task)
        task.add_done_callback(_REFRESH_TASKS.discard)

    async def _refresh(self) -> list[dict]:
        """Fetch every stale source, bounded, writing through the cache.

        Runs off the caller's path. Every failure is swallowed here: this is a
        fire-and-forget task, so an exception escaping it would surface as an
        unretrieved-exception warning attached to nothing.
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
        except asyncio.CancelledError:
            raise
        except Exception:
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
