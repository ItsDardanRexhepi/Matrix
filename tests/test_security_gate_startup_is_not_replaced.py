"""A security gate that did not come up at startup is not replaced by a lesser one.

THE DEFECT. The gateway builds the process-wide gate at startup, with the full
platform config and the database handle, loads its durable state, and starts the
loop that writes that state back. All three sat in one `try` whose `except`
only logged:

    self._morpheus = get_morpheus_security({**self.config, "db": db})
    await self._morpheus.initialize()
    self._security_flush_task = asyncio.create_task(self._security_flush_loop())

So a fault in any of them left the gateway serving, `/ready` answering 200, and
the process-wide gate unbuilt, or built and not loaded, with no loop writing its
state. The accessor builds the gate for whichever caller asks first, and the
next callers ask with NO config (every gated HTTP route) or with the platform
config and no database (the chat path, the hand-off). The first of them built a
gate without the database or the gate's own settings, every later caller
adopted it, and nothing said so. Its own two siblings in the same class already
refuse a production start when they cannot be built (the OTP services and the
App Attest verifier, H2); this one did not.

THE CLASS, AND THE AXES CLOSED HERE
  (a) construction raises            -> production refuses to start; elsewhere
                                        the gateway runs with the gate declared
                                        failed, and says so on /ready
  (b) loading durable state raises   -> the same
  (c) the write-back loop            -> started whenever a gate object exists,
                                        even one that did not finish loading
  (d) readiness                      -> /ready fails on (a), (b), and on a loop
                                        that is missing or has stopped
  (e) a later caller building a gate -> the seam hands out the host's gate and
                                        never builds another while a host has
                                        declared one; after a failed start it
                                        raises, and the callers refuse rather
                                        than run ungated (see (f) and (g))
  (e') the host adopting a gate someone else built earlier -> the host builds
                                        its own from its own config
  (f) the agent-tool boundary while the gate is not up -> every tool call is
                                        refused, and neither the installed
                                        backend's policy nor the public default
                                        is asked in the gate's place; with the
                                        gate up, or no host, the policy decides
  (g) the HTTP gate and the chat path's pre-action check while the gate is not
      up                             -> every request is refused, reads
                                        included, and the public fail-direction
                                        classifier is not asked in the gate's
                                        place; a gate that is up and faults on
                                        one call keeps that fail direction

The test doubles below stand in for the backend's accessor. Nothing here says
how the core decides anything; it pins what the host and the seam do when the
gate cannot be brought up.

§CC, measured: against the base tree (73f5441), given only the names this file
patches, each routed to the base's own accessor so the base behaved as it does,
7 failed and 1 passed. The one that passed is the healthy-start control. The
seven failed on the behaviour: no refusal in production, /ready 200 after a
failed start, no write-back loop, and the host adopting a gate built before it.
After the change, 8 passed. The same on the no-op backend and with the core
installed.

(f), measured against 117cf8f, the tree that made the seam refuse to hand out
a gate after a failed start: 3 failed and 1 passed. The one that
passed is the scope pin (a healthy start and no host still ask the policy).
The three failed on the behaviour: the boundary answered (True, '') after a
failed start and while the gate was starting, having asked the policy. After
the change, all 12 in this file passed, on both backends.

(g), measured against a966d5c, the tree whose documents said no other policy
decides in the gate's place after a failed start: 3 failed and 13 passed. The
one (g) test that passed is its scope pin (a gate that is up and faults keeps
the fail direction). The three failed on the behaviour: get_balance answered
allow=True with route observe-read-failopen after a failed start and while the
gate was starting, and the pre-action check approved a platform_action read,
each having asked the public classifier. After the change, all 16 in this file
passed, on both backends.
"""

from __future__ import annotations

import asyncio
import sys
from unittest.mock import AsyncMock

import pytest

sys.path.insert(0, "tests")

from aiohttp.test_utils import TestClient, TestServer  # noqa: E402

import runtime.security as seam  # noqa: E402
from gateway.server import GatewayServer  # noqa: E402
from test_route_sweep import SWEEP_CONFIG  # noqa: E402

PROD_CONFIG = {**SWEEP_CONFIG, "gateway": {**SWEEP_CONFIG.get("gateway", {}), "api_key": "test-key"}}


