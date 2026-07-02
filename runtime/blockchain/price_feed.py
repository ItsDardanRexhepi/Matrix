"""P4: honest ETH/USD price feed.

Primary source is the on-chain Chainlink ETH/USD aggregator (read via configured
RPC); a Coinbase spot REST call is the fallback; results cache for 30s. If neither
source is available the feed raises PriceUnavailable — the route then returns an
honest 503 and NEVER a stale/invented number.

Feed addresses are config-driven (blockchain.price_feeds.eth_usd) with a
verify-against-chainlink-docs note in the config example — not hardcoded trust.
"""

from __future__ import annotations

import logging
import time
from typing import Any, Callable, Optional

logger = logging.getLogger(__name__)

_CACHE_TTL = 30.0
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

    def _feed_address(self) -> str:
        bc = self._config.get("blockchain", {}) if isinstance(self._config, dict) else {}
        return str((bc.get("price_feeds", {}) or {}).get("eth_usd", "")).strip()

    async def eth_usd(self, *, now: Optional[float] = None) -> dict:
        now = time.time() if now is None else now
        if self._cache is not None and (now - self._cache_at) < _CACHE_TTL:
            return {**self._cache, "cached": True}

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
        from web3 import Web3
        bc = self._config.get("blockchain", {})
        rpc = bc.get("rpc_url", "")
        if not rpc or str(rpc).startswith("YOUR_"):
            return None
        w3 = Web3(Web3.HTTPProvider(rpc))
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
