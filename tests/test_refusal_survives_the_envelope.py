"""A refusal must still be a refusal after the platform wraps it.

WHAT LANDED, AND WHERE IT STOPS. ``runtime/protocols/outcome_truth.py`` reads a
tool's own verdict from the STRUCTURE it returned, and ``post_action`` refuses to
learn from an outcome nobody labelled. That fix is real and it is right. It reads
the structure the tool returned — and in this platform the structure the tool
returned is almost never the structure the next layer passes on.

Three envelopes stand between a service's refusal and every consumer of it:

  * ``ServiceDispatcher.execute``  -> ``{"status": "ok", "result": <refusal>}``
  * ``ServiceRoutes._ok``          -> ``{"status": "ok", "data":   <refusal>}``
  * ``MobileResponse.ok``          -> ``{"ok": true,    "data":   <refusal>}``

Each is built AFTER the refusal is in hand, and each states a verdict of its own
over it. ``report_of`` then reads the envelope's verdict, because that is the
outermost named field and it is exactly the kind of field the module was built to
believe. So the mega-tool — ``platform_action``, the single handler through which
the agent reaches all 45 services — relays every refusal to the learner as a
success, and the two HTTP surfaces relay it to callers as HTTP 200 ``ok``.

The envelope is not lying about itself. ``ServiceDispatcher.execute`` really did
complete; ``_ok`` really did serve the request. That is the whole difficulty: the
transport's truthful claim about ITSELF is written into the same field name that
the service uses to report ITS outcome, and the reader cannot tell them apart.
The rule this file pins is that it does not have to: a wrapper may report on the
wrapping, and it may never report on what it wraps.

The same assumption, away from the envelope, in three more places:

  * the HTTP live-feed ripple published a returned refusal as an executed action;
  * account deletion answered ``{"success": true}`` after swallowing the
    push-token and session removals;
  * ``/ready`` reported three model providers reachable from ``bool(api_key)``;
  * every platform-signed transaction was signed by an UNMETERED exemption whose
    stated justification was that its call sites meter themselves — none did.

NONE OF THIS IS A STRING SNIFF (§NEW-27). Every assertion below is about named
fields of structures the platform itself emitted.
"""
from __future__ import annotations

import asyncio
import json
import tempfile
import time

import pytest
from aiohttp.test_utils import TestClient, TestServer

from gateway.bridge import MobileResponse
from gateway.service_routes import ServiceRoutes
from runtime.protocols.outcome_truth import (
    FAILURE,
    OUTCOME_FIELD,
    SUCCESS,
    UNKNOWN,
    report_of,
)


# The canonical refusal, built by the platform's own helper rather than typed
# out here, so the control cannot drift from the shape services actually return.
def _refusal() -> dict:
    from runtime.blockchain.web3_manager import not_deployed_response
    return not_deployed_response("defi")


# ── 1. report_of must see through the platform's own envelopes ─────────────

def test_a_bare_refusal_is_read_as_a_refusal():
    """The baseline the rest of the file is measured against."""
    assert report_of(_refusal()) == FAILURE


@pytest.mark.parametrize("wrap", [
    # ServiceDispatcher.execute — the mega-tool's envelope, a JSON STRING.
    lambda inner: json.dumps({"status": "ok", "action": "create_loan",
                              "service": "defi", "result": inner,
                              "elapsed_ms": 3}),
    # ServiceRoutes._ok — the /api/v1 envelope.
    lambda inner: {"status": "ok", "data": inner},
    # MobileResponse.ok — the bridge envelope.
    lambda inner: {"ok": True, "data": inner, "timestamp": 0.0},
    # Both bridge envelopes, as /bridge/v1/action actually nests them.
    lambda inner: {"ok": True, "timestamp": 0.0,
                   "data": {"status": "ok", "action": "create_loan",
                            "result": inner}},
])
def test_an_envelope_cannot_report_a_success_over_a_refusal(wrap):
    assert report_of(wrap(_refusal())) == FAILURE, (
        "the wrapper answered for what it wrapped; every refusal relayed "
        "through this envelope is learned, and published, as a success"
    )


def test_an_envelope_over_an_unlabelled_payload_is_unknown_not_success():
    """The third answer survives the wrapping too. ``pending`` carries opposite
    meanings in different services, which is why outcome_truth refuses to grade
    it — an envelope must not launder it into a graded success."""
    assert report_of({"status": "ok", "data": {"status": "pending"}}) == UNKNOWN


