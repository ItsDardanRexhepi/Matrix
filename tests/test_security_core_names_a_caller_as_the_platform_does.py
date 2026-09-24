"""The security core names a caller the way the platform does, or its gate does not start.

THE DEFECT. The platform names a caller in one spelling (runtime/auth/identity.py:
a wallet address as `0x` and its digits in lower case, anything else as given)
and hands the security seam that spelling: the wallet bound for a gated HTTP
action, the caller at the agent-tool boundary and at the hand-off's gate. Before
that rule, a session carried the address as it was sent to /auth/verify, and a
sign-in usually sends the EIP-55 checksum form, so the seam was handed whatever
spelling the session carried. Whatever the core holds about a caller, it is
handed the platform's spelling of that caller; if the core named a caller by
any other rule, a record under another spelling of the same wallet would match
no caller the platform hands it. So folding every spelling into one on the
platform's side, with nothing checked about the core's rule, would turn such a
record into one that binds for nobody.

THE RULE. The core names a caller by the same rule, exported from the core as
`canonical_identity`. Before the gateway starts the gate, the seam checks that
the rule the installed backend exports gives the platform's answer for a set of
spellings. A backend that exports no rule, or another one, is not started: the
start fails at stage "identity" and is handled like any other failed start. In
production the gateway refuses to start; elsewhere it runs not ready, and every
request the gate would decide is refused. How the core applies the rule to what
it holds is the core's, and nothing here says what it holds.

THE CLASS, AND THE AXES CLOSED HERE
  (a) a backend that exports no rule                   -> not started
  (b) a rule that leaves some spelling of an address as it came
                                                       -> not started
  (c) a rule that also folds what is not an address (merging two callers whose
      ids differ only in case)                         -> not started
  (d) a rule that raises                               -> not started
  (e) production                                       -> refuses to start and
                                                          names the cause
  (e') the operator's doctor check                     -> does not call such a
                                                          core READY
  (f) SCOPE PIN: a backend that exports the platform's rule starts, and the
      no-op backend, which records nothing about any caller, uses the
      platform's rule

§CC, measured: against the tree at the commit "While the security gate is not
up, nothing decides a request in its place", the tree before this rule, with
this file added: 12 failed and 2 passed on the no-op backend; with the core
installed 11 failed, 2 passed and 1 skipped (the no-op test does not apply
there). The two that passed are the scope pin's healthy start and the
production companion check that a matching rule still starts. The rest failed
on the behaviour: every stand-in backend was started whatever rule it exported,
/ready answered 200, production started, the doctor check called each of them
READY, and the no-op backend exported no rule. After the change, 14 passed on
the no-op backend, and 13 passed and 1 skipped with the core installed.

An installed core that does not export the rule is refused like the stand-ins
above, so with such a core every test that starts a gateway and needs its gate
up fails with the cause "failed to name a caller the way the platform does".
That is this check doing its job: the platform's one spelling and a core that
names callers otherwise must not run together.
"""

from __future__ import annotations

import sys
from unittest.mock import AsyncMock

import pytest

sys.path.insert(0, "tests")

from aiohttp.test_utils import TestClient, TestServer  # noqa: E402

import runtime.security as seam  # noqa: E402
from gateway.server import GatewayServer  # noqa: E402
from runtime.auth.identity import canonical_identity  # noqa: E402
from test_route_sweep import SWEEP_CONFIG  # noqa: E402

PROD_CONFIG = {**SWEEP_CONFIG, "gateway": {**SWEEP_CONFIG.get("gateway", {}), "api_key": "test-key"}}


class _Gate:
    mode = seam.MorpheusMode.OBSERVE

    def __init__(self, config):
        self.config = config

    async def initialize(self):
        return None

    async def persist_security_state(self):
        return {}

    async def evaluate(self, action, context):
        return {"allow": True, "would_block": False, "route": "observe"}


class _Backend:
    """Stands in for the installed backend: its accessor and the rule it exports."""

    def __init__(self, rule):
        self.rule = rule
        self.builds: list = []
        self._gate = None

    def get(self, config=None):
        if self._gate is None:
            self.builds.append(config)
            self._gate = _Gate(config)
        return self._gate

    def reset(self):
        self._gate = None


def _install(monkeypatch, backend: _Backend):
    monkeypatch.setattr(seam, "_backend_get_gate", backend.get)
    monkeypatch.setattr(seam, "_backend_reset_gate", backend.reset)
    monkeypatch.setattr(seam, "_backend_canonical_identity", backend.rule, raising=False)


@pytest.fixture(autouse=True)
def _release_the_host():
    seam.release_security_gate()
    yield
    seam.release_security_gate()


def _server(config=SWEEP_CONFIG) -> GatewayServer:
    server = GatewayServer(config)
    server.react_loop.router.health_check = AsyncMock(return_value={"ollama": True})
    return server


def _as_given(value):
    return value


