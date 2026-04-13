"""Data aggregator — cached market data, gas prices, portfolio, and protocol metrics."""

from __future__ import annotations

import asyncio
import logging
import time
from typing import Any

from runtime.blockchain.web3_manager import Web3Manager

logger = logging.getLogger(__name__)

_CACHE_TTL_SECONDS = 30

# Baseline prices used when no external data source is available.
_FALLBACK_PRICES: dict[str, dict[str, Any]] = {
    "ETH": {"price_usd": 3200.0, "change_24h_pct": 0.0, "market_cap": 385_000_000_000, "volume_24h": 12_000_000_000},
    "BTC": {"price_usd": 68000.0, "change_24h_pct": 0.0, "market_cap": 1_340_000_000_000, "volume_24h": 25_000_000_000},
    "USDC": {"price_usd": 1.0, "change_24h_pct": 0.0, "market_cap": 32_000_000_000, "volume_24h": 5_000_000_000},
    "USDT": {"price_usd": 1.0, "change_24h_pct": 0.0, "market_cap": 110_000_000_000, "volume_24h": 40_000_000_000},
    "DAI": {"price_usd": 1.0, "change_24h_pct": 0.0, "market_cap": 5_000_000_000, "volume_24h": 300_000_000},
    "MATIC": {"price_usd": 0.72, "change_24h_pct": 0.0, "market_cap": 7_200_000_000, "volume_24h": 350_000_000},
    "ARB": {"price_usd": 1.10, "change_24h_pct": 0.0, "market_cap": 3_500_000_000, "volume_24h": 200_000_000},
    "OP": {"price_usd": 2.40, "change_24h_pct": 0.0, "market_cap": 2_800_000_000, "volume_24h": 180_000_000},
}

# Baseline gas in gwei per chain.
_FALLBACK_GAS: dict[str, dict[str, float]] = {
    "base": {"gwei": 0.005, "usd_simple_tx": 0.01},
    "ethereum": {"gwei": 25.0, "usd_simple_tx": 3.50},
    "polygon": {"gwei": 30.0, "usd_simple_tx": 0.005},
    "arbitrum": {"gwei": 0.1, "usd_simple_tx": 0.08},
    "optimism": {"gwei": 0.001, "usd_simple_tx": 0.06},
}

# Baseline TVL per protocol.
_FALLBACK_TVL: dict[str, float] = {
    "aave": 12_500_000_000,
    "compound": 3_200_000_000,
    "morpho": 1_800_000_000,
    "spark": 900_000_000,
    "uniswap": 5_500_000_000,
    "curve": 4_100_000_000,
    "balancer": 1_200_000_000,
}


