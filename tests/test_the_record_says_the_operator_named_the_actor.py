"""THE RECORD SAYS WHEN THE OPERATOR KEY NAMED THE ACTOR.

A state-modifying action is attributed to the identity its entry point resolved
(tests/test_the_actor_is_the_resolved_identity.py). An entry point resolves one
in one of two ways:

  * from a presented wallet session — the session's subject, or the wallet
    linked to the Apple user; nothing in the request overrides it;
  * with no session, from what a request carrying the operator key names: an
    ``X-Wallet-Address`` header, a body ``wallet``/``from``/``sender``/
    ``account`` field or ``params.from`` on ``/api/v1/*``, a chat body's
    ``wallet``, or the wallet linked to a bridge session id the request names.

The second is the decided operator path — an integration holding the operator
key names the user it acts for — and docs/api-reference.md ("Identity") calls
that value asserted, not authenticated. Who may name an identity is not what
this file is about, and nothing here changes it.

What it is about is the record. ``ServiceDispatcher.execute`` labelled every
threaded identity ``actor_source: "authenticated"``, so an address the operator
wrote was recorded exactly like a session's subject, and nothing in the
attestation, the refusal record or the broadcast record said the operator
key had named it. Measured on the tree before this change, through the gateway
with auth on and the operator key set, on
``POST /api/v1/capabilities/set_nft_rights/invoke``::

    session caller                        -> actor 0xa1…, actor_source "authenticated"
    operator, X-Wallet-Address: 0xc3…     -> actor 0xc3…, actor_source "authenticated"
    operator, body "wallet": 0xc3…        -> actor 0xc3…, actor_source "authenticated"

The record now says which. An identity the operator key named is recorded with
``actor_source: "operator"``; one derived from a session keeps
``"authenticated"``; a call with no identity keeps the label it had
(``agent_handoff``, ``agent``, ``unauthenticated``). Every entrance that can
thread an operator-named identity into the dispatcher is driven here: the
capability route; the chat entrances, through the context builder all four
share (driven on ``/chat``), the ReAct loop and the tool dispatcher; and
``/bridge/v1/action``.
"""

from __future__ import annotations

import json
import sys
from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest

pytest.importorskip("eth_account")
pytest.importorskip("eth_abi")

sys.path.insert(0, "tests")
from aiohttp.test_utils import TestClient, TestServer  # noqa: E402

from runtime.blockchain.services.service_dispatcher import ServiceDispatcher  # noqa: E402

SESSION = "0x" + "a1" * 20
NAMED = "0x" + "c3" * 20
KEY = "test-operator-key"


def _rights(token_id: int, holder: str) -> dict:
    return {"collection": "0xCollection", "token_id": token_id,
            "rights": {"commercial": {"granted": True, "holder": holder}}}


@pytest.fixture
def rows(monkeypatch):
    """Every audit row the dispatcher writes: the attestation of a settled
    action, the record of a refusal and the record of a broadcast."""
    seen: list[dict] = []

    async def _spy(self, action, service_name, params, result, *, actor="",
                   actor_source="", actor_claimed=""):
        seen.append({"action": action, "actor": actor,
                     "actor_source": actor_source, "actor_claimed": actor_claimed})

    for name in ("_attest_action", "_attest_refusal", "_record_broadcast"):
        monkeypatch.setattr(ServiceDispatcher, name, _spy)
    return seen


# ══════════════════════════════════════════════════════════════════════════
# 1. the capability route
# ══════════════════════════════════════════════════════════════════════════

async def _capability_client(tmp_path):
    from tests.test_gateway import _build_mock_server
    from tests.test_paymaster_sponsors_what_it_signs import _config

    config = _config(tmp_path)
    config["gateway"]["api_key"] = KEY
    server = _build_mock_server(config)
    server._app_attest = None
    server._security_backend = "noop"
    sessions = {"tok-a": {"address": SESSION}}
    server.wallet_sessions.get = lambda token, default=None: sessions.get(token, default)
    client = TestClient(TestServer(server.create_app()))
    await client.start_server()
    return client


