"""No request makes the attestation service sign or revoke.

THE FINDING. The services layer has its own attestation service
(``runtime/blockchain/services/attestation/``), and three ACTION_MAP actions
hand it a request as it arrived: ``create_attestation`` (``attestation.attest``,
schema, data and recipient all from the request), ``batch_attest`` (a list of
the same) and ``revoke_attestation`` (``attestation.revoke``, any uid the request
names). The platform key signs every one; a time-critical category (an
emergency freeze, a ban, a dispute filing) and a revocation go through the
UNMETERED platform signer. So a request could have the platform put its name to
"morpheus approved this withdrawal" about any address, or void any attestation
the platform ever made, somebody's identity registration included.

Four doors reached it, and none refused it to any caller:

  POST /api/v1/capabilities/{id}/invoke  a session may invoke any catalog id
                                         its routes do not refuse, and these
                                         three have no route to refuse them;
  POST /bridge/v1/action                 the same dispatcher, by action name;
  request_execution                      Trinity's hand-off to Neo, which a
                                         session reaches from chat;
  platform_action                        Neo's mega-tool, the operator's chat.

The twin tools' ``eas`` attest, batch_attest and revoke were refused on this
branch; this is the same decision at the tier the capability routes and the
chat agents reach.

THE CHANGE. ``runtime.access_policy.refused_on_request`` names the three
operations by the (service, method) pair a dispatch RUNS, and each door refuses
them before the dispatcher runs, whoever is asking — a session, the operator
key, an anonymous chat, a caller with no HTTP request behind it. The platform
still attests what it EXECUTES (the dispatcher's own record of an action, each
service's record of an operation it ran); those never enter through a door.

CONTROL. At fix/oldq-census 083ed72 the tests marked [control] fail: every
door runs the dispatcher. The tests marked [guard] pass before and after: a
read through the same doors still runs, and the platform's own in-process code
still reaches the service.
"""

from __future__ import annotations

import json
import sys
import time

import pytest

sys.path.insert(0, "tests")

A = "0x" + "a1" * 20      # the caller
B = "0x" + "b2" * 20      # somebody else

PARAMS = {
    # "morpheus approved a withdrawal" about B, as an emergency freeze: the
    # time-critical path, signed at once by the unmetered platform signer.
    "create_attestation": {
        "schema_uid": "primary", "recipient": B, "time_critical": True,
        "data": {"action": "approved_withdrawal", "agent": "morpheus",
                 "category": "emergency_freeze"},
    },
    "batch_attest": {"attestations": [
        {"schema_uid": "primary", "recipient": B,
         "data": {"action": "approved_withdrawal", "agent": "morpheus"}}]},
    # Any uid the platform ever attested, somebody else's registration included.
    "revoke_attestation": {"attestation_uid": "0x" + "ef" * 32, "schema_uid": "primary"},
}
CAPABILITY_OF = {"create_attestation": "create_attestation",
                 "batch_attest": "batch_attest",
                 "revoke_attestation": "revoke_attestation"}
REFUSED = sorted(PARAMS)


class _Allow:
    """A gate that allows everything, so a refusal can only be the door's."""

    async def initialize(self):
        return None

    async def evaluate(self, action, context):
        return {"allow": True}


@pytest.fixture
def reached(monkeypatch):
    """Every action that reached ServiceDispatcher.execute. Installed on the
    class before any dispatcher is built, so a bound method registered later
    is the spy too."""
    from runtime.blockchain.services.service_dispatcher import ServiceDispatcher

    calls: list[str] = []

    async def execute(self, action, service=None, params=None, **kwargs):
        calls.append(action if not service else f"{action}@{service}")
        return json.dumps({"status": "ok", "result": {"status": "recorded by the test"}})

    monkeypatch.setattr(ServiceDispatcher, "execute", execute)
    monkeypatch.setattr("runtime.security.get_morpheus_security", lambda *a, **k: _Allow())
    return calls


def _dispatcher():
    from runtime.tools.dispatcher import ToolDispatcher
    return ToolDispatcher({"workspace": "."})


# ── the chat doors: request_execution and platform_action ────────────────