def test_the_bridge_envelope_the_bridge_ACTUALLY_EMITS_sees_through_too():
    """THE SHAPE, NOT AN APPROXIMATION OF IT.

    Every bridge case above is a dict typed out in this file. The real
    ``MobileResponse.ok`` writes one more field than any of them —
    ``call_outcome``, defaulted to SUCCESS when the caller did not state one —
    and that field is the one ``report_of`` believes over everything else,
    including its own unwrapping. So the control passed on a shape the bridge
    does not emit, while the shape it does emit hid the refusal exactly as
    before the fix.

    Built by calling the emitter, so this cannot drift from it again.
    """
    body = json.loads(MobileResponse.ok(_refusal()).body.decode())
    assert report_of(body) == FAILURE, (
        "the bridge envelope stated a verdict nobody established, and that "
        f"stated SUCCESS outranks the unwrapping that would have found it: {body}")


def test_the_bridge_envelope_does_not_bury_a_verdict_the_dispatcher_STATED():
    """THE WORST CASE THE DEFAULT ALLOWED — LATENT, NOT LIVE.

    ``ServiceDispatcher.execute`` reads its payload with the one fact no reader
    downstream holds — whether the action modifies state — and STATES the
    answer. When that answer is FAILURE and the bridge wraps it with a
    defaulted SUCCESS, the outer default outranks the inner statement: the
    layer that knew was overruled by the layer that did not look.

    This docstring first called that live. It was not. When the default was
    removed, the one bridge route that relays a dispatcher payload,
    /bridge/v1/action, already passed ``outcome=``; the other thirteen routes
    that build this envelope carry payloads with no verdict field in them —
    chat replies, sessions, catalogs, the dashboard — which read as success
    with the default or without it. No response the bridge sent changed. The
    control stays because the next route that relays a stated verdict without
    ``outcome=`` would bury it, and nothing else would notice.
    """
    relayed = json.dumps({"status": "ok", "action": "create_loan",
                          "service": "defi", OUTCOME_FIELD: FAILURE,
                          "result": _refusal()})
    body = json.loads(MobileResponse.ok(relayed).body.decode())
    assert report_of(body) == FAILURE, (
        "the dispatcher stated FAILURE and the bridge's defaulted SUCCESS "
        f"buried it: {body}")


def test_the_bridge_envelope_still_states_success_for_a_payload_that_succeeded():
    """The scope pin. A wrapper that downgraded everything would teach the
    learner that the whole platform fails — the same defect facing the other
    way. A payload that reports success, and one that reports nothing at all,
    both stay SUCCESS."""
    for data in ({"status": "deployed", "tx_hash": "0x1"},
                 {"registered": True},
                 {"components": [1, 2, 3]}):
        body = json.loads(MobileResponse.ok(data).body.decode())
        assert body[OUTCOME_FIELD] == SUCCESS, body
        assert report_of(body) == SUCCESS, body


def test_a_caller_that_KNOWS_still_outranks_what_the_payload_looks_like():
    """``outcome=`` is why the field exists: /bridge/v1/action holds the action
    name and the dispatcher's reading of it, and that statement must survive
    a payload the generic reader would grade differently."""
    body = json.loads(
        MobileResponse.ok({"status": "failed"}, outcome=SUCCESS).body.decode())
    assert body[OUTCOME_FIELD] == SUCCESS and report_of(body) == SUCCESS, body


def test_an_envelope_over_a_real_success_is_still_a_success():
    """The dangerous half. A wrapper that downgraded everything would teach the
    learner that the whole platform fails."""
    assert report_of({"status": "ok", "data": {"status": "deployed"}}) == SUCCESS
    assert report_of({"ok": True, "data": {"balance": "5.0"}}) == SUCCESS
    assert report_of({"status": "ok", "data": [1, 2, 3]}) == SUCCESS
    assert report_of({"status": "ok", "data": None}) == SUCCESS


# ── 2. ServiceRoutes._ok must not stamp "ok" on a refusal ──────────────────

@pytest.fixture
def routes():
    return ServiceRoutes(config={})


def test_ok_does_not_relay_a_refusal_as_status_ok(routes):
    resp = routes._ok(_refusal())
    body = json.loads(resp.body.decode())
    assert body["status"] != "ok", (
        "HTTP 200 {'status': 'ok'} over a not_deployed payload — sdk/client.py "
        "checks only resp.status, so the caller proceeds as though it worked"
    )
    assert body["data"]["status"] == "not_deployed", "the service's detail was dropped"


