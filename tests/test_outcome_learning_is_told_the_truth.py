"""Outcome learning must never learn from a label the system made up.

THE DEFECT THIS EXISTS FOR. The ReAct loop computes the real execution result —
``tool_succeeded = outcome.ok`` — and then calls ``protocol_stack.post_action()``
WITHOUT it. post_action then built its own outcome:

    outcome = {"result": tool_result, "success": True, "status": "success"}
                                      # assume success if no exception

and fed that to ``OutcomeLearning.record_outcome`` and, through it, to the
Trajectory base-rate blend and ``adjust_confidence``. Two separate things were
wrong, and the second is worse than the first:

  1. A tool the DISPATCHER knew had failed (denied, timed out, raised) was
     recorded as a success, because the success state was never passed along.

  2. A tool that reports failure the way most tools in this repository report it
     — by RETURNING a structure, ``{"status": "error", ...}`` or
     ``{"ok": False, "reason": "insufficient funds"}`` — was recorded as a
     success by the dispatcher too. ``dispatch()`` wraps every non-raising
     handler in ``ToolOutcome.success``. At the time of writing the tree carries
     245 ``"error":`` returns, 200 ``"status": "error"`` and 16
     ``"status": "failed"``; structured failure is the NORM here, not the
     exception.

The consequence is not merely a wrong number. ``adjust_confidence`` scores a
prediction against ``actual.get("success", False)``, so with the label pinned to
True a prediction that CORRECTLY predicted failure was graded "very_poor" and
pushed down, while an overconfident one was graded "excellent". The calibration
did not just fail to learn — it learned backwards.

WHAT THIS FILE DOES NOT DO. It does not sniff the result string. NEW-27 removed
exactly that (``"error" not in text.lower()[:100]``) and ``ToolOutcome`` records
the rule it left behind: ``ok`` is set explicitly by whoever knows, never
guessed from prose. The truth here is read from the handler's STRUCTURED return
value, and where that value does not say, the outcome is recorded as UNKNOWN and
is not learned from at all — an unlabelled sample is strictly better than a
mislabelled one.
"""
from __future__ import annotations

import asyncio
from unittest.mock import AsyncMock

import pytest

from runtime.protocols.integration import ProtocolStack
from runtime.tools.dispatcher import ToolDispatcher, ToolOutcome


# ── The dispatcher must see a structured failure for what it is ──────────

def _dispatcher_with(handler):
    d = ToolDispatcher({})
    d.register("probe", handler, {"name": "probe", "description": "d",
                                  "parameters": {"type": "object", "properties": {}}})
    return d


@pytest.mark.parametrize("payload", [
    {"ok": False, "reason": "insufficient funds"},
    {"success": False, "error": "nonce too low"},
    {"status": "error", "message": "reverted"},
    {"status": "failed"},
    {"error": "no such contract"},
    # Not a guess: `not_deployed` is named as a refusal idiom by the census in
    # service_dispatcher._NON_OUTCOME_STATUSES, measured over 182 attested
    # actions. An earlier draft of this file called it ambiguous by reasoning
    # about the word; the repository had already measured it.
    {"status": "not_deployed"},
])
def test_a_tool_that_returns_a_failure_is_not_reported_as_a_success(payload):
    async def handler():
        return payload
    out = asyncio.run(_dispatcher_with(handler).dispatch("probe", {}))
    assert out.reported == "failure", (
        f"a handler returning {payload!r} was reported as {out.reported!r}; "
        "structured failure is how most tools in this repository fail")
    assert out.learnable_success is False


@pytest.mark.parametrize("payload", [
    {"ok": True, "tx": "0xabc"},
    {"status": "success", "value": 1},
    {"success": True},
    {"status": "deployed"},          # from the measured real-outcome set
    {"status": "queried"},           # a READ: not a state change, but the call worked
    # A structure with no outcome vocabulary at all. An earlier draft called
    # this UNKNOWN; that was wrong and would have starved the learner, because
    # the measured default in this codebase is that absence of a status is
    # evidence of success (17 of 182 attested actions return one).
    {"state": "whatever"},
    {"balance": 100},
])
def test_a_tool_that_returns_a_success_is_reported_as_one(payload):
    async def handler():
        return payload
    out = asyncio.run(_dispatcher_with(handler).dispatch("probe", {}))
    assert out.reported == "success"
    assert out.learnable_success is True


