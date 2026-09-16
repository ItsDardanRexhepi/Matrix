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
from collections.abc import Iterable
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

#: The failure-vocabulary statuses that a STORED RECORD is assigned in this tree,
#: as opposed to being returned inline as a call's disposition. Measured, not
#: chosen, and measured over BOTH ways this tree writes a record: an AST census
#: of every ``<record>["status"] = <literal>`` assignment under ``runtime/``
#: (42 states) together with every record CONSTRUCTED with its status in the
#: dict display and stored on ``self`` (16 states, 14 of which the first scan
#: never saw). Exactly four of the 56 collide with the refusal vocabulary —
#: ``fundraising._fail_campaign`` writes ``failed``, ``gaming.vetting`` writes
#: ``rejected`` and ``needs_changes``, ``x402``/``pooled_purchase`` write
#: ``expired``.
#:
#: WHY THE DISTINCTION HAS TO EXIST. ``get_campaign`` is a READ. It succeeds, and
#: it returns a campaign whose own ``status`` is ``failed`` because the campaign
#: missed its deadline. The CALL did exactly what was asked. Reading that record
#: state as the call's verdict would teach the learner that reads fail — the same
#: corruption as the defect this module was written for, facing the other way.
#: ``tests/test_envelopes_do_not_hide_refusals.py`` re-derives the census and
#: fails if a new record state collides with the refusal vocabulary.
_SUBJECT_LIFECYCLE: frozenset[str] = frozenset({
    "expired", "failed", "needs_changes", "rejected",
})

#: The field a layer that KNOWS uses to STATE the verdict of the call.
#:
#: A wrapper may report on the wrapping and never on what it wraps — unless it
#: says so outright, and that is what this field is for. ``report_of`` believes
#: it over every other signal, including its own unwrapping, because the layer
#: that wrote it is the layer that held the service's structured report AND knew
#: which action produced it. ``ServiceDispatcher.execute`` knows whether the
#: action changes state; nothing downstream of it does.
#:
#: NOT ONLY A WRAPPER. ``agent_identity._verify`` writes it into a bare service
#: payload, because it is the layer that knows the difference between a check
#: that could not run and a check that ran and answered no — a difference no
#: reader can see in the payload. Any layer holding a fact the vocabulary cannot
#: express may state it here; the rule is that it must HOLD the fact, not infer
#: it, and ``report_of`` reads the field wherever it appears, at any depth.
#:
#: AND THAT IS WHY IT IS NAMESPACED. The first version of this field was the
#: bare word ``outcome``, and the word was already taken: an AST census finds it
#: used as a DATA key at 15 sites under ``runtime/`` — a prediction market's
#: resolved outcome (``gaming.resolve_market`` writes the CALLER's argument into
#: the record it returns), a dispute's outcome, a governance proposal's outcome,
#: an agent interaction's outcome in ``agent_identity.reputation``, whose literal
#: values are ``"success"`` and ``"failure"``. Resolving a prediction market TO
#: "failure" therefore made the platform state that the CALL had failed — for an
#: action the same response attested as REAL — and the client was shown a cross
#: for something that happened. Nothing tells a domain word from a platform word
#: by looking at it, so the platform stopped using a domain word.
#: ``tests/test_envelopes_do_not_hide_refusals.py`` keeps the name unspoken by
#: anything but this module and re-derives the census that motivates it.
OUTCOME_FIELD = "call_outcome"

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


# ── the envelope ─────────────────────────────────────────────────────────
#
# WHERE THE FIRST VERSION OF THIS MODULE LANDED SHORT. It reads the structure
# the tool returned. In this platform the structure the tool returned is almost
# never the structure the next layer hands on: three transport envelopes stand
# between a service's refusal and every consumer of it, and each states a verdict
# of its own over it.
#
#   ServiceDispatcher.execute  ->  {"status": "ok", "result": <the refusal>}
#   ServiceRoutes._ok          ->  {"status": "ok", "data":   <the refusal>}
#   MobileResponse.ok          ->  {"ok": true,     "data":   <the refusal>}
#
# `report_of` believed the outermost verdict — correctly, by its own rule, since
# that IS a named field a layer set deliberately. So `platform_action`, the one
# handler through which the agent reaches all 45 services, relayed every refusal
# to the learner as a success. The fix was real and it reached nothing that went
# through the mega-tool.
#
# The envelope is not lying about itself: `execute` really did complete, `_ok`
# really did serve the request. That is the whole difficulty — the transport's
# truthful claim about ITSELF is written into the same field name a service uses
# to report ITS outcome. The rule below is that the reader does not have to tell
# them apart: A WRAPPER MAY REPORT ON THE WRAPPING, AND NEVER ON WHAT IT WRAPS.
#
# NARROW ON PURPOSE. Unwrapping fires only when the outer object states an
# AFFIRMATIVE verdict about itself and carries another structured report under
# one of these keys. An object that says nothing, or that reports its own
# failure, is read exactly as before — there is no envelope to see through. And
# the combination only ever weakens: a wrapped FAILURE makes the whole FAILURE, a
# wrapped UNKNOWN makes it UNKNOWN, and nothing here can turn a refusal into a
# success. Downgrading everything would teach the learner that the platform
# always fails, which is the same defect facing the other way.

