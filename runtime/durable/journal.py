"""The run journal: ``workflow_runs`` and ``workflow_steps`` (database migration 10).

A run is one state-modifying action the durable engine journals — a
state-modifying ``ServiceDispatcher.execute`` or a twin tool's platform-key
signing call. Its ``state`` is the LIFECYCLE, and only that::

    START ──► RUNNING ──► COMPLETE | FAIL
      │
      └────► ABORT

* ``START`` — the run is opened; its effect call has not begun.
* ``RUNNING`` — the effect call began. From here on the action may have acted,
  whatever happens to this process.
* ``COMPLETE`` — the call returned an answer. Not "the action succeeded": the
  answer's word is on the ``return`` step, in the words the layer that made the
  call already used (the dispatcher's settled / broadcast / refused, the tool
  dispatcher's success / failure / unknown).
* ``FAIL`` — the call raised, or the run ended with no answer recorded (the
  process died mid-call, the call was cancelled or timed out): its effect is
  unknown, and an ``unknown_effect`` step says so. FAIL never means "did not
  happen", and nothing here ever runs a FAIL run again.
* ``ABORT`` — the run ended before its call began.

A run is opened and moved to RUNNING in ONE transaction, written immediately
before its call: every entry point reaches its call from the moment it decides
to run it without awaiting anything, so no other task can see a START row in
between, and a START that is never followed by its call is written as START and
ABORT together, with the step that says why. Only a run another process left
behind can be found in START or RUNNING; recovery (``recover``) closes it the
only ways that are true: START → ABORT (its call never began) and RUNNING →
FAIL with ``unknown_effect`` (it may have acted).

Every write here takes a transaction handle (``transaction``), so a caller
composes a transition with its steps, its outbox rows and its idempotency key
in ONE transaction; every transition is a compare-and-set on the state it
expects, so a transition that lost a race changes nothing and says so.

Only digests and fixed words reach these tables: the caller is a sha256, the
parameters a sha256 of their canonical JSON, a step's ``detail`` a fixed word
or ``sha256:<hex>``.
"""

from __future__ import annotations

import hashlib
import json
import uuid
from typing import Any, Callable, TypeVar

START = "START"
RUNNING = "RUNNING"
COMPLETE = "COMPLETE"
ABORT = "ABORT"
FAIL = "FAIL"

STATES: tuple[str, ...] = (START, RUNNING, COMPLETE, ABORT, FAIL)
OPEN: frozenset[str] = frozenset({START, RUNNING})
TERMINAL: frozenset[str] = frozenset({COMPLETE, ABORT, FAIL})

#: The only transitions a run may make.
TRANSITIONS: frozenset[tuple[str, str]] = frozenset({
    (START, RUNNING), (START, ABORT), (RUNNING, COMPLETE), (RUNNING, FAIL),
})

# Step names, in the order a run appends them.
STEP_START = "start"              # state: "opened"
STEP_CALL = "call"                # state: "began"
STEP_RETURN = "return"            # state: the caller's word for the answer
STEP_RAISE = "raise"              # state: "raised"; detail: the exception's type, digested
STEP_ABORT = "abort"              # state: why the call never began
STEP_UNKNOWN = "unknown_effect"   # state: why no answer is recorded

#: The shortest time an open run that no live engine in this process holds is
#: left before recovery closes it. The gateway derives its window from its own
#: request timeout (``wiring.abandoned_window``: 120 s by default, so 300 s):
#: an entry point answers within that budget, so an open run older than the
#: window that this process does not hold was left by a process that is gone.
ABANDONED_AFTER_S = 300.0

T = TypeVar("T")


# ── digests ─────────────────────────────────────────────────────────────────

def new_run_id() -> str:
    """``run_`` + a uuid4's 32 hex digits — the shape evidence_shadow's ids have."""
    return "run_" + uuid.uuid4().hex


