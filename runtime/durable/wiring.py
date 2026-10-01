"""The wiring: the mode, the canary, and the engine the service dispatcher (and
the twin tools' dispatch) consult.

``engines.durable.mode`` — ``MATRIX_DURABLE_MODE`` wins, then the config, then
"off"; read once at startup:

* ``off`` — the default. No engine is installed; every call site's first check
  finds none and runs exactly the code it ran before this package existed. No
  Idempotency-Key is read. The four tables exist, empty, because the database
  creates them whatever the mode.
* ``shadow`` — the engine records and owns nothing. Every journaled action gets
  a run; the attestation and the feed entry the legacy path delivers get
  outbox rows written as already handed off; an Idempotency-Key is recorded
  against the first run that used it. Every answer is the answer mode off
  gives, and a replay runs again, as it does with the mode off. Nothing waits
  for the database: a run that cannot be opened at once is not recorded, and
  an end that cannot be written at once is kept and written again each tick.
* ``on`` — for the actions in the canary, the run is the only lifecycle path:
  the run is written before the effect call begins, and an action whose run
  cannot be written is not run; the outbox loop sends its attestation (tried
  again with backoff only while an answer says it did not land and was not
  sent; one sent and not confirmed is never sent again) and publishes its feed
  entry (once); a replayed Idempotency-Key gets the first answer and runs
  nothing. An engine that cannot be built in mode on is replaced by one over
  no database: every action it would own is refused, as a run that cannot be
  written is, and ``healthy`` is False, so ``/ready`` says so.

THE CANARY, in the order it moves: first the twin tools' platform-key signing
calls (``runtime/security/action_map.py`` ``SIGNING_ACTIONS``), then every
state-modifying name the service dispatcher serves (``_STATE_MODIFYING_ACTIONS``).
``CANARY`` names the stages; ``engines.durable.canary`` (or
``MATRIX_DURABLE_CANARY``) names how many of them mode on covers, first stage
first, and by default covers both.

WHAT THE ENGINE NEVER DOES, IN ANY MODE. It never decides whether an action is
allowed: every entry point's gate has answered before any of this runs, and a
replay passes the gate again like any request. It never decides what an
action's outcome was: a run's state says whether its call began and whether it
answered, and the words on its steps are the ones the layer that made the call
already computed. It never runs an action a second time. The one refusal it
adds, in mode on, is to not start an effect it could not first record.

COPIES, NEVER THE LIVE DICTS. The parameters and the answer are only digested
here; the attestation and feed payloads the outbox holds are deep copies taken
when the run ends, so nothing a delivery does reaches the dispatcher's own
dicts and nothing the dispatcher does afterwards reaches a delivery.
"""

from __future__ import annotations

import asyncio
import contextlib
import contextvars
import copy
import json
import logging
import os
import time
from dataclasses import dataclass, field
from typing import Any, Awaitable, Callable

from runtime.durable import journal, keys, outbox
from runtime.durable.journal import Tx

logger = logging.getLogger(__name__)

MODES: tuple[str, ...] = ("off", "shadow", "on")
TWINS = "twins"
STATE_MODIFYING = "state_modifying"
#: The stages of the canary mode on covers, in the order they moved.
CANARY: tuple[str, ...] = (TWINS, STATE_MODIFYING)

#: The surface the bridge's keys are scoped to.
BRIDGE_ACTION = "bridge.action"

#: A run whose record could not be written: in memory only, nothing more is written.
UNRECORDED = "UNRECORDED"

_OUTCOME_FIELD = "call_outcome"   # runtime.protocols.outcome_truth.OUTCOME_FIELD
_FAILURE = "failure"              # runtime.protocols.outcome_truth.FAILURE


def durable_mode(config: Any) -> str:
    """``MATRIX_DURABLE_MODE``, then ``engines.durable.mode``, then "off". A value
    that is not one of MODES is logged and read as "off": an unrecognised switch
    never moves lifecycle authority."""
    engines = config.get("engines") if isinstance(config, dict) else None
    durable = engines.get("durable") if isinstance(engines, dict) else None
    configured = durable.get("mode") if isinstance(durable, dict) else None
    raw = os.environ.get("MATRIX_DURABLE_MODE") or configured or "off"
    mode = str(raw).strip().lower()
    if mode not in MODES:
        logger.warning("Unknown engines.durable.mode %r; durable execution stays off.", raw)
        return "off"
    return mode


def durable_canary(config: Any) -> tuple[str, ...]:
    """The stages of the canary mode on covers: ``MATRIX_DURABLE_CANARY``, then
    ``engines.durable.canary``, then all of ``CANARY``. A value names stages
    first to last, as a comma-separated string or a list — ``"twins"`` covers
    the twin tools' signing calls alone, ``"twins,state_modifying"`` both — and
    must be the canary's first stages in order: a later stage never moves
    before an earlier one. Anything else is logged and read as no stage, so
    mode on then owns nothing and records as shadow does: an unrecognised
    switch never moves lifecycle authority."""
    engines = config.get("engines") if isinstance(config, dict) else None
    durable = engines.get("durable") if isinstance(engines, dict) else None
    configured = durable.get("canary") if isinstance(durable, dict) else None
    raw = os.environ.get("MATRIX_DURABLE_CANARY") or configured
    if raw is None or (isinstance(raw, str) and not raw.strip()):
        return CANARY
    parts: list[str] | None = None
    if isinstance(raw, str):
        parts = [p.strip().lower() for p in raw.split(",")]
    elif isinstance(raw, (list, tuple)) and all(isinstance(p, str) for p in raw):
        parts = [p.strip().lower() for p in raw]
    if parts and tuple(parts) == CANARY[:len(parts)]:
        return tuple(parts)
    logger.warning("Unknown engines.durable.canary %r (the stages, first to last, are %s); "
                   "mode on owns no stage.", raw, ", ".join(CANARY))
    return ()