#: The keys the platform's own envelopes carry their payload under. Read off the
#: three sites above, not invented: `result` is the dispatcher's and the
#: capability registry's, `data` is both HTTP envelopes'.
_WRAPPED_KEYS: tuple[str, ...] = ("result", "data")

#: How deep to follow them. /bridge/v1/action nests two (MobileResponse.ok over
#: ServiceDispatcher.execute); the limit is slack, not a budget.
_MAX_UNWRAP = 4


def _asserts_success(obj: dict) -> bool:
    """True when *obj* states an affirmative verdict ABOUT ITSELF.

    The signature of a transport envelope: a boolean verdict field set True, or
    a status the vocabulary resolves to SUCCESS. `{"status": "ok"}` qualifies
    because `ok` is one of the 101 measured real-outcome statuses.
    """
    for key in ("ok", "success", "succeeded"):
        if obj.get(key) is True:
            return True
    if "status" in obj:
        status = _status_of(obj.get("status"))
        return status in _SUCCEEDED_READ or status in _real_outcome_statuses()
    return False


def _wrapped_report(obj: dict, depth: int) -> str | None:
    """The report of the structure(s) *obj* carries, or None if it carries none.

    Several keys are combined by taking the weakest, so a wrapper that carries
    both a refusal and a success cannot be read as a clean success.
    """
    if depth >= _MAX_UNWRAP:
        return None
    reports = [
        report_of(obj[key], _depth=depth + 1)
        for key in _WRAPPED_KEYS
        if key in obj and _as_object(obj[key]) is not None
    ]
    if not reports:
        return None
    if FAILURE in reports:
        return FAILURE
    if UNKNOWN in reports:
        return UNKNOWN
    return SUCCESS


#: The three answers, keyed by the string a layer may write them as.
#:
#: WHY THIS EXISTS RATHER THAN `stated.strip().lower()`. That expression builds
#: a NEW string. It is equal to `SUCCESS` and it is not `SUCCESS`, and the
#: readers this module was written for compare with `is` — `report_of(result) is
#: SUCCESS` at five sites added in one pass, because every other path returns
#: the interned module constant and the idiom looked safe. It was safe until a
#: layer started STATING its verdict, which `ServiceDispatcher.execute` and the
#: Trinity hand-off now do. A landed attestation graded not-landed by an
#: identity comparison is a SECOND on-chain write.
#:
#: The contract is now the one the readers assumed: `report_of` returns one of
#: these three objects, never a copy of one. `tests/test_the_fix_reaches_what_it
#: _aimed_at.py` pins it.
_CANONICAL: dict[str, str] = {SUCCESS: SUCCESS, FAILURE: FAILURE, UNKNOWN: UNKNOWN}


def envelope_chain(result: Any, *, _depth: int = 0) -> list[dict]:
    """*result* and every structured report it carries, outermost first.

    THE SAME UNWRAPPING, FOR THE CALLERS THAT NEED THE PAYLOAD AND NOT THE
    VERDICT. ``report_of`` reads THROUGH the platform's envelopes; a transport
    that has to ACT on the refusal — decide the HTTP status it deserves, relay
    the service's own detail — needs the structures themselves. Two gateway
    surfaces unwrapped by hand and a third read only the outermost ``status``,
    so ``refusal_http_status`` and ``report_of`` disagreed on exactly the shape
    ``POST /api/v1/capabilities/{id}/invoke`` relays: outcome ``failure``, HTTP
    200. One walk, the same keys, the same JSON-string handling.

    A non-object returns an empty list: there is no report to read.
    """
    obj = _as_object(result)
    if obj is None:
        return []
    chain = [obj]
    if _depth >= _MAX_UNWRAP:
        return chain
    for key in _WRAPPED_KEYS:
        if key in obj and _as_object(obj[key]) is not None:
            chain.extend(envelope_chain(obj[key], _depth=_depth + 1))
    return chain


