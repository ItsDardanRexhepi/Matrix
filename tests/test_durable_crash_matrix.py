"""Gate G7: the crash matrix of durable execution, in the cells the plan names.

Engines Phase 2 (runtime/durable), mode on. The test plan's crash matrix
(section 1.5 of the plan's test plan, and its gate G7: "100 seeded injections
per cell", every one passing) is a table of boundaries against crash points —
W1 before the call, W2 during it, W3 after the other side accepted and before
the local record, W4 after the local commit and before publishing, W5 after a
receipt and before reconciling — and asks four proofs of every cell after a
KILL AND A FRESH PROCESS ON THE SAME SQLITE FILE:

* L — no lost workflow: the run is findable by id with a state;
* U — no unauthorized continuation: nothing goes on after the crash that a
  request which passed the gate did not start;
* D — no duplicate effect: each external effect happens at most once;
* R — deterministic recovery: two independent recoveries from the same file
  reach the same state.

Phase 2's exit is G7 at the cells of four boundaries, at the crash points the
plan fills in for them: X1, the client and ``POST /bridge/v1/action`` under an
Idempotency-Key (W2, W4); X2, a route and ``ServiceDispatcher.execute`` (W1,
W2, W4); X6, the dispatcher's attestation and the chain (W1, W2, W3); X7, the
dispatcher's feed entry (W1, W2). Ten cells, ``CELLS``, each with the instants
of ``POINTS``; 100 injections each.

ONE INJECTION. Every draw — the state-modifying name, the marker, the client's
key, whether the request carries one, the service's answer, a raise, the
instant, whether the client replays early and whether the gate refuses its
first replay — comes from ``random.Random`` seeded with the cell and the
injection's index, so the matrix is the same on every run. The first process
runs the request (and, for X6 and X7, the outbox loop's tick) through the real
``ServiceDispatcher`` and ``DurableEngine`` over the platform ``Database``, over
stand-in services, chain and feed, and dies at the instant. In process, the
death is ``snapshot()``: the committed state of the file at that instant, with
the effects and calls made up to it; nothing the process did afterwards
survives. Two of each cell's injections instead run in a child interpreter over
a real file and end it with ``os._exit(137)`` at the instant.

RECOVERY, TWICE. The file is copied twice, and each copy is recovered on its
own by a fresh ``Database`` and ``DurableEngine`` holding nothing in memory: a
replay while the dead run is still inside ``abandoned_after_s`` when the draw
says so (it must be answered and must not act), the clock past the window, one
loop tick (maintenance, then delivery). The two copies' four tables must be
identical, and a second tick changes nothing. Then the client replays twice
under the same key on one of them.

THE PROOFS, as measured here:

* L — every run the dead process committed is in the recovered file under its
  id, and no effect was made without its record: at every service call a
  RUNNING run of that action and those parameters was committed already, and
  at every attestation or feed entry the outbox delivered, that run's outbox
  row of that kind was committed and the run COMPLETE;
* U — recovery (the restart, maintenance and the loop's ticks, before any
  request) makes no effect — no service call, no attestation, no feed entry —
  and moves no run forward: an open run becomes ABORT or FAIL, a closed one
  stays as it was; and a replay the gate refuses makes no effect. No decision
  expires in Phase 2 (there is no decision record yet), so "stops past its
  decision's expiry" is not measured; the engine continues nothing at all;
* D — across the dead process, recovery and the replays, the service's effect
  for the marker happens at most once, and so do the attestation (by the
  outbox or the legacy path) and the feed entry; and exactly once when the dead
  process made no call and left the key unbound and a replay passed the gate;
* R — the two recoveries' tables are identical, and a second pass changes
  nothing;

and, recorded beside them, T (every run in the recovered file is COMPLETE,
ABORT or FAIL) and A (every request is answered what the spec says: the first
answer, ``idempotency_in_progress``, ``idempotency_answer_not_held`` after a
restart, or a normal dispatch when the key was never bound).

WHAT THE PLAN ASKS AND THIS DOES NOT MEASURE is in the artefact's
``not_measured``: X1.W1 (the client's own outbox, a later phase), W5 and W3
outside X6, and a reconciler at X6.W3 — there is none: a delivery the chain
took and whose row was not marked is never sent again, and its row is given up.

The artefact is ``tests/baseline/durable_g7_crash_matrix.json``:
``ENGINES_BASELINE=write`` measures and rewrites it; otherwise the matrix is
run again and its counts must equal the committed ones.
"""
from __future__ import annotations

import asyncio
import contextlib
import json
import os
import random
import sqlite3
import subprocess
import sys
import tempfile
from collections import Counter
from dataclasses import asdict, dataclass
from pathlib import Path
from types import SimpleNamespace
from typing import Any, Callable

import pytest

sys.path.insert(0, "tests")

from test_durable_harness import (  # noqa: E402
    ACTION_MAP, BROADCAST, REFUSED, SETTLED, STATE_MODIFYING, WALLET, Boom, Clock, Effects,
    drain, engine, installed, open_db, params_for, resolve_schema, snapshot,
)
from runtime.blockchain.services.service_dispatcher import ServiceDispatcher  # noqa: E402
from runtime.durable import journal, keys, wiring  # noqa: E402
from tests import durable_measured_at  # noqa: E402

ROOT = Path(__file__).resolve().parent.parent
BASELINE = ROOT / "tests" / "baseline"
ARTEFACT = "durable_g7_crash_matrix.json"
WRITE = os.environ.get("ENGINES_BASELINE", "").strip().lower() == "write"

