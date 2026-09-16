"""What a tool call actually reported — the ground truth outcome learning uses.

THE DEFECT THIS MODULE EXISTS FOR. ``ProtocolStack.post_action`` built its own
outcome and fed it to ``OutcomeLearning``:

    outcome = {"result": tool_result, "success": True, "status": "success"}
                                      # assume success if no exception

The ReAct loop already held the real answer one line earlier
(``tool_succeeded = outcome.ok``) and did not pass it. Worse, ``outcome.ok``
would not have been enough on its own: ``ToolDispatcher.dispatch`` wraps every
handler that does not RAISE in ``ToolOutcome.success``, and in this codebase
failure is usually RETURNED, not raised — ``{"status": "error"}``,
``{"ok": False, "reason": "insufficient funds"}``, ``{"status": "not_deployed"}``.
The platform's own mega-tool (``ServiceDispatcher.execute``) returns
``json.dumps({...})``.

So every refusal in the system was being learned as a success. That corrupts
``OutcomeLearning`` success rates, which are blended into
``TrajectoryEngine._BASE_RATES``, which drive future confidence. And
``adjust_confidence`` grades a prediction against ``actual["success"]``, so with
the label pinned True a prediction that CORRECTLY foresaw failure scored
"very_poor" and was pushed down while an overconfident one scored "excellent".
The calibration did not merely fail to learn; it learned backwards.

WHAT THIS IS NOT. It is not a string sniff. NEW-27 removed
``"error" not in text.lower()[:100]`` and ``ToolOutcome`` records the rule it
left behind: an outcome is set by whoever knows, never guessed from prose.
Nothing here searches free text. It reads NAMED FIELDS from a structure the tool
itself emitted — a dict, or a JSON object the tool serialised — and if the value
does not parse as a JSON object, no classification is attempted.

WHY IT IS NOT ``_outcome_is_real``. ``service_dispatcher._outcome_is_real``
answers a DIFFERENT question — "did a state change happen that deserves an
attestation and a public feed entry" — and correctly answers NO for a successful
read (``queried``, ``checked``, ``found``). Those calls SUCCEEDED. Reusing that
predicate here would teach the learner that every read fails, corrupting the base
rates in the opposite direction from the bug being fixed. The two questions share
a vocabulary, not an answer, so this module reuses the vocabulary — which was
measured over 182 attested actions, not invented — and splits it for its own
question. ``tests/test_outcome_learning_is_told_the_truth.py`` re-derives the
split against that source and fails if a status is added there and not
classified here, so the two cannot drift apart silently.

THE THIRD ANSWER IS THE POINT. Outcome learning must never learn from a label
nobody established, so this returns UNKNOWN rather than guessing, and
``post_action`` records nothing when it does. An unlabelled sample costs one
data point. A mislabelled one corrupts the rate. That asymmetry is why
``pending`` is UNKNOWN here and not a failure: ``insurance.process_claim``
returns it to mean "reserve insufficient, the claim was NOT paid", and
``x402.create_payment`` returns it to mean "the payment record was created and
persisted". Both are honest, their meanings are opposite, and no classification
of the string is correct for both.
"""
from __future__ import annotations

import json
from typing import Any

#: The tool stated a verdict and it was affirmative.
SUCCESS = "success"
#: The tool stated a verdict and it was negative — a refusal, a failure, a
#: precondition it would not proceed without.
FAILURE = "failure"
#: The tool spoke about its status and said something that does not decide the
#: question, or said nothing that decides it. NOT learned from.
UNKNOWN = "unknown"

# ── The vocabulary, split for THIS question ──────────────────────────────
# Source: service_dispatcher._NON_OUTCOME_STATUSES (62 strings) and
# _REAL_OUTCOME_STATUSES (101). Every one of the 163 is classified below; the
# test re-derives that and fails on an unclassified addition.

#: Refusals and failures. The call did not do what was asked.
_FAILED: frozenset[str] = frozenset({
    "already_released", "blocked", "chain_error", "compliance_hold", "declined",
    "denied", "error", "expired", "failed", "failure", "invalid",
    "invalid_request", "needs_changes", "no_position", "no_rewards",
    "no_rights_supplied", "no_submission", "not_available", "not_configured",
    "not_deployed", "not_found", "not_implemented", "not_qualified", "not_ready",
    "not_registered", "not_settlement", "nothing_to_claim", "provider_error",
    "provider_unsupported", "refused", "rejected", "unavailable", "unsupported",
})

#: Reads and checks. Not a state change — which is why _outcome_is_real says NO —
#: but the CALL succeeded, which is this module's question.
_SUCCEEDED_READ: frozenset[str] = frozenset({
    "checked", "found", "known", "metadata_only", "queried", "reviewed",
    "suspicious", "valid",
})