def _stated_verdict(obj: dict) -> str | None:
    """The verdict *obj* states outright in ``OUTCOME_FIELD``, as the CONSTANT.

    None when the field is absent or holds something that is not one of the
    three answers — an unrecognised value is not a fourth answer, it is no
    answer, and the reading falls through to the rest of the predicate.
    """
    stated = obj.get(OUTCOME_FIELD)
    if not isinstance(stated, str):
        return None
    return _CANONICAL.get(stated.strip().lower())


def _declares_its_own_failure(obj: dict) -> bool:
    """True when *obj* states a negative verdict about itself in a named field.

    The two unambiguous ones only: an explicit boolean verdict set False, and a
    populated singular ``error``. Deliberately NOT the status vocabulary — a
    record's lifecycle status is the field this module spends most of its length
    refusing to read as a call's verdict, and reading it here would undo that.
    """
    for key in ("ok", "success", "succeeded"):
        if obj.get(key) is False:
            return True
    return obj.get("error") not in (None, "", [], {}, False)


def report_of(result: Any, *, status_describes_the_call: bool = True,
              _depth: int = 0) -> str:
    """What the tool said about its own outcome: SUCCESS, FAILURE or UNKNOWN.

    A structure's own report, weakened by the report of anything it is carrying:
    a wrapper may report on the wrapping and never on what it wraps.

    ``status_describes_the_call`` is the one fact a caller may hold that this
    module cannot read off the payload: whether the ``status`` field in front of
    it is the SERVICE's disposition or a RECORD's lifecycle. Callers that know —
    ``ServiceDispatcher.execute`` holds ``_STATE_MODIFYING_ACTIONS`` — pass it.
    Callers that do not leave it True, which is the reading the vocabulary was
    measured under.
    """
    obj = _as_object(result)

    # 0. A layer that STATES the verdict. This outranks the unwrapping below,
    #    and outranks the structure's own verdict about itself, because it is
    #    the one signal written by a layer that had both the payload and the
    #    context to read it — the definition of "set by whoever knows".
    if obj is not None:
        stated = _stated_verdict(obj)
        if stated is not None:
            # …AND IT STILL CANNOT TALK A REFUSAL INTO A SUCCESS. The field
            # outranks what this module INFERS from the vocabulary. It does not
            # outrank the same structure flatly contradicting it: a payload that
            # states success while declaring `ok: false` or carrying a populated
            # `error` is a payload whose truth nobody established, and the third
            # answer is the whole point of this module. Not learned from, in
            # either direction — an unlabelled sample costs one data point, a
            # mislabelled one corrupts the rate.
            #
            # Only an affirmative claim can be contradicted this way. A stated
            # FAILURE over a structure that reports success is not a conflict to
            # resolve; it is exactly what the field exists for (an envelope's
            # truthful `"status": "ok"` over a service's refusal).
            if stated == SUCCESS and _declares_its_own_failure(obj):
                return UNKNOWN
            return stated

    own = _own_report(obj, status_describes_the_call=status_describes_the_call)
    if obj is None or own != SUCCESS or not _asserts_success(obj):
        # Nothing to see through. Either there is no structure, or it already
        # reports something other than a clean success, or it makes no
        # affirmative claim for a wrapped report to contradict.
        return own
    wrapped = _wrapped_report(obj, _depth)
    return own if wrapped is None else wrapped


def foreign_report_of(result: Any) -> str:
    """What a structure THIS CODEBASE DID NOT EMIT said about its own outcome.

    THE DEFAULT IS THE WHOLE DIFFERENCE. ``report_of`` answers SUCCESS when a
    result carries no report at all, and that is not a guess: it is measured
    over 182 attested actions OF THIS TREE, where 17 genuine successes return no
    status and every refusal idiom is explicit. The measurement is a fact about
    code we wrote. It says nothing about a payment gateway, a courier API or any
    other foreign party, and a party whose failure idiom we have not measured is
    exactly the party whose silence must not be read as a yes.

    Pointed at a gateway, the measured default turned a decline delivered as an
    HTTP response object, a plain string or ``None`` into a settled charge:
    ``SubscriptionService`` advanced ``total_paid``, set ``charges_settled`` and
    rolled the billing period forward for money nobody took. That is the defect
    this module exists for, inside the fix written for it.

    So: only an EXPLICIT verdict is believed, and everything else is the third
    answer. UNKNOWN costs the caller a retry or a human; SUCCESS costs a
    customer a charge that was refused.
    """
    obj = _as_object(result)
    if obj is None:
        return UNKNOWN
    if _stated_verdict(obj) is not None:
        return report_of(obj)
    for key in ("ok", "success", "succeeded"):
        if isinstance(obj.get(key), bool):
            return report_of(obj)
    if obj.get("error") not in (None, "", [], {}, False):
        return FAILURE
    if "status" in obj:
        # The status vocabulary is this tree's, measured on this tree. A foreign
        # `status` is read only where it lands in the vocabulary unambiguously;
        # anything else — including a word we have never seen — is UNKNOWN,
        # which is what `report_of` already answers for an unrecognised status.
        return report_of(obj)
    return UNKNOWN