def digest(value: Any) -> str:
    """sha256 of the canonical JSON of *value* (sorted keys, no whitespace,
    UTF-8 unescaped, anything not JSON rendered with ``str``) — the digest
    ``service_dispatcher.params_digest`` writes into evidence_shadow."""
    canonical = json.dumps(value, sort_keys=True, separators=(",", ":"),
                           ensure_ascii=False, default=str)
    return hashlib.sha256(canonical.encode("utf-8", "surrogatepass")).hexdigest()


def text_digest(text: str) -> str:
    return hashlib.sha256(text.encode("utf-8", "surrogatepass")).hexdigest()


def actor_hash(actor: str) -> str:
    """sha256 of the resolved caller, or "" when the entry point resolved none."""
    return hashlib.sha256(actor.encode("utf-8")).hexdigest() if actor else ""


def label(value: str, known: Callable[[str], bool]) -> str:
    """*value* verbatim when the code defines it (*known*), else ``sha256:`` and
    its digest: a name a caller or a model chose is never written out."""
    return value if known(value) else "sha256:" + text_digest(value)


# ── the transaction ─────────────────────────────────────────────────────────

class Tx:
    """The statements of one transaction, on the platform ``Database``'s own
    connection, through its public synchronous calls."""

    __slots__ = ("_db",)

    def __init__(self, db: Any) -> None:
        self._db = db

    def run(self, sql: str, params: tuple = ()) -> None:
        """Run one statement."""
        self._db.execute_sync(sql, params)

    def execute(self, sql: str, params: tuple = ()) -> int:
        """Run one statement and return how many rows it changed."""
        self._db.execute_sync(sql, params)
        return int(self._db.fetchall_sync("SELECT changes()")[0][0])

    def rows(self, sql: str, params: tuple = ()) -> list:
        return self._db.fetchall_sync(sql, params)

    def one(self, sql: str, params: tuple = ()):
        found = self._db.fetchall_sync(sql, params)
        return found[0] if found else None


def transaction(db: Any, work: Callable[[Tx], T], *, wait: bool) -> T:
    """Run ``work(tx)`` — synchronous statements only — as ONE ``BEGIN
    IMMEDIATE`` transaction on *db*'s connection, now, and return what it
    returns. An exception inside *work* rolls all of it back and is re-raised.

    No asyncio lock is taken and none is needed: nothing is awaited between
    BEGIN and COMMIT, and every other writer on this connection (the async
    ``execute`` and ``run_in_transaction``, the synchronous sinks) also runs its
    statements on the event loop's thread without awaiting between them, so
    neither can land inside the other. ``wait=False`` sets the busy timeout to
    zero for this transaction only: when another connection holds the database
    the BEGIN raises at once instead of holding the event loop for up to five
    seconds — for records that are dropped rather than waited for (shadow)."""
    previous = None
    if not wait:
        previous = int(db.fetchall_sync("PRAGMA busy_timeout")[0][0])
        db.execute_sync("PRAGMA busy_timeout = 0")
    try:
        db.execute_sync("BEGIN IMMEDIATE")
        try:
            result = work(Tx(db))
            db.execute_sync("COMMIT")
        except BaseException:
            try:
                db.execute_sync("ROLLBACK")
            except Exception:  # noqa: BLE001 — the original error is the one to raise
                pass
            raise
        return result
    finally:
        if previous is not None:
            db.execute_sync(f"PRAGMA busy_timeout = {previous}")


# ── writes ──────────────────────────────────────────────────────────────────

def insert_run(tx: Tx, *, run_id: str, action: str, service: str, actor_hash: str,
               params_digest: str, state: str, started_at: float, key: str = "",
               decision_ref: str = "", terminal_at: float | None = None) -> None:
    if state not in STATES:
        raise ValueError(f"unknown run state {state!r}")
    tx.run(
        "INSERT INTO workflow_runs (run_id, key, action, service, actor_hash, params_digest, "
        "state, decision_ref, started_at, terminal_at) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
        (run_id, key, action, service, actor_hash, params_digest, state, decision_ref,
         started_at, terminal_at if state in TERMINAL else None))