def test_a_capability_the_platform_does_not_have_is_not_a_200(routes):
    """``not_deployed`` is not a domain answer the caller asked for — it is the
    platform saying it cannot act at all. RUN-4 protects genuine domain outcomes
    at 200 and was right to; this is not one of them."""
    assert routes._ok(_refusal()).status in (501, 503)


# ── 2b. …and neither may the OTHER route that relays the same payload ─────
#
# The /api/v1 surface answers a `not_deployed` refusal with 503 and the outcome
# in its own field. `POST /api/v1/capabilities/{id}/invoke` relays the SAME
# dispatcher payload through `CapabilityRegistry.invoke`, which wraps it as
# {"status": "ok", "result": <the dispatcher's envelope>} whatever it says, and
# answered HTTP 200 {"status": "ok"} with no outcome anywhere a client reads.
# Two /api/v1 surfaces gave opposite answers for the same refusal, and this one
# is on the session allowlist — the iOS app calls it.


async def _invoke(capability_id: str, params: dict | None = None):
    from aiohttp import web as _web

    routes = ServiceRoutes(config={})
    app = _web.Application()
    routes.register_routes(app)
    async with TestClient(TestServer(app)) as client:
        resp = await client.post(f"/api/v1/capabilities/{capability_id}/invoke",
                                 json={"params": params or {}})
        return resp.status, await resp.json()


async def test_the_invoke_route_does_not_answer_200_ok_over_a_relayed_refusal():
    """`place_limit_order` reaches `auctions`, which is not deployed here."""
    status, body = await _invoke("place_limit_order", {
        "auction_id": "a1", "bidder": "0xabc", "amount": 1.0,
    })
    assert body.get("result"), f"premise changed — nothing was relayed: {body}"
    assert report_of(body) == FAILURE, f"premise changed — not a refusal: {body}"
    assert status != 200, (
        f"HTTP {status} {{'status': {body.get('status')!r}}} over a refusal the "
        "same platform answers 503 for on /api/v1/licensing/ip; sdk/client.py "
        "raises only on a non-200, so the caller proceeds as though it worked"
    )
    assert body.get(OUTCOME_FIELD) == FAILURE, (
        f"the envelope states no outcome of its own: {sorted(body)}")


async def test_the_invoke_route_still_relays_an_executed_action():
    """The scope pin. A capability that really runs keeps its 200 and says so."""
    status, body = await _invoke("community_create", {
        "creator": "0xabc", "name": "Builders",
    })
    assert status == 200, body
    assert body.get(OUTCOME_FIELD) == SUCCESS, body


async def test_the_registry_envelope_states_what_it_wraps():
    """Read at the source, not only through the route: the registry's envelope
    is where the verdict went missing, and the route is not its only caller."""
    from runtime.capabilities.registry import CapabilityRegistry

    reg = CapabilityRegistry({})
    refused = await reg.invoke("place_limit_order", {
        "auction_id": "a1", "bidder": "0xabc", "amount": 1.0,
    }, caller_identity="0xabc")
    assert refused[OUTCOME_FIELD] == FAILURE, refused
    ran = await reg.invoke("community_create", {
        "creator": "0xabc", "name": "Builders",
    }, caller_identity="0xabc")
    assert ran[OUTCOME_FIELD] == SUCCESS, ran


# ── 3. the live feed must not publish a refusal as an executed action ──────

def test_the_ripple_does_not_publish_a_returned_refusal(routes):
    published: list = []
    routes._broadcaster = type("B", (), {
        "publish_dict": lambda _self, topic, payload: published.append((topic, payload))
    })()
    routes._maybe_ripple("defi", "create_loan", {"owner": "0xabc"}, _refusal())
    assert published == [], (
        f"the public feed announced a refusal as an executed action: {published}"
    )


def test_the_ripple_still_publishes_a_real_action(routes):
    published: list = []
    routes._broadcaster = type("B", (), {
        "publish_dict": lambda _self, topic, payload: published.append((topic, payload))
    })()
    routes._maybe_ripple("defi", "create_loan", {"owner": "0xabc"},
                         {"status": "created", "id": "loan-1"})
    assert len(published) == 1 and published[0][0] == "feed.ripple"


