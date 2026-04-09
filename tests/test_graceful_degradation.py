"""Tests for oracle + service-dispatcher graceful degradation."""

import json
import time

import pytest

from runtime.blockchain.services.oracle_gateway.gateway import OracleGateway
from runtime.blockchain.services.oracle_gateway.cache import OracleCache
from runtime.blockchain.services.service_dispatcher import ServiceDispatcher


# ── Oracle gateway ────────────────────────────────────────────────────


class TestOracleStaleCache:
    @pytest.mark.asyncio
    async def test_get_stale_returns_expired_entry(self):
        cache = OracleCache(ttls={"price_feed": 1})
        await cache.set("price_feed", "k", {"price": 42})
        # Wait for the entry to expire.
        await _sleep_until_expired()
        # Normal get should miss.
        assert await cache.get("price_feed", "k") is None
        # Stale get should still return it.
        value, age = await cache.get_stale("price_feed", "k", max_age_seconds=60)
        assert value == {"price": 42}
        assert age is not None and age >= 0

    @pytest.mark.asyncio
    async def test_get_stale_respects_max_age(self):
        cache = OracleCache(ttls={"price_feed": 1})
        await cache.set("price_feed", "k", {"price": 1})
        await _sleep_until_expired()
        # max_age 0 means anything older than 0s is rejected.
        value, age = await cache.get_stale("price_feed", "k", max_age_seconds=0.0)
        assert value is None
        assert age is None

    @pytest.mark.asyncio
    async def test_request_safe_falls_back_to_stale(self):
        gw = OracleGateway({"oracle": {"cache_ttls": {"price_feed": 1}}})
        # Seed the cache with a healthy response by hijacking the
        # private cache directly (no live RPC required).
        params = {"pair": "ETH/USD"}
        cache_key = OracleGateway._cache_key(params)
        await gw._cache.set("price_feed", cache_key, {
            "oracle_type": "price_feed",
            "pair": "ETH/USD",
            "price": 3000,
        })
        await _sleep_until_expired()

        # request_safe should fall back to the stale entry when the
        # provider raises (price feed isn't configured -> raises).
        result = await gw.request_safe("price_feed", params)
        assert result["degraded"] is True
        assert result["stale"] is True
        assert result["price"] == 3000
        assert "error" in result

    @pytest.mark.asyncio
    async def test_request_safe_returns_error_when_no_cache(self):
        gw = OracleGateway({})
        result = await gw.request_safe("price_feed", {"pair": "ETH/USD"})
        assert result["degraded"] is True
        assert result["stale"] is False
        assert "error" in result


async def _sleep_until_expired():
    import asyncio
    await asyncio.sleep(1.05)


# ── Service dispatcher ────────────────────────────────────────────────


class _BoomService:
    async def boom(self):
        raise RuntimeError("upstream RPC unreachable")

    async def reject(self, required_arg):  # noqa: ARG002 — only the signature matters
        return "ok"

    async def not_built(self):
        raise NotImplementedError("feature gated off")


class _StubRegistry:
    """Drop-in replacement for ServiceRegistry used by the dispatcher."""

    def __init__(self):
        self._services = {"contract_conversion": _BoomService()}

    def get(self, name):
        if name not in self._services:
            raise KeyError(name)
        return self._services[name]


@pytest.fixture
def dispatcher():
    disp = ServiceDispatcher({"blockchain": {"platform_wallet": "0x0"}})
    # Inject the stub registry so we never touch real RPC code.
    disp._registry = _StubRegistry()
    return disp


class TestDispatcherDegradation:
    @pytest.mark.asyncio
    async def test_unknown_action_categorised(self, dispatcher):
        out = json.loads(await dispatcher.execute("not_a_real_action"))
        assert out["status"] == "error"
        assert out["error_category"] == "not_found"
        assert out["degraded"] is False

    @pytest.mark.asyncio
    async def test_service_unavailable_marked_degraded(self, dispatcher):
        # mint_nft -> nft_services, which the stub registry doesn't have.
        out = json.loads(await dispatcher.execute("mint_nft", params={}))
        assert out["status"] == "error"
        assert out["error_category"] == "service_unavailable"
        assert out["degraded"] is True

    @pytest.mark.asyncio
    async def test_validation_error_not_degraded(self, dispatcher):
        # Replace the contract_conversion stub with one that requires args
        # so calling it with no params raises TypeError.
        from runtime.blockchain.services.service_dispatcher import ACTION_MAP
        ACTION_MAP["__test_validate__"] = ("contract_conversion", "reject")
        try:
            out = json.loads(
                await dispatcher.execute("__test_validate__", params={})
            )
            assert out["status"] == "error"
            assert out["error_category"] == "validation"
            assert out["degraded"] is False
        finally:
            del ACTION_MAP["__test_validate__"]

    @pytest.mark.asyncio
    async def test_runtime_error_marked_degraded(self, dispatcher):
        from runtime.blockchain.services.service_dispatcher import ACTION_MAP
        ACTION_MAP["__test_boom__"] = ("contract_conversion", "boom")
        try:
            out = json.loads(await dispatcher.execute("__test_boom__", params={}))
            assert out["status"] == "error"
            assert out["error_category"] == "service_error"
            assert out["degraded"] is True
        finally:
            del ACTION_MAP["__test_boom__"]

    @pytest.mark.asyncio
    async def test_not_implemented_marked_degraded(self, dispatcher):
        from runtime.blockchain.services.service_dispatcher import ACTION_MAP
        ACTION_MAP["__test_ni__"] = ("contract_conversion", "not_built")
        try:
            out = json.loads(await dispatcher.execute("__test_ni__", params={}))
            assert out["status"] == "error"
            assert out["error_category"] == "not_implemented"
            assert out["degraded"] is True
        finally:
            del ACTION_MAP["__test_ni__"]
