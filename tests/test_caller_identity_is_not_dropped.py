"""17-D — the caller's identity was KNOWN and then DISCARDED before the
service decided, and before the record said what happened.

THE SHAPE OF THE DEFECT. `gateway/bridge.py` reads the session's linked wallet
and binds it into the security context::

    linked = self._linked_wallets.get(session_id) or {}
    bind_request_security(identity=linked.get("address", ""), ...)

and then called `dispatcher.execute(action, params)` with no identity at all.
The wallet existed one frame above the dispatcher. It was thrown away there.

The same dropped identity surfaced on two different surfaces, and a fix that
lands one and not the other still leaves the platform unable to answer "who":

  AUTHORITY  — `RightsManagement.set_rights` grants `commercial` /
    `derivative` / `physical` rights and stored the grant with no record of
    who asked for it.
  EVIDENCE   — `service_dispatcher.py` computed
        _actor = params.get("wallet") or params.get("address") or ""
    and `set_nft_rights` carries neither key, so every rights grant was
    attested and published to a PUBLIC feed with actor "". The record said a
    right moved and could not say who moved it.

WHAT IS DELIBERATELY NOT TESTED HERE: an OWNERSHIP check. This platform holds
no ownership record — `NFTFactory._collections` has one declaration, two reads
and ZERO writers — so a check would have to invent its own truth. Nothing below
asserts that `set_rights` refuses anybody. It asserts the platform now KNOWS
and RECORDS who called, which is the input an ownership check would need and
the answer the audit trail owes regardless.


CLASSIFICATION — every test in this file, MEASURED, not assumed.
================================================================
Method: save the 17-D change as a patch, `git apply --reverse` it, run this
file against the unfixed tree, restore the patch (verified byte-for-byte), run
again. Measured result: 16 failed / 7 passed before, 23 passed after.

Re-measured the same way for the SECOND gateway entry point (group 3 below),
against the tree that already had the bridge half: 3 failed / 24 passed
before that half landed, 27 passed after.

An earlier draft of this docstring guessed the split and got five of them
wrong, all in the same direction — tests asserted to be scope pins that in fact
fail before, because they name a parameter or a record field the unfixed code
does not have. The list below is the measurement, not the intention.

DEFECT-PROVERS — FAIL before the change, PASS after (16)
  Group 1: the defect itself — the identity is dropped.
    test_identity_reaches_the_service_and_is_recorded
    test_each_right_records_who_granted_it
    test_the_stored_record_not_just_the_response_carries_the_grantor
    test_the_grantor_is_readable_back_through_check_rights
    test_feed_actor_is_the_caller_not_empty_string
    test_attestation_payload_names_the_actor
    test_attestation_and_feed_agree_on_the_actor
    test_gateway_passes_the_wallet_it_already_bound
    test_gateway_action_with_params_reaches_its_service
    test_service_records_unknown_rather_than_fabricating_a_caller

  Group 2: ratchets on the mechanism this change introduces. Their INTENT is
  to pin scope, but they are honestly counted here because they fail before —
  they reference `caller_identity` / `set_by`, which did not exist. What they
  guard is future drift, not the original defect.
    test_params_caller_identity_is_overwritten_when_nothing_is_threaded
    test_params_caller_identity_cannot_override_a_threaded_identity
    test_action_whose_method_does_not_declare_identity_is_unaffected
    test_no_ownership_check_was_invented
    test_identity_parameter_stays_optional[RightsManagement.set_rights]
    test_identity_parameter_stays_optional[ServiceDispatcher.execute]

  Group 3: the SECOND gateway entry point, found by adversarial review after
  the first pass. `POST /api/v1/capabilities/{id}/invoke` reaches the same
  dispatcher and the same `set_nft_rights`, with the identity bound by
  `_security_context_middleware` and never asked for. Measured against the
  tree that had only the bridge half: these three failed, `set_by` was "".
    test_capability_route_passes_the_identity_the_middleware_bound
    test_capability_route_records_the_grantor_end_to_end
    test_capability_invoke_identity_stays_optional

SCOPE-PINS — PASS before AND after (8)
    test_capability_registry_overwrites_a_params_caller_identity  (renamed from test_capability_route_body_cannot_assert_an_identity;
      the route's body CAN assert an identity, see that test's docstring)
    test_gateway_with_no_linked_wallet_still_dispatches
    test_dispatch_without_identity_still_works_and_degrades_honestly
    test_positional_call_site_still_works
    test_keyword_call_site_still_works
    test_direct_service_call_without_identity_still_works
    test_non_declaring_method_still_works_without_the_kwarg
    test_collections_store_still_has_no_writers

The scope pins exist because the cheap version of this fix — make the platform
refuse anything without a wallet, or inject the parameter into every service
method — would "close" the finding by breaking ~219 actions and this package's
own `NFTService.mint`, which writes the default rights grant with no caller at
all. Degrading to `set_by: ""` (honest "unknown") is the required behaviour,
not a shortcoming.
"""

