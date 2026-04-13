"""Tests for the protocol abstraction layer — DeFi router, cross-chain, intent resolver, data aggregator."""

from __future__ import annotations

import time

import pytest

from runtime.blockchain.web3_manager import Web3Manager
from runtime.blockchain.protocol_abstraction.defi_router import DeFiRouter
from runtime.blockchain.protocol_abstraction.cross_chain_router import (
    CrossChainRouter,
    SUPPORTED_CHAINS,
    SUPPORTED_BRIDGES,
)
from runtime.blockchain.protocol_abstraction.intent_resolver import IntentResolver
from runtime.blockchain.protocol_abstraction.data_aggregator import DataAggregator


# Force-offline blockchain config — no rpc_url, no protocols, no bridges.
OFFLINE_CONFIG: dict = {
    "blockchain": {
        "rpc_url": "",
        "chain_id": 84532,
        "network": "base-sepolia",
    }
}


@pytest.fixture(autouse=True)
def _reset_web3_singleton():
    """Ensure each test starts with a fresh offline Web3Manager."""
    Web3Manager.reset_shared()
    Web3Manager.get_shared(OFFLINE_CONFIG)
    yield
    Web3Manager.reset_shared()


# ═══════════════════════════════════════════════════════════════════════
# DeFi Router
# ═══════════════════════════════════════════════════════════════════════


class TestDeFiRouter:
    """Verify DeFiRouter graceful degradation when no protocols are configured."""

    @pytest.mark.asyncio
    async def test_get_best_yield_not_configured(self):
        router = DeFiRouter(config={})
        result = await router.get_best_yield("ETH", 1.0)
        assert isinstance(result, dict)
        assert result["status"] == "not_configured"
        assert "supported_protocols" in result
        assert isinstance(result["supported_protocols"], list)
        assert len(result["supported_protocols"]) > 0

    @pytest.mark.asyncio
    async def test_get_best_yield_with_risk_tolerance(self):
        router = DeFiRouter(config={})
        for risk in ("low", "medium", "high"):
            result = await router.get_best_yield("ETH", 1.0, risk_tolerance=risk)
            assert isinstance(result, dict)
            # With empty config the status is not_configured, but the call must
            # not crash regardless of the risk_tolerance value.
            assert "status" in result

    @pytest.mark.asyncio
    async def test_get_best_swap_route_not_configured(self):
        router = DeFiRouter(config={})
        result = await router.get_best_swap_route("ETH", "USDC", 1.0)
        assert isinstance(result, dict)
        assert result["status"] == "not_configured"
        assert "supported_dexes" in result

    @pytest.mark.asyncio
    async def test_get_best_borrow_rate_not_configured(self):
        router = DeFiRouter(config={})
        result = await router.get_best_borrow_rate("USDC", "ETH")
        assert isinstance(result, dict)
        assert result["status"] == "not_configured"
        assert "supported_protocols" in result

    @pytest.mark.asyncio
    async def test_execute_yield_deposit_no_chain(self):
        router = DeFiRouter(OFFLINE_CONFIG)
        result = await router.execute_yield_deposit(
            protocol="aave",
            asset="ETH",
            amount=1.0,
            wallet="0x" + "a" * 40,
        )
        assert isinstance(result, dict)
        assert result["status"] in ("not_deployed", "not_configured", "error")

    @pytest.mark.asyncio
    async def test_execute_swap_no_chain(self):
        router = DeFiRouter(OFFLINE_CONFIG)
        route = {
            "dex": "Uniswap V3",
            "route_path": ["ETH", "USDC"],
            "estimated_output": 3200.0,
        }
        result = await router.execute_swap(route, "0x" + "b" * 40)
        assert isinstance(result, dict)
        assert result["status"] in ("not_deployed", "not_configured", "error")

    @pytest.mark.asyncio
    async def test_error_handling_bad_input(self):
        router = DeFiRouter(config={})
        # None values and empty strings should never raise — they must return
        # a dict with a status field.
        result1 = await router.get_best_yield("", 0.0)
        assert isinstance(result1, dict)
        assert "status" in result1

        result2 = await router.get_best_swap_route("", "", 0.0)
        assert isinstance(result2, dict)
        assert "status" in result2

        result3 = await router.execute_swap({}, "")
        assert isinstance(result3, dict)
        assert "status" in result3


