"""Every model client sends every tool the platform registers, under its name.

The README's Model Support section says to use whichever model you want and
that `custom` reaches any endpoint that speaks the OpenAI format. The tool
dispatcher registers most tools flat ({"name", "description", "parameters"})
and three (platform_action, request_execution and security_audit) in the
function-calling shape ({"type": "function", "function": {...}}). The OpenAI
client, which every OpenAI-compatible provider and `custom` use, and the
Gemini and NVIDIA clients read t["name"], so every request that carried tools
failed with KeyError 'name' before anything was sent, and the gateway answered
503; the Ollama client read tool.get("name", "") and sent those three tools
with an empty name. Only the Anthropic client read both shapes.

Each client in runtime/models is run here with the dispatcher's own tool list
and a stand-in HTTP session that records the request body instead of sending
it; the tools in the body must be the registered tools, each under its name.
"""

from __future__ import annotations

import asyncio
import importlib
import inspect
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent
_NOT_CLIENTS = {"model_interface", "router", "catalog", "providers", "task_classifier"}


class _Sent(Exception):
    pass


class _RecordingSession:
    """Stands in for aiohttp.ClientSession: keeps the JSON body, sends nothing."""

    bodies: list = []

    def __init__(self, *args, **kwargs):
        pass

    async def __aenter__(self):
        return self

    async def __aexit__(self, *exc):
        return False

    def post(self, url, json=None, **kwargs):
        _RecordingSession.bodies.append(json)
        raise _Sent(url)


def _clients():
    from runtime.models.model_interface import ModelInterface
    found = []
    for path in sorted((ROOT / "runtime" / "models").glob("*.py")):
        if path.stem.startswith("_") or path.stem in _NOT_CLIENTS:
            continue
        module = importlib.import_module(f"runtime.models.{path.stem}")
        for _name, cls in inspect.getmembers(module, inspect.isclass):
            if (issubclass(cls, ModelInterface) and cls is not ModelInterface
                    and cls.__module__ == module.__name__ and not inspect.isabstract(cls)):
                found.append((module, cls))
    return found


def _registered_tools(tmp_path):
    from runtime.tools.dispatcher import ToolDispatcher
    dispatcher = ToolDispatcher({"memory_dir": str(tmp_path),
                                 "database": {"path": str(tmp_path / "p.db")}})
    return dispatcher.get_tool_schemas()


def _name_of(schema: dict) -> str:
    return schema["function"]["name"] if isinstance(schema.get("function"), dict) else schema["name"]


def _sent_names(body: dict) -> list[str]:
    names = []
    for tool in body.get("tools") or []:
        if "function_declarations" in tool:
            names += [d.get("name") for d in tool["function_declarations"]]
        elif isinstance(tool.get("function"), dict):
            names.append(tool["function"].get("name"))
        else:
            names.append(tool.get("name"))
    return names


def test_the_premise_both_shapes_are_registered(tmp_path):
    tools = _registered_tools(tmp_path)
    nested = [t for t in tools if isinstance(t.get("function"), dict)]
    flat = [t for t in tools if "name" in t]
    assert nested and flat, "the dispatcher registers one shape only now; re-derive this check"


def test_the_harness_finds_every_client():
    names = {cls.__name__ for _m, cls in _clients()}
    assert {"OpenAIClient", "AnthropicClient", "OllamaClient", "GeminiClient",
            "NVIDIAClient"} <= names, names


@pytest.mark.parametrize("client_cls", [cls for _m, cls in _clients()], ids=lambda c: c.__name__)
def test_every_client_sends_every_registered_tool_under_its_name(client_cls, tmp_path, monkeypatch):
    from runtime.react_loop import Message
    tools = _registered_tools(tmp_path)
    expected = [_name_of(t) for t in tools]
    assert all(expected)

    _RecordingSession.bodies = []
    monkeypatch.setattr("aiohttp.ClientSession", _RecordingSession)
    client = client_cls({"api_key": "k", "model": "m", "base_url": "http://127.0.0.1:9"})
    try:
        asyncio.run(client.complete([Message(role="user", content="hello")], tools=tools))
    except Exception:
        pass  # the stand-in session refuses to send; the body is what is read
    assert _RecordingSession.bodies, f"{client_cls.__name__} built no request"
    for body in _RecordingSession.bodies:
        assert _sent_names(body) == expected, (
            f"{client_cls.__name__} sent the tools as {_sent_names(body)}")