from __future__ import annotations

import asyncio
import inspect
import json

import pytest

from runtime.blockchain.services.nft_services.rights import RightsManagement
from runtime.blockchain.services.service_dispatcher import ServiceDispatcher

CALLER = "0xCAllerWallet00000000000000000000000000001"
OTHER = "0xSomebodyElse000000000000000000000000000002"

_RIGHTS = {"commercial": {"granted": True, "holder": "0xHolder"}}


def _params(token_id: int = 1, **extra) -> dict:
    p = {
        "collection": "0xCollection",
        "token_id": token_id,
        "rights": {k: dict(v) for k, v in _RIGHTS.items()},
    }
    p.update(extra)
    return p


class _CapturingFeed:
    """Stand-in for SocialFeedEngine — records what the feed was told."""

    def __init__(self) -> None:
        self.events: list[dict] = []

    async def ingest(self, **kwargs):
        self.events.append(kwargs)
        return None


class _CapturingAttestation:
    """Records the attestation payload instead of hitting a chain."""

    def __init__(self) -> None:
        self.calls: list[dict] = []

    async def attest(self, **kwargs):
        self.calls.append(kwargs)
        return {"status": "attested"}


def _dispatcher_with_recorders():
    """A dispatcher whose feed and attestation surfaces are observable.

    The attestation service is replaced on the *instance* the dispatcher will
    resolve, so `_attest_action` reaches the recorder through its real lookup
    path rather than through a patched helper — the point of these tests is
    that the identity survives the real call chain.
    """
    dispatcher = ServiceDispatcher({})
    feed = _CapturingFeed()
    dispatcher._feed_engine = feed

    attestation = _CapturingAttestation()
    registry = dispatcher._get_registry()
    registry.get("attestation").attest = attestation.attest

    return dispatcher, feed, attestation


async def _drain():
    """Let the fire-and-forget feed task run.

    The dispatcher publishes with `asyncio.create_task`, so the ingest call has
    not happened yet when `execute` returns.
    """
    for _ in range(5):
        await asyncio.sleep(0)
    pending = [t for t in asyncio.all_tasks() if t is not asyncio.current_task()]
    if pending:
        await asyncio.wait(pending, timeout=2)


# ─────────────────────────────────────────────────────────────────────────
# AUTHORITY SURFACE — the identity reaches the service and is recorded
# ─────────────────────────────────────────────────────────────────────────


async def test_identity_reaches_the_service_and_is_recorded():
    """DEFECT-PROVER. The identity the entry point threads (on the bridge, the
    wallet linked to the SIWE session) must arrive at the service that decides,
    and the service must write it down."""
    dispatcher = ServiceDispatcher({})

    envelope = json.loads(
        await dispatcher.execute(
            "set_nft_rights", params=_params(), caller_identity=CALLER
        )
    )

    assert envelope["status"] == "ok", envelope
    assert envelope["result"]["set_by"] == CALLER, (
        "the rights grant does not record the threaded caller identity — the "
        "platform's own record still cannot say who granted the right"
    )


async def test_each_right_records_who_granted_it():
    """DEFECT-PROVER. Attribution belongs on each right, not only on the
    record: a later call touching one right type must not silently reassign
    authorship of the others."""
    dispatcher = ServiceDispatcher({})

    first = json.loads(
        await dispatcher.execute(
            "set_nft_rights",
            params=_params(token_id=11),
            caller_identity=CALLER,
        )
    )
    assert first["result"]["rights"]["commercial"]["set_by"] == CALLER

    second = json.loads(
        await dispatcher.execute(
            "set_nft_rights",
            params={
                "collection": "0xCollection",
                "token_id": 11,
                "rights": {"derivative": {"granted": True, "holder": "0xHolder"}},
            },
            caller_identity=OTHER,
        )
    )
    rights = second["result"]["rights"]
    assert rights["derivative"]["set_by"] == OTHER
    assert rights["commercial"]["set_by"] == CALLER, (
        "a second caller's grant rewrote the attribution of a right it never "
        "touched"
    )


