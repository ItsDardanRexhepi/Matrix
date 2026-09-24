"""The run journal: ``workflow_runs`` and ``workflow_steps`` (database migration 10).

A run is one state-modifying action the durable engine journals. Its ``state``
is the LIFECYCLE, and only that:

    START ──► RUNNING ──► COMPLETE | FAIL
      │
      └────► ABORT

* ``START`` — the run is recorded and its effect call had not begun when it was.
  Whether it can have begun since depends on who recorded it, which its
  ``start`` step says: ``recorded`` — an engine that owns the run, which never
  lets the call begin before the run is RUNNING — or ``observed`` — an engine
  that does not (shadow; mode on outside its canary), where the call goes ahead
  even when the RUNNING mark cannot be written.
* ``RUNNING`` — the effect call began. From here on the action may have acted,
  whatever happens to this process.
* ``COMPLETE`` — the call returned an answer the layer that made it did not
  read as a refusal. It is not "the action succeeded": which answer it was is on
  the ``return`` step (``settled``, ``broadcast`` …), and whether the world
  agrees is the evidence engine's question, never this one's.
* ``FAIL`` — the call returned a refusal, or raised.
* ``ABORT`` — the run ended before the effect call began.

A run with no recorded answer — the process died, the call timed out or was
cancelled, or an engine that does not own the run could not write the answer —
stays ``RUNNING``, with an ``unknown_effect`` step saying so, because nobody
knows from the journal whether it acted. So does an ``observed`` run found in
START long after its request: it stays START with an ``unknown_effect`` step,
because its call may have begun unmarked. Nothing in this package ever moves
such a run anywhere, and nothing ever runs it again.

Every write here takes a connection that is already inside a transaction, so a
caller composes a transition with its steps, its outbox rows and its
idempotency key in ONE transaction. Every transition is a compare-and-set on
the state it expects (``UPDATE … WHERE run_id = ? AND state = ?``, rowcount 1),
so a transition that lost a race changes nothing and says so.
"""

from __future__ import annotations

import hashlib
import json
import sqlite3
import uuid
from typing import Any

START = "START"
RUNNING = "RUNNING"
COMPLETE = "COMPLETE"
ABORT = "ABORT"
FAIL = "FAIL"

STATES: tuple[str, ...] = (START, RUNNING, COMPLETE, ABORT, FAIL)
TERMINAL: frozenset[str] = frozenset({COMPLETE, ABORT, FAIL})

#: The only transitions a run may make. Anything else is a programming error.
TRANSITIONS: frozenset[tuple[str, str]] = frozenset({
    (START, RUNNING), (START, ABORT), (RUNNING, COMPLETE), (RUNNING, FAIL),
})

# Step kinds, in the order a run appends them.
STEP_START = "start"            # the run was recorded; state = START_OWNED | START_OBSERVED
STEP_CALL = "call"              # the effect call began; state = CALL_MARKED | CALL_LATE
STEP_RETURN = "return"          # the call returned; state = the caller's word for the answer
STEP_RAISE = "raise"            # the call raised; state = "raised"
STEP_ABORT = "abort"            # the run ended before the call; state = why
STEP_UNKNOWN = "unknown_effect"  # the journal holds no answer for the call; state = why

#: The ``start`` step's word: who owned the run's lifecycle when it was recorded.
#: Only an owned run's START proves its call never began, so only an owned run
#: found abandoned in START is closed ABORT and gives its key back.
START_OWNED = "recorded"
START_OBSERVED = "observed"
#: The ``call`` step's word. ``attempting`` is written before the call begins.
#: ``began_before_recorded`` is written after it: an engine that does not own
#: the run could not write the mark at once, the call went ahead as it does
#: with the mode off, and the mark was written with what the call answered.
CALL_MARKED = "attempting"
CALL_LATE = "began_before_recorded"
#: The ``unknown_effect`` step's words. ``no_answer_recorded``: the call began
#: and the journal holds no answer (the call timed out or was cancelled uses
#: its own word). ``not_known_if_called``: an observed run left in START whose
#: call may have begun without its mark.
NO_ANSWER_RECORDED = "no_answer_recorded"
NOT_KNOWN_IF_CALLED = "not_known_if_called"

#: A run in START for this long is abandoned: every entry point moves its run to
#: RUNNING (or ABORT) within the request that created it, and the gateway's own
#: request budget is 120 seconds. A START row older than this belongs to a
#: process that is gone; if the engine that wrote it owned the run, its effect
#: call never began. The same window marks a RUNNING run's answer as missing.
ABANDONED_AFTER_S = 300.0


def new_run_id() -> str:
    """``run_`` + a uuid4's 32 hex digits — the id evidence_shadow already uses."""
    return "run_" + uuid.uuid4().hex


def digest(value: Any) -> str:
    """sha256 of the canonical JSON of *value* (sorted keys, no whitespace,
    UTF-8 unescaped, anything not JSON rendered with ``str``) — the same digest
    ``service_dispatcher.params_digest`` writes into evidence_shadow, so a run
    and its shadow row carry the same parameters digest."""
    canonical = json.dumps(value, sort_keys=True, separators=(",", ":"),
                           ensure_ascii=False, default=str)
    return hashlib.sha256(canonical.encode("utf-8")).hexdigest()


def actor_hash(actor: str) -> str:
    """sha256 of the resolved caller, or "" when the entry point resolved none."""
    return hashlib.sha256(actor.encode("utf-8")).hexdigest() if actor else ""