#: The plan's Phase 2 cells: boundary.crash point -> what dies where.
CELLS: dict[str, str] = {
    "X1.W2": ("POST /bridge/v1/action under an Idempotency-Key: the gateway dies while the "
              "request is in its handler, after its run was written"),
    "X1.W4": ("POST /bridge/v1/action under an Idempotency-Key: the run's end is committed and "
              "the answer never reaches the client"),
    "X2.W1": ("a route into ServiceDispatcher.execute: the process dies before the service "
              "call begins"),
    "X2.W2": "a route into ServiceDispatcher.execute: the process dies during the service call",
    "X2.W4": ("a route into ServiceDispatcher.execute: the run's end and its outbox rows are "
              "committed, and nothing is delivered yet"),
    "X6.W1": "the dispatcher's attestation: its outbox row is written and it is not sent yet",
    "X6.W2": "the dispatcher's attestation: the process dies while the chain is being handed it",
    "X6.W3": ("the dispatcher's attestation: the chain took it, and its outbox row is not "
              "marked"),
    "X7.W1": ("the dispatcher's feed entry: its outbox row is written and it is not "
              "published yet"),
    "X7.W2": ("the dispatcher's feed entry: the process dies while it is published, or before "
              "its row is marked"),
}
#: Each cell's instants (see ``inject``).
POINTS: dict[str, tuple[str, ...]] = {
    "X1.W2": ("open_committed", "service_before_effect", "service_after_effect",
              "terminal_uncommitted", "held"),
    "X1.W4": ("terminal_committed", "answered"),
    "X2.W1": ("begin", "open_uncommitted", "open_committed", "abort_uncommitted",
              "abort_committed"),
    "X2.W2": ("service_before_effect", "service_after_effect", "held"),
    "X2.W4": ("terminal_committed", "answered"),
    "X6.W1": ("answered", "claim_committed:attest", "chain_before_effect"),
    "X6.W2": ("chain_after_effect",),
    "X6.W3": ("delivered_unsettled:attest", "settle_uncommitted:attest"),
    "X7.W1": ("claim_committed:feed", "feed_before_effect"),
    "X7.W2": ("feed_after_effect", "delivered_unsettled:feed", "settle_uncommitted:feed"),
}
PER_CELL = 100
#: Injections per cell run in a child interpreter ended with os._exit.
CHILDREN_PER_CELL = 2
PROPERTIES = ("L", "U", "D", "R", "T", "A")
GATE_PROPERTIES = ("L", "U", "D", "R")
ANSWERS = {"settled": SETTLED, "broadcast": BROADCAST, "refused": REFUSED}
EXCEPTIONS = {"Boom": lambda: Boom("the service failed"),
              "NotImplementedError": lambda: NotImplementedError("not in this build")}
#: The instants at which a service that raises is drawn (a raise ends the run
#: before any earlier instant could fire).
RAISE_POINTS = frozenset({"terminal_uncommitted", "terminal_committed", "answered"})
DURABLE_TABLES = ("workflow_runs", "workflow_steps", "outbox", "idempotency_keys")
CHILD_EXIT = 137
SCOPE = f"operator|{WALLET}"
START_AT = Clock().now


@pytest.fixture(autouse=True)
def _no_mode_env(monkeypatch):
    monkeypatch.delenv("MATRIX_DURABLE_MODE", raising=False)
    monkeypatch.delenv("MATRIX_DURABLE_CANARY", raising=False)


# ── the seeded case ─────────────────────────────────────────────────────────

@dataclass(frozen=True)
class Case:
    cell: str
    index: int
    action: str
    marker: int
    key: str
    keyed: bool
    answer: str
    raise_when: str | None
    exc: str
    point: str
    early: bool
    blocked_first_replay: bool

    @property
    def seed(self) -> str:
        return f"G7|{self.cell}|{self.index}"

    @property
    def delivers(self) -> bool:
        """X6 and X7: the instant is in the outbox loop's delivery."""
        return self.cell[:2] in ("X6", "X7")

    def stand(self, *, first_world: bool) -> dict:
        """The stand-in service's behaviour, the same in every process except
        that the first one's registry refuses the service at an ABORT instant."""
        return {"answer": ANSWERS[self.answer], "raise_when": self.raise_when,
                "exc": EXCEPTIONS[self.exc],
                "unavailable": first_world and self.point in ("abort_committed",
                                                              "abort_uncommitted")}


def _client_key(rng: random.Random) -> str:
    """1-48 printable ASCII characters, no surrounding space."""
    n = rng.randint(1, 48)
    ends = [chr(rng.randint(33, 126)) for _ in range(2)]
    inner = "".join(chr(rng.randint(32, 126)) for _ in range(max(0, n - 2)))
    return ends[0] if n == 1 else ends[0] + inner + ends[1]


def case_for(cell: str, index: int, *, point: str | None = None) -> Case:
    rng = random.Random(f"G7|{cell}|{index}")
    drawn_point = rng.choice(POINTS[cell])
    point = point or drawn_point
    action = rng.choice(STATE_MODIFYING)
    marker = rng.randrange(1, 10 ** 9)
    key = _client_key(rng)
    keyed = cell.startswith("X1") or rng.random() < 0.5
    answer = rng.choice(sorted(ANSWERS))
    if cell[:2] in ("X6", "X7") or cell == "X2.W4":
        answer = "settled"              # only a settled run has outbox rows
    raise_when = rng.choice((None, None, "before", "after"))
    if cell not in ("X1.W2", "X1.W4") or point not in RAISE_POINTS:
        raise_when = None
    exc = rng.choice(sorted(EXCEPTIONS))
    early = keyed and rng.random() < 0.5
    blocked = keyed and rng.random() < 0.3
    return Case(cell=cell, index=index, action=action, marker=marker, key=key, keyed=keyed,
                answer=answer, raise_when=raise_when, exc=exc, point=point, early=early,
                blocked_first_replay=blocked)


# ── the stand-ins ───────────────────────────────────────────────────────────

class Crash(BaseException):
    """The process died here: nothing after this instant happens."""


