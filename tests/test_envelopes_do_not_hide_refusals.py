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
from runtime.protocols.outcome_truth import (
    FAILURE,
    OUTCOME_FIELD,
    SUCCESS,
    UNKNOWN,
    report_of,
)

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
    assert env.get(OUTCOME_FIELD) == FAILURE, env


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
    assert json.loads(env).get(OUTCOME_FIELD) == FAILURE
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
        # The field is written as the SYMBOL (a bare string would be half of a
        # rename waiting to happen), so the key is an ast.Name here, not a
        # Constant. A literal spelling is caught by the namespacing test below.
        states_outcome = any(
            isinstance(k, ast.Name) and k.id == "OUTCOME_FIELD"
            for k in payload.keys)
        if not states_outcome:
            missing.append(node.lineno)
    assert missing == [], (
        f"execute() returns an envelope with no {OUTCOME_FIELD} field at "
        f"line(s) {missing}")


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


def _status_literals(node: ast.Dict) -> set[str]:
    """The literal ``"status"`` values a dict display is constructed with."""
    out: set[str] = set()
    for key, value in zip(node.keys, node.values):
        if not (isinstance(key, ast.Constant) and key.value == "status"):
            continue
        if isinstance(value, ast.Constant) and isinstance(value.value, str):
            out.add(value.value.strip().lower())
        elif isinstance(value, ast.Attribute):          # an Enum member
            out.add(value.attr.strip().lower())
    return out


def _records_assigned_a_status() -> dict[str, list[str]]:
    """``<record>["status"] = <literal>`` — a record RE-assigned a lifecycle."""
    found: dict[str, list[str]] = {}
    for path in sorted(pathlib.Path("runtime").rglob("*.py")):
        try:
            tree = ast.parse(path.read_text())
        except (SyntaxError, UnicodeDecodeError, OSError):
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
                status = None
                if isinstance(value, ast.Constant) and isinstance(value.value, str):
                    status = value.value.strip().lower()
                elif isinstance(value, ast.Attribute):
                    status = value.attr.strip().lower()
                if status:
                    found.setdefault(status, []).append(f"{path}:{node.lineno}")
    return found


def _records_built_as_dict_literals() -> dict[str, list[str]]:
    """``self._things[key] = {"status": <literal>, ...}`` — a record BORN with a
    lifecycle, which is how most of this tree writes one.

    Scoped to stores into a container hanging off ``self``, and that scope is
    load-bearing in both directions. Narrower than "every returned dict with a
    status", which sweeps up ~250 sites that are INLINE DISPOSITIONS — a read
    answering ``{"status": "not_found"}`` is the call refusing, not a record's
    lifecycle, and discounting those would be this cluster's own defect facing
    the other way. Wider than the subscript scan above, which is what it is here
    to fix.
    """
    found: dict[str, list[str]] = {}

    def stored_in_self(node: ast.AST) -> bool:
        if isinstance(node, ast.Subscript):                  # self._x[k] = ...
            base = node.value
        elif (isinstance(node, ast.Call) and isinstance(node.func, ast.Attribute)
                and node.func.attr in ("append", "insert")):  # self._x.append()
            base = node.func.value
        else:
            return False
        return (isinstance(base, ast.Attribute)
                and isinstance(base.value, ast.Name) and base.value.id == "self")

    for path in sorted(pathlib.Path("runtime").rglob("*.py")):
        try:
            tree = ast.parse(path.read_text())
        except (SyntaxError, UnicodeDecodeError, OSError):
            continue
        for scope in ast.walk(tree):
            if not isinstance(scope, (ast.FunctionDef, ast.AsyncFunctionDef)):
                continue
            bound: dict[str, ast.Dict] = {}
            for node in ast.walk(scope):
                if isinstance(node, ast.Assign) and isinstance(node.value, ast.Dict):
                    for target in node.targets:
                        if isinstance(target, ast.Name):
                            bound[target.id] = node.value
            records: list[ast.Dict] = []
            for node in ast.walk(scope):
                candidates: list[ast.AST] = []
                if isinstance(node, ast.Assign):
                    if any(stored_in_self(t) for t in node.targets):
                        candidates.append(node.value)
                elif isinstance(node, ast.Call) and stored_in_self(node):
                    candidates.extend(node.args)
                for candidate in candidates:
                    if isinstance(candidate, ast.Dict):
                        records.append(candidate)
                    elif isinstance(candidate, ast.Name) and candidate.id in bound:
                        records.append(bound[candidate.id])
            for record in records:
                for status in _status_literals(record):
                    found.setdefault(status, []).append(f"{path}:{record.lineno}")
    return found


