"""The public feed announces the figure an action MOVED, or none.

attest-money F12/F14. `_feed_value_of` stopped reading the request body and
started reading the result — and then read the wrong thing out of it. `price`
was one of its value keys, so a subscription announced the plan's list price
as its value, and so did the cancellation, on a record that says in two fields
that nothing was charged (`total_paid: 0.0`, `charges_settled: False`).
Measured through `execute` before the fix: subscribe -> value_usd 30.0,
cancel_subscription -> value_usd 30.0, create_subscription_plan -> 30.0.

Every test here goes through `ServiceDispatcher.execute` with a spy feed, so it
observes the value the feed actually receives. A pure-helper test would pass
while the ingest block read something else — which is exactly the gap the
earlier "DEFECT-PROVER" for this block had: it called the helper and never
supplied a request.

SIBLING AXES, named so the next reader does not have to rediscover them:
  * `price` as a value key — closed here (subscriptions, marketplace listing and
    purchase, agent-identity trades, NFT rental, the plan itself);
  * a record's own disclosure (`charges_settled: False`, `value_moved` not
    True) outranking a figure in the same record — closed here;
  * WHETHER a record that moved nothing is attested at all is the dispatcher's
    `_record_verdict`, not this helper — see
    tests/test_a_trade_that_moved_nothing_is_not_settled.py.
"""

from __future__ import annotations

import asyncio

import pytest

from runtime.blockchain.services.service_dispatcher import (
    ServiceDispatcher,
    _feed_value_of,
)


class _SpyFeed:
    def __init__(self) -> None:
        self.published: list[dict] = []

    async def ingest(self, **kwargs):  # noqa: D401 - test double
        self.published.append(kwargs)


def _dispatcher():
    d = ServiceDispatcher({})
    feed = _SpyFeed()
    d._feed_engine = feed

    async def _noop(*_a, **_k):
        return None

    # The EAS writers are not under test here; the feed is.
    d._attest_action = _noop
    d._attest_refusal = _noop
    d._record_broadcast = _noop
    return d, feed


async def _run(d, action, params):
    raw = await d.execute(action, params=params, caller_identity="0xA")
    await asyncio.sleep(0)  # the feed publish is a scheduled task
    return raw


def _value_for(feed, action):
    events = [e for e in feed.published if e["action"] == action]
    assert len(events) == 1, (action, feed.published)
    return events[0]["value_usd"]


async def _plan(d):
    await _run(d, "create_subscription_plan", {
        "provider": "0xP", "name": "Pro", "price": 30.0,
        "interval": "monthly", "rewards": {},
    })
    svc = d._get_registry().get("subscriptions")
    return next(iter(svc._plans.values()))


async def test_a_subscription_nobody_was_charged_for_announces_no_value():
    """DEFECT-PROVER. The record is a real, active subscription, so it IS
    published — but it says nothing was charged, and the feed said $30."""
    d, feed = _dispatcher()
    plan = await _plan(d)

    await _run(d, "subscribe", {
        "user": "0xA", "plan_id": plan["plan_id"], "payment_token": "tok-1",
    })

    svc = d._get_registry().get("subscriptions")
    sub = next(iter(svc._subscriptions.values()))
    assert sub["total_paid"] == 0.0 and sub["charges_settled"] is False
    assert _value_for(feed, "subscribe") is None, (
        "the feed announced the plan's list price as the value of a "
        "subscription whose record says nothing was charged"
    )


async def test_a_cancellation_announces_no_value():
    """DEFECT-PROVER. Cancelling moves no money whatever was charged before;
    the feed said $30 for this too."""
    d, feed = _dispatcher()
    plan = await _plan(d)
    await _run(d, "subscribe", {
        "user": "0xA", "plan_id": plan["plan_id"], "payment_token": "tok-1",
    })
    svc = d._get_registry().get("subscriptions")
    sub_id = next(iter(svc._subscriptions))

    await _run(d, "cancel_subscription", {"subscription_id": sub_id, "user": "0xA"})

    assert _value_for(feed, "cancel_subscription") is None


async def test_a_cancellation_after_a_settled_charge_still_announces_no_value():
    """The disclosure flag alone would not close this: once a renewal settles,
    `charges_settled` is True and the cancellation's record still carries the
    list price. The value key itself had to go."""
    d, feed = _dispatcher()
    plan = await _plan(d)
    await _run(d, "subscribe", {
        "user": "0xA", "plan_id": plan["plan_id"], "payment_token": "tok-1",
    })
    svc = d._get_registry().get("subscriptions")
    sub_id, sub = next(iter(svc._subscriptions.items()))
    sub["charges_settled"] = True
    sub["total_paid"] = 30.0

    await _run(d, "cancel_subscription", {"subscription_id": sub_id, "user": "0xA"})

    assert _value_for(feed, "cancel_subscription") is None


async def test_creating_a_plan_announces_no_value():
    """A plan's price is what it WILL charge. Creating it moves nothing."""
    d, feed = _dispatcher()
    await _plan(d)
    assert _value_for(feed, "create_subscription_plan") is None


class _Registry:
    def __init__(self, services: dict) -> None:
        self._services = services

    def get(self, name):
        return self._services[name]


class _Service:
    def __init__(self, result: dict) -> None:
        self._result = result

    async def subscribe(self, **_params):
        return dict(self._result)


async def test_the_value_comes_from_the_result_even_when_the_request_names_another():
    """The request says 999; the service acted on 5. Driven through `execute`
    with a request that names its own figure, so a block that read `params`
    fails here."""
    d, feed = _dispatcher()
    d._registry = _Registry({"subscriptions": _Service({"amount": 5.0})})

    await _run(d, "subscribe", {"amount": 999.0, "value_usd": 999.0})

    assert _value_for(feed, "subscribe") == 5.0


@pytest.mark.parametrize("label,result", [
    ("charges_settled False", {"amount": 30.0, "charges_settled": False}),
    ("value_moved None (the question does not arise)", {"amount": 30.0, "value_moved": None}),
    ("value_moved False", {"amount": 30.0, "value_moved": False}),
    ("settled False", {"amount": 30.0, "settled": False}),
    ("only a price", {"status": "active", "price": 30.0}),
])
def test_a_record_that_says_nothing_moved_carries_no_figure(label, result):
    assert _feed_value_of(result) is None, label


@pytest.mark.parametrize("label,result,expected", [
    ("a plain amount", {"amount": 5.0}, 5.0),
    ("value_moved True", {"amount": 5.0, "value_moved": True}, 5.0),
    ("settled, with value_usd", {"value_usd": 7.5, "settled": True, "value_moved": True}, 7.5),
    ("charges settled", {"total": 12.0, "charges_settled": True}, 12.0),
])
def test_a_figure_that_moved_is_still_published(label, result, expected):
    """SCOPE PIN. A feed that never names a figure is the mirror-image
    defect."""
    assert _feed_value_of(result) == expected, label
