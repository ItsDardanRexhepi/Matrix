"""An envelope must not hide the refusal it is carrying.

THE DEFECT THIS EXISTS FOR. ``runtime/protocols/outcome_truth.py`` reads a
tool's own verdict out of the structure the tool returned, and
``ProtocolStack.post_action`` refuses to learn from an unlabelled one. That fix
is real, and on the two tools that matter most it lands short — because neither
tool hands the classifier the service's report. It hands it an ENVELOPE:

    ServiceDispatcher.execute   ->  {"status": "ok", "result": {...}}
    AgentHandoff.as_tool        ->  {"handoff": ..., "approved": false, ...}

The first says ``"status": "ok"`` about the DISPATCH — it says it just as
loudly when the service inside it returned ``{"status": "not_deployed"}``, and
``report_of`` reads the outer status and answers SUCCESS. The second states no
outcome vocabulary at all, so every Morpheus denial, every fail-closed gate
error and every unwired executor falls through to the measured default and is
learned as a success. Between them these two are ``platform_action`` and
``request_execution``: the mega-tool and the only channel Trinity has to move
value. Every refusal either one makes was being learned as a success.

WHAT THE FIX IS. The envelope STATES what it wraps, in a field that exists for
no other purpose (``outcome``), and ``report_of`` reads that field before every
weaker signal. Not a string sniff and not a shape guess: the layer that knows —
the one that called the service and holds its structured report — writes down
what it saw, exactly as ``ToolOutcome.ok`` is written down by the dispatcher
that knows.

THE SAME ASSUMPTION, THE OTHER WAY. Surfacing the inner verdict makes a second
error visible that the envelope used to hide: a READ of a record whose own
lifecycle status is ``failed`` (``get_campaign`` on a campaign that missed its
deadline) would be labelled a failed CALL. So the classifier is told whether the
``status`` field it is reading is the service's disposition or a record's
lifecycle — a fact only the caller knows, and one the dispatcher already holds
in ``_STATE_MODIFYING_ACTIONS``. Where the two readings cannot be told apart the
answer is UNKNOWN and nothing is learned, which is this module's whole point.
"""

from __future__ import annotations

import ast
import json
import pathlib

import pytest

from runtime.blockchain.services.service_dispatcher import (
    _STATE_MODIFYING_ACTIONS,
    ServiceDispatcher,
)
from runtime.protocols.outcome_truth import FAILURE, SUCCESS, UNKNOWN, report_of

_LOAN_PARAMS = {
    "borrower": "0xA", "collateral_token": "ETH", "collateral_amount": 10.0,
    "borrow_token": "USDC", "borrow_amount": 1000.0,
}


# ── platform_action: the mega-tool the outcome-truth fix was written for ──


async def test_the_platform_action_envelope_does_not_hide_a_service_refusal():
    """THE LOAD-BEARING ASSERTION of this cluster.

    ``create_loan`` under the shipped config returns ``not_deployed`` — the
    census's own refusal idiom. The envelope wraps it in ``"status": "ok"``, and
    that is the string the classifier reads.
    """
    env = await ServiceDispatcher({}).execute("create_loan", params=_LOAN_PARAMS)
    inner = json.loads(env)["result"]
    assert inner.get("status") == "not_deployed", f"premise changed: {inner}"
    assert report_of(env) == FAILURE, (
        "the envelope reported a refused action as a success — the outcome-truth "
        "fix cannot see past `status: ok`")


async def test_the_envelope_states_the_outcome_of_the_action_it_ran():
    """Stated in a field, not left to be inferred from the envelope's shape."""
    env = json.loads(
        await ServiceDispatcher({}).execute("create_loan", params=_LOAN_PARAMS))
    assert env.get("outcome") == FAILURE, env


async def test_a_genuine_action_is_still_a_success_through_the_envelope():
    """SCOPE PIN. An envelope that reports every action as a refusal is the
    mirror-image defect. ``create_payment`` genuinely mints, signs and persists
    a payment and returns ``created: True`` with a record status of ``pending``.
    """
    env = await ServiceDispatcher({}).execute("create_payment", params={
        "agent_id": "agent_1", "recipient": "0xB", "amount": 12.5,
        "token": "USDC", "purpose": "data access",
    })
    inner = json.loads(env)["result"]
    assert inner.get("created") is True, f"premise changed: {inner}"
    assert report_of(env) == SUCCESS


async def test_an_unknown_action_is_a_failure_not_a_success():
    env = await ServiceDispatcher({}).execute("no_such_action_at_all", params={})
    assert json.loads(env).get("outcome") == FAILURE
    assert report_of(env) == FAILURE


