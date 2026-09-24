"""G7 — the crash matrix for durable execution (engines Phase 2), cells X1, X2,
X6 and X7 of the packet's Section 9 §1.5.

A crash is modelled the way a kill leaves the platform database: at the
injection point the committed state of the file is copied through a connection
of its own (``snapshot``), and from that instant nothing the old process goes on
to do counts — its effects on the world are dropped (``World.alive``) and its
later writes stay in a file nobody reads again. Then a FRESH engine opens a copy
of the snapshot, after the lease has run out, and recovers; a second fresh
engine recovers a second copy; and the first continues — the loop delivers
what it owes, and for X1 the client replays its request with the same key.

Each injection must satisfy the packet's four proofs, as this phase can hold
them:

* L — no lost workflow: every run the old process recorded is still there, and
  a request whose effect happened has a run that says its call began;
* U — no unauthorized continuation: recovery itself performs no effect, and the
  replay that continues an X1 request goes through the gate again. NARROWER
  THAN THE PACKET'S U (14 §1.5: "recovery re-checks the authorization fact and
  Morpheus invariants before any further effect; a run whose decision has
  expired stops"). In this phase no decision carries an expiry to re-check —
  the gate's decision is an id on the run (``decision_ref``), and a decision
  row with ``expires_at`` is Phase 4's (14 §1.5 X3, X10) — and the one further
  effect a recovered engine makes, the attestation of a run that completed, is
  sent without asking the gate again, as the dispatcher's legacy path sends it;
* D — no duplicate effect: the service's effect, the attestation and the feed
  entry each happened at most once for the request;
* R — deterministic recovery: the two recoveries reach the same state.

X6.W3 holds an attestation whose sending was cut off after the chain accepted
it, for a person; the packet's rule there — a reconciler reads the attestation
back by its UID — needs the evidence side's chain reader, which this phase does
not build. It never sends one twice either way.

X1 is measured on ``POST /bridge/v1/action`` only: the ``/api/v1`` service
routes read no Idempotency-Key and are not journaled (the README's "Not covered
yet").

``SEEDS_PER_CELL`` seeded injections per cell (100, the packet's G7 minimum)
run in-process at every commit. ``test_a_real_kill_leaves_what_the_model_says``
also kills a real child process with ``os._exit`` at the X2, X6 and X7 points
and applies the same proofs to what it left. ``DURABLE_BASELINE=write`` writes
the pass counts to ``tests/baseline/durable_crash_matrix.json``.
"""

from __future__ import annotations

import asyncio
import json
import os
import random
import subprocess
import sys
import time
from pathlib import Path

import pytest

sys.path.insert(0, "tests")

from aiohttp.test_utils import TestClient, TestServer  # noqa: E402

from durable_harness import (  # noqa: E402
    BROADCAST, REFUSED, SETTLED, WALLET, OTHER_WALLET, STATE_ACTIONS, Clock, FakeEAS, FeedSpy,
    World, copy_file, database, feed_rows, gateway, measured_where, projection, snapshot,
    stub_dispatcher,
)
from runtime.durable import journal, keys, outbox, wiring  # noqa: E402

ROOT = Path(__file__).resolve().parent.parent
ARTEFACT = ROOT / "tests" / "baseline" / "durable_crash_matrix.json"
WRITE = os.environ.get("DURABLE_BASELINE", "").strip().lower() == "write"
SEEDS_PER_CELL = 100
T0 = 1_800_000_000.0
LATER = T0 + max(outbox.LEASE_S, journal.ABANDONED_AFTER_S) + 60

#: cell -> the kill points drawn from for it
CELLS: dict[str, tuple[str, ...]] = {
    "X1.W2": ("gate", "claimed", "in_call_before_effect", "in_call_after_effect"),
    "X1.W4": ("before_answer_recorded", "after_answer_recorded"),
    "X2.W1": ("in_call_before_effect",),
    "X2.W2": ("in_call_after_effect",),
    "X2.W4": ("after_terminal",),
    "X6.W1": ("after_terminal",),
    "X6.W2": ("attest_before_accept",),
    "X6.W3": ("attest_after_accept",),
    "X7.W1": ("after_terminal",),
    "X7.W2": ("feed_before_insert", "feed_after_insert"),
}
_SHAPES = {"settled": SETTLED, "broadcast": BROADCAST, "refused": REFUSED}
#: X6 and X7 are about the attestation and the feed entry, which only a settled
#: answer produces.
_SETTLED_ONLY = ("X6", "X7")
#: The attestation service's own actions answer through a stub that does not
#: take the drawn shape; they are covered by the off/shadow measurement.
_CORPUS = [a for a in STATE_ACTIONS if not a.endswith("attestation") and a != "batch_attest"]


