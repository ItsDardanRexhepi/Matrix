"""The agent-tool boundary is handed the caller the entry point bound.

THE DEFECT. `ToolDispatcher.dispatch` receives the caller's identity from the
entry point (`caller_identity`, bound from the session on /chat and the bridge,
never from the model's arguments) and then asked the security seam whether the
tool may run WITHOUT it:

    agent_access_allowed(agent_name, tool_name, action)                  # no context
    agent_access_allowed(self.NON_OPERATOR_AGENT, tool_name, action)     # no context

The seam's signature has taken a `context` all along, and the core behind it
decides on what that context says. A decision the core would make about THIS
caller could not be made, because the one frame that knew who was calling threw
the answer away one line before asking. A refusal that does not depend on who is
calling (one that applies to everybody) still bound, which is why nothing
noticed: the boundary was reached, only blind.

The same shape one hop further: Trinity's `request_execution` goes through
`AgentHandoff.as_tool -> escalate(action, params)` with no context, so the gate
evaluating the inner action (the send, the swap) could not see who asked for
it either.

WHAT THIS FILE PINS — in the platform's terms only. The dispatcher and the
hand-off hand the seam the caller's identity; what the core does with it is the
core's business and is not described here.

  1. Both boundary calls carry the bound identity, under the seam's one key.
  2. An identity only the MODEL wrote (in its arguments) never arrives there.
  3. A refusal the seam returns for this caller stops the call; the same tool
     still runs for another caller (the scope pin — nothing is refused wholesale).
  4. The hand-off's gate sees the same bound identity, and still not one the
     model wrote; Neo's execution keeps its declared agent-to-agent source.

§CC, measured: against the base tree (the commit "Merge
audit-remediation-2026-07: no personal address, local path or private detail in
the shipped files, and the compose stack passes the secrets the documents
name"), given only the key's name in the seam and nothing else, 8 failed and 2
passed. The two that passed are the
scope pins: the call with no bound caller, and the hand-off's gate not seeing an
identity the model wrote (at the base it saw no identity at all). After the
change, 10 passed. The same on the no-op backend and with the core installed.
"""

from __future__ import annotations

import json

import pytest

from runtime.security import CALLER_IDENTITY_KEY

CALLER = "0x" + "ab" * 20
OTHER = "0x" + "cd" * 20
FORGED = "0x" + "ee" * 20


class _Recorder:
    """Stands in for the seam's agent_access_allowed; records every context."""

    def __init__(self, refuse_for: str | None = None):
        self.calls: list[dict] = []
        self._refuse_for = refuse_for

    def __call__(self, agent, tool, action=None, context=None):
        self.calls.append({"agent": agent, "tool": tool, "action": action,
                           "context": context})
        if self._refuse_for and (context or {}).get(CALLER_IDENTITY_KEY) == self._refuse_for:
            return False, "refused for this caller"
        return True, ""


def _dispatcher_with_stub(monkeypatch, recorder):
    from runtime.tools import dispatcher as mod

    monkeypatch.setattr(mod, "agent_access_allowed", recorder)
    d = mod.ToolDispatcher({})
    ran: list[dict] = []

    async def stub(query: str = "", **extra):
        ran.append({"query": query, **extra})
        return "stub-result"

    d._tools["web_search"] = stub
    return d, ran


# ── 1. both boundary calls carry the bound identity ───────────────────────


async def test_the_agent_boundary_is_handed_the_bound_caller(monkeypatch):
    rec = _Recorder()
    d, _ = _dispatcher_with_stub(monkeypatch, rec)

    out = await d.dispatch("web_search", {"query": "q"}, agent_name="neo",
                           caller_identity=CALLER, caller_source="agent",
                           caller_kind="operator")

    assert out.ok, out.model_text
    assert len(rec.calls) == 1, rec.calls
    ctx = rec.calls[0]["context"]
    assert isinstance(ctx, dict), "the boundary was asked with no context at all"
    assert ctx.get(CALLER_IDENTITY_KEY) == CALLER, ctx


async def test_the_credential_boundary_is_handed_the_bound_caller_too(monkeypatch):
    """A caller without the operator key is checked twice — once as the agent it
    named, once as the agent its credential allows. Both calls must see it."""
    rec = _Recorder()
    d, _ = _dispatcher_with_stub(monkeypatch, rec)

    await d.dispatch("web_search", {"query": "q"}, agent_name="trinity",
                     caller_identity=CALLER, caller_source="agent",
                     caller_kind="session")

    assert len(rec.calls) == 2, rec.calls
    for call in rec.calls:
        assert (call["context"] or {}).get(CALLER_IDENTITY_KEY) == CALLER, call


# ── 2. an identity the model wrote never arrives ──────────────────────────