async def _invoke(client, body: dict, headers: dict) -> dict:
    r = await client.post("/api/v1/capabilities/set_nft_rights/invoke",
                          json=body, headers=headers)
    assert r.status == 200, f"{r.status} {await r.text()}"
    inner = (await r.json())["result"]
    inner = json.loads(inner) if isinstance(inner, str) else inner
    assert inner["status"] == "ok", inner
    return inner["result"]


@pytest.mark.parametrize("label,headers,top", [
    ("X-Wallet-Address", {"Authorization": f"Bearer {KEY}", "X-Wallet-Address": NAMED}, {}),
    ("body wallet", {"Authorization": f"Bearer {KEY}"}, {"wallet": NAMED}),
])
async def test_an_identity_the_operator_named_is_recorded_as_the_operators(
        rows, tmp_path, label, headers, top):
    """THE LOAD-BEARING ASSERTION. The operator key named 0xc3…; the record
    names 0xc3… as the actor and says the operator named it."""
    client = await _capability_client(tmp_path)
    try:
        result = await _invoke(client, {"params": _rights(2, NAMED), **top}, headers)
    finally:
        await client.close()

    assert rows, f"nothing was recorded ({label})"
    row = rows[-1]
    assert row["actor"] == NAMED, row
    assert row["actor_source"] == "operator", (
        f"an identity the operator key named through the {label} is recorded "
        f"as if a session had established it: {row}")
    assert result["set_by"] == NAMED, result


async def test_a_session_is_still_recorded_as_authenticated(rows, tmp_path):
    client = await _capability_client(tmp_path)
    try:
        result = await _invoke(client, {"params": _rights(1, SESSION)},
                               {"X-Wallet-Session": "tok-a"})
    finally:
        await client.close()
    assert rows[-1]["actor"] == SESSION, rows[-1]
    assert rows[-1]["actor_source"] == "authenticated", rows[-1]
    assert result["set_by"] == SESSION, result


async def test_an_operator_request_that_presents_a_session_is_the_sessions(rows, tmp_path):
    """The session wins over anything the request names, the operator's too;
    so the identity is the session's and so is the label."""
    client = await _capability_client(tmp_path)
    try:
        await _invoke(client, {"params": _rights(3, SESSION), "wallet": NAMED},
                      {"Authorization": f"Bearer {KEY}", "X-Wallet-Session": "tok-a",
                       "X-Wallet-Address": NAMED})
    finally:
        await client.close()
    assert rows[-1]["actor"] == SESSION, rows[-1]
    assert rows[-1]["actor_source"] == "authenticated", rows[-1]


# ══════════════════════════════════════════════════════════════════════════
# 2. the chat entrances, the ReAct loop and the tool path
# ══════════════════════════════════════════════════════════════════════════

async def _chat_context(headers: dict, body: dict, *, link: str = "") -> dict:
    from tests.test_apple_session_auth_wall import _apple_session, _server

    server = _server()
    async with TestClient(TestServer(server.create_app())) as client:
        if headers.get("Authorization") == "Bearer <session>":
            token = await _apple_session(server, sub="chat-sub")
            if link:
                await server.apple_users.link_wallet("chat-sub", link)
            headers = {**headers, "Authorization": f"Bearer {token}"}
        r = await client.post("/chat", headers=headers, json=body)
        assert r.status == 200, await r.text()
        (context,), _ = server.react_loop.run.call_args
        return context.metadata["user_context"]