@pytest.mark.parametrize("payload", [
    {"status": "pending"},
    {"status": "in_progress"},
    {"status": "a_status_nobody_has_classified_yet"},
    {"settled": False, "record": "written"},
])
def test_a_tool_whose_report_does_not_say_is_left_UNKNOWN_not_assumed(payload):
    """The third answer, and the reason it has to exist.

    `pending` is returned by `insurance.process_claim` to mean "reserve
    insufficient, the claim was NOT paid" and by `x402.create_payment` to mean
    "the payment record was created and persisted". Both are honest and their
    meanings are opposite, so no classification of the string is correct for
    both — that argument is the service dispatcher's own, measured there, not
    reasoned here. A status nobody has classified is the case a NEW refusal
    idiom arrives in, and guessing is how it would get learned as a success.
    """
    async def handler():
        return payload
    out = asyncio.run(_dispatcher_with(handler).dispatch("probe", {}))
    assert out.learnable_success is None, (
        f"{payload!r} was labelled {out.learnable_success!r}; it says nothing about success")


def test_a_plain_string_return_is_still_a_success():
    """The common case must not regress: a tool that returns text and does not
    raise has succeeded by the only evidence there is."""
    async def handler():
        return "here are the contents"
    out = asyncio.run(_dispatcher_with(handler).dispatch("probe", {}))
    assert out.ok is True and out.learnable_success is True


def test_a_raising_tool_is_a_failure_not_an_unknown():
    async def handler():
        raise RuntimeError("boom")
    out = asyncio.run(_dispatcher_with(handler).dispatch("probe", {}))
    assert out.ok is False and out.learnable_success is False


def test_the_client_preview_contract_from_NEW_27_is_unchanged():
    """A structured failure is still the tool's own output to the CLIENT.

    Reclassifying the outcome for LEARNING must not start redacting content the
    client was already receiving, nor hand the model less than it had. `ok`
    still means 'the dispatcher completed the call'.
    """
    async def handler():
        return {"status": "error", "message": "reverted"}
    out = asyncio.run(_dispatcher_with(handler).dispatch("probe", {}))
    assert out.ok is True, "ok governs the NEW-27 redaction contract and must not flip"
    assert "reverted" in out.model_text
    assert "reverted" in out.client_preview


# ── post_action must be told, and must not invent ────────────────────────

def _stack_with_recorder():
    stack = ProtocolStack({}, "tester")
    recorded: list[dict] = []

    class _Learner:
        async def record_outcome(self, action, result, context):
            recorded.append(result)
        async def get_learned_patterns(self, action_type):
            return []
        async def adjust_confidence(self, prediction, actual):
            return {}

    stack._outcome_learning = _Learner()
    stack._trajectory = None
    stack._jarvis = None
    return stack, recorded


def test_post_action_records_the_failure_it_was_given():
    stack, recorded = _stack_with_recorder()
    asyncio.run(stack.post_action(
        "probe", {}, "the text", {}, succeeded=False, status="failure", code="denied"))
    assert recorded, "nothing was recorded"
    assert recorded[0]["success"] is False, (
        f"post_action recorded {recorded[0]['success']!r} for a call it was told had FAILED")
    assert recorded[0]["status"] != "success"


def test_post_action_does_not_learn_from_an_unknown_outcome():
    stack, recorded = _stack_with_recorder()
    asyncio.run(stack.post_action(
        "probe", {}, "the text", {}, succeeded=None, status="unknown"))
    assert recorded == [], (
        "an outcome with no known ground truth was recorded anyway; "
        "outcome learning must never learn from a label nobody established")


def test_post_action_still_records_a_real_success():
    stack, recorded = _stack_with_recorder()
    asyncio.run(stack.post_action(
        "probe", {}, "the text", {}, succeeded=True, status="success"))
    assert len(recorded) == 1 and recorded[0]["success"] is True


def test_a_failed_tool_does_not_mark_a_plan_step_complete():
    """§CD sibling axis. The same post_action body tells Jarvis the plan step
    finished, on the same 'no exception' assumption."""
    stack, _ = _stack_with_recorder()

    class _Jarvis:
        _active_plan = {"id": "p"}
        completed: list = []
        def suggest_next_action(self):
            return {"action": "probe", "step_id": "s1"}
        def mark_step_complete(self, step_id):
            self.completed.append(step_id)

    jarvis = _Jarvis()
    stack._jarvis = jarvis
    asyncio.run(stack.post_action(
        "probe", {}, "the text", {}, succeeded=False, status="failure", code="tool_timeout"))
    assert jarvis.completed == [], (
        "a plan step was marked COMPLETE for a tool call that failed")