async def test_the_stored_record_not_just_the_response_carries_the_grantor():
    """DEFECT-PROVER. A response the caller could have written themselves is
    not a record. The persisted store must carry it."""
    service = RightsManagement({})

    await service.set_rights(
        collection="0xCollection",
        token_id=7,
        rights={k: dict(v) for k, v in _RIGHTS.items()},
        caller_identity=CALLER,
    )

    stored = service._rights["0xCollection:7"]
    assert stored["set_by"] == CALLER
    assert stored["rights"]["commercial"]["set_by"] == CALLER


async def test_the_grantor_is_readable_back_through_check_rights():
    """DEFECT-PROVER. Written-and-unreadable is only half a record — the
    attribution must survive a read."""
    dispatcher = ServiceDispatcher({})

    await dispatcher.execute(
        "set_nft_rights", params=_params(token_id=21), caller_identity=CALLER
    )
    readback = json.loads(
        await dispatcher.execute(
            "check_nft_rights",
            params={
                "collection": "0xCollection",
                "token_id": 21,
                "right_type": "commercial",
            },
        )
    )

    assert readback["result"]["set_by"] == CALLER


# ─────────────────────────────────────────────────────────────────────────
# EVIDENCE SURFACE — the actor in the feed and the attestation
# ─────────────────────────────────────────────────────────────────────────


async def test_feed_actor_is_the_caller_not_empty_string():
    """DEFECT-PROVER. `set_nft_rights` params carry neither `wallet` nor
    `address`, so the public feed announced the grant with actor ""."""
    dispatcher, feed, _ = _dispatcher_with_recorders()

    await dispatcher.execute(
        "set_nft_rights", params=_params(token_id=31), caller_identity=CALLER
    )
    await _drain()

    assert feed.events, "the rights grant was never published to the feed"
    assert feed.events[0]["actor"] == CALLER, (
        f"feed announced the grant as actor {feed.events[0]['actor']!r} — a "
        "public record that a right moved, with no one attached to it"
    )


async def test_attestation_payload_names_the_actor():
    """DEFECT-PROVER. The attestation recorded action, service, a params hash
    and a timestamp — everything except who. A hash is not a name."""
    dispatcher, _, attestation = _dispatcher_with_recorders()

    await dispatcher.execute(
        "set_nft_rights", params=_params(token_id=32), caller_identity=CALLER
    )
    await _drain()

    assert attestation.calls, "the rights grant was never attested"
    payload = attestation.calls[0]["data"]
    assert payload.get("actor") == CALLER, (
        f"attestation payload actor is {payload.get('actor')!r} — the audit "
        "record asserts a right was granted and cannot name the grantor"
    )


async def test_attestation_and_feed_agree_on_the_actor():
    """DEFECT-PROVER — the anti-half-fix pin.

    Attributing the public feed while leaving the audit record anonymous (or
    the reverse) is the exact half-fix this standard forbids. Both surfaces
    are derived from one value; this fails if they ever diverge.
    """
    dispatcher, feed, attestation = _dispatcher_with_recorders()

    await dispatcher.execute(
        "set_nft_rights", params=_params(token_id=33), caller_identity=CALLER
    )
    await _drain()

    assert feed.events and attestation.calls
    assert feed.events[0]["actor"] == attestation.calls[0]["data"]["actor"] == CALLER


# ─────────────────────────────────────────────────────────────────────────
# THE GATEWAY — the frame that had the wallet and dropped it
# ─────────────────────────────────────────────────────────────────────────


class _FakeRequest:
    def __init__(self, body: dict) -> None:
        self._body = body

    async def json(self):
        return self._body


