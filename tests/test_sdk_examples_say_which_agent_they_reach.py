"""An SDK example says which agent its calls reach, as the requests it sends show.

sdk/examples/blockchain_ops.py said "Each call except the conversion is a chat
message to Neo". MatrixClient.convert_contract is ablockchain(...), and
ablockchain is a chat message naming Neo, so all five calls are. On a gateway
with a key set, naming Neo takes the operator key (gateway/chat_agents.py).
MatrixClient had no way to send one, and its astream_chat read an api_key
attribute nothing set; it now takes api_key and sends it as a bearer token on
every request, and the example passes MATRIX_API_KEY.

The example is run here with the client's transport replaced by a recorder:
nothing is sent, and the requests it would make are read. The client's own
headers are read through a stand-in aiohttp session.

What this cannot see: an example that builds its own HTTP requests rather than
going through MatrixClient.
"""

from __future__ import annotations

import asyncio
import importlib.util
import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
EXAMPLE = ROOT / "sdk" / "examples" / "blockchain_ops.py"


def _requests(monkeypatch) -> list[tuple[str, dict, str]]:
    from sdk.client import MatrixClient

    sent: list[tuple[str, dict, str]] = []

    async def record(self, path, data):
        sent.append((path, dict(data), self.api_key))
        return {"response": "", "agent": data.get("agent", ""), "tool_calls": []}

    monkeypatch.setattr(MatrixClient, "_post", record)
    monkeypatch.setenv("MATRIX_API_KEY", "the-operator-key")
    spec = importlib.util.spec_from_file_location("sdk_example_under_test", EXAMPLE)
    module = importlib.util.module_from_spec(spec)
    monkeypatch.setitem(sys.modules, "sdk_example_under_test", module)
    spec.loader.exec_module(module)
    asyncio.run(module.main())
    return sent


def _operator_agents() -> set[str]:
    from gateway.chat_agents import OPERATOR_AGENTS
    return set(OPERATOR_AGENTS)


class _Session:
    """A stand-in aiohttp.ClientSession that records each request's headers."""

    seen: list[dict] = []

    def __init__(self, *a, **k):
        pass

    async def __aenter__(self):
        return self

    async def __aexit__(self, *exc):
        return False

    def _answer(self, headers):
        _Session.seen.append(dict(headers or {}))

        class _Response:
            status = 200
            content = _Lines()

            async def __aenter__(self):
                return self

            async def __aexit__(self, *exc):
                return False

            async def json(self):
                return {"response": "", "status": "ok"}

            async def text(self):
                return ""

        return _Response()

    def post(self, url, json=None, headers=None):
        return self._answer(headers)

    def get(self, url, headers=None):
        return self._answer(headers)


class _Lines:
    def __aiter__(self):
        async def gen():
            yield b"event: done"
            yield b"data: {}"
        return gen()


def test_the_client_sends_the_operator_key_it_is_given(monkeypatch):
    """MatrixClient took no key, so it could not name Neo on a gateway with one
    set, and astream_chat read self.api_key, which nothing set (AttributeError)."""
    import aiohttp
    from sdk.client import MatrixClient

    monkeypatch.setattr(aiohttp, "ClientSession", _Session)

    async def drive(client):
        await client.achat("hi")
        await client.ahealth()
        async for _ in client.astream_chat("hi"):
            pass

    _Session.seen = []
    asyncio.run(drive(MatrixClient("http://gw", api_key="k")))
    assert len(_Session.seen) == 3
    assert all(h.get("Authorization") == "Bearer k" for h in _Session.seen), _Session.seen

    _Session.seen = []
    asyncio.run(drive(MatrixClient("http://gw")))
    assert len(_Session.seen) == 3
    assert not any("Authorization" in h for h in _Session.seen), _Session.seen


def test_the_example_docstring_names_the_agent_every_call_reaches(monkeypatch, capsys):
    sent = _requests(monkeypatch)
    capsys.readouterr()
    assert sent, "the example sent nothing; the recorder is not in the path"
    agents = {data.get("agent") for path, data, _key in sent if path == "/chat"}
    assert all(path == "/chat" for path, _data, _key in sent), sent
    assert agents == {"neo"}, agents
    assert agents <= _operator_agents(), "Neo no longer takes the operator key; re-derive this"
    assert {key for _p, _d, key in sent} == {"the-operator-key"}, (
        "the example does not pass MATRIX_API_KEY to the client")

    doc = " ".join((EXAMPLE.read_text(encoding="utf-8").split('"""')[1]).split()).lower()
    problems = []
    if re.search(r"except the \w+", doc):
        problems.append("the docstring excepts a call, and every call is a chat message to Neo")
    if not re.search(r"(?:every|all|each) (?:one of them|call|of them)[^.]*chat message to neo", doc):
        problems.append("the docstring does not say every call is a chat message to Neo")
    if "operator key" not in doc or "matrix_api_key" not in doc:
        problems.append("the docstring does not say that naming Neo takes the operator key "
                        "and that the example reads it from MATRIX_API_KEY")
    assert not problems, "\n".join(problems)