# ── the process-wide engine ─────────────────────────────────────────────────

_engine: "DurableEngine | None" = None


def install(engine: "DurableEngine | None") -> "DurableEngine | None":
    """Install *engine* process-wide (None removes it) and return the one it
    replaces. Process-wide because the gateway's shared dispatcher is not the
    only one: the capability-invoke route and the bridge's cold fallback build
    their own, and every one of them must journal."""
    global _engine
    previous, _engine = _engine, engine
    return previous


def current() -> "DurableEngine | None":
    """The installed engine, or None — which is mode off."""
    return _engine


# ── the bridge's key, for the one dispatch it makes ─────────────────────────

@dataclass
class RequestKey:
    client_key: Any
    scope: str
    decision_ref: str = ""
    used: bool = False


_request: contextvars.ContextVar[RequestKey | None] = contextvars.ContextVar(
    "durable_request_key", default=None)


@contextlib.contextmanager
def keyed(request: Any, *, scope: str | Callable[[], str], decision: Any = None):
    """While the bridge runs one request, tell the dispatcher the request's
    ``Idempotency-Key`` header (None when it sent none), whose it is (*scope*,
    called only here: the credential's kind and stable subject) and the gate
    decision's id. The first state-modifying dispatch in the request uses them.
    With no engine installed (mode off) this reads and calls nothing."""
    if _engine is None:
        yield
        return
    headers = getattr(request, "headers", None)
    client_key = headers.get("Idempotency-Key") if headers is not None else None
    decision_ref = decision.get("evaluation_id") if isinstance(decision, dict) else None
    try:
        who = str((scope() if callable(scope) else scope) or "")
    except Exception:  # noqa: BLE001 — no scope: the key cannot be honoured
        who, client_key = "", None
    token = _request.set(RequestKey(client_key, who, str(decision_ref) if decision_ref else ""))
    try:
        yield
    finally:
        _request.reset(token)


def caller_scope(server: Any, request: Any, caller_kind: str, identity: str) -> str:
    """Whose an Idempotency-Key is on the bridge: the credential's kind and its
    own subject — the SIWE address or ``apple:<sub>`` a session was issued to,
    which linking a wallet does not change — or, with no session, the identity
    the gate saw (the operator naming the user it acts for). In the platform's
    one spelling of a caller (``runtime/auth/identity.py``): a wallet address
    in any case is one caller, and anything else — ``apple:<sub>``, a label —
    is kept exactly as given, so two subjects that differ only in case are two
    callers with two scopes."""
    from runtime.auth.identity import canonical_identity

    subject = ""
    lookup = getattr(server, "_wallet_session_from_request", None)
    if callable(lookup):
        try:
            session = lookup(request)
        except Exception:  # noqa: BLE001
            session = None
        if isinstance(session, dict):
            subject = str(session.get("address") or "")
    return f"{caller_kind or 'unknown'}|{canonical_identity(str(subject or identity or ''))}"


# ── a run, while this process holds it ─────────────────────────────────────

@dataclass(eq=False)
class Run:
    run_id: str
    action: str
    service: str
    actor_hash: str
    params_digest: str
    started_at: float
    owned: bool
    key: str = ""
    decision_ref: str = ""
    #: This run's key was looked up and found unbound, so opening binds it.
    binds_key: bool = False
    #: When set, the dispatcher returns this instead of running anything.
    answer: str | None = None
    state: str = journal.START
    #: False once a write for this run failed (shadow): nothing more is written.
    written: bool = True
    answered: bool = False
    seq: int = 0
    #: Payloads the outbox delivers for this run (mode on): deep copies.
    deliveries: dict = field(default_factory=dict)
    #: The dispatcher's own deliveries of the same, used only when the outbox
    #: did not take them.
    legacy: dict = field(default_factory=dict)
    #: Shadow: the payloads the legacy path delivered, by kind (digested only).
    recorded: dict = field(default_factory=dict)

    def next_seq(self) -> int:
        self.seq += 1
        return self.seq


def envelope_error(category: str, error: str, **extra: Any) -> str:
    """A dispatcher failure envelope, in the dispatcher's own shape."""
    return json.dumps({"status": "error", _OUTCOME_FIELD: _FAILURE, "error_category": category,
                       "degraded": False, "error": error, **extra})


#: Ends kept for writing later, at most; past this the run is left to recovery.
MAX_PENDING_ENDS = 10_000


class NotRecorded(RuntimeError):
    """Mode on could not record a signing call before making it; it was not made."""


