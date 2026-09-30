"""Gate G7: every run reaches a terminal state on every path, through a crash.

Engines Phase 2 (runtime/durable), mode on. This file drives the bridge's
sequence at the dispatcher (``bridge_like``: the gate's answer, then
``wiring.keyed``, then ``ServiceDispatcher.execute``) under an Idempotency-Key,
kills the process at a chosen instant, starts it again, and replays the
client's request under the same key. It measures four cells:

* X1 dispatch-then-crash — the dispatch began (or answered) and then the
  process died;
* X2 crash-before-record — the process died before anything about the
  dispatch was committed;
* X6 replay-after-complete — the first request ended, then it is replayed;
* X7 replay-during-run — a replay arrives while the first request is still in
  its service call; on its crash path the new process is also replayed to once
  before the dead process's run passes ``abandoned_after_s``;

each over four paths: ``normal`` (the service answers settled, broadcast or
refused), ``refused`` (the gate answers 403 to one of the requests),
``raises`` (the service raises, before or after its effect) and ``crash``
(the process dies between two steps, then restarts).

A CRASH is ``snapshot()`` of the committed database at the injection instant
together with the effects and service calls made up to that instant; nothing
the process did afterwards survives. A RESTART is a fresh ``Database`` and
``DurableEngine`` over the snapshot, with nothing held in memory, the clock
moved past ``abandoned_after_s``, ``engine.maintain()`` and one loop tick; then
the client replays the same request under the same key, twice.

The injection instants: at the start of ``engine.begin`` (before the key is
looked up); inside the transaction that opens the run, its statements run and
not yet committed (``open_uncommitted``) — likewise for the ABORT of a pre-call
refusal (``abort_uncommitted``) and for the run's end (``terminal_uncommitted``:
``finish`` or ``_fail``); just after each of those commits (``*_committed``;
``terminal_committed`` is before the first answer is cached); inside the
service before and after its effect; while the service call is held open
(``held``); after the dispatcher answered (``answered``); inside the outbox's
attestation delivery after the chain took it and before the row is marked
(``delivery_sent``); after the outbox delivered (``delivered``); after
everything (``after_all``, a clean stop). The instants inside the engine are
reached by wrapping ``journal.transaction`` (matched by the work function the
engine hands it), ``engine.begin``, the stand-in service's effect hooks and the
chain's ``_submit_batch``.

For every injection four properties are checked and counted:

* T — every run in the recovered database is terminal (COMPLETE, ABORT, FAIL);
* D — service calls under the key, across the first request, the crash and
  the replays, are at most 1, and effects at most the calls; and exactly 1 call
  when the first request left no sign it might have acted (no call made, key
  unbound in the committed state) and a later request passed the gate;
* R — once a run under the key may have acted (its call began, or the key is
  bound to it in the committed state), no later request calls the service,
  the key stays bound to that run, and the run ends COMPLETE or FAIL;
* L — at most one attestation (outbox or legacy) and at most one feed entry
  are delivered, only when a COMPLETE run of the action returned ``settled``,
  and no outbox row is marked delivered for a run that is not COMPLETE;

and a fifth, A: every request is answered what the spec says (the first
answer byte for byte, ``idempotency_in_progress``,
``idempotency_answer_not_held`` after a restart, or a normal dispatch when the
key was never bound).

Every draw — the state-modifying name, the marker, the key, the service's
answer, the raise, the instant — comes from ``random.Random`` seeded with the
cell, the path and the injection's index, so the matrix is the same on every
run. A small subset runs in a real child process (the interpreter running this
suite) over a real database file and ends it with ``os._exit(137)`` at the
injection instant; the parent recovers the file and checks the same
properties.

The artefact is ``tests/baseline/durable_g7_crash_matrix.json``:
``ENGINES_BASELINE=write`` measures and rewrites it; otherwise the matrix is
re-run and its counts must equal the committed ones.

Why: a crash mid-run, a replayed key or a refusal must never leave a run
open, run an action twice, re-run an action that may have acted, or deliver a
record of an action that did not complete.
"""
from __future__ import annotations

import asyncio
import contextlib
import json
import os
import random
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
    Feed, bridge_like, drain, engine, installed, open_db, params_for, snapshot,
)
from runtime.blockchain.services.service_dispatcher import ServiceDispatcher  # noqa: E402
from runtime.durable import journal, keys, wiring  # noqa: E402
from tests import durable_measured_at  # noqa: E402

ROOT = Path(__file__).resolve().parent.parent
BASELINE = ROOT / "tests" / "baseline"
ARTEFACT = "durable_g7_crash_matrix.json"
WRITE = os.environ.get("ENGINES_BASELINE", "").strip().lower() == "write"

CELLS = {"X1": "X1_dispatch_then_crash", "X2": "X2_crash_before_record",
         "X6": "X6_replay_after_complete", "X7": "X7_replay_during_run"}