@pytest.mark.parametrize("caller_kind", ["session", "operator", ""])
@pytest.mark.parametrize("action", REFUSED)
async def test_request_execution_runs_none_of_them(reached, action, caller_kind):
    """[control] Trinity's hand-off to Neo, from any caller. A session's chat is
    Trinity's, and this was the door the capability-route limit left out."""
    out = await _dispatcher().dispatch(
        "request_execution", {"action": action, "params": PARAMS[action]},
        agent_name="trinity", caller_identity=A, caller_kind=caller_kind)
    assert reached == [], f"request_execution ran {reached} for a {caller_kind or 'caller-less'} caller"
    assert out.ok is False and "[DENIED]" in out.model_text


@pytest.mark.parametrize("action", REFUSED)
async def test_an_anonymous_chat_was_and_is_refused_them(reached, action):
    """[guard] An anonymous caller is refused every state change already
    (gateway/session_routes.py caller_refused_route); that stays."""
    out = await _dispatcher().dispatch(
        "request_execution", {"action": action, "params": PARAMS[action]},
        agent_name="trinity", caller_kind="anonymous")
    assert reached == [] and out.ok is False and "[DENIED]" in out.model_text


@pytest.mark.parametrize("caller_kind", ["operator", ""])
@pytest.mark.parametrize("action", REFUSED)
async def test_platform_action_runs_none_of_them(reached, action, caller_kind):
    """[control] Neo's mega-tool, from the operator's chat and from a caller
    with no HTTP request behind it. The model composes these arguments."""
    out = await _dispatcher().dispatch(
        "platform_action", {"action": action, "params": PARAMS[action]},
        agent_name="neo", caller_identity=A, caller_kind=caller_kind)
    assert reached == [], f"platform_action ran {reached}"
    assert out.ok is False and "[DENIED]" in out.model_text


async def test_a_read_through_the_same_doors_still_runs(reached):
    """[guard] The refusal is the three operations', not the attestation
    service's: verifying an attestation still runs, for Trinity and for Neo."""
    uid = {"attestation_uid": "0x" + "ef" * 32}
    out = await _dispatcher().dispatch(
        "platform_action", {"action": "verify_attestation", "params": uid},
        agent_name="trinity", caller_kind="session")
    assert reached == ["verify_attestation"], (reached, out.model_text)
    out = await _dispatcher().dispatch(
        "platform_action", {"action": "verify_attestation", "params": uid},
        agent_name="neo", caller_kind="operator")
    assert reached == ["verify_attestation"] * 2, (reached, out.model_text)


# ── the HTTP doors: capability invoke and the bridge action ──────────────

def _server(tmp_path):
    from test_capability_catalog_truth import _session_server
    from test_route_sweep import SWEEP_CONFIG
    return _session_server(tmp_path, SWEEP_CONFIG)


async def _with_session(server):
    now = time.time()
    await server.wallet_sessions.add(token="0xTEST_SESSION", address="apple:sub",
                                     issued_at=now, expires_at=now + 3600)


HEADERS = {"session": {"Authorization": "Bearer 0xTEST_SESSION"},
           "operator": {"Authorization": "Bearer k"}}


@pytest.mark.parametrize("who", sorted(HEADERS))
async def test_the_capability_invoke_route_runs_none_of_them(reached, tmp_path, who):
    """[control] A session reached all three here; the operator key too."""
    from aiohttp.test_utils import TestClient, TestServer

    server = _server(tmp_path)
    answered = {}
    async with TestClient(TestServer(server.create_app())) as client:
        await _with_session(server)
        for action in REFUSED:
            resp = await client.post(f"/api/v1/capabilities/{CAPABILITY_OF[action]}/invoke",
                                     headers=HEADERS[who], json={"params": PARAMS[action]})
            answered[action] = resp.status
    assert reached == [], f"the invoke route ran {reached} for the {who}"
    assert answered == {a: 403 for a in REFUSED}, answered