def step(tx: Tx, run_id: str, seq: int, name: str, state: str, *, at: float,
         detail: str = "") -> None:
    tx.run("INSERT INTO workflow_steps (run_id, seq, name, state, detail, at) "
               "VALUES (?, ?, ?, ?, ?, ?)", (run_id, seq, name, state, detail, at))


def next_seq(tx: Tx, run_id: str) -> int:
    """The next step number of a run this process does not hold."""
    return int(tx.one("SELECT COALESCE(MAX(seq), 0) FROM workflow_steps WHERE run_id = ?",
                      (run_id,))[0]) + 1


def move(tx: Tx, run_id: str, expected: str, to: str, *, at: float) -> bool:
    """Compare-and-set *run_id* from *expected* to *to*. True when it moved."""
    if (expected, to) not in TRANSITIONS:
        raise ValueError(f"a run cannot go from {expected} to {to}")
    return tx.execute(
        "UPDATE workflow_runs SET state = ?, terminal_at = ? WHERE run_id = ? AND state = ?",
        (to, at if to in TERMINAL else None, run_id, expected)) == 1


# ── reads ───────────────────────────────────────────────────────────────────

def get_run(source: Any, run_id: str) -> dict | None:
    rows = source.fetchall_sync("SELECT * FROM workflow_runs WHERE run_id = ?", (run_id,)) \
        if not isinstance(source, Tx) else source.rows(
            "SELECT * FROM workflow_runs WHERE run_id = ?", (run_id,))
    return dict(rows[0]) if rows else None


def get_steps(db: Any, run_id: str) -> list[dict]:
    return [dict(r) for r in db.fetchall_sync(
        "SELECT * FROM workflow_steps WHERE run_id = ? ORDER BY seq", (run_id,))]


# ── recovery ────────────────────────────────────────────────────────────────

def abandoned(db: Any, *, now: float, held: frozenset[str] | set[str],
              older_than_s: float = ABANDONED_AFTER_S) -> list[tuple[str, str, str]]:
    """``(run_id, state, key)`` of every open run older than the window that
    *held* (the runs this process's engine has open) does not name. Read-only."""
    return [(r[0], r[1], r[2]) for r in db.fetchall_sync(
        "SELECT run_id, state, key FROM workflow_runs WHERE state IN ('START', 'RUNNING') "
        "AND started_at < ? ORDER BY started_at, run_id", (now - older_than_s,))
        if r[0] not in held]


def recover(tx: Tx, found: list[tuple[str, str, str]], *, now: float) -> dict[str, list[str]]:
    """Close what a process that is gone left open, the only ways that are true.

    * START → ABORT, step ``abort``/``not_attempted``: the call of a run found
      in START never began (a run is moved to RUNNING before its call).
    * RUNNING → FAIL, step ``unknown_effect``/``no_answer_recorded``: the call
      began and no answer was recorded, so it may have acted. It is not retried,
      and a key bound to it stays bound, so a replay never runs it again.

    Deterministic and idempotent: each close is a compare-and-set, so a second
    pass, or another process's, changes nothing."""
    aborted: list[str] = []
    failed: list[str] = []
    for run_id, state, _key in found:
        seq = next_seq(tx, run_id)
        if state == START and move(tx, run_id, START, ABORT, at=now):
            step(tx, run_id, seq, STEP_ABORT, "not_attempted", at=now,
                 detail="left_open_past_window")
            aborted.append(run_id)
        elif state == RUNNING and move(tx, run_id, RUNNING, FAIL, at=now):
            step(tx, run_id, seq, STEP_UNKNOWN, "no_answer_recorded", at=now,
                 detail="left_open_past_window")
            failed.append(run_id)
    return {"aborted": aborted, "failed": failed}