PATHS = ("normal", "refused", "raises", "crash")
PER_PATH = 28          # 112 injections per cell
PROPERTIES = ("T", "D", "R", "L", "A")
ANSWERS = {"settled": SETTLED, "broadcast": BROADCAST, "refused": REFUSED}
EXCEPTIONS = {"Boom": lambda: Boom("the service failed"),
              "NotImplementedError": lambda: NotImplementedError("not in this build")}

#: The instants each (cell, path) draws from; None = no crash, the flow ends in
#: the process that began it.
POINTS: dict[tuple[str, str], tuple[str | None, ...]] = {
    ("X1", "normal"): ("answered", "delivered"),
    ("X1", "refused"): ("open_committed", "service_before_effect", "service_after_effect",
                        "terminal_uncommitted", "terminal_committed", "answered"),
    ("X1", "raises"): ("terminal_uncommitted", "terminal_committed", "answered"),
    ("X1", "crash"): ("open_committed", "service_before_effect", "service_after_effect",
                      "terminal_uncommitted", "terminal_committed", "abort_committed"),
    ("X2", "normal"): ("open_uncommitted",),
    ("X2", "refused"): ("refused",),
    ("X2", "raises"): ("open_uncommitted",),
    ("X2", "crash"): ("begin", "open_uncommitted", "abort_uncommitted"),
    ("X6", "normal"): (None, "after_all"),
    ("X6", "refused"): (None, "after_all"),
    ("X6", "raises"): (None, "after_all"),
    ("X6", "crash"): ("terminal_committed", "answered", "delivery_sent", "delivered"),
    ("X7", "normal"): (None, "after_all"),
    ("X7", "refused"): (None, "after_all"),
    ("X7", "raises"): (None, "after_all"),
    ("X7", "crash"): ("held", "service_after_effect", "terminal_uncommitted",
                      "terminal_committed"),
}

#: The instants the brief requires, and the name each has here.
REQUIRED_POINTS = {
    "before anything is written": "open_uncommitted",
    "after the RUNNING commit, before the service is called": "open_committed",
    "inside the service, before its effect": "service_before_effect",
    "inside the service, after its effect": "service_after_effect",
    "after the service answered, before the terminal commit": "terminal_uncommitted",
    "after the terminal commit, before the answer is cached": "terminal_committed",
}

#: The real-process subset: three runs per cell, one instant each.
CHILD_POINTS = {"X1": ("service_after_effect", "open_committed", "terminal_uncommitted"),
                "X2": ("open_uncommitted", "begin", "abort_uncommitted")}
CHILD_EXIT = 137
SCOPE = f"operator|{WALLET}"
START_AT = Clock().now


@pytest.fixture(autouse=True)
def _no_mode_env(monkeypatch):
    monkeypatch.delenv("MATRIX_DURABLE_MODE", raising=False)


# ── the seeded case ─────────────────────────────────────────────────────────

@dataclass(frozen=True)
class Case:
    cell: str
    path: str
    index: int
    action: str
    marker: int
    key: str
    answer: str
    raise_when: str | None
    exc: str
    point: str | None
    replays: int
    allow_first_replay: bool
    allow_second_replay: bool

    @property
    def seed(self) -> str:
        return f"G7|{self.cell}|{self.path}|{self.index}"

    def stand(self, *, first_world: bool) -> dict:
        """The stand-in service's behaviour in the first process or after it."""
        answer = "settled" if self.point in ("delivery_sent", "delivered") else self.answer
        return {"answer": ANSWERS[answer], "raise_when": self.raise_when,
                "exc": EXCEPTIONS[self.exc],
                "unavailable": first_world and self.point in ("abort_committed",
                                                              "abort_uncommitted")}


def _client_key(rng: random.Random) -> str:
    """1-48 printable ASCII characters, no surrounding space."""
    n = rng.randint(1, 48)
    ends = [chr(rng.randint(33, 126)) for _ in range(2)]
    inner = "".join(chr(rng.randint(32, 126)) for _ in range(max(0, n - 2)))
    return ends[0] if n == 1 else ends[0] + inner + ends[1]


def case_for(cell: str, path: str, index: int) -> Case:
    rng = random.Random(f"G7|{cell}|{path}|{index}")
    return Case(
        cell=cell, path=path, index=index,
        action=rng.choice(STATE_MODIFYING),
        marker=rng.randrange(1, 10 ** 9),
        key=_client_key(rng),
        answer=rng.choice(sorted(ANSWERS)),
        raise_when=rng.choice(("before", "after")) if path == "raises" else None,
        exc=rng.choice(sorted(EXCEPTIONS)),
        point=rng.choice(POINTS[(cell, path)]),
        replays=rng.randint(1, 3),
        allow_first_replay=rng.random() < 0.5 if (cell, path) == ("X2", "refused") else True,
        allow_second_replay=rng.random() < 0.75 if (cell, path) == ("X2", "refused") else True,
    )


# ── the stand-ins ───────────────────────────────────────────────────────────

class Crash(BaseException):
    """The process died here: nothing after this instant happens."""


