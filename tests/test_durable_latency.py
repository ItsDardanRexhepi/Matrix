"""Engines Phase 2, gate G6: the latency the durable engine adds per dispatch.

``engines.durable.mode`` shadow and on write a run around every journaled
dispatch — two transactions on the platform database, one immediately before
the effect call (the run RUNNING, its key bound) and one after it (the run
COMPLETE, its outbox rows, its key's answer digest). G6 asks what that costs a
caller, in microseconds, and this file measures it on three surfaces:

  (a) ``execute``        — ``ServiceDispatcher.execute`` of a state-modifying
                           name, no Idempotency-Key;
  (b) ``execute_keyed``  — the same inside ``wiring.keyed`` with a fresh
                           Idempotency-Key on every call, as the bridge runs it;
  (c) ``tool_twin_signing`` — ``ToolDispatcher.dispatch`` of a twin tool's
                           platform-key signing call (``nft`` ``mint``).

Each in off, shadow and on over a scratch SQLite file, against stand-ins that
answer at once (a settled success: the heaviest answer, the one that writes the
attestation and the feed entry), so what is timed is the platform's own cost:
no chain, no network. The modes are interleaved — every round runs one block of
each mode, in an order that rotates — so a drift of the host over the run lands
on every mode alike. The outbox loop is not running while a block is timed; it
ticks between blocks, outside the stopwatch, so mode on reaches a steady state
the way a live gateway does without its deliveries landing inside a sample.

THE BASE TREE. The off figure of (a) is also taken on the base tree — a
checkout of the branch this work merges into, which has no ``runtime/durable``
— by the same function, run in a separate interpreter importing ``runtime``
from that checkout, and, with the same instrument, on this tree, alternating
the two, so ``main_off`` and its ratio compare like with like. The functions that run there use only
``ServiceDispatcher``, ``ACTION_MAP`` and ``_STATE_MODIFYING_ACTIONS``, which
the base tree has; nothing from ``runtime.durable`` is imported at module level.

Stopwatch figures are host-dependent, so, as with B4 in
tests/test_engines_baseline.py, they are measured only with
``ENGINES_BASELINE=write`` (which also needs a checkout of main: the
``DURABLE_LATENCY_MAIN_TREE`` directory, else the git worktree on branch
``main``) and otherwise the committed ``tests/baseline/durable_g6_latency.json``
is checked for shape. The always-on checks here are the cheap facts the figures
rest on: mode off touches no durable table, reads no Idempotency-Key and opens
no transaction; shadow and on open exactly two transactions per journaled
dispatch (shadow never waiting for the database, on waiting like any platform
write), and none for a call they do not journal.

WHAT IS NOT MEASURED. The plan's G6 names three surfaces: ``pre_action``,
``execute`` and the whole ``POST /bridge/v1/action`` route. No durable code
runs in ``pre_action`` (the gate has answered before any of it), and it is not
timed here; the route is not timed through HTTP either: surface (b) is the
route's sequence after the gate, at the dispatcher. The stand-ins answer at
once, so a real service's own latency, which would dilute the ratio, is not in
the figures, and the outbox loop's deliveries are not inside any timed call.

THE BUDGET. G6 asks that a phase keep a dispatch's p95 within +10 percent of
the base tree's, a bound left to the project owner to confirm; this file
records the figures and asserts no bound. Shadow and on are over it: they put a
journaled dispatch's p95 at several times the same dispatch's with the mode
off. Off is a difference of about a microsecond on a call of about sixteen, in
either direction from one run to the next (``main_off.pairs``), which this
instrument does not resolve against a 10 percent bound. The budget is the
owner's decision and still open. Durable execution can merge dark, with the mode
off by default, and its phase is not closed until G6 holds.
"""
from __future__ import annotations

import asyncio
import gc
import json
import os
import platform
import statistics
import subprocess
import sys
import tempfile
import time
from pathlib import Path
from types import SimpleNamespace

import pytest

# Only what the base tree has: the off measure of surface (a) also runs there.
from runtime.blockchain.services.service_dispatcher import (
    ACTION_MAP, ServiceDispatcher, _STATE_MODIFYING_ACTIONS,
)

ROOT = Path(__file__).resolve().parent.parent
ARTEFACT = ROOT / "tests" / "baseline" / "durable_g6_latency.json"
WRITE = os.environ.get("ENGINES_BASELINE", "").strip().lower() == "write"
MAIN_TREE_ENV = "DURABLE_LATENCY_MAIN_TREE"