def test_the_record_lifecycle_census_is_re_derived_not_copied():
    """The four discounted statuses are measured, and drift is a test failure.

    A new record state that collides with the refusal vocabulary fails here
    rather than quietly relabelling a read.
    """
    from runtime.protocols.outcome_truth import _FAILED, _SUBJECT_LIFECYCLE

    measured = set(_records_assigned_a_status()) | set(_records_built_as_dict_literals())
    assert measured, "the census found nothing — the scan is broken, not the tree"
    unclassified = (measured & _FAILED) - _SUBJECT_LIFECYCLE
    assert unclassified == set(), (
        f"{sorted(unclassified)} are assigned to stored records AND are in the "
        "refusal vocabulary, but are not classified as record lifecycle — a read "
        "returning one would be learned as a failed call")
    assert _SUBJECT_LIFECYCLE <= measured, (
        f"{sorted(_SUBJECT_LIFECYCLE - measured)} are discounted on reads as "
        "record lifecycle states, but no record in the tree is given them any "
        "more — a stale carve-out silently weakens a real refusal")


def test_the_record_lifecycle_census_sees_records_built_as_dict_literals():
    """THE GUARD DID NOT GUARD THE DRIFT IT WAS WRITTEN FOR.

    It walked ``<record>["status"] = <literal>`` only — a record whose status is
    CHANGED after the fact. Most of this tree never does that: it constructs the
    record with its status already in the dict display and stores it. Re-derived
    at the time of writing, the subscript scan sees 42 states and the dict
    display scan sees 16, of which 14 the first scan never saw at all
    (``active`` on a subscription, ``pending`` on a refund, ``submitted`` on a
    milestone). None of the 14 collides with the refusal vocabulary, which is
    the only reason the
    guard's CONCLUSION was right — it was right by luck, over a blind spot big
    enough to hide the next one in.

    This pins the scan's reach, so the guard cannot quietly shrink back to the
    half of the tree it could see.
    """
    subscript = _records_assigned_a_status()
    literal = _records_built_as_dict_literals()
    assert subscript and literal, "one of the two scans is broken"
    only_in_literals = set(literal) - set(subscript)
    assert len(only_in_literals) >= 10, (
        "the dict-display scan no longer contributes states the subscript scan "
        f"misses ({sorted(only_in_literals)}) — re-derive before trusting the "
        "census that keeps a read from being learned as a failed call")


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
    """The tool is registered as ``web_request``. This control used to dispatch
    ``"web"``, which no registry entry answers to — so it tested the
    dispatcher's unknown-tool path and passed on the unfixed tree.
    ``test_every_tool_these_controls_dispatch_is_a_registered_tool`` below is
    what keeps that from happening again."""
    out = await _dispatch("web_request", url="ftp://example.com")
    assert out.reported == FAILURE, out.model_text
    assert json.loads(out.model_text)["ok"] is False, out.model_text


async def test_a_blockchain_capability_refusal_is_not_reported_as_a_success():
    """The 91 capability error paths across 20 modules. Their success idiom is
    `json.dumps({...})` and their failure idiom was prose, so every failure read
    as a success."""
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


# ── the stated field is the PLATFORM's word, not a domain word ───────────
#
# THE REGRESSION THIS SECTION EXISTS FOR. The fix above gave the envelope a
# field to state what it wraps and had `report_of` believe it first. The field
# it chose was the bare word `outcome`, which this tree ALREADY uses as a DATA
# key in 15 places — a prediction market's resolved outcome, a dispute's
# outcome, a governance proposal's outcome, an agent interaction's outcome. So
# `gaming.resolve_market`, whose whole job is to write the caller's market
# outcome into a record, resolved a market to "failure" and the platform read
# that as ITS OWN call having failed: the same request attested the action as
# REAL and told the client and the learner it was a refusal.
#
# The fix is a field the domain does not speak. Not a heuristic that tells the
# two apart — there is nothing in the payload that could.


