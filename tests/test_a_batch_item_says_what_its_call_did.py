"""A batch item must say what its CALL did, not that it came back.

WHERE THE ENVELOPE FIX LANDS SHORT. ``runtime/protocols/outcome_truth.py`` reads
a tool's verdict out of the structure it returned, and the gateway's two response
envelopes were taught to state it: ``ServiceRoutes._ok`` and the capability
registry both put ``call_outcome`` in the body they answer with, and
``tests/test_refusal_survives_the_envelope.py`` pins that.

``POST /api/v1/batch`` is a THIRD envelope, built after those, and it hid exactly
what they stopped hiding. It takes the sub-route's body, puts it under ``body``
in a result of its own, and states its own verdict over it in the two fields a
consumer actually reads::

    {"id": ..., "status": <the sub-route's HTTP status>,
     "body": {...the payload, outcome and all...},
     "error": null}

``error: null`` for every item that produced a response — including a refusal —
and no outcome anywhere on the item. A DOMAIN refusal keeps its 200 on purpose
(``_ok`` is right that a rejected claim is a real answer the caller asked for,
and promoting it would break a working flow), so the HTTP status is a true
statement about the transport and says nothing about whether the thing happened.
200 was the only thing this envelope passed on.

It is not only relayed. It is COUNTED, PUBLISHED and ACTED ON:

  * ``success_count`` was ``sum(1 for r in results if 200 <= r["status"] < 300)``
    — a count of sub-calls that did not throw, published to every SSE subscriber
    as ``batch.completed`` and fed to the ``batch.item.success`` metric.
  * ``abort_on_failure`` tested the same status, so a refused item did not stop
    the items queued behind it and the rest of the plan ran on.
  * ``MTRXPackager.unpackBatchItem`` decodes on ``status >= 200 && < 300``, so
    the refusal reached the user as a decoded success — the single-call defect
    ``rejectIfEnvelopeReportsFailure`` closed one envelope further in.

NOT A STRING SNIFF (§NEW-27). Every assertion below is about named fields of
structures the platform itself emitted.
"""
from __future__ import annotations

import asyncio

from aiohttp.test_utils import TestClient, TestServer

from gateway.service_routes import ServiceRoutes
from runtime.protocols.outcome_truth import (
    FAILURE,
    OUTCOME_FIELD,
    SUCCESS,
    UNKNOWN,
    report_of,
)



class _ScriptedRegistry:
    """A registry whose services RETURN what they are told to.

    Returned, not raised: a raise is the case the batch already handled, and the
    kind of refusal this codebase actually produces is the kind it did not.
    """

    def __init__(self, by_method: dict):
        self.by_method = by_method
        self.called: list[str] = []

    def get(self, name: str):
        registry = self

        class _Svc:
            def __getattr__(self, method):
                async def _impl(**_kwargs):
                    registry.called.append(method)
                    return dict(registry.by_method[method])
                return _impl

        return _Svc()


#: A refusal that is a DOMAIN answer, so the sub-route correctly keeps its 200.
#: That is the whole case: the item's HTTP status is a true statement about the
#: transport and says nothing about whether the loan was made.
_REFUSED_LOAN = {"status": "rejected", "reason": "collateral below the minimum"}
_MADE_LOAN = {"loan_id": "loan_1", "tx_hash": "0xabc"}

_CREATE = {"id": "create", "method": "POST", "path": "/api/v1/defi/loan/create",
           "body": {"borrower": "0xabc", "collateral_token": "WETH",
                    "collateral_amount": 1, "borrow_token": "USDC",
                    "borrow_amount": 100}}
_REPAY = {"id": "repay", "method": "POST", "path": "/api/v1/defi/loan/repay",
          "body": {"loan_id": "loan_1", "amount": 100}}


