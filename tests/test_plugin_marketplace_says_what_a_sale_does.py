"""What the plugin marketplace says about a sale is what purchase() does.

The package said the platform takes a 30% commission while the constant it
quotes with, PLATFORM_COMMISSION, is 10%. The store said it processed payment
through Stripe and created a checkout session; it imports no payment library
and answers a paid purchase with `requires_iap` and nothing more. A comment
told clients to call `record_purchase` with the verified transaction; the
store has no such method and no route records a paid purchase. The answer
itself sent the buyer elsewhere to "complete the purchase". The README said
developers keep 90% of revenue, although no paid sale completes and nothing
pays a developer.

Whether paid plugins are sold, and on what split, is the owner's decision.
These tests only hold the words to the code: when a paid sale can complete,
the statements have to change with it.
"""
from __future__ import annotations

import asyncio
import pathlib
import re

REPO = pathlib.Path(__file__).resolve().parent.parent
PACKAGE = REPO / "runtime" / "marketplace"


def _package_text() -> str:
    return "\n".join(p.read_text() for p in sorted(PACKAGE.glob("*.py")))


def _readme_plugin_section() -> str:
    text = (REPO / "README.md").read_text()
    start = text.index("## Plugin Development")
    end = text.index("\n---", start)
    return " ".join(text[start:end].split())


def _paid_purchase():
    from runtime.marketplace.plugin_store import PluginMarketplace

    async def run():
        store = PluginMarketplace()
        await store.initialize()
        submitted = await store.submit_listing(
            "0x" + "ab" * 20, {"name": "Paid", "price_usd": 10.0})
        pid = submitted["plugin_id"]
        answer = await store.purchase("0x" + "cd" * 20, pid)
        owned = await store.has_purchased("0x" + "cd" * 20, pid)
        return store, answer, owned

    return asyncio.run(run())


def _a_paid_sale_completes() -> bool:
    store, answer, owned = _paid_purchase()
    return owned or answer.get("status") not in ("requires_iap",) or hasattr(
        store, "record_purchase")


def test_the_store_does_not_claim_a_payment_path_it_lacks():
    answer = _paid_purchase()[1]
    if _a_paid_sale_completes():
        assert "cannot be bought" not in answer["message"], (
            "a paid sale now completes, and its answer still says it cannot")
        return
    text = _package_text()
    prose = text.replace("stripe_session", "")
    assert "stripe" not in prose.lower(), (
        "runtime/marketplace names Stripe, and nothing there takes a payment")
    assert not re.search(r"(?<!_)record_purchase`", text), (
        "runtime/marketplace tells clients to call record_purchase, "
        "which the store does not have")
    assert "checkout session" not in text.lower()
    assert "complete the purchase" not in answer["message"].lower(), (
        "a paid purchase answers that it can be completed elsewhere, "
        "and nothing records it")


def test_every_commission_stated_is_the_constant():
    from runtime.marketplace.plugin_store import PLATFORM_COMMISSION

    platform = round(PLATFORM_COMMISSION * 100)
    stated = re.findall(r"(\d+)%\s+commission", _package_text())
    assert all(int(n) == platform for n in stated), (
        f"runtime/marketplace states a commission of {stated}%; "
        f"PLATFORM_COMMISSION is {platform}%")

    section = _readme_plugin_section()
    for dev, plat in re.findall(r"(\d+)/(\d+) split", section):
        assert (int(dev), int(plat)) == (100 - platform, platform), (
            f"the README quotes a {dev}/{plat} split; the store quotes "
            f"{100 - platform}/{platform}")


def test_the_readme_does_not_sell_what_cannot_be_bought():
    section = _readme_plugin_section()
    completes = _a_paid_sale_completes()
    says_unbuyable = "cannot be bought" in section
    assert says_unbuyable != completes, (
        "a paid plugin can now be bought, and the README says it cannot"
        if completes else
        "no paid sale completes, and the README does not say so")
    if not completes:
        assert "keep 90% of revenue" not in section, (
            "the README says developers keep 90% of revenue; no paid sale completes")
