"""P4: honest ETH/USD price feed.

Primary source is the on-chain Chainlink ETH/USD aggregator (read via configured
RPC); a Coinbase spot REST call is the fallback; results cache for 30s. If neither
source is available the feed raises PriceUnavailable — the route then returns an
honest 503 and NEVER a stale/invented number.

Feed addresses are config-driven (blockchain.price_feeds.eth_usd) with a
verify-against-chainlink-docs note in the config example — not hardcoded trust.

The cache is per instance, so it only works for a caller that keeps one
instance: ServiceRoutes owns one for /price, the paymaster route and the
portfolio routes. Concurrent callers of one instance share a single in-flight
read rather than each starting their own. The Chainlink read is synchronous
web3, so it runs in a worker thread with a timeout; it used to run on the event
loop, and every other request waited for its RPC round trips.
"""

from __future__ import annotations

import asyncio
import logging
import time
from typing import Any, Callable, Optional

logger = logging.getLogger(__name__)

_CACHE_TTL = 30.0
# Bound on one Chainlink read (the whole read, and each HTTP request in it).
_SOURCE_TIMEOUT_SECONDS = 4.0
COINBASE_SPOT_URL = "https://api.coinbase.com/v2/prices/ETH-USD/spot"

# Minimal Chainlink AggregatorV3Interface ABI (latestRoundData + decimals).
AGGREGATOR_ABI = [
    {"inputs": [], "name": "latestRoundData",
     "outputs": [{"name": "roundId", "type": "uint80"},
                 {"name": "answer", "type": "int256"},
                 {"name": "startedAt", "type": "uint256"},
                 {"name": "updatedAt", "type": "uint256"},
                 {"name": "answeredInRound", "type": "uint80"}],
     "stateMutability": "view", "type": "function"},
    {"inputs": [], "name": "decimals",
     "outputs": [{"name": "", "type": "uint8"}],
     "stateMutability": "view", "type": "function"},
]


class PriceUnavailable(Exception):
    """No price source could be reached — the caller must fail honestly (503)."""


class PriceFeed:
    """ETH/USD price with Chainlink-primary / Coinbase-fallback and a 30s cache.

    ``chainlink_reader`` and ``coinbase_fetcher`` are injectable for tests; the
    defaults use the configured RPC and a real HTTP GET.
    """

    def __init__(self, config: dict,
                 chainlink_reader: Optional[Callable] = None,
                 coinbase_fetcher: Optional[Callable] = None) -> None:
        self._config = config or {}
        self._chainlink = chainlink_reader or self._default_chainlink
        self._coinbase = coinbase_fetcher or self._default_coinbase
        self._cache: Optional[dict] = None
        self._cache_at: float = 0.0
        self._lock: Optional[asyncio.Lock] = None
        self._lock_loop: Any = None
        # Completed reads, and whether the latest one failed: a caller that
        # queued behind a read takes that read's outcome, success or failure.
        self._reads_done: int = 0
        self._last_read_failed: bool = False

    def _read_lock(self) -> asyncio.Lock:
        """One lock per running loop (an asyncio.Lock is bound to the loop that
        first waits on it, and tests run each case on a fresh loop)."""
        loop = asyncio.get_running_loop()
        if self._lock is None or self._lock_loop is not loop:
            self._lock, self._lock_loop = asyncio.Lock(), loop
        return self._lock

    def _fresh(self, now: float) -> Optional[dict]:
        if self._cache is not None and (now - self._cache_at) < _CACHE_TTL:
            return {**self._cache, "cached": True}
        return None

    def _feed_address(self) -> str:
        bc = self._config.get("blockchain", {}) if isinstance(self._config, dict) else {}
        return str((bc.get("price_feeds", {}) or {}).get("eth_usd", "")).strip()

    async def eth_usd(self, *, now: Optional[float] = None) -> dict:
        now = time.time() if now is None else now
        fresh = self._fresh(now)
        if fresh is not None:
            return fresh
        queued_at = self._reads_done
        async with self._read_lock():
            # A caller that waited here while another read ran gets that read:
            # its quote if it succeeded, its failure if it did not. Failures
            # are still not cached; the next caller who did not wait retries.
            fresh = self._fresh(now)
            if fresh is not None:
                return fresh
            if self._reads_done != queued_at and self._last_read_failed:
                raise PriceUnavailable(
                    "ETH/USD price unavailable (the read this request waited "
                    "on found no reachable source).")
            try:
                result = await self._read(now)
            except Exception:
                # (A cancelled read is not an outcome: waiters read for themselves.)
                self._reads_done += 1
                self._last_read_failed = True
                raise
            self._reads_done += 1
            self._last_read_failed = False
            return result

    async def _read(self, now: float) -> dict:
        result: Optional[dict] = None
        # 1) Chainlink (on-chain, authoritative)
        try:
            result = await self._chainlink()
        except Exception as exc:
            logger.info("Chainlink ETH/USD read failed: %s", exc)
        # 2) Coinbase fallback
        if result is None:
            try:
                result = await self._coinbase()
            except Exception as exc:
                logger.info("Coinbase ETH/USD fallback failed: %s", exc)

        if result is None or not result.get("price"):
            raise PriceUnavailable(
                "ETH/USD price unavailable (no configured RPC/Chainlink feed and "
                "the Coinbase fallback could not be reached).")

        result.setdefault("pair", "ETH-USD")
        result.setdefault("updated_at", int(now))
        result["cached"] = False
        self._cache, self._cache_at = result, now
        return result

    # ── default sources ──────────────────────────────────────────────────

    async def _default_chainlink(self) -> Optional[dict]:
        addr = self._feed_address()
        if not addr:
            return None
        bc = self._config.get("blockchain", {})
        rpc = bc.get("rpc_url", "")
        if not rpc or str(rpc).startswith("YOUR_"):
            return None
        timeout = _SOURCE_TIMEOUT_SECONDS
        loop = asyncio.get_running_loop()
        return await asyncio.wait_for(
            loop.run_in_executor(None, self._read_chainlink_blocking, addr, rpc, timeout),
            timeout=timeout)

    @staticmethod
    def _read_chainlink_blocking(addr: str, rpc: str, timeout: float) -> Optional[dict]:
        """Synchronous web3 calls; runs in a worker thread, never on the loop."""
        from web3 import Web3
        w3 = Web3(Web3.HTTPProvider(rpc, request_kwargs={"timeout": timeout}))
        agg = w3.eth.contract(address=Web3.to_checksum_address(addr), abi=AGGREGATOR_ABI)
        decimals = agg.functions.decimals().call()
        _, answer, _, updated_at, _ = agg.functions.latestRoundData().call()
        if answer <= 0:
            return None
        return {"price": answer / (10 ** decimals), "decimals": decimals,
                "source": "chainlink", "updated_at": int(updated_at)}

    async def _default_coinbase(self) -> Optional[dict]:
        import aiohttp
        async with aiohttp.ClientSession() as s:
            async with s.get(COINBASE_SPOT_URL, timeout=aiohttp.ClientTimeout(total=6)) as r:
                data = await r.json()
        amount = ((data or {}).get("data") or {}).get("amount")
        if amount is None:
            return None
        return {"price": float(amount), "decimals": 2, "source": "coinbase"}