class _FakeGate:
    """A gate double: records what it was built with and what was asked of it."""

    mode = seam.MorpheusMode.OBSERVE

    def __init__(self, config, fail_initialize=False):
        self.config = config
        self._fail_initialize = fail_initialize
        self.persisted = 0

    async def initialize(self):
        if self._fail_initialize:
            raise RuntimeError("durable state could not be read")

    async def persist_security_state(self):
        self.persisted += 1
        return {}

    async def evaluate(self, action, context):
        return {"allow": True, "would_block": False, "route": "observe"}


class _Backend:
    """Stands in for the backend accessor the seam wraps. Counts every build."""

    def __init__(self, *, fail_construct=False, fail_initialize=False):
        self.builds: list[object] = []
        self.fail_construct = fail_construct
        self.fail_initialize = fail_initialize
        self._gate = None

    def get(self, config=None):
        if self._gate is None:
            self.builds.append(config)
            if self.fail_construct:
                raise ValueError("gate settings could not be parsed")
            self._gate = _FakeGate(config, fail_initialize=self.fail_initialize)
        return self._gate

    def reset(self):
        self._gate = None


@pytest.fixture(autouse=True)
def _release_the_host(monkeypatch):
    """A refused start never reaches the gateway's cleanup, so the declaration
    it made would outlive this test. Release it either way.

    The doubles here stand in for the whole backend, and every one of them
    names a caller the way the platform does: whether a backend does is
    tests/test_security_core_names_a_caller_as_the_platform_does.py's subject,
    not this file's."""
    from runtime.auth.identity import canonical_identity

    monkeypatch.setattr(seam, "_backend_canonical_identity", canonical_identity, raising=False)
    seam.release_security_gate()
    yield
    seam.release_security_gate()


def _install(monkeypatch, backend: _Backend):
    monkeypatch.setattr(seam, "_backend_get_gate", backend.get)
    monkeypatch.setattr(seam, "_backend_reset_gate", backend.reset)


def _server(config=SWEEP_CONFIG) -> GatewayServer:
    server = GatewayServer(config)
    server.react_loop.router.health_check = AsyncMock(return_value={"ollama": True})
    return server


class _InertService:
    def __init__(self, *args, **kwargs):
        pass


def _production_reaches_the_gate(monkeypatch):
    """Production refuses to construct for other reasons than the one under
    test: the H2 refusal for a missing backend, and whatever the installed
    backend's own OTP services and App Attest verifier require of a production
    deployment. Those have their own tests. Take them out of the way, so that
    what refuses here is the gate's start and nothing else."""
    monkeypatch.setenv("MATRIX_ENV", "production")
    monkeypatch.setattr(seam, "SECURITY_BACKEND", "morpheus_security", raising=False)
    monkeypatch.setattr(seam, "OTPService", _InertService)
    monkeypatch.setattr(seam, "OwnerVerification", _InertService)
    monkeypatch.setattr(seam, "get_app_attest_verifier", lambda *a, **k: _InertService())


# ── (a)/(b) production refuses to start ───────────────────────────────────


@pytest.mark.parametrize("fault", ["construct", "initialize"])
async def test_production_refuses_to_start_when_the_gate_does_not_come_up(monkeypatch, fault):
    _production_reaches_the_gate(monkeypatch)
    _install(monkeypatch, _Backend(fail_construct=fault == "construct",
                                   fail_initialize=fault == "initialize"))
    server = _server(PROD_CONFIG)

    test_server = TestServer(server.create_app())
    try:
        with pytest.raises(RuntimeError,
                           match=rf"security gate failed to {fault}.*Refusing to start"):
            await test_server.start_server()
    finally:
        await test_server.close()


# ── (a)-(e) elsewhere: honest, and no lesser gate ─────────────────────────


