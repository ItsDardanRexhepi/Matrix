"""WHO THE RECORD NAMES IS WHO THE ENTRY POINT RESOLVED — NOT WHO THE BODY SAID.

Two attribution surfaces picked the actor out of the request body.

  DISPATCHER (runtime/blockchain/services/service_dispatcher.py). `_actor` was

      params.get("wallet") or params.get("address") or caller_identity or ""

  — the caller-written value FIRST, the identity the entry point resolved only
  as a fallback. So a request arriving with a session, whose wallet the bridge
  reads and threads as `caller_identity`, was attested and published to the
  PUBLIC social feed under whatever address the body wrote. Measured on the tree
  before this change::

      execute("create_social_profile",
              params={"address": "0xVICTIM", ...},
              caller_identity="0xSESSION")

      -> attestation actor "0xVICTIM", actor_source "authenticated"
      -> feed event actor "0xVICTIM"

  The resolved identity appeared nowhere in either record. `wallet` reaches the
  same line on 55 state-modifying actions whose service method takes `**kwargs`
  (auctions, restaking, ccip, mpc, storage, social_protocols …), and `address`
  on create_social_profile / update_social_profile, so this is not one action's
  parameter spelling.

  GATEWAY RIPPLE (gateway/service_routes.py `_maybe_ripple`). The same defect,
  wider: the live-feed broadcast for every executed /api/v1 action scanned the
  request kwargs for the first of FIFTEEN keys — owner, creator, author, sender,
  from_, from, uploader, requester, employer, holder, minter, user, voter,
  address, delegator — and published that as `actor`, while the identity the
  security middleware had bound for the very same request went unread. Measured::

      POST /api/v1/groups {"creator": "0xCLAIMED", "name": "B"}
      -> feed.ripple {"actor": "0xCLAIMED", ...}

WHAT REPLACES IT. The actor is the identity the entry point resolved, and only
that. A caller-supplied address is still recorded — suppressing it would trade a
false record for a thinner one — but as `actor_claimed`, a CLAIM about who
acted, never as the actor. When the two differ, the record carries both, which
is the interesting case: it is the shape of one caller naming another.

WHAT THIS DOES NOT CLAIM. "Resolved" means "bound by the entry point", not
"authenticated". The middleware binds a session's subject when there is one and,
for an operator request, the X-Wallet-Address header or a body field as written
(gateway/server.py); /chat threads the chat body's wallet. That overstatement is
older and wider than this change, is pinned by
tests/test_bound_identity_is_not_called_authenticated.py, and is NOT narrowed
here. What changes is that a value the request body wrote can no longer outrank
the bound one, and can no longer be the actor when nothing was bound at all.

17-J's three facts still render differently — see the parametrised test at the
end, which is that file's assertion re-run against this change.
"""

from __future__ import annotations

import asyncio

import pytest
from aiohttp import web
from aiohttp.test_utils import TestClient, TestServer

from runtime.blockchain.services.service_dispatcher import ServiceDispatcher


# ══════════════════════════════════════════════════════════════════════════
# rig
# ══════════════════════════════════════════════════════════════════════════

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

    async def _spy(action, service_name, params, result, *, actor="",
                   actor_source="", actor_claimed=""):
        seen.append({"actor": actor, "actor_source": actor_source,
                     "actor_claimed": actor_claimed})

    d._attest_action = _spy
    d._attest_refusal = _spy
    return d, seen, feed


# ══════════════════════════════════════════════════════════════════════════
# 1. the dispatcher — a body value never outranks the resolved identity
# ══════════════════════════════════════════════════════════════════════════

@pytest.mark.parametrize("action,params,key", [
    # `address` — declared parameter (social.create_profile).
    ("create_social_profile",
     {"address": "0xCLAIMED", "display_name": "x", "bio": "b"}, "address"),
    # `wallet` — reaches the same line through a **kwargs service method.
    # 55 state-modifying actions have one; auctions is two of them.
    ("create_auction", {"wallet": "0xCLAIMED", "asset": "x", "reserve": 1},
     "wallet"),
    ("place_bid", {"wallet": "0xCLAIMED", "auction_id": "a1", "amount": 2},
     "wallet"),
])
async def test_the_body_does_not_name_the_actor_when_an_identity_was_resolved(
        action, params, key):
    """THE LOAD-BEARING ASSERTION. The entry point resolved 0xSESSION; the body
    wrote 0xCLAIMED. The record names 0xSESSION and says 0xCLAIMED was claimed.
    """
    d, seen, _feed = _rig()
    await d.execute(action, params=dict(params), caller_identity="0xSESSION")

    assert seen, f"{action} recorded nothing"
    rec = seen[-1]
    assert rec["actor"] == "0xSESSION", (
        f"the {key} the body wrote is still the actor: {rec}"
    )
    assert rec["actor_claimed"] == "0xCLAIMED", (
        f"the caller-supplied {key} is not recorded as a claim: {rec}"
    )