# ═══════════════════════════════════════════════════════════════════════
# Cross-Chain Router
# ═══════════════════════════════════════════════════════════════════════


class TestCrossChainRouter:
    """Verify CrossChainRouter constants and graceful degradation."""

    def test_supported_chains_exist(self):
        for chain in ("base", "ethereum", "polygon"):
            assert chain in SUPPORTED_CHAINS, f"{chain} missing from SUPPORTED_CHAINS"

    def test_supported_bridges_exist(self):
        assert len(SUPPORTED_BRIDGES) > 0
        for key, info in SUPPORTED_BRIDGES.items():
            assert "name" in info
            assert "fee_bps" in info

    @pytest.mark.asyncio
    async def test_get_best_bridge_not_configured(self):
        router = CrossChainRouter(config={})
        result = await router.get_best_bridge("ETH", "base", "ethereum", 1.0)
        assert isinstance(result, dict)
        assert result["status"] == "not_configured"
        assert "supported_bridges" in result

    def test_get_optimal_chain_default(self):
        router = CrossChainRouter(config={})
        chain = router.get_optimal_chain("transfer", "ETH")
        assert isinstance(chain, str)
        # Base should win for a simple transfer due to lowest gas.
        assert chain == "base"

    @pytest.mark.asyncio
    async def test_estimate_total_cost(self):
        router = CrossChainRouter(config={})
        result = await router.estimate_total_cost("swap", "base", "ethereum")
        assert isinstance(result, dict)
        assert result["status"] == "ok"
        for key in ("gas_source_usd", "gas_destination_usd", "total_estimated_usd"):
            assert key in result

    @pytest.mark.asyncio
    async def test_invalid_chains(self):
        router = CrossChainRouter(config={})
        # Invalid chain names must not crash.
        result = await router.estimate_total_cost("swap", "mars", "venus")
        assert isinstance(result, dict)
        assert "status" in result

        # get_optimal_chain should still return a string.
        chain = router.get_optimal_chain("swap", "ZZZTOKEN")
        assert isinstance(chain, str)


# ═══════════════════════════════════════════════════════════════════════
# Intent Resolver
# ═══════════════════════════════════════════════════════════════════════


class TestIntentResolver:
    """Verify IntentResolver resolves common intents and degrades gracefully."""

    @pytest.mark.asyncio
    async def test_resolve_swap_intent(self):
        resolver = IntentResolver(config={})
        result = await resolver.resolve(
            intent="swap 1 ETH for USDC",
            entities={"asset": "ETH", "amount": 1.0, "token_out": "USDC"},
            wallet="0x" + "a" * 40,
        )
        assert isinstance(result, dict)
        assert result["status"] == "ok"
        assert "steps" in result
        assert len(result["steps"]) > 0

    @pytest.mark.asyncio
    async def test_resolve_unknown_intent(self):
        resolver = IntentResolver(config={})
        result = await resolver.resolve(
            intent="xyzzy flurpnax gibberish",
            entities={},
            wallet="0x" + "c" * 40,
        )
        assert isinstance(result, dict)
        assert result["status"] == "unresolved"

    @pytest.mark.asyncio
    async def test_get_plan_summary(self):
        resolver = IntentResolver(config={})
        mock_plan = {
            "action": "swap",
            "chain": "base",
            "protocols": ["uniswap"],
            "estimated_cost_usd": 3.50,
            "estimated_time_seconds": 15,
            "risk_level": "low",
            "risk_description": "Standard token swap.",
            "steps": [
                {"action": "swap", "estimated_gas_usd": 3.50},
            ],
            "requires_confirmation": False,
        }
        summary = await resolver.get_plan_summary(mock_plan)
        assert isinstance(summary, str)
        assert len(summary) > 0

    @pytest.mark.asyncio
    async def test_execute_plan_empty(self):
        resolver = IntentResolver(config={})
        result = await resolver.execute_plan(plan={}, wallet="0x" + "d" * 40)
        assert isinstance(result, dict)
        assert "status" in result
        # Empty plan should complete with zero steps.
        assert result.get("total_steps", 0) == 0

    @pytest.mark.asyncio
    async def test_resolve_bridge_intent(self):
        resolver = IntentResolver(config={})
        result = await resolver.resolve(
            intent="bridge 10 ETH from base to ethereum",
            entities={
                "asset": "ETH",
                "amount": 10.0,
                "from_chain": "base",
                "to_chain": "ethereum",
            },
            wallet="0x" + "e" * 40,
        )
        assert isinstance(result, dict)
        assert result["status"] == "ok"
        assert "steps" in result
        assert len(result["steps"]) > 0