class DataAggregator:
    """Provide cached market data, gas prices, portfolio views, and protocol metrics."""

    def __init__(self, config: dict) -> None:
        self._config = config
        self._web3 = Web3Manager.get_shared(config)
        self._cache: dict[str, tuple[float, Any]] = {}
        self._ttl = _CACHE_TTL_SECONDS
        self._logger = logging.getLogger(__name__)

    # ── Cache helpers ────────────────────────────────────────────────

    def _get_cached(self, key: str) -> Any | None:
        """Return cached value if not expired, else None."""
        entry = self._cache.get(key)
        if entry is None:
            return None
        expiry, data = entry
        if time.time() > expiry:
            del self._cache[key]
            return None
        return data

    def _set_cache(self, key: str, value: Any) -> None:
        """Store *value* in cache with expiry = now + TTL."""
        self._cache[key] = (time.time() + self._ttl, value)

    # ── Asset prices ─────────────────────────────────────────────────

    async def get_asset_price(self, symbol: str) -> dict:
        """Return price data for *symbol*, falling back to static defaults."""
        try:
            cache_key = f"price:{symbol.upper()}"
            cached = self._get_cached(cache_key)
            if cached is not None:
                cached["cached"] = True
                return cached

            upper = symbol.upper()
            price_source_cfg = self._config.get("price_feeds", {})

            # If an external feed is configured, attempt to fetch (with 2s timeout).
            if upper in price_source_cfg:
                try:
                    result = await asyncio.wait_for(
                        self._fetch_external_price(upper, price_source_cfg[upper]),
                        timeout=2.0,
                    )
                    if result is not None:
                        self._set_cache(cache_key, result)
                        result["cached"] = False
                        return result
                except (asyncio.TimeoutError, Exception) as exc:
                    self._logger.warning("External price fetch for %s timed out or failed: %s", upper, exc)

            # Fallback to static data.
            fallback = _FALLBACK_PRICES.get(upper, {
                "price_usd": 0.0,
                "change_24h_pct": 0.0,
                "market_cap": 0,
                "volume_24h": 0,
            })

            result = {
                "symbol": upper,
                "price_usd": fallback["price_usd"],
                "change_24h_pct": fallback["change_24h_pct"],
                "market_cap": fallback["market_cap"],
                "volume_24h": fallback["volume_24h"],
                "source": "unavailable" if upper not in _FALLBACK_PRICES else "fallback",
                "cached": False,
            }
            self._set_cache(cache_key, result)
            return result
        except Exception as exc:
            self._logger.error("get_asset_price failed: %s", exc, exc_info=True)
            return {
                "symbol": symbol.upper(),
                "price_usd": 0.0,
                "change_24h_pct": 0.0,
                "market_cap": 0,
                "volume_24h": 0,
                "source": "unavailable",
                "cached": False,
            }

    async def _fetch_external_price(self, symbol: str, feed_cfg: Any) -> dict | None:
        """Attempt to fetch price from an external API (placeholder for real integration)."""
        # In production this would call CoinGecko / DefiLlama / an on-chain oracle.
        # For now, return None to trigger fallback.
        return None

    # ── Gas prices ───────────────────────────────────────────────────

    async def get_gas_prices(self) -> dict:
        """Return gas prices across all supported chains."""
        try:
            cache_key = "gas_prices"
            cached = self._get_cached(cache_key)
            if cached is not None:
                cached["cached"] = True
                return cached

            chains: dict[str, dict[str, float]] = {}
            for chain_name, defaults in _FALLBACK_GAS.items():
                chains[chain_name] = {
                    "gwei": defaults["gwei"],
                    "usd_simple_tx": defaults["usd_simple_tx"],
                }

            # If Web3 is available and on a known chain, attempt live gas price.
            if self._web3.available and self._web3.w3 is not None:
                try:
                    live_gas_wei = await asyncio.wait_for(
                        asyncio.get_event_loop().run_in_executor(
                            None, self._web3.w3.eth.gas_price
                        ),
                        timeout=2.0,
                    )
                    live_gwei = round(live_gas_wei / 1e9, 4)
                    # Map the connected chain.
                    chain_map = {8453: "base", 1: "ethereum", 137: "polygon", 42161: "arbitrum", 10: "optimism"}
                    connected_chain = chain_map.get(self._web3.chain_id)
                    if connected_chain and connected_chain in chains:
                        chains[connected_chain]["gwei"] = live_gwei
                        chains[connected_chain]["usd_simple_tx"] = round(live_gwei * 21_000 / 1e9 * 3200, 4)
                except (asyncio.TimeoutError, Exception) as exc:
                    self._logger.warning("Live gas fetch failed: %s", exc)

            # Recommend the cheapest chain.
            recommended = min(chains, key=lambda c: chains[c]["usd_simple_tx"])

            result = {
                "chains": chains,
                "recommended": recommended,
                "cached": False,
            }
            self._set_cache(cache_key, result)
            return result
        except Exception as exc:
            self._logger.error("get_gas_prices failed: %s", exc, exc_info=True)
            return {"chains": {}, "recommended": "base", "cached": False}

    # ── Protocol TVL ─────────────────────────────────────────────────

    async def get_protocol_tvl(self, protocol: str) -> float:
        """Return total value locked for *protocol* (or 0.0 if unknown)."""
        try:
            cache_key = f"tvl:{protocol.lower()}"
            cached = self._get_cached(cache_key)
            if cached is not None:
                return cached

            tvl = _FALLBACK_TVL.get(protocol.lower(), 0.0)
            self._set_cache(cache_key, tvl)
            return tvl
        except Exception as exc:
            self._logger.error("get_protocol_tvl failed: %s", exc, exc_info=True)
            return 0.0

    # ── Yield rates ──────────────────────────────────────────────────

    async def get_yield_rates(self, asset: str) -> list[dict]:
        """Return yield options for *asset* across known protocols."""
        try:
            cache_key = f"yields:{asset.upper()}"
            cached = self._get_cached(cache_key)
            if cached is not None:
                return cached

            # Static baseline yield data.
            base_rates = {
                "aave": 3.2,
                "compound": 2.8,
                "morpho": 4.1,
                "spark": 3.5,
            }
            asset_offset = (sum(ord(c) for c in asset.upper()) % 10) * 0.05

            results: list[dict] = []
            for protocol, base in base_rates.items():
                results.append({
                    "protocol": protocol,
                    "asset": asset.upper(),
                    "apy_pct": round(base + asset_offset, 2),
                    "tvl": _FALLBACK_TVL.get(protocol, 0.0),
                })

            results.sort(key=lambda r: r["apy_pct"], reverse=True)
            self._set_cache(cache_key, results)
            return results
        except Exception as exc:
            self._logger.error("get_yield_rates failed: %s", exc, exc_info=True)
            return []

    # ── Portfolio ─────────────────────────────────────────────────────

    async def get_user_portfolio(self, wallet: str) -> dict:
        """Return a portfolio summary for *wallet*."""
        try:
            cache_key = f"portfolio:{wallet}"
            cached = self._get_cached(cache_key)
            if cached is not None:
                cached["cached"] = True
                return cached

            tokens: list[dict] = []
            nfts: list[dict] = []
            defi_positions: list[dict] = []
            staking_positions: list[dict] = []
            streams: list[dict] = []
            rwa_positions: list[dict] = []
            total_value = 0.0

            # If Web3 is available, try to fetch the native balance.
            if self._web3.available and self._web3.w3 is not None:
                try:
                    balance = await asyncio.wait_for(
                        asyncio.get_event_loop().run_in_executor(
                            None,
                            lambda: self._web3.get_balance_eth(wallet),
                        ),
                        timeout=2.0,
                    )
                    if balance > 0:
                        eth_price = _FALLBACK_PRICES.get("ETH", {}).get("price_usd", 3200.0)
                        value_usd = round(balance * eth_price, 2)
                        tokens.append({
                            "symbol": "ETH",
                            "balance": balance,
                            "value_usd": value_usd,
                            "chain": "base",
                        })
                        total_value += value_usd
                except (asyncio.TimeoutError, Exception) as exc:
                    self._logger.warning("Portfolio balance fetch failed: %s", exc)

            result = {
                "wallet": wallet,
                "total_value_usd": round(total_value, 2),
                "tokens": tokens,
                "nfts": nfts,
                "defi_positions": defi_positions,
                "staking_positions": staking_positions,
                "streams": streams,
                "rwa_positions": rwa_positions,
                "cached": False,
            }
            self._set_cache(cache_key, result)
            return result
        except Exception as exc:
            self._logger.error("get_user_portfolio failed: %s", exc, exc_info=True)
            return {
                "wallet": wallet,
                "total_value_usd": 0.0,
                "tokens": [],
                "nfts": [],
                "defi_positions": [],
                "staking_positions": [],
                "streams": [],
                "rwa_positions": [],
                "cached": False,
            }

    # ── NFT floor price ──────────────────────────────────────────────

    async def get_nft_floor(self, collection: str) -> float:
        """Return the floor price for *collection* (ETH), or 0.0 if unknown."""
        try:
            cache_key = f"nft_floor:{collection.lower()}"
            cached = self._get_cached(cache_key)
            if cached is not None:
                return cached

            # Static defaults for well-known collections.
            known_floors: dict[str, float] = {
                "cryptopunks": 48.0,
                "boredapeyachtclub": 12.5,
                "azuki": 5.2,
                "pudgypenguins": 8.0,
                "milady": 3.8,
            }
            floor = known_floors.get(collection.lower(), 0.0)
            self._set_cache(cache_key, floor)
            return floor
        except Exception as exc:
            self._logger.error("get_nft_floor failed: %s", exc, exc_info=True)
            return 0.0

    # ── Market conditions ────────────────────────────────────────────

    async def get_market_conditions(self) -> dict:
        """Return a high-level snapshot of current market conditions."""
        try:
            cache_key = "market_conditions"
            cached = self._get_cached(cache_key)
            if cached is not None:
                cached["cached"] = True
                return cached

            gas_data = await self.get_gas_prices()
            eth_gas_gwei = gas_data.get("chains", {}).get("ethereum", {}).get("gwei", 25.0)

            # Classify gas environment.
            if eth_gas_gwei < 15:
                gas_env = "low"
            elif eth_gas_gwei < 50:
                gas_env = "normal"
            else:
                gas_env = "high"

            result = {
                "trend": "neutral",
                "fear_greed_index": 50,
                "gas_environment": gas_env,
                "eth_gas_gwei": eth_gas_gwei,
                "cached": False,
            }
            self._set_cache(cache_key, result)
            return result
        except Exception as exc:
            self._logger.error("get_market_conditions failed: %s", exc, exc_info=True)
            return {
                "trend": "neutral",
                "fear_greed_index": 50,
                "gas_environment": "normal",
                "cached": False,
            }
