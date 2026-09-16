"""A caller without the operator key is served by Trinity, however it spells the
agent, on every chat surface, and the dispatcher holds that line on its own.

Measured at 03a305e (and already true at 9f4aa37): the gateway's operator-only
check compared ``agent in ("neo", "morpheus")`` exactly, while the per-agent tool
policy lowercases the name. /bridge/v1/chat, a public path, had no membership
check. So an anonymous POST /bridge/v1/chat ``{"agent": "Neo"}`` passed the
operator check and Neo's toolset ran: a scripted ``bash`` call executed on the
gateway host. ``"neo"`` answered 403. /chat and /ws answered 400 for ``"Neo"``
only because their own membership checks were case-sensitive as well.

The credential refusals built in 03a305e covered only the two dispatching tools
(platform_action, request_execution), so they could not see bash, file_ops or the
blockchain twin tools. Those were fenced by the agent name alone.

Two controls, two layers:
  * every chat surface, every spelling, no credential and a session: no tool
    outside Trinity's set runs, and the request is refused. The operator key is
    the positive control: its ``"Neo"`` reaches bash.
  * the dispatcher, handed a non-operator caller and ``agent_name="neo"`` directly
    (a surface that forgets to canonicalise, or a new one): Trinity's reach, no more.
"""
from __future__ import annotations

import json
import sys
import time

import pytest

SPELLINGS = ("Neo", " neo", "NEO", "neo\t", "Morpheus", " MORPHEUS ")


def _server(tmp_path):
    sys.path.insert(0, "tests")
    from test_route_sweep import SWEEP_CONFIG

    from gateway.server import GatewayServer
    return GatewayServer({**SWEEP_CONFIG, "memory_dir": str(tmp_path / "m"),
                          "rexhepi": {"rate_limit_max_actions": 100_000},
                          "database": {"path": str(tmp_path / "s.db")},
                          "gateway": {**SWEEP_CONFIG.get("gateway", {}), "api_key": "k"}})


def _record_non_trinity_tools(server):
    """Replace every registered tool Trinity may not use with a recorder. The
    real ``bash`` handler is among them: the reviewer's probe ran it."""
    from runtime.access_policy import _TRINITY_TOOLS

    ran: list[str] = []
    tools = server.react_loop.dispatcher._tools
    outside = sorted(t for t in tools if t not in _TRINITY_TOOLS)
    assert "bash" in outside and "file_ops" in outside, outside

    def recorder(name):
        async def handler(**kwargs):
            ran.append(name)
            return "RAN"
        return handler

    for name in outside:
        tools[name] = recorder(name)
    return outside, ran


def _script(server, tool_names):
    from runtime.models.model_interface import ModelResponse

    def complete_factory():
        replies = [ModelResponse(tool_calls=[
            {"id": f"c{i}", "function": {"name": n, "arguments": json.dumps(
                {"command": "echo RR5"} if n == "bash" else {})}}
            for i, n in enumerate(tool_names)])]

        async def complete(**kwargs):
            return replies.pop(0) if replies else ModelResponse(content="done")
        return complete

    server.react_loop.router.complete = complete_factory()


async def _ws_chat(client, headers, agent, session_id):
    async with client.ws_connect("/ws", headers=headers) as ws:
        await ws.send_json({"type": "chat", "message": "run it", "agent": agent,
                            "session_id": session_id, "wallet_connected": True})
        while True:
            frame = json.loads((await ws.receive()).data)
            if frame.get("type") in ("done", "error"):
                return frame