async def test_every_envelope_execute_returns_states_an_outcome():
    """Structural: no return path may leave the field off, or the classifier
    silently falls back to reading `status: "ok"` on that path alone."""
    src = pathlib.Path(
        "runtime/blockchain/services/service_dispatcher.py").read_text()
    tree = ast.parse(src)
    cls = next(n for n in ast.walk(tree)
               if isinstance(n, ast.ClassDef) and n.name == "ServiceDispatcher")
    fn = next(n for n in cls.body
              if isinstance(n, ast.AsyncFunctionDef) and n.name == "execute")
    missing = []
    for node in ast.walk(fn):
        if not isinstance(node, ast.Return) or node.value is None:
            continue
        call = node.value
        if not (isinstance(call, ast.Call) and isinstance(call.func, ast.Attribute)
                and call.func.attr == "dumps"):
            continue
        payload = call.args[0] if call.args else None
        if not isinstance(payload, ast.Dict):
            continue
        keys = [k.value for k in payload.keys
                if isinstance(k, ast.Constant) and isinstance(k.value, str)]
        if "outcome" not in keys:
            missing.append(node.lineno)
    assert missing == [], (
        f"execute() returns an envelope with no `outcome` field at line(s) {missing}")


# ── the read whose SUBJECT failed ────────────────────────────────────────


async def _a_failed_campaign() -> tuple[ServiceDispatcher, str]:
    d = ServiceDispatcher({})
    svc = d._get_registry().get("fundraising")
    created = await svc.create_campaign(
        creator="0xA", title="T", goal=100.0, deadline_days=1,
        milestones=[{"title": "m", "release_pct": 100.0, "description": "d"}])
    cid = created["campaign_id"]
    svc._campaigns[cid]["status"] = "failed"      # the campaign missed its goal
    return d, cid


async def test_a_read_of_a_failed_record_is_not_a_failed_call():
    """THE ERROR SURFACING THE INNER VERDICT WOULD OTHERWISE INTRODUCE.

    ``get_campaign`` is a READ. It succeeded: it returned the record. The
    record's own ``status`` is ``failed`` because the campaign missed its
    deadline — that is the CAMPAIGN's lifecycle, not the call's disposition, and
    ``failed`` is one of exactly four failure-vocabulary statuses this tree ever
    assigns to a stored record (see the census test below).

    Not SUCCESS either: from the payload alone the two readings cannot be told
    apart, and a mislabelled sample is worse than an unlabelled one.
    """
    d, cid = await _a_failed_campaign()
    env = await d.execute("get_campaign", params={"campaign_id": cid})
    assert json.loads(env)["result"].get("status") == "failed", "premise changed"
    assert report_of(env) == UNKNOWN, (
        "a successful read of a failed campaign was labelled — the record's "
        "lifecycle was read as the call's verdict")


async def test_a_read_that_really_failed_is_still_a_failure():
    """SCOPE PIN for the rule above: only a record's own lifecycle vocabulary is
    discounted on a read. A read that failed says so, and still says so."""
    d = ServiceDispatcher({})
    env = await d.execute("get_campaign", params={"campaign_id": "nope"})
    assert report_of(env) == FAILURE


def test_the_record_lifecycle_census_is_re_derived_not_copied():
    """The four discounted statuses are measured, and drift is a test failure.

    Scans every ``<record>["status"] = <literal>`` assignment in the tree — the
    places a STORED RECORD is given a lifecycle — and asserts that every one of
    them that is also in the refusal vocabulary is classified. A new record
    state that collides with the refusal vocabulary fails here rather than
    quietly relabelling a read.
    """
    from runtime.protocols.outcome_truth import _FAILED, _SUBJECT_LIFECYCLE

    measured: set[str] = set()
    for path in pathlib.Path("runtime").rglob("*.py"):
        try:
            tree = ast.parse(path.read_text())
        except (SyntaxError, UnicodeDecodeError):
            continue
        for node in ast.walk(tree):
            if not isinstance(node, ast.Assign):
                continue
            for target in node.targets:
                if not (isinstance(target, ast.Subscript)
                        and isinstance(target.slice, ast.Constant)
                        and target.slice.value == "status"):
                    continue
                value = node.value
                if isinstance(value, ast.Constant) and isinstance(value.value, str):
                    measured.add(value.value.strip().lower())
                elif isinstance(value, ast.Attribute):      # an Enum member
                    measured.add(value.attr.strip().lower())

    assert measured, "the census found nothing — the scan is broken, not the tree"
    unclassified = (measured & _FAILED) - _SUBJECT_LIFECYCLE
    assert unclassified == set(), (
        f"{sorted(unclassified)} are assigned to stored records AND are in the "
        "refusal vocabulary, but are not classified as record lifecycle — a read "
        "returning one would be learned as a failed call")