@pytest.mark.parametrize("fault", ["construct", "initialize"])
async def test_outside_production_the_gateway_is_not_ready_and_builds_no_second_gate(
        monkeypatch, fault):
    monkeypatch.delenv("MATRIX_ENV", raising=False)
    backend = _Backend(fail_construct=fault == "construct",
                       fail_initialize=fault == "initialize")
    _install(monkeypatch, backend)
    server = _server()

    async with TestClient(TestServer(server.create_app())) as client:
        ready = await client.get("/ready")
        body = await ready.json()
        assert ready.status == 503, body
        assert set(body) == {"ready", "ref"}, f"/ready says more than ready-or-not: {body}"
        health = await client.get("/health")
        assert health.status == 200, "liveness must not move on a readiness fault"

        # Every later caller asks the seam. None of them may build a gate.
        with pytest.raises(seam.SecurityGateUnavailable):
            seam.get_morpheus_security()
        with pytest.raises(seam.SecurityGateUnavailable):
            seam.get_morpheus_security(server.config)

        from gateway.security_gate import gate_action
        decision = await gate_action("send", {}, context={"wallet": "0x" + "b" * 40})
        assert decision["allow"] is False, decision

        from runtime.protocols.integration import ProtocolStack
        stack = ProtocolStack(server.config, "neo")
        assert stack._morpheus_security is None and stack._morpheus_init_failed

        from runtime.agents.handoff import AgentHandoff
        out = await AgentHandoff(server.config, None).escalate("send", {})
        assert out["approved"] is False, out

    assert len(backend.builds) == 1, (
        f"a gate was built {len(backend.builds)} times: after the host's start "
        "failed, a later caller built a lesser one")
    assert isinstance(backend.builds[0], dict) and "db" in backend.builds[0]


async def test_a_gate_that_did_not_finish_loading_still_has_its_writes_flushed(monkeypatch):
    """(c): the loop that writes the gate's state back runs whenever a gate
    object exists, so nothing it holds is stranded until a clean shutdown."""
    monkeypatch.delenv("MATRIX_ENV", raising=False)
    backend = _Backend(fail_initialize=True)
    _install(monkeypatch, backend)
    server = _server()

    async with TestClient(TestServer(server.create_app())):
        task = server._security_flush_task
        assert task is not None and not task.done(), "no write-back loop is running"
        gate = server._morpheus
        assert gate is not None
    assert gate.persisted >= 1, "the shutdown flush never reached the gate"


# ── (d) a stopped loop is not ready ───────────────────────────────────────


async def test_a_write_back_loop_that_has_stopped_is_not_ready(monkeypatch):
    monkeypatch.delenv("MATRIX_ENV", raising=False)
    _install(monkeypatch, _Backend())
    server = _server()

    async with TestClient(TestServer(server.create_app())) as client:
        assert (await client.get("/ready")).status == 200
        server._security_flush_task.cancel()
        await asyncio.sleep(0)
        assert (await client.get("/ready")).status == 503


# ── the healthy start, and the host builds its own gate ───────────────────


async def test_a_healthy_start_hands_every_caller_the_hosts_gate(monkeypatch):
    """CONTROL: the start that works keeps working, and the gate every later
    caller receives is the one built with the host's config and database."""
    monkeypatch.delenv("MATRIX_ENV", raising=False)
    backend = _Backend()
    _install(monkeypatch, backend)
    server = _server()

    async with TestClient(TestServer(server.create_app())) as client:
        assert (await client.get("/ready")).status == 200
        gate = server._morpheus
        assert gate is not None and "db" in gate.config
        assert seam.get_morpheus_security() is gate
        assert seam.get_morpheus_security({"a": "lesser config"}) is gate
        task = server._security_flush_task
        assert task is not None and not task.done()
    assert len(backend.builds) == 1


async def test_the_host_does_not_adopt_a_gate_built_before_it_started(monkeypatch):
    """(e'): the accessor builds for its first caller. A gate some earlier caller
    built with no config must not become the host's."""
    monkeypatch.delenv("MATRIX_ENV", raising=False)
    backend = _Backend()
    _install(monkeypatch, backend)
    early = seam.get_morpheus_security()          # no host yet: built with no config
    assert early.config is None

    server = _server()
    async with TestClient(TestServer(server.create_app())):
        assert server._morpheus is not early
        assert "db" in server._morpheus.config
        assert seam.get_morpheus_security() is server._morpheus


# ── (f) the tool boundary: nothing stands in for the gate ─────────────────


class _PolicyRecorder:
    """Stands in for the installed backend's per-agent policy; records each ask."""

    def __init__(self):
        self.asked: list[tuple] = []

    def __call__(self, agent, tool, action=None, context=None):
        self.asked.append((agent, tool, action, dict(context or {})))
        return {"allowed": True, "reason": ""}