def _committed_run(db, params: dict) -> bool:
    """A RUNNING run of these parameters is committed. By the parameters alone:
    several names share one service method, and the marker in them is the
    injection's own."""
    return bool(db.fetchall_sync(
        "SELECT 1 FROM workflow_runs WHERE params_digest = ? AND state = ?",
        (journal.digest(params), journal.RUNNING)))


def _committed_row(db, action: str, kind: str) -> bool:
    return bool(db.fetchall_sync(
        "SELECT 1 FROM outbox o JOIN workflow_runs r ON o.run_id = r.run_id WHERE r.action = ? "
        "AND o.kind = ? AND r.state = ? AND o.done_at IS NULL AND o.next_at IS NOT NULL",
        (action, kind, journal.COMPLETE)))


class Stand:
    """Every ACTION_MAP method: records the call (``calls``, the marker) the
    moment it begins — and, for L, whether a RUNNING run of that action and
    those parameters was committed by then — waits on ``gate`` when set,
    records its effect (``("service", action, marker)``) and answers
    ``answer``, or raises ``exc`` before or after the effect. The attestation
    service's ``attest`` takes the dispatcher's legacy attestation (recorded
    ``("attest", action)``) and resolves schemas as the real one does;
    ``unavailable`` makes the registry refuse every service."""

    def __init__(self, world: "World", *, answer: dict, raise_when: str | None,
                 exc: Callable[[], BaseException], unavailable: bool) -> None:
        self.world = world
        self.answer = answer
        self.raise_when = raise_when
        self.exc = exc
        self.unavailable = unavailable
        self.gate: asyncio.Event | None = None
        self.before_effect: Callable[[], None] | None = None
        self.after_effect: Callable[[], None] | None = None

    def _method(self, action: str):
        async def method(**params):
            world = self.world
            if not _committed_run(world.db, params):
                world.problems.append(f"L: {action} called with no RUNNING run committed")
            world.calls.append(params.get("marker"))
            if self.gate is not None:
                await self.gate.wait()
            if self.before_effect is not None:
                self.before_effect()
            if self.raise_when == "before":
                raise self.exc()
            world.effects.log.append(("service", action, params.get("marker")))
            if self.after_effect is not None:
                self.after_effect()
            if self.raise_when == "after":
                raise self.exc()
            return dict(self.answer)
        return method

    def registry(self):
        by_service: dict[str, dict[str, Any]] = {}
        for action, (service, method) in ACTION_MAP.items():
            by_service.setdefault(service, {})[method] = self._method(action)
        attestation = dict(by_service.get("attestation", {}))
        action_attest = attestation.get("attest")
        effects = self.world.effects

        async def attest(**kwargs):
            if "schema_uid" in kwargs and "data" in kwargs and "marker" not in kwargs:
                effects.log.append(("attest", kwargs["data"].get("action")))
                return {"status": "queued"}
            return await action_attest(**kwargs)
        attestation["attest"] = attest
        attestation["_resolve_schema"] = resolve_schema
        namespaces = {s: SimpleNamespace(**m) for s, m in by_service.items()}
        namespaces["attestation"] = SimpleNamespace(**attestation)

        def get(name):
            if self.unavailable:
                raise KeyError(name)
            return namespaces.get(name, SimpleNamespace())
        return SimpleNamespace(get=get)


class Chain:
    """The batch processor's submission path: every attestation lands. Records
    ``("attest_sent", action)`` and, for L, whether the attestation's outbox
    row was committed when the chain was handed it."""

    def __init__(self, world: "World") -> None:
        self.world = world
        self.before_effect: Callable[[], None] | None = None
        self.after_effect: Callable[[], None] | None = None

    async def _submit_batch(self, batch):
        out = []
        for att in batch:
            action = att.get("data", {}).get("action")
            if not _committed_row(self.world.db, action, "attest"):
                self.world.problems.append(f"L: {action}'s attestation sent with no row committed")
            if self.before_effect is not None:
                self.before_effect()
            self.world.effects.log.append(("attest_sent", action))
            if self.after_effect is not None:
                self.after_effect()
            out.append({"status": "success", "attestation_uid": "0x" + "44" * 32,
                        "tx_hash": "0x" + "55" * 32, "id": att["id"]})
        return out


class Feed:
    """The feed engine's ``ingest``: records ``("feed", action)`` and, for L,
    whether the entry's outbox row was committed when it was published."""

    def __init__(self, world: "World") -> None:
        self.world = world
        self.before_effect: Callable[[], None] | None = None
        self.after_effect: Callable[[], None] | None = None

    async def ingest(self, **kwargs):
        action = kwargs.get("action")
        if not _committed_row(self.world.db, action, "feed"):
            self.world.problems.append(f"L: {action}'s feed entry published with no row committed")
        if self.before_effect is not None:
            self.before_effect()
        self.world.effects.log.append(("feed", action))
        if self.after_effect is not None:
            self.after_effect()
        return SimpleNamespace(summary=f"performed {action}")


class World:
    """One process: its database, its effects, calls and live L findings, the
    dispatcher, and the mode-on engine with the stand-in chain."""

    def __init__(self, db_path: Path, clock: Clock, stand: dict, *,
                 effects: Effects | None = None, calls: list | None = None,
                 problems: list | None = None) -> None:
        self.clock = clock
        self.effects = effects if effects is not None else Effects()
        self.calls = calls if calls is not None else []
        self.problems = problems if problems is not None else []
        self.db = open_db(db_path)
        self.stand = Stand(self, **stand)
        self.d = ServiceDispatcher({})
        registry = self.stand.registry()
        self.d._get_registry = lambda: registry
        self.feed = Feed(self)
        self.d._feed_engine = self.feed
        self.chain = Chain(self)
        self.eng = engine(self.db, "on", clock, self.effects)
        self.eng.attestations = self.chain

    async def request(self, case: Case, *, blocked: bool = False) -> str | None:
        """The bridge's sequence at the dispatcher (the gate's answer, then the
        dispatch under the request's key); None stands for the gate's 403."""
        if blocked:
            return None
        request = SimpleNamespace(headers={"Idempotency-Key": case.key} if case.keyed else {})
        with wiring.keyed(request, scope=SCOPE, decision={}):
            return await self.d.execute(case.action, params=params_for(case.action, case.marker),
                                        caller_identity=WALLET)


