"""The transactional outbox (``outbox``, database migration 11) and THE ONE LOOP
of the durable engine.

WHAT IT REPLACES. The service dispatcher delivered a completed action's two side
records with nobody owning their lifecycle:

* the attestation — awaited onto an in-memory batch queue that submits once 50
  have gathered, whose interval timer (``BatchProcessor.start``) has never had
  a caller, so an attestation below the threshold had no time bound and was
  lost when the process exited;
* the public feed entry — ``asyncio.create_task(feed.ingest(...))``, fire and
  forget.

In ``engines.durable.mode = "on"`` each is a row here, written in the SAME
transaction as the run's terminal state, and this loop delivers it: the
attestation through the batch processor's submission path, one per row, the
same client call a flush makes; the feed entry through the feed engine's
``ingest``, the same call the task made. In shadow the rows are written as
already handed off — the legacy path delivered them — and nothing drains them.

DIGESTS, NOT PAYLOADS. A row holds ``payload_digest`` only. The payload is
held in memory by the process that wrote the row, and a row is delivered only
when this process holds a payload for it with that digest, for that run and
kind, and its run is COMPLETE. Anything else — a row another process wrote, a
row written by hand, a row whose run is not COMPLETE, a payload that does not
match — is delivered to nobody: it is given up (``done_at`` and ``next_at``
both NULL) with an ``outbox:<kind>`` step on its run saying why, and a row this
process does not hold is given up only once it has been due for
``ABANDONED_AFTER_S``, so another live process's row is never taken.

AT MOST ONCE. Before a delivery is tried its row is claimed (``attempts`` + 1,
``next_at`` moved past a lease) in its own transaction. What the delivery
answers decides the rest: handed off (``done_at``); ``retry`` — only when the
answer proves nothing went out, or it is the answer the batch processor itself
re-queues — after a backoff, until ``MAX_ATTEMPTS``; or given up. A delivery
that raised is given up, never retried blind. A process that dies mid-delivery
leaves a claimed row whose payload no process holds, so it is never sent again.

WHAT THIS LOOP CANNOT DO. It calls exactly the delivery closures the service
dispatcher handed it, for rows it wrote. It has no path into a service, a
tool, the dispatcher or a gate: a row cannot make it act, only make it attest
or publish what a completed run already produced.
"""

from __future__ import annotations

import asyncio
import hashlib
import logging
import time
from dataclasses import dataclass
from typing import Any, Awaitable, Callable

from runtime.durable import journal
from runtime.durable.journal import Tx

logger = logging.getLogger(__name__)

KINDS: tuple[str, ...] = ("attest", "feed")

#: Attempts in all, the first and four retries — the batch processor's own bound.
MAX_ATTEMPTS = 5
RETRY_BASE_S = 30.0
RETRY_CAP_S = 3600.0
#: How long a claimed delivery may take before its row is due again. The
#: slowest delivery is an attestation waiting on its receipt.
LEASE_S = 300.0
#: A delivery still unanswered after this long is cut off and given up (it may
#: have gone out, so it is never tried again); below the lease, so no claimed
#: row is ever due again while its delivery is still in hand.
DELIVERY_TIMEOUT_S = 240.0
TICK_S = 5.0
BATCH = 50
#: How long a stopping gateway lets the delivery in hand finish.
STOP_GRACE_S = 10.0

DELIVERED = "delivered"
RETRY = "retry"
GIVEN_UP = "given_up"
GIVEN_UP_ELSEWHERE = "given_up_elsewhere"   # internal: the row was given up by another process


@dataclass(frozen=True)
class Delivery:
    """What one delivery answered, in a fixed word (``detail``)."""
    outcome: str
    detail: str = ""


@dataclass(frozen=True)
class Held:
    """A payload this process holds for one row: the digest it was written
    under and the closure that delivers it (built by the dispatcher over its
    own copies)."""
    run_id: str
    kind: str
    payload_digest: str
    deliver: Callable[[], Awaitable[Delivery]]


def backoff_s(attempts: int, row_id: int) -> float:
    """30 s, 60 s, 120 s … capped at an hour, plus a jitter under a second
    derived from the row rather than drawn, so a recovery is repeatable."""
    base = min(RETRY_CAP_S, RETRY_BASE_S * (2 ** max(0, attempts - 1)))
    jitter = int(hashlib.sha256(f"{row_id}:{attempts}".encode()).hexdigest()[:8], 16) % 1000
    return base + jitter / 1000.0