#: Not yet done, partially done, or documented as carrying opposite meanings in
#: different services. Never learned from, in either direction.
_INDETERMINATE: frozenset[str] = frozenset({
    "calculated_unpaid", "degraded", "grace_period", "in_progress",
    "liquidation_due_unsettled", "matched_unsettled", "no_op", "none", "noop",
    "not_started", "not_verified", "pending", "pending_verification",
    "prepared", "prepared_unsigned", "queued", "recorded_unqueued",
    "recorded_unsettled", "skipped", "unknown", "unresolved",
})


def _real_outcome_statuses() -> frozenset[str]:
    """The 101 statuses that report a real state change, read from the ONE place
    they are measured rather than copied here.

    Imported lazily and defensively: ``service_dispatcher`` pulls in the whole
    service tree, this module is imported by the tool dispatcher, and a copy kept
    locally would be a second source of truth that drifts the first time a status
    is added there. If the import is unavailable the set is empty, so an
    otherwise-recognised success degrades to UNKNOWN — not learned from, never
    mislabelled.
    """
    global _REAL_CACHE
    if _REAL_CACHE is None:
        try:
            from runtime.blockchain.services.service_dispatcher import (
                _REAL_OUTCOME_STATUSES,
            )
            _REAL_CACHE = frozenset(_REAL_OUTCOME_STATUSES)
        except Exception:
            _REAL_CACHE = frozenset()
    return _REAL_CACHE


_REAL_CACHE: frozenset[str] | None = None


def _as_object(result: Any) -> dict | None:
    """The tool's structured report, or None if it did not emit one.

    A JSON string counts: the platform's own service dispatcher returns
    ``json.dumps({...})`` and its refusals would otherwise be invisible here.
    Only a JSON OBJECT counts — a bare string, number or list is not a report
    about an outcome, and nothing is inferred from free text.
    """
    if isinstance(result, dict):
        return result
    if isinstance(result, (str, bytes, bytearray)):
        text = result.strip() if isinstance(result, str) else result.decode("utf-8", "replace").strip()
        if not text.startswith("{"):
            return None
        try:
            parsed = json.loads(text)
        except (ValueError, TypeError):
            return None
        return parsed if isinstance(parsed, dict) else None
    return None


def _status_of(value: Any) -> str:
    """A status value reduced to the string the sets are keyed on.

    ``str(LoanStatus.ACTIVE)`` is ``"LoanStatus.ACTIVE"``, not ``"active"`` — a
    ``(str, Enum)`` member does not stringify to its value, and several services
    return members directly. Same reduction as ``_normalise_status``, which this
    mirrors deliberately.
    """
    return str(getattr(value, "value", value)).strip().lower()


def report_of(result: Any) -> str:
    """What the tool said about its own outcome: SUCCESS, FAILURE or UNKNOWN.

    Order of precedence, most explicit first. A tool that states a boolean
    verdict about itself is believed over every weaker signal, because that field
    exists for no other purpose.
    """
    obj = _as_object(result)
    if obj is None:
        # No structured report. The handler returned and did not raise, and
        # nothing it emitted speaks to the question. Measured default for this
        # codebase: absence of a status is evidence of success, not of refusal
        # (17 of 182 attested actions return a success with no status at all).
        return SUCCESS

    # 1. An explicit boolean verdict.
    for key in ("ok", "success", "succeeded"):
        value = obj.get(key)
        if isinstance(value, bool):
            return SUCCESS if value else FAILURE

    # 2. A populated error field. `None`, `""`, `[]`, `{}` and `False` are a
    #    field that exists and is empty — that is not a report of an error.
    error = obj.get("error")
    if error not in (None, "", [], {}, False) or obj.get("errors") not in (None, "", [], {}, False):
        return FAILURE

    # 3. Positive evidence that the service acted outranks a lifecycle status:
    #    a record-creating action reports the NEW RECORD's state, not its own
    #    disposition (x402.create_payment returns "pending" having genuinely
    #    minted, signed and persisted a payment).
    if obj.get("created") is True:
        return SUCCESS

    # 4. Disclosure flags: the record says plainly that nothing moved. That is
    #    not a clean success, and it is not necessarily a failed CALL either.
    if obj.get("settled") is False or obj.get("value_moved") is False:
        return UNKNOWN

    # 5. The status vocabulary.
    if "status" in obj:
        status = _status_of(obj.get("status"))
        if status in _FAILED:
            return FAILURE
        if status in _SUCCEEDED_READ:
            return SUCCESS
        if status in _INDETERMINATE:
            return UNKNOWN
        if status in _real_outcome_statuses():
            return SUCCESS
        # Present but unrecognised is not evidence of anything. It is exactly
        # the case a new status string lands in, and guessing is how a new
        # refusal idiom would get learned as a success.
        return UNKNOWN

    # 6. A structured report that says nothing about its outcome — the
    #    successful read that returns only data. Same measured default as (1).
    return SUCCESS


def learnable_success(report: str) -> bool | None:
    """True, False, or None for 'do not learn from this sample'."""
    if report == SUCCESS:
        return True
    if report == FAILURE:
        return False
    return None