class _RecordingDispatcher:
    """Captures exactly what the bridge hands the dispatcher."""

    def __init__(self) -> None:
        self.calls: list[dict] = []

    async def execute(self, action, service=None, params=None, *, caller_identity=""):
        self.calls.append(
            {
                "action": action,
                "service": service,
                "params": params,
                "caller_identity": caller_identity,
            }
        )
        return json.dumps({"status": "ok", "action": action})


class _FakeServer:
    def __init__(self, dispatcher) -> None:
        self.service_dispatcher = dispatcher


def _bridge_with(dispatcher, session_id="sess-1", wallet=CALLER):
    from gateway.bridge import BridgeRoutes

    routes = BridgeRoutes({}, _FakeServer(dispatcher))
    routes._linked_wallets[session_id] = {"address": wallet}
    return routes


async def test_gateway_passes_the_wallet_it_already_bound():
    """DEFECT-PROVER. The bridge already had this wallet — it handed it to
    `bind_request_security` — and then dropped it on the next line."""
    recorder = _RecordingDispatcher()
    routes = _bridge_with(recorder)

    await routes.execute_action(
        _FakeRequest(
            {
                "action": "set_nft_rights",
                "params": _params(token_id=41),
                "session_id": "sess-1",
            }
        )
    )

    assert recorder.calls, "the bridge never reached the dispatcher"
    assert recorder.calls[0]["caller_identity"] == CALLER, (
        "the gateway bound this wallet into the security context and then "
        "called the dispatcher without it"
    )


async def test_gateway_action_with_params_reaches_its_service():
    """DEFECT-PROVER — the argument-slot bug found while threading identity.

    The bridge called `execute(action, params)`, but the signature is
    `execute(action, service=None, params=None)`, so the params dict landed in
    the SERVICE-OVERRIDE slot and the real params defaulted to {}. The registry
    lookup then raised `unhashable type: 'dict'` and EVERY bridge action
    carrying parameters returned a validation error. 17-D is unreachable
    without this: `set_rights` always carries params, so the request died
    before the service was ever called.
    """
    recorder = _RecordingDispatcher()
    routes = _bridge_with(recorder)
    sent = _params(token_id=42)

    await routes.execute_action(
        _FakeRequest(
            {"action": "set_nft_rights", "params": sent, "session_id": "sess-1"}
        )
    )

    call = recorder.calls[0]
    assert call["service"] is None, (
        f"params landed in the service-override slot: {call['service']!r}"
    )
    assert call["params"] == sent


async def test_gateway_with_no_linked_wallet_still_dispatches():
    """SCOPE-PIN. An unlinked session must not become an outage. It dispatches
    with an empty identity and the record says "unknown"."""
    recorder = _RecordingDispatcher()
    routes = _bridge_with(recorder)

    await routes.execute_action(
        _FakeRequest(
            {
                "action": "set_nft_rights",
                "params": _params(token_id=43),
                "session_id": "no-such-session",
            }
        )
    )

    assert recorder.calls, "an unlinked session was refused outright"
    assert recorder.calls[0]["caller_identity"] == ""


# ─────────────────────────────────────────────────────────────────────────
# SPOOFING — params are attacker-controlled on the bridge path
# ─────────────────────────────────────────────────────────────────────────


async def test_params_caller_identity_is_overwritten_when_nothing_is_threaded():
    """DEFECT-PROVER, group 2 (ratchet — measured to fail before).

    `params` IS the request body on the bridge path. If a
    client-supplied `caller_identity` were left to stand, this fix would ship
    a brand-new spoofing primitive: assert any address, have the platform
    record it as fact. Renamed from test_params_cannot_assert_an_identity_
    when_unauthenticated: it shows the one key the dispatcher overwrites, not
    that the body cannot name the caller by another route (on
    POST /api/v1/capabilities/{id}/invoke with no session it can, see
    tests/test_bound_identity_is_not_called_authenticated.py)."""
    dispatcher = ServiceDispatcher({})

    envelope = json.loads(
        await dispatcher.execute(
            "set_nft_rights",
            params=_params(token_id=51, caller_identity=OTHER),
        )
    )

    assert envelope["status"] == "ok", envelope
    assert envelope["result"]["set_by"] == "", (
        "a call whose entry point bound no identity wrote its own into the "
        "platform's record through params['caller_identity']"
    )