def refusal(message: str, *, code: str | None = None) -> str:
    """A structured refusal, for a tool whose only failure channel was prose.

    THE HALF OF THE CONTRACT THAT HAD NO WRITER. This module reads a verdict out
    of named fields, and a tool that answers ``"Error: command timed out"`` has
    no named fields to read — so its every failure fell to the measured default
    and was learned as a success. The four builtin tools and the 91 error paths
    across the 20 blockchain capability modules were all in that position.

    The fix is not to read the prose (NEW-27 removed exactly that, and
    ``"error" not in text.lower()[:100]`` is wrong in both directions). It is to
    let those tools SAY it, in the same shape the rest of the platform already
    refuses in: ``{"ok": false, "error": ...}``. The message is preserved
    verbatim, so the agent reads what it always read.

    Kept beside the reader deliberately: one module owns both halves of the
    contract, so a change to what a refusal looks like cannot land on one side
    only.
    """
    payload: dict[str, Any] = {"ok": False, "error": message}
    if code:
        payload["code"] = code
    return json.dumps(payload)


def _own_report(obj: dict | None, *, status_describes_the_call: bool = True) -> str:
    """What this structure says about ITSELF, ignoring anything it carries.

    Order of precedence, most explicit first. A tool that states a boolean
    verdict about itself is believed over every weaker signal, because that field
    exists for no other purpose.
    """
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
    #
    #    SINGULAR ONLY, AND THAT IS MEASURED. `error` is this tree's refusal
    #    idiom (245 `"error":` returns). `errors` is not: an AST census finds
    #    four `errors` keys in the whole tree and every one is DATA — a
    #    verifier's findings list (`credential_vault.verify_credential`,
    #    `selective_disclosure`, `did_identity.service`) or a counter
    #    (`agent_identity.reputation`, which returns `"errors": 0`). Not one of
    #    them reports that the CALL failed. Reading the plural as a verdict
    #    labelled a credential check that ran perfectly — and answered "this
    #    credential has expired", which is a real answer — as a failed call, and
    #    labelled an agent with three logged errors as a failed lookup.
    error = obj.get("error")
    if error not in (None, "", [], {}, False):
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
            if not status_describes_the_call and status in _SUBJECT_LIFECYCLE:
                # The caller told us this action does not change state, and this
                # is one of the four statuses a stored record is assigned. So the
                # field may be the SUBJECT's lifecycle (`get_campaign` on a
                # campaign that missed its deadline) or the call's refusal, and
                # from the payload the two are identical. The third answer: do
                # not learn from it. A status no record is ever assigned —
                # `error`, `not_found`, `not_deployed` — is unaffected and is
                # still a refusal on a read.
                return UNKNOWN
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


def combine(reports: Iterable[str]) -> str:
    """One verdict over several sub-reports of the SAME operation.

    For the fan-outs: a post sent to two platforms, a job whose agent made five
    tool calls, a batch submitted attestation by attestation. Each part reports
    for itself and the caller has to write ONE record.

        every part SUCCESS (or no parts) -> SUCCESS
        every part FAILURE               -> FAILURE
        anything else                    -> UNKNOWN

    THE MIXED CASE IS THE WHOLE POINT, and it is why this is not `all()` or
    `any()`. One platform took the post and one refused it; the record is
    neither "published" nor "failed", and writing either loses the fact the
    record is the only evidence of. UNKNOWN is not a hedge here — it is the
    accurate answer, and it keeps the caller from billing, learning from or
    announcing something nobody established.

    No parts is SUCCESS, not UNKNOWN: an operation that fanned out to nothing
    had nothing go wrong. The caller that needs "did anything happen at all"
    is asking a different question and should count the parts.
    """
    seen = set(reports)
    if not seen or seen == {SUCCESS}:
        return SUCCESS
    if seen == {FAILURE}:
        return FAILURE
    return UNKNOWN
