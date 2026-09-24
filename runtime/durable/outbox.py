"""The transactional outbox and THE ONE LOOP that drains it (database migration 10).

WHAT IT REPLACES. Two things delivered a state-modifying action's side records
with nobody owning their lifecycle:

* the attestation — handed to an in-memory batch queue that submits when 50
  have gathered. Its interval timer (``BatchProcessor.start``) has never had a
  caller, so an attestation below the threshold had no time bound and was lost
  when the process exited;
* the public feed entry — ``asyncio.create_task(feed.ingest(...))``, fire and
  forget, lost with the process.

In ``engines.durable.mode = "on"`` both are rows in this table, written in the
SAME transaction as the run's terminal state, and this loop delivers them: the
attestation through ``BatchProcessor.submit_now`` (the batch processor's
submission path, now the outbox's client) and the feed entry through
``SocialFeedEngine.ingest`` under an event id derived from the run, which the
feed stores once. In shadow the rows are written as ``recorded`` — the legacy
path delivered them — and nothing ever drains a ``recorded`` row.

AT MOST ONCE, BY CONSTRUCTION. A row is marked ``attempting`` in its own
transaction BEFORE its delivery is tried. What a delivery answers decides the
next state: ``done``; ``pending`` again after a backoff when the answer proves
nothing was sent (the chain is not configured; a mined revert); ``dead`` after
the fifth such answer; or ``held`` when the answer does not say whether an
attestation went out. A held attestation is never sent again by this loop —
two attestations on a public chain for one action cannot be taken back — and
it is logged at ERROR for a person to settle. A row found still ``attempting``
after its lease (the process died mid-delivery) is held the same way if it is
an attestation, and delivered again if it is a feed entry, which is safe
because the feed keys it by the run.

WHAT THIS LOOP CANNOT DO. It delivers exactly two kinds, to exactly two
clients. It has no path into a service, the dispatcher, a tool or a gate: a row
cannot make it act, only make it attest or publish, and only for a run the
journal says completed with a settled answer. A row that does not match its run
— no such run, a run that did not complete, an answer that was not settled, a
payload whose digest is not the one recorded, a kind with no client — is held
and delivered to nobody.
"""

from __future__ import annotations

import asyncio
import hashlib
import json
import logging
import sqlite3
import time
from dataclasses import dataclass
from typing import Any, Awaitable, Callable

from runtime.durable import journal

logger = logging.getLogger(__name__)

KINDS: tuple[str, ...] = ("attest", "feed", "notify")

RECORDED = "recorded"      # shadow: the legacy path delivered it; never drained
PENDING = "pending"        # mode on: waiting for the loop
ATTEMPTING = "attempting"  # a delivery was begun and has not answered
DONE = "done"
HELD = "held"              # nobody knows whether it went out, or it does not match its run
DEAD = "dead"              # five deliveries answered that nothing was sent

MAX_ATTEMPTS = 5
RETRY_BASE_S = 30.0
RETRY_CAP_S = 3600.0
#: How long a delivery may take before its row is treated as interrupted. The
#: slowest delivery is an attestation waiting up to 120 s for its receipt.
LEASE_S = 300.0
TICK_S = 5.0
#: How long a stopping gateway waits for a delivery already under way to
#: answer before cancelling it. A delivery cut off is not lost — its row is
#: `attempting` — but an attestation cut off is then held for a person, so a
#: restart lets the one in hand finish first.
STOP_GRACE_S = 20.0


@dataclass(frozen=True)
class Delivery:
    """What one delivery answered: ``done``, ``retry`` (provably nothing was
    sent) or ``held`` (nobody can say)."""
    outcome: str
    note: str = ""


Deliverer = Callable[[dict, dict], Awaitable[Delivery]]


def payload_text(payload: Any) -> str:
    return json.dumps(payload, sort_keys=True, separators=(",", ":"),
                      ensure_ascii=False, default=str)


def text_digest(text: str) -> str:
    return hashlib.sha256(text.encode("utf-8", "surrogatepass")).hexdigest()


def enqueue(conn: sqlite3.Connection, *, run_id: str, kind: str, payload: Any,
            deliver: bool, now: float) -> None:
    """Write one row for *run_id* inside the caller's transaction. ``deliver``
    False writes shadow bookkeeping (``recorded``, no payload kept) that nothing
    drains; True writes a ``pending`` row the loop delivers."""
    if kind not in KINDS:
        raise ValueError(f"unknown outbox kind {kind!r}")
    text = payload_text(payload)
    conn.execute(
        "INSERT INTO outbox (run_id, kind, payload, payload_digest, state, attempts, "
        "next_at, done_at, last_error, created_at) VALUES (?, ?, ?, ?, ?, 0, ?, ?, '', ?)",
        (run_id, kind, text if deliver else "", text_digest(text),
         PENDING if deliver else RECORDED, now, None if deliver else now, now))