async def test_params_caller_identity_cannot_override_a_threaded_identity():
    """DEFECT-PROVER, group 2 (ratchet — measured to fail before).

    The threaded value wins over `params["caller_identity"]`, always. That is
    the only body key this overwrite covers: an entry point can still thread a
    value the caller wrote (see
    tests/test_bound_identity_is_not_called_authenticated.py).
    """
    dispatcher = ServiceDispatcher({})

    envelope = json.loads(
        await dispatcher.execute(
            "set_nft_rights",
            params=_params(token_id=52, caller_identity=OTHER),
            caller_identity=CALLER,
        )
    )

    assert envelope["result"]["set_by"] == CALLER


# ─────────────────────────────────────────────────────────────────────────
# SCOPE PINS — what this fix must NOT break
# ─────────────────────────────────────────────────────────────────────────


async def test_dispatch_without_identity_still_works_and_degrades_honestly():
    """SCOPE-PIN. Three of the four entry points that reach this dispatcher
    have no authenticated identity today. Refusing them would trade a gap in
    the record for an outage."""
    dispatcher = ServiceDispatcher({})

    envelope = json.loads(
        await dispatcher.execute("set_nft_rights", params=_params(token_id=61))
    )

    assert envelope["status"] == "ok", envelope
    assert envelope["result"]["rights"]["commercial"]["granted"] is True


async def test_service_records_unknown_rather_than_fabricating_a_caller():
    """DEFECT-PROVER (measured — the field does not exist before the change).

    "" means "we do not know", and must stay distinguishable from a real
    address. Nothing may be invented to fill the hole.
    """
    service = RightsManagement({})

    result = await service.set_rights(
        collection="0xCollection",
        token_id=62,
        rights={k: dict(v) for k, v in _RIGHTS.items()},
    )

    assert result["set_by"] == ""
    assert service._rights["0xCollection:62"]["rights"]["commercial"]["set_by"] == ""


async def test_positional_call_site_still_works():
    """SCOPE-PIN. `runtime/agents/handoff.py` calls
    `execute(action, None, params)` positionally. The new parameter is
    keyword-only precisely so this cannot break."""
    dispatcher = ServiceDispatcher({})

    envelope = json.loads(
        await dispatcher.execute("set_nft_rights", None, _params(token_id=63))
    )

    assert envelope["status"] == "ok", envelope


async def test_keyword_call_site_still_works():
    """SCOPE-PIN. `runtime/capabilities/registry.py` calls
    `execute(action=..., params=...)`."""
    dispatcher = ServiceDispatcher({})

    envelope = json.loads(
        await dispatcher.execute(action="set_nft_rights", params=_params(token_id=64))
    )

    assert envelope["status"] == "ok", envelope


async def test_direct_service_call_without_identity_still_works():
    """SCOPE-PIN. `NFTService.mint` writes the default rights grant with a
    three-positional-argument call and no caller. That is an in-process write,
    not a request, and must keep working."""
    service = RightsManagement({})

    result = await service.set_rights(
        "0xCollection", 65, {"display": {"granted": True, "holder": "0xCreator"}}
    )

    assert result["status"] == "rights_set"
    assert result["rights"]["display"]["granted"] is True


async def test_non_declaring_method_still_works_without_the_kwarg():
    """SCOPE-PIN — the blast-radius pin, in its before-and-after form.

    `check_rights` does not declare `caller_identity`. Dispatching it must be
    byte-for-byte the call it always was. This is the version that runs
    identically on both sides of the change; the threaded variant below cannot,
    because the parameter does not exist before it.
    """
    dispatcher = ServiceDispatcher({})

    await dispatcher.execute("set_nft_rights", params=_params(token_id=67))
    envelope = json.loads(
        await dispatcher.execute(
            "check_nft_rights",
            params={
                "collection": "0xCollection",
                "token_id": 67,
                "right_type": "commercial",
            },
        )
    )

    assert envelope["status"] == "ok", envelope
    assert envelope["result"]["granted"] is True