class Stand:
    """Every ACTION_MAP method: records the call (``calls``, the marker) the
    moment it begins, waits on ``gate`` when set (one gate for every method:
    several names share one service method, so a gate per name could miss), records its effect
    (``("service", action, marker)``) and answers ``answer``, or raises
    ``exc`` before or after the effect. The attestation service's ``attest``
    also takes the dispatcher's legacy attestation (recorded ``("attest",
    action)``); ``unavailable`` makes the registry refuse every service."""

    def __init__(self, effects: Effects, calls: list, *, answer: dict, raise_when: str | None,
                 exc: Callable[[], BaseException], unavailable: bool) -> None:
        self.effects = effects
        self.calls = calls
        self.answer = answer
        self.raise_when = raise_when
        self.exc = exc
        self.unavailable = unavailable
        self.gate: asyncio.Event | None = None
        self.before_effect: Callable[[], None] | None = None
        self.after_effect: Callable[[], None] | None = None

    def _method(self, action: str):
        async def method(**params):
            marker = params.get("marker")
            self.calls.append(marker)
            if self.gate is not None:
                await self.gate.wait()
            if self.before_effect is not None:
                self.before_effect()
            if self.raise_when == "before":
                raise self.exc()
            self.effects.log.append(("service", action, marker))
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
        effects = self.effects

        async def attest(**kwargs):
            if "schema_uid" in kwargs and "data" in kwargs and "marker" not in kwargs:
                effects.log.append(("attest", kwargs["data"].get("action")))
                return {"status": "queued"}
            return await action_attest(**kwargs)
        attestation["attest"] = attest
        namespaces = {s: SimpleNamespace(**m) for s, m in by_service.items()}
        namespaces["attestation"] = SimpleNamespace(**attestation)

        def get(name):
            if self.unavailable:
                raise KeyError(name)
            return namespaces.get(name, SimpleNamespace())
        return SimpleNamespace(get=get)


class World:
    """One process: its database, its effects and calls, the dispatcher and the
    mode-on engine."""

    def __init__(self, db_path: Path, clock: Clock, stand: dict, *,
                 effects: Effects | None = None, calls: list | None = None) -> None:
        self.clock = clock
        self.effects = effects if effects is not None else Effects()
        self.calls = calls if calls is not None else []
        self.db = open_db(db_path)
        self.stand = Stand(self.effects, self.calls, **stand)
        self.d = ServiceDispatcher({})
        registry = self.stand.registry()
        self.d._get_registry = lambda: registry
        self.d._feed_engine = Feed(self.effects)
        self.eng = engine(self.db, "on", clock, self.effects)

    async def request(self, case: Case, *, blocked: bool = False) -> str | None:
        return await bridge_like(self.d, case.action, params_for(case.action, case.marker),
                                 key=case.key, blocked=blocked)


_ENGINE_WORK = {"DurableEngine.open.<locals>.work": "open",
                "DurableEngine.abort.<locals>.work": "abort",
                "DurableEngine.finish.<locals>.work": "terminal",
                "DurableEngine._fail.<locals>.work": "terminal"}


@contextlib.contextmanager
def inject(point: str | None, world: World, on_crash: Callable[[], None]):
    """Arm the crash at *point* in *world*, once. ``on_crash`` must not return
    normally (it raises Crash, or ends the process)."""
    fired = [False]

    def fire() -> None:
        if not fired[0]:
            fired[0] = True
            on_crash()

    original_tx = journal.transaction

    def transaction(db, work, *, wait):
        kind = _ENGINE_WORK.get(getattr(work, "__qualname__", ""))
        if fired[0] or kind is None or point not in (f"{kind}_uncommitted", f"{kind}_committed"):
            return original_tx(db, work, wait=wait)
        if point.endswith("_uncommitted"):
            def cut(tx):
                out = work(tx)
                fire()          # the statements ran; COMMIT never does
                return out
            return original_tx(db, cut, wait=wait)
        out = original_tx(db, work, wait=wait)
        fire()
        return out

    journal.transaction = transaction
    if point == "begin":
        original_begin = world.eng.begin

        def begin(*args, **kwargs):
            fire()
            return original_begin(*args, **kwargs)
        world.eng.begin = begin
    elif point == "service_before_effect":
        world.stand.before_effect = fire
    elif point == "service_after_effect":
        world.stand.after_effect = fire
    elif point == "delivery_sent":
        original_submit = world.eng.attestations._submit_batch

        async def submit(batch):
            out = await original_submit(batch)
            fire()
            return out
        world.eng.attestations._submit_batch = submit
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


