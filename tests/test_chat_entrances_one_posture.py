"""The four chat entrances are one chat — same wall, same identity, same turn.

POST /chat, POST /chat/stream, GET /ws and POST /bridge/v1/chat all run the
same flow: resolve the conversation, build a ReActContext, hand it to the
ReAct loop. What the loop reads from that context is not decoration:

  * ``user_context["wallet_address"]`` is the ``caller_identity`` the tool
    dispatcher injects and binds for the sponsorship cap
    (react_loop.py → dispatcher.dispatch → set_caller_identity), and the
    identity the seam's beneficiary check compares a platform-signed action
    against (integration.py pre_action).
  * ``apple_id`` / ``app_attest`` are what the Morpheus gate attributes and
    verifies a tool call with.
  * ``wallet_connected`` / ``network`` / ``balance`` / ``jurisdiction`` feed
    the Rexhepi gate's safety and compliance verdicts.

Before this file, each entrance built that dict by hand and no two agreed:
/chat took the wallet, apple_id and every gate input from the request body —
on a public route, so anyone could name any wallet — while /ws bound no
identity at all, /chat/stream bound none and still took two gate inputs from
the body, and the bridge took a linked wallet from whoever named its session
id. /chat/stream was also the one entrance left behind the operator key, so the
gateway's own public web chat page (served at GET /chat, which calls
/chat/stream) answered 401 on every gateway with a key configured. And the
client's per-turn ``context`` reached the model on two transports and was
dropped on the other two.

Every test here drives the real middlewares and handlers.
"""

from __future__ import annotations

import json
import re
import sys
import tempfile
import time
from types import SimpleNamespace
from unittest.mock import AsyncMock

import aiohttp
import pytest

sys.path.insert(0, "tests")
from aiohttp.test_utils import TestClient, TestServer  # noqa: E402

from gateway.server import GatewayServer  # noqa: E402
from test_route_sweep import SWEEP_CONFIG  # noqa: E402

KEY = "test-operator-key"
ENTRANCES = ("/chat", "/chat/stream", "/ws", "/bridge/v1/chat")
LINKED = "0x" + "1" * 40
VICTIM = "0x" + "d" * 40


def _server(api_key: str = "", stub: str = "run") -> GatewayServer:
    scratch = tempfile.mkdtemp(prefix="opnmatrx-entrances-")
    config = {**SWEEP_CONFIG, "memory_dir": scratch,
              "database": {**SWEEP_CONFIG.get("database", {}), "path": f"{scratch}/e.db"},
              "gateway": {**SWEEP_CONFIG.get("gateway", {}), "api_key": api_key}}
    server = GatewayServer(config)
    if stub == "run":
        server.react_loop.run = AsyncMock(
            return_value=SimpleNamespace(response="ok", tool_calls=[], provider="stub"))
    else:
        server.react_loop.router.complete = AsyncMock(
            return_value=SimpleNamespace(content="ok", tool_calls=[], provider="stub"))
    return server


async def _session(server: GatewayServer, subject: str) -> str:
    token = f"tok-{subject}"
    now = time.time()
    await server.wallet_sessions.add(token=token, address=subject, issued_at=now, expires_at=now + 3600)
    return token


def _bearer(token: str) -> dict:
    return {"Authorization": f"Bearer {token}"}


async def _drive(client: TestClient, entrance: str, body: dict, headers: dict | None = None) -> int:
    """One chat turn through *entrance*; the HTTP status it answered (a WS
    turn that completes counts as 200, an error frame as its status or 400)."""
    headers = headers or {}
    if entrance == "/ws":
        try:
            ws = await client.ws_connect("/ws", headers=headers)
        except aiohttp.WSServerHandshakeError as exc:
            return exc.status
        async with ws:
            await ws.send_json({"type": "chat", **body})
            while True:
                frame = await ws.receive_json(timeout=15)
                if frame.get("type") == "done":
                    return 200
                if frame.get("type") == "error":
                    return int(frame.get("status") or 400)
    resp = await client.post(entrance, json=body, headers=headers)
    await resp.read()
    return resp.status