def _upper_case_address(value):
    if isinstance(value, str) and value.strip()[:2].lower() == "0x":
        return "0x" + value.strip()[2:].upper()
    return value


def _folds_everything(value):
    return value.strip().lower() if isinstance(value, str) else value


def _raises(value):
    raise RuntimeError("rule unavailable")


_OTHER_RULES = {
    "(a) no rule": None,
    "(b) as given": _as_given,
    "(b) upper-case digits": _upper_case_address,
    "(c) folds what is not an address": _folds_everything,
    "(d) raises": _raises,
}


@pytest.mark.parametrize("label", list(_OTHER_RULES))
async def test_a_backend_that_does_not_name_a_caller_the_platforms_way_is_not_started(
        monkeypatch, label):
    monkeypatch.delenv("MATRIX_ENV", raising=False)
    backend = _Backend(_OTHER_RULES[label])
    _install(monkeypatch, backend)
    server = _server()

    async with TestClient(TestServer(server.create_app())) as client:
        assert (await client.get("/ready")).status == 503, label
        assert seam.security_gate_state() == "failed", label
        with pytest.raises(seam.SecurityGateUnavailable):
            seam.get_morpheus_security()
        assert server._security_gate_cause and "name a caller" in server._security_gate_cause

        from gateway.security_gate import gate_action
        decision = await gate_action("get_balance", {}, context={"wallet": "0x" + "ab" * 20})
        assert decision["allow"] is False, (label, decision)

    assert backend.builds == [], f"{label}: a gate was built for a backend that names callers otherwise"


class _InertService:
    def __init__(self, *args, **kwargs):
        pass


def _production_reaches_the_gate(monkeypatch):
    """Take the other production refusals out of the way (they have their own
    tests), so what refuses here is the gate's start and nothing else."""
    monkeypatch.setenv("MATRIX_ENV", "production")
    monkeypatch.setattr(seam, "SECURITY_BACKEND", "morpheus_security", raising=False)
    monkeypatch.setattr(seam, "OTPService", _InertService)
    monkeypatch.setattr(seam, "OwnerVerification", _InertService)
    monkeypatch.setattr(seam, "get_app_attest_verifier", lambda *a, **k: _InertService())


async def test_production_refuses_to_start_a_backend_that_names_a_caller_otherwise(monkeypatch):
    _production_reaches_the_gate(monkeypatch)
    _install(monkeypatch, _Backend(_as_given))
    test_server = TestServer(_server(PROD_CONFIG).create_app())
    try:
        with pytest.raises(RuntimeError,
                           match=r"failed to name a caller the way the platform does.*Refusing to start"):
            await test_server.start_server()
    finally:
        await test_server.close()


async def test_production_starts_a_backend_that_names_a_caller_the_platforms_way(monkeypatch):
    """Companion to the refusal above: the same production start, with the
    platform's rule exported, comes up."""
    _production_reaches_the_gate(monkeypatch)
    _install(monkeypatch, _Backend(canonical_identity))
    test_server = TestServer(_server(PROD_CONFIG).create_app())
    try:
        await test_server.start_server()
        assert seam.security_gate_state() == "up"
    finally:
        await test_server.close()


async def test_a_backend_that_exports_the_platforms_rule_starts(monkeypatch):
    """(f) SCOPE PIN."""
    monkeypatch.delenv("MATRIX_ENV", raising=False)
    backend = _Backend(canonical_identity)
    _install(monkeypatch, backend)
    server = _server()

    async with TestClient(TestServer(server.create_app())) as client:
        assert (await client.get("/ready")).status == 200
        assert seam.get_morpheus_security() is server._morpheus
    assert len(backend.builds) == 1


def test_the_no_op_backend_names_a_caller_the_platforms_way():
    """(f): the no-op records nothing about a caller and uses the platform's
    rule, so a checkout without the core starts its gate as before."""
    import importlib.util

    if importlib.util.find_spec("morpheus_security") is not None:
        pytest.skip("the core is installed; the no-op backend is not in use")
    assert getattr(seam, "_backend_canonical_identity", None) is canonical_identity
    assert seam.backend_names_callers_as_the_platform_does() is True


@pytest.mark.parametrize("label", list(_OTHER_RULES))
def test_doctor_does_not_call_a_core_ready_that_names_a_caller_otherwise(monkeypatch, label):
    """(e'): `ops.sh doctor` reads the live backend. A core the gateway will not
    start is not READY, and the detail says why."""
    import gateway.doctor as doctor

    monkeypatch.setattr(seam, "SECURITY_BACKEND", "morpheus_security", raising=False)
    monkeypatch.setattr(seam, "_backend_canonical_identity", _OTHER_RULES[label], raising=False)
    _, status, detail = doctor.check_security_backend({})
    assert status != doctor.READY, (label, detail)
    assert "name a caller" in detail, detail

    monkeypatch.setattr(seam, "_backend_canonical_identity", canonical_identity)
    _, status, _ = doctor.check_security_backend({})
    assert status == doctor.READY