async def test_the_chat_entrances_say_who_named_the_identity():
    body = {"message": "hi", "session_id": "s-chat", "wallet": NAMED}

    operator = await _chat_context({"Authorization": f"Bearer {KEY}"}, body)
    assert operator["wallet_address"] == NAMED, operator
    assert operator.get("identity_source") == "operator", operator

    session = await _chat_context({"Authorization": "Bearer <session>"}, body, link=SESSION)
    assert session["wallet_address"] == SESSION, session
    assert session.get("identity_source") == "session", session

    anonymous = await _chat_context({}, body)
    assert anonymous["wallet_address"] == "", anonymous
    assert anonymous.get("identity_source", "") == "", anonymous


async def _loop_hands_the_dispatcher(tmp_path, user_context: dict) -> dict:
    """Run the real ReAct loop for one platform_action tool call and return the
    keyword arguments the tool received."""
    from test_route_sweep import SWEEP_CONFIG

    from runtime.models.model_interface import ModelResponse
    from runtime.react_loop import Message, ReActContext, ReActLoop

    loop = ReActLoop({**SWEEP_CONFIG, "memory_dir": str(tmp_path / "memory")})
    replies = [
        ModelResponse(tool_calls=[{"id": "c1", "function": {
            "name": "platform_action",
            "arguments": json.dumps({"action": "get_balance", "params": {}})}}]),
        ModelResponse(content="done"),
    ]

    async def complete(**kwargs):
        return replies.pop(0)

    seen: dict = {}

    async def platform_action(action: str, service: str | None = None,
                              params: dict | None = None, *,
                              caller_identity: str = "", caller_source: str = "") -> str:
        seen.update(action=action, caller_identity=caller_identity,
                    caller_source=caller_source)
        return json.dumps({"status": "ok"})

    loop.router.complete = complete
    loop.dispatcher._tools["platform_action"] = platform_action
    await loop.run(ReActContext(
        agent_name="neo", conversation=[Message(role="user", content="go")],
        metadata={"user_context": user_context}))
    assert seen, "the tool was not called"
    return seen


async def test_the_loop_hands_the_dispatcher_the_operators_label(tmp_path):
    seen = await _loop_hands_the_dispatcher(tmp_path, {
        "wallet_address": NAMED, "identity_source": "operator", "caller_kind": "operator"})
    assert seen["caller_identity"] == NAMED, seen
    assert seen["caller_source"] == "operator", (
        f"the loop threaded an identity the operator named without saying so: {seen}")


@pytest.mark.parametrize("user_context", [
    {"wallet_address": SESSION, "identity_source": "session", "caller_kind": "operator"},
    {"wallet_address": "", "caller_kind": "operator"},
])
async def test_the_loop_keeps_the_agent_channel_otherwise(tmp_path, user_context):
    seen = await _loop_hands_the_dispatcher(tmp_path, user_context)
    assert seen["caller_source"] == "agent", seen


async def test_the_tool_path_records_the_operators_label(rows):
    """The label the loop passes reaches the record through the real tool
    dispatcher and the real ServiceDispatcher."""
    from runtime.tools.dispatcher import ToolDispatcher

    d = ToolDispatcher.__new__(ToolDispatcher)
    d._tools = {"platform_action": ServiceDispatcher({}).execute}
    d._schemas = {}
    outcome = await d.dispatch(
        "platform_action", {"action": "set_nft_rights", "params": _rights(8, NAMED)},
        agent_name="neo", caller_identity=NAMED, caller_source="operator",
        caller_kind="operator")
    assert outcome.ok, outcome
    assert rows[-1]["actor"] == NAMED, rows[-1]
    assert rows[-1]["actor_source"] == "operator", rows[-1]


# ══════════════════════════════════════════════════════════════════════════
# 3. /bridge/v1/action
# ══════════════════════════════════════════════════════════════════════════