def _user_context(server: GatewayServer) -> dict:
    (context,), _ = server.react_loop.run.call_args
    return context.metadata["user_context"]


# ── identity: derived from the presented session, the same on every entrance ─

@pytest.mark.parametrize("entrance", ENTRANCES)
async def test_every_entrance_binds_the_session_identity_the_gate_and_dispatcher_read(entrance):
    server = _server()
    async with TestClient(TestServer(server.create_app())) as client:
        token = await _session(server, "apple:sub-1")
        await server.apple_users.link_wallet("sub-1", LINKED)
        status = await _drive(client, entrance,
                              {"message": "hi", "session_id": f"conv-{entrance}"}, _bearer(token))
        assert status == 200, (entrance, status)
        ctx = _user_context(server)
        assert ctx.get("wallet_address") == LINKED, (entrance, ctx)
        assert ctx.get("apple_id") == "sub-1", (entrance, ctx)
        assert ctx.get("wallet_connected") is True, (entrance, ctx)


@pytest.mark.parametrize("entrance", ENTRANCES)
async def test_every_entrance_carries_the_app_attest_assertion_to_the_gate(entrance):
    """The assertion is evidence the gate verifies, not a claim it believes."""
    server = _server()
    async with TestClient(TestServer(server.create_app())) as client:
        assertion = {"key_id": "k1", "assertion": "b64", "client_data": "c"}
        status = await _drive(client, entrance,
                              {"message": "hi", "session_id": "conv-attest", "app_attest": assertion})
        assert status == 200, (entrance, status)
        assert _user_context(server).get("app_attest") == assertion, entrance


# ── §EE: an anonymous body describes nothing the gate decides on ─────────────

SELF_DESCRIPTION = {
    "wallet": VICTIM, "wallet_address": VICTIM, "apple_id": "victim-sub",
    "wallet_connected": True, "network": "ethereum", "balance": 10 ** 9,
    "jurisdiction": "CH", "total_transactions": 500,
}


@pytest.mark.parametrize("entrance", ENTRANCES)
async def test_an_anonymous_body_cannot_name_the_identity_or_the_gate_inputs(entrance):
    server = _server(api_key=KEY)
    async with TestClient(TestServer(server.create_app())) as client:
        status = await _drive(client, entrance,
                              {"message": "hi", "session_id": "conv-anon", **SELF_DESCRIPTION})
        assert status == 200, (entrance, status)
        ctx = _user_context(server)
        assert not ctx.get("wallet_address"), (entrance, ctx)
        assert not ctx.get("apple_id"), (entrance, ctx)
        for key in ("wallet_connected", "network", "balance", "jurisdiction", "total_transactions"):
            assert ctx.get(key) != SELF_DESCRIPTION[key], (entrance, key, ctx)


@pytest.mark.parametrize("entrance", ENTRANCES)
async def test_a_session_body_cannot_override_the_session_identity(entrance):
    server = _server(api_key=KEY)
    async with TestClient(TestServer(server.create_app())) as client:
        token = await _session(server, "apple:real")
        status = await _drive(client, entrance,
                              {"message": "hi", "session_id": "conv-s", **SELF_DESCRIPTION}, _bearer(token))
        assert status == 200, (entrance, status)
        ctx = _user_context(server)
        assert ctx.get("wallet_address") == "apple:real", (entrance, ctx)
        assert ctx.get("apple_id") == "real", (entrance, ctx)
        assert ctx.get("jurisdiction") != "CH" and ctx.get("balance") != 10 ** 9, (entrance, ctx)


async def test_the_operator_still_speaks_for_the_user_it_integrates():
    """The operator key opens every route; an operator integration naming the
    user it acts for is the trusted flow the body fields were for."""
    server = _server(api_key=KEY)
    async with TestClient(TestServer(server.create_app())) as client:
        status = await _drive(client, "/chat",
                              {"message": "hi", "session_id": "conv-op", **SELF_DESCRIPTION}, _bearer(KEY))
        assert status == 200
        ctx = _user_context(server)
        assert ctx["wallet_address"] == VICTIM
        assert ctx["jurisdiction"] == "CH"