async def test_a_domain_outcome_word_is_not_read_as_the_calls_verdict():
    """A market resolved TO "failure" is a call that SUCCEEDED."""
    env = await ServiceDispatcher({}).execute("market_resolve", params={
        "market_id": "m1", "outcome": "failure", "resolver": "0xA",
    })
    body = json.loads(env)
    assert body["result"].get("outcome") == "failure", f"premise changed: {body}"
    assert body["result"].get("status") == "resolved", f"premise changed: {body}"
    assert body[OUTCOME_FIELD] == SUCCESS, (
        "the platform read a market's DOMAIN outcome as its own verdict")
    assert report_of(env) == SUCCESS


async def test_a_domain_outcome_word_cannot_fabricate_a_success_either():
    """The same collision the other way: a payload that carries the word must
    not be able to talk a refusal into a success."""
    assert report_of({"outcome": "success", "ok": False, "error": "reverted"}) == FAILURE
    assert report_of({"status": "ok",
                      "result": {"outcome": "success", "status": "error",
                                 "error": "nope"}}) == FAILURE


def test_nothing_but_the_platform_writes_the_stated_field():
    """The namespacing is the guarantee, so it is measured, not asserted.

    Two claims. (1) No site outside ``outcome_truth`` spells the field as a bare
    string — every writer goes through the symbol, so the name can never be half
    renamed. (2) The name is not one the domain uses: the word it replaced,
    ``outcome``, is written as a data key in double figures across the tree, and
    that census is what makes this test necessary rather than decorative.
    """
    from runtime.protocols.outcome_truth import OUTCOME_FIELD as _field

    bare: list[str] = []
    domain_outcome_keys: list[str] = []
    for path in sorted(pathlib.Path().glob("*/**/*.py")):
        if any(part in {".git", "node_modules"} for part in path.parts):
            continue
        try:
            tree = ast.parse(path.read_text())
        except (SyntaxError, UnicodeDecodeError, OSError):
            continue
        own = path.as_posix() == "runtime/protocols/outcome_truth.py"
        for node in ast.walk(tree):
            if not isinstance(node, ast.Dict):
                continue
            for key in node.keys:
                if not (isinstance(key, ast.Constant) and isinstance(key.value, str)):
                    continue
                if key.value == _field and not own:
                    bare.append(f"{path}:{key.lineno}")
                if key.value == "outcome" and path.parts[0] == "runtime":
                    domain_outcome_keys.append(f"{path}:{key.lineno}")
    assert bare == [], (
        f"{_field} is written as a bare string at {bare} — write OUTCOME_FIELD")
    assert len(domain_outcome_keys) >= 10, (
        "the census that motivates the namespacing no longer holds; re-derive "
        f"it before narrowing the field name: {domain_outcome_keys}")


def test_the_stated_field_is_not_a_word_any_service_returns():
    """Live census, not a source scan: no service payload reachable through the
    mega-tool may already carry the field the platform states its verdict in."""
    from runtime.protocols.outcome_truth import OUTCOME_FIELD as _field

    assert "_" in _field, (
        f"{_field!r} is a plain English word — the field the platform states "
        "its own verdict in must be one no domain payload can collide with")


async def test_a_stated_success_cannot_overrule_a_structures_own_refusal():
    """THE THIRD ANSWER. The stated field outranks the heuristics because the
    layer that wrote it knew more than they can see. It does not outrank the
    structure CONTRADICTING it: a payload that says both is a payload nobody
    established the truth of, and an unlabelled sample beats a mislabelled one.
    """
    from runtime.protocols.outcome_truth import OUTCOME_FIELD as _field

    assert report_of({_field: SUCCESS, "ok": False, "error": "reverted"}) == UNKNOWN
    assert report_of({_field: SUCCESS, "error": "insufficient funds"}) == UNKNOWN
    # A stated FAILURE over a structure that claims success is not a
    # contradiction to resolve — it is exactly what the field is for.
    assert report_of({_field: FAILURE, "status": "ok"}) == FAILURE


# ── a READ that ran and answered "nothing here" ──────────────────────────
#
# THE UNFIXED SIBLING AXIS. `agent_identity._verify` was taught the difference
# between "the check could not run" (FAILURE) and "the check ran and the answer
# is no" (SUCCESS). The tree has more than the two sites that rule was applied
# to. A read whose honest answer is a negative one still reached the learner as
# a broken tool, because its answer is spelled in a word the refusal vocabulary
# also owns — `invalid`, `no_position`.
#
# THE CARVE-OUT CANNOT REACH THEM AND SHOULD NOT BE WIDENED TO. Discounting a
# status on a read is for a status a STORED RECORD is assigned, where the
# payload genuinely cannot say which reading is meant. These sites are not
# ambiguous at all — the service knows perfectly well that it looked and
# answered. So it says so, in the field that exists for saying so, and the
# vocabulary keeps meaning what it means everywhere else.