# ── the loop must pass it, not recompute it ──────────────────────────────

def test_the_react_loop_hands_post_action_the_real_outcome():
    """A property about the wiring: the call site must forward the outcome it
    already holds. Asserted on the source because the loop's own integration
    test cannot distinguish 'passed True' from 'defaulted to True'."""
    import ast
    import pathlib
    src = (pathlib.Path(__file__).resolve().parent.parent / "runtime/react_loop.py").read_text()
    tree = ast.parse(src)
    calls = [n for n in ast.walk(tree)
             if isinstance(n, ast.Call)
             and isinstance(n.func, ast.Attribute)
             and n.func.attr == "post_action"]
    assert calls, "no post_action call found in the ReAct loop"
    for call in calls:
        kw = {k.arg for k in call.keywords}
        assert "succeeded" in kw, (
            "the ReAct loop calls post_action without passing the execution result "
            "it already computed; post_action then assumes success")


# ── the vocabulary must not drift from the place it was measured ─────────

def test_every_status_the_services_emit_is_classified_for_learning():
    """One measured source, two questions.

    `service_dispatcher` holds the census of status strings — which ones report
    a real state change and which do not. This module asks a DIFFERENT question
    of the same vocabulary ("did the call succeed", where a read succeeds and an
    attestation-worthy state change is not required), so it keeps its own split
    rather than reusing the predicate. That is a second classification of one
    vocabulary, and the failure mode is drift: a status added to the census that
    nobody classifies here would silently become UNKNOWN and stop being learned
    from — or worse, a new refusal idiom would.

    So the split is re-derived here. If this fails, classify the named status in
    runtime/protocols/outcome_truth.py; do not edit this test to pass.
    """
    from runtime.blockchain.services.service_dispatcher import (
        _NON_OUTCOME_STATUSES, _REAL_OUTCOME_STATUSES,
    )
    from runtime.protocols.outcome_truth import (
        _FAILED, _INDETERMINATE, _SUCCEEDED_READ,
    )
    classified = _FAILED | _SUCCEEDED_READ | _INDETERMINATE
    unclassified = set(_NON_OUTCOME_STATUSES) - classified
    assert not unclassified, (
        "these statuses are emitted by the services but carry no learning "
        f"classification: {sorted(unclassified)}")

    # The real-outcome half is consumed wholesale as success, so it needs no
    # per-string split — but it must not overlap the failure set, which would
    # make one string mean both things depending on lookup order.
    contradiction = set(_REAL_OUTCOME_STATUSES) & _FAILED
    assert not contradiction, (
        f"classified as BOTH a real outcome and a failure: {sorted(contradiction)}")


def test_the_three_learning_sets_do_not_overlap_each_other():
    from runtime.protocols.outcome_truth import (
        _FAILED, _INDETERMINATE, _SUCCEEDED_READ,
    )
    pairs = [("failed", _FAILED, "read", _SUCCEEDED_READ),
             ("failed", _FAILED, "indeterminate", _INDETERMINATE),
             ("read", _SUCCEEDED_READ, "indeterminate", _INDETERMINATE)]
    for an, a, bn, b in pairs:
        assert not (a & b), f"{an} and {bn} both claim: {sorted(a & b)}"


def test_the_platform_mega_tool_json_string_is_classified():
    """ServiceDispatcher.execute returns `json.dumps({...})`, so its refusals
    arrive as a STRING. Classifying dicts alone would have fixed almost nothing
    on the largest tool surface in the platform."""
    import json
    from runtime.protocols.outcome_truth import report_of
    assert report_of(json.dumps({"status": "error", "message": "x"})) == "failure"
    assert report_of(json.dumps({"status": "not_deployed"})) == "failure"
    assert report_of(json.dumps({"status": "deployed"})) == "success"


def test_free_text_is_never_classified_from_its_prose():
    """The rule NEW-27 left behind: an outcome is never guessed from prose.

    A tool whose SUCCESSFUL output happens to contain the word error must not be
    recorded as a failure — that was the original bug, in the other direction.
    """
    from runtime.protocols.outcome_truth import report_of
    assert report_of("the error log is empty; all checks passed") == "success"
    assert report_of("ERROR ERROR ERROR") == "success"
    assert report_of("{not json after all: error}") == "success"