async def test_an_anonymous_bridge_caller_does_not_inherit_a_wallet_linked_to_the_session_id_it_names():
    server = _server(api_key=KEY)
    async with TestClient(TestServer(server.create_app())) as client:
        siwe = await _session(server, LINKED)
        r = await client.post("/bridge/v1/wallet/link", headers={"X-Wallet-Session": siwe},
                              json={"session_id": "conv-linked"})
        assert r.status == 200, await r.text()
        status = await _drive(client, "/bridge/v1/chat", {"message": "hi", "session_id": "conv-linked"})
        assert status == 200
        assert _user_context(server).get("wallet_address") != LINKED


async def test_the_body_wallet_never_reaches_the_dispatcher_as_the_caller():
    """The effect, not the dict: drive a real tool call through the ReAct loop
    and read the caller identity the dispatcher was handed — the value the
    sponsorship cap meters and a service decides ownership on."""
    from runtime.tools.dispatcher import ToolOutcome

    server = _server(api_key=KEY, stub="router")
    server.react_loop._get_protocol_stack = lambda *a, **k: None   # isolate the identity path
    tool_turn = SimpleNamespace(
        content="", provider="stub",
        tool_calls=[{"id": "t1", "type": "function",
                     "function": {"name": "platform_action", "arguments": json.dumps({"action": "noop"})}}])
    final_turn = SimpleNamespace(content="done", tool_calls=[], provider="stub")
    server.react_loop.router.complete = AsyncMock(side_effect=[tool_turn, final_turn])
    server.react_loop.dispatcher.dispatch = AsyncMock(return_value=ToolOutcome.success("ok"))
    async with TestClient(TestServer(server.create_app())) as client:
        r = await client.post("/chat", json={"message": "send it", "session_id": "conv-e", "wallet": VICTIM})
        assert r.status == 200, await r.text()
    assert server.react_loop.dispatcher.dispatch.await_count == 1, "the tool call never reached the dispatcher"
    assert server.react_loop.dispatcher.dispatch.call_args.kwargs.get("caller_identity") != VICTIM


async def test_a_body_wallet_no_longer_satisfies_the_beneficiary_check_on_public_chat():
    """The seam refuses a platform-signed action pointed at an address other
    than the caller's bound identity. With the identity taken from the body of
    a public route, naming the target as your own ``wallet`` passed that check.
    Driven through the real ProtocolStack.pre_action; its decision is read."""
    server = _server(api_key=KEY, stub="router")
    stack = server.react_loop._get_protocol_stack("trinity", "conv-benef")
    decisions: list[dict] = []
    real_pre_action = stack.pre_action

    async def recording_pre_action(tool_name, arguments, context):
        decision = await real_pre_action(tool_name, arguments, context)
        decisions.append(decision)
        return decision

    stack.pre_action = recording_pre_action
    supply = SimpleNamespace(
        content="", provider="stub",
        tool_calls=[{"id": "t1", "type": "function", "function": {
            "name": "defi",
            "arguments": json.dumps({"action": "supply", "asset": "USDC", "amount": 1, "onBehalfOf": VICTIM})}}])
    server.react_loop.router.complete = AsyncMock(
        side_effect=[supply, SimpleNamespace(content="done", tool_calls=[], provider="stub")])
    async with TestClient(TestServer(server.create_app())) as client:
        r = await client.post("/chat", json={"message": "supply for me", "session_id": "conv-benef",
                                             "wallet": VICTIM})
        assert r.status == 200, await r.text()
    assert decisions, "the tool call never reached the seam"
    assert decisions[0]["approved"] is False
    assert "no identity is bound" in (decisions[0]["denial_reason"] or ""), decisions[0]


# ── one wall: every chat entrance answers an anonymous caller the same way ───

@pytest.mark.parametrize("entrance", ENTRANCES)
async def test_every_chat_entrance_admits_the_anonymous_caller_the_others_admit(entrance):
    server = _server(api_key=KEY)
    async with TestClient(TestServer(server.create_app())) as client:
        status = await _drive(client, entrance, {"message": "hi", "session_id": "conv-wall"})
        assert status == 200, (entrance, status)


