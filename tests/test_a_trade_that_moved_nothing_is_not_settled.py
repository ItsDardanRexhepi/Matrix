"""A trade that moved nothing is not attested as settled or announced as done.

attest-money F19. `GamingService.trade_item` wrote one in-memory dict keyed by
the TRADE — the item's owner never changed, no payment was taken — and returned
`{"status": "completed", "price": ...}`. The dispatcher read "completed" as a
real outcome, EAS-attested the trade as settled and published it to the public
feed at its price. Measured before the fix: `_record_verdict(result) ==
"settled"`, `_attest_action` called with ("game_item_trade", "gaming"), and
the feed ingested value_usd=12.5.

The same audit had already fixed `attest_achievement`, in the same service and
the same class, with the RECORDED_UNSETTLED idiom. This closes the rest of that
class — a local record of value changing hands that claims it changed hands:

    gaming.trade_item                    "completed" + price
    gaming.enter_tournament              "entered"   + entry_fee
    gaming.place_prediction_bet          "placed"    + amount
    agent_identity.trade_model_access    "traded"    + price
    agent_identity.sell_training_data    "sold"      + price
    marketplace.buy_item                 no status   + price, fee, proceeds

Each is now `recorded_unsettled` with `settled: False` and `value_moved: False`,
so the dispatcher files it through the refusal path the RECORDED_UNSETTLED
idiom already takes (attest_achievement's path), and the feed announces
nothing.

NAMED, NOT CLOSED HERE — the same claim in other services, left for their own
pass because each needs its own adjudication: fundraising's
buy_carbon_credit / buy_renewable_cert / invest_green_bond, and
ip_royalties.RoyaltyDistribution.claim (all four in
tests/test_uuid_mint_fabrication_shape.py's inventory). A different axis in a
sibling method: agent_identity.verify_inference answers `verified` and
`valid: True` without checking anything.
"""

from __future__ import annotations

import asyncio
import json

import pytest

from runtime.blockchain.services.service_dispatcher import (
    RECORD_SETTLED,
    ServiceDispatcher,
    _record_verdict,
)


class _SpyFeed:
    def __init__(self) -> None:
        self.published: list[dict] = []

    async def ingest(self, **kwargs):  # noqa: D401 - test double
        self.published.append(kwargs)


@pytest.fixture
def spied():
    d = ServiceDispatcher({})
    feed = _SpyFeed()
    d._feed_engine = feed
    attested: list[str] = []
    declined: list[str] = []

    async def _spy_attest(action, *_a, **_k):
        attested.append(action)

    async def _spy_refusal(action, *_a, **_k):
        declined.append(action)

    async def _spy_broadcast(action, *_a, **_k):
        raise AssertionError(f"{action} was filed as a broadcast; nothing was sent")

    d._attest_action = _spy_attest
    d._attest_refusal = _spy_refusal
    d._record_broadcast = _spy_broadcast
    return d, feed, attested, declined


_TRADES = [
    ("game_item_trade", {"asset_id": "asset_1", "seller": "0xS", "buyer": "0xB",
                         "price": 12.5}),
    ("tournament_enter", {"game_id": "g1", "player": "0xP", "entry_fee": 5.0}),
    ("market_bet", {"market_id": "m1", "bettor": "0xB", "option": "yes",
                    "amount": 40.0}),
    ("ai_model_trade", {"seller": "0xS", "buyer": "0xB", "model_id": "m1",
                        "price": 99.0}),
    ("training_data_sell", {"seller": "0xS", "buyer": "0xB", "dataset_id": "d1",
                            "price": 250.0}),
]


@pytest.mark.parametrize("action,params", _TRADES, ids=[a for a, _ in _TRADES])
async def test_a_recorded_trade_is_not_attested_or_published(spied, action, params):
    """DEFECT-PROVER, per method, through `execute`."""
    d, feed, attested, declined = spied

    envelope = json.loads(await d.execute(action, params=params, caller_identity="0xB"))
    await asyncio.sleep(0)

    result = envelope["result"]
    assert result["settled"] is False and result["value_moved"] is False, result
    assert _record_verdict(result) != RECORD_SETTLED
    assert attested == [], f"{action} was EAS-attested as settled"
    assert feed.published == [], f"{action} was announced on the public feed"
    assert declined == [action], "the record must still be recorded, as unsettled"


async def test_a_marketplace_purchase_is_not_attested_or_published(spied):
    """DEFECT-PROVER. The purchase returned no status at all, which is the
    plain-success shape, and was attested and announced at its price."""
    d, feed, attested, declined = spied
    listed = json.loads(await d.execute("list_marketplace", params={
        "seller": "0xS", "item_type": "digital",
        "metadata": {"title": "a thing"}, "price": 30.0,
    }, caller_identity="0xS"))
    listing_id = listed["result"]["listing_id"]
    await asyncio.sleep(0)  # let the listing's own publish land before clearing
    attested.clear()
    feed.published.clear()

    envelope = json.loads(await d.execute("buy_marketplace", params={
        "listing_id": listing_id, "buyer": "0xB",
    }, caller_identity="0xB"))
    await asyncio.sleep(0)

    sale = envelope["result"]
    assert sale["settled"] is False and sale["value_moved"] is False, sale
    assert "completed_at" not in sale, "a sale that did not settle has no completion time"
    assert attested == [] and feed.published == []
    assert declined == ["buy_marketplace"]


async def test_the_record_keeps_what_was_agreed():
    """SCOPE PIN. The fix is the claim, not the record: the parties and the
    figure are still written down, so nothing a later settlement needs is
    lost."""
    from runtime.blockchain.services.gaming.service import GamingService

    trade = await GamingService({}).trade_item("asset_1", "0xS", "0xB", 12.5)
    assert (trade["asset_id"], trade["seller"], trade["buyer"], trade["price"]) == (
        "asset_1", "0xS", "0xB", 12.5)
    assert trade["status"] == "recorded_unsettled"
    assert trade["disclosure"]


async def test_a_listing_is_still_a_real_outcome():
    """SCOPE PIN. Listing an item is a genuine record — the listing IS the
    artifact — so it is still attested and published; it just carries no
    dollar figure, because an asking price is not a payment
    (tests/test_the_feed_value_is_what_moved.py)."""
    d = ServiceDispatcher({})
    feed = _SpyFeed()
    d._feed_engine = feed
    attested: list[str] = []

    async def _spy_attest(action, *_a, **_k):
        attested.append(action)

    d._attest_action = _spy_attest
    await d.execute("list_marketplace", params={
        "seller": "0xS", "item_type": "digital",
        "metadata": {"title": "a thing"}, "price": 30.0,
    }, caller_identity="0xS")
    await asyncio.sleep(0)

    assert attested == ["list_marketplace"]
    assert [e["value_usd"] for e in feed.published] == [None]