async def test_a_credential_lookup_that_answered_no_is_not_a_failed_call():
    """`credential_verify` on an unknown id looks in the vault, does not find
    the credential, and answers `valid: False` — fail-closed BY DESIGN, and the
    design's own docstring says so. That is an answer, not a broken check.

    The scope pin is right beside it: verifying a credential that IS in the
    vault and has expired already reported SUCCESS, because the vault's result
    carries no refusal status. The two branches answered the same kind of
    question and were labelled differently.
    """
    env = await ServiceDispatcher({}).execute("credential_verify", params={
        "credential_id": "no_such_credential", "verifier_did": "did:matrix:v",
    })
    body = json.loads(env)
    assert body["result"].get("valid") is False, f"premise changed: {body}"
    assert body["result"].get("status") == "invalid", f"premise changed: {body}"
    assert body[OUTCOME_FIELD] == SUCCESS, (
        "a credential check that ran and answered was learned as a failed call")


async def test_a_staking_read_with_no_position_is_not_a_failed_call():
    """`get_staking_position` for a staker who has never staked. The read ran,
    the answer is a zeroed position, and `no_position` is that answer — not a
    report that the platform could not look."""
    d = ServiceDispatcher({})
    svc = d._get_registry().get("staking")

    class _ArmedWeb3:                      # the gate is not what is under test
        available = True

        @staticmethod
        def is_placeholder(_addr: str) -> bool:
            return False

    svc._web3, svc._staking_contract = _ArmedWeb3(), "0x" + "ab" * 20
    result = await svc.get_position(staker="0xNeverStaked", pool_id="default")
    assert result.get("status") == "no_position", f"premise changed: {result}"
    assert report_of(result, status_describes_the_call=False) == SUCCESS
    assert report_of(result) == SUCCESS


async def test_a_read_that_could_not_look_is_still_a_failure():
    """SCOPE PIN for the two above. Labelling the answer does not relabel the
    refusal: the same staking read, with the domain unarmed, still refuses."""
    d = ServiceDispatcher({})
    svc = d._get_registry().get("staking")
    result = await svc.get_position(staker="0xA", pool_id="default")
    assert result.get("status") == "not_deployed", f"premise changed: {result}"
    assert report_of(result, status_describes_the_call=False) == FAILURE


def test_every_tool_these_controls_dispatch_is_a_registered_tool():
    """A CONTROL THAT NAMES A TOOL THAT DOES NOT EXIST IS NOT A CONTROL.

    ``test_a_web_refusal_is_not_reported_as_a_success`` dispatched ``"web"``.
    The tool is registered as ``web_request``, so the call never reached it: the
    dispatcher answered "unknown tool", which is a genuine dispatcher-level
    failure, so the assertion passed — on the pre-fix tree too, and it would go
    on passing if ``web.py`` were reverted to prose tomorrow. The web axis was
    fixed and unguarded at the same time, and nothing said so.

    This walks the names THIS FILE dispatches and checks each one is registered,
    so a control can never again be satisfied by the dispatcher's own refusal to
    find the tool it was supposed to be testing.
    """
    from runtime.tools.dispatcher import ToolDispatcher

    registered = set(ToolDispatcher({"workspace": "."})._tools)
    tree = ast.parse(pathlib.Path(__file__).read_text())
    dispatched = {
        (node.args[0].value, node.lineno)
        for node in ast.walk(tree)
        if isinstance(node, ast.Call)
        and isinstance(node.func, ast.Name) and node.func.id == "_dispatch"
        and node.args and isinstance(node.args[0], ast.Constant)
        and isinstance(node.args[0].value, str)
    }
    assert dispatched, "the _dispatch call sites are no longer findable"
    unknown = sorted(f"{name} (line {lineno})"
                     for name, lineno in dispatched if name not in registered)
    assert unknown == [], (
        f"these controls dispatch tools that are not registered: {unknown}. "
        f"Registered: {sorted(registered)}")
