"""An SDK example says which agent its calls reach, as the requests it sends show.

sdk/examples/blockchain_ops.py said "Each call except the conversion is a chat
message to Neo". MatrixClient.convert_contract is ablockchain(...), and
ablockchain is a chat message naming Neo, so all five calls are. On a gateway
with a key set, naming Neo takes the operator key (gateway/chat_agents.py), and
MatrixClient sends no key, so there every one of them is refused.

The example is run here with the client's transport replaced by a recorder:
nothing is sent, and the requests it would make are read.

What this cannot see: an example that builds its own HTTP requests rather than
going through MatrixClient.
"""

from __future__ import annotations

import asyncio
import importlib.util
import inspect
import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
EXAMPLE = ROOT / "sdk" / "examples" / "blockchain_ops.py"


def _requests(monkeypatch) -> list[tuple[str, dict]]:
    from sdk.client import MatrixClient

    sent: list[tuple[str, dict]] = []

    async def record(self, path, data):
        sent.append((path, dict(data)))
        return {"response": "", "agent": data.get("agent", ""), "tool_calls": []}

    monkeypatch.setattr(MatrixClient, "_post", record)
    spec = importlib.util.spec_from_file_location("sdk_example_under_test", EXAMPLE)
    module = importlib.util.module_from_spec(spec)
    monkeypatch.setitem(sys.modules, "sdk_example_under_test", module)
    spec.loader.exec_module(module)
    asyncio.run(module.main())
    return sent


def _operator_agents() -> set[str]:
    from gateway.chat_agents import OPERATOR_AGENTS
    return set(OPERATOR_AGENTS)


def test_the_client_sends_no_key():
    """The premise: MatrixClient has no way to present the operator key."""
    from sdk.client import MatrixClient
    assert "api_key" not in inspect.signature(MatrixClient.__init__).parameters
    source = inspect.getsource(MatrixClient._post)
    assert "Authorization" not in source and "api_key" not in source


def test_the_example_docstring_names_the_agent_every_call_reaches(monkeypatch, capsys):
    sent = _requests(monkeypatch)
    capsys.readouterr()
    assert sent, "the example sent nothing; the recorder is not in the path"
    agents = {data.get("agent") for path, data in sent if path == "/chat"}
    assert all(path == "/chat" for path, _ in sent), sent
    assert agents == {"neo"}, agents
    assert agents <= _operator_agents(), "Neo no longer takes the operator key; re-derive this"

    doc = " ".join((EXAMPLE.read_text(encoding="utf-8").split('"""')[1]).split()).lower()
    problems = []
    if re.search(r"except the \w+", doc):
        problems.append("the docstring excepts a call, and every call is a chat message to Neo")
    if not re.search(r"(?:every|all|each) (?:one of them|call|of them)[^.]*chat message to neo", doc):
        problems.append("the docstring does not say every call is a chat message to Neo")
    if "operator key" not in doc:
        problems.append("the docstring does not say that naming Neo takes the operator key, "
                        "which this client does not send")
    assert not problems, "\n".join(problems)