async def test_with_no_resolved_identity_the_body_value_is_a_claim_not_the_actor():
    """"Only a client-supplied value exists" is the case the item names: the
    record must say CLAIMED, and must not promote it to actor."""
    d, seen, _feed = _rig()
    await d.execute("create_social_profile",
                    params={"address": "0xANON", "display_name": "x", "bio": "b"})

    rec = seen[-1]
    assert rec["actor"] == "", f"an unbound call still named an actor: {rec}"
    assert rec["actor_claimed"] == "0xANON", rec
    assert rec["actor_source"] == "unauthenticated", rec


async def test_a_claim_that_agrees_with_the_identity_is_not_recorded_twice():
    """Nothing is claimed when the body names the identity the entry point
    already resolved — the extra field is for the DISAGREEMENT, and a field
    that is always populated stops meaning anything."""
    d, seen, _feed = _rig()
    await d.execute("create_social_profile",
                    params={"address": "0xSAME", "display_name": "x", "bio": "b"},
                    caller_identity="0xSAME")

    rec = seen[-1]
    assert rec["actor"] == "0xSAME", rec
    assert rec["actor_claimed"] == "", rec


# ══════════════════════════════════════════════════════════════════════════
# 2. the PUBLIC feed carries the same answer as the audit record
# ══════════════════════════════════════════════════════════════════════════

async def test_the_public_feed_is_attributed_to_the_resolved_identity():
    """The half-fix this codebase keeps catching: attributing the audit record
    and leaving the public surface announcing the body's address. Both come off
    one value, so they cannot disagree."""
    d, seen, feed = _rig()
    await d.execute("create_social_profile",
                    params={"address": "0xVICTIM", "display_name": "x", "bio": "b"},
                    caller_identity="0xSESSION")
    await asyncio.sleep(0.05)   # the feed publish is fire-and-forget

    assert feed.published, "nothing was published"
    event = feed.published[-1]
    assert event["actor"] == "0xSESSION", (
        f"the public feed still announces the body's address: {event['actor']}"
    )
    assert event["detail"].get("actor_claimed") == "0xVICTIM", (
        f"the claim is not carried on the feed event: {event['detail']}"
    )


# ══════════════════════════════════════════════════════════════════════════
# 3. the gateway ripple — the same rule on the second attribution surface
# ══════════════════════════════════════════════════════════════════════════

@pytest.fixture
async def gateway():
    from gateway.service_routes import ServiceRoutes
    routes = ServiceRoutes(config={})
    app = web.Application()
    routes.register_routes(app)
    events: list[tuple] = []
    orig = routes.broadcaster.publish_dict

    def _spy(type_, payload, **kw):
        events.append((type_, payload))
        return orig(type_, payload, **kw)

    routes.broadcaster.publish_dict = _spy   # type: ignore[assignment]
    async with TestClient(TestServer(app)) as client:
        yield routes, client, events


async def test_the_ripple_does_not_name_an_actor_nobody_resolved(gateway):
    """No security context is bound for this request, so the platform resolved
    nobody. The live feed must not announce the body's `creator` as the actor.
    """
    _routes, client, events = gateway
    resp = await client.post("/api/v1/groups",
                             json={"creator": "0xCLAIMED", "name": "B"})
    assert resp.status == 200, await resp.text()

    ripples = [p for t, p in events if t == "feed.ripple"]
    assert ripples, "an executed action must still ripple"
    assert ripples[-1]["actor"] == "", (
        f"the ripple named an actor nobody resolved: {ripples[-1]}"
    )
    assert ripples[-1].get("actor_claimed") == "0xCLAIMED", (
        f"the claim was dropped instead of labelled: {ripples[-1]}"
    )