class DurableEngine:
    """One per gateway process, installed by the gateway at startup."""

    def __init__(self, db: Any, *, mode: str, canary: tuple[str, ...] = CANARY,
                 clock: Callable[[], float] = time.time, attestations: Any = None,
                 tick_s: float = outbox.TICK_S,
                 abandoned_after_s: float = journal.ABANDONED_AFTER_S) -> None:
        if mode not in ("shadow", "on"):
            raise ValueError(f"an engine runs in shadow or on, not {mode!r}")
        self._db = db
        self.mode = mode
        self.canary = tuple(canary)
        #: Why this engine could not be built, when it could not (``unbuilt``).
        self.fault = ""
        self._clock = clock
        self._abandoned_after_s = abandoned_after_s
        #: The batch processor whose submission path delivers attestations.
        self.attestations = attestations
        self.answers = keys.AnswerCache(clock=clock)
        self._open: set[str] = set()
        #: Ends this process knows and could not write yet (run_id -> the write):
        #: written again every tick, so recovery never closes a run whose end
        #: this process holds.
        self._pending: dict[str, tuple[Callable[[Tx], None], Callable[[], None] | None]] = {}
        self.recovered: dict[str, list[str]] = {"aborted": [], "failed": []}
        self.loop = outbox.OutboxLoop(
            db, deliver=(mode == "on"), maintain=self.maintain, clock=clock, tick_s=tick_s,
            abandoned_after_s=abandoned_after_s, write_wait=(mode == "on"))

    # ── authority ────────────────────────────────────────────────────────

    def owns(self, stage: str) -> bool:
        """Does mode on move the lifecycle of *stage* to the run? Never in shadow."""
        return self.mode == "on" and stage in self.canary

    def _write(self, work: Callable[[Tx], Any], *, owned: bool, what: str) -> tuple[bool, Any]:
        """One transaction. An owned write waits for the database like any other
        platform write; a shadow write never waits. A failure is logged and
        reported, never raised into the call site: the call site's own code
        decides what a failed write means."""
        try:
            return True, journal.transaction(self._db, work, wait=owned)
        except Exception as exc:  # noqa: BLE001 — a record never breaks the dispatch
            logger.warning("Durable %s: %s not written: %s", self.mode, what, exc)
            return False, None

    # ── the service dispatcher ───────────────────────────────────────────

    def begin(self, action: str, service: str, actor: str, params: Any) -> Run:
        try:
            return self._begin(action, service, actor, params)
        except Exception as exc:  # noqa: BLE001 — a record never breaks the dispatch
            logger.warning("Durable %s: run for %s not opened: %s", self.mode, action, exc)
            run = Run(run_id=journal.new_run_id(), action=action, service=service,
                      actor_hash="", params_digest="", started_at=self._clock(),
                      owned=self.owns(STATE_MODIFYING), state=UNRECORDED, written=False)
            if run.owned:
                run.answer = self._not_run(action)
            return run

    def _begin(self, action: str, service: str, actor: str, params: Any) -> Run:
        """Open a state-modifying dispatch's run, in memory: nothing is written
        until the call is about to begin (``open``) or will not begin (``abort``).
        A replayed Idempotency-Key in mode on comes back with ``answer`` set —
        the first answer, or why nothing is run — and the dispatcher returns it."""
        owned = self.owns(STATE_MODIFYING)
        run = Run(run_id=journal.new_run_id(), action=action, service=service,
                  actor_hash=journal.actor_hash(actor), params_digest=journal.digest(params),
                  started_at=self._clock(), owned=owned)
        request = _request.get()
        if request is None or request.used:
            return run
        request.used = True
        run.decision_ref = request.decision_ref
        if request.client_key is None:
            return run
        if not keys.valid_client_key(request.client_key):
            if owned:
                run.answer = envelope_error(
                    "validation", "Idempotency-Key must be 1 to 255 printable ASCII characters "
                    "with no leading or trailing space; this request was not run.")
            return run
        run.key = keys.scoped(BRIDGE_ACTION, request.scope, request.client_key)
        try:
            bound = keys.lookup(self._db, run.key)
        except Exception as exc:  # noqa: BLE001
            logger.warning("Durable %s: key lookup failed: %s", self.mode, exc)
            if owned:
                run.answer = self._not_run(action)
            return run
        if bound is None:
            run.binds_key = True
        elif owned:
            run.answer = self._replay(run, *bound)
        return run

    def _replay(self, run: Run, bound_run_id: str, response_digest: str) -> str:
        """What a request whose key is already bound is answered (mode on).

        The request is compared with the first one twice: with the run the key
        is bound to, as the table holds it, and — when this process still holds
        the first answer — with the request that answer was given to, as this
        process remembers it. A row altered to match a different request
        therefore still meets a conflict wherever the answer is held, and where
        it is not held the replay is told so: either way nothing runs, and no
        request is handed an answer that was given to another."""
        first = journal.get_run(self._db, bound_run_id)
        conflict = envelope_error(
            "idempotency_conflict", "This Idempotency-Key was used for a different request; "
            "this one was not run.")
        if first is None or (first["action"], first["params_digest"]) != (run.action,
                                                                          run.params_digest):
            return conflict
        if first["state"] in journal.OPEN:
            return envelope_error(
                "idempotency_in_progress", "The first request with this Idempotency-Key has not "
                "answered yet; this one was not run.", run_state=first["state"])
        held = self.answers.held(run.key)
        if held is not None:
            answer, request = held
            if request != _request_of(run):
                return conflict
            if response_digest and journal.text_digest(answer) == response_digest:
                return answer
        return envelope_error(
            "idempotency_answer_not_held", "The first request with this Idempotency-Key ended; "
            "its answer is no longer held, and this one was not run.", run_state=first["state"])

    def _not_run(self, action: str) -> str:
        return envelope_error(
            "service_unavailable", f"Action '{action}' was not run: the platform could not "
            "record it before running it. Nothing was executed; it is safe to try again.",
            degraded=True)

    def abort(self, run: Run, why: str) -> None:
        """The dispatch ends before its call: written as START and ABORT together."""
        if run.answer is not None or run.state != journal.START:
            return
        now = self._clock()

        def work(tx: Tx) -> None:
            journal.insert_run(tx, run_id=run.run_id, action=run.action, service=run.service,
                               actor_hash=run.actor_hash, params_digest=run.params_digest,
                               state=journal.ABORT, started_at=run.started_at,
                               decision_ref=run.decision_ref, terminal_at=now)
            journal.step(tx, run.run_id, run.next_seq(), journal.STEP_START, "opened",
                         at=run.started_at)
            journal.step(tx, run.run_id, run.next_seq(), journal.STEP_ABORT, why, at=now)
        run.state = journal.ABORT
        self._write(work, owned=run.owned, what=f"run for {run.action} ABORT")

    def open(self, run: Run) -> bool:
        """Write the run as RUNNING, with its key, immediately before its call.
        False when the dispatcher must not call: mode on could not record it, or
        (another process having bound the key in between) it is now a replay —
        ``run.answer`` says which."""
        if run.state != journal.START:
            return run.state == UNRECORDED and not run.owned
        now = self._clock()

        def work(tx: Tx) -> bool:
            if run.binds_key and not keys.bind(tx, key=run.key, run_id=run.run_id, now=now):
                if run.owned:
                    return False
                # Shadow: another process bound the key between the lookup and
                # now. The run is recorded with the key, as a replay's is.
                run.binds_key = False
            journal.insert_run(tx, run_id=run.run_id, action=run.action, service=run.service,
                               actor_hash=run.actor_hash, params_digest=run.params_digest,
                               state=journal.RUNNING, started_at=run.started_at, key=run.key,
                               decision_ref=run.decision_ref)
            journal.step(tx, run.run_id, 1, journal.STEP_START, "opened", at=run.started_at)
            journal.step(tx, run.run_id, 2, journal.STEP_CALL, "began", at=now)
            return True
        ok, opened = self._write(work, owned=run.owned, what=f"run for {run.action}")
        if ok and opened:
            run.seq, run.state = 2, journal.RUNNING
            self._open.add(run.run_id)
            return True
        run.state = UNRECORDED
        if not run.owned:
            run.written = False       # shadow: the call goes ahead, as with the mode off
            return True
        if ok:                        # the key was bound by another request first
            bound = keys.lookup(self._db, run.key)
            run.answer = self._replay(run, *bound) if bound else self._not_run(run.action)
        else:
            run.answer = self._not_run(run.action)
        return False

    async def call(self, run: Run, make_call: Callable[[], Awaitable[Any]]) -> Any:
        """Await the effect call. A raise is recorded (FAIL, step ``raise``) and
        re-raised; a cancellation leaves no answer (FAIL, ``unknown_effect``)."""
        try:
            result = await make_call()
        except Exception as exc:
            self._fail(run, journal.STEP_RAISE, "raised", "raised:" + type(exc).__name__)
            raise
        except BaseException:
            self._fail(run, journal.STEP_UNKNOWN, "cancelled", "call_interrupted")
            raise
        run.answered = True
        return result

    async def broken(self, run: Run, exc: BaseException, *, answer: str = "") -> None:
        """The dispatch raised: before the call (ABORT), in it (already FAIL),
        or after the call answered and before the run ended (FAIL). *answer* is
        the error the dispatcher answers with: for a keyed run that ended FAIL
        it is the first answer, and a replay gets it. What the outbox had been
        handed for the run is delivered the legacy way, as the dispatcher had
        already delivered it with the mode off."""
        if run.state == journal.START:
            self.abort(run, "raised_before_call")
            return
        if run.state == journal.RUNNING:
            self._fail(run, journal.STEP_RAISE,
                       "raised_after_answer" if run.answered else "raised",
                       "raised:" + type(exc).__name__)
        if answer:
            self.failed_with(run, answer)
        if run.legacy:
            await self.deliver_legacy(run)

    def interrupted(self, run: Run) -> None:
        """The dispatch was cut off (cancelled, interrupted) outside the call:
        before it (ABORT) or after it answered (FAIL, ``unknown_effect``: the
        answer was never given)."""
        if run.state == journal.START:
            self.abort(run, "interrupted_before_call")
        elif run.state == journal.RUNNING:
            self._fail(run, journal.STEP_UNKNOWN, "interrupted",
                       "interrupted_after_answer" if run.answered else "call_interrupted")

    def _fail(self, run: Run, name: str, state: str, detail: str) -> None:
        if run.state != journal.RUNNING:
            return
        now = self._clock()
        seq = run.next_seq()

        def work(tx: Tx) -> None:
            if not journal.move(tx, run.run_id, journal.RUNNING, journal.FAIL, at=now):
                raise _Closed(run.run_id)
            journal.step(tx, run.run_id, seq, name, state, at=now, detail=detail)
        run.state = journal.FAIL
        if run.written:
            self._end(run, work, what=f"run {run.run_id} FAIL")
        else:
            self._open.discard(run.run_id)

    def failed_with(self, run: Run, envelope: str) -> None:
        """A keyed run that ended FAIL answered *envelope*: that is its first
        answer, and a replay gets it (mode on)."""
        if not (run.binds_key and run.owned and run.written and run.state == journal.FAIL):
            return
        digest = journal.text_digest(envelope)

        def work(tx: Tx) -> None:
            keys.answered(tx, key=run.key, run_id=run.run_id, response_digest=digest)
        ok, _ = self._write(work, owned=True, what=f"answer for run {run.run_id}")
        if ok:
            self.answers.put(run.key, envelope, request=_request_of(run))

    def takes_delivery(self, run: Run | None) -> bool:
        """Does the outbox deliver this run's attestation and feed entry (mode
        on, the run written)? Otherwise the legacy path delivers them."""
        return run is not None and run.owned and run.written and run.state == journal.RUNNING

    def hold(self, run: Run, kind: str, build: Callable[[], Any],
             deliver: Callable[[Any], Awaitable[outbox.Delivery]], *,
             legacy: Callable[[], Any]) -> None:
        """Keep a deep copy of the payload *build* makes, for the outbox, and
        the closure that delivers it, and *legacy* — the dispatcher's own
        delivery — for when the outbox does not take it: the payload could not
        be built or copied (the legacy path then fails or succeeds exactly as it
        does with the mode off), or the end of the run could not be written."""
        run.legacy[kind] = legacy
        try:
            run.deliveries[kind] = (copy.deepcopy(build()), deliver)
        except Exception as exc:  # noqa: BLE001 — the legacy path delivers it, as with the mode off
            logger.warning("Durable on: run %s's %s is delivered the legacy way: %s",
                           run.run_id, kind, exc)

    def record(self, run: Run, kind: str, build: Callable[[], Any]) -> None:
        """Shadow: note the payload the legacy path is delivering, digested when
        the run ends. A payload that cannot be built is not recorded."""
        try:
            run.recorded[kind] = journal.digest(build())
        except Exception:  # noqa: BLE001 — a record never breaks the dispatch
            pass

    async def deliver_legacy(self, run: Run) -> None:
        """Deliver the legacy way — once — whatever ``hold`` took that the
        outbox did not."""
        legacies, run.legacy = dict(run.legacy), {}
        run.deliveries.clear()
        for kind in ("attest", "feed"):
            deliver = legacies.get(kind)
            if deliver is None:
                continue
            outcome = deliver()
            if asyncio.iscoroutine(outcome):
                await outcome

    async def deliver_attestation(self, record: dict) -> outbox.Delivery:
        """Deliver one attestation (``_attestation_of``'s record, its schema
        resolved by the attestation service the legacy path hands it to)
        through the batch processor's submission path — the call a flush makes
        for each attestation — and read the answer the way the batch processor
        does (``BatchProcessor._reconcile``): landed, or sent and not confirmed
        (never sent again), is delivered; refused by the sponsorship policy
        (nothing signed, not owed again) is given up; anything else the
        processor would re-queue is retried."""
        from runtime.protocols.outcome_truth import SUCCESS, report_of

        processor = self.attestations
        if processor is None:
            return outbox.Delivery(outbox.GIVEN_UP, "no_attestation_client")
        entry = {"id": journal.new_run_id(), "queued_at": self._clock(), **record}
        results = await processor._submit_batch([entry])
        result = results[0] if results else None
        if isinstance(result, dict) and report_of(result) is SUCCESS:
            return outbox.Delivery(outbox.DELIVERED, "landed")
        if isinstance(result, dict) and result.get("sponsorship_refused") is True:
            return outbox.Delivery(outbox.GIVEN_UP, "refused_by_policy")
        if (isinstance(result, dict) and result.get("broadcast") is True
                and result.get("settled") is not True):
            return outbox.Delivery(outbox.DELIVERED, "sent_unconfirmed")
        status = str(result.get("status") or "") if isinstance(result, dict) else ""
        return outbox.Delivery(outbox.RETRY, status if status in (
            "skipped", "failed", "unknown", "error", "pending") else "not_landed")

    def feed_deliverer(self, feed_engine: Any) -> Callable[[dict], Awaitable[outbox.Delivery]]:
        """Deliver one feed entry through *feed_engine*'s ``ingest``, the call
        the dispatcher's task made. Once: the feed engine answers a failure it
        swallowed with an event that has no summary, and cannot say whether the
        row was stored before it failed, so that answer is given up, not retried."""
        async def deliver(entry: dict) -> outbox.Delivery:
            event = await feed_engine.ingest(**entry)
            if getattr(event, "summary", None) == "":
                return outbox.Delivery(outbox.GIVEN_UP, "feed_reported_failure")
            return outbox.Delivery(outbox.DELIVERED, "ingested")
        return deliver

    def finish(self, run: Run, *, word: str, result: Any, envelope: str) -> bool:
        """End the run COMPLETE with the answer's word, and — in the same
        transaction — its outbox rows and its key's answer digest. True when the
        outbox now delivers what ``hold`` took (those kinds leave ``run.legacy``);
        otherwise whatever ``hold`` took is the caller's to deliver the legacy
        way (``end`` does), exactly once either way. An end that cannot be
        written is kept and written again by the loop, without the outbox rows
        (their deliveries went the legacy way)."""
        if run.state != journal.RUNNING:
            return False
        now = self._clock()
        run.state = journal.COMPLETE
        if not run.written:
            self._open.discard(run.run_id)
            return False
        try:
            seq = run.next_seq()
            result_digest = journal.digest(result)
            owned_rows = {kind: journal.digest(held) for kind, (held, _d) in run.deliveries.items()}
            answer_digest = journal.text_digest(envelope)
        except Exception as exc:  # noqa: BLE001 — a record never breaks the dispatch
            logger.warning("Durable %s: run %s's end not written: %s", self.mode, run.run_id, exc)
            self._open.discard(run.run_id)
            return False
        rows: dict[str, int] = {}

        def work(tx: Tx, *, with_rows: bool = True) -> None:
            if not journal.move(tx, run.run_id, journal.RUNNING, journal.COMPLETE, at=now):
                raise _Closed(run.run_id)
            journal.step(tx, run.run_id, seq, journal.STEP_RETURN, word, at=now,
                         detail="sha256:" + result_digest)
            if with_rows:
                for kind, digest in owned_rows.items():
                    rows[kind] = outbox.insert(tx, run_id=run.run_id, kind=kind,
                                               payload_digest=digest, now=now, deliver=True)
            for kind, digest in run.recorded.items():
                outbox.insert(tx, run_id=run.run_id, kind=kind, payload_digest=digest,
                              now=now, deliver=False)
            if run.binds_key:
                keys.answered(tx, key=run.key, run_id=run.run_id, response_digest=answer_digest)
        def remember() -> None:
            if run.binds_key and run.owned:
                self.answers.put(run.key, envelope, request=_request_of(run))
        if not self._end(run, work, what=f"run {run.run_id} COMPLETE",
                         later=lambda tx: work(tx, with_rows=False), then=remember):
            return False
        remember()
        for kind, (held, deliver) in run.deliveries.items():
            self.loop.hold(rows[kind], outbox.Held(
                run_id=run.run_id, kind=kind, payload_digest=owned_rows[kind],
                deliver=_bound(deliver, held)))
            run.legacy.pop(kind, None)
        if rows:
            self.loop.wake()
        return bool(rows)

    async def end(self, run: Run, *, word: str, result: Any, envelope: str) -> None:
        """``finish``, then the legacy delivery of whatever the outbox did not take."""
        self.finish(run, word=word, result=result, envelope=envelope)
        if run.legacy:
            await self.deliver_legacy(run)

    def _end(self, run: Run, work: Callable[[Tx], None], *, what: str,
             later: Callable[[Tx], None] | None = None,
             then: Callable[[], None] | None = None) -> bool:
        """Write a run's end. When it cannot be written now, the end is kept
        (*later*, or *work*) and written again every tick, and the run stays
        held, so recovery never closes a run whose end this process knows."""
        try:
            journal.transaction(self._db, work, wait=run.owned)
        except _Closed:
            logger.warning("Durable %s: %s found the run already closed", self.mode, what)
            self._open.discard(run.run_id)
            return False
        except Exception as exc:  # noqa: BLE001 — a record never breaks the dispatch
            logger.warning("Durable %s: %s not written yet: %s", self.mode, what, exc)
            if len(self._pending) < MAX_PENDING_ENDS:
                self._pending[run.run_id] = (later or work, then)
            else:
                self._open.discard(run.run_id)
            return False
        self._open.discard(run.run_id)
        return True

    def _write_pending(self) -> None:
        for run_id, (work, then) in list(self._pending.items()):
            try:
                journal.transaction(self._db, work, wait=(self.mode == "on"))
            except _Closed:
                then = None
            except Exception:  # noqa: BLE001 — the next tick tries again
                continue
            self._pending.pop(run_id, None)
            self._open.discard(run_id)
            if then is not None:
                then()

    # ── the twin tools ───────────────────────────────────────────────────

    async def run_tool(self, tool_name: str, arguments: Any, caller_identity: str,
                       make_call: Callable[[], Awaitable[Any]]) -> Any:
        """Journal a twin tool's platform-key signing call around *make_call*;
        any other call is made as it is. In mode on a signing call whose run
        cannot be written is not made (NotRecorded). The call's result and its
        exceptions reach the caller untouched."""
        from runtime.security.action_map import SIGNING_ACTIONS, TWIN_TOOLS, canonical_action

        if tool_name not in TWIN_TOOLS:
            return await make_call()
        args = arguments if isinstance(arguments, dict) else {}
        _label, signs = canonical_action(tool_name, args)
        if not signs:
            return await make_call()
        verb = str(args.get("action") or "").strip().lower()
        # The verb is the model's own string: written only when the tool declares it.
        action = f"{tool_name}.{verb if verb in SIGNING_ACTIONS[tool_name] else 'undeclared'}"
        try:
            run = Run(run_id=journal.new_run_id(), action=action, service=tool_name,
                      actor_hash=journal.actor_hash(str(caller_identity or "")),
                      params_digest=journal.digest(
                          {k: v for k, v in args.items()
                           if k not in ("caller_identity", "caller_source")}),
                      started_at=self._clock(), owned=self.owns(TWINS))
        except Exception as exc:  # noqa: BLE001 — a record never breaks the call
            logger.warning("Durable %s: run for %s not opened: %s", self.mode, action, exc)
            if self.owns(TWINS):
                raise NotRecorded("the platform could not record this signing call before "
                                  "making it, so it was not made; nothing was executed") from exc
            return await make_call()
        if not self.open(run):
            raise NotRecorded(
                "the platform could not record this signing call before making it, so it was "
                "not made; nothing was executed and it is safe to try again")
        try:
            result = await make_call()
        except asyncio.TimeoutError:
            self._fail(run, journal.STEP_UNKNOWN, "timed_out", "call_timed_out")
            raise
        except Exception as exc:
            self._fail(run, journal.STEP_RAISE, "raised", "raised:" + type(exc).__name__)
            raise
        except BaseException:
            self._fail(run, journal.STEP_UNKNOWN, "cancelled", "call_interrupted")
            raise
        run.answered = True
        try:
            from runtime.protocols.outcome_truth import report_of
            word = str(report_of(result))
        except Exception:  # noqa: BLE001 — classification never fails a call
            word = "unknown"
        self.finish(run, word=word, result=result, envelope="")
        return result

    # ── maintenance and the loop ─────────────────────────────────────────

    def maintain(self) -> dict[str, list[str]]:
        """Close what a process that is gone left open (journal.recover), and
        give back the key of a run that ended before its call. Runs every tick,
        in shadow and on; a tick with nothing to close takes no write lock.

        In mode on, also checkpoints the write-ahead log (``_checkpoint_wal``):
        the database checkpoints itself every 1,000 pages, and past that point
        the checkpoint's I/O lands inside whichever dispatch's COMMIT trips it —
        a stall in roughly one journaled dispatch in a hundred once the log
        fills, which sets the dispatch's p99. Done here, with the loop's other maintenance and between
        dispatches, the log stays short, so the database's own checkpoint fires
        less often: dispatch p99 drops while the worst case stays about 5 ms.
        Shadow checkpoints nothing: its only effects stay the rows it writes
        and the time they take."""
        if self.mode == "on":
            self._checkpoint_wal()
        if self._pending:
            self._write_pending()
        now = self._clock()
        try:
            found = journal.abandoned(self._db, now=now, held=frozenset(self._open),
                                      older_than_s=self._abandoned_after_s)
        except Exception:  # noqa: BLE001
            return {"aborted": [], "failed": []}
        if not found:
            return {"aborted": [], "failed": []}

        def work(tx: Tx) -> dict[str, list[str]]:
            closed = journal.recover(tx, found, now=now)
            for run_id, _state, key in found:
                if key and run_id in closed["aborted"]:
                    keys.release(tx, key=key, run_id=run_id)
            return closed
        ok, closed = self._write(work, owned=(self.mode == "on"), what="recovery")
        if not ok:
            return {"aborted": [], "failed": []}
        for k in ("aborted", "failed"):
            self.recovered[k].extend(closed[k])
        if closed["aborted"] or closed["failed"]:
            logger.warning("Durable: closed %d run(s) a stopped process left open: %d ABORT "
                           "(their call never began), %d FAIL with an unknown effect (none is "
                           "run again): %s", len(closed["aborted"]) + len(closed["failed"]),
                           len(closed["aborted"]), len(closed["failed"]),
                           ", ".join(closed["aborted"] + closed["failed"]))
        return closed

    def _checkpoint_wal(self) -> None:
        """Move committed frames from the write-ahead log into the database
        file. Called from ``maintain()`` in mode on only: shadow's ticks leave
        the log alone. PASSIVE waits for no lock: on a database another connection
        holds, it checkpoints what it can. What is durable does not change —
        a checkpoint moves committed frames, and recovery replays the log
        either way. A failure is logged, never raised: maintenance never
        breaks the loop."""
        try:
            self._db.execute_sync("PRAGMA wal_checkpoint(PASSIVE)")
        except Exception as exc:  # noqa: BLE001 — maintenance never breaks the loop
            logger.warning("Durable %s: WAL checkpoint not run: %s", self.mode, exc)

    def start(self) -> None:
        if not self.fault:
            self.loop.start()

    async def stop(self) -> None:
        """Stop the loop, then a last attempt to write what this process knows
        and has not written: run ends, and the answers of deliveries."""
        await self.loop.stop()
        self._write_pending()
        self.loop.settle_unsettled()

    def healthy(self) -> bool:
        """False for an engine that could not be built, and while the loop is
        not running or not making progress."""
        return not self.fault and self.loop.healthy()

    def health(self) -> dict:
        """For the operator's log (never a response body)."""
        try:
            rows = outbox.counts(self._db)
        except Exception:  # noqa: BLE001
            rows = {}
        return {"mode": self.mode, "canary": list(self.canary), "fault": self.fault,
                "loop_alive": self.loop.alive,
                "last_tick_at": self.loop.last_tick_at, "open_runs": len(self._open),
                "ends_not_written": len(self._pending),
                "held_payloads": self.loop.held_count(), "outbox": rows}

    @classmethod
    def unbuilt(cls, *, mode: str, canary: tuple[str, ...], fault: str,
                clock: Callable[[], float] = time.time) -> "DurableEngine":
        """The engine installed when the one the config asks for could not be
        built: the same engine over a database that refuses every statement.
        Every path it takes is one the engine already takes when a run cannot
        be written — an action it owns is not run and answers
        ``service_unavailable`` ("was not run"), a twin signing call it owns is
        not made, an action it does not own runs as with the mode off — and
        its loop never starts, so ``healthy`` is False."""
        engine = cls(_Unwritable(fault), mode=mode, canary=canary, clock=clock)
        engine.fault = fault or "not built"
        return engine