_ENGINE_WORK = {"DurableEngine.open.<locals>.work": "open",
                "DurableEngine.abort.<locals>.work": "abort",
                "DurableEngine.finish.<locals>.work": "terminal",
                "DurableEngine._fail.<locals>.work": "terminal",
                "OutboxLoop._settle.<locals>.work": "settle"}


@contextlib.contextmanager
def inject(point: str, world: World, on_crash: Callable[[], None]):
    """Arm the crash at *point* in *world*, once. ``on_crash`` must not return
    normally (it raises Crash, or ends the process).

    ``<work>_uncommitted``: the transaction's statements ran and its COMMIT
    never does; ``<work>_committed``: just after its COMMIT (open: the run
    RUNNING and its key bound; abort: START and ABORT; terminal: the end, its
    outbox rows and its key's answer digest, before the answer is cached;
    settle: the outbox row marked). ``begin``: before the key is looked up.
    ``service_*_effect``, ``chain_*_effect``, ``feed_*_effect``: inside the
    stand-in, around its effect. ``claim_committed:<kind>``: the outbox row
    claimed, before its delivery. ``delivered_unsettled:<kind>``: the delivery
    answered, before its row is marked. ``held`` and ``answered`` are driven by
    the caller."""
    fired = [False]

    def fire() -> None:
        if not fired[0]:
            fired[0] = True
            on_crash()

    point_name, _, kind = point.partition(":")
    settling = [""]
    original_tx = journal.transaction

    def transaction(db, work, *, wait):
        what = _ENGINE_WORK.get(getattr(work, "__qualname__", ""))
        if what == "settle" and settling[0] != kind:
            what = None
        if fired[0] or what is None or point_name not in (f"{what}_uncommitted",
                                                          f"{what}_committed"):
            return original_tx(db, work, wait=wait)
        if point_name.endswith("_uncommitted"):
            def cut(tx):
                out = work(tx)
                fire()          # the statements ran; COMMIT never does
                return out
            return original_tx(db, cut, wait=wait)
        out = original_tx(db, work, wait=wait)
        fire()
        return out

    journal.transaction = transaction
    loop = world.eng.loop
    original_settle, original_claim = loop._settle, loop._claim

    def settle(row, delivery):
        settling[0] = row[2]
        if point_name == "delivered_unsettled" and row[2] == kind:
            fire()
        try:
            return original_settle(row, delivery)
        finally:
            settling[0] = ""

    def claim(row, now):
        out = original_claim(row, now)
        if point_name == "claim_committed" and out is not None and row[2] == kind:
            fire()
        return out
    loop._settle, loop._claim = settle, claim
    if point_name == "begin":
        original_begin = world.eng.begin

        def begin(*args, **kwargs):
            fire()
            return original_begin(*args, **kwargs)
        world.eng.begin = begin
    hooks = {"service_before_effect": (world.stand, "before_effect"),
             "service_after_effect": (world.stand, "after_effect"),
             "chain_before_effect": (world.chain, "before_effect"),
             "chain_after_effect": (world.chain, "after_effect"),
             "feed_before_effect": (world.feed, "before_effect"),
             "feed_after_effect": (world.feed, "after_effect")}
    if point_name in hooks:
        target, attr = hooks[point_name]
        setattr(target, attr, fire)
    try:
        yield fired
    finally:
        journal.transaction = original_tx


# ── one injection ───────────────────────────────────────────────────────────

def _category(answer: str | None) -> str:
    if answer is None:
        return "gate_403"
    body = json.loads(answer)
    return "ok" if body.get("status") == "ok" else str(body.get("error_category"))


def _binding(db) -> dict[str, str]:
    return {r[0]: r[1] for r in db.fetchall_sync("SELECT key, run_id FROM idempotency_keys")}


def _error_category(case: Case) -> str:
    return "not_implemented" if case.exc == "NotImplementedError" else "service_error"


def _expected_first(case: Case) -> str:
    if case.raise_when:
        return _error_category(case)
    return "ok"


def dump(db) -> dict[str, list]:
    """Every row of the four tables, in a fixed order: the state R compares."""
    return {t: sorted((tuple(r) for r in db.fetchall_sync(f"SELECT * FROM {t}")), key=repr)
            for t in DURABLE_TABLES}


class _Raw:
    """A file read with sqlite3 alone, changing nothing in it."""

    def __init__(self, path: Path) -> None:
        self._conn = sqlite3.connect(f"file:{path}?mode=ro", uri=True)

    def fetchall_sync(self, sql: str, params: tuple = ()) -> list:
        return self._conn.execute(sql, params).fetchall()

    def close(self) -> None:
        self._conn.close()


def copy_db(src: Path, dest: Path) -> Path:
    """The committed state of the file at *src* (its write-ahead log read too),
    as a new file: what a fresh process opening *src* would find."""
    a, b = sqlite3.connect(str(src)), sqlite3.connect(str(dest))
    try:
        a.backup(b)
    finally:
        a.close()
        b.close()
    return dest