class Killer:
    """Copies the database at the injection point, once, and from then on the
    world ignores the old process."""

    def __init__(self, world: World, db_path: Path, dest: Path, point: str) -> None:
        self.world, self.db_path, self.dest, self.point = world, db_path, dest, point
        self.fired = False

    def at(self, point: str) -> None:
        if self.fired or point != self.point:
            return
        snapshot(self.db_path, self.dest)
        self.world.alive = False
        self.fired = True


def _case(cell: str, seed: int) -> dict:
    rng = random.Random(f"{cell}:{seed}")
    shape = "settled" if cell.startswith(_SETTLED_ONLY) else rng.choice(sorted(_SHAPES))
    return {
        "action": rng.choice(_CORPUS),
        "shape": shape,
        "actor": rng.choice([WALLET, OTHER_WALLET, ""]),
        "params": {"to": WALLET, "amount": rng.randint(1, 10 ** 6), "marker": seed},
        "point": rng.choice(CELLS[cell]),
        "key": f"crash-{cell}-{seed}",
    }


def _recovered(snap: Path, scratch: Path, world: World, name: str):
    """A fresh process over a copy of *snap*: a new database handle, a new
    engine whose clock is past every lease, and its recovery, run twice."""
    db = database(copy_file(snap, scratch / f"{name}.db"))
    eas = FakeEAS(world)
    feed = FeedSpy(db, world)
    from runtime.blockchain.services.attestation import batch_processor as bp
    eng = wiring.DurableEngine(
        db, mode="on", canary="state_modifying", clock=Clock(LATER),
        deliverers={"attest": outbox.attestation_deliverer(bp.BatchProcessor({})),
                    "feed": outbox.feed_deliverer(feed, db)})
    eng.maintain()
    eng.maintain()
    return db, eng, eas, feed


def _check(cell: str, case: dict, world: World, effects_at_kill: int, snap: Path,
           scratch: Path, continued_db, extra: dict) -> list[str]:
    """The four proofs over one injection. Returns what failed."""
    failures: list[str] = []
    services = world.count("service")
    attests = world.count("attest")
    feed = len(feed_rows(continued_db))
    # D
    if services > 1:
        failures.append(f"D: the service acted {services} times")
    if attests > 1:
        failures.append(f"D: {attests} attestations")
    if feed > 1:
        failures.append(f"D: {feed} feed entries")
    # L
    before = database(copy_file(snap, scratch / "before.db"))
    recorded = {r[0] for r in before.fetchall_sync("SELECT run_id FROM workflow_runs")}
    after = {r[0]: r[1] for r in continued_db.fetchall_sync(
        "SELECT run_id, state FROM workflow_runs")}
    if not recorded <= set(after):
        failures.append("L: a recorded run is gone")
    if services and not any(s in (journal.RUNNING, journal.COMPLETE, journal.FAIL)
                            for s in after.values()):
        failures.append("L: the service acted and no run says its call began")
    # U
    if extra.get("effects_after_recovery", effects_at_kill) != effects_at_kill:
        failures.append("U: recovery itself performed an effect")
    if extra.get("replay_gated") is False:
        failures.append("U: the replay was not gated")
    # R
    if extra["projection_a"] != extra["projection_b"]:
        failures.append("R: two recoveries disagree")
    # What each cell must also show.
    settled = case["shape"] == "settled"
    point = case["point"]
    if cell.startswith("X6") or cell.startswith("X7") or cell == "X2.W4":
        runs = [s for s in after.values()]
        if runs != [journal.COMPLETE if case["shape"] != "refused" else journal.FAIL]:
            failures.append(f"a terminal run was expected, found {runs}")
    if cell in ("X6.W1", "X2.W4") and settled and attests != 1:
        failures.append(f"the owed attestation was delivered {attests} times, not once")
    if cell == "X6.W2" and attests != 0:
        failures.append("an interrupted attestation was sent again")
    if cell == "X6.W3" and attests != 1:
        failures.append("an accepted attestation was lost or doubled")
    if cell.startswith("X7") and settled and feed != 1:
        failures.append(f"the feed entry landed {feed} times, not once")
    if cell == "X1.W2" and point in ("gate", "claimed") and services != 1:
        failures.append("a request that never reached its service did not run exactly once "
                        "on replay")
    if cell == "X1.W4" and services != 1:
        failures.append("a completed request did not act exactly once")
    # The packet's X1.W4: "response lost after commit: replay returns recorded
    # outcome" — at both points, because the run's end records the answer.
    if cell == "X1.W4" and not extra.get("replayed_the_first_answer"):
        failures.append("the recorded answer was not returned")
    before._conn.close()
    return failures