async def test_the_ripple_prefers_the_bound_identity_over_the_body():
    """With an identity bound for the request — what the security middleware
    does for every POST /api/v1/* — that identity is the actor, and the body's
    disagreeing value is the claim.

    The binding runs as a middleware in front of the real route, because the
    context is a ContextVar: set it in the test's own task and the handler,
    which runs in the server's task, would never see it. That is also why the
    real `_security_context_middleware` is a middleware and not a call inside
    each handler.
    """
    from gateway.security_gate import bind_request_security
    from gateway.service_routes import ServiceRoutes

    @web.middleware
    async def _bind(request, handler):
        bind_request_security(identity="0xBOUND")
        return await handler(request)

    routes = ServiceRoutes(config={})
    app = web.Application(middlewares=[_bind])
    routes.register_routes(app)
    events: list[tuple] = []
    orig = routes.broadcaster.publish_dict

    def _spy(type_, payload, **kw):
        events.append((type_, payload))
        return orig(type_, payload, **kw)

    routes.broadcaster.publish_dict = _spy   # type: ignore[assignment]

    async with TestClient(TestServer(app)) as client:
        resp = await client.post("/api/v1/groups",
                                 json={"creator": "0xCLAIMED", "name": "B"})
        assert resp.status == 200, await resp.text()

    ripples = [p for t, p in events if t == "feed.ripple"]
    assert ripples, "an executed action must still ripple"
    assert ripples[-1]["actor"] == "0xBOUND", (
        f"the bound identity lost to the body: {ripples[-1]}"
    )
    assert ripples[-1].get("actor_claimed") == "0xCLAIMED", ripples[-1]


def test_every_body_key_the_ripple_reads_is_read_as_a_claim():
    """§CD — the class, not the line. The ripple's actor scan covers fifteen
    body keys; a fix applied to `creator` alone would leave fourteen. Each is
    driven through the real `_maybe_ripple` with nothing bound."""
    from gateway.service_routes import ServiceRoutes

    routes = ServiceRoutes(config={})
    published: list = []
    routes._broadcaster = type("B", (), {
        "publish_dict": lambda _s, topic, payload: published.append((topic, payload)),
    })()

    keys = ("owner", "creator", "author", "sender", "from_", "from",
            "uploader", "requester", "employer", "holder", "minter",
            "user", "voter", "address", "delegator")
    for key in keys:
        published.clear()
        routes._maybe_ripple("defi", "create_loan", {key: "0xCLAIMED"},
                             {"status": "created", "id": "loan-1"})
        assert published, f"{key}: nothing rippled"
        payload = published[-1][1]
        assert payload["actor"] == "", (
            f"{key} is still promoted to actor: {payload}"
        )
        assert payload.get("actor_claimed") == "0xCLAIMED", (
            f"{key} is not recorded as a claim: {payload}"
        )


# ══════════════════════════════════════════════════════════════════════════
# 4. 17-J still holds — three facts, three renderings
# ══════════════════════════════════════════════════════════════════════════

@pytest.mark.parametrize("kwargs,expect_actor,expect_source,label", [
    ({"caller_identity": "0xAUTH"}, "0xAUTH", "authenticated",
     "a threaded caller identity"),
    ({"caller_source": "agent_handoff"}, "", "agent_handoff",
     "an agent hand-off — no human, and the record SAYS no human"),
    ({}, "", "unauthenticated", "genuinely anonymous"),
])
async def test_the_three_facts_still_render_differently(kwargs, expect_actor,
                                                        expect_source, label):
    """Re-run of 17-J's assertion against this change. Binding the actor to the
    resolved identity must not collapse a hand-off into a dropped identity."""
    d, seen, _feed = _rig()
    await d.execute("set_nft_rights", params={
        "collection": "0xC", "token_id": 1,
        "rights": {"commercial": {"granted": True, "holder": "0xH"}},
    }, **kwargs)

    assert seen, f"nothing recorded for {label}"
    assert seen[-1]["actor"] == expect_actor, label
    assert seen[-1]["actor_source"] == expect_source, label
    assert seen[-1]["actor_claimed"] == "", (
        f"{label}: nothing was claimed, so nothing should be recorded as a claim"
    )