def _request_of(run: Run) -> str:
    """The request a first answer was given to, as this process remembers it:
    a digest of the action and the parameters' digest, never the parameters."""
    return journal.text_digest(f"{run.action}\x00{run.params_digest}")


def _bound(fn: Callable[[Any], Awaitable[Any]], arg: Any) -> Callable[[], Awaitable[Any]]:
    """Each attempt is handed its own deep copy of the held payload: nothing
    one attempt (or the client it calls) does to what it was handed reaches the
    next attempt, and the held payload stays the one whose digest was written."""
    async def call() -> Any:
        return await fn(copy.deepcopy(arg))
    return call


class _Closed(RuntimeError):
    """A run's end found the run no longer RUNNING (another process closed it)."""


class _Unwritable:
    """A database that refuses every statement: what an engine that could not
    be built runs over."""

    def __init__(self, fault: str) -> None:
        self._fault = fault

    def _refuse(self, *_args: Any, **_kwargs: Any) -> Any:
        raise RuntimeError(f"durable execution could not be built: {self._fault}")

    execute_sync = fetchall_sync = _refuse


class NotBuilt(RuntimeError):
    """The engine the config asks for cannot run over this database."""


def build_engine(config: Any, db: Any, *, clock: Callable[[], float] = time.time
                 ) -> DurableEngine | None:
    """The engine this config asks for, or None for mode off. In mode on,
    attestations are delivered through a batch processor of the engine's own
    (the submission path a flush uses).

    An engine is built only over the four tables in the shape this build writes
    (``table_problems``). In mode on, an engine that cannot be built — for that
    or any other reason — is replaced by ``DurableEngine.unbuilt``, which
    refuses what it would have owned and is never healthy: a configured on is
    never silently off. In shadow the fault is raised, and the caller serves as
    with the mode off: recording is all shadow does."""
    mode = durable_mode(config)
    if mode == "off":
        return None
    canary = durable_canary(config)
    try:
        problems = table_problems(db)
        if problems:
            raise NotBuilt(
                "the durable tables in this database are not the ones this build writes ("
                + "; ".join(problems) + "); a database an earlier, unreleased build of durable "
                "execution created holds them in another shape and is not healed: discard it")
        attestations = None
        if mode == "on":
            from runtime.blockchain.services.attestation.batch_processor import BatchProcessor
            attestations = BatchProcessor(_with_sections(config, "blockchain"))
        return DurableEngine(db, mode=mode, canary=canary, clock=clock,
                             attestations=attestations,
                             abandoned_after_s=abandoned_window(config))
    except Exception as exc:
        if mode != "on":
            raise
        logger.error("Durable execution (mode on) could not be built: %s. The actions it would "
                     "own are refused until it is, and /ready answers 503.", exc, exc_info=True)
        return DurableEngine.unbuilt(mode=mode, canary=canary,
                                     fault=f"{type(exc).__name__}: {exc}", clock=clock)