@pytest.mark.parametrize("who", sorted(HEADERS))
async def test_the_bridge_action_route_runs_none_of_them(reached, tmp_path, who):
    """[control]"""
    from aiohttp.test_utils import TestClient, TestServer

    server = _server(tmp_path)
    answered = {}
    async with TestClient(TestServer(server.create_app())) as client:
        await _with_session(server)
        for action in REFUSED:
            resp = await client.post("/bridge/v1/action", headers=HEADERS[who],
                                     json={"action": action, "params": PARAMS[action],
                                           "session_id": "s1"})
            answered[action] = resp.status
    assert reached == [], f"/bridge/v1/action ran {reached} for the {who}"
    assert answered == {a: 403 for a in REFUSED}, answered


async def test_the_same_http_doors_still_run_a_read(reached, tmp_path):
    """[guard]"""
    from aiohttp.test_utils import TestClient, TestServer

    server = _server(tmp_path)
    uid = {"attestation_uid": "0x" + "ef" * 32}
    async with TestClient(TestServer(server.create_app())) as client:
        await _with_session(server)
        # verify_attestation has no catalog id; a catalog read stands in for it.
        resp = await client.post("/api/v1/capabilities/reputation_query/invoke",
                                 headers=HEADERS["session"], json={"params": {}})
        assert resp.status != 403, await resp.text()
        resp = await client.post("/bridge/v1/action", headers=HEADERS["session"],
                                 json={"action": "verify_attestation", "params": uid,
                                       "session_id": "s1"})
        assert resp.status != 403, await resp.text()
    assert reached == ["reputation_query", "verify_attestation"], reached


# ── what decides, and what it leaves alone ───────────────────────────────

def test_the_refusal_follows_the_pair_a_dispatch_runs(monkeypatch):
    """[control] Keyed on what the dispatcher RUNS, not the label: a new action
    name for attestation.attest, or a service override onto the attestation
    service, is the same operation."""
    from runtime.access_policy import refused_on_request
    from runtime.blockchain.services import service_dispatcher as sd

    monkeypatch.setitem(sd.ACTION_MAP, "note_for_the_record", ("attestation", "attest"))
    monkeypatch.setitem(sd.ACTION_MAP, "undo_a_note", ("did_identity", "revoke"))
    assert refused_on_request("note_for_the_record")
    assert refused_on_request("undo_a_note", "attestation")
    assert refused_on_request("undo_a_note") is None
    for action in REFUSED:
        assert refused_on_request(action), action
    assert refused_on_request("verify_attestation") is None
    assert refused_on_request("no_such_action") is None
    assert refused_on_request({"action": "create_attestation"}) is None


async def test_the_platforms_own_code_still_reaches_the_service(monkeypatch):
    """[guard] The refusal is at the doors a request comes through. The
    dispatcher itself, called in process by the platform's own code (the
    attestation-chain example, the services' own records), still runs the
    service — that is the platform's own statement, not a request's."""
    from runtime.blockchain.services.attestation.service import AttestationService
    from runtime.blockchain.services.service_dispatcher import ServiceDispatcher

    ran = []

    async def attest(self, schema_uid, data, recipient, time_critical=False):
        ran.append(("attest", recipient))
        return {"status": "queued"}

    monkeypatch.setattr(AttestationService, "attest", attest)
    d = ServiceDispatcher({})
    d._get_registry()._instances["attestation"] = AttestationService({})
    await d.execute("create_attestation", params={
        "schema_uid": "primary", "recipient": A, "data": {"action": "contract_deployed"}})
    assert ("attest", A) in ran, ran


def test_the_catalog_and_the_chat_guide_do_not_offer_them():
    """[control] Offered as available, a refused operation is a promise the
    platform breaks: the catalog marks each unavailable (still routed, so a
    caller gets the refusal, not a 404), and the chat guide tells the model it
    is not available instead of how to call it."""
    from runtime.capabilities import catalog
    from runtime.chat.intent_actions import INTENT_ACTION_MAP

    for action in REFUSED:
        cap = catalog.get_by_id(CAPABILITY_OF[action])
        assert cap is not None and cap["available"] is False, (action, cap)
        guide = INTENT_ACTION_MAP[action]
        assert guide.get("unavailable") is True and "action_name" not in guide, action