class Play:
    """The record of one injection: every answer, the dead process's prefix of
    effects, calls and live L findings, what its file held, and what recovery
    and the replays did."""

    def __init__(self, case: Case, tmp: Path) -> None:
        self.case = case
        self.tmp = tmp
        self.key = keys.scoped(wiring.BRIDGE_ACTION, SCOPE, case.key)
        self.answers: list[tuple[str, str]] = []
        self.problems: list[str] = []
        self.prefix_effects: list = []
        self.prefix_calls: list = []
        self.prefix_problems: list = []
        self.crashed_at: float | None = None
        self.snap = tmp / f"{case.cell}-{case.index}-crash.db"
        self.recovery: dict = {}

    def take_snapshot(self, world: World) -> None:
        snapshot(world.db, self.snap)
        self.prefix_effects = list(world.effects.log)
        self.prefix_calls = list(world.calls)
        self.prefix_problems = list(world.problems)
        self.crashed_at = world.clock.now

    def crash(self, world: World) -> None:
        self.take_snapshot(world)
        raise Crash()

    def expect(self, label: str, answer: str | None, expected: str | None = None,
               same_as: str | None = None) -> None:
        got = _category(answer)
        self.answers.append((label, got))
        if same_as is not None:
            if answer != same_as:
                self.problems.append(f"A: {label} was not the first answer byte for byte "
                                     f"({got}: {answer!r:.160} vs {same_as!r:.160})")
        elif got != expected:
            self.problems.append(f"A: {label} answered {got}, expected {expected}: {answer!r:.200}")


async def _until_called(world: World) -> None:
    for _ in range(1000):
        if world.calls:
            return
        await asyncio.sleep(0)
    raise AssertionError("the first request never reached its service call")


async def first_process(p: Play, w1: World, on_crash: Callable[[], None]) -> None:
    """The process that dies: the first request and, for X6 and X7, the outbox
    loop's tick, with the crash armed at the case's instant."""
    case = p.case
    with installed(w1.eng), inject(case.point, w1, on_crash) as fired:
        try:
            if case.point == "held":
                w1.stand.gate = asyncio.Event()
                task = asyncio.ensure_future(w1.request(case))
                await _until_called(w1)
                fired[0] = True
                p.take_snapshot(w1)          # the process dies with the call held open
                task.cancel()
                with contextlib.suppress(Crash, asyncio.CancelledError):
                    await task
                return
            first = await w1.request(case)
            p.expect("first", first, _expected_first(case))
            if case.point == "answered":
                fired[0] = True
                on_crash()
            await drain(w1.eng)
        except Crash:
            pass
    assert fired[0], f"{case.seed}: the instant {case.point} never fired"


async def recover(p: Play, path: Path, *, keep: bool) -> tuple[World, dict]:
    """One recovery of the dead process's file: a fresh process, an early
    replay when drawn (and the key is bound: the dead run is not closed or run
    inside the window), the clock past the window, one loop tick. Returns the
    world and its tables; with *keep*, the early replay's answer is recorded."""
    case = p.case
    world = World(path, Clock(p.crashed_at + 1.0), case.stand(first_world=False))
    with installed(world.eng):
        bound = _binding(world.db).get(p.key) if case.keyed else None
        if case.early and bound is not None:
            state = journal.get_run(world.db, bound)["state"]
            answer = await world.request(case)
            if keep:
                p.expect("replay_early", answer,
                         "idempotency_in_progress" if state in journal.OPEN
                         else "idempotency_answer_not_held")
        world.clock.advance(journal.ABANDONED_AFTER_S)
        await world.eng.loop.tick()
    return world, dump(world.db)


async def replays(p: Play, world: World, *, unbound: bool) -> None:
    """The client's replay under the same key, twice, in the recovered process
    (a request without a key is not replayed: a retry without one is a new
    request)."""
    case = p.case
    if not case.keyed:
        return
    with installed(world.eng):
        if unbound:
            expected = _expected_first(case)
            first = await world.request(case, blocked=case.blocked_first_replay)
            p.expect("replay_1", first, "gate_403" if case.blocked_first_replay else expected)
            if case.blocked_first_replay:
                p.recovery["after_blocked"] = (len(world.effects.log), len(world.calls))
            await drain(world.eng)
            second = await world.request(case)
            if case.blocked_first_replay:
                p.expect("replay_2", second, expected)
            else:
                p.expect("replay_2", second, same_as=first)
        else:
            for label in ("replay_1", "replay_2"):
                blocked = label == "replay_1" and case.blocked_first_replay
                answer = await world.request(case, blocked=blocked)
                p.expect(label, answer, "gate_403" if blocked else "idempotency_answer_not_held")
                if blocked:
                    p.recovery["after_blocked"] = (len(world.effects.log), len(world.calls))
                await drain(world.eng)
        await drain(world.eng)


async def after_the_crash(p: Play) -> dict:
    """Recovery twice from copies of the dead process's file, a second pass
    over one of them, the replays on it, then the proofs."""
    before = _Raw(p.snap)
    try:
        committed = dump(before)
        bound_at_crash = _binding(before).get(p.key) if p.case.keyed else None
    finally:
        before.close()
    a_path = copy_db(p.snap, p.tmp / f"{p.case.cell}-{p.case.index}-a.db")
    b_path = copy_db(p.snap, p.tmp / f"{p.case.cell}-{p.case.index}-b.db")
    world_b, dump_b = await recover(p, b_path, keep=False)
    await world_b.db.close()
    world, dump_a = await recover(p, a_path, keep=True)
    try:
        recovery_effects = (list(world.effects.log), list(world.calls))
        with installed(world.eng):
            await world.eng.loop.tick()
        dump_a2 = dump(world.db)
        p.recovery.update(effects=recovery_effects, committed=committed, dump_a=dump_a,
                          dump_b=dump_b, dump_a2=dump_a2)
        await replays(p, world, unbound=bound_at_crash is None)
        return judge(p, world, bound_at_crash)
    finally:
        await world.db.close()


# ── the proofs ──────────────────────────────────────────────────────────────