# ── 3b. nor a broadcast — the third answer, on the HTTP path ───────────────
#
# The dispatcher's feed path records a transaction that was sent and not
# confirmed as a BROADCAST and announces nothing (`_record_verdict`, the third
# answer). `_maybe_ripple` is the same feed on the /api/v1 path, and it read the
# result through `report_of` alone, which answers SUCCESS for the bare
# `{"status": "submitted", "tx_hash": ...}` that twenty-six methods return
# straight off the send — so the live feed announced a bridge, a channel close
# or a liquidation as an executed action on the evidence that a node had taken
# the bytes. The README says a broadcast is not announced on the feed as done;
# it was, on this surface.

_HASH = "0x" + "ab" * 32


def _feed(routes) -> list:
    published: list = []
    routes._broadcaster = type("B", (), {
        "publish_dict": lambda _self, topic, payload: published.append((topic, payload))
    })()
    return published


def test_the_ripple_does_not_announce_a_bare_broadcast_as_done(routes, caplog):
    """DEFECT-PROVER. The shape is what `neosafe.route_revenue` and its
    twenty-five siblings return with no receipt wait, and what the dispatcher
    records as a broadcast."""
    import logging

    from runtime.blockchain.services.service_dispatcher import RECORD_BROADCAST, _record_verdict

    published = _feed(routes)
    sent = {"status": "submitted", "tx_hash": _HASH, "service": "bridge"}
    assert _record_verdict(sent) == RECORD_BROADCAST, "premise changed — the dispatcher no longer calls this a broadcast"
    with caplog.at_level(logging.INFO):
        routes._maybe_ripple("bridge", "cross_chain_bridge", {"sender": "0xabc"}, sent)
    assert published == [], (
        f"the public feed announced a broadcast as an executed action: {published}")
    messages = [r.getMessage() for r in caplog.records]
    assert any("ACTION BROADCAST" in m and _HASH in m for m in messages), (
        f"a sent transaction left no record carrying its hash: {messages}")
    assert not any("ACTION DECLINED" in m for m in messages), "a broadcast was recorded as a decline"


async def test_the_ripple_does_not_announce_an_unconfirmed_wait_either(routes):
    """The other broadcast shape, built by calling the emitter: what
    `settle_transaction` returns when its wait runs out."""
    from runtime.blockchain.web3_manager import settle_transaction

    class _NoReceipt:
        async def wait_for_receipt(self, _tx_hash, timeout=120):
            raise TimeoutError("no receipt in time")

    unconfirmed = await settle_transaction(_NoReceipt(), _HASH, "route_revenue", "neosafe")
    assert unconfirmed.get("broadcast") is True and unconfirmed.get("settled") is False
    published = _feed(routes)
    routes._maybe_ripple("neosafe", "route_revenue", {"sender": "0xabc"}, unconfirmed)
    assert published == [], (
        f"the public feed announced an unconfirmed transaction as an executed action: {published}")


async def test_the_ripple_still_announces_a_settled_transaction(routes):
    """SCOPE PIN, and the ordering argument: `settle_transaction`'s confirmed
    shape keeps the word "submitted" and carries `settled: True`, and a gate
    keyed on the word would silence exactly the services that wait."""
    from runtime.blockchain.web3_manager import settle_transaction

    class _Confirmed:
        async def wait_for_receipt(self, _tx_hash, timeout=120):
            return {"status": 1, "blockNumber": 7, "gasUsed": 21000}

    settled = await settle_transaction(_Confirmed(), _HASH, "route_revenue", "neosafe")
    assert settled.get("settled") is True and settled.get("status") == "submitted"
    published = _feed(routes)
    routes._maybe_ripple("neosafe", "route_revenue", {"sender": "0xabc"}, settled)
    assert len(published) == 1 and published[0][0] == "feed.ripple", published
    assert published[0][1].get("ref") == _HASH and published[0][1].get("status") == "submitted"


# ── 4. the bridge must not answer ok:true over the dispatcher's refusal ────

def test_bridge_action_does_not_answer_ok_true_over_a_relayed_refusal():
    from gateway.bridge import BridgeRoutes

    relayed = json.dumps({"status": "ok", "action": "create_loan",
                          "service": "defi", "result": _refusal()})
    resp = BridgeRoutes._action_response("create_loan", relayed)
    body = json.loads(resp.body.decode())
    assert body.get("ok") is not True, (
        "the bridge read the dispatcher's OUTER status, which says 'ok' "
        "whenever the service RETURNED rather than raised"
    )


