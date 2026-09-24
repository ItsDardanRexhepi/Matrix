"""The wiring: the mode, the canary, and the engine the call sites consult.

``engines.durable.mode`` (``MATRIX_DURABLE_MODE`` wins, read once at startup):

* ``off`` — the default. No engine is installed; every call site's first check
  finds none and runs exactly the code it ran before this package existed. The
  ``Idempotency-Key`` header is not read. The four tables exist, empty, because
  the database creates them whatever the mode.
* ``shadow`` — the engine journals and records, and owns nothing: every run is
  written to the journal, every attestation and feed entry the legacy path
  delivers is written to the outbox as ``recorded`` bookkeeping, and every key
  the bridge sees is recorded with the answer it got. A request's answer is the
  answer it gets with the mode off. A row that cannot be written at once is
  dropped, never waited for.
* ``on`` — the engine owns the LIFECYCLE of the actions in its canary, and
  nothing else: a run's row is written before its effect call begins, and an
  action whose row cannot be written is not run; the outbox loop delivers the
  attestation and the feed entry; a replayed ``Idempotency-Key`` gets the first
  answer and runs nothing.

``engines.durable.canary`` says which actions ``on`` covers. ``twins`` (the
default) is the twin tools' platform-key signing calls
(``runtime/security/action_map.py`` ``SIGNING_ACTIONS``); ``state_modifying`` is
those and every state-modifying action name the service dispatcher serves.
Actions outside the canary are journaled as in shadow.

WHAT THE ENGINE NEVER DOES, IN ANY MODE. It never decides whether an action is
allowed — the gate has already decided before any of this runs, and a replay is
gated again like any request. It never decides what an action's outcome was: a
run's state says whether its call began and whether it answered, and the words
on its steps are the ones the layer that made the call already computed. It
never runs an action a second time: a run whose call never answered stays
RUNNING for a person to look at, and a key already bound answers from its
record. The only refusal it adds is to not start an effect it could not record.
"""

from __future__ import annotations

import asyncio
import contextlib
import contextvars
import json
import logging
import os
import sqlite3
import time
from dataclasses import dataclass
from typing import Any, Awaitable, Callable

from runtime.durable import journal, keys, outbox

logger = logging.getLogger(__name__)

MODES: tuple[str, ...] = ("off", "shadow", "on")
TWINS = "twins"
STATE_MODIFYING = "state_modifying"
CANARIES: tuple[str, ...] = (TWINS, STATE_MODIFYING)

#: The surface the bridge's keys are scoped to.
BRIDGE_ACTION_SURFACE = "bridge.action"


def _engines_section(config: Any) -> dict:
    engines = config.get("engines") if isinstance(config, dict) else None
    durable = engines.get("durable") if isinstance(engines, dict) else None
    return durable if isinstance(durable, dict) else {}


def durable_mode(config: Any) -> str:
    """``MATRIX_DURABLE_MODE``, then ``engines.durable.mode``, then "off". A
    value that is not one of MODES is logged and read as "off": an unrecognised
    switch never moves lifecycle authority."""
    raw = os.environ.get("MATRIX_DURABLE_MODE") or _engines_section(config).get("mode") or "off"
    mode = str(raw).strip().lower()
    if mode not in MODES:
        logger.warning("Unknown engines.durable.mode %r; durable execution stays off.", raw)
        return "off"
    return mode


def durable_canary(config: Any) -> str:
    """``engines.durable.canary``: "twins" (the default) or "state_modifying". A
    value that is not one of CANARIES is logged and read as "twins", the
    narrower one."""
    raw = _engines_section(config).get("canary") or TWINS
    canary = str(raw).strip().lower()
    if canary not in CANARIES:
        logger.warning("Unknown engines.durable.canary %r; the canary stays %r.", raw, TWINS)
        return TWINS
    return canary


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


@dataclass(frozen=True)
class Binding:
    """What the bridge knows about a request before the dispatcher runs it: the
    scoped key, the run the key's claim started (None when it started none),
    and the gate decision's id."""
    key: str
    run_id: str | None
    action: str
    decision_ref: str = ""


_binding: contextvars.ContextVar[Binding | None] = contextvars.ContextVar(
    "durable_binding", default=None)


@dataclass
class Run:
    run_id: str
    owned: bool
    refused: bool = False