class Play:
    """The record of one injection: every request and its answer, what the
    key was bound to after each, the crash's prefix of effects and calls, and
    the world the properties are read from."""

    def __init__(self, case: Case, tmp: Path) -> None:
        self.case = case
        self.tmp = tmp
        self.key = keys.scoped(wiring.BRIDGE_ACTION, SCOPE, case.key)
        self.obs: list[tuple[str, int, str | None]] = []
        self.answers: list[tuple[str, str]] = []
        self.problems: list[str] = []
        self.prefix_effects: list = []
        self.prefix_calls: list = []
        self.crashed_at: float | None = None
        self.allowed_after_decisive = False
        self.decisive: int | None = None
        self.snap = tmp / f"{case.cell}-{case.path}-{case.index}-crash.db"

    # what happened
    def observe(self, label: str, world: World, *, base_calls: int = 0) -> None:
        self.obs.append((label, base_calls + len(world.calls), _binding(world.db).get(self.key)))

    def take_snapshot(self, world: World) -> None:
        snapshot(world.db, self.snap)
        self.prefix_effects = list(world.effects.log)
        self.prefix_calls = list(world.calls)
        self.crashed_at = world.clock.now

    def crash(self, world: World) -> None:
        self.take_snapshot(world)
        raise Crash()

    def expect(self, label: str, answer: str | None, expected: str | None,
               same_as: str | None = None) -> None:
        got = _category(answer)
        self.answers.append((label, got))
        if same_as is not None:
            if answer != same_as:
                self.problems.append(f"A: {label} was not the first answer byte for byte "
                                     f"({got}: {answer!r:.160} vs {same_as!r:.160})")
        elif got != expected:
            self.problems.append(f"A: {label} answered {got}, expected {expected}: {answer!r:.200}")

    async def request(self, world: World, label: str, *, blocked: bool = False,
                      expected: str | None = None, same_as: str | None = None,
                      base_calls: int = 0) -> str | None:
        answer = await world.request(self.case, blocked=blocked)
        if not blocked and self.decisive is not None:
            self.allowed_after_decisive = True
        self.observe(label, world, base_calls=base_calls)
        self.expect(label, answer, "gate_403" if blocked else expected, same_as)
        return answer

    def mark_decisive(self) -> None:
        """The observation that says whether the first request may have acted."""
        self.decisive = len(self.obs) - 1

    async def restart(self, db_path: Path, crashed_at: float, *, early: bool = False) -> World:
        """The new process over *db_path*. With *early*, the client replays
        once while the dead process's run is still inside ``abandoned_after_s``
        (the new process does not hold it and must not close or re-run it);
        then the clock passes the window."""
        world = World(db_path, Clock(crashed_at + 1.0), self.case.stand(first_world=False))
        self.obs.append(("crash", len(self.prefix_calls), _binding(world.db).get(self.key)))
        if self.decisive is None:
            self.mark_decisive()
        with installed(world.eng):
            if early:
                bound = self.obs[-1][2]
                state = journal.get_run(world.db, bound)["state"] if bound else None
                world.eng.maintain()
                await world.eng.loop.tick()
                await self.request(
                    world, "replay_early", base_calls=len(self.prefix_calls),
                    expected=("idempotency_in_progress" if state in journal.OPEN
                              else "idempotency_answer_not_held"))
            world.clock.advance(journal.ABANDONED_AFTER_S)
            world.eng.maintain()
            await world.eng.loop.tick()
        return world

    async def replays_after_restart(self, world: World, *, unbound: bool) -> None:
        """The client's replay under the same key, twice, in the new process."""
        base = len(self.prefix_calls)
        case = self.case
        with installed(world.eng):
            if unbound:
                expected = _error_category(case) if case.raise_when else "ok"
                first = await self.request(world, "replay_1", blocked=not case.allow_first_replay,
                                           expected=expected, base_calls=base)
                await drain(world.eng)
                if case.allow_first_replay and case.allow_second_replay:
                    await self.request(world, "replay_2", same_as=first, base_calls=base)
                else:
                    await self.request(world, "replay_2", blocked=not case.allow_second_replay,
                                       expected=expected, base_calls=base)
            else:
                await self.request(world, "replay_1", expected="idempotency_answer_not_held",
                                   base_calls=base)
                await drain(world.eng)
                await self.request(world, "replay_2", expected="idempotency_answer_not_held",
                                   base_calls=base)
            await drain(world.eng)


async def _new_world(template, path: Path, case: Case) -> World:
    snapshot(template, path)
    return World(path, Clock(), case.stand(first_world=True))


async def _settle(task: asyncio.Task) -> Any:
    try:
        return await task
    except (Crash, asyncio.CancelledError):
        return None


async def _until_called(world: World, n: int = 1) -> None:
    for _ in range(1000):
        if len(world.calls) >= n:
            return
        await asyncio.sleep(0)
    raise AssertionError("the first request never reached its service call")


# The four cells. Each plays the first process (w1), then — when it crashed or
# stopped — the restart and the replays; and returns the world the recovered
# state is read from.

async def play_x1(p: Play, w1: World) -> World:
    case = p.case
    with installed(w1.eng), inject(case.point, w1, lambda: p.crash(w1)) as fired:
        try:
            if case.path == "refused":
                await p.request(w1, "first", blocked=True)
            label = "second" if case.path == "refused" else "first"
            expected = (_error_category(case) if case.path == "raises"
                        else "service_unavailable" if case.point == "abort_committed" else "ok")
            await p.request(w1, label, expected=expected)
            if case.point == "delivered":
                await drain(w1.eng)
            p.take_snapshot(w1)
        except Crash:
            pass
    assert fired[0] or case.point in ("answered", "delivered"), f"{case.point} never fired"
    await w1.db.close()
    w2 = await p.restart(p.snap, p.crashed_at)
    await p.replays_after_restart(w2, unbound=p.obs[-1][2] is None)
    return w2