def test_every_route_that_runs_the_chat_flow_is_a_named_entrance_and_public():
    """Derived from the router, not from the list: a fifth route bound to a chat
    handler that nobody added to CHAT_ENTRANCES fails here."""
    from gateway.server import CHAT_ENTRANCES

    server = _server(api_key=KEY)
    app = server.create_app()
    chat_handlers = {"handle_chat", "handle_chat_stream", "handle_websocket", "chat"}
    bound = set()
    for route in app.router.routes():
        handler = getattr(route.handler, "__func__", route.handler)
        owner = getattr(route.handler, "__self__", None)
        name = getattr(handler, "__name__", "")
        if name in chat_handlers and type(owner).__name__ in ("GatewayServer", "BridgeRoutes"):
            bound.add(route.resource.canonical)
    assert bound == set(CHAT_ENTRANCES), bound
    assert set(CHAT_ENTRANCES) <= server._public_paths


async def test_the_public_web_chat_page_can_reach_every_chat_endpoint_it_calls():
    """GET /chat is public and serves web/index.html; the page's chat calls
    are derived from the page as served, then driven anonymously."""
    server = _server(api_key=KEY)
    async with TestClient(TestServer(server.create_app())) as client:
        page = await client.get("/chat")
        assert page.status == 200
        html = await page.text()
        called = set(re.findall(r"fetch\(`\$\{baseUrl\(\)\}(/[A-Za-z0-9_/\-]+)", html))
        chat_calls = {p for p in called if p.startswith("/chat")}
        assert chat_calls, "the page no longer calls a chat endpoint — re-derive this test"
        for path in sorted(chat_calls):
            status = await _drive(client, path, {"message": "hi", "session_id": "web-page-conv"})
            assert status != 401, (path, status)


# ── the client's per-turn context: decided once, for all four ────────────────

MARKER = "CTX-7f3a respond in Albanian"


def _model_messages(server: GatewayServer) -> list:
    return list(server.react_loop.router.complete.call_args.kwargs["messages"])


@pytest.mark.parametrize("entrance", ENTRANCES)
async def test_every_entrance_hands_the_clients_turn_context_to_the_model(entrance):
    server = _server(stub="router")
    async with TestClient(TestServer(server.create_app())) as client:
        status = await _drive(client, entrance,
                              {"message": "hello", "session_id": f"ctx-{entrance}", "context": MARKER})
        assert status == 200, (entrance, status)
        carrying = [m for m in _model_messages(server) if MARKER in str(getattr(m, "content", ""))]
        assert carrying, f"{entrance} dropped the client's per-turn context"


@pytest.mark.parametrize("entrance", ENTRANCES)
async def test_the_clients_context_never_rewrites_the_platforms_instructions(entrance):
    """Caller-authored text travels in its own message, never spliced into the
    platform's instruction message — so no caller input changes that message —
    under a label the SERVER writes, identically on every entrance. And it is
    per-turn: it is not written into the stored conversation."""
    server = _server(stub="router")
    agent_prompt = server.react_loop.get_agent_prompt("trinity")
    assert agent_prompt, "the trinity prompt must load for this property to mean anything"
    async with TestClient(TestServer(server.create_app())) as client:
        sid = f"fence-{entrance}"
        status = await _drive(client, entrance, {"message": "hello", "session_id": sid, "context": MARKER})
        assert status == 200, (entrance, status)
        messages = _model_messages(server)
        carrying = [m for m in messages if MARKER in str(getattr(m, "content", ""))]
        assert len(carrying) == 1, (entrance, carrying)
        assert agent_prompt[:200] not in str(carrying[0].content), (
            f"{entrance}: the client's text was spliced into the platform's instruction message")
        platform = [m for m in messages if agent_prompt[:200] in str(getattr(m, "content", ""))]
        assert platform and all(MARKER not in str(m.content) for m in platform), entrance

        from gateway.server import CLIENT_CONTEXT_FENCE
        assert str(carrying[0].content).startswith(CLIENT_CONTEXT_FENCE), (entrance, carrying[0].content)
        stored = server.conversations.get(sid, [])
        assert stored and all(MARKER not in str(m.content) for m in stored), (entrance, stored)