def backoff_s(attempts: int, row_id: int) -> float:
    """30 s, 60 s, 120 s … capped at an hour, plus a jitter under a second
    derived from the row, not drawn at random, so a recovery is repeatable."""
    base = min(RETRY_CAP_S, RETRY_BASE_S * (2 ** max(0, attempts - 1)))
    jitter = int(hashlib.sha256(f"{row_id}:{attempts}".encode()).hexdigest()[:8], 16) % 1000
    return base + jitter / 1000.0


def feed_event_id(run_id: str) -> str:
    """The feed event id a run's publication is stored under (16 hex, the
    feed's own id shape): one run, one feed entry, however often delivered."""
    return hashlib.sha256(f"feed|{run_id}".encode()).hexdigest()[:16]


def classify_attestation(result: Any) -> Delivery:
    """What an attestation client's answer establishes about the send.

    Retried only when the answer proves nothing reached the chain: ``skipped``
    (the chain is not configured, a dependency is missing) and a revert the
    chain mined (it carries its block). An answer that went out without a
    receipt is done — sending it again is how one attestation becomes two. Any
    other answer, including ``failed`` with no block, does not say whether the
    transaction left, and is held."""
    from runtime.protocols.outcome_truth import SUCCESS, report_of

    if not isinstance(result, dict):
        return Delivery("held", "the attestation client answered with no structure")
    if result.get("broadcast") is True and result.get("settled") is not True:
        return Delivery("done", f"sent, no receipt yet: tx={result.get('tx_hash')}")
    if report_of(result) is SUCCESS:
        tx = result.get("attestation_tx") or result.get("tx_hash") or ""
        return Delivery("done", f"attested: tx={tx}" if tx
                        else "the attestation client reported success")
    status = str(result.get("status") or "").strip().lower()
    if status == "skipped":
        return Delivery("retry", f"not sent: {result.get('reason') or 'skipped'}")
    if status == "failed" and result.get("block_number") is not None:
        return Delivery("retry", f"mined and reverted in block {result.get('block_number')}")
    return Delivery("held", f"the attestation client answered {status or 'nothing'!r} "
                            "without saying whether it sent the transaction")


def attestation_deliverer(processor: Any) -> Deliverer:
    """Deliver an ``attest`` row through the batch processor's submission path,
    one attestation, now, outside its in-memory queue."""
    async def deliver(payload: dict, row: dict) -> Delivery:
        entry = {"id": f"outbox-{row['id']}", "schema_uid": payload.get("schema_uid", ""),
                 "data": payload.get("data") or {}, "recipient": payload.get("recipient", "")}
        results = await processor.submit_now([entry])
        return classify_attestation(results[0] if results else None)
    return deliver


def feed_deliverer(feed_engine: Any, db: Any) -> Deliverer:
    """Deliver a ``feed`` row to the social feed under the run's event id, and
    call it done only when the feed holds that event."""
    async def deliver(payload: dict, row: dict) -> Delivery:
        event_id = feed_event_id(row["run_id"])
        await feed_engine.ingest(event_id=event_id, **payload)
        present = db.fetchall_sync(
            "SELECT 1 FROM social_feed_events WHERE id = ?", (event_id,))
        if present:
            return Delivery("done", f"feed event {event_id}")
        return Delivery("retry", "the feed did not store the event")
    return deliver


def recover_attempts(conn: sqlite3.Connection, *, now: float) -> dict[str, list[int]]:
    """Rows still ``attempting`` past their lease were interrupted mid-delivery.
    An attestation is held — nobody knows whether it was sent — and a feed entry
    goes back to pending, because the feed stores it once under the run's id."""
    held: list[int] = []
    requeued: list[int] = []
    for row in conn.execute(
        "SELECT id, kind FROM outbox WHERE state IN ('pending', 'attempting') "
        "AND state = ? AND next_at < ? ORDER BY id",
        (ATTEMPTING, now)).fetchall():
        row_id, kind = int(row[0]), row[1]
        if kind == "feed":
            conn.execute("UPDATE outbox SET state = ?, next_at = ?, last_error = ? "
                         "WHERE id = ? AND state = ?",
                         (PENDING, now, "delivery interrupted; delivered again under the "
                          "run's event id", row_id, ATTEMPTING))
            requeued.append(row_id)
        else:
            conn.execute("UPDATE outbox SET state = ?, last_error = ? WHERE id = ? AND state = ?",
                         (HELD, "delivery interrupted; whether it was sent is not known, so "
                          "it is not sent again", row_id, ATTEMPTING))
            held.append(row_id)
    return {"held": held, "requeued": requeued}


def counts(db: Any) -> dict[str, int]:
    return {str(r[0]): int(r[1]) for r in db.fetchall_sync(
        "SELECT state, COUNT(*) FROM outbox GROUP BY state")}