async def _inject_dispatch(cell: str, seed: int, scratch: Path, monkeypatch) -> list[str]:
    """X2, X6, X7: a state-modifying dispatch (the ReAct / hand-off path)."""
    case = _case(cell, seed)
    world = World()
    path = scratch / "live.db"
    db = database(path)
    killer = Killer(world, path, scratch / "snap.db", case["point"])
    from runtime.blockchain.services.attestation import batch_processor as bp
    eas = FakeEAS(world, on_call=lambda _k: killer.at("attest_before_accept"),
                  after_call=lambda _k: killer.at("attest_after_accept"))
    monkeypatch.setattr(bp, "_eas_client_for", lambda _cfg: eas, raising=False)
    feed = FeedSpy(db, world)
    feed.before_insert = lambda: killer.at("feed_before_insert")
    feed.after_insert = lambda: killer.at("feed_after_insert")
    eng = wiring.DurableEngine(
        db, mode="on", canary="state_modifying", clock=Clock(T0),
        deliverers={"attest": outbox.attestation_deliverer(bp.BatchProcessor({})),
                    "feed": outbox.feed_deliverer(feed, db)})
    previous = wiring.install(eng)
    try:
        async def during(when, _kwargs):
            killer.at("in_call_before_effect" if when == "before" else "in_call_after_effect")
        d = stub_dispatcher(world, _SHAPES[case["shape"]], feed=feed, during=during)
        await d.execute(case["action"], params=dict(case["params"]),
                        caller_identity=case["actor"])
        killer.at("after_terminal")
        await eng.loop.tick()
    finally:
        wiring.install(previous)
    assert killer.fired, (cell, case)
    effects_at_kill = len(world.effects)
    world.alive = True
    snap = scratch / "snap.db"
    db_a, eng_a, eas_a, _ = _recovered(snap, scratch, world, "rec_a")
    db_b, _eng_b, _, _ = _recovered(snap, scratch, World(), "rec_b")
    extra = {"projection_a": projection(db_a), "projection_b": projection(db_b),
             "effects_after_recovery": len(world.effects)}
    monkeypatch.setattr(bp, "_eas_client_for", lambda _cfg: eas_a, raising=False)
    for _ in range(3):
        await eng_a.loop.tick()
    failures = _check(cell, case, world, effects_at_kill, snap, scratch, db_a, extra)
    for handle in (db, db_a, db_b):
        await handle.close()
    return failures