MODES = ("off", "shadow", "on")
SURFACES = ("execute", "execute_keyed", "tool_twin_signing")
N = 5000
ROUNDS = 50
BLOCK = N // ROUNDS
WARM_UP = 200
#: Interpreter runs per tree for main_off, alternating main and this tree.
MAIN_PAIRS = 5

WALLET = "0x" + "ab" * 20
SCOPE = f"operator|{WALLET}"
NAMES = sorted(a for a in _STATE_MODIFYING_ACTIONS if a in ACTION_MAP)
SETTLED = {"status": "success", "tx_hash": "0x" + "22" * 32, "settled": True}
BROADCAST = {"status": "submitted", "tx_hash": "0x" + "33" * 32}
REFUSED = {"status": "not_deployed", "error": "contracts are not deployed"}
TWIN_CALL = {"action": "mint", "to": WALLET, "token_uri": "ipfs://g6"}
TWIN_READ = {"action": "get_owner", "token_id": 1}


# ── the stand-ins (main-safe) ───────────────────────────────────────────────

def _percentiles(samples: list[float]) -> dict:
    """B4's method (tests/test_engines_baseline.py), verbatim."""
    ordered = sorted(samples)
    return {"n": len(ordered),
            "p50_us": round(statistics.median(ordered) * 1e6, 1),
            "p95_us": round(ordered[int(0.95 * (len(ordered) - 1))] * 1e6, 1)}


class _Service:
    """Every method of every service answers ``answer`` at once; as the
    attestation service, it resolves every schema to one well-formed UID."""

    def __init__(self, answer: dict) -> None:
        async def returns_at_once(**kwargs):
            return dict(answer)
        self._method = returns_at_once

    @staticmethod
    def _resolve_schema(schema_uid: str) -> str:
        return "0x" + "77" * 32

    def __getattr__(self, name):
        return self._method


class _Feed:
    async def ingest(self, **kwargs):
        return SimpleNamespace(summary=f"performed {kwargs.get('action')}")


def stand_in_dispatcher(answer: dict = SETTLED) -> ServiceDispatcher:
    """A real ServiceDispatcher over a registry whose every method answers at
    once, with a feed engine attached (a settled answer publishes)."""
    d = ServiceDispatcher({})
    service = _Service(answer)
    registry = SimpleNamespace(get=lambda name: service)
    d._get_registry = lambda: registry
    d.attach_feed_engine(_Feed())
    return d


async def _settle_tasks() -> None:
    """Let the feed publishes a block queued (mode off and shadow) run."""
    for _ in range(3):
        await asyncio.sleep(0)


async def time_execute(d: ServiceDispatcher, count: int, start: int) -> list[float]:
    """Surface (a): ``count`` dispatches of the state-modifying names in turn,
    each timed alone. Main-safe."""
    samples: list[float] = []
    for i in range(start, start + count):
        name = NAMES[i % len(NAMES)]
        params = {"to": WALLET, "amount": 5, "marker": i}
        t0 = time.perf_counter()
        await d.execute(name, params=params, caller_identity=WALLET)
        samples.append(time.perf_counter() - t0)
    await _settle_tasks()
    return samples