async def test_the_bridge_does_not_announce_a_refusal_for_an_action_it_performed():
    """THE OTHER DIRECTION, ON THE SURFACE A USER READS. `gaming.resolve_market`
    writes the CALLER's market outcome into the record it returns, and
    "failure" is a legitimate answer to a market question. The bridge read that
    domain word as its own verdict and showed the user
    ``{"ok": false, "refused": true, "error": "The platform did not perform
    this action."}`` — with the resolution record, status "resolved" and a real
    id, sitting inside `data` as proof that it had. Caller-controlled, so any
    client could make the platform announce a refusal for an action it took.

    The dispatcher-level reading is pinned in
    tests/test_envelopes_do_not_hide_refusals.py; this pins the sentence the
    client is shown, which is where the fabrication was visible.
    """
    from gateway.bridge import BridgeRoutes
    from runtime.blockchain.services.service_dispatcher import ServiceDispatcher

    env = await ServiceDispatcher({}).execute("market_resolve", params={
        "market_id": "mkt-1", "outcome": "failure", "resolver": "0xabc",
    })
    relayed = json.loads(env)
    assert relayed["result"]["status"] == "resolved", f"premise changed: {relayed}"
    assert relayed["result"]["outcome"] == "failure", f"premise changed: {relayed}"

    resp = BridgeRoutes._action_response("market_resolve", env)
    body = json.loads(resp.body.decode())
    assert body.get("refused") is not True and body.get("ok") is True, (
        f"the bridge told the client the platform did not act: {body}")
    assert body.get(OUTCOME_FIELD) == SUCCESS, body


def test_bridge_action_still_relays_a_real_result():
    from gateway.bridge import BridgeRoutes

    relayed = json.dumps({"status": "ok", "action": "get_loan",
                          "result": {"status": "active", "id": "loan-1"}})
    resp = BridgeRoutes._action_response("get_loan", relayed)
    body = json.loads(resp.body.decode())
    assert resp.status == 200 and body["ok"] is True


# ── 5. account deletion must not answer success over a swallowed removal ───

def _delete_server():
    from gateway.server import GatewayServer
    from tests.test_route_sweep import SWEEP_CONFIG

    scratch = tempfile.mkdtemp(prefix="the-matrix-envelope-del-")
    return GatewayServer({**SWEEP_CONFIG, "memory_dir": scratch,
                          "database": {"path": f"{scratch}/d.db"}})


async def test_a_deletion_that_could_not_remove_the_session_is_not_a_success():
    """The session token is the account's live credential. A deletion that left
    it usable and answered ``{"success": true}`` told the caller their account
    was gone while it was still reachable with the token in their hand."""
    server = _delete_server()
    subject = "apple:envelope-del"

    async def wont_remove(_token):
        raise RuntimeError("session store unavailable")

    async with TestClient(TestServer(server.create_app())) as client:
        token = f"tok-{subject}"
        now = time.time()
        await server.wallet_sessions.add(token=token, address=subject,
                                         issued_at=now, expires_at=now + 3600)
        headers = {"Authorization": f"Bearer {token}"}
        server.wallet_sessions.remove = wont_remove

        resp = await client.delete("/api/v1/auth/account", headers=headers)
        body = await resp.json()
        assert body.get("success") is not True, (
            f"the session removal was swallowed and the answer was {body}"
        )
        assert resp.status != 200, body
        # The session really is still there — the answer was not merely cautious.
        assert server.wallet_sessions.get(token)


async def test_a_clean_deletion_is_still_a_success():
    server = _delete_server()
    subject = "apple:envelope-del-ok"
    async with TestClient(TestServer(server.create_app())) as client:
        token = f"tok-{subject}"
        now = time.time()
        await server.wallet_sessions.add(token=token, address=subject,
                                         issued_at=now, expires_at=now + 3600)
        resp = await client.delete("/api/v1/auth/account",
                                   headers={"Authorization": f"Bearer {token}"})
        body = await resp.json()
        assert resp.status == 200 and body["success"] is True, body