def judge(p: Play, world: World, bound_at_crash: str | None) -> dict:
    case = p.case
    rec = p.recovery
    effects = p.prefix_effects + list(world.effects.log)
    calls = len(p.prefix_calls) + len(world.calls)
    runs = {r["run_id"]: dict(r) for r in world.db.fetchall_sync("SELECT * FROM workflow_runs")}
    committed_runs = {r[0]: r[6] for r in rec["committed"]["workflow_runs"]}
    problems = list(p.problems)
    out: dict[str, bool] = {}

    # L
    lost = sorted(set(committed_runs) - set(runs))
    live = [pr for pr in p.prefix_problems + list(world.problems) if pr.startswith("L:")]
    out["L"] = not lost and not live
    if lost:
        problems.append(f"L: runs the dead process committed are gone: {lost}")
    problems += live

    # U
    made, called = rec["effects"]
    moved = {rid: (state, runs.get(rid, {}).get("state")) for rid, state in committed_runs.items()
             if (state in journal.TERMINAL and runs.get(rid, {}).get("state") != state)
             or (state in journal.OPEN and runs.get(rid, {}).get("state") not in (
                 journal.ABORT, journal.FAIL))}
    blocked_made = rec.get("after_blocked", (0, 0)) != (0, 0)
    out["U"] = not made and not called and not moved and not blocked_made
    if made or called:
        problems.append(f"U: recovery made effects {made} or calls {called}")
    if moved:
        problems.append(f"U: recovery moved runs forward: {moved}")
    if blocked_made:
        problems.append(f"U: a replay the gate refused made effects: {blocked_made}")

    # D
    service_effects = sum(1 for e in effects if e[0] == "service" and e[2] == case.marker)
    attests = sum(1 for e in effects if e[0] in ("attest", "attest_sent"))
    feeds = sum(1 for e in effects if e[0] == "feed")
    d_ok = calls <= 1 and service_effects <= calls and attests <= 1 and feeds <= 1
    # A keyed request the dead process never called and left unbound is run by
    # a replay that passes the gate (the second always does).
    exact = case.keyed and not p.prefix_calls and bound_at_crash is None
    if exact:
        d_ok = d_ok and calls == 1 and service_effects == (0 if case.raise_when == "before" else 1)
    out["D"] = d_ok
    if not d_ok:
        problems.append(f"D: {calls} call(s), {service_effects} effect(s), {attests} "
                        f"attestation(s), {feeds} feed entr(y/ies) (exactly one call "
                        f"expected: {exact})")

    # R
    same = rec["dump_a"] == rec["dump_b"]
    settled = rec["dump_a2"] == rec["dump_a"]
    out["R"] = same and settled
    if not same:
        problems.append("R: two recoveries of the same file reached different states")
    if not settled:
        problems.append("R: a second recovery pass changed the recovered state")

    # T
    still_open = [r for r in runs.values() if r["state"] not in journal.TERMINAL]
    out["T"] = not still_open
    if still_open:
        problems.append(f"T: runs left open: {[(r['run_id'], r['state']) for r in still_open]}")

    out["A"] = not any(pr.startswith("A:") for pr in p.problems)
    return {"case": case, "point": case.point, "held": out, "problems": problems,
            "answers": [a for _l, a in p.answers],
            "deliveries": {"attest": attests, "feed": feeds}}


async def play(case: Case, template, tmp: Path) -> dict:
    p = Play(case, tmp)
    path = tmp / f"{case.cell}-{case.index}.db"
    snapshot(template, path)
    w1 = World(path, Clock(), case.stand(first_world=True))
    try:
        await first_process(p, w1, lambda: p.crash(w1))
    finally:
        await w1.db.close()
    return await after_the_crash(p)


# ── the matrix ──────────────────────────────────────────────────────────────

def _tally(results: list[dict]) -> dict:
    held = {prop: {"checked": 0, "held": 0} for prop in PROPERTIES}
    for r in results:
        for prop in PROPERTIES:
            held[prop]["checked"] += 1
            held[prop]["held"] += int(bool(r["held"][prop]))
    return {
        "injections": len(results),
        "keyed": sum(1 for r in results if r["case"].keyed),
        "crash_points": dict(sorted(Counter(r["point"] for r in results).items())),
        "held": held,
        "answers": dict(sorted(Counter(a for r in results for a in r["answers"]).items())),
        "deliveries": {k: sum(r["deliveries"][k] for r in results) for k in ("attest", "feed")},
    }


_MATRIX: dict[str, list[dict]] = {}


async def _run_cell(cell: str) -> list[dict]:
    out: list[dict] = []
    with tempfile.TemporaryDirectory() as scratch:
        tmp = Path(scratch)
        template = open_db(tmp / "template.db")
        try:
            for i in range(PER_CELL):
                out.append(await play(case_for(cell, i), template, tmp))
                for f in tmp.glob(f"{cell}-{i}*"):
                    f.unlink()
        finally:
            await template.close()
    return out


def cell_results(cell: str) -> list[dict]:
    if cell not in _MATRIX:
        previous = wiring.current()
        _MATRIX[cell] = asyncio.run(_run_cell(cell))
        assert wiring.current() is previous, "the matrix left a durable engine installed"
    return _MATRIX[cell]


def _failures(results: list[dict], *, answers: bool) -> list[str]:
    return [f"{r['case'].seed} {r['case'].action} at {r['point']}: {pr}"
            for r in results for pr in r["problems"] if pr.startswith("A:") is answers]


def test_the_cells_are_the_plans_phase_2_cells():
    assert sorted(CELLS) == ["X1.W2", "X1.W4", "X2.W1", "X2.W2", "X2.W4", "X6.W1", "X6.W2",
                             "X6.W3", "X7.W1", "X7.W2"]
    assert set(POINTS) == set(CELLS) and all(POINTS.values())


@pytest.mark.parametrize("cell", sorted(CELLS))
def test_a_cell_has_100_seeded_injections_over_every_instant(cell):
    results = cell_results(cell)
    assert len(results) >= 100, f"{cell}: only {len(results)} injections"
    drawn = {r["point"] for r in results}
    assert drawn == set(POINTS[cell]), f"{cell}: instants never drawn: {set(POINTS[cell]) - drawn}"