def _with_sections(config: Any, *names: str) -> dict:
    """*config* as a dict whose named sections are dicts: a section the config
    leaves empty (``blockchain:`` with no value) is read as no settings, the
    way an absent one is, rather than failing the reader."""
    out = dict(config) if isinstance(config, dict) else {}
    for name in names:
        if not isinstance(out.get(name), dict):
            out[name] = {}
    return out


#: The columns this build writes, table by table, in order (database migration 11).
TABLE_COLUMNS: dict[str, tuple[str, ...]] = {
    "workflow_runs": ("run_id", "key", "action", "service", "actor_hash", "params_digest",
                      "state", "decision_ref", "started_at", "terminal_at"),
    "workflow_steps": ("run_id", "seq", "name", "state", "detail", "at"),
    "outbox": ("id", "run_id", "kind", "payload_digest", "attempts", "next_at", "done_at"),
    "idempotency_keys": ("key", "run_id", "response_digest", "created_at"),
}


def table_problems(db: Any) -> list[str]:
    """Each durable table in *db* whose columns are not the ones this build
    writes, in order: an earlier, unreleased build of this work created the
    tables in other shapes, and ``CREATE TABLE IF NOT EXISTS`` leaves a table
    it finds as it is. Empty when all four are as written. Read-only."""
    problems: list[str] = []
    for table, columns in TABLE_COLUMNS.items():
        found = tuple(r[0] for r in db.fetchall_sync(
            "SELECT name FROM pragma_table_info(?) ORDER BY cid", (table,)))
        if found != columns:
            problems.append(f"{table} has ({', '.join(found) or 'no table'})")
    return problems


def abandoned_window(config: Any) -> float:
    """How long an open run another process holds may stay open before recovery
    closes it: the longest the gateway lets a request run (its
    ``gateway.request_timeout_seconds``, 120 s by default), doubled, plus a
    minute — never under ``journal.ABANDONED_AFTER_S``. With the request timeout
    turned off (0) no request is bounded, and the window is an hour."""
    gateway = config.get("gateway") if isinstance(config, dict) else None
    raw = gateway.get("request_timeout_seconds", 120) if isinstance(gateway, dict) else 120
    try:
        timeout = float(raw)
    except (TypeError, ValueError):
        timeout = 120.0
    if timeout <= 0:
        return 3600.0
    return max(journal.ABANDONED_AFTER_S, 2 * timeout + 60.0)