async def _inject_bridge(cell: str, seed: int, scratch: Path, client, server, monkeypatch,
                         real_gate) -> list[str]:
    """X1: POST /bridge/v1/action with an Idempotency-Key; the client replays."""
    import gateway.security_gate as security_gate
    case = _case(cell, seed)
    world = World()
    path = scratch / "live.db"
    db = database(path)
    killer = Killer(world, path, scratch / "snap.db", case["point"])
    from runtime.blockchain.services.attestation import batch_processor as bp
    monkeypatch.setattr(bp, "_eas_client_for", lambda _cfg: FakeEAS(world), raising=False)
    eng = wiring.DurableEngine(db, mode="on", canary="state_modifying", clock=Clock(T0),
                               deliverers={"attest": outbox.attestation_deliverer(
                                   bp.BatchProcessor({}))})
    original_finish = eng.bridge_finish

    def finish(claim, *, status, body):
        killer.at("before_answer_recorded")
        original_finish(claim, status=status, body=body)
        killer.at("after_answer_recorded")
    eng.bridge_finish = finish
    gate_calls = {"n": 0}

    async def gate(*a, **k):
        gate_calls["n"] += 1
        killer.at("gate")
        return await real_gate(*a, **k)
    monkeypatch.setattr(security_gate, "gate_action", gate)

    async def during(when, _kwargs):
        killer.at("in_call_before_effect" if when == "before" else "in_call_after_effect")
    body = {"action": case["action"], "params": dict(case["params"])}
    headers = {"Idempotency-Key": case["key"]}
    previous = wiring.install(eng)
    try:
        server.service_dispatcher = stub_dispatcher(
            world, _SHAPES[case["shape"]], during=during,
            get_hook=lambda name: killer.at("claimed") if name != "attestation" else None)
        first = await client.post("/bridge/v1/action", json=body, headers=headers)
        first_status = first.status
    finally:
        wiring.install(previous)
    assert killer.fired, (cell, case)
    effects_at_kill = len(world.effects)
    world.alive = True
    snap = scratch / "snap.db"
    db_a, eng_a, eas_a, _ = _recovered(snap, scratch, world, "rec_a")
    db_b, _eng_b, _, _ = _recovered(snap, scratch, World(), "rec_b")
    extra = {"projection_a": projection(db_a), "projection_b": projection(db_b),
             "effects_after_recovery": len(world.effects)}
    monkeypatch.setattr(bp, "_eas_client_for", lambda _cfg: eas_a, raising=False)
    killer.point = None
    previous = wiring.install(eng_a)
    try:
        server.service_dispatcher = stub_dispatcher(world, _SHAPES[case["shape"]])
        gated_before = gate_calls["n"]
        resp = await client.post("/bridge/v1/action", json=body, headers=headers)
        extra["replay_status"] = resp.status
        extra["replayed_the_first_answer"] = (
            resp.status == first_status and resp.headers.get("Idempotent-Replayed") == "true")
        extra["replay_gated"] = gate_calls["n"] == gated_before + 1
        if resp.status not in (200, 409, 503):
            extra["unexpected_status"] = resp.status
        for _ in range(3):
            await eng_a.loop.tick()
    finally:
        wiring.install(previous)
    failures = _check(cell, case, world, effects_at_kill, snap, scratch, db_a, extra)
    if "unexpected_status" in extra:
        failures.append(f"the replay answered {extra['unexpected_status']}")
    for handle in (db, db_a, db_b):
        await handle.close()
    return failures


async def run_cell(cell: str, seeds: range, scratch_root: Path, monkeypatch) -> dict:
    failures: dict[int, list[str]] = {}
    points: dict[str, int] = {}
    if cell.startswith("X1"):
        import gateway.security_gate as security_gate
        real_gate = security_gate.gate_action
        server = gateway(scratch_root / "gw")
        (scratch_root / "gw").mkdir(exist_ok=True)
        async with TestClient(TestServer(server.create_app())) as client:
            for seed in seeds:
                scratch = scratch_root / f"{cell}-{seed}"
                scratch.mkdir()
                points[_case(cell, seed)["point"]] = points.get(_case(cell, seed)["point"], 0) + 1
                found = await _inject_bridge(cell, seed, scratch, client, server, monkeypatch,
                                             real_gate)
                if found:
                    failures[seed] = found
    else:
        for seed in seeds:
            scratch = scratch_root / f"{cell}-{seed}"
            scratch.mkdir()
            points[_case(cell, seed)["point"]] = points.get(_case(cell, seed)["point"], 0) + 1
            found = await _inject_dispatch(cell, seed, scratch, monkeypatch)
            if found:
                failures[seed] = found
    return {"injections": len(seeds), "passed": len(seeds) - len(failures),
            "points": dict(sorted(points.items())), "failures": failures}


@pytest.mark.parametrize("cell", sorted(CELLS))
async def test_every_injection_in_the_cell_keeps_the_four_proofs(cell, tmp_path, monkeypatch):
    monkeypatch.delenv("MATRIX_DURABLE_MODE", raising=False)
    result = await run_cell(cell, range(SEEDS_PER_CELL), tmp_path, monkeypatch)
    assert result["failures"] == {}, result["failures"]
    assert result["passed"] == SEEDS_PER_CELL
    assert all(result["points"].get(p) for p in CELLS[cell]), (
        f"a kill point of {cell} was never drawn: {result['points']}")
    if WRITE:
        record = json.loads(ARTEFACT.read_text()) if ARTEFACT.exists() else {"cells": {}}
        record["cells"][cell] = {k: v for k, v in result.items() if k != "failures"}
        record.update(_ARTEFACT_HEADER)
        record["measured"] = measured_where()
        ARTEFACT.write_text(json.dumps(record, indent=1, sort_keys=True) + "\n", encoding="utf-8")