# ── request_execution: Trinity -> Morpheus -> Neo ────────────────────────


class _Gate:
    def __init__(self, decision):
        self._decision = decision

    async def evaluate(self, request, context):
        return self._decision


@pytest.fixture
def gate(monkeypatch):
    """Install a Morpheus gate decision. `handoff` imports the accessor inside
    the function, so patching the module attribute is what reaches it."""
    import runtime.security as security

    def _install(decision=None, raises=False):
        def _get(config):
            if raises:
                raise RuntimeError("gate backend down")
            return _Gate(decision if decision is not None else {"allow": True})
        monkeypatch.setattr(security, "get_morpheus_security", _get)
    return _install


async def test_a_morpheus_denial_is_not_reported_as_a_success(gate):
    """Every denial by the security gate was being learned as a success."""
    from runtime.agents.handoff import AgentHandoff

    gate({"allow": False, "reason": "value cap exceeded"})
    out = await AgentHandoff({}, None).as_tool("swap_tokens", {})
    assert json.loads(out)["approved"] is False, "premise changed"
    assert report_of(out) == FAILURE


async def test_a_fail_closed_gate_error_is_not_reported_as_a_success(gate):
    """The gate was unavailable, so nothing was escalated. That is a refusal."""
    from runtime.agents.handoff import AgentHandoff

    gate(raises=True)
    out = await AgentHandoff({}, None).as_tool("swap_tokens", {})
    assert report_of(out) == FAILURE


async def test_an_unwired_executor_is_not_reported_as_a_success(gate):
    """approved=True, executed=False. Nothing ran."""
    from runtime.agents.handoff import AgentHandoff

    gate({"allow": True})
    out = await AgentHandoff({}, None).as_tool("swap_tokens", {})
    assert json.loads(out)["executed"] is False, "premise changed"
    assert report_of(out) == FAILURE


async def test_a_neo_execution_error_is_not_reported_as_a_success(gate):
    from runtime.agents.handoff import AgentHandoff

    class _Exploding:
        async def execute(self, *a, **k):
            raise RuntimeError("boom")

    gate({"allow": True})
    out = await AgentHandoff({}, _Exploding()).as_tool("swap_tokens", {})
    assert report_of(out) == FAILURE


async def test_the_handoff_relays_neos_own_verdict(gate):
    """END TO END, both envelopes. Neo's refusal travels through the service
    dispatcher's envelope and then through the hand-off's, and must still be a
    refusal when outcome learning reads it."""
    from runtime.agents.handoff import AgentHandoff

    gate({"allow": True})
    out = await AgentHandoff({}, ServiceDispatcher({})).as_tool(
        "create_loan", _LOAN_PARAMS)
    assert report_of(out) == FAILURE


async def test_the_handoff_still_reports_a_real_execution_as_a_success(gate):
    """SCOPE PIN: the channel must not report everything it carries as refused."""
    from runtime.agents.handoff import AgentHandoff

    gate({"allow": True})
    out = await AgentHandoff({}, ServiceDispatcher({})).as_tool("create_payment", {
        "agent_id": "agent_1", "recipient": "0xB", "amount": 12.5,
        "token": "USDC", "purpose": "data access",
    })
    assert report_of(out) == SUCCESS


# ── agent_identity: a verification that could not run ────────────────────


async def test_a_verification_that_could_not_run_is_not_a_success():
    """``verified: False`` is not a field ``report_of`` reads, and two of these
    branches are not answers at all — they are the platform saying it could not
    look."""
    from runtime.blockchain.agent_identity import AgentIdentity

    out = await AgentIdentity({}).execute(action="verify", agent_name="nobody")
    assert json.loads(out)["verified"] is False, "premise changed"
    assert report_of(out) == FAILURE, (
        "a verification that never ran was reported as a successful call")


# ── the prose tools ──────────────────────────────────────────────────────


async def _dispatch(name, **arguments):
    from runtime.tools.dispatcher import ToolDispatcher

    return await ToolDispatcher({"workspace": "."}).dispatch(name, arguments)


async def test_a_blocked_bash_command_is_not_reported_as_a_success():
    out = await _dispatch("bash", command="rm -rf /")
    assert out.reported == FAILURE, out.model_text