async def play_x2(p: Play, w1: World) -> World:
    case = p.case
    with installed(w1.eng), inject(case.point, w1, lambda: p.crash(w1)) as fired:
        try:
            if case.path == "refused":
                await p.request(w1, "first", blocked=True)
                p.take_snapshot(w1)
            else:
                await p.request(w1, "first", expected="never answered")
        except Crash:
            pass
    assert case.path == "refused" or fired[0], f"{case.point} never fired"
    await w1.db.close()
    w2 = await p.restart(p.snap, p.crashed_at)
    await p.replays_after_restart(w2, unbound=True)
    return w2


async def play_x6(p: Play, w1: World) -> World:
    case = p.case
    with installed(w1.eng), inject(case.point, w1, lambda: p.crash(w1)) as fired:
        try:
            if case.path == "refused":
                await p.request(w1, "first", blocked=True)
                p.mark_decisive()
            label = "second" if case.path == "refused" else "first"
            expected = _error_category(case) if case.path == "raises" else "ok"
            first = await p.request(w1, label, expected=expected)
            if p.decisive is None:
                p.mark_decisive()
            if case.point == "answered":
                p.crash(w1)
            await drain(w1.eng)
            if case.path != "crash":
                for i in range(case.replays):
                    await p.request(w1, f"replay_{i + 1}", same_as=first)
                    await drain(w1.eng)
            if case.point in ("delivered", "after_all"):
                p.crash(w1)
        except Crash:
            pass
    if case.point in ("terminal_committed", "delivery_sent"):
        assert fired[0], f"{case.point} never fired"
    if p.crashed_at is None:
        return w1
    await w1.db.close()
    w2 = await p.restart(p.snap, p.crashed_at)
    await p.replays_after_restart(w2, unbound=False)
    return w2


async def play_x7(p: Play, w1: World) -> World:
    case = p.case
    gate = asyncio.Event()
    w1.stand.gate = gate
    with installed(w1.eng), inject(case.point, w1, lambda: p.crash(w1)) as fired:
        task = asyncio.ensure_future(w1.request(case))
        await _until_called(w1)
        p.observe("first_in_call", w1)
        p.mark_decisive()
        concurrent = asyncio.ensure_future(p.request(
            w1, "concurrent", blocked=case.path == "refused",
            expected="idempotency_in_progress"))
        done, _pending = await asyncio.wait({concurrent}, timeout=1.0)
        if not done:
            # The replay entered the held service call: let both go on, so the
            # properties record it rather than the test hanging.
            p.problems.append("A: the concurrent replay did not answer while the first "
                              "request was held; it entered the service call")
            gate.set()
        await concurrent
        if case.point == "held":
            p.take_snapshot(w1)
            task.cancel()
            await _settle(task)
        else:
            gate.set()
            first = await _settle(task)
            if case.point is not None and case.point != "after_all":
                assert fired[0], f"{case.point} never fired"
            if p.crashed_at is None:
                expected = _error_category(case) if case.path == "raises" else "ok"
                p.observe("first", w1)
                p.expect("first", first, expected)
                await drain(w1.eng)
                await p.request(w1, "replay_1", same_as=first)
                await drain(w1.eng)
                if case.point == "after_all":
                    p.take_snapshot(w1)
    if p.crashed_at is None:
        return w1
    await w1.db.close()
    w2 = await p.restart(p.snap, p.crashed_at, early=case.path == "crash")
    await p.replays_after_restart(w2, unbound=False)
    return w2


PLAYERS = {"X1": play_x1, "X2": play_x2, "X6": play_x6, "X7": play_x7}


# ── the four properties ─────────────────────────────────────────────────────