def _dispatcher_with_stub():
    from runtime.tools.dispatcher import ToolDispatcher

    d = ToolDispatcher({})
    ran: list[str] = []

    async def stub(query: str = "", **extra):
        ran.append(query)
        return "ok"

    d._tools["web_search"] = stub
    return d, ran


@pytest.mark.parametrize("fault", ["construct", "initialize"])
async def test_after_a_failed_start_every_tool_call_is_refused_and_no_policy_stands_in(
        monkeypatch, fault):
    """(f): the per-agent tool boundary is a decision about who is calling, and
    it belongs with the gate. With the host's gate not up, it is refused on
    every tool call, and neither the backend's policy nor the public default is
    asked in its place: either would be a decision made without the gate."""
    monkeypatch.delenv("MATRIX_ENV", raising=False)
    backend = _Backend(fail_construct=fault == "construct",
                       fail_initialize=fault == "initialize")
    _install(monkeypatch, backend)
    policy = _PolicyRecorder()
    monkeypatch.setattr(seam, "_private_agent_access", policy)
    import runtime.access_policy as public_policy
    public_asked: list[tuple] = []
    monkeypatch.setattr(public_policy, "default_agent_access",
                        lambda *a, **k: public_asked.append(a) or (True, ""))
    server = _server()

    async with TestClient(TestServer(server.create_app())) as client:
        assert (await client.get("/ready")).status == 503
        allowed, reason = seam.agent_access_allowed(
            "trinity", "web_search", None, context={seam.CALLER_IDENTITY_KEY: "0x" + "b" * 40})
        assert allowed is False and reason, (allowed, reason)

        d, ran = _dispatcher_with_stub()
        for agent, kind in (("neo", "operator"), ("trinity", "session"), ("trinity", "")):
            out = await d.dispatch("web_search", {"query": "q"}, agent_name=agent,
                                   caller_identity="0x" + "b" * 40, caller_source="agent",
                                   caller_kind=kind)
            assert not out.ok and out.code == "denied", (agent, kind, out.model_text)
        assert ran == [], "a tool ran with the gate not up"

    assert policy.asked == [], f"the backend's policy was asked without the gate: {policy.asked}"
    assert public_asked == [], "the public default stood in for the gate"
    assert len(backend.builds) == 1, backend.builds


async def test_while_the_gate_is_starting_a_tool_call_is_refused(monkeypatch):
    """(f), the other phase: between the host declaring the gate and the gate
    finishing its load, the boundary refuses as well."""
    monkeypatch.delenv("MATRIX_ENV", raising=False)
    policy = _PolicyRecorder()
    monkeypatch.setattr(seam, "_private_agent_access", policy)
    seen: list[tuple] = []

    class _SlowGate(_FakeGate):
        async def initialize(self):
            seen.append(seam.agent_access_allowed("trinity", "web_search"))

    monkeypatch.setattr(seam, "_backend_get_gate", lambda config=None: _SlowGate(config))
    monkeypatch.setattr(seam, "_backend_reset_gate", lambda: None)
    await seam.start_security_gate({"db": object()})
    assert len(seen) == 1 and seen[0][0] is False, seen
    assert policy.asked == []
    assert seam.agent_access_allowed("trinity", "web_search")[0] is True
    assert len(policy.asked) == 1


class _ClassifierSpy:
    """Records every question put to the platform's public fail-direction
    classifier, and answers as the real one does."""

    def __init__(self, monkeypatch):
        import runtime.access_policy as public_policy

        self.asked: list[tuple] = []
        for name in ("could_move_value", "operation_could_move_value",
                     "dispatch_could_move_value"):
            real = getattr(public_policy, name)

            def spy(*args, _real=real, _name=name, **kwargs):
                self.asked.append((_name, args))
                return _real(*args, **kwargs)

            monkeypatch.setattr(public_policy, name, spy)