async def test_a_retry_after_a_failed_push_removal_still_finishes_the_job():
    """THE PROMISE THE ORDERING MAKES. The handler returns 503 before the
    session is removed so the client still holds a credential to retry with,
    and says re-running the deletion is safe because "both removals are by-id".

    It is not safe for the device the mechanism exists to catch. A token
    registered before `push_tokens` carried an owner is findable ONLY through
    the account's conversation ids, and those are read BEFORE the erasure. If
    the erasure has already committed when the push removal fails, the retry's
    pre-erasure read comes back empty, the ownerless device is unreachable for
    ever, and the retry answers {"success": true} with it still registered:
    the false success moved from the first response to the second.
    """
    from runtime.notifications.token_store import PushTokenStore

    server = _delete_server()
    subject = "apple:envelope-del-retry"
    conversation = "conv:legacy-device-owner"
    attempts = {"n": 0}
    unpatched = PushTokenStore.remove_for_account

    async def fails_the_first_time(self, owner, session_ids=()):
        attempts["n"] += 1
        if attempts["n"] == 1:
            raise RuntimeError("push token store unavailable")
        return await unpatched(self, owner, session_ids)

    async with TestClient(TestServer(server.create_app())) as client:
        memory = server.react_loop.memory
        # The documented legacy shape: a device filed under one of the
        # account's own conversations, with NO owner recorded on it.
        memory.claim_conversation(conversation, subject)
        store = PushTokenStore(memory.db)
        await store.register("legacy-device", session_id=conversation)
        assert await store.tokens_for(session_id=conversation) == ["legacy-device"]

        token = f"tok-{subject}"
        now = time.time()
        await server.wallet_sessions.add(token=token, address=subject,
                                         issued_at=now, expires_at=now + 3600)
        headers = {"Authorization": f"Bearer {token}"}

        PushTokenStore.remove_for_account = fails_the_first_time
        try:
            first = await client.delete("/api/v1/auth/account", headers=headers)
            assert first.status == 503, await first.json()
            assert server.wallet_sessions.get(token), (
                "the retry the ordering promises needs the session to survive")
            retry = await client.delete("/api/v1/auth/account", headers=headers)
        finally:
            PushTokenStore.remove_for_account = unpatched

        body = await retry.json()
        still_registered = await store.tokens_for(session_id=conversation)
        assert not still_registered, (
            f"the retry answered {body} with the account's device still "
            f"registered: {still_registered}")
        assert retry.status == 200 and body["success"] is True, body


# ── 6. a provider is reachable when it ANSWERS, not when a key is set ──────

@pytest.mark.parametrize("module_name,class_name", [
    ("runtime.models.anthropic_client", "AnthropicClient"),
    ("runtime.models.gemini_client", "GeminiClient"),
    ("runtime.models.nvidia_client", "NVIDIAClient"),
    # Mythos is the platform's own Claude-backed profile; it inherits whatever
    # AnthropicClient does, which is why the sibling is pinned here.
    ("runtime.models.mythos_client", "MythosClient"),
])
async def test_a_configured_but_unreachable_provider_is_not_reported_reachable(
        module_name, class_name):
    """``/ready`` takes an instance out of rotation when NO provider is
    reachable. A provider that reports itself reachable because a key is set
    keeps a dead instance serving traffic — the exact condition RUN-7 built
    ``/ready`` to express."""
    import importlib

    cls = getattr(importlib.import_module(module_name), class_name)
    # A key is configured and the endpoint does not exist: the honest answer is
    # False, and the only way to know it is to ask.
    client = cls({"api_key": "sk-configured-but-the-host-is-not-there",
                  "base_url": "http://127.0.0.1:1"})
    assert await client.health_check() is False, (
        f"{class_name} reported itself reachable without reaching anything"
    )


@pytest.mark.parametrize("module_name,class_name", [
    ("runtime.models.anthropic_client", "AnthropicClient"),
    ("runtime.models.gemini_client", "GeminiClient"),
    ("runtime.models.nvidia_client", "NVIDIAClient"),
])
async def test_an_unconfigured_provider_is_not_reachable_either(module_name, class_name):
    import importlib

    cls = getattr(importlib.import_module(module_name), class_name)
    assert await cls({"api_key": ""}).health_check() is False


# ── 7. the platform's transactions are metered, or the cap is decoration ───