async def _batch(by_method: dict, items: list, **options):
    from aiohttp import web as _web

    routes = ServiceRoutes(config={})
    routes._registry = _ScriptedRegistry(by_method)
    app = _web.Application()
    routes.register_routes(app)
    async with TestClient(TestServer(app)) as client:
        sub = await routes.broadcaster.register(types={"batch.completed"})
        resp = await client.post("/api/v1/batch",
                                 json={"requests": items, **options})
        assert resp.status == 200
        body = await resp.json()
        await asyncio.sleep(0)  # let the publish run
        event = await sub.queue.get()
        await routes.broadcaster.unregister(sub)
        return routes, body, event.payload


async def test_a_batch_item_states_the_outcome_of_the_call_it_ran():
    _routes, body, _evt = await _batch({"create_loan": _REFUSED_LOAN}, [_CREATE])
    item = body["results"][0]
    assert report_of(item["body"]) == FAILURE, (
        f"premise changed — the sub-route did not refuse: {item}")
    assert item["status"] == 200, (
        f"premise changed — this is the domain refusal that keeps its 200: {item}")
    assert item.get(OUTCOME_FIELD) == FAILURE, (
        "the batch item states no outcome, so every consumer is left with the "
        f"HTTP status of a call that did not happen: {sorted(item)}")


async def test_a_batch_does_not_count_a_refused_item_as_a_success():
    _routes, _body, payload = await _batch({"create_loan": _REFUSED_LOAN}, [_CREATE])
    assert payload["success_count"] == 0, (
        "the loan was refused and the platform published that one succeeded: "
        f"{payload}")
    assert payload.get("refused_count") == 1, (
        f"the published event does not say anything was refused: {payload}")


async def test_abort_on_failure_stops_at_a_refusal_that_kept_its_200():
    routes, body, _evt = await _batch(
        {"create_loan": _REFUSED_LOAN, "repay_loan": {"repaid": True}},
        [_CREATE, _REPAY], sequential=True, abort_on_failure=True)
    assert "repay_loan" not in routes._registry.called, (
        "the loan was refused and the repayment ran anyway — abort_on_failure "
        f"read the HTTP status, not what the call reported: {body['results']}")
    assert body["results"][1]["error"] == "aborted", body["results"]


async def test_a_batch_item_that_really_ran_is_still_a_success():
    """The scope pin, in all three places: an executed action keeps its 200,
    is counted, and does not abort what is queued behind it."""
    routes, body, payload = await _batch(
        {"create_loan": _MADE_LOAN, "repay_loan": {"repaid": True}},
        [_CREATE, _REPAY], sequential=True, abort_on_failure=True)
    assert [r["status"] for r in body["results"]] == [200, 200], body["results"]
    assert all(r.get(OUTCOME_FIELD) == SUCCESS for r in body["results"]), body["results"]
    assert payload["success_count"] == 2, payload
    assert routes._registry.called == ["create_loan", "repay_loan"]


async def test_abort_on_failure_also_stops_at_a_2xx_item_nobody_established():
    """THE WIDENING, PINNED WHERE IT IS DISCLOSED. Before items stated their
    call's verdict, a 200 carrying `recorded_unsettled` let the items behind it
    run. It stops them now, on purpose: a repayment must not be built on a loan
    nobody established. The comment at the abort once said this was not a
    widening; this test is what makes the sentence that replaced it checkable."""
    routes, body, payload = await _batch(
        {"create_loan": {"status": "recorded_unsettled", "settled": False},
         "repay_loan": {"repaid": True}},
        [_CREATE, _REPAY], sequential=True, abort_on_failure=True)
    first = body["results"][0]
    assert first["status"] == 200 and first.get(OUTCOME_FIELD) == UNKNOWN, (
        f"premise changed — this is a 2xx item with no established outcome: {first}")
    assert routes._registry.called == ["create_loan"], routes._registry.called
    assert body["results"][1]["error"] == "aborted", body["results"]


# ── the third answer, which is where most of the care goes ────────────────