async def test_action_whose_method_does_not_declare_identity_is_unaffected():
    """DEFECT-PROVER, group 2 (ratchet — measured to fail before).

    Injection is gated on the target method's own signature. A method that has
    not declared `caller_identity` must be called EXACTLY as before, or this
    change breaks ~219 actions at once. `check_rights` does not declare it;
    threading an identity past it must be a no-op, not a TypeError.
    """
    dispatcher = ServiceDispatcher({})

    await dispatcher.execute("set_nft_rights", params=_params(token_id=66))
    envelope = json.loads(
        await dispatcher.execute(
            "check_nft_rights",
            params={
                "collection": "0xCollection",
                "token_id": 66,
                "right_type": "commercial",
            },
            caller_identity=CALLER,
        )
    )

    assert envelope["status"] == "ok", envelope
    assert "caller_identity" not in inspect.signature(
        RightsManagement.check_rights
    ).parameters


# ─────────────────────────────────────────────────────────────────────────
# THE SCOPE BOUNDARY — what this fix deliberately did NOT build
# ─────────────────────────────────────────────────────────────────────────


async def test_no_ownership_check_was_invented():
    """DEFECT-PROVER, group 2 (ratchet — measured to fail before).

    `set_rights` must NOT refuse a caller who does not hold the
    token, because this platform cannot tell whether they hold it:
    `NFTFactory._collections` is a cache with zero writers.

    Fabricating a control is worse than the gap it covers — the check would
    pass or fail on invented state. This test fails the moment someone adds an
    ownership refusal here, so that it has to be added with a real ownership
    record rather than quietly.
    """
    dispatcher = ServiceDispatcher({})

    envelope = json.loads(
        await dispatcher.execute(
            "set_nft_rights",
            params=_params(token_id=71),
            caller_identity="0xDefinitelyNotTheOwner",
        )
    )

    assert envelope["status"] == "ok", (
        "set_rights now refuses on ownership grounds. If a real ownership "
        "record was added, update this test; if not, the check is deciding on "
        "invented state."
    )


def test_collections_store_still_has_no_writers():
    """SCOPE-PIN — the premise this fix rests on, re-measured.

    The reason 17-D threads identity WITHOUT an ownership check is that there
    is nothing to check against. If `_collections` ever gains a writer that
    premise changes and the ownership half becomes buildable — this test is
    where that news arrives.
    """
    import pathlib

    factory = (
        pathlib.Path(__file__).resolve().parent.parent
        / "runtime/blockchain/services/nft_services/factory.py"
    )
    writes = [
        line.strip()
        for line in factory.read_text().splitlines()
        if "_collections[" in line
        and "=" in line
        and not line.strip().startswith("#")
    ]

    assert not writes, (
        f"_collections now has a writer: {writes}. The 'no ownership record "
        "exists' premise behind 17-D's scope no longer holds."
    )


@pytest.mark.parametrize(
    "method",
    [RightsManagement.set_rights, ServiceDispatcher.execute],
    ids=["RightsManagement.set_rights", "ServiceDispatcher.execute"],
)
def test_identity_parameter_stays_optional(method):
    """DEFECT-PROVER, group 2 (ratchet — measured to fail before).

    The parameter must never become required. The moment it does,
    every call site that threads no identity starts raising TypeError
    at dispatch time — an outage dressed as a security fix.
    """
    param = inspect.signature(method).parameters["caller_identity"]
    assert param.default == "", (
        f"{method.__qualname__} made caller_identity required"
    )


# ─────────────────────────────────────────────────────────────────────────
# THE SECOND GATEWAY ENTRY POINT — found by adversarial review
#
# `gateway/bridge.py` was not the only live HTTP path that knew the caller and
# dropped it. `POST /api/v1/capabilities/{id}/invoke`
# (gateway/service_routes.py:_handle_capability_invoke) reaches the SAME
# ServiceDispatcher through `CapabilityRegistry.invoke`, and `set_nft_rights`
# is a catalog capability id — so the identical IP-rights grant is reachable
# there. The identity is not missing on that path either: `gateway/server.py`'s
# `_security_context_middleware` binds it for every POST /api/v1/*, so
# `current_request_security()["wallet"]` is populated at the moment the handler
# runs. MEASURED before this half landed: a `set_nft_rights` invoked through
# this route with a bound identity recorded `set_by: ""`.
#
# Fixing the bridge alone would have been the same half-fix in a new place:
# one HTTP route naming the grantor, the other still attesting and publishing
# the same grant with actor "".
#
# BOUND, NOT AUTHENTICATED. On this route the middleware binds a session's
# identity when a session is presented; otherwise the X-Wallet-Address header;
# otherwise a body `wallet`, `from`, `sender` or `account` field or
# `params.from`. So without a session, the grantor this route records is an
# address the caller wrote.
# ─────────────────────────────────────────────────────────────────────────