@dataclass(frozen=True)
class BridgeClaim:
    """What a request's Idempotency-Key is bound to.

    ``outcome`` is "none" (no key), "invalid", "unrecorded" (the claim could not
    be written), or one of keys.MISS / HIT / CONFLICT / IN_FLIGHT / EXPIRED.
    ``honoured`` is True when the bridge must answer from this claim instead of
    running the request: mode on, the canary covering state-modifying names,
    and an outcome other than a fresh bind."""
    outcome: str
    honoured: bool = False
    key: str = ""
    run_id: str | None = None
    run_state: str | None = None
    status: int | None = None
    response: str | None = None
    action: str = ""
    decision_ref: str = ""


def _tx_of(result: Any) -> str:
    if isinstance(result, dict):
        tx = result.get("tx_hash") or result.get("transaction_hash")
        return str(tx) if tx else ""
    return ""


class DurableEngine:
    """One per gateway process, installed by the gateway at startup."""

    def __init__(
        self,
        db: Any,
        *,
        mode: str,
        canary: str = TWINS,
        clock: Callable[[], float] = time.time,
        deliverers: dict[str, outbox.Deliverer] | None = None,
        tick_s: float = outbox.TICK_S,
    ) -> None:
        if mode not in ("shadow", "on"):
            raise ValueError(f"an engine runs in shadow or on, not {mode!r}")
        if canary not in CANARIES:
            raise ValueError(f"unknown canary {canary!r}")
        self._db = db
        self.mode = mode
        self.canary = canary
        self._clock = clock
        self.loop = outbox.OutboxLoop(
            db, deliver=(mode == "on"), deliverers=deliverers, maintain=self.maintain,
            clock=clock, tick_s=tick_s, write_wait=(mode == "on"))

    # ── authority ────────────────────────────────────────────────────────

    def owns(self, domain: str) -> bool:
        """Does mode on move the lifecycle of *domain* ("twins" or
        "state_modifying") to this engine? Never in shadow."""
        if self.mode != "on":
            return False
        if domain == TWINS:
            return True
        return domain == STATE_MODIFYING and self.canary == STATE_MODIFYING

    # ── writes ───────────────────────────────────────────────────────────

    def _write(self, work: Callable[[sqlite3.Connection], Any], *, owned: bool,
               what: str) -> tuple[bool, Any]:
        """One transaction. An owned write waits for the database like any other
        platform write; a shadow write never waits. A failure — the database,
        or anything else that goes wrong building the rows — is logged and
        reported, never raised into the call site: the call site's own code
        path decides what a failed write means (not run, or delivered the
        legacy way), never an exception from here."""
        try:
            return True, self._db.transaction_sync(work, wait=owned)
        except (sqlite3.Error, RuntimeError) as exc:
            logger.warning("Durable %s: %s not written: %s", self.mode, what, exc)
            return False, None
        except Exception:
            logger.exception("Durable %s: %s not written", self.mode, what)
            return False, None

    # ── the service dispatcher ───────────────────────────────────────────

    def begin_dispatch(self, action: str, service: str, actor: str, params: Any) -> Run | None:
        """Record a state-modifying dispatch as RUNNING before its service is
        called. None: nothing journaled, run as before (shadow, a write that
        failed). ``refused``: mode on could not record it, so it must not run."""
        owned = self.owns(STATE_MODIFYING)
        binding = _binding.get()
        if binding is not None and binding.action != action:
            binding = None
        now = self._clock()

        if binding is not None and binding.run_id:
            run_id = binding.run_id

            def begin_bound(conn):
                if not journal.transition(conn, run_id, journal.START, journal.RUNNING, at=now):
                    return False
                conn.execute("UPDATE workflow_runs SET service = ?, params_digest = ? "
                             "WHERE run_id = ?", (service, journal.digest(params), run_id))
                journal.append_step(conn, run_id, journal.STEP_CALL, "attempting", at=now)
                return True
            ok, moved = self._write(begin_bound, owned=owned, what=f"run {run_id} RUNNING")
            if ok and moved:
                return Run(run_id, owned)
            return Run(run_id, owned, refused=True) if owned else None

        run_id = journal.new_run_id()

        def begin(conn):
            journal.insert_run(
                conn, run_id=run_id, key=binding.key if binding else "", action=action,
                service=service, actor_hash=journal.actor_hash(actor),
                params_digest=journal.digest(params),
                state=journal.RUNNING, started_at=now,
                decision_ref=binding.decision_ref if binding else "")
            journal.append_step(conn, run_id, journal.STEP_START, "recorded", at=now)
            journal.append_step(conn, run_id, journal.STEP_CALL, "attempting", at=now)
        ok, _ = self._write(begin, owned=owned, what=f"run for {action}")
        if ok:
            return Run(run_id, owned)
        return Run(run_id, owned, refused=True) if owned else None

    async def call(self, run: Run, make_call: Callable[[], Awaitable[Any]]) -> Any:
        """Await the effect call, recording a raise (FAIL) or a call that never
        answered (it stays RUNNING, marked unknown). The call's result and its
        exceptions reach the caller untouched."""
        try:
            return await make_call()
        except asyncio.CancelledError:
            self._no_answer(run, "cancelled")
            raise
        except Exception as exc:
            self._raised(run, exc)
            raise
        except BaseException:
            self._no_answer(run, "interrupted")
            raise

    def finish_dispatch(self, run: Run, *, answer: str, refused: bool, result: Any,
                        attestation: Callable[[], dict] | None,
                        feed: Callable[[], dict] | None) -> bool:
        """Record the answer and the run's terminal state, and — in the same
        transaction — the attestation and feed entry the dispatcher would
        deliver, built by the dispatcher's own builders (*attestation*, *feed*;
        None for none). True only when this engine now owns their delivery
        (mode on, written): the dispatcher then does not deliver them itself.
        False in shadow, and when mode on could not write them — the database,
        or a builder that raised — so the legacy path delivers them exactly
        once either way, exactly as it does with the mode off."""
        now = self._clock()

        def finish(conn):
            journal.append_step(conn, run.run_id, journal.STEP_RETURN, answer, at=now,
                                payload_digest=journal.digest(result), tx_hash=_tx_of(result))
            to = journal.FAIL if refused else journal.COMPLETE
            if not journal.transition(conn, run.run_id, journal.RUNNING, to, at=now):
                raise sqlite3.IntegrityError(f"run {run.run_id} was not RUNNING")
            if attestation is not None:
                outbox.enqueue(conn, run_id=run.run_id, kind="attest", payload=attestation(),
                               deliver=run.owned, now=now)
            if feed is not None:
                outbox.enqueue(conn, run_id=run.run_id, kind="feed", payload=feed(),
                               deliver=run.owned, now=now)
        ok, _ = self._write(finish, owned=run.owned, what=f"run {run.run_id} terminal")
        if not ok:
            if run.owned:
                logger.warning("Durable on: run %s's delivery stays with the legacy path", run.run_id)
            return False
        if run.owned and (attestation is not None or feed is not None):
            self.loop.wake()
        return run.owned

    def _raised(self, run: Run, exc: BaseException) -> None:
        now = self._clock()

        def raised(conn):
            journal.append_step(conn, run.run_id, journal.STEP_RAISE, "raised", at=now,
                                payload_digest=journal.digest(type(exc).__name__))
            journal.transition(conn, run.run_id, journal.RUNNING, journal.FAIL, at=now)
        self._write(raised, owned=run.owned, what=f"run {run.run_id} FAIL")

    def _no_answer(self, run: Run, why: str) -> None:
        now = self._clock()

        def unknown(conn):
            journal.append_step(conn, run.run_id, journal.STEP_UNKNOWN, why, at=now)
        self._write(unknown, owned=run.owned, what=f"run {run.run_id} unknown effect")

    # ── the twin tools ───────────────────────────────────────────────────

    def begin_tool(self, tool_name: str, arguments: Any, caller_identity: str) -> Run | None:
        """Record a twin tool's platform-key signing call as RUNNING before the
        tool runs. None for anything else (a read, another tool)."""
        from runtime.security.action_map import TWIN_TOOLS, canonical_action

        if tool_name not in TWIN_TOOLS:
            return None
        _label, signs = canonical_action(tool_name, arguments)
        if not signs:
            return None
        args = arguments if isinstance(arguments, dict) else {}
        verb = str(args.get("action") or "").strip().lower()
        owned = self.owns(TWINS)
        run_id = journal.new_run_id()
        now = self._clock()

        def begin(conn):
            journal.insert_run(
                conn, run_id=run_id, action=f"{tool_name}.{verb}", service=tool_name,
                actor_hash=journal.actor_hash(caller_identity),
                params_digest=journal.digest(args), state=journal.RUNNING, started_at=now)
            journal.append_step(conn, run_id, journal.STEP_START, "recorded", at=now)
            journal.append_step(conn, run_id, journal.STEP_CALL, "attempting", at=now)
        ok, _ = self._write(begin, owned=owned, what=f"run for {tool_name}.{verb}")
        if ok:
            return Run(run_id, owned)
        return Run(run_id, owned, refused=True) if owned else None

    async def call_tool(self, run: Run, make_call: Callable[[], Awaitable[Any]]) -> Any:
        """Await the tool; record its answer as the tool dispatcher reads it
        (``report_of``: success / failure / unknown), a raise (FAIL), or a
        timeout or cancellation (no answer: the run stays RUNNING)."""
        from runtime.protocols.outcome_truth import FAILURE, report_of

        try:
            result = await make_call()
        except (asyncio.TimeoutError, asyncio.CancelledError) as exc:
            self._no_answer(run, "timed_out" if isinstance(exc, asyncio.TimeoutError)
                            else "cancelled")
            raise
        except Exception as exc:
            self._raised(run, exc)
            raise
        except BaseException:
            self._no_answer(run, "interrupted")
            raise
        try:
            word = report_of(result)
        except Exception:
            word = "unknown"
        now = self._clock()

        def finish(conn):
            journal.append_step(conn, run.run_id, journal.STEP_RETURN, str(word), at=now,
                                payload_digest=journal.digest(result), tx_hash=_tx_of(result))
            journal.transition(conn, run.run_id, journal.RUNNING,
                               journal.FAIL if word == FAILURE else journal.COMPLETE, at=now)
        self._write(finish, owned=run.owned, what=f"run {run.run_id} terminal")
        return result

    # ── the bridge's Idempotency-Key ─────────────────────────────────────

    def bridge_claim(self, *, client_key: Any, action: str, params: Any, service: str,
                     actor: str, actor_scope: str, decision_ref: str = "") -> BridgeClaim:
        """Claim *client_key* for this request, or say what it is bound to."""
        owned = self.owns(STATE_MODIFYING)
        if client_key is None:
            return BridgeClaim("none", action=action, decision_ref=decision_ref)
        if not keys.valid_client_key(client_key):
            return BridgeClaim("invalid", honoured=owned, action=action, decision_ref=decision_ref)
        key = keys.scoped_key(BRIDGE_ACTION_SURFACE, actor_scope, client_key)
        run_id = journal.new_run_id()
        now = self._clock()

        def claim(conn):
            request = keys.request_digest({"action": action, "params": params})
            bound = keys.claim(conn, key=key, request_digest=request, run_id=run_id, now=now)
            if bound.outcome == keys.MISS:
                journal.insert_run(
                    conn, run_id=run_id, key=key, action=action, service=service,
                    actor_hash=journal.actor_hash(actor), params_digest=journal.digest(params),
                    state=journal.START, started_at=now, decision_ref=decision_ref)
                journal.append_step(conn, run_id, journal.STEP_START, "recorded", at=now)
                return bound, journal.START
            run = journal.get_run(conn, bound.run_id)
            return bound, (run["state"] if run else None)
        ok, res = self._write(claim, owned=owned, what="idempotency key")
        if not ok:
            return BridgeClaim("unrecorded", honoured=owned, key=key, action=action,
                               decision_ref=decision_ref)
        bound, state = res
        return BridgeClaim(
            bound.outcome, honoured=owned and bound.outcome != keys.MISS, key=key,
            run_id=bound.run_id, run_state=state, status=bound.status,
            response=bound.response, action=action, decision_ref=decision_ref)

    @contextlib.contextmanager
    def bound(self, claim: BridgeClaim):
        """While the bridge runs a request, tell the dispatcher which run and
        key it belongs to."""
        if claim.outcome in ("none", "invalid") or not claim.key:
            yield
            return
        token = _binding.set(Binding(
            key=claim.key, run_id=claim.run_id if claim.outcome == keys.MISS else None,
            action=claim.action, decision_ref=claim.decision_ref))
        try:
            yield
        finally:
            _binding.reset(token)

    def bridge_finish(self, claim: BridgeClaim, *, status: int, body: bytes | str | None) -> None:
        """After the request answered: a run that never began its effect call
        ends ABORT and gives its key back; any other run's key keeps the answer
        (secret-named fields withheld) for 24 hours."""
        if claim.outcome != keys.MISS or not claim.run_id:
            return
        owned = self.owns(STATE_MODIFYING)
        run_id, key = claim.run_id, claim.key
        now = self._clock()

        def answer_text() -> str:
            text = (body.decode("utf-8", "replace") if isinstance(body, (bytes, bytearray))
                    else (body or ""))
            try:
                parsed = json.loads(text)
            except (ValueError, TypeError):
                return text
            cleaned = keys.withhold_secrets(parsed)
            return text if cleaned is parsed else json.dumps(cleaned)

        def finish(conn):
            run = journal.get_run(conn, run_id)
            if run is None:
                return None
            if run["state"] == journal.START:
                journal.transition(conn, run_id, journal.START, journal.ABORT, at=now)
                journal.append_step(conn, run_id, journal.STEP_ABORT, "not_attempted", at=now)
                keys.release(conn, key=key, run_id=run_id)
                return "released"
            keys.record_response(conn, key=key, run_id=run_id, status=status, body=answer_text())
            return "recorded"
        self._write(finish, owned=owned, what=f"answer for run {run_id}")

    # ── maintenance and the loop ─────────────────────────────────────────

    def maintain(self) -> dict | None:
        """Close what a dead process left behind and drop answers past their
        24 hours. Runs on every loop tick, in shadow and on."""
        now = self._clock()
        if not self._maintenance_due(now):
            return {"runs": {"aborted": [], "unknown": []},
                    "outbox": {"held": [], "requeued": []}, "answers_dropped": 0}

        def work(conn):
            runs = journal.recover_runs(conn, now=now)
            for run_id in runs["aborted"]:
                keys.release_for_run(conn, run_id)
            rows = outbox.recover_attempts(conn, now=now)
            dropped = keys.drop_expired_answers(conn, now=now)
            return {"runs": runs, "outbox": rows, "answers_dropped": dropped}
        ok, res = self._write(work, owned=(self.mode == "on"), what="maintenance")
        if not ok:
            return None
        if res["runs"]["aborted"] or res["runs"]["unknown"]:
            logger.warning("Durable: %d abandoned run(s) ended ABORT before their call began; "
                           "%d run(s) whose call never answered stay RUNNING, not run again: %s",
                           len(res["runs"]["aborted"]), len(res["runs"]["unknown"]),
                           ", ".join(res["runs"]["unknown"]) or "-")
        if res["outbox"]["held"]:
            logger.error("Durable: %d attestation(s) interrupted mid-delivery are HELD, not sent "
                         "again: outbox rows %s", len(res["outbox"]["held"]),
                         ", ".join(str(i) for i in res["outbox"]["held"]))
        return res

    def _maintenance_due(self, now: float) -> bool:
        """Read-only: is there anything for maintain() to write? A tick with
        nothing to do takes no write lock."""
        cutoff = now - journal.ABANDONED_AFTER_S
        probes = (
            ("SELECT 1 FROM workflow_runs WHERE state IN ('START', 'RUNNING') "
             "AND state = ? AND started_at < ? LIMIT 1", (journal.START, cutoff)),
            ("SELECT 1 FROM workflow_runs r WHERE r.state IN ('START', 'RUNNING') "
             "AND r.state = ? AND r.started_at < ? "
             "AND NOT EXISTS (SELECT 1 FROM workflow_steps s WHERE s.run_id = r.run_id "
             "AND s.kind = ?) LIMIT 1", (journal.RUNNING, cutoff, journal.STEP_UNKNOWN)),
            ("SELECT 1 FROM outbox WHERE state IN ('pending', 'attempting') "
             "AND state = ? AND next_at < ? LIMIT 1", (outbox.ATTEMPTING, now)),
            ("SELECT 1 FROM idempotency_keys WHERE response IS NOT NULL AND expires_at < ? "
             "LIMIT 1", (now,)),
        )
        try:
            return any(self._db.fetchall_sync(sql, args) for sql, args in probes)
        except (sqlite3.Error, RuntimeError):
            return False

    def start(self) -> None:
        self.loop.start()

    async def stop(self) -> None:
        await self.loop.stop()

    def health(self) -> dict:
        """For /ready and the operator's log: whether the loop runs, and the
        outbox by state."""
        try:
            by_state = outbox.counts(self._db)
        except (sqlite3.Error, RuntimeError):
            by_state = {}
        return {"mode": self.mode, "canary": self.canary, "loop_alive": self.loop.alive,
                "outbox": by_state}


def build_engine(config: Any, db: Any, *, feed_engine: Any = None,
                 clock: Callable[[], float] = time.time) -> DurableEngine | None:
    """The engine this config asks for, or None for mode off. Its deliverers are
    the batch processor's submission path (attestations) and the social feed
    engine (feed entries), when there is one."""
    mode = durable_mode(config)
    if mode == "off":
        return None
    from runtime.blockchain.services.attestation.batch_processor import BatchProcessor

    deliverers: dict[str, outbox.Deliverer] = {
        "attest": outbox.attestation_deliverer(BatchProcessor(config if isinstance(config, dict) else {})),
    }
    if feed_engine is not None:
        deliverers["feed"] = outbox.feed_deliverer(feed_engine, db)
    return DurableEngine(db, mode=mode, canary=durable_canary(config), clock=clock,
                         deliverers=deliverers)
