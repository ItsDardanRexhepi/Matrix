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
never writes plugin ownership, and the only purchase recorder was reached only
from a free branch that could not run (it has since been removed). And a sale through Apple IAP pays the App Store's commission
before any platform split, so `developer_revenue` = 90% of the sticker price
was a number no developer could ever receive.

The properties, asserted on behaviour rather than on the constant's absence:
  * the rate reported is the configured one — a different configured rate comes
    back, and no configuration comes back as unknown, not as 10%;
  * a paid purchase is answered as not built (HTTP 501 at the route) and carries
    no proceeds figure;
  * a free listing is answered as already owned, and nothing is recorded or
    installed (tests/test_plugin_marketplace_installs_nothing.py);
  * a boolean is not a rate (`float(True)` is 1.0, which would have reported a
    100% commission from `"commission_rate": true`);
  * no tracked text states a plugin commission as a number of its own. The
    30% in runtime/marketplace/__init__.py survived the first fix one file over
    from the constant, because the first control looked at the constant, not
    at what the package says. A sentence that names a percentage next to
    "commission" and "plugin" must attribute it to the published Terms; legal
    copy itself is not scanned (it is the source being cited).
"""

from __future__ import annotations

import re
import subprocess
from pathlib import Path

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


@pytest.mark.parametrize("bad", ["ten percent", -0.1, 1.5, float("nan"), True, False])
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


async def test_free_listing_is_answered_as_owned_not_refused():
    market, _, free_id = await _market({})
    result = await market.purchase("0xbuyer", free_id)
    # Free listings are owned by everyone (has_purchased): never a refusal, and
    # never a claim that anything was installed.
    assert result.get("status") == "already_purchased", result
    assert result.get("installed") is False, result


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


ROOT = Path(__file__).resolve().parent.parent
_LEGAL_COPY = {"web/terms.html", "web/privacy.html"}
_PERCENT = re.compile(r"\b\d+(?:\.\d+)?\s*(?:%|percent\b)", re.I)


def _plugin_commission_sentences(text: str, in_marketplace_package: bool) -> list[str]:
    text = re.sub(r"<[^>]+>", " ", text)
    # blank lines and table rows end a sentence; other line breaks do not
    blocks = re.split(r"\n\s*\n|\n(?=\s*\|)", text)
    sentences = [s for block in blocks
                 for s in re.split(r"(?<=[.!?])\s+", re.sub(r"\s+", " ", block))]
    out = []
    for sentence in sentences:
        low = sentence.lower()
        if "commission" not in low or not _PERCENT.search(sentence):
            continue
        if not (in_marketplace_package or "plugin" in low):
            continue
        if "terms" in low:
            continue  # attributed to the published Terms, which are the source
        out.append(sentence.strip()[:160])
    return out


def test_the_commission_sentence_scan_is_not_vacuous():
    assert _plugin_commission_sentences(
        "Developers sell plugins. The platform takes a 30%\n commission on paid plugins.", True)
    assert _plugin_commission_sentences("A 10 percent commission on plugin sales.", False)
    assert not _plugin_commission_sentences(
        "The published Terms state a 10% commission on paid plugins.", False)
    assert not _plugin_commission_sentences("Staking takes a 5% commission on rewards.", False)


def test_no_tracked_text_hardcodes_a_plugin_commission_rate():
    this_file = Path(__file__).resolve()
    out = subprocess.check_output(["git", "ls-files"], cwd=ROOT, text=True)
    offenders = []
    for rel in out.splitlines():
        path = ROOT / rel
        if rel in _LEGAL_COPY or not path.is_file() or path.resolve() == this_file:
            continue
        try:
            text = path.read_text(encoding="utf-8")
        except (UnicodeDecodeError, OSError):
            continue
        for sentence in _plugin_commission_sentences(text, rel.startswith("runtime/marketplace/")):
            offenders.append(f"{rel}: {sentence}")
    assert not offenders, (
        "a plugin commission rate stated as a number of the repository's own "
        "(the rate is plugin_marketplace.commission_rate):\n" + "\n".join(offenders))