@pytest.mark.parametrize("fault", ["construct", "initialize"])
async def test_after_a_failed_start_a_gated_read_is_refused_and_no_classifier_stands_in(
        monkeypatch, fault):
    """(g): the HTTP gate and the chat path's pre-action check, after a failed
    start. A read is refused like everything else, and the platform's public
    fail-direction classifier is not asked in the gate's place: that would be a
    decision about the request made without the gate the host failed to bring
    up. Refusing a read is stricter than what either side of the gate ever did
    before; it lasts until a gateway starts with the gate up."""
    monkeypatch.delenv("MATRIX_ENV", raising=False)
    _install(monkeypatch, _Backend(fail_construct=fault == "construct",
                                   fail_initialize=fault == "initialize"))
    server = _server()

    async with TestClient(TestServer(server.create_app())) as client:
        assert (await client.get("/ready")).status == 503
        spy = _ClassifierSpy(monkeypatch)

        from gateway.security_gate import gate_action
        for action in ("get_balance", "get_price", "send"):
            decision = await gate_action(action, {}, context={"wallet": "0x" + "b" * 40},
                                         operation=("wallet", action))
            assert decision["allow"] is False, (action, decision)

        from runtime.protocols.integration import ProtocolStack
        stack = ProtocolStack(server.config, "trinity")
        for tool, args in (("platform_action", {"action": "get_balance"}),
                           ("platform_action", {"action": "send"})):
            verdict = await stack.pre_action(tool, args, {"wallet": "0x" + "b" * 40})
            assert verdict["approved"] is False, (tool, args, verdict)
            assert verdict["denial_reason"], verdict

        assert spy.asked == [], f"the public classifier stood in for the gate: {spy.asked}"


async def test_while_the_gate_is_starting_a_gated_read_is_refused(monkeypatch):
    """(g), the other phase: between the host declaring the gate and the gate
    finishing its load, the HTTP gate and the pre-action check refuse too."""
    monkeypatch.delenv("MATRIX_ENV", raising=False)
    seen: list = []
    spy = _ClassifierSpy(monkeypatch)

    class _SlowGate(_FakeGate):
        async def initialize(self):
            from gateway.security_gate import gate_action
            from runtime.protocols.integration import ProtocolStack

            seen.append(await gate_action("get_balance", {}, context={"wallet": "0x" + "b" * 40}))
            stack = ProtocolStack({}, "trinity")
            seen.append(await stack.pre_action("platform_action", {"action": "get_balance"}, {}))

    monkeypatch.setattr(seam, "_backend_get_gate", lambda config=None: _SlowGate(config))
    monkeypatch.setattr(seam, "_backend_reset_gate", lambda: None)
    await seam.start_security_gate({"db": object()})
    assert seen[0]["allow"] is False, seen
    assert seen[1]["approved"] is False, seen
    assert spy.asked == [], spy.asked


async def test_a_gate_that_is_up_and_faults_on_one_call_keeps_the_public_fail_direction(
        monkeypatch):
    """SCOPE PIN for (g): a gate that came up and then raises on one call is a
    different case, and it keeps the direction it always had: an action that
    could move value is refused, a clearly benign read proceeds."""
    monkeypatch.delenv("MATRIX_ENV", raising=False)

    class _FaultingGate(_FakeGate):
        async def evaluate(self, action, context):
            raise RuntimeError("transient fault")

    monkeypatch.setattr(seam, "_backend_get_gate", lambda config=None: _FaultingGate(config))
    monkeypatch.setattr(seam, "_backend_reset_gate", lambda: None)
    await seam.start_security_gate({"db": object()})
    assert seam.security_gate_state() == "up"

    from gateway.security_gate import gate_action
    assert (await gate_action("get_balance", {}, context={}))["allow"] is True
    assert (await gate_action("send", {}, context={}))["allow"] is False


async def test_with_the_gate_up_or_no_host_the_policy_decides(monkeypatch):
    """SCOPE PIN: a healthy start, and a process with no host (a script, the
    CLI), ask the policy exactly as before; nothing is refused wholesale."""
    monkeypatch.delenv("MATRIX_ENV", raising=False)
    policy = _PolicyRecorder()
    monkeypatch.setattr(seam, "_private_agent_access", policy)

    assert seam.agent_access_allowed("trinity", "web_search")[0] is True   # no host
    _install(monkeypatch, _Backend())
    server = _server()
    async with TestClient(TestServer(server.create_app())) as client:
        assert (await client.get("/ready")).status == 200
        d, ran = _dispatcher_with_stub()
        out = await d.dispatch("web_search", {"query": "q"}, agent_name="trinity",
                               caller_identity="0x" + "b" * 40, caller_source="agent",
                               caller_kind="session")
        assert out.ok, out.model_text
        assert ran == ["q"]
    assert len(policy.asked) == 3, policy.asked