_ARTEFACT_HEADER = {
    "gate": "G7",
    "rule": ("100% of at least 100 seeded injections per cell keep the four proofs L, U, D, R "
             "as tests/test_durable_crash_matrix.py states them: U is narrower than the "
             "packet's (recovery performs no effect of its own and a continued X1 request is "
             "gated again; no decision in this phase carries an expiry to re-check, and the "
             "recovered engine's attestation is sent without asking the gate again, as the "
             "legacy path sends it)"),
    "scope": ("X1 is POST /bridge/v1/action only: the /api/v1 service routes read no "
              "Idempotency-Key and are not journaled. X6.W3 holds the attestation for a "
              "person; the packet's read-back by attestation UID is the evidence side's"),
    "instrument": ("tests/test_durable_crash_matrix.py: the committed state of the platform "
                   "database copied at the kill point, recovered twice by fresh engines past "
                   "every lease, then continued (outbox loop; for X1 the client's replay "
                   "under the same Idempotency-Key through POST /bridge/v1/action); a real "
                   "os._exit kill of a child process at the X2, X6 and X7 points is checked "
                   "the same way (real_kills)"),
    "cells_meaning": {
        "X1.W2": "the gateway dies mid-handler: before the key is claimed, after the claim "
                 "before the service, or inside the service before or after its effect",
        "X1.W4": "the answer is lost: after the run's terminal commit (which records the "
                 "answer computed then) before the request records the answer it sent, or "
                 "after; the replay must get the recorded answer, with the first status",
        "X2.W1": "the run is recorded and the service has not acted",
        "X2.W2": "the service acted and has not answered",
        "X2.W4": "the terminal state and the outbox rows are committed, nothing delivered",
        "X6.W1": "the attestation row exists and was not sent",
        "X6.W2": "the attestation was being sent and the chain had not accepted it",
        "X6.W3": "the chain accepted the attestation and the row was not marked",
        "X7.W1": "the feed row exists and was not delivered",
        "X7.W2": "the feed entry was being delivered, before or after the feed stored it",
    },
}


def test_the_artefact_says_every_cell_passed_all_its_injections():
    record = json.loads(ARTEFACT.read_text(encoding="utf-8"))
    assert record["gate"] == "G7" and set(record["cells"]) == set(CELLS)
    # It says what it does not prove, next to what it does.
    assert record["rule"] == _ARTEFACT_HEADER["rule"] and "narrower" in record["rule"]
    assert record["scope"] == _ARTEFACT_HEADER["scope"] and "/api/v1" in record["scope"]
    for cell, result in record["cells"].items():
        assert result["injections"] >= 100 and result["passed"] == result["injections"], cell
    kills = record["real_kills"]
    assert set(kills["cells"]) == set(REAL_KILL_POINTS)
    assert all(v["passed"] == v["runs"] >= 1 for v in kills["cells"].values())


# ── real kills ──────────────────────────────────────────────────────────────

#: cell -> the point at which the child calls os._exit
REAL_KILL_POINTS = {
    "X2.W2": "in_call_after_effect",
    "X2.W4": "after_terminal",
    "X6.W2": "attest_before_accept",
    "X6.W3": "attest_after_accept",
    "X7.W2": "feed_after_insert",
}