def judge(p: Play, final: World) -> dict:
    """T, D, R, L (and A) for one injection, read from *final* (the recovered
    world, or the only one) and from what every process did."""
    case = p.case
    db = final.db
    effects = p.prefix_effects + list(final.effects.log) if final_is_restart(p) \
        else list(final.effects.log)
    calls = len(p.prefix_calls) + len(final.calls) if final_is_restart(p) else len(final.calls)
    runs = {r["run_id"]: dict(r) for r in db.fetchall_sync("SELECT * FROM workflow_runs")}
    problems = list(p.problems)
    out: dict[str, bool | None] = {}

    # T
    still_open = [r for r in runs.values() if r["state"] not in journal.TERMINAL]
    out["T"] = not still_open
    if still_open:
        problems.append(f"T: runs left open: {[(r['run_id'], r['state']) for r in still_open]}")

    # D
    service_effects = sum(1 for e in effects if e[0] == "service" and e[2] == case.marker)
    decisive = p.obs[p.decisive] if p.decisive is not None else p.obs[0]
    never_acted = decisive[1] == 0 and decisive[2] is None
    exact = never_acted and p.allowed_after_decisive
    d_ok = calls <= 1 and service_effects <= calls
    if exact:
        d_ok = d_ok and calls == 1 and service_effects == (0 if case.raise_when == "before" else 1)
    out["D"] = d_ok
    if not d_ok:
        problems.append(f"D: {calls} call(s), {service_effects} effect(s) under the key "
                        f"(exactly one call expected: {exact})")

    # R
    acting = next((i for i, o in enumerate(p.obs) if o[1] > 0 or o[2] is not None), None)
    if acting is None:
        out["R"] = None
    else:
        _label, calls_then, bound_to = p.obs[acting]
        later = p.obs[acting + 1:]
        final_bound = _binding(db).get(p.key)
        r_ok = (bound_to is not None
                and all(o[1] == calls_then and o[2] == bound_to for o in later)
                and final_bound == bound_to
                and runs.get(bound_to, {}).get("state") in (journal.COMPLETE, journal.FAIL))
        out["R"] = r_ok
        if not r_ok:
            problems.append(f"R: acting run {bound_to} at {p.obs[acting][0]}; observations "
                            f"{p.obs}; final binding {final_bound}, state "
                            f"{runs.get(bound_to or '', {}).get('state')}")

    # L
    attests = sum(1 for e in effects if e[0] in ("attest", "attest_sent"))
    feeds = sum(1 for e in effects if e[0] == "feed")
    settled_complete = any(
        r["action"] == case.action and r["state"] == journal.COMPLETE and any(
            s["name"] == journal.STEP_RETURN and s["state"] == "settled"
            for s in journal.get_steps(db, r["run_id"]))
        for r in runs.values())
    delivered_rows_ok = all(
        runs.get(row[0], {}).get("state") == journal.COMPLETE
        for row in db.fetchall_sync("SELECT run_id FROM outbox WHERE done_at IS NOT NULL"))
    l_ok = (attests <= 1 and feeds <= 1 and (attests + feeds == 0 or settled_complete)
            and delivered_rows_ok)
    out["L"] = l_ok
    if not l_ok:
        problems.append(f"L: {attests} attestation(s), {feeds} feed entr(y/ies); a settled "
                        f"COMPLETE run: {settled_complete}; delivered rows on COMPLETE runs "
                        f"only: {delivered_rows_ok}")

    out["A"] = not any(pr.startswith("A:") for pr in p.problems)
    return {"case": case, "point": case.point or "none", "held": out, "problems": problems,
            "answers": [a for _l, a in p.answers],
            "deliveries": {"attest": attests, "feed": feeds}}


def final_is_restart(p: Play) -> bool:
    return p.crashed_at is not None


async def play(case: Case, template, tmp: Path) -> dict:
    p = Play(case, tmp)
    w1 = await _new_world(template, tmp / f"{case.cell}-{case.path}-{case.index}.db", case)
    final = await PLAYERS[case.cell](p, w1)
    try:
        return judge(p, final)
    finally:
        await final.db.close()
        with contextlib.suppress(Exception):
            await w1.db.close()


# ── the matrix ──────────────────────────────────────────────────────────────

def _tally(results: list[dict]) -> dict:
    held = {prop: {"checked": 0, "held": 0} for prop in PROPERTIES}
    for r in results:
        for prop in PROPERTIES:
            v = r["held"][prop]
            if v is None:
                continue
            held[prop]["checked"] += 1
            held[prop]["held"] += int(bool(v))
    return {
        "injections": len(results),
        "crash_points": dict(sorted(Counter(r["point"] for r in results).items())),
        "held": held,
        "replay_answers": dict(sorted(Counter(a for r in results for a in r["answers"]).items())),
        "deliveries": {k: sum(r["deliveries"][k] for r in results) for k in ("attest", "feed")},
    }


_MATRIX: dict[str, dict[str, list[dict]]] = {}


async def _run_cell(cell: str) -> dict[str, list[dict]]:
    out: dict[str, list[dict]] = {}
    with tempfile.TemporaryDirectory() as scratch:
        tmp = Path(scratch)
        template = open_db(tmp / "template.db")
        try:
            for path in PATHS:
                out[path] = [await play(case_for(cell, path, i), template, tmp)
                             for i in range(PER_PATH)]
                for f in tmp.glob(f"{cell}-{path}-*"):
                    f.unlink()
        finally:
            await template.close()
    return out


def cell_results(cell: str) -> dict[str, list[dict]]:
    if cell not in _MATRIX:
        previous = wiring.current()
        _MATRIX[cell] = asyncio.run(_run_cell(cell))
        assert wiring.current() is previous, "the matrix left a durable engine installed"
    return _MATRIX[cell]


def _failures(results: dict[str, list[dict]]) -> list[str]:
    return [f"{r['case'].seed} {r['case'].action} at {r['point']}: {pr}"
            for rs in results.values() for r in rs for pr in r["problems"]]