async def test_a_file_op_refusal_is_not_reported_as_a_success():
    out = await _dispatch("file_ops", operation="read", path="../../etc/passwd")
    assert out.reported == FAILURE, out.model_text


async def test_a_web_refusal_is_not_reported_as_a_success():
    out = await _dispatch("web", url="ftp://example.com")
    assert out.reported == FAILURE, out.model_text


async def test_a_blockchain_capability_refusal_is_not_reported_as_a_success():
    """The 57 capability error paths. Their success idiom is `json.dumps({...})`
    and their failure idiom was prose, so every failure read as a success."""
    out = await _dispatch("nft", action="no_such_nft_action")
    assert out.reported == FAILURE, out.model_text


async def test_a_prose_success_is_still_a_success():
    """SCOPE PIN. `file_ops read` returns the FILE'S CONTENTS as prose. Nothing
    here may start reading a successful tool's output as a refusal."""
    out = await _dispatch("file_ops", operation="read", path="README.md")
    assert out.reported == SUCCESS and out.ok is True


# ── what the client is told ──────────────────────────────────────────────


async def test_the_client_is_told_the_corrected_verdict_not_just_that_it_ran(tmp_path):
    """``tool_calls[].success`` on /chat, /chat/stream, /ws and the bridge was
    ``outcome.ok`` — "the dispatcher completed the call" — three lines from the
    verdict the tool actually reported. The iOS client declares it ``Bool?``, so
    the third answer travels as ``null`` rather than as a guess."""
    import sys

    sys.path.insert(0, "tests")
    from test_route_sweep import SWEEP_CONFIG

    from runtime.models.model_interface import ModelResponse
    from runtime.react_loop import Message, ReActContext, ReActLoop

    loop = ReActLoop({**SWEEP_CONFIG, "memory_dir": str(tmp_path / "memory")})
    replies = [
        ModelResponse(tool_calls=[{"id": "c1", "function": {
            "name": "probe", "arguments": "{}"}}]),
        ModelResponse(content="done"),
    ]

    async def complete(**kwargs):
        return replies.pop(0)

    async def probe(**kwargs):
        return {"status": "error", "message": "reverted"}

    loop.router.complete = complete
    loop.dispatcher._tools["probe"] = probe

    result = await loop.run(ReActContext(
        agent_name="neo", conversation=[Message(role="user", content="go")],
        metadata={}))

    assert result.tool_calls, "no tool call was recorded"
    assert result.tool_calls[0]["success"] is False, (
        "the client was told a refused tool call succeeded")


# ── the classifier's own false positives ─────────────────────────────────


@pytest.mark.parametrize("payload,label", [
    ({"credential_id": "c1", "valid": False, "expired": True,
      "errors": ["Credential has expired"]}, "credential_vault.verify_credential"),
    ({"agent": "neo", "score": 40, "errors": 3}, "reputation's error COUNTER"),
])
def test_a_data_field_named_errors_is_not_a_report_about_the_call(payload, label):
    """MEASURED, not reasoned. Every ``errors`` key this tree emits is DATA — a
    verifier's findings list (``credential_vault``, ``selective_disclosure``,
    ``did_identity.service``) or a counter (``agent_identity.reputation``).
    Not one of them reports that the CALL failed, so reading it as the call's
    verdict labels a verification that ran perfectly as a failure.
    """
    assert report_of(payload) != FAILURE, label


@pytest.mark.parametrize("payload", [
    {"error": "nonce too low"},
    {"status": "error", "errors": ["reverted"]},
    {"ok": False, "errors": []},
])
def test_the_singular_error_idiom_is_untouched(payload):
    """SCOPE PIN: 245 `"error":` returns are how this tree reports a failed call,
    and nothing above may soften one of them."""
    assert report_of(payload) == FAILURE


def test_a_record_lifecycle_status_is_only_discounted_where_it_is_ambiguous():
    """The same payload, the two readings, stated explicitly."""
    record = {"campaign_id": "c1", "status": "failed"}
    assert report_of(record) == FAILURE, (
        "on an action that changes state the status IS the service's verdict")
    assert report_of(record, status_describes_the_call=False) == UNKNOWN
    # and a status no record is ever assigned stays a refusal on both readings
    assert report_of({"status": "not_deployed"},
                     status_describes_the_call=False) == FAILURE


def test_the_dispatcher_decides_which_reading_applies_from_the_measured_set():
    """The caller passes the fact it holds; it does not re-derive one."""
    assert "create_loan" in _STATE_MODIFYING_ACTIONS
    assert "get_campaign" not in _STATE_MODIFYING_ACTIONS