@pytest.mark.parametrize("cell", sorted(CELLS))
def test_every_injection_keeps_l_u_d_r(cell):
    failures = _failures(cell_results(cell), answers=False)
    assert not failures, (f"{cell}: {len(failures)} property violation(s), first ones:\n"
                          + "\n".join(failures[:12]))


@pytest.mark.parametrize("cell", sorted(CELLS))
def test_every_request_is_answered_what_the_spec_says(cell):
    failures = _failures(cell_results(cell), answers=True)
    assert not failures, (f"{cell}: {len(failures)} answer(s) not the spec's, first ones:\n"
                          + "\n".join(failures[:12]))


def test_the_matrix_is_deterministic_per_seed():
    assert [asdict(case_for("X1.W2", i)) for i in range(5)] == \
        [asdict(case_for("X1.W2", i)) for i in range(5)]
    assert len({case_for("X2.W1", i).key for i in range(PER_CELL)}) == PER_CELL


# ── the real-process subset ─────────────────────────────────────────────────

def child_main(spec_json: str) -> None:
    """Run in a child process: the first process of *spec*'s case over the real
    database file, ended with os._exit at the instant."""
    spec = json.loads(spec_json)
    case = Case(**spec["case"])
    sink = open(spec["effects"], "a", encoding="utf-8")

    def persist(entry) -> None:
        sink.write(json.dumps(entry) + "\n")
        sink.flush()
        os.fsync(sink.fileno())

    class Log(list):
        def append(self, item):
            super().append(item)
            persist(["effect", *item])

    class Calls(list):
        def append(self, item):
            super().append(item)
            persist(["call", item])

    class Problems(list):
        def append(self, item):
            super().append(item)
            persist(["problem", item])

    async def main() -> None:
        world = World(Path(spec["db"]), Clock(), case.stand(first_world=True),
                      effects=Effects(log=Log()), calls=Calls(), problems=Problems())
        p = Play(case, Path(spec["db"]).parent)
        await first_process(p, world, lambda: os._exit(CHILD_EXIT))
        os._exit(3)     # the instant was never reached
    asyncio.run(main())


def _child_case(cell: str, index: int) -> Case:
    instants = [pt for pt in POINTS[cell] if pt != "held"]
    return case_for(cell, 1000 + index, point=instants[index % len(instants)])


async def _recover_child(case: Case, db_path: Path, effects_path: Path) -> dict:
    p = Play(case, db_path.parent)
    for line in effects_path.read_text(encoding="utf-8").splitlines():
        entry = json.loads(line)
        if entry[0] == "call":
            p.prefix_calls.append(entry[1])
        elif entry[0] == "problem":
            p.prefix_problems.append(entry[1])
        else:
            p.prefix_effects.append(tuple(entry[1:]))
    p.crashed_at = START_AT
    copy_db(db_path, p.snap)
    return await after_the_crash(p)


def children_results(tmp: Path) -> tuple[dict[str, list[dict]], dict[str, list[int]]]:
    env = {k: v for k, v in os.environ.items()
           if k not in ("MATRIX_DURABLE_MODE", "MATRIX_DURABLE_CANARY")}
    env.update(PYTHONPATH=str(ROOT), PYTHONDONTWRITEBYTECODE="1")
    code = ("import sys; sys.path.insert(0, 'tests'); "
            "import test_durable_crash_matrix as m; m.child_main(sys.argv[1])")
    specs = []
    for cell in sorted(CELLS):
        for i in range(CHILDREN_PER_CELL):
            case = _child_case(cell, i)
            db_path, effects_path = tmp / f"child-{cell}-{i}.db", tmp / f"child-{cell}-{i}.effects"
            effects_path.write_text("", encoding="utf-8")
            specs.append((case, db_path, effects_path, json.dumps(
                {"case": asdict(case), "db": str(db_path), "effects": str(effects_path)})))
    results: dict[str, list[dict]] = {c: [] for c in CELLS}
    statuses: dict[str, list[int]] = {c: [] for c in CELLS}
    for start in range(0, len(specs), 10):
        batch = specs[start:start + 10]
        procs = [(case, db_path, effects_path, subprocess.Popen(
            [sys.executable, "-c", code, spec], cwd=ROOT, env=env, stdout=subprocess.DEVNULL,
            stderr=subprocess.PIPE)) for case, db_path, effects_path, spec in batch]
        for case, db_path, effects_path, proc in procs:
            _out, err = proc.communicate(timeout=120)
            statuses[case.cell].append(proc.returncode)
            assert proc.returncode == CHILD_EXIT, (
                f"{case.seed} child at {case.point} exited {proc.returncode}, not {CHILD_EXIT}: "
                f"{err.decode(errors='replace')[-1500:]}")
            previous = wiring.current()
            results[case.cell].append(asyncio.run(_recover_child(case, db_path, effects_path)))
            assert wiring.current() is previous
    return results, statuses


_CHILDREN: dict[str, tuple] = {}


def children() -> tuple[dict[str, list[dict]], dict[str, list[int]]]:
    if "all" not in _CHILDREN:
        with tempfile.TemporaryDirectory() as scratch:
            _CHILDREN["all"] = children_results(Path(scratch))
    return _CHILDREN["all"]


@pytest.mark.parametrize("cell", sorted(CELLS))
def test_a_process_killed_at_the_instant_recovers_with_l_u_d_r(cell):
    results, statuses = children()
    assert statuses[cell] == [CHILD_EXIT] * CHILDREN_PER_CELL, statuses[cell]
    failures = [f"{r['case'].seed} {r['case'].action} at {r['point']}: {pr}"
                for r in results[cell] for pr in r["problems"]]
    assert not failures, f"{cell} (real process): " + "\n".join(failures)


# ── the artefact ────────────────────────────────────────────────────────────