@pytest.mark.parametrize("forged_args", [
    {"caller_identity": FORGED},
    {CALLER_IDENTITY_KEY: FORGED},
    {"wallet": FORGED, "identity": FORGED, "address": FORGED},
    {"context": {CALLER_IDENTITY_KEY: FORGED}},
])
async def test_an_identity_only_the_model_wrote_never_reaches_the_boundary(
        monkeypatch, forged_args):
    rec = _Recorder()
    d, _ = _dispatcher_with_stub(monkeypatch, rec)

    await d.dispatch("web_search", {"query": "q", **forged_args}, agent_name="trinity",
                     caller_identity=CALLER, caller_source="agent", caller_kind="session")
    await d.dispatch("web_search", {"query": "q", **forged_args}, agent_name="trinity",
                     caller_identity="", caller_source="agent", caller_kind="anonymous")

    assert rec.calls, "the boundary was never asked"
    for call in rec.calls:
        ctx = call["context"] or {}
        assert FORGED not in json.dumps(ctx), f"a model-written identity arrived: {ctx}"
    bound = [c for c in rec.calls if (c["context"] or {}).get(CALLER_IDENTITY_KEY)]
    assert bound and all(c["context"][CALLER_IDENTITY_KEY] == CALLER for c in bound)


# ── 3. the seam's answer for this caller binds; nobody else is refused ────


async def test_a_refusal_for_this_caller_stops_the_call(monkeypatch):
    rec = _Recorder(refuse_for=CALLER)
    d, ran = _dispatcher_with_stub(monkeypatch, rec)

    for agent, kind in (("neo", "operator"), ("trinity", "session"), ("trinity", "anonymous")):
        out = await d.dispatch("web_search", {"query": "q"}, agent_name=agent,
                               caller_identity=CALLER, caller_source="agent",
                               caller_kind=kind)
        assert not out.ok and out.code == "denied", (agent, kind, out.model_text)
    assert ran == [], "the handler ran for a caller the seam refused"

    out = await d.dispatch("web_search", {"query": "q"}, agent_name="neo",
                           caller_identity=OTHER, caller_source="agent",
                           caller_kind="operator")
    assert out.ok, "another caller was refused: the scope is this caller only"
    assert len(ran) == 1


async def test_a_call_with_no_bound_caller_is_asked_without_one(monkeypatch):
    """SCOPE PIN: an internal dispatch (no HTTP request behind it) carries no
    identity, and none is invented for it."""
    rec = _Recorder()
    d, _ = _dispatcher_with_stub(monkeypatch, rec)

    out = await d.dispatch("web_search", {"query": "q"}, agent_name="neo")
    assert out.ok
    assert CALLER_IDENTITY_KEY not in (rec.calls[0]["context"] or {})


# ── 4. the hand-off's gate sees the same caller ───────────────────────────


class _RecordingGate:
    def __init__(self):
        self.contexts: list[dict] = []

    async def evaluate(self, request, context):
        self.contexts.append(dict(context))
        return {"allow": True}


class _RecordingExecutor:
    def __init__(self):
        self.calls: list[tuple] = []

    async def execute(self, *args, **kwargs):
        self.calls.append((args, kwargs))
        return {"status": "ok"}


def _handoff_dispatcher(monkeypatch):
    import runtime.security as seam
    from runtime.agents.handoff import AgentHandoff
    from runtime.tools import dispatcher as mod

    gate = _RecordingGate()
    monkeypatch.setattr(seam, "get_morpheus_security", lambda *a, **k: gate)
    monkeypatch.setattr(mod, "agent_access_allowed", _Recorder())
    executor = _RecordingExecutor()
    d = mod.ToolDispatcher({})
    handoff = AgentHandoff({}, executor)
    d._tools["request_execution"] = handoff.as_tool
    return d, gate, executor


async def test_the_handoff_gate_is_handed_the_bound_caller(monkeypatch):
    d, gate, executor = _handoff_dispatcher(monkeypatch)

    out = await d.dispatch("request_execution", {"action": "swap_tokens", "params": {}},
                           agent_name="trinity", caller_identity=CALLER,
                           caller_source="agent", caller_kind="operator")

    assert out.ok, out.model_text
    assert len(gate.contexts) == 1
    assert gate.contexts[0].get(CALLER_IDENTITY_KEY) == CALLER, gate.contexts[0]
    # Neo's execution keeps its declared agent-to-agent source; the identity is
    # handed to the gate, not asserted as the executor's actor.
    (args, kwargs), = executor.calls
    assert kwargs.get("caller_source") == "agent_handoff"
    assert "caller_identity" not in kwargs


async def test_the_handoff_gate_never_sees_an_identity_the_model_wrote(monkeypatch):
    d, gate, _ = _handoff_dispatcher(monkeypatch)

    await d.dispatch("request_execution",
                     {"action": "swap_tokens", "caller_identity": FORGED,
                      "params": {CALLER_IDENTITY_KEY: FORGED}, "wallet": FORGED},
                     agent_name="trinity", caller_identity="", caller_source="agent",
                     caller_kind="operator")

    assert len(gate.contexts) == 1
    assert FORGED not in json.dumps(gate.contexts[0]), gate.contexts[0]