def insert_run(
    conn: sqlite3.Connection,
    *,
    run_id: str,
    action: str,
    service: str,
    actor_hash: str,
    params_digest: str,
    state: str,
    started_at: float,
    key: str = "",
    decision_ref: str = "",
) -> None:
    if state not in (START, RUNNING):
        raise ValueError(f"a run starts in START or RUNNING, not {state!r}")
    conn.execute(
        "INSERT INTO workflow_runs (run_id, key, action, service, actor_hash, "
        "params_digest, state, decision_ref, started_at, terminal_at) "
        "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, NULL)",
        (run_id, key, action, service, actor_hash, params_digest, state,
         decision_ref, started_at),
    )


def append_step(
    conn: sqlite3.Connection,
    run_id: str,
    kind: str,
    state: str,
    *,
    at: float,
    payload_digest: str = "",
    tx_hash: str = "",
) -> int:
    """Append one step to *run_id*'s history and return its sequence number."""
    (last,) = conn.execute(
        "SELECT COALESCE(MAX(seq), 0) FROM workflow_steps WHERE run_id = ?", (run_id,)
    ).fetchone()
    seq = int(last) + 1
    conn.execute(
        "INSERT INTO workflow_steps (run_id, seq, kind, payload_digest, tx_hash, state, at) "
        "VALUES (?, ?, ?, ?, ?, ?, ?)",
        (run_id, seq, kind, payload_digest, tx_hash, state, at),
    )
    return seq


def transition(conn: sqlite3.Connection, run_id: str, expected: str, to: str, *, at: float) -> bool:
    """Move *run_id* from *expected* to *to*. True when it moved; False when the
    run was not in *expected* (another writer moved it first, or it is gone)."""
    if (expected, to) not in TRANSITIONS:
        raise ValueError(f"a run cannot go from {expected} to {to}")
    cur = conn.execute(
        "UPDATE workflow_runs SET state = ?, terminal_at = ? WHERE run_id = ? AND state = ?",
        (to, at if to in TERMINAL else None, run_id, expected),
    )
    return cur.rowcount == 1


def _rows(source: Any, sql: str, params: tuple) -> list:
    """Rows from a connection (inside a transaction) or from the platform
    ``Database`` (a synchronous read)."""
    if isinstance(source, sqlite3.Connection):
        return source.execute(sql, params).fetchall()
    return source.fetchall_sync(sql, params)


def get_run(source: Any, run_id: str) -> dict | None:
    rows = _rows(source, "SELECT * FROM workflow_runs WHERE run_id = ?", (run_id,))
    return dict(rows[0]) if rows else None


def get_steps(source: Any, run_id: str) -> list[dict]:
    return [dict(r) for r in _rows(
        source, "SELECT * FROM workflow_steps WHERE run_id = ? ORDER BY seq", (run_id,))]


def recover_runs(conn: sqlite3.Connection, *, now: float,
                 abandoned_after_s: float = ABANDONED_AFTER_S) -> dict[str, list[str]]:
    """What a process that died left behind, closed the only ways that are true.

    * An OWNED START run (its ``start`` step says ``recorded``) older than the
      window never began its effect call — the engine that owned it lets no
      call begin before the run is RUNNING — so it ends ABORT (step
      ``abort``/``not_attempted``). Its idempotency key is released by the
      caller in the same transaction: a request that never acted binds nothing.
    * Any other START run older than the window — ``observed``, or a start step
      that says neither — may have begun its call without a mark. Its state is
      NOT changed and its key is NOT released; it gains one
      ``unknown_effect``/``not_known_if_called`` step, once ("undetermined").
    * A RUNNING run older than the window may have acted. Its state is NOT
      changed — it is not failed, not completed, not retried — and it gains one
      ``unknown_effect``/``no_answer_recorded`` step, once.

    Idempotent and deterministic: a second pass over the same file changes
    nothing, and two passes over copies of one file make the same changes.
    """
    cutoff = now - abandoned_after_s
    aborted: list[str] = []
    undetermined: list[str] = []
    unknown: list[str] = []
    for run_id, word in conn.execute(
        "SELECT r.run_id, COALESCE((SELECT s.state FROM workflow_steps s WHERE s.run_id = "
        "r.run_id AND s.kind = ? ORDER BY s.seq LIMIT 1), '') FROM workflow_runs r "
        "WHERE r.state IN ('START', 'RUNNING') AND r.state = ? AND r.started_at < ? "
        "AND NOT EXISTS (SELECT 1 FROM workflow_steps u WHERE u.run_id = r.run_id "
        "AND u.kind = ?) ORDER BY r.started_at, r.run_id",
        (STEP_START, START, cutoff, STEP_UNKNOWN)).fetchall():
        if word == START_OWNED:
            if transition(conn, run_id, START, ABORT, at=now):
                append_step(conn, run_id, STEP_ABORT, "not_attempted", at=now)
                aborted.append(run_id)
        else:
            append_step(conn, run_id, STEP_UNKNOWN, NOT_KNOWN_IF_CALLED, at=now)
            undetermined.append(run_id)
    for (run_id,) in conn.execute(
        "SELECT r.run_id FROM workflow_runs r WHERE r.state IN ('START', 'RUNNING') "
        "AND r.state = ? AND r.started_at < ? AND NOT EXISTS (SELECT 1 FROM workflow_steps s WHERE s.run_id = r.run_id "
        "AND s.kind = ?) ORDER BY r.started_at, r.run_id",
        (RUNNING, cutoff, STEP_UNKNOWN)).fetchall():
        append_step(conn, run_id, STEP_UNKNOWN, NO_ANSWER_RECORDED, at=now)
        unknown.append(run_id)
    return {"aborted": aborted, "undetermined": undetermined, "unknown": unknown}