_CHILD = r'''
import asyncio, json, os, sys
sys.path.insert(0, "tests")
db_path, world_path, point, action = sys.argv[1:5]
from durable_harness import (SETTLED, World, FakeEAS, FeedSpy, database, stub_dispatcher,
                             Clock)
from runtime.durable import outbox, wiring
from runtime.blockchain.services.attestation import batch_processor as bp

class FileWorld(World):
    def record(self, *effect):
        with open(world_path, "a") as f:
            f.write(json.dumps(list(effect)) + "\n")
            f.flush()
            os.fsync(f.fileno())
        super().record(*effect)

def at(p):
    if p == point:
        os._exit(137)

async def main():
    world = FileWorld()
    db = database(db_path)
    eas = FakeEAS(world, on_call=lambda _k: at("attest_before_accept"),
                  after_call=lambda _k: at("attest_after_accept"))
    bp._eas_client_for = lambda _cfg: eas
    feed = FeedSpy(db, world)
    feed.after_insert = lambda: at("feed_after_insert")
    eng = wiring.DurableEngine(db, mode="on", canary="state_modifying", clock=Clock(%(T0)r),
        deliverers={"attest": outbox.attestation_deliverer(bp.BatchProcessor({})),
                    "feed": outbox.feed_deliverer(feed, db)})
    wiring.install(eng)
    async def during(when, _kwargs):
        if when == "after":
            at("in_call_after_effect")
    d = stub_dispatcher(world, SETTLED, feed=feed, during=during)
    await d.execute(action, params={"to": "0x" + "12" * 20, "amount": 7, "marker": 1})
    at("after_terminal")
    await eng.loop.tick()
    os._exit(3)   # every point above kills before this line

asyncio.run(main())
''' % {"T0": T0}


def _real_kill(cell: str, scratch: Path, action: str = "transfer_stablecoin") -> list[str]:
    path, world_path = scratch / "live.db", scratch / "world.jsonl"
    database(path)._conn.close()
    env = {k: v for k, v in os.environ.items() if not k.startswith("MATRIX_")}
    env.update(PYTHONPATH=str(ROOT), PYTHONDONTWRITEBYTECODE="1", MATRIX_LOG_LEVEL="ERROR")
    proc = subprocess.run([sys.executable, "-c", _CHILD, str(path), str(world_path),
                           REAL_KILL_POINTS[cell], action],
                          cwd=ROOT, env=env, capture_output=True, text=True, timeout=120)
    if proc.returncode != 137:
        return [f"the child exited {proc.returncode}: {proc.stderr[-1500:]}"]
    world = World()
    if world_path.exists():
        world.effects = [tuple(json.loads(line)) for line in world_path.read_text().splitlines()]
    effects_at_kill = len(world.effects)
    # What the killed process left: the file and its write-ahead log, read by a
    # connection of this process (which recovers the log) into one file.
    folded = snapshot(path, scratch / "folded.db")

    async def recover_and_continue():
        from runtime.blockchain.services.attestation import batch_processor as bp
        db_a, eng_a, eas_a, _ = _recovered(folded, scratch, world, "rec_a")
        db_b, _eng_b, _, _ = _recovered(folded, scratch, World(), "rec_b")
        extra = {"projection_a": projection(db_a), "projection_b": projection(db_b),
                 "effects_after_recovery": len(world.effects)}
        original = bp._eas_client_for
        bp._eas_client_for = lambda _cfg: eas_a
        try:
            for _ in range(3):
                await eng_a.loop.tick()
        finally:
            bp._eas_client_for = original
        case = {"shape": "settled", "point": REAL_KILL_POINTS[cell]}
        failures = _check(cell, case, world, effects_at_kill, folded, scratch, db_a, extra)
        await db_a.close()
        await db_b.close()
        return failures
    return asyncio.run(recover_and_continue())


@pytest.mark.parametrize("cell", sorted(REAL_KILL_POINTS))
def test_a_real_kill_leaves_what_the_model_says(cell, tmp_path):
    runs = 3 if WRITE else 1
    failures = []
    for i in range(runs):
        scratch = tmp_path / f"kill-{i}"
        scratch.mkdir()
        failures += _real_kill(cell, scratch)
    assert failures == []
    if WRITE:
        record = json.loads(ARTEFACT.read_text()) if ARTEFACT.exists() else {"cells": {}}
        kills = record.setdefault("real_kills", {"cells": {}})
        kills["instrument"] = ("a child process runs the dispatch and the outbox loop over the "
                               "platform database and calls os._exit(137) at the point; the "
                               "parent recovers what the file holds (with its write-ahead log) "
                               "twice and continues, and applies the same four proofs")
        kills["cells"][cell] = {"point": REAL_KILL_POINTS[cell], "runs": runs, "passed": runs}
        ARTEFACT.write_text(json.dumps(record, indent=1, sort_keys=True) + "\n", encoding="utf-8")