def measure_main_off(n: int = N) -> dict:
    """Surface (a) in mode off, in this interpreter, with the tree it imports:
    a warm-up, then ``n`` samples. Run on the base tree and on this tree alike."""
    import importlib.util

    async def run() -> list[float]:
        d = stand_in_dispatcher()
        await time_execute(d, WARM_UP, 0)
        samples: list[float] = []
        for r in range(n // BLOCK):
            if r % len(SURFACES) == 0:
                gc.collect()
            samples += await time_execute(d, BLOCK, WARM_UP + r * BLOCK)
        return samples
    return {"samples": asyncio.run(run()),
            "durable_package_present": importlib.util.find_spec("runtime.durable") is not None}


# ── the in-process measure (this tree only) ─────────────────────────────────

class _Chain:
    """The batch processor's submission path: every attestation lands."""

    async def _submit_batch(self, batch):
        return [{"status": "success", "attestation_uid": "0x" + "44" * 32,
                 "tx_hash": "0x" + "55" * 32, "id": att["id"]} for att in batch]


def _tool_dispatcher():
    from runtime.tools.dispatcher import ToolDispatcher

    td = ToolDispatcher({})

    async def nft(**kwargs):
        return dict(SETTLED)
    td.register("nft", nft, {"name": "nft"})
    return td


async def time_execute_keyed(d: ServiceDispatcher, count: int, start: int, tag: str
                             ) -> list[float]:
    """Surface (b): as (a), each call inside ``wiring.keyed`` with a key no
    other call used."""
    from runtime.durable import wiring

    samples: list[float] = []
    for i in range(start, start + count):
        name = NAMES[i % len(NAMES)]
        params = {"to": WALLET, "amount": 5, "marker": i}
        request = SimpleNamespace(headers={"Idempotency-Key": f"g6-{tag}-{i}"})
        t0 = time.perf_counter()
        with wiring.keyed(request, scope=SCOPE, decision={"evaluation_id": f"eval_{i}"}):
            await d.execute(name, params=params, caller_identity=WALLET)
        samples.append(time.perf_counter() - t0)
    await _settle_tasks()
    return samples


async def time_tool(td, count: int) -> list[float]:
    """Surface (c): ``count`` twin signing calls through ToolDispatcher.dispatch."""
    samples: list[float] = []
    for _ in range(count):
        arguments = dict(TWIN_CALL)
        t0 = time.perf_counter()
        outcome = await td.dispatch("nft", arguments, agent_name="neo",
                                    caller_identity=WALLET, caller_source="session")
        samples.append(time.perf_counter() - t0)
        if not outcome.ok:
            raise RuntimeError(f"the stand-in twin call failed: {outcome!r}")
    return samples


async def measure_in_process(scratch: str) -> dict:
    """Every surface in every mode, interleaved in ROUNDS rounds of BLOCK."""
    from runtime.db.database import Database
    from runtime.durable import wiring
    from runtime.durable.wiring import DurableEngine

    db = Database({"database": {"path": f"{scratch}/g6.db"}})
    engines = {"off": None,
               "shadow": DurableEngine(db, mode="shadow", attestations=_Chain()),
               "on": DurableEngine(db, mode="on", attestations=_Chain())}
    d = stand_in_dispatcher()
    td = _tool_dispatcher()
    samples = {s: {m: [] for m in MODES} for s in SURFACES}
    counter = {s: {m: 0 for m in MODES} for s in SURFACES}

    async def block(surface: str, mode: str, count: int, keep: bool) -> None:
        eng = engines[mode]
        previous = wiring.install(eng)
        try:
            start = counter[surface][mode]
            counter[surface][mode] += count
            if surface == "execute":
                got = await time_execute(d, count, start)
            elif surface == "execute_keyed":
                got = await time_execute_keyed(d, count, start, mode)
            else:
                got = await time_tool(td, count)
        finally:
            wiring.install(previous)
        if eng is not None:
            await eng.loop.tick()     # the outbox loop's work, outside the stopwatch
        if keep:
            samples[surface][mode] += got

    try:
        for surface in SURFACES:
            for mode in MODES:
                await block(surface, mode, WARM_UP, keep=False)
        for r in range(ROUNDS):
            order = MODES[r % 3:] + MODES[:r % 3]
            gc.collect()
            for surface in SURFACES:
                for mode in order:
                    await block(surface, mode, BLOCK, keep=True)
        runs = {row[0]: row[1] for row in db.fetchall_sync(
            "SELECT state, COUNT(*) FROM workflow_runs GROUP BY state")}
        undelivered = db.fetchall_sync(
            "SELECT COUNT(*) FROM outbox WHERE done_at IS NULL")[0][0]
    finally:
        await db.close()
    journaled = 2 * (WARM_UP + N) * len(SURFACES)
    if runs != {"COMPLETE": journaled} or undelivered:
        raise RuntimeError(f"the measured runs did not all complete and deliver: {runs}, "
                           f"{undelivered} outbox row(s) not handed off")
    return {s: {m: _percentiles(samples[s][m]) for m in MODES} for s in SURFACES}


# ── main_off ────────────────────────────────────────────────────────────────

_RUN_ONE = ("import importlib.util, json, sys\n"
            "spec = importlib.util.spec_from_file_location('durable_g6_measure', sys.argv[1])\n"
            "m = importlib.util.module_from_spec(spec)\n"
            "spec.loader.exec_module(m)\n"
            "open(sys.argv[2], 'w').write(json.dumps(m.measure_main_off()))\n")


def _git(tree: Path, *args: str) -> str:
    return subprocess.run(["git", "-C", str(tree), *args], capture_output=True, text=True,
                          timeout=60).stdout.strip()


def _main_tree() -> Path:
    named = os.environ.get(MAIN_TREE_ENV, "").strip()
    if named:
        return Path(named)
    current = None
    for line in _git(ROOT, "worktree", "list", "--porcelain").splitlines():
        if line.startswith("worktree "):
            current = line[len("worktree "):]
        elif line == "branch refs/heads/main" and current:
            return Path(current)
    raise AssertionError(f"measuring G6 needs a checkout of main: set {MAIN_TREE_ENV} or add a "
                         "git worktree on branch main")


def _measure_off_in(tree: Path, out: Path) -> dict:
    env = {k: v for k, v in os.environ.items() if k != "MATRIX_DURABLE_MODE"}
    env["PYTHONPATH"] = str(tree)
    env["PYTHONDONTWRITEBYTECODE"] = "1"   # measure main, never write into it
    done = subprocess.run([sys.executable, "-c", _RUN_ONE, str(Path(__file__).resolve()),
                           str(out)], cwd=str(tree), env=env, capture_output=True, text=True,
                          timeout=600)
    assert done.returncode == 0, f"measuring off in a separate interpreter failed:\n" \
                                 f"{done.stderr[-4000:]}"
    return json.loads(out.read_text(encoding="utf-8"))


def measure_main_off_pair(scratch: str) -> dict:
    main_tree = _main_tree()
    pooled: dict[str, list[float]] = {"main": [], "this_tree": []}
    pairs: list[dict] = []
    for k in range(MAIN_PAIRS):
        pair: dict[str, float] = {}
        # Which tree runs first alternates from one pair to the next, so a
        # host that drifts during a pair moves neither side's figures alone.
        order = (("main", main_tree), ("this_tree", ROOT))
        for which, tree in (order if k % 2 == 0 else order[::-1]):
            got = _measure_off_in(tree, Path(scratch) / f"{which}-{k}.json")
            assert got["durable_package_present"] is (which == "this_tree"), (
                f"{tree} {'has' if got['durable_package_present'] else 'lacks'} runtime/durable: "
                f"it is not {which.replace('_', ' ')}")
            pooled[which] += got["samples"]
            pair[f"{which}_p95_us"] = _percentiles(got["samples"])["p95_us"]
        pair["ratio_p95"] = round(pair["this_tree_p95_us"] / pair["main_p95_us"], 3)
        pairs.append(pair)
    main = _percentiles(pooled["main"])
    this = _percentiles(pooled["this_tree"])
    per_pair = sorted(p["ratio_p95"] for p in pairs)
    return {
        # By subject: an id does not survive a rewrite of the history.
        "main_commit": _git(main_tree, "log", "-1", "--format=%s", "HEAD"),
        "main": main,
        "this_tree": this,
        "ratio_this_tree_to_main": {"p50": round(this["p50_us"] / main["p50_us"], 3),
                                    "p95": round(this["p95_us"] / main["p95_us"], 3)},
        # Each run of the base tree against the run of this tree beside it
        # (first on even pairs, second on odd ones): how far one draw moves
        # the ratio.
        "pairs": pairs,
        "ratio_p95_per_pair": {"min": per_pair[0], "median": statistics.median(per_pair),
                               "max": per_pair[-1]},
    }


# ── the artefact ────────────────────────────────────────────────────────────

def _measured_where() -> dict:
    """The commit this tree is at, by subject, and whether it is clean. Imported
    here, not at the top: this module is also run on the base tree, which lacks it."""
    from tests.durable_measured_at import measured_at
    return measured_at(ROOT)


def _added(cells: dict) -> dict:
    return {s: {m: {"p50_us": round(cells[s][m]["p50_us"] - cells[s]["off"]["p50_us"], 1),
                    "p95_us": round(cells[s][m]["p95_us"] - cells[s]["off"]["p95_us"], 1)}
                for m in ("shadow", "on")} for s in SURFACES}


def _load() -> list[float]:
    """The host's 1, 5 and 15 minute load averages: how busy the machine the
    stopwatch ran on was with other work."""
    return [round(x, 2) for x in os.getloadavg()]


def measure() -> dict:
    load_before = _load()
    with tempfile.TemporaryDirectory() as scratch:
        cells = asyncio.run(measure_in_process(scratch))
        main_off = measure_main_off_pair(scratch)
    load_after = _load()
    off = cells["execute"]["off"]
    main = main_off["main"]
    main_off["ratio_cell_off_to_main"] = {"p50": round(off["p50_us"] / main["p50_us"], 3),
                                          "p95": round(off["p95_us"] / main["p95_us"], 3)}
    return {
        "gate": "G6",
        "rule": ("the latency engines.durable adds to one dispatch, in microseconds: for each "
                 "surface, added = the mode's p50 (p95) minus mode off's p50 (p95), measured in "
                 "the same rounds. A p95 difference is a difference of percentiles, not a "
                 "percentile of per-call differences."),
        "scope": ("execute: ServiceDispatcher.execute of every state-modifying ACTION_MAP name "
                  f"in turn ({len(NAMES)}), params {{to, amount, marker}}, the caller's identity "
                  "bound, no Idempotency-Key. execute_keyed: the same inside wiring.keyed with a "
                  "fresh Idempotency-Key per call (the bridge's sequence after the gate). "
                  "tool_twin_signing: ToolDispatcher.dispatch('nft', {action: mint, ...}) as "
                  "agent neo with a session identity. Every service answers a settled success at "
                  "once; in shadow and on every dispatch writes one run (two transactions), and "
                  "in on a settled execute also writes an attestation and a feed outbox row."),
        "instrument": ("in-process time.perf_counter around one call, B4's percentile method; "
                       f"{ROUNDS} rounds, each timing a block of {BLOCK} calls per surface per "
                       "mode with the mode order rotating every round, after a discarded "
                       f"warm-up of {WARM_UP} per cell; gc.collect() at the start of each "
                       "round; one DurableEngine per mode over one scratch SQLite file (the "
                       "platform Database, WAL), installed for its block only; the outbox loop not "
                       "running, ticked between blocks outside the stopwatch so every held "
                       "delivery is handed off; stand-in services, feed and attestation client "
                       "that answer at once — the platform's own cost, no chain, no network. "
                       "main_off: surface execute in mode off, measure_main_off() in a separate "
                       "interpreter per run (gc.collect() every third block, as often as a round "
                       "collects), alternating a checkout of the base tree and this tree, "
                       f"{MAIN_PAIRS} runs each, samples pooled; ratio_this_tree_to_main compares "
                       "those two, pairs and ratio_p95_per_pair give each run of the base tree "
                       "against the run of this tree beside it, the base tree first on even "
                       "pairs and second on odd ones, ratio_cell_off_to_main compares "
                       "the in-process off cell (taken between shadow and on blocks) with the "
                       "base tree. Not timed: pre_action, which no durable code runs in, and the "
                       "HTTP route itself. Host-dependent."),
        "measured": _measured_where(),
        "host": {"machine": platform.machine(), "system": platform.system(),
                 "python": platform.python_version(), "cpus": os.cpu_count(),
                 "load_average_before": load_before, "load_average_after": load_after},
        "cells": cells,
        "added": _added(cells),
        "main_off": main_off,
    }


def _write(payload: dict) -> None:
    ARTEFACT.parent.mkdir(parents=True, exist_ok=True)
    ARTEFACT.write_text(json.dumps(payload, indent=1, sort_keys=True) + "\n", encoding="utf-8")


def _check_cell(where: str, cell: dict) -> None:
    assert cell["n"] >= N, f"{where}: {cell['n']} samples, G6 needs at least {N}"
    assert 0 < cell["p50_us"] <= cell["p95_us"], f"{where}: not 0 < p50 <= p95: {cell}"


def test_g6_latency_added_per_dispatch_is_recorded():
    if WRITE:
        _write(measure())
    assert ARTEFACT.is_file(), f"{ARTEFACT} missing — run with ENGINES_BASELINE=write"
    g6 = json.loads(ARTEFACT.read_text(encoding="utf-8"))
    assert g6["gate"] == "G6", g6.get("gate")
    for field in ("rule", "scope", "instrument"):
        assert isinstance(g6.get(field), str) and g6[field], f"G6 does not say its {field}"
    from tests import durable_measured_at
    durable_measured_at.check(g6["measured"], ARTEFACT.name)
    assert set(g6["host"]) == {"machine", "system", "python", "cpus", "load_average_before",
                               "load_average_after"}, g6["host"]
    assert set(g6["cells"]) == set(SURFACES), f"G6 surfaces: {sorted(g6['cells'])}"
    for surface in SURFACES:
        assert set(g6["cells"][surface]) == set(MODES), f"{surface}: {sorted(g6['cells'][surface])}"
        for mode in MODES:
            _check_cell(f"{surface}/{mode}", g6["cells"][surface][mode])
        for mode in ("shadow", "on"):
            added = g6["added"][surface][mode]
            for p in ("p50_us", "p95_us"):
                expected = round(g6["cells"][surface][mode][p] - g6["cells"][surface]["off"][p], 1)
                assert isinstance(added.get(p), (int, float)) and abs(added[p] - expected) < 0.05, (
                    f"added {surface}/{mode} {p} is {added.get(p)}, the cells give {expected}")
    main_off = g6["main_off"]
    subjects = durable_measured_at.history_subjects()
    assert main_off["main_commit"] and (subjects is None or main_off["main_commit"] in subjects), (
        f"main_off does not name, by subject, a commit of this history: {main_off['main_commit']!r}")
    _check_cell("main_off/main", main_off["main"])
    _check_cell("main_off/this_tree", main_off["this_tree"])
    for ratio, over in (("ratio_this_tree_to_main", main_off["this_tree"]),
                        ("ratio_cell_off_to_main", g6["cells"]["execute"]["off"])):
        for p in ("p50", "p95"):
            expected = round(over[f"{p}_us"] / main_off["main"][f"{p}_us"], 3)
            assert abs(main_off[ratio][p] - expected) < 0.0015, (
                f"main_off {ratio} {p} is {main_off[ratio][p]}, the figures give {expected}")
    pairs = main_off["pairs"]
    assert len(pairs) == MAIN_PAIRS, f"{len(pairs)} pairs, the instrument runs {MAIN_PAIRS}"
    for pair in pairs:
        assert abs(pair["ratio_p95"] - pair["this_tree_p95_us"] / pair["main_p95_us"]) < 0.0015
    ratios = sorted(pair["ratio_p95"] for pair in pairs)
    assert main_off["ratio_p95_per_pair"] == {
        "min": ratios[0], "median": statistics.median(ratios), "max": ratios[-1]}, (
        main_off["ratio_p95_per_pair"])


# ── always on: what the figures rest on ─────────────────────────────────────

@pytest.fixture
async def db(tmp_path):
    from runtime.db.database import Database

    database = Database({"database": {"path": str(tmp_path / "g6.db")}})
    yield database
    await database.close()


@pytest.fixture
def transactions(monkeypatch):
    """Every journal.transaction call, as its ``wait`` argument."""
    from runtime.durable import journal

    seen: list[bool] = []
    real = journal.transaction

    def counted(db_, work, *, wait):
        seen.append(wait)
        return real(db_, work, wait=wait)
    monkeypatch.setattr(journal, "transaction", counted)
    return seen


class _Headers(dict):
    """Request headers that remember every read."""

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.reads: list = []

    def get(self, key, default=None):
        self.reads.append(key)
        return super().get(key, default)


DURABLE_TABLES = ("workflow_runs", "workflow_steps", "outbox", "idempotency_keys")
DISPATCHES = 3


def _table_counts(database) -> dict:
    return {t: database.fetchall_sync(f"SELECT COUNT(*) FROM {t}")[0][0] for t in DURABLE_TABLES}


@pytest.fixture(scope="module")
def tool_dispatcher():
    from runtime.tools.dispatcher import ToolDispatcher
    return ToolDispatcher({})


async def _dispatch(surface: str, answer: dict, i: int, headers: _Headers, td) -> None:
    from runtime.durable import wiring

    if surface == "tool_twin_signing":
        async def nft(**kwargs):
            return dict(answer)
        td.register("nft", nft, {"name": "nft"})
        outcome = await td.dispatch("nft", dict(TWIN_CALL), agent_name="neo",
                                    caller_identity=WALLET, caller_source="session")
        assert outcome.ok, f"the twin signing call failed: {outcome!r}"
        return
    d = stand_in_dispatcher(answer)
    params = {"to": WALLET, "amount": 5, "marker": i}
    if surface == "execute":
        envelope = await d.execute(NAMES[i], params=params, caller_identity=WALLET)
    else:
        headers["Idempotency-Key"] = f"g6-check-{i}"
        with wiring.keyed(SimpleNamespace(headers=headers), scope=SCOPE,
                          decision={"evaluation_id": f"eval_{i}"}):
            envelope = await d.execute(NAMES[i], params=params, caller_identity=WALLET)
    assert json.loads(envelope)["status"] == "ok", envelope
    await _settle_tasks()


@pytest.mark.parametrize("surface", SURFACES)
@pytest.mark.parametrize("answer", [SETTLED, BROADCAST, REFUSED], ids=["settled", "broadcast",
                                                                       "refused"])
@pytest.mark.parametrize("mode", MODES)
async def test_off_touches_nothing_and_a_journaled_dispatch_takes_two_transactions(
        mode, answer, surface, db, transactions, tool_dispatcher):
    from runtime.durable import wiring
    from runtime.durable.wiring import DurableEngine

    sys.path.insert(0, "tests")
    from test_durable_harness import installed

    engine = None if mode == "off" else DurableEngine(db, mode=mode, attestations=_Chain())
    statements: list[str] = []
    db._conn.set_trace_callback(statements.append)
    headers = _Headers()
    try:
        with installed(engine):
            for i in range(DISPATCHES):
                await _dispatch(surface, answer, i, headers, tool_dispatcher)
    finally:
        db._conn.set_trace_callback(None)
    assert wiring.current() is None, "the test left an engine installed"
    counts = _table_counts(db)

    if mode == "off":
        assert transactions == [], f"mode off opened {len(transactions)} durable transaction(s)"
        assert statements == [], f"mode off ran SQL on the platform database: {statements[:5]}"
        assert headers.reads == [], f"mode off read request headers: {headers.reads}"
        assert counts == dict.fromkeys(DURABLE_TABLES, 0), f"mode off wrote durable rows: {counts}"
        return

    assert len(transactions) == 2 * DISPATCHES, (
        f"{mode} {surface}: {len(transactions)} transactions for {DISPATCHES} dispatches, "
        f"expected 2 each (open, finish)")
    assert set(transactions) == {mode == "on"}, (
        f"{mode}: transactions taken with wait={sorted(set(transactions))}; shadow never waits, "
        "on waits like any platform write")
    runs = [dict(r) for r in db.fetchall_sync("SELECT * FROM workflow_runs")]
    assert len(runs) == DISPATCHES and {r["state"] for r in runs} == {"COMPLETE"}, runs
    assert counts["workflow_steps"] == 3 * DISPATCHES, (
        f"{counts['workflow_steps']} steps; each run should have start, call, return")
    publishes = answer is SETTLED and surface != "tool_twin_signing"
    assert counts["outbox"] == (2 * DISPATCHES if publishes else 0), (
        f"{mode} {surface} {answer['status']}: {counts['outbox']} outbox rows")
    keyed = surface == "execute_keyed"
    assert counts["idempotency_keys"] == (DISPATCHES if keyed else 0), (
        f"{counts['idempotency_keys']} keys bound for {DISPATCHES} {surface} dispatches")
    assert headers.reads == (["Idempotency-Key"] * DISPATCHES if keyed else []), headers.reads


@pytest.mark.parametrize("mode", ("shadow", "on"))
async def test_a_call_that_is_not_journaled_takes_no_transaction(
        mode, db, transactions, tool_dispatcher):
    """A read-only dispatcher name and a twin read cost the engine nothing."""
    from runtime.durable.wiring import DurableEngine

    sys.path.insert(0, "tests")
    from test_durable_harness import installed

    read_name = next(a for a in sorted(ACTION_MAP) if a not in _STATE_MODIFYING_ACTIONS)
    d = stand_in_dispatcher()
    td = tool_dispatcher

    async def nft(**kwargs):
        return {"owner": WALLET}
    td.register("nft", nft, {"name": "nft"})
    with installed(DurableEngine(db, mode=mode, attestations=_Chain())):
        await d.execute(read_name, params={"to": WALLET}, caller_identity=WALLET)
        outcome = await td.dispatch("nft", dict(TWIN_READ), agent_name="neo",
                                    caller_identity=WALLET, caller_source="session")
    assert outcome.ok, outcome
    assert transactions == [], (
        f"{mode}: {len(transactions)} transaction(s) for a read ({read_name}) and a twin read")
    assert _table_counts(db) == dict.fromkeys(DURABLE_TABLES, 0), _table_counts(db)