class OutboxLoop:
    """The one background loop of the durable engine.

    Every tick it runs the engine's maintenance (recovery of what a dead process
    left behind, and dropping idempotency answers past their 24 hours) and — in
    mode on only — drains the due ``pending`` rows, feed entries first because
    they are local, one row at a time. ``wake()`` starts a tick at once, so a
    feed entry written by a dispatch is published about as promptly as the
    ``create_task`` it replaces.
    """

    def __init__(
        self,
        db: Any,
        *,
        deliver: bool,
        deliverers: dict[str, Deliverer] | None = None,
        maintain: Callable[[], Any] | None = None,
        clock: Callable[[], float] = time.time,
        tick_s: float = TICK_S,
        batch_size: int = 50,
        write_wait: bool = True,
    ) -> None:
        self._db = db
        self.deliver = deliver
        self._deliverers = dict(deliverers or {})
        self._maintain = maintain
        self._clock = clock
        self.tick_s = tick_s
        self.batch_size = batch_size
        self._write_wait = write_wait
        self._task: asyncio.Task | None = None
        self._event: asyncio.Event | None = None
        self._stopping = False
        self.last_tick_at: float | None = None

    # ── lifecycle ──────────────────────────────────────────────────────

    def start(self) -> None:
        if self._task is None or self._task.done():
            self._stopping = False
            self._event = asyncio.Event()
            self._task = asyncio.create_task(self._run())

    async def stop(self, grace_s: float = STOP_GRACE_S) -> None:
        """Stop the loop: no new delivery is begun, the one under way (if any)
        gets *grace_s* to answer, and then the task is cancelled."""
        task, self._task = self._task, None
        if task is None:
            return
        self._stopping = True
        if self._event is not None:
            self._event.set()
        try:
            await asyncio.wait_for(asyncio.shield(task), timeout=grace_s)
        except (asyncio.TimeoutError, asyncio.CancelledError, Exception):
            pass
        if not task.done():
            task.cancel()
            try:
                await task
            except (asyncio.CancelledError, Exception):
                pass

    @property
    def alive(self) -> bool:
        return self._task is not None and not self._task.done()

    def wake(self) -> None:
        if self._event is not None:
            self._event.set()

    async def _run(self) -> None:
        while not self._stopping:
            try:
                await self.tick()
            except asyncio.CancelledError:
                raise
            except Exception:
                logger.exception("Durable outbox loop: tick failed; the next tick tries again")
            event = self._event
            if event is None:
                await asyncio.sleep(self.tick_s)
                continue
            try:
                await asyncio.wait_for(event.wait(), timeout=self.tick_s)
            except asyncio.TimeoutError:
                pass
            event.clear()

    async def tick(self) -> int:
        """Maintenance, then — in mode on — every due row, a batch at a time,
        until a batch comes back short. Returns how many deliveries were tried."""
        self.last_tick_at = self._clock()
        if self._maintain is not None:
            self._maintain()
        if not self.deliver:
            return 0
        tried = 0
        while True:
            batch = await self.drain()
            tried += batch
            if batch < self.batch_size:
                return tried

    # ── delivery ───────────────────────────────────────────────────────

    def _tx(self, work):
        return self._db.transaction_sync(work, wait=self._write_wait)

    async def drain(self, limit: int | None = None) -> int:
        """Deliver the due pending rows; return how many deliveries were tried."""
        now = self._clock()
        rows = self._db.fetchall_sync(
            "SELECT id FROM outbox WHERE state IN ('pending', 'attempting') "
            "AND state = ? AND next_at <= ? "
            "ORDER BY CASE kind WHEN 'feed' THEN 0 ELSE 1 END, id LIMIT ?",
            (PENDING, now, int(limit or self.batch_size)))
        tried = 0
        for (row_id,) in [tuple(r) for r in rows]:
            if self._stopping:
                break
            claimed = self._claim(int(row_id))
            if claimed is None:
                continue
            row, payload = claimed
            delivery = await self._attempt(row, payload)
            self._settle(row, delivery)
            tried += 1
        return tried

    def _claim(self, row_id: int) -> tuple[dict, dict] | None:
        """Mark one due row ``attempting`` — or ``held``, when it does not match
        its run — in one transaction, before anything is delivered."""
        def work(conn):
            row = conn.execute("SELECT * FROM outbox WHERE id = ? AND state = ?",
                               (row_id, PENDING)).fetchone()
            if row is None:
                return None
            row = dict(row)
            now = self._clock()
            problem, payload = self._mismatch(conn, row)
            if problem:
                conn.execute("UPDATE outbox SET state = ?, last_error = ? WHERE id = ? AND state = ?",
                             (HELD, problem, row_id, PENDING))
                return ("held", row, problem)
            conn.execute(
                "UPDATE outbox SET state = ?, attempts = attempts + 1, next_at = ? "
                "WHERE id = ? AND state = ?", (ATTEMPTING, now + LEASE_S, row_id, PENDING))
            row["attempts"] = int(row["attempts"]) + 1
            return ("claimed", row, payload)
        try:
            result = self._tx(work)
        except (sqlite3.Error, RuntimeError):
            logger.warning("Durable outbox: row %s could not be claimed; the next tick tries again",
                           row_id, exc_info=True)
            return None
        if result is None:
            return None
        verdict, row, detail = result
        if verdict == "held":
            logger.error("Durable outbox: row %s (%s, run %s) HELD and delivered to nobody: %s",
                         row_id, row["kind"], row["run_id"], detail)
            return None
        return row, detail

    def _mismatch(self, conn, row: dict) -> tuple[str, dict]:
        """"" and the payload when *row* may be delivered; otherwise why not."""
        if row["kind"] not in self._deliverers:
            return f"no client delivers the kind {row['kind']!r}", {}
        if text_digest(row["payload"]) != row["payload_digest"]:
            return "the payload is not the one recorded", {}
        try:
            payload = json.loads(row["payload"])
        except (ValueError, TypeError):
            return "the payload is not JSON", {}
        if not isinstance(payload, dict):
            return "the payload is not an object", {}
        run = journal.get_run(conn, row["run_id"])
        if run is None:
            return "no run with this id", {}
        if run["state"] != journal.COMPLETE:
            return f"its run is {run['state']}, not COMPLETE", {}
        answered = conn.execute(
            "SELECT state FROM workflow_steps WHERE run_id = ? AND kind = ? "
            "ORDER BY seq DESC LIMIT 1", (row["run_id"], journal.STEP_RETURN)).fetchone()
        if answered is None or answered[0] != "settled":
            return "its run's answer was not settled", {}
        if row["kind"] == "attest":
            data = payload.get("data")
            if not isinstance(data, dict) or data.get("action") != run["action"]:
                return "the attestation does not name its run's action", {}
        if row["kind"] == "feed" and payload.get("action") != run["action"]:
            return "the feed entry does not name its run's action", {}
        return "", payload

    async def _attempt(self, row: dict, payload: dict) -> Delivery:
        deliverer = self._deliverers[row["kind"]]
        try:
            return await deliverer(payload, row)
        except asyncio.CancelledError:
            raise
        except Exception as exc:  # noqa: BLE001 — a delivery that raised is answered, not retried blind
            name = type(exc).__name__
            if row["kind"] == "feed":
                return Delivery("retry", f"the feed raised {name}")
            return Delivery("held", f"the delivery raised {name}; whether it was sent is not known")

    def _settle(self, row: dict, delivery: Delivery) -> None:
        row_id, attempts = int(row["id"]), int(row["attempts"])

        def work(conn):
            now = self._clock()
            if delivery.outcome == "done":
                conn.execute("UPDATE outbox SET state = ?, done_at = ?, payload = '', "
                             "last_error = ? WHERE id = ? AND state = ?",
                             (DONE, now, delivery.note, row_id, ATTEMPTING))
                return DONE
            if delivery.outcome == "retry" and attempts < MAX_ATTEMPTS:
                conn.execute("UPDATE outbox SET state = ?, next_at = ?, last_error = ? "
                             "WHERE id = ? AND state = ?",
                             (PENDING, now + backoff_s(attempts, row_id), delivery.note,
                              row_id, ATTEMPTING))
                return PENDING
            if delivery.outcome == "retry":
                conn.execute("UPDATE outbox SET state = ?, done_at = ?, payload = '', "
                             "last_error = ? WHERE id = ? AND state = ?",
                             (DEAD, now, delivery.note, row_id, ATTEMPTING))
                return DEAD
            conn.execute("UPDATE outbox SET state = ?, last_error = ? WHERE id = ? AND state = ?",
                         (HELD, delivery.note, row_id, ATTEMPTING))
            return HELD
        try:
            state = self._tx(work)
        except (sqlite3.Error, RuntimeError):
            # The row stays `attempting`; after its lease an attestation is held
            # and a feed entry is delivered again under its own event id.
            logger.warning("Durable outbox: row %s delivered (%s) but its state could not be "
                           "written", row_id, delivery.outcome, exc_info=True)
            return
        if state == DEAD:
            logger.error("Durable outbox: row %s (%s, run %s) is a DEAD LETTER after %d attempts: %s",
                         row_id, row["kind"], row["run_id"], attempts, delivery.note)
        elif state == HELD:
            logger.error("Durable outbox: row %s (%s, run %s) HELD, not sent again: %s",
                         row_id, row["kind"], row["run_id"], delivery.note)
