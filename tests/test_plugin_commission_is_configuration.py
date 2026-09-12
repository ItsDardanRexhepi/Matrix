"""The plugin marketplace's revenue split is configuration, and a sale nobody
can complete does not come back with invented proceeds.

runtime/marketplace/plugin_store.py carried `PLATFORM_COMMISSION = 0.10` — the
same class 875e8ec removed from subscription tiers: a commercial number
hardcoded in the public repository. It was consumed in exactly one place, the
paid branch of `purchase()`, which answered 200 with `status: requires_iap`,
`platform_fee` = 10% of the listing price and `developer_revenue` = 90%, and
told the caller to "complete the purchase in the MTRX iOS app".

Nothing can complete that purchase. The App Store product table
(gateway/iap.py DEFAULT_PRODUCTS) has no plugin product, /api/v1/iap/verify
never writes plugin ownership, and `_record_purchase` is reached only from the
free branch. And a sale through Apple IAP pays the App Store's commission
before any platform split, so `developer_revenue` = 90% of the sticker price
was a number no developer could ever receive.

The properties, asserted on behaviour rather than on the constant's absence:
  * the rate reported is the configured one — a different configured rate comes
    back, and no configuration comes back as unknown, not as 10%;
  * a paid purchase is answered as not built (HTTP 501 at the route) and carries
    no proceeds figure;
  * a free plugin still installs.
"""

from __future__ import annotations

import pytest
from aiohttp import web
from aiohttp.test_utils import TestClient, TestServer

from runtime.marketplace.plugin_store import PluginListing, PluginMarketplace


async def _market(config: dict) -> tuple[PluginMarketplace, str, str]:
    market = PluginMarketplace(config=config)
    await market.initialize()
    paid = PluginListing(name="Paid", author="dev", price_usd=4.99, status="active")
    market.listings[paid.plugin_id] = paid
    free_id = next(pid for pid, l in market.listings.items() if l.price_usd <= 0)
    return market, paid.plugin_id, free_id


async def test_unconfigured_commission_is_unknown_not_a_hardcoded_rate():
    market, paid_id, _ = await _market({})
    result = await market.purchase("0xbuyer", paid_id)
    assert "platform_commission_rate" in result, result
    assert result["platform_commission_rate"] is None, result
    for invented in ("platform_fee", "developer_revenue"):
        assert invented not in result, f"{invented} reported for a sale that cannot happen"


async def test_configured_commission_is_the_rate_reported():
    market, paid_id, _ = await _market({"plugin_marketplace": {"commission_rate": 0.2}})
    result = await market.purchase("0xbuyer", paid_id)
    assert result.get("platform_commission_rate") == 0.2, result


@pytest.mark.parametrize("bad", ["ten percent", -0.1, 1.5, float("nan")])
async def test_malformed_commission_is_unknown_rather_than_guessed(bad):
    market, paid_id, _ = await _market({"plugin_marketplace": {"commission_rate": bad}})
    result = await market.purchase("0xbuyer", paid_id)
    assert "platform_commission_rate" in result, result
    assert result["platform_commission_rate"] is None, result


async def test_paid_purchase_is_answered_as_not_built():
    market, paid_id, _ = await _market({"plugin_marketplace": {"commission_rate": 0.1}})
    result = await market.purchase("0xbuyer", paid_id)
    assert result.get("status") == "not_built", result
    assert not await market.has_purchased("0xbuyer", paid_id)


async def test_free_plugin_still_installs():
    market, _, free_id = await _market({})
    result = await market.purchase("0xbuyer", free_id)
    # Free plugins are owned by everyone (has_purchased), so this is either
    # branch of "you have it" — never a refusal.
    assert result.get("status") in ("ok", "already_purchased"), result


async def test_route_returns_501_for_a_paid_purchase():
    from gateway.server import GatewayServer

    market, paid_id, free_id = await _market({})
    server = GatewayServer.__new__(GatewayServer)
    server.plugin_marketplace = market
    server._caller_identity = lambda request: "0xbuyer"

    app = web.Application()
    app.router.add_post("/marketplace/plugins/{plugin_id}/purchase",
                        server.handle_marketplace_purchase)
    async with TestClient(TestServer(app)) as client:
        paid = await client.post(f"/marketplace/plugins/{paid_id}/purchase")
        assert paid.status == 501, await paid.text()
        free = await client.post(f"/marketplace/plugins/{free_id}/purchase")
        assert free.status == 200, await free.text()