RULE = ("G7: 100 seeded injections in each of the plan's ten Phase 2 cells (X1 at W2 and W4, X2 "
        "at W1, W2 and W4, X6 at W1, W2 and W3, X7 at W1 and W2), each a kill and a fresh process "
        "on the same SQLite file, and in every one L (no lost run, and no effect without its "
        "record), U (recovery continues nothing and a replay the gate refuses makes no effect), "
        "D (no effect twice) and R (two independent recoveries from the same file reach the same "
        "state, and a second pass changes nothing) hold.")
INSTRUMENT = (
    "tests/test_durable_crash_matrix.py: engines.durable.mode on, both canary stages, the real "
    "ServiceDispatcher and DurableEngine over the platform Database (SQLite, a scratch file per "
    "injection), driven through the bridge's sequence at the dispatcher (the gate's answer, then "
    "wiring.keyed, then execute), with an Idempotency-Key always at X1 and on a seeded half of "
    "the others, over stand-in services, chain and feed that record every call and effect and "
    "check, when called, that the record the call needs was committed first. A kill in process "
    "is the SQLite backup of the committed state at the instant with the effects and calls made "
    "so far; in a child, os._exit(137) at the instant over a real file. Recovery: the file "
    "copied twice, each copy opened by a fresh Database and engine, an early replay when drawn, "
    "the clock past abandoned_after_s, one loop tick; the copies' four tables compared, a second "
    "tick on one of them, then two replays under the key there. Seeded with "
    "random.Random('G7|cell|index').")
SCOPE_TEXT = (
    f"{PER_CELL} injections in each of {len(CELLS)} cells ({PER_CELL * len(CELLS)} in all), over "
    f"the {len(STATE_MODIFYING)} state-modifying names ACTION_MAP serves; {CHILDREN_PER_CELL} "
    f"more per cell in a real process ({CHILDREN_PER_CELL * len(CELLS)} in all). In process: no "
    "network, no chain, no gateway HTTP layer (the gate is the request's blocked flag).")
PROPERTY_TEXT = {
    "L": ("no lost workflow: every run the dead process committed is in the recovered file under "
          "its id, and at every service call a RUNNING run of that action and those parameters "
          "was committed, and at every attestation or feed entry the outbox delivered its row "
          "was committed for a COMPLETE run"),
    "U": ("no unauthorized continuation: recovery (restart, maintenance, loop ticks, before any "
          "request) makes no service call, attestation or feed entry and moves no run forward "
          "(open runs become ABORT or FAIL, closed ones stay), and a replay the gate refuses "
          "makes no effect; no decision expires in Phase 2, so expiry is not measured"),
    "D": ("no duplicate effect: across the dead process, recovery and the replays, the service's "
          "effect for the marker, the attestation (outbox or legacy) and the feed entry each "
          "happen at most once; exactly once for the service when the dead process made no call, "
          "left the key unbound and a replay passed the gate"),
    "R": ("deterministic recovery: two independent recoveries of copies of the same file leave "
          "identical rows in the four tables, and a second pass changes none"),
    "T": "every run in the recovered file is COMPLETE, ABORT or FAIL (recorded beside G7)",
    "A": ("every request answered what the spec says: the first answer byte for byte, "
          "idempotency_in_progress, idempotency_answer_not_held after a restart, the gate's 403, "
          "or a normal dispatch when the key was never bound (recorded beside G7)"),
}
NOT_MEASURED = (
    "The plan's other Phase 2-adjacent cells are not here: X1.W1 (a request the gateway never "
    "received, which the client's own outbox keeps, a later phase); W3 and W5 outside X6; and "
    "U's expiry of a decision, since no decision record exists yet. X6.W3 has no reconciler "
    "reading the attestation's UID: an attestation the chain took whose row was not marked is "
    "never sent again, and after the window its row is given up, so its outbox row says "
    "given_up while the chain holds it.")


def measure() -> dict:
    cells = {c: {"describes": CELLS[c], **_tally(cell_results(c))} for c in sorted(CELLS)}
    results, statuses = children()
    real = {}
    for c in sorted(CELLS):
        tally = _tally(results[c])
        tally["exit_status"] = dict(Counter(str(s) for s in statuses[c]))
        real[c] = tally
    return {"gate": "G7", "rule": RULE, "instrument": INSTRUMENT, "scope": SCOPE_TEXT,
            "properties": PROPERTY_TEXT, "not_measured": NOT_MEASURED,
            "measured": durable_measured_at.measured_at(), "cells": cells,
            "real_process": real}


def test_the_g7_artefact():
    measured = measure()
    path = BASELINE / ARTEFACT
    if WRITE:
        BASELINE.mkdir(parents=True, exist_ok=True)
        path.write_text(json.dumps(measured, indent=1, sort_keys=True) + "\n", encoding="utf-8")
    assert path.is_file(), f"{path} missing — run with ENGINES_BASELINE=write"
    committed = json.loads(path.read_text(encoding="utf-8"))
    for field_name in ("gate", "rule", "instrument", "scope", "properties", "not_measured",
                       "measured"):
        assert field_name in committed, f"{ARTEFACT} has no {field_name!r}"
    durable_measured_at.check(committed["measured"], ARTEFACT)
    recomputed = json.loads(json.dumps(measured))
    for part in ("cells", "real_process"):
        assert committed[part] == recomputed[part], (
            f"{ARTEFACT} {part} no longer match what the matrix measures. If the change is "
            "intended, rewrite it with ENGINES_BASELINE=write and say why in the commit.")
    assert sorted(committed["cells"]) == sorted(CELLS)
    for part in ("cells", "real_process"):
        for name, tally in committed[part].items():
            if part == "cells":
                assert tally["injections"] >= PER_CELL, (name, tally["injections"])
            for prop in GATE_PROPERTIES + ("T",):
                h = tally["held"][prop]
                assert h["held"] == h["checked"] == tally["injections"], (
                    f"G7 fails: {part} {name}: {prop} held in {h['held']} of {h['checked']} "
                    "injections")