async def test_capability_route_passes_the_identity_the_middleware_bound():
    """DEFECT-PROVER. The second gateway entry point must hand the dispatcher
    the wallet the security middleware already bound for this request.
    """
    from gateway.security_gate import bind_request_security
    from gateway.service_routes import ServiceRoutes

    bind_request_security(identity=CALLER, app_attest=None, session_id="s")

    routes = ServiceRoutes.__new__(ServiceRoutes)
    routes._config = {}
    recorder = _RecordingDispatcher()

    from runtime.capabilities import CapabilityRegistry

    routes._cap_registry_cache = CapabilityRegistry({}, recorder)

    await routes._handle_capability_invoke(
        _CapabilityRequest("set_nft_rights", {"params": _params(token_id=81)})
    )

    assert recorder.calls, "the capability route never reached the dispatcher"
    assert recorder.calls[0]["caller_identity"] == CALLER, (
        "POST /api/v1/capabilities/{id}/invoke bound this wallet in the "
        "security middleware and then called the dispatcher without it — the "
        "same identity drop as the bridge, at a second live HTTP route"
    )


async def test_capability_route_records_the_grantor_end_to_end():
    """DEFECT-PROVER. Not the call shape — the RECORD. Driving the real
    dispatcher through the capability registry must produce a grant that names
    the caller, on the service's own stored record."""
    from runtime.capabilities import CapabilityRegistry

    registry = CapabilityRegistry({}, ServiceDispatcher({}))

    out = await registry.invoke(
        "set_nft_rights", _params(token_id=82), caller_identity=CALLER
    )

    inner = json.loads(out["result"])
    assert inner["status"] == "ok", inner
    assert inner["result"]["set_by"] == CALLER, (
        "a rights grant made through the capability route still cannot say "
        "who made it"
    )


async def test_capability_registry_overwrites_a_params_caller_identity():
    """SCOPE-PIN — MEASURED to pass before this half landed, and kept anyway.

    Renamed from test_capability_route_body_cannot_assert_an_identity, which
    said more than it tests. It calls `CapabilityRegistry.invoke` directly,
    without the gateway, and shows one thing: with no identity threaded, a
    `params["caller_identity"]` is overwritten and the record says "unknown".
    The dispatcher-side injection does that unconditionally, so it held before
    the route was fixed. Counted as a pin, not a prover.

    It does NOT show that the route's body cannot assert an identity. It can.
    With no session and no X-Wallet-Address header, the security middleware
    binds a body `wallet`, `from`, `sender` or `account` field or `params.from`,
    the handler threads it, and it is recorded as the grantor.
    tests/test_bound_identity_is_not_called_authenticated.py drives that
    through the gateway.
    """
    from runtime.capabilities import CapabilityRegistry

    registry = CapabilityRegistry({}, ServiceDispatcher({}))

    out = await registry.invoke(
        "set_nft_rights", _params(token_id=83, caller_identity=OTHER)
    )

    inner = json.loads(out["result"])
    assert inner["status"] == "ok", inner
    assert inner["result"]["set_by"] == "", (
        "CapabilityRegistry.invoke let params['caller_identity'] become the "
        "platform's record of who granted the right"
    )


async def test_capability_invoke_identity_stays_optional():
    """SCOPE-PIN. The three non-HTTP callers of `invoke` thread no identity at
    all — not an unauthenticated one, none. Making the parameter required would
    turn a gap in the record into an outage."""
    from runtime.capabilities import CapabilityRegistry

    param = inspect.signature(CapabilityRegistry.invoke).parameters["caller_identity"]
    assert param.default == "", "CapabilityRegistry.invoke made identity required"

    registry = CapabilityRegistry({}, ServiceDispatcher({}))
    out = await registry.invoke("set_nft_rights", _params(token_id=84))
    inner = json.loads(out["result"])
    assert inner["status"] == "ok", inner
    assert inner["result"]["set_by"] == ""