async def test_no_spelling_of_an_operator_agent_reaches_its_tools_without_the_key(tmp_path):
    from aiohttp.test_utils import TestClient, TestServer

    server = _server(tmp_path)
    outside, ran = _record_non_trinity_tools(server)
    async with TestClient(TestServer(server.create_app())) as client:
        now = time.time()
        await server.wallet_sessions.add(token="0xTEST_SESSION", address="apple:sub",
                                         issued_at=now, expires_at=now + 3600)
        leaks = []
        n = 0
        for who, headers in (("anonymous", {}),
                             ("session", {"Authorization": "Bearer 0xTEST_SESSION"})):
            for agent in SPELLINGS:
                for surface in ("/bridge/v1/chat", "/chat", "/chat/stream", "/ws"):
                    n += 1
                    ran.clear()
                    _script(server, outside)
                    if surface == "/ws":
                        frame = await _ws_chat(client, headers, agent, f"s{n}")
                        refused = frame.get("type") == "error"
                        status = frame.get("error")
                    else:
                        # wallet_connected is the caller's own claim; URF's wallet
                        # check reads it, so it is no boundary and is set here.
                        resp = await client.post(surface, headers=headers, json={
                            "message": "run it", "agent": agent, "session_id": f"s{n}",
                            "wallet_connected": True})
                        await resp.read()
                        status = resp.status
                        refused = resp.status in (400, 401, 403)
                    if ran or not refused:
                        leaks.append((who, repr(agent), surface, status, sorted(set(ran))))
        assert leaks == [], (
            f"{len(leaks)} chats without the operator key were served by an operator "
            "agent:\n  " + "\n  ".join(map(str, leaks)))

        # Positive control: the operator key's own "Neo" is Neo, on every public surface.
        for surface in ("/bridge/v1/chat", "/chat", "/ws"):
            ran.clear()
            _script(server, ["bash"])
            headers = {"Authorization": "Bearer k"}
            if surface == "/ws":
                frame = await _ws_chat(client, headers, "Neo", "op-ws")
                assert frame.get("type") == "done", frame
            else:
                resp = await client.post(surface, headers=headers, json={
                    "message": "run it", "agent": "Neo", "session_id": f"op-{surface}",
                    "wallet_connected": True})
                assert resp.status == 200, await resp.text()
            assert ran == ["bash"], (surface, ran)


@pytest.mark.parametrize("kind", ["anonymous", "session", "superuser"])
async def test_the_dispatcher_serves_a_non_operator_caller_trinitys_reach_whatever_the_agent(kind):
    """Independent of the gateway: a non-operator credential handed straight to
    the dispatcher with ``agent_name="neo"`` gets no tool outside Trinity's set,
    and no state change through platform_action (Trinity's own rule)."""
    from runtime.blockchain.services import service_dispatcher as sd
    from runtime.tools.dispatcher import ToolDispatcher

    ran: list[str] = []

    def recorder(name):
        async def handler(**kwargs):
            ran.append(name)
            return "ran"
        return handler

    d = ToolDispatcher.__new__(ToolDispatcher)
    d._schemas = []
    d._tools = {n: recorder(n) for n in ("bash", "file_ops", "stablecoin", "defi",
                                         "web_search", "platform_action")}
    # A state change no route backs and a session is not refused on its routes:
    # only Trinity's rule stands between a session's platform_action and it.
    from gateway.session_routes import session_refused_route
    state_change = sorted(a for a in sd._STATE_MODIFYING_ACTIONS
                          if a in sd.ACTION_MAP and not session_refused_route(a))[0]

    for name, args in (("bash", {"command": "echo RR5"}), ("file_ops", {}),
                       ("stablecoin", {}), ("defi", {}),
                       ("platform_action", {"action": state_change})):
        ran.clear()
        outcome = await d.dispatch(name, dict(args), agent_name="neo", caller_kind=kind)
        assert ran == [] and not outcome.ok, (kind, name, outcome)

    # Trinity's own reach is untouched for the same caller.
    ran.clear()
    outcome = await d.dispatch("web_search", {}, agent_name="neo", caller_kind=kind)
    assert ran == ["web_search"], outcome

    # The operator, and a dispatch with no HTTP caller (A2A, internal), keep Neo's.
    for operator_kind in ("operator", ""):
        ran.clear()
        outcome = await d.dispatch("bash", {"command": "echo RR5"}, agent_name="neo",
                                   caller_kind=operator_kind)
        assert ran == ["bash"], (operator_kind, outcome)