async def test_an_item_that_timed_out_is_neither_counted_nor_called_a_refusal(
        monkeypatch):
    """A cancelled handler may already have signed, spent or written.

    A refusal is a CLAIM THAT NOTHING HAPPENED, and nothing here establishes
    that — so the item says `unknown`, the published count leaves it out of
    both totals, and `abort_on_failure` still stops (an item nobody has a
    verdict for is exactly the item a dependent call must not be built on).
    """
    from aiohttp import web as _web
    import gateway.service_routes as sr

    monkeypatch.setattr(sr, "BATCH_ITEM_TIMEOUT_SECONDS", 0.01)

    class _Hangs:
        called: list[str] = []

        def get(self, _name: str):
            class _Svc:
                def __getattr__(self, method):
                    async def _impl(**_kwargs):
                        _Hangs.called.append(method)
                        await asyncio.sleep(5)
                    return _impl
            return _Svc()

    routes = ServiceRoutes(config={})
    routes._registry = _Hangs()
    app = _web.Application()
    routes.register_routes(app)
    async with TestClient(TestServer(app)) as client:
        sub = await routes.broadcaster.register(types={"batch.completed"})
        resp = await client.post("/api/v1/batch", json={
            "requests": [_CREATE, _REPAY],
            "sequential": True, "abort_on_failure": True,
        })
        body = await resp.json()
        await asyncio.sleep(0)
        payload = (await sub.queue.get()).payload
        await routes.broadcaster.unregister(sub)

    timed_out = body["results"][0]
    assert timed_out["status"] == 504, f"premise changed: {timed_out}"
    assert timed_out[OUTCOME_FIELD] == UNKNOWN, (
        "a handler cancelled mid-flight was recorded as a settled fact: "
        f"{timed_out}")
    assert payload["success_count"] == 0, payload
    # The one refusal is the ABORTED repayment, which genuinely never ran —
    # that fact IS established. The timed-out item is in neither total, which
    # is the whole distinction: `item_count - success - refused` is the number
    # of calls nobody has a verdict for, and publishing it as anything else
    # asserts a fact this surface does not have.
    assert payload["refused_count"] == 1, payload
    assert payload["item_count"] - payload["success_count"] - payload["refused_count"] == 1, (
        "the timed-out item was filed under a verdict nothing established: "
        f"{payload}")
    aborted = body["results"][1]
    assert aborted["error"] == "aborted" and aborted[OUTCOME_FIELD] == FAILURE, aborted
    assert "repay_loan" not in _Hangs.called, body["results"]


def test_an_error_the_gateway_decided_itself_is_a_refusal_and_a_timeout_is_not():
    """Read at the source, because the dispatch paths are not its only callers."""
    assert ServiceRoutes._outcome_for_error_status(400) == FAILURE
    assert ServiceRoutes._outcome_for_error_status(501) == FAILURE
    assert ServiceRoutes._outcome_for_error_status(503) == FAILURE
    assert ServiceRoutes._outcome_for_error_status(504) == UNKNOWN


def test_a_non_2xx_with_nothing_to_read_is_a_refusal_not_the_measured_default():
    """`report_of` reads a silent payload as SUCCESS — measured over payloads
    this tree RETURNS, which says nothing about a status it RAISED. An item with
    no body must not inherit that default."""
    assert ServiceRoutes._item_outcome(404, None) == FAILURE
    assert ServiceRoutes._item_outcome(500, {"error": "internal error"}) == FAILURE
    # …and a non-2xx whose body states the outcome keeps what it stated.
    assert ServiceRoutes._item_outcome(
        503, {"status": "refused", OUTCOME_FIELD: FAILURE}) == FAILURE
    # A 2xx is read from the payload, which is the whole point of the field.
    assert ServiceRoutes._item_outcome(
        200, {"status": "ok", OUTCOME_FIELD: FAILURE,
              "data": {"status": "rejected"}}) == FAILURE
    assert ServiceRoutes._item_outcome(
        200, {"status": "ok", OUTCOME_FIELD: SUCCESS, "data": {"id": 1}}) == SUCCESS