class _CapabilityRequest:
    """Minimal aiohttp-request stand-in for `_handle_capability_invoke`."""

    def __init__(self, capability_id: str, body: dict) -> None:
        self.match_info = {"capability_id": capability_id}
        self._body = body

    async def json(self):
        return self._body


# ══════════════════════════════════════════════════════════════════════════
# 17-J — AN EMPTY ACTOR WAS THREE FACTS WEARING ONE VALUE
#
#   * no human initiated this        (agent hand-off — "" is CORRECT)
#   * a human initiated it and the identity was DROPPED   (17-D's defect)
#   * a human initiated it and was genuinely anonymous
#
# The first two rendered identically, which meant THE 17-D FIX COULD NOT
# DEMONSTRATE ITS OWN SUCCESS FROM THE TRAIL: an auditor seeing `actor: ""`
# post-fix could not tell a hand-off from a regression. A fix whose success is
# invisible in the artifact it produces is a fix nobody can audit — including
# us, later.
#
# THE ASSERTION THAT MATTERS IS THAT THE DISTINCTION IS RENDERABLE, not that a
# field exists. §AK's lesson applied to its own fix: the defect was a record
# that could not distinguish two facts, so the proof is that it now can.
#
# A sentinel was rejected. It makes ONE string carry both the identity and the
# reason for its absence — which is the collapse being fixed, relocated.
# ══════════════════════════════════════════════════════════════════════════

import pytest

from runtime.blockchain.services.service_dispatcher import ServiceDispatcher


class _RecordingFeed:
    def __init__(self) -> None:
        self.published: list[dict] = []

    async def ingest(self, **kwargs):
        self.published.append(kwargs)


def _rig():
    d = ServiceDispatcher({})
    feed = _RecordingFeed()
    d._feed_engine = feed
    seen: list[dict] = []

    async def _spy(action, service_name, params, result, *, actor="", actor_source=""):
        seen.append({"actor": actor, "actor_source": actor_source})

    d._attest_action = _spy
    d._attest_refusal = _spy
    return d, seen


@pytest.mark.parametrize(
    "kwargs,expect_actor,expect_source,label",
    [
        ({"caller_identity": "0xAUTH"}, "0xAUTH", "authenticated",
         "a threaded caller identity (labelled authenticated whatever its source)"),
        ({"caller_source": "agent_handoff"}, "", "agent_handoff",
         "an agent hand-off — no human, and the record SAYS no human"),
        ({}, "", "unauthenticated",
         "genuinely anonymous — distinct from both of the above"),
    ],
)
async def test_the_three_facts_render_differently(kwargs, expect_actor,
                                                  expect_source, label):
    """THE LOAD-BEARING ASSERTION OF 17-J.

    Not "a source field exists" — that would pass with the field hardcoded.
    THREE CALLS, THREE DISTINGUISHABLE RECORDS. If any two collapse, the defect
    is back, whatever the field contains.
    """
    d, seen = _rig()
    await d.execute("set_nft_rights", params={
        "collection": "0xC", "token_id": 1,
        "rights": {"commercial": {"granted": True, "holder": "0xH"}},
    }, **kwargs)

    assert seen, f"nothing recorded for {label}"
    assert seen[-1]["actor"] == expect_actor, label
    assert seen[-1]["actor_source"] == expect_source, label


async def test_a_dropped_identity_cannot_masquerade_as_a_hand_off():
    """THE REGRESSION DETECTOR — the reason 17-J exists.

    Post-fix, a dropped identity surfaces as `unauthenticated`, a value the
    hand-off path never writes. Pre-fix both were "" and indistinguishable, so
    a 17-D regression would have been invisible in the trail.
    """
    d, seen = _rig()
    await d.execute("set_nft_rights", params={
        "collection": "0xC", "token_id": 2,
        "rights": {"display": {"granted": True, "holder": "0xH"}},
    })
    dropped = seen[-1]["actor_source"]

    d2, seen2 = _rig()
    await d2.execute("set_nft_rights", params={
        "collection": "0xC", "token_id": 3,
        "rights": {"display": {"granted": True, "holder": "0xH"}},
    }, caller_source="agent_handoff")
    handoff = seen2[-1]["actor_source"]

    assert dropped != handoff, (
        "a dropped identity and an agent hand-off render identically — 17-J is "
        "back, and a 17-D regression would be invisible in the trail"
    )