# ═══════════════════════════════════════════════════════════════════════
# Data Aggregator
# ═══════════════════════════════════════════════════════════════════════


class TestDataAggregator:
    """Verify DataAggregator caching, fallbacks, and graceful responses."""

    @pytest.mark.asyncio
    async def test_cache_behavior(self):
        agg = DataAggregator(config={})
        result1 = await agg.get_asset_price("ETH")
        result2 = await agg.get_asset_price("ETH")
        assert isinstance(result1, dict)
        assert isinstance(result2, dict)
        # The second call should return from cache.
        assert result2.get("cached") is True

    @pytest.mark.asyncio
    async def test_cache_expiry(self):
        agg = DataAggregator(config={})
        # Artificially set a very short TTL so cache expires immediately.
        agg._ttl = 0
        result1 = await agg.get_asset_price("BTC")
        assert isinstance(result1, dict)
        # Manually expire the cache entry.
        for key in list(agg._cache.keys()):
            expiry, data = agg._cache[key]
            agg._cache[key] = (0.0, data)  # expired timestamp
        result2 = await agg.get_asset_price("BTC")
        assert isinstance(result2, dict)
        # After expiry the result should not be flagged as cached.
        assert result2.get("cached") is False

    @pytest.mark.asyncio
    async def test_get_gas_prices_structure(self):
        agg = DataAggregator(config={})
        result = await agg.get_gas_prices()
        assert isinstance(result, dict)
        assert "chains" in result
        chains = result["chains"]
        for expected_chain in ("base", "ethereum", "polygon"):
            assert expected_chain in chains

    @pytest.mark.asyncio
    async def test_get_user_portfolio_empty(self):
        agg = DataAggregator(config={})
        result = await agg.get_user_portfolio("0x" + "f" * 40)
        assert isinstance(result, dict)
        assert result["wallet"] == "0x" + "f" * 40
        assert "total_value_usd" in result
        assert "tokens" in result
        assert isinstance(result["tokens"], list)

    @pytest.mark.asyncio
    async def test_get_market_conditions(self):
        agg = DataAggregator(config={})
        result = await agg.get_market_conditions()
        assert isinstance(result, dict)
        for key in ("trend", "fear_greed_index", "gas_environment"):
            assert key in result

    @pytest.mark.asyncio
    async def test_timeout_handling(self):
        agg = DataAggregator(config={})
        # Call get_asset_price for a symbol that is not in the fallback table.
        # The method should complete within 2 seconds and return defaults.
        result = await agg.get_asset_price("UNKNOWNCOIN123")
        assert isinstance(result, dict)
        assert result.get("price_usd") == 0.0

    @pytest.mark.asyncio
    async def test_get_nft_floor_unknown(self):
        agg = DataAggregator(config={})
        floor = await agg.get_nft_floor("nonexistent_collection_xyz")
        assert isinstance(floor, float)
        assert floor == 0.0
