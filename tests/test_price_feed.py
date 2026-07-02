"""P4: ETH/USD price feed — Chainlink primary, Coinbase fallback, honest 503."""

import pytest

from runtime.blockchain.price_feed import PriceFeed, PriceUnavailable


def _cfg():
    return {"blockchain": {"chain_id": 84532}}


@pytest.mark.asyncio
async def test_chainlink_primary_used_when_available():
    async def chainlink():
        return {"price": 3200.5, "decimals": 8, "source": "chainlink", "updated_at": 111}

    async def coinbase():
        raise AssertionError("fallback must not be called when Chainlink works")

    pf = PriceFeed(_cfg(), chainlink_reader=chainlink, coinbase_fetcher=coinbase)
    d = await pf.eth_usd(now=1000.0)
    assert d["price"] == 3200.5 and d["source"] == "chainlink" and d["cached"] is False


@pytest.mark.asyncio
async def test_falls_back_to_coinbase_when_chainlink_unavailable():
    async def chainlink():
        return None  # unconfigured / feed absent

    async def coinbase():
        return {"price": 3150.0, "decimals": 2, "source": "coinbase"}

    pf = PriceFeed(_cfg(), chainlink_reader=chainlink, coinbase_fetcher=coinbase)
    d = await pf.eth_usd(now=1000.0)
    assert d["price"] == 3150.0 and d["source"] == "coinbase"


@pytest.mark.asyncio
async def test_no_source_raises_price_unavailable():
    async def none_source():
        return None

    pf = PriceFeed(_cfg(), chainlink_reader=none_source, coinbase_fetcher=none_source)
    with pytest.raises(PriceUnavailable):
        await pf.eth_usd(now=1000.0)


@pytest.mark.asyncio
async def test_cache_within_ttl():
    calls = {"n": 0}

    async def chainlink():
        calls["n"] += 1
        return {"price": 3000.0 + calls["n"], "source": "chainlink"}

    async def coinbase():
        return None

    pf = PriceFeed(_cfg(), chainlink_reader=chainlink, coinbase_fetcher=coinbase)
    a = await pf.eth_usd(now=1000.0)
    b = await pf.eth_usd(now=1010.0)   # within 30s -> cached
    assert a["price"] == b["price"] and b["cached"] is True and calls["n"] == 1
    c = await pf.eth_usd(now=1040.0)   # past TTL -> refreshed
    assert calls["n"] == 2 and c["cached"] is False


@pytest.mark.asyncio
async def test_route_503_under_no_source(aiohttp_client, tmp_path):
    from tests.test_gateway import _build_mock_server
    cfg = {
        "platform": "0pnMatrx", "memory_dir": str(tmp_path / "m"),
        "workspace": str(tmp_path), "timezone": "UTC",
        "model": {"provider": "ollama", "providers": {}},
        "agents": {"neo": {"enabled": True}},
        "gateway": {"api_key": "", "rate_limit_rpm": 60, "rate_limit_burst": 10},
        "security": {}, "blockchain": {"chain_id": 84532},  # no rpc, no feed
    }
    server = _build_mock_server(cfg)
    server._app_attest = None
    server._security_backend = "noop"
    client = await aiohttp_client(server.create_app())
    r = await client.get("/api/v1/price/eth-usd")
    # No RPC/feed configured, so Chainlink is skipped. Honest outcomes only:
    #   • Coinbase fallback reachable -> 200 with a REAL sourced price (never faked)
    #   • no source reachable         -> 503
    assert r.status in (200, 503)
    if r.status == 200:
        body = await r.json()
        assert body["source"] in ("chainlink", "coinbase")
        assert float(body["price"]) > 0
        assert "sample" not in str(body).lower() and "demo" not in str(body).lower()