@pytest.mark.parametrize("cell", sorted(CELLS))
def test_every_injection_keeps_t_d_r_l(cell):
    results = cell_results(cell)
    total = sum(len(rs) for rs in results.values())
    assert total >= 100, f"{cell}: only {total} injections"
    for path in PATHS:
        assert len(results[path]) >= 25, f"{cell}/{path}: only {len(results[path])} injections"
        drawn = {r["point"] for r in results[path]}
        wanted = {pt or "none" for pt in POINTS[(cell, path)]}
        assert drawn == wanted, f"{cell}/{path}: instants never drawn: {wanted - drawn}"
    failures = [f for f in _failures(results) if not f.split(": ", 1)[1].startswith("A:")]
    assert not failures, (f"{cell}: {len(failures)} property violation(s) (T/D/R/L), "
                          "first ones:\n" + "\n".join(failures[:12]))


@pytest.mark.parametrize("cell", sorted(CELLS))
def test_every_request_is_answered_what_the_spec_says(cell):
    failures = [f for f in _failures(cell_results(cell)) if f.split(": ", 1)[1].startswith("A:")]
    assert not failures, (f"{cell}: {len(failures)} answer(s) not the spec's, first ones:\n"
                          + "\n".join(failures[:12]))


def test_the_matrix_injects_at_every_required_instant():
    drawn = {pt for pts in POINTS.values() for pt in pts}
    missing = {what: pt for what, pt in REQUIRED_POINTS.items() if pt not in drawn}
    assert not missing, f"required crash instants never injected: {missing}"


def test_the_matrix_is_deterministic_per_seed():
    assert [asdict(case_for("X1", "crash", i)) for i in range(5)] == \
        [asdict(case_for("X1", "crash", i)) for i in range(5)]
    assert len({case_for("X7", "normal", i).key for i in range(PER_PATH)}) == PER_PATH


# ── the real-process subset ─────────────────────────────────────────────────

def child_main(spec_json: str) -> None:
    """Run in a child process: the first request of *spec*'s case over the
    real database file, ending the process with os._exit at the instant."""
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

    async def main() -> None:
        world = World(Path(spec["db"]), Clock(), case.stand(first_world=True),
                      effects=Effects(log=Log()), calls=Calls())
        with installed(world.eng), inject(case.point, world, lambda: os._exit(CHILD_EXIT)):
            await world.request(case)
            await drain(world.eng)
        os._exit(3)     # the instant was never reached
    asyncio.run(main())


def _child_case(cell: str, index: int) -> Case:
    base = case_for(cell, "crash", 1000 + index)
    return Case(**{**asdict(base), "point": CHILD_POINTS[cell][index], "path": "crash",
                   "raise_when": None})


async def _recover_child(case: Case, db_path: Path, effects_path: Path) -> dict:
    p = Play(case, db_path.parent)
    for line in effects_path.read_text(encoding="utf-8").splitlines():
        entry = json.loads(line)
        if entry[0] == "call":
            p.prefix_calls.append(entry[1])
        else:
            p.prefix_effects.append(tuple(entry[1:]))
    p.crashed_at = START_AT
    world = await p.restart(db_path, START_AT)
    await p.replays_after_restart(world, unbound=p.obs[-1][2] is None)
    try:
        return judge(p, world)
    finally:
        await world.db.close()


def child_results(cell: str, tmp: Path) -> tuple[list[dict], list[int]]:
    env = {k: v for k, v in os.environ.items() if k != "MATRIX_DURABLE_MODE"}
    env.update(PYTHONPATH=str(ROOT), PYTHONDONTWRITEBYTECODE="1")
    procs = []
    for i in range(len(CHILD_POINTS[cell])):
        case = _child_case(cell, i)
        db_path, effects_path = tmp / f"{cell}-{i}.db", tmp / f"{cell}-{i}.effects"
        effects_path.write_text("", encoding="utf-8")
        spec = json.dumps({"case": asdict(case), "db": str(db_path),
                           "effects": str(effects_path)})
        code = ("import sys; sys.path.insert(0, 'tests'); "
                "import test_durable_crash_matrix as m; m.child_main(sys.argv[1])")
        procs.append((case, db_path, effects_path, subprocess.Popen(
            [sys.executable, "-c", code, spec], cwd=ROOT, env=env,
            stdout=subprocess.DEVNULL, stderr=subprocess.PIPE)))
    results, statuses = [], []
    for case, db_path, effects_path, proc in procs:
        _out, err = proc.communicate(timeout=60)
        statuses.append(proc.returncode)
        assert proc.returncode == CHILD_EXIT, (
            f"{case.cell} child at {case.point} exited {proc.returncode}, not {CHILD_EXIT}: "
            f"{err.decode(errors='replace')[-1500:]}")
        previous = wiring.current()
        results.append(asyncio.run(_recover_child(case, db_path, effects_path)))
        assert wiring.current() is previous
    return results, statuses


_CHILDREN: dict[str, tuple[list[dict], list[int]]] = {}


def children(cell: str) -> tuple[list[dict], list[int]]:
    if cell not in _CHILDREN:
        with tempfile.TemporaryDirectory() as scratch:
            _CHILDREN[cell] = child_results(cell, Path(scratch))
    return _CHILDREN[cell]


