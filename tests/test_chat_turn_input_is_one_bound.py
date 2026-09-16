"""One chat turn, one set of input bounds — on all four entrances.

POST /chat, POST /chat/stream and GET /ws each checked the turn's input by
hand: a string message, at most 100 000 characters, an agent from the three
that exist. POST /bridge/v1/chat — public, anonymous, and the entrance the iOS
app ships against — checked none of it. A ~1 MiB message (the aiohttp body cap
is the only limit) went straight into the shared conversation store and was
copied into the model context on every later turn; a non-string message raised
AttributeError outside the JSON guard and answered 500; any agent name, of any
type, reached the ReAct loop. And /chat/stream and /ws coerced a non-string
message with ``str()`` where /chat refused it, so the same body was a turn on
two entrances and a 400 on another.

The bounds are now one helper (``GatewayServer._chat_turn_input``) that every
entrance calls before it resolves, claims or stores anything. Every test here
drives the real middlewares and handlers.
"""

from __future__ import annotations

import sys

import pytest

sys.path.insert(0, "tests")
from aiohttp.test_utils import TestClient, TestServer  # noqa: E402

from test_chat_entrances_one_posture import ENTRANCES, _drive, _server  # noqa: E402


def _stored_turns(server) -> list:
    return [m for conv in server.conversations.values() for m in conv]


@pytest.mark.parametrize("entrance", ENTRANCES)
async def test_a_message_over_the_cap_is_refused_before_it_is_stored_or_run(entrance):
    server = _server()
    async with TestClient(TestServer(server.create_app())) as client:
        status = await _drive(client, entrance,
                              {"message": "x" * 100_001, "session_id": f"big-{entrance}"})
        assert status == 400, (entrance, status)
        assert not server.react_loop.run.called, entrance
        assert all(len(str(m.content)) <= 100_000 for m in _stored_turns(server)), entrance
        stored = server.react_loop.memory.load_conversation(f"big-{entrance}")
        assert not stored, (entrance, [len(m["content"]) for m in stored])


@pytest.mark.parametrize("entrance", ENTRANCES)
async def test_a_message_at_the_cap_is_still_a_turn(entrance):
    server = _server()
    async with TestClient(TestServer(server.create_app())) as client:
        status = await _drive(client, entrance,
                              {"message": "x" * 100_000, "session_id": f"edge-{entrance}"})
        assert status == 200, (entrance, status)


@pytest.mark.parametrize("entrance", ENTRANCES)
@pytest.mark.parametrize("message", [12345, {"text": "hi"}, ["hi"], True])
async def test_a_non_string_message_is_a_400_everywhere_never_a_500_or_a_coerced_turn(entrance, message):
    server = _server()
    async with TestClient(TestServer(server.create_app())) as client:
        status = await _drive(client, entrance, {"message": message, "session_id": f"type-{entrance}"})
        assert status == 400, (entrance, message, status)
        assert not server.react_loop.run.called, (entrance, message)


@pytest.mark.parametrize("entrance", ENTRANCES)
@pytest.mark.parametrize("agent", ["smith", "", ["trinity"], {"name": "trinity"}, 7])
async def test_an_agent_that_does_not_exist_is_a_400_everywhere(entrance, agent):
    server = _server()
    async with TestClient(TestServer(server.create_app())) as client:
        status = await _drive(client, entrance,
                              {"message": "hi", "agent": agent, "session_id": f"agent-{entrance}"})
        assert status == 400, (entrance, agent, status)
        assert not server.react_loop.run.called, (entrance, agent)


@pytest.mark.parametrize("entrance", [e for e in ENTRANCES if e != "/ws"])
async def test_a_body_that_is_not_an_object_is_a_400_not_a_500(entrance):
    server = _server()
    async with TestClient(TestServer(server.create_app())) as client:
        resp = await client.post(entrance, json=["hi"])
        await resp.read()
        assert resp.status == 400, (entrance, resp.status)


@pytest.mark.parametrize("entrance", ENTRANCES)
async def test_the_conversation_key_is_bounded_whatever_the_caller_names(entrance):
    """Already true at 9f4aa37 on all four (``_resolve_session_id`` truncates);
    pinned so the bound cannot drift off one entrance again."""
    server = _server()
    async with TestClient(TestServer(server.create_app())) as client:
        status = await _drive(client, entrance, {"message": "hi", "session_id": "s" * 5000})
        assert status == 200, (entrance, status)
        assert server.conversations and all(len(k) <= 100 for k in server.conversations), entrance


async def test_a_ws_frame_that_is_not_an_object_is_answered_and_the_socket_lives():
    server = _server()
    async with TestClient(TestServer(server.create_app())) as client:
        async with client.ws_connect("/ws") as ws:
            await ws.send_json(["chat", "hi"])
            frame = await ws.receive_json(timeout=10)
            assert frame.get("type") == "error", frame
            await ws.send_json({"type": "chat", "message": "hi", "session_id": "after-bad-frame"})
            while True:
                frame = await ws.receive_json(timeout=10)
                if frame.get("type") in ("done", "error"):
                    break
            assert frame.get("type") == "done", frame