def test_no_exemption_claims_a_call_site_meters_it_unless_one_does():
    """§CT. ``UNMETERED_PLATFORM_OPERATIONS`` is a reviewable list, and its
    entries are claims. ``web3.platform_account`` claimed "every USE of it is a
    call site metered on its own" — ``Web3Manager.send_transaction`` signs with
    that handle directly and is the ONLY signing path the 45 services have, so
    no use of it was metered anywhere."""
    from runtime.blockchain.sponsorship import UNMETERED_PLATFORM_OPERATIONS
    assert "web3.platform_account" not in UNMETERED_PLATFORM_OPERATIONS, (
        "the exemption that covers every service transaction is still listed; "
        "the D-045 daily cap meters nothing the platform actually signs"
    )


async def test_a_service_transaction_is_metered_against_the_cap(tmp_path, monkeypatch):
    """The property, not the plumbing: send a transaction through the one path
    all 45 services use and assert the sponsorship ledger recorded the spend."""
    from runtime.blockchain.sponsorship import SponsorshipPolicy, set_caller_identity
    from runtime.blockchain.web3_manager import Web3Manager

    key = "0x" + "11" * 32
    config = {
        "blockchain": {"paymaster_private_key": key, "chain_id": 84532,
                       "rpc_url": "http://127.0.0.1:1"},
        "paymaster": {"policy": {"daily_cap_usd": 50.0}},
        "database": {"path": str(tmp_path / "d.db")},
    }
    manager = Web3Manager(config)

    class _Eth:
        gas_price = 1_000_000_000
        @staticmethod
        def get_transaction_count(_a): return 0
        @staticmethod
        def estimate_gas(_t): return 21_000
        @staticmethod
        def send_raw_transaction(_raw):
            return bytes.fromhex("ab" * 32)

    class _W3:
        eth = _Eth()
        @staticmethod
        def to_checksum_address(a): return a

    manager.w3 = _W3()
    manager.available = True

    from runtime.blockchain import price_feed as _pf
    async def _quote(self): return {"price": 3000.0}
    monkeypatch.setattr(_pf.PriceFeed, "eth_usd", _quote)

    from eth_utils import to_checksum_address

    token = set_caller_identity("0x" + "ab" * 20)
    try:
        await manager.send_transaction(
            {"to": to_checksum_address("0x" + "cd" * 20), "value": 0})
    finally:
        from runtime.blockchain.sponsorship import reset_caller_identity
        reset_caller_identity(token)

    policy = SponsorshipPolicy.from_config(config)
    assert policy.spent_today("0x" + "ab" * 20) > 0, (
        "the transaction was signed and broadcast and the sponsorship ledger "
        "recorded nothing — the cap does not see what the platform signs"
    )


async def test_the_readiness_probe_asks_every_provider_at_once():
    """A real probe has a real cost, and a serial one is a new defect.

    Three providers answered ``bool(self.api_key)`` without leaving the
    process, so a serial loop over five of them was free. Asking for real makes
    the loop cost the SUM of five timeouts, and an orchestrator reads a
    readiness probe that times out as "not ready" — the instance is pulled for
    being slow to say it was fine.
    """
    from runtime.models.router import ModelRouter

    in_flight = {"now": 0, "peak": 0}

    class _Slow:
        async def health_check(self) -> bool:
            in_flight["now"] += 1
            in_flight["peak"] = max(in_flight["peak"], in_flight["now"])
            await asyncio.sleep(0.05)
            in_flight["now"] -= 1
            return True

    router = ModelRouter.__new__(ModelRouter)
    router.providers = {f"p{i}": _Slow() for i in range(5)}

    started = time.monotonic()
    health = await router.health_check()
    elapsed = time.monotonic() - started

    assert health == {f"p{i}": True for i in range(5)}
    assert in_flight["peak"] == 5, (
        f"the probes ran {in_flight['peak']} at a time; five real timeouts in "
        "series is a readiness probe that fails by being slow")
    assert elapsed < 0.2, elapsed


async def test_a_provider_that_raises_is_not_ready_rather_than_an_exception():
    """``/ready`` must answer. A provider whose probe blows up is one that did
    not answer, which is what this method is asked to report."""
    from runtime.models.router import ModelRouter

    class _Broken:
        async def health_check(self) -> bool:
            raise RuntimeError("no route to host")

    class _Fine:
        async def health_check(self) -> bool:
            return True

    router = ModelRouter.__new__(ModelRouter)
    router.providers = {"broken": _Broken(), "fine": _Fine()}
    assert await router.health_check() == {"broken": False, "fine": True}