@pytest.mark.parametrize("cell", sorted(CHILD_POINTS))
def test_a_process_killed_at_the_instant_recovers_with_t_d_r_l(cell):
    results, statuses = children(cell)
    assert statuses == [CHILD_EXIT] * len(CHILD_POINTS[cell]), statuses
    failures = [f"{r['case'].seed} {r['case'].action} at {r['point']}: {pr}"
                for r in results for pr in r["problems"]]
    assert not failures, f"{cell} (real process): " + "\n".join(failures)


# ── the artefact ────────────────────────────────────────────────────────────

RULE = ("G7: every run reaches a terminal state on every path (normal, refused by the gate, "
        "service raises, crash between steps then restart) for X1 dispatch-then-crash, X2 "
        "crash-before-record, X6 replay-after-complete and X7 replay-during-run; and through "
        "every injection no action runs twice, an action that may have acted is never re-run "
        "and keeps its key, and no attestation or feed entry is delivered for a run that is "
        "not COMPLETE or delivered twice.")
INSTRUMENT = (
    "tests/test_durable_crash_matrix.py: engines.durable.mode on, the real ServiceDispatcher and "
    "DurableEngine over the platform Database (SQLite, a scratch file per injection), driven "
    "through the bridge's sequence at the dispatcher (gate -> wiring.keyed -> execute) under an "
    "Idempotency-Key, over stand-in services, chain and feed that record every call and effect. "
    "A crash is the SQLite backup of the committed state at the instant plus the effects and "
    "calls made so far; a restart is a fresh Database and engine over it, the clock moved past "
    "abandoned_after_s, maintain() and one loop tick, then the same request twice under the same "
    "key. Seeded with random.Random('G7|cell|path|index'). real_process: a child interpreter "
    "over a real database file, ended with os._exit(137) at the instant, recovered by the parent.")
SCOPE_TEXT = (
    f"{PER_PATH} injections per path, 4 paths per cell, 4 cells ({PER_PATH * 16} in all), over "
    f"the {len(STATE_MODIFYING)} state-modifying names ACTION_MAP serves; 3 real-process runs "
    "each for X1 and X2. In-process: no network, no chain, no gateway HTTP layer (the gate is "
    "bridge_like's blocked flag).")
PROPERTY_TEXT = {
    "T": "every run in the recovered database is COMPLETE, ABORT or FAIL",
    "D": ("service calls under the key <= 1 across the first request, the crash and the replays, "
          "effects <= calls; exactly 1 call when the first request made no call and left its key "
          "unbound in the committed state and a later request passed the gate"),
    "R": ("once a run under the key may have acted (call began, or key bound to it in the "
          "committed state) no later request calls the service, the key stays bound to that run "
          "and it ends COMPLETE or FAIL; checked only where some run may have acted"),
    "L": ("at most one attestation (outbox or legacy) and one feed entry delivered, only when a "
          "COMPLETE run returned settled, and no outbox row marked delivered for a run that is "
          "not COMPLETE"),
    "A": ("every request answered what the spec says: the first answer byte for byte, "
          "idempotency_in_progress, idempotency_answer_not_held after a restart, or a normal "
          "dispatch when the key was never bound (not one of the four G7 properties; recorded "
          "alongside)"),
}


def measure() -> dict:
    cells = {CELLS[c]: {path: _tally(rs) for path, rs in cell_results(c).items()}
             for c in sorted(CELLS)}
    real = {}
    for c in sorted(CHILD_POINTS):
        results, statuses = children(c)
        tally = _tally(results)
        tally["exit_status"] = dict(Counter(str(s) for s in statuses))
        real[CELLS[c]] = tally
    return {"gate": "G7", "rule": RULE, "instrument": INSTRUMENT, "scope": SCOPE_TEXT,
            "properties": PROPERTY_TEXT, "measured": durable_measured_at.measured_at(),
            "cells": cells, "real_process": real}


def test_the_g7_artefact():
    measured = measure()
    path = BASELINE / ARTEFACT
    if WRITE:
        BASELINE.mkdir(parents=True, exist_ok=True)
        path.write_text(json.dumps(measured, indent=1, sort_keys=True) + "\n", encoding="utf-8")
    assert path.is_file(), f"{path} missing — run with ENGINES_BASELINE=write"
    committed = json.loads(path.read_text(encoding="utf-8"))
    for field_name in ("gate", "rule", "instrument", "scope", "properties", "measured"):
        assert field_name in committed, f"{ARTEFACT} has no {field_name!r}"
    durable_measured_at.check(committed["measured"], ARTEFACT)
    recomputed = json.loads(json.dumps(measured))
    for part in ("cells", "real_process"):
        assert committed[part] == recomputed[part], (
            f"{ARTEFACT} {part} no longer match what the matrix measures. If the change is "
            "intended, rewrite it with ENGINES_BASELINE=write and say why in the commit.")
    for name, paths in committed["cells"].items():
        for path_name, tally in paths.items():
            for prop in ("T", "D", "R", "L"):
                h = tally["held"][prop]
                assert h["held"] == h["checked"], (
                    f"G7 fails: {name}/{path_name}: {prop} held in {h['held']} of "
                    f"{h['checked']} injections")