def insert(tx: Tx, *, run_id: str, kind: str, payload_digest: str, now: float,
           deliver: bool) -> int:
    """One row, inside the caller's transaction. ``deliver`` True writes a row
    the loop delivers (due now); False writes shadow bookkeeping, handed off at
    once by the legacy path."""
    if kind not in KINDS:
        raise ValueError(f"unknown outbox kind {kind!r}")
    tx.run("INSERT INTO outbox (run_id, kind, payload_digest, attempts, next_at, done_at) "
           "VALUES (?, ?, ?, 0, ?, ?)",
           (run_id, kind, payload_digest, now if deliver else None, None if deliver else now))
    return int(tx.one("SELECT last_insert_rowid()")[0])


def counts(db: Any) -> dict[str, int]:
    """Rows by where they stand: due, delivered (handed off), given up."""
    row = db.fetchall_sync(
        "SELECT COALESCE(SUM(done_at IS NULL AND next_at IS NOT NULL), 0), "
        "COALESCE(SUM(done_at IS NOT NULL), 0), "
        "COALESCE(SUM(done_at IS NULL AND next_at IS NULL), 0) FROM outbox")[0]
    return {"due": int(row[0]), "handed_off": int(row[1]), "given_up": int(row[2])}


class OutboxLoop:
    """The one background loop of the durable engine.

    Every tick it runs the engine's maintenance (closing runs a dead process
    left open) and — when ``deliver`` is set (mode on) — drains every due row.
    ``wake()`` starts a tick at once, so a feed entry written by a dispatch is
    published about as promptly as the task it replaces."""

    def __init__(self, db: Any, *, deliver: bool, maintain: Callable[[], Any] | None = None,
                 clock: Callable[[], float] = time.time, tick_s: float = TICK_S,
                 abandoned_after_s: float = journal.ABANDONED_AFTER_S,
                 write_wait: bool = True) -> None:
        self._db = db
        self.deliver = deliver
        self._maintain = maintain
        self._clock = clock
        self.tick_s = tick_s
        self._abandoned_after_s = abandoned_after_s
        self._write_wait = write_wait
        self._held: dict[int, Held] = {}
        #: Deliveries that answered and whose answer could not be written yet:
        #: written again every tick, never delivered again.
        self._unsettled: dict[int, tuple[tuple, Delivery]] = {}
        self._task: asyncio.Task | None = None
        self._event: asyncio.Event | None = None
        self._stopping = False
        self.last_tick_at: float | None = None
        #: The last time the loop did something: began a tick or answered a delivery.
        self.last_progress_at: float | None = None
        self.ticks = 0

    # ── what this process holds ─────────────────────────────────────────

    def hold(self, row_id: int, held: Held) -> None:
        self._held[row_id] = held

    def held_count(self) -> int:
        return len(self._held)

    # ── lifecycle ──────────────────────────────────────────────────────

    def start(self) -> None:
        if self._task is None or self._task.done():
            self._stopping = False
            self._event = asyncio.Event()
            self._task = asyncio.get_running_loop().create_task(self._run())

    async def stop(self, grace_s: float = STOP_GRACE_S) -> None:
        """No new delivery is begun; the one in hand gets *grace_s* to answer;
        then the task is cancelled. A delivery cut off by the cancellation is
        given up, never tried again; payloads still held stay with this object
        (a loop started again delivers them) and are lost with the process, whose
        rows the next process gives up."""
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

    def healthy(self, now: float | None = None) -> bool:
        """Running, and making progress: a tick began, or a delivery answered,
        within the longest a single delivery may take plus a margin — so a loop
        busy with slow deliveries is healthy and a stuck one is not."""
        if not self.alive:
            return False
        if self.last_progress_at is None:
            return True
        now = self._clock() if now is None else now
        return now - self.last_progress_at <= DELIVERY_TIMEOUT_S + max(60.0, 12 * self.tick_s)

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
        """Maintenance, then — when delivering — every due row, a batch at a
        time. Returns how many deliveries were tried."""
        self.last_tick_at = self.last_progress_at = self._clock()
        self.ticks += 1
        if self._maintain is not None:
            self._maintain()
        if not self.deliver:
            return 0
        tried = 0
        while not self._stopping:
            batch, examined = await self.drain()
            tried += batch
            if batch == 0 or examined < BATCH:
                break
        return tried

    # ── delivery ───────────────────────────────────────────────────────

    def _tx(self, work):
        return journal.transaction(self._db, work, wait=self._write_wait)

    async def drain(self) -> tuple[int, int]:
        """Give up the rows no process has held for the window, then deliver
        the due rows this process holds; ``(deliveries tried, held rows
        examined)``. Rows this process does not hold are never selected for
        delivery, so however many of them there are, none stands in front of a
        row it holds."""
        now = self._clock()
        self.settle_unsettled()
        self._renew(now)
        cols = "id, run_id, kind, payload_digest, attempts, next_at"
        for row in [tuple(r) for r in self._db.fetchall_sync(
                f"SELECT {cols} FROM outbox WHERE done_at IS NULL AND next_at IS NOT NULL "
                "AND next_at < ? ORDER BY next_at, id LIMIT ?",
                (now - self._abandoned_after_s, 1000))]:
            if row[0] not in self._held:
                self._give_up(row[0], row[1], row[2], "payload_not_held",
                              due_before=now - self._abandoned_after_s)
        held_ids = sorted(i for i in self._held if i not in self._unsettled)
        rows: list[tuple] = []
        for i in range(0, len(held_ids), 500):
            chunk = held_ids[i:i + 500]
            rows += [tuple(r) for r in self._db.fetchall_sync(
                f"SELECT {cols} FROM outbox WHERE id IN ({', '.join('?' for _ in chunk)}) "
                "AND done_at IS NULL AND next_at IS NOT NULL AND next_at <= ?",
                (*chunk, now))]
        rows = sorted(rows, key=lambda r: (r[5], r[0]))[:BATCH]
        tried = 0
        for row in rows:
            if self._stopping:
                break
            self._renew(self._clock())
            claimed = self._claim(row, self._clock())
            if claimed is None:
                continue
            delivery = await self._attempt(claimed, row)
            self.last_progress_at = self._clock()
            self._settle(row, delivery)
            tried += 1
        return tried, len(rows)

    def settle_unsettled(self) -> None:
        """Write the answers of deliveries that answered and could not be
        marked yet (never delivering them again)."""
        for row, delivery in list(self._unsettled.values()):
            self._settle(row, delivery)

    def _renew(self, now: float) -> None:
        """Keep every row this process holds from looking abandoned to another
        process while this one is busy — renewed before each delivery, so no
        held row is ever older than one delivery (``DELIVERY_TIMEOUT_S``, under
        the window): a held row that is due has its ``next_at`` moved up to now,
        and a row whose answer is still to be written has its lease extended."""
        ids = [i for i in self._held if i not in self._unsettled]
        waiting = list(self._unsettled)
        if not ids and not waiting:
            return

        def work(tx: Tx) -> None:
            for i in range(0, len(ids), 500):
                chunk = ids[i:i + 500]
                tx.run(f"UPDATE outbox SET next_at = ? WHERE id IN ({', '.join('?' for _ in chunk)}) "
                       "AND done_at IS NULL AND next_at IS NOT NULL AND next_at < ?",
                       (now, *chunk, now))
            for i in range(0, len(waiting), 500):
                chunk = waiting[i:i + 500]
                tx.run(f"UPDATE outbox SET next_at = ? WHERE id IN ({', '.join('?' for _ in chunk)}) "
                       "AND done_at IS NULL AND next_at IS NOT NULL AND next_at < ?",
                       (now + LEASE_S, *chunk, now + LEASE_S / 2))
        try:
            self._tx(work)
        except Exception:  # noqa: BLE001 — the next pass renews again
            pass

    def _claim(self, row: tuple, now: float) -> Held | None:
        row_id, run_id, kind, row_digest, attempts, next_at = row
        held = self._held.get(row_id)
        if held is None:
            if next_at < now - self._abandoned_after_s:
                self._give_up(row_id, run_id, kind, "payload_not_held")
            return None
        problem = ""
        if (held.run_id, held.kind, held.payload_digest) != (run_id, kind, row_digest):
            problem = "payload_mismatch"
        else:
            run = journal.get_run(self._db, run_id)
            if run is None or run["state"] != journal.COMPLETE:
                problem = "run_not_complete"
        if problem:
            self._held.pop(row_id, None)
            self._give_up(row_id, run_id, kind, problem)
            return None

        def work(tx: Tx) -> bool:
            if tx.execute(
                    "UPDATE outbox SET attempts = attempts + 1, next_at = ? "
                    "WHERE id = ? AND done_at IS NULL AND next_at IS NOT NULL AND next_at <= ?",
                    (now + LEASE_S, row_id, now)) == 1:
                return True
            if tx.one("SELECT 1 FROM outbox WHERE id = ? AND done_at IS NULL "
                      "AND next_at IS NOT NULL", (row_id,)) is None:
                self._held.pop(row_id, None)      # done or given up elsewhere
            return False
        try:
            return held if self._tx(work) else None
        except Exception:
            logger.warning("Durable outbox: row %s could not be claimed; the next tick tries "
                           "again", row_id, exc_info=True)
            return None

    async def _attempt(self, held: Held, row: tuple) -> Delivery:
        try:
            delivery = await asyncio.wait_for(held.deliver(), DELIVERY_TIMEOUT_S)
        except asyncio.TimeoutError:
            return Delivery(GIVEN_UP, "delivery_timed_out")
        except asyncio.CancelledError:
            # Interrupted mid-delivery (the loop is stopping): whether it went
            # out is not known, so it is never tried again — given up, now.
            self._held.pop(row[0], None)
            self._give_up(row[0], row[1], row[2], "delivery_interrupted")
            raise
        except Exception as exc:  # noqa: BLE001 — a delivery that raised is given up, not retried blind
            return Delivery(GIVEN_UP, "raised:" + type(exc).__name__)
        if not isinstance(delivery, Delivery) or delivery.outcome not in (DELIVERED, RETRY, GIVEN_UP):
            return Delivery(GIVEN_UP, "no_answer")
        return delivery

    def _settle(self, row: tuple, delivery: Delivery) -> None:
        row_id, run_id, kind, _digest, attempts, _next = row
        attempts = int(attempts) + 1

        def work(tx: Tx) -> str:
            now = self._clock()
            if delivery.outcome == DELIVERED:
                tx.run("UPDATE outbox SET done_at = ?, next_at = NULL "
                       "WHERE id = ? AND done_at IS NULL", (now, row_id))
                word = DELIVERED
            elif delivery.outcome == RETRY and attempts < MAX_ATTEMPTS:
                # Only while the row is still this delivery's: a row another
                # process gave up meanwhile stays given up.
                if tx.execute("UPDATE outbox SET next_at = ? WHERE id = ? AND done_at IS NULL "
                              "AND next_at IS NOT NULL",
                              (now + backoff_s(attempts, row_id), row_id)) != 1:
                    return GIVEN_UP_ELSEWHERE
                word = RETRY
            else:
                tx.run("UPDATE outbox SET next_at = NULL WHERE id = ? AND done_at IS NULL",
                       (row_id,))
                word = GIVEN_UP
            journal.step(tx, run_id, journal.next_seq(tx, run_id), "outbox:" + kind, word,
                         at=now, detail=delivery.detail)
            return word
        try:
            word = self._tx(work)
        except Exception:
            # The answer is kept and written again on the next pass; the
            # payload is not delivered again meanwhile (the row stays claimed,
            # and the answer, not the payload, is what is retried).
            logger.warning("Durable outbox: row %s answered %s and could not be marked yet",
                           row_id, delivery.outcome, exc_info=True)
            self._unsettled[row_id] = (row, delivery)
            return
        self._unsettled.pop(row_id, None)
        if word != RETRY:
            self._held.pop(row_id, None)
        if word == GIVEN_UP_ELSEWHERE:
            return
        if word == GIVEN_UP:
            logger.error("Durable outbox: row %s (%s, run %s) given up after %d attempt(s): %s",
                         row_id, kind, run_id, attempts, delivery.detail)

    def _give_up(self, row_id: int, run_id: str, kind: str, why: str, *,
                 due_before: float | None = None) -> None:
        """Give *row_id* up. With *due_before* (a row this process does not
        hold), only while it is still that stale: a row its holder renewed in
        the meantime is left to its holder."""
        def work(tx: Tx) -> bool:
            if due_before is None:
                changed = tx.execute("UPDATE outbox SET next_at = NULL WHERE id = ? "
                                     "AND done_at IS NULL AND next_at IS NOT NULL", (row_id,))
            else:
                changed = tx.execute("UPDATE outbox SET next_at = NULL WHERE id = ? "
                                     "AND done_at IS NULL AND next_at IS NOT NULL "
                                     "AND next_at < ?", (row_id, due_before))
            if changed != 1:
                return False
            if journal.get_run(tx, run_id) is not None:
                journal.step(tx, run_id, journal.next_seq(tx, run_id), "outbox:" + kind,
                             GIVEN_UP, at=self._clock(), detail=why)
            return True
        try:
            if self._tx(work):
                logger.error("Durable outbox: row %s (%s, run %s) given up, delivered to nobody: %s",
                             row_id, kind, run_id, why)
        except Exception:
            logger.warning("Durable outbox: row %s could not be given up", row_id, exc_info=True)