async def _bridge_row(rows, monkeypatch, headers: dict, *, session: bool) -> dict:
    from gateway.bridge import BridgeRoutes
    from tests.test_apple_session_auth_wall import _apple_session, _server

    captured: dict = {}
    original = BridgeRoutes.register_routes

    def _capture(self, app):
        captured["bridge"] = self
        return original(self, app)

    monkeypatch.setattr(BridgeRoutes, "register_routes", _capture)
    server = _server()
    async with TestClient(TestServer(server.create_app())) as client:
        if session:
            token = await _apple_session(server, sub="bridge-sub")
            await server.apple_users.link_wallet("bridge-sub", SESSION)
            headers = {**headers, "Authorization": f"Bearer {token}"}
        # The wallet a SIWE holder linked to the session id this request names.
        captured["bridge"]._linked_wallets["s-link"] = {
            "address": NAMED, "subject": NAMED, "verified": True}
        before = len(rows)
        r = await client.post("/bridge/v1/action", headers=headers, json={
            "action": "set_nft_rights", "params": _rights(21, NAMED),
            "session_id": "s-link"})
        assert r.status == 200, await r.text()
        assert len(rows) > before, "the bridge action wrote no record"
        return rows[-1]


async def test_the_bridge_records_a_link_the_operator_named_as_the_operators(rows, monkeypatch):
    row = await _bridge_row(rows, monkeypatch, {"Authorization": f"Bearer {KEY}"},
                            session=False)
    assert row["actor"] == NAMED, row
    assert row["actor_source"] == "operator", (
        f"the wallet linked to a session id the operator named is recorded as "
        f"if a session had established it: {row}")


async def test_the_bridge_still_records_a_session_as_authenticated(rows, monkeypatch):
    row = await _bridge_row(rows, monkeypatch, {}, session=True)
    assert row["actor"] == SESSION, row
    assert row["actor_source"] == "authenticated", row


# ══════════════════════════════════════════════════════════════════════════
# 4. the dispatcher — the facts render differently
# ══════════════════════════════════════════════════════════════════════════

@pytest.mark.parametrize("kwargs,expect_actor,expect_source", [
    ({"caller_identity": "0xS"}, "0xS", "authenticated"),
    ({"caller_identity": "0xS", "caller_source": "agent"}, "0xS", "authenticated"),
    ({"caller_identity": "0xN", "caller_source": "operator"}, "0xN", "operator"),
    ({"caller_source": "agent_handoff"}, "", "agent_handoff"),
    ({}, "", "unauthenticated"),
])
async def test_an_operator_named_identity_is_its_own_fact(rows, kwargs, expect_actor,
                                                          expect_source):
    """17-J's facts, plus the one this file adds: a session's identity and an
    identity the operator named no longer render identically."""
    d = ServiceDispatcher({})
    d._feed_engine = SimpleNamespace(ingest=AsyncMock())
    await d.execute("set_nft_rights", params=_rights(31, "0xH"), **kwargs)
    assert rows[-1]["actor"] == expect_actor, rows[-1]
    assert rows[-1]["actor_source"] == expect_source, rows[-1]


# ══════════════════════════════════════════════════════════════════════════
# 5. the binding — every bind says, and says nothing it was not told
# ══════════════════════════════════════════════════════════════════════════

async def test_a_bind_that_does_not_say_is_not_read_as_the_last_one():
    """The source is set by every bind: a later bind that does not say how it
    resolved the identity is recorded as not saying, never as the previous
    bind's "operator" — and nothing is "operator" when nothing is bound."""
    from gateway.security_gate import bind_request_security, bound_identity_source

    bind_request_security(identity=NAMED, identity_source="operator")
    assert bound_identity_source() == "operator"
    bind_request_security(identity=SESSION)
    assert bound_identity_source() == "", "a bind that did not say inherited the last answer"
    bind_request_security(identity="", identity_source="operator")
    assert bound_identity_source() == "", "a source was recorded with no identity bound"
    bind_request_security(identity=SESSION, identity_source="session")
    assert bound_identity_source() == "session"
    with pytest.raises(ValueError):
        bind_request_security(identity=SESSION, identity_source="authenticated")
