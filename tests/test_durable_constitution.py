"""Engines Phase 2: the constitution durable execution was built under, pinned.

    Deterministic code owns facts; the gate owns authorization; judgments
    advise, never permit. Nothing in runtime/durable decides an outcome, grants
    an action or changes what the gate decides; a crash mid-run, a hostile
    outbox row, a replayed key or a raised sink can never duplicate or grant an
    action. Every sink gets copies, never the live dicts.

Measured against the real code — the platform ``Database`` with its
migrations, the real ``ServiceDispatcher``, the real ``DurableEngine`` and its
outbox loop, and the real gateway for the bridge — over the shared harness's
stand-ins for the services, the chain and the feed:

1. COPIES. What the outbox holds and delivers is a copy taken when the run
   ended: the caller mutating its parameters or the service's answer after the
   dispatch, or during a delivery, changes nothing delivered; a delivery
   mutating what it was handed reaches neither the caller's dicts nor the next
   attempt; the engine keeps no reference to the parameters or the answer and
   writes only digests.
2. HOSTILE ROWS. An outbox row the engine did not write for a payload it holds
   (an unknown run, a real run with a forged digest, a duplicate of a delivered
   row, a row for a FAIL run, a held row tampered with) is delivered to nobody
   and never calls a service: it is given up. Rows of its own changed by hand
   are pinned in tests/test_durable_on.py (a bound run's parameters rewritten,
   a run moved back to START); the one change no table can stand against, the
   key's own row deleted, is stated in the README, not claimed away here.
3. A RAISED SINK. ``journal.transaction`` raising at each write point (open,
   the key bind, finish, fail, abort, the key's answer, recovery, the outbox's
   claim, settle and give-up) never makes a second service call and never a
   call mode on did not record first; in shadow it never changes an answer.
4. A REPLAYED KEY never calls the service again, whatever state the first run
   is in (open, COMPLETE, FAIL, FAIL by recovery after a restart); a key given
   back with an ABORT — its first request never acted — runs exactly once more.
5. NO AUTHORITY IMPORTED. Nothing in runtime/durable imports the gate, the
   access policy, the vocabulary or a service, or calls a gate function.
6. THE GATE IS NOT BYPASSED. Through the real bridge, a request the gate blocks
   opens no run and binds no key, and a replay the gate refuses is refused.
7. The three invariant test files are byte-identical to the target branch's
   copies, wherever this runs.

Why: mode on hands the engine lifecycle authority, and these are the ways that
authority could leak into a decision it does not own — a live dict shared with
a sink, a row the loop trusts, a write that fails half way, a key that answers
for an action, an import that reaches the gate. Each is pinned from the outside.
"""
from __future__ import annotations

import ast
import asyncio
import contextlib
import copy
import gc
import hashlib
import json
import sqlite3
import subprocess
import sys
import time
import types
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest

sys.path.insert(0, "tests")

from test_durable_harness import (  # noqa: E402
    ACTION_MAP, STATE_MODIFYING, WALLET, Attestations, Boom, Clock, Effects, Feed, Services,
    bridge_like, engine, installed, open_db, open_runs, params_for, resolve_schema, rows, snapshot,
)
from test_durable_harness import dispatcher as _harness_dispatcher  # noqa: E402
from runtime.durable import journal, keys, outbox, wiring  # noqa: E402
from runtime.durable.wiring import DurableEngine  # noqa: E402

REPO = Path(__file__).resolve().parents[1]
DURABLE_DIR = REPO / "runtime" / "durable"

ACTION = "transfer_stablecoin"        # settles
RAISES = "add_liquidity"              # its service raises
UNAVAILABLE = "appeal_dispute"        # its service is not registered: ABORT before the call
DURABLE_TABLES = ("workflow_runs", "workflow_steps", "outbox", "idempotency_keys")
SCOPE = f"operator|{WALLET}"          # the scope bridge_like keys under

assert {ACTION, RAISES, UNAVAILABLE} <= set(STATE_MODIFYING)
assert len({ACTION_MAP[a][0] for a in (ACTION, RAISES, UNAVAILABLE)}) == 3


@pytest.fixture(autouse=True)
def _no_mode_env(monkeypatch):
    monkeypatch.delenv("MATRIX_DURABLE_MODE", raising=False)


@pytest.fixture(autouse=True)
def _engine_restored():
    """Whatever engine was installed before a test is installed after it."""
    with installed(wiring.current()):
        yield


@pytest.fixture
async def db(tmp_path):
    database = open_db(tmp_path / "constitution.db")
    yield database
    await database.close()


@pytest.fixture
def clock() -> Clock:
    return Clock()


# ── helpers ─────────────────────────────────────────────────────────────────

def dispatcher(effects: Effects, services: Services | None = None, *,
               unavailable: tuple[str, ...] = ()):
    """The harness's dispatcher, with a legacy attestation service that records
    ``("attest", action)`` and the services named in *unavailable* missing from
    the registry (the dispatcher's pre-call ``service_unavailable`` refusal)."""
    d = _harness_dispatcher(effects, services)
    inner = d._get_registry()

    async def attest(**kwargs):
        effects.log.append(("attest", kwargs.get("data", {}).get("action")))
        return {"status": "queued"}

    def get(name):
        if name in unavailable:
            raise KeyError(f"service {name!r} is not registered")
        if name == "attestation":
            return SimpleNamespace(attest=attest, _resolve_schema=resolve_schema)
        return inner.get(name)
    registry = SimpleNamespace(get=get)
    d._get_registry = lambda: registry
    return d


class Calls:
    """Every service call, counted at its start (a call that raises leaves no
    effect in the harness's log), and — in mode on — whether a RUNNING run with
    this call's action and parameter digest, not already claimed by another
    call, was on record when it began."""

    def __init__(self, services: Services, db, *, check_recorded: bool) -> None:
        self.db = db
        self.check_recorded = check_recorded
        self.made: list[tuple[str, object]] = []
        self.unrecorded: list[tuple[str, object]] = []
        self._claimed: set[str] = set()
        services.before_effect = self

    def __call__(self, action, params) -> None:
        self.made.append((action, params.get("marker")))
        if not self.check_recorded:
            return
        found = [r[0] for r in self.db.fetchall_sync(
            "SELECT run_id FROM workflow_runs WHERE state = 'RUNNING' AND action = ? "
            "AND params_digest = ?", (action, journal.digest(params)))
            if r[0] not in self._claimed]
        if not found:
            self.unrecorded.append((action, params.get("marker")))
        else:
            self._claimed.add(found[0])

    def count(self, marker) -> int:
        return sum(1 for _a, m in self.made if m == marker)


async def settle() -> None:
    """Let the tasks a dispatch created (the legacy feed publish) run."""
    for _ in range(3):
        await asyncio.sleep(0)


def normalised(answer: str | None):
    if answer is None:
        return None
    envelope = json.loads(answer)
    if isinstance(envelope, dict):
        envelope.pop("elapsed_ms", None)
    return envelope


def steps(db, run_id: str) -> list[tuple[str, str, str]]:
    return [(s["name"], s["state"], s["detail"]) for s in journal.get_steps(db, run_id)]


def plant_row(db, *, run_id: str, kind: str, digest: str, next_at: float) -> int:
    """An outbox row written by hand — by nobody this engine knows."""
    db.execute_sync("INSERT INTO outbox (run_id, kind, payload_digest, attempts, next_at, done_at) "
                    "VALUES (?, ?, ?, 0, ?, NULL)", (run_id, kind, digest, next_at))
    return int(db.fetchall_sync("SELECT MAX(id) FROM outbox")[0][0])


def plant_abandoned_start(db, *, run_id: str, action: str, marker, client_key: str,
                          at: float) -> str:
    """A run another process opened in START, its key bound to it, and left."""
    key = keys.scoped(wiring.BRIDGE_ACTION, SCOPE, client_key)
    db.execute_sync(
        "INSERT INTO workflow_runs (run_id, key, action, service, actor_hash, params_digest, "
        "state, decision_ref, started_at, terminal_at) VALUES (?, ?, ?, ?, ?, ?, 'START', '', ?, "
        "NULL)", (run_id, key, action, ACTION_MAP[action][0], journal.actor_hash(WALLET),
                  journal.digest(params_for(action, marker)), at))
    db.execute_sync("INSERT INTO workflow_steps (run_id, seq, name, state, detail, at) "
                    "VALUES (?, 1, 'start', 'opened', '', ?)", (run_id, at))
    db.execute_sync("INSERT INTO idempotency_keys (key, run_id, response_digest, created_at) "
                    "VALUES (?, ?, '', ?)", (key, run_id, at))
    return key


class RecordingAttestations(Attestations):
    """The chain, keeping a deep copy of every attestation as it arrived, before
    ``on_receive`` (a hook the test sets) runs."""

    def __init__(self, effects: Effects) -> None:
        super().__init__(effects)
        self.received: list[dict] = []
        self.on_receive = None

    async def _submit_batch(self, batch):
        for att in batch:
            self.received.append(copy.deepcopy(att))
            if self.on_receive is not None:
                self.on_receive(att)
        return await super()._submit_batch(batch)


class RecordingFeed(Feed):
    """The feed engine, keeping a deep copy of every entry as it arrived."""

    def __init__(self, effects: Effects) -> None:
        super().__init__(effects)
        self.received: list[dict] = []
        self.on_receive = None

    async def ingest(self, **kwargs):
        self.received.append(copy.deepcopy(kwargs))
        if self.on_receive is not None:
            self.on_receive(kwargs)
        return await super().ingest(**kwargs)


class ReturnedDicts:
    """The service for ACTION, returning a fresh nested answer each call and
    keeping every answer it returned (the live dict the dispatcher got)."""

    def __init__(self, effects: Effects) -> None:
        self.effects = effects
        self.returned: list[dict] = []

    async def __call__(self, **params):
        self.effects.log.append(("service", ACTION, params.get("marker")))
        answer = {"status": "success", "tx_hash": "0x" + "22" * 32, "settled": True,
                  "legs": [{"hop": 1, "note": "original"}]}
        self.returned.append(answer)
        return answer


def copies_dispatcher(effects: Effects, attestations: RecordingAttestations):
    d = dispatcher(effects)
    service = ReturnedDicts(effects)
    registry = d._get_registry()
    target, method = ACTION_MAP[ACTION]

    def get(name):
        if name == target:
            return SimpleNamespace(**{method: service})
        return registry.get(name)
    fixed = SimpleNamespace(get=get)
    d._get_registry = lambda: fixed
    feed = RecordingFeed(effects)
    d._feed_engine = feed
    return d, service, feed


def nested_params(marker) -> dict:
    return {"to": WALLET, "amount": 5, "marker": marker,
            "memo": {"note": "original-memo-7f3a"}, "tags": ["first", {"deep": "original"}]}


# ── 1. copies, never the live dicts ─────────────────────────────────────────

async def test_what_the_outbox_delivers_is_unchanged_by_the_callers_mutations_after_dispatch(
        db, clock):
    effects = Effects()
    attestations = RecordingAttestations(effects)
    d, service, feed = copies_dispatcher(effects, attestations)
    params = nested_params(1)
    original = copy.deepcopy(params)
    eng = DurableEngine(db, mode="on", clock=clock, attestations=attestations)
    with installed(eng):
        answer = await bridge_like(d, ACTION, params, key="copies-1")
        # The caller and the service's answer both change after the dispatch.
        params["memo"]["note"] = "mutated after the answer"
        params["tags"][1]["deep"] = "mutated"
        params["amount"] = 999
        params["injected"] = True
        service.returned[0]["tx_hash"] = "0x" + "ee" * 32
        service.returned[0]["legs"][0]["note"] = "mutated"
        await eng.loop.tick()
    assert json.loads(answer)["status"] == "ok", answer
    assert len(feed.received) == 1 and len(attestations.received) == 1, (
        f"expected one feed entry and one attestation, got {feed.received} "
        f"and {attestations.received}")
    entry = feed.received[0]
    assert entry["detail"]["params"] == original, (
        f"the feed entry saw the caller's later mutation: {entry['detail']['params']}")
    assert entry["tx_hash"] == "0x" + "22" * 32, (
        f"the feed entry saw a mutation of the service's answer: {entry['tx_hash']}")
    data = attestations.received[0]["data"]
    expected_hash = str(hash(json.dumps(original, sort_keys=True, default=str)))
    assert data["params_hash"] == expected_hash, (
        "the attestation was built over the caller's mutated parameters, not the ones "
        "the action ran with")
    assert (data["action"], data["actor"]) == (ACTION, WALLET), data


async def test_the_callers_mutations_during_a_delivery_never_reach_a_later_delivery(db, clock):
    """The attestation row is delivered first; while the chain holds it the
    caller mutates its parameters and the service's answer. The feed entry
    delivered after it carries the originals."""
    effects = Effects()
    attestations = RecordingAttestations(effects)
    d, service, feed = copies_dispatcher(effects, attestations)
    params = nested_params(2)
    original = copy.deepcopy(params)

    def mutate_the_callers_dicts(_att):
        params["memo"]["note"] = "mutated during the attestation"
        params["tags"].append("appended")
        service.returned[0]["tx_hash"] = "0x" + "ee" * 32
    attestations.on_receive = mutate_the_callers_dicts
    eng = DurableEngine(db, mode="on", clock=clock, attestations=attestations)
    with installed(eng):
        await bridge_like(d, ACTION, params, key="copies-2")
        await eng.loop.tick()
    assert [e[0] for e in effects.log if e[0] in ("attest_sent", "feed")] == [
        "attest_sent", "feed"], f"the rows were not delivered in the order written: {effects.log}"
    (entry,) = feed.received
    assert entry["detail"]["params"] == original and entry["tx_hash"] == "0x" + "22" * 32, (
        f"a feed entry delivered after the caller's mutation carried it: {entry}")


async def test_a_delivery_that_mutates_what_it_was_handed_never_reaches_the_callers_dicts(
        db, clock):
    effects = Effects()
    attestations = RecordingAttestations(effects)
    d, service, feed = copies_dispatcher(effects, attestations)
    params = nested_params(3)
    original = copy.deepcopy(params)

    def chain_mutates(att):
        att["data"]["action"] = "rewritten by the chain"
        att["data"]["actor"] = "0x" + "99" * 20

    def feed_mutates(kwargs):
        kwargs["detail"]["params"]["memo"]["note"] = "rewritten by the feed"
        kwargs["detail"]["params"]["tags"][1]["deep"] = "rewritten by the feed"
        kwargs["detail"]["service"] = "rewritten"
    attestations.on_receive = chain_mutates
    feed.on_receive = feed_mutates
    eng = DurableEngine(db, mode="on", clock=clock, attestations=attestations)
    with installed(eng):
        answer = await bridge_like(d, ACTION, params, key="copies-3")
        first = copy.deepcopy(service.returned[0])
        await eng.loop.tick()
    assert params == original, f"a delivery reached the caller's parameters: {params}"
    assert service.returned[0] == first, (
        f"a delivery reached the service's answer: {service.returned[0]}")
    replayed = json.loads(answer)["result"]
    assert replayed["legs"] == [{"hop": 1, "note": "original"}], replayed


async def test_a_retried_attestation_is_the_payload_held_not_what_the_last_attempt_did_to_it(
        db, clock):
    """The first attempt is not confirmed (the chain answers ``failed``), so the
    row is retried after its backoff. The chain rewrote the attestation it was
    handed on the first attempt; the second attempt must carry the payload the
    outbox held — with the digest the row was written under — not the rewrite."""
    effects = Effects()
    attestations = RecordingAttestations(effects)
    attestations.answers = [{"status": "failed"}]
    d, _service, _feed = copies_dispatcher(effects, attestations)
    rewritten: list[int] = []

    def chain_mutates(att):
        if not rewritten:
            rewritten.append(1)
            att["data"]["action"] = "rewritten by the chain"
            att["data"]["actor"] = "0x" + "99" * 20
            att["recipient"] = "0x" + "98" * 20
    attestations.on_receive = chain_mutates
    eng = DurableEngine(db, mode="on", clock=clock, attestations=attestations)
    with installed(eng):
        await bridge_like(d, ACTION, nested_params(4), key="copies-4")
        await eng.loop.tick()
        clock.advance(outbox.RETRY_CAP_S)
        await eng.loop.tick()
    assert len(attestations.received) == 2, (
        f"expected a first attempt and one retry, got {len(attestations.received)}")
    first, second = (dict(a) for a in attestations.received)
    first.pop("id"), second.pop("id")
    first.pop("queued_at"), second.pop("queued_at")
    assert second == first, (
        "the retried attestation carries what the chain did to the first attempt's copy, not "
        f"the payload the outbox held under its digest:\n first  {first}\n second {second}")


@pytest.mark.parametrize("mode", ["on", "shadow"])
async def test_the_engine_keeps_no_reference_to_the_parameters_or_the_answer(mode, db, clock):
    effects = Effects()
    attestations = RecordingAttestations(effects)
    d, service, _feed = copies_dispatcher(effects, attestations)
    params = nested_params(5)
    eng = DurableEngine(db, mode=mode, clock=clock, attestations=attestations)
    with installed(eng):
        await bridge_like(d, ACTION, params, key="raw-client-key-5c1e")
        await settle()
        live = {id(params), id(params["memo"]), id(params["tags"]), id(params["tags"][1])}
        live |= {id(service.returned[0]), id(service.returned[0]["legs"]),
                 id(service.returned[0]["legs"][0])}
        found_before = _reachable_ids(eng) & live
        await eng.loop.tick()
        found_after = _reachable_ids(eng) & live
    assert not found_before and not found_after, (
        f"the engine holds a live dict of the caller's or the service's "
        f"({len(found_before)} before delivery, {len(found_after)} after)")
    written = json.dumps({t: rows(db, t) for t in DURABLE_TABLES}, default=str)
    for raw in (WALLET, "original-memo-7f3a", "raw-client-key-5c1e", "0x" + "22" * 32):
        assert raw not in written, f"a raw value reached the durable tables: {raw!r}"
    assert rows(db, "workflow_runs"), "no run was written"


def _reachable_ids(root) -> set[int]:
    """Ids of every object reachable from *root*, not following modules,
    classes or a module's globals (which reach everything in the process)."""
    module_dicts = {id(vars(m)) for m in list(sys.modules.values()) if m is not None}
    seen: set[int] = set()
    stack = [root]
    while stack:
        obj = stack.pop()
        if id(obj) in seen:
            continue
        seen.add(id(obj))
        if isinstance(obj, (types.ModuleType, type)) or id(obj) in module_dicts:
            continue
        stack.extend(gc.get_referents(obj))
    return seen


# ── 2. a hostile outbox row is never delivered ──────────────────────────────

async def test_a_hostile_outbox_row_is_given_up_never_delivered_and_never_calls_a_service(
        db, clock):
    effects = Effects()
    services = Services(effects)
    services.answers[RAISES] = Boom("the stand-in service failed")
    calls = Calls(services, db, check_recorded=True)
    d = dispatcher(effects, services)
    eng = engine(db, "on", clock, effects)
    with installed(eng):
        await bridge_like(d, ACTION, params_for(ACTION, 1), key="real-1")
        await bridge_like(d, RAISES, params_for(RAISES, 2), key="real-2")
        await eng.loop.tick()
        runs = {r["action"]: r for r in rows(db, "workflow_runs")}
        complete, failed = runs[ACTION], runs[RAISES]
        assert (complete["state"], failed["state"]) == (journal.COMPLETE, journal.FAIL), runs
        delivered = {r["kind"]: r for r in rows(db, "outbox") if r["done_at"] is not None}
        assert set(delivered) == {"attest", "feed"}, rows(db, "outbox")
        before = list(effects.log)

        now = clock.now
        hostile = {
            "unknown run": plant_row(db, run_id="run_" + "0" * 32, kind="attest",
                                     digest=delivered["attest"]["payload_digest"], next_at=now),
            "forged digest": plant_row(db, run_id=complete["run_id"], kind="attest",
                                       digest="f" * 64, next_at=now),
            "duplicate of a delivered row": plant_row(
                db, run_id=complete["run_id"], kind="feed",
                digest=delivered["feed"]["payload_digest"], next_at=now),
            "a FAIL run's row": plant_row(db, run_id=failed["run_id"], kind="attest",
                                          digest=delivered["attest"]["payload_digest"],
                                          next_at=now),
        }
        await eng.loop.tick()
        by_id = {r["id"]: r for r in rows(db, "outbox")}
        for what, row_id in hostile.items():
            row = by_id[row_id]
            assert row["done_at"] is None and row["attempts"] == 0, (
                f"{what}: a row this process does not hold was taken: {row}")
        clock.advance(journal.ABANDONED_AFTER_S + 1)
        for _ in range(3):
            await eng.loop.tick()
    by_id = {r["id"]: r for r in rows(db, "outbox")}
    for what, row_id in hostile.items():
        row = by_id[row_id]
        assert (row["done_at"], row["next_at"], row["attempts"]) == (None, None, 0), (
            f"{what}: not given up (or tried) once due for the window: {row}")
    assert effects.log == before, (
        f"a hostile row made an effect: {effects.log[len(before):]}")
    assert calls.made == [(ACTION, 1), (RAISES, 2)] and not calls.unrecorded, calls.made
    for run in (complete, failed):
        given_up = [s for s in steps(db, run["run_id"]) if s[1] == outbox.GIVEN_UP]
        assert given_up and all(s[2] == "payload_not_held" for s in given_up), (
            f"run {run['action']}: the given-up rows are not on its steps: "
            f"{steps(db, run['run_id'])}")
    states = {r["run_id"]: r["state"] for r in rows(db, "workflow_runs")}
    assert states == {complete["run_id"]: journal.COMPLETE, failed["run_id"]: journal.FAIL}, (
        f"a hostile row changed a run, or made one: {states}")


async def test_a_held_row_tampered_with_or_whose_run_is_not_complete_is_given_up_at_once(
        db, clock):
    effects = Effects()
    services = Services(effects)
    calls = Calls(services, db, check_recorded=True)
    d = dispatcher(effects, services)
    eng = engine(db, "on", clock, effects)
    with installed(eng):
        await bridge_like(d, ACTION, params_for(ACTION, 1), key="tamper-1")
        await bridge_like(d, ACTION, params_for(ACTION, 2), key="tamper-2")
        first, second = sorted(rows(db, "workflow_runs"), key=lambda r: r["started_at"])
        if first["params_digest"] != journal.digest(params_for(ACTION, 1)):
            first, second = second, first
        tampered = [r["id"] for r in rows(db, "outbox")
                    if r["run_id"] == first["run_id"] and r["kind"] == "attest"]
        db.execute_sync("UPDATE outbox SET payload_digest = ? WHERE id = ?", ("f" * 64, tampered[0]))
        db.execute_sync("UPDATE workflow_runs SET state = 'FAIL' WHERE run_id = ?",
                        (second["run_id"],))
        await eng.loop.tick()
        await eng.loop.tick()
    outcome = {(r["run_id"], r["kind"]): r for r in rows(db, "outbox")}
    assert outcome[(first["run_id"], "attest")]["done_at"] is None \
        and outcome[(first["run_id"], "attest")]["next_at"] is None, (
            f"a row whose digest was forged was not given up: {outcome}")
    assert outcome[(first["run_id"], "feed")]["done_at"] is not None, (
        "the untouched row of the same run was not delivered")
    for kind in ("attest", "feed"):
        row = outcome[(second["run_id"], kind)]
        assert row["done_at"] is None and row["next_at"] is None, (
            f"a row whose run is not COMPLETE was not given up: {row}")
    assert effects.count("attest_sent") == 0 and effects.count("feed") == 1, (
        f"a tampered row was delivered: {effects.log}")
    assert ("outbox:attest", outbox.GIVEN_UP, "payload_mismatch") in steps(db, first["run_id"])
    assert ("outbox:attest", outbox.GIVEN_UP, "run_not_complete") in steps(db, second["run_id"])
    assert calls.made == [(ACTION, 1), (ACTION, 2)] and eng.loop.held_count() == 0


# ── 3. a raised sink ────────────────────────────────────────────────────────

class Sink:
    """``journal.transaction`` (and ``keys.bind`` / ``keys.answered``, which run
    inside one) raising at one write point while ``broken``. A write point is
    the engine or loop method whose transaction it is."""

    def __init__(self, monkeypatch, point: str) -> None:
        self.point = point
        self.broken = True
        self.raised = 0
        real = journal.transaction

        def transaction(db_, work, *, wait):
            if self.broken and self._where() == point:
                self.raised += 1
                raise sqlite3.OperationalError("database is locked")
            return real(db_, work, wait=wait)
        monkeypatch.setattr(journal, "transaction", transaction)
        if point.startswith("keys."):
            name = point.split(".", 1)[1]
            real_key_write = getattr(keys, name)

            def key_write(*args, **kwargs):
                if self.broken:
                    self.raised += 1
                    raise sqlite3.OperationalError("database is locked")
                return real_key_write(*args, **kwargs)
            monkeypatch.setattr(keys, name, key_write)

    @staticmethod
    def _where() -> str:
        frame = sys._getframe(2)
        # The helpers a write point goes through: a run's end (_end, and the
        # retry of one that could not be written, from maintain) and the
        # engine's and the loop's transaction helpers.
        while frame.f_code.co_name in ("_write", "_tx", "_end", "_write_pending"):
            frame = frame.f_back
        return frame.f_code.co_name


ENGINE_POINTS = ["open", "keys.bind", "abort", "_fail", "failed_with", "finish",
                 "keys.answered", "maintain"]
LOOP_POINTS = ["_claim", "_settle", "_give_up"]


async def corpus(d, eng, clock, db, sink: Sink | None) -> list:
    """One sequence over every write point: a settled request, one whose
    service raises and one refused before its call, each under a key; a hostile
    row and a run another process left in START with its key bound; replays
    before and after recovery; then the sink heals and everything is replayed
    again. Returns every answer, in order."""
    answers: list = []

    async def send(action, marker, key):
        answers.append(await bridge_like(d, action, params_for(action, marker), key=key))
        await settle()

    async def tick():
        if eng is not None:
            await eng.loop.tick()
        await settle()

    batch = [(ACTION, 1, "key-a"), (RAISES, 2, "key-b"), (UNAVAILABLE, 3, "key-c"),
             (ACTION, 4, "key-d")]
    for request in batch[:3]:
        await send(*request)
    plant_row(db, run_id="run_" + "0" * 32, kind="attest", digest="f" * 64, next_at=clock.now)
    plant_abandoned_start(db, run_id="run_" + "d" * 32, action=ACTION, marker=4,
                          client_key="key-d", at=clock.now - 1)
    for request in batch:
        await send(*request)
    clock.advance(journal.ABANDONED_AFTER_S + 1)
    await tick()
    for request in batch:
        await send(*request)
    if sink is not None:
        sink.broken = False
    clock.advance(journal.ABANDONED_AFTER_S + 1)
    await tick()
    await tick()
    for request in batch:
        await send(*request)
    await tick()
    return answers


@pytest.mark.parametrize("point", ENGINE_POINTS + LOOP_POINTS)
async def test_a_raised_sink_in_mode_on_never_calls_twice_or_unrecorded(point, db, clock,
                                                                       monkeypatch):
    effects = Effects()
    services = Services(effects)
    services.answers[RAISES] = Boom("the stand-in service failed")
    calls = Calls(services, db, check_recorded=True)
    d = dispatcher(effects, services, unavailable=(ACTION_MAP[UNAVAILABLE][0],))
    eng = engine(db, "on", clock, effects)
    with installed(eng):
        sink = Sink(monkeypatch, point)
        await corpus(d, eng, clock, db, sink)
    assert sink.raised > 0, f"the corpus never reached the write point {point}"
    assert not calls.unrecorded, (
        f"{point} raising: mode on called a service it had not recorded as RUNNING first: "
        f"{calls.unrecorded}")
    for marker in (1, 2, 3, 4):
        assert calls.count(marker) <= 1, (
            f"{point} raising: request {marker} reached its service {calls.count(marker)} "
            f"times: {calls.made}")
    assert calls.count(3) == 0, "a request refused before its call reached its service"
    if point != "_settle":   # see the dedicated test below
        for kind in (("attest", "attest_sent"), ("feed",)):
            delivered = sum(effects.count(k, ACTION) for k in kind)
            assert delivered <= calls.count(1) + calls.count(4), (
                f"{point} raising: {kind[0]} delivered {delivered} time(s) for "
                f"{calls.count(1) + calls.count(4)} settled call(s): {effects.log}")
    assert open_runs(db) == [], f"{point} raising: runs left open: {open_runs(db)}"


async def test_a_settle_that_raised_once_never_delivers_the_attestation_a_second_time(
        db, clock, monkeypatch):
    """The delivery went out and its row could not be marked, once; the next
    write succeeds. The row stays claimed and its payload stays held, so past
    the lease the loop delivers it again — one refused write is enough."""
    effects = Effects()
    d = dispatcher(effects)
    eng = engine(db, "on", clock, effects)
    with installed(eng):
        sink = Sink(monkeypatch, "_settle")
        await bridge_like(d, ACTION, params_for(ACTION, 1), key="settle-1")
        await eng.loop.tick()
        sink.broken = False
        assert sink.raised == 2 and effects.count("attest_sent") == 1, (sink.raised, effects.log)
        clock.advance(outbox.LEASE_S + 1)
        await eng.loop.tick()
        clock.advance(outbox.LEASE_S + 1)
        await eng.loop.tick()
    assert effects.count("service") == 1
    assert effects.count("attest_sent") == 1 and effects.count("feed") == 1, (
        "one settle that raised made the outbox deliver again: "
        f"attest_sent x{effects.count('attest_sent')}, feed x{effects.count('feed')}")


@pytest.mark.parametrize("point", ["open", "keys.bind", "abort", "_fail", "finish",
                                   "keys.answered", "maintain"])
async def test_a_raised_sink_in_shadow_never_changes_an_answer(point, tmp_path):
    async def run(mode: str):
        effects = Effects()
        services = Services(effects)
        services.answers[RAISES] = Boom("the stand-in service failed")
        database = open_db(tmp_path / f"{mode}.db")
        calls = Calls(services, database, check_recorded=False)
        d = dispatcher(effects, services, unavailable=(ACTION_MAP[UNAVAILABLE][0],))
        run_clock = Clock()
        eng = None if mode == "off" else engine(database, "shadow", run_clock, effects)
        try:
            with pytest.MonkeyPatch.context() as patch, installed(eng):
                sink = Sink(patch, point) if mode == "shadow" else None
                answers = await corpus(d, eng, run_clock, database, sink)
        finally:
            await database.close()
        return [normalised(a) for a in answers], effects.log, calls.made, sink

    off_answers, off_effects, off_calls, _ = await run("off")
    answers, effects, made, sink = await run("shadow")
    assert sink.raised > 0, f"the corpus never reached the write point {point}"
    assert answers == off_answers, (
        f"{point} raising in shadow changed an answer: "
        f"{[(a, b) for a, b in zip(answers, off_answers) if a != b][:2]}")
    assert made == off_calls and effects == off_effects, (
        f"{point} raising in shadow changed what was called or delivered:\n"
        f" shadow {effects}\n off    {off_effects}")


# ── 4. a replayed key never calls the service again ─────────────────────────

async def test_a_replay_while_the_first_run_is_open_calls_nothing(db, clock):
    effects = Effects()
    services = Services(effects)
    calls = Calls(services, db, check_recorded=True)
    d = dispatcher(effects, services)
    hold = asyncio.Event()
    services.gates[ACTION] = hold
    with installed(engine(db, "on", clock, effects)):
        first = asyncio.ensure_future(bridge_like(d, ACTION, params_for(ACTION, 1), key="open-1"))
        for _ in range(50):
            await asyncio.sleep(0)
            if [r["state"] for r in rows(db, "workflow_runs")] == [journal.RUNNING]:
                break
        replays = [json.loads(await bridge_like(d, ACTION, params_for(ACTION, 1), key="open-1"))
                   for _ in range(3)]
        hold.set()
        answer = await first
        after = await bridge_like(d, ACTION, params_for(ACTION, 1), key="open-1")
    assert all(r.get("error_category") == "idempotency_in_progress" for r in replays), replays
    assert after == answer, "the replay after the first answered is not its answer"
    assert calls.made == [(ACTION, 1)], f"a replay called the service: {calls.made}"


@pytest.mark.parametrize("state", ["COMPLETE", "FAIL"])
async def test_a_replay_after_the_first_run_ended_calls_nothing(state, db, clock):
    effects = Effects()
    services = Services(effects)
    if state == "FAIL":
        services.answers[ACTION] = Boom("the stand-in service failed")
    calls = Calls(services, db, check_recorded=True)
    d = dispatcher(effects, services)
    with installed(eng := engine(db, "on", clock, effects)):
        first = await bridge_like(d, ACTION, params_for(ACTION, 1), key="ended-1")
        await eng.loop.tick()
        replays = [await bridge_like(d, ACTION, params_for(ACTION, 1), key="ended-1")
                   for _ in range(3)]
        concurrent = await asyncio.gather(*[
            bridge_like(d, ACTION, params_for(ACTION, 1), key="ended-1") for _ in range(4)])
    (run,) = rows(db, "workflow_runs")
    assert run["state"] == state, run
    assert all(r == first for r in replays + list(concurrent)), (
        f"a replay of a {state} run was not given the first answer byte for byte")
    assert calls.made == [(ACTION, 1)], f"a replay of a {state} run called again: {calls.made}"


async def test_a_replay_after_a_crash_mid_call_and_a_restart_calls_nothing(tmp_path, clock):
    effects = Effects()
    services = Services(effects)
    first_db = open_db(tmp_path / "first.db")
    calls = Calls(services, first_db, check_recorded=True)
    d = dispatcher(effects, services)
    hold = asyncio.Event()
    services.gates[ACTION] = hold
    try:
        with installed(engine(first_db, "on", clock, effects)):
            first = asyncio.ensure_future(
                bridge_like(d, ACTION, params_for(ACTION, 1), key="crash-1"))
            for _ in range(50):
                await asyncio.sleep(0)
                if rows(first_db, "workflow_runs"):
                    break
            crashed = snapshot(first_db, tmp_path / "crashed.db")
            first.cancel()
            with contextlib.suppress(asyncio.CancelledError):
                await first
    finally:
        await first_db.close()
    restarted_db = open_db(crashed)
    try:
        restarted = engine(restarted_db, "on", clock, effects)
        calls.db = restarted_db
        with installed(restarted):
            before = json.loads(await bridge_like(d, ACTION, params_for(ACTION, 1),
                                                  key="crash-1"))
            clock.advance(journal.ABANDONED_AFTER_S + 1)
            await restarted.loop.tick()
            after = json.loads(await bridge_like(d, ACTION, params_for(ACTION, 1), key="crash-1"))
            (run,) = rows(restarted_db, "workflow_runs")
    finally:
        await restarted_db.close()
    assert before.get("error_category") == "idempotency_in_progress", before
    assert run["state"] == journal.FAIL, f"the crashed run was left {run['state']}"
    assert after.get("error_category") == "idempotency_answer_not_held", after
    # The first call was held at its start and the process died there: it
    # never reached its effect, and nothing after the restart calls at all.
    assert calls.made == [], f"a replay after the crash called the service: {calls.made}"
    assert effects.count("service") == 0, effects.log


async def test_a_key_released_with_an_abort_runs_exactly_once_more(db, clock):
    """Two ways a run ends ABORT with a key: refused before its call (the key
    is never bound), and left in START by a process that is gone (recovery
    gives the key back). Neither acted, so the retry runs — once."""
    effects = Effects()
    services = Services(effects)
    calls = Calls(services, db, check_recorded=True)
    refusing = dispatcher(effects, services, unavailable=(ACTION_MAP[ACTION][0],))
    d = dispatcher(effects, services)
    with installed(eng := engine(db, "on", clock, effects)):
        refused = json.loads(await bridge_like(refusing, ACTION, params_for(ACTION, 1),
                                               key="abort-1"))
        assert refused.get("error_category") == "service_unavailable", refused
        assert rows(db, "idempotency_keys") == []
        retries = [await bridge_like(d, ACTION, params_for(ACTION, 1), key="abort-1")
                   for _ in range(3)]

        plant_abandoned_start(db, run_id="run_" + "d" * 32, action=ACTION, marker=2,
                              client_key="abort-2", at=clock.now)
        while_open = json.loads(await bridge_like(d, ACTION, params_for(ACTION, 2),
                                                  key="abort-2"))
        clock.advance(journal.ABANDONED_AFTER_S + 1)
        await eng.loop.tick()
        released = [await bridge_like(d, ACTION, params_for(ACTION, 2), key="abort-2")
                    for _ in range(3)]
    assert retries[0] == retries[1] == retries[2], "the retry's own replays were not its answer"
    assert while_open.get("error_category") == "idempotency_in_progress", while_open
    assert released[0] == released[1] == released[2], released
    assert json.loads(released[0])["status"] == "ok", released[0]
    assert calls.made == [(ACTION, 1), (ACTION, 2)], (
        f"a key given back with an ABORT did not run exactly once more: {calls.made}")
    states = {r["run_id"]: r["state"] for r in rows(db, "workflow_runs")}
    assert states["run_" + "d" * 32] == journal.ABORT, states


async def test_concurrent_requests_under_one_key_call_once(db, clock):
    effects = Effects()
    services = Services(effects)
    calls = Calls(services, db, check_recorded=True)
    d = dispatcher(effects, services)
    with installed(engine(db, "on", clock, effects)):
        answers = await asyncio.gather(*[
            bridge_like(d, ACTION, params_for(ACTION, 1), key="together") for _ in range(8)])
    assert calls.made == [(ACTION, 1)], f"concurrent requests under one key: {calls.made}"
    words = {json.loads(a).get("error_category", "ok") for a in answers}
    assert words <= {"ok", "idempotency_in_progress"}, words


# ── 5. nothing in runtime/durable reaches for authority ─────────────────────

#: What runtime/durable may import beyond the standard library and itself: the
#: outcome vocabulary it reads words from, the twin tools' signing list, the
#: batch processor whose submission path delivers an attestation, and the one
#: spelling of a caller (runtime/auth/identity.py), which scopes a key and
#: decides nothing.
ALLOWED_IMPORTS = ("runtime.protocols.outcome_truth", "runtime.security.action_map",
                   "runtime.blockchain.services.attestation.batch_processor",
                   "runtime.auth.identity")
GATE_FUNCTIONS = {"gate_action", "evaluate", "pre_action"}


def _imports(tree: ast.AST) -> list[str]:
    found = []
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            found += [alias.name for alias in node.names]
        elif isinstance(node, ast.ImportFrom):
            found.append("." * node.level + (node.module or ""))
    return found


def test_runtime_durable_imports_only_the_stdlib_itself_and_four_named_modules():
    sources = sorted(DURABLE_DIR.glob("*.py"))
    assert {p.name for p in sources} >= {"journal.py", "outbox.py", "keys.py", "wiring.py"}
    offending = []
    for path in sources:
        for name in _imports(ast.parse(path.read_text(), str(path))):
            top = name.split(".")[0]
            if name == "__future__" or top in sys.stdlib_module_names:
                continue
            if name == "runtime.durable" or name.startswith("runtime.durable."):
                continue
            if name in ALLOWED_IMPORTS:
                continue
            offending.append(f"{path.name}: {name}")
    assert not offending, f"runtime/durable imports outside what it may: {offending}"


def test_runtime_durable_never_calls_a_gate_function():
    offending = []
    for path in sorted(DURABLE_DIR.glob("*.py")):
        for node in ast.walk(ast.parse(path.read_text(), str(path))):
            if not isinstance(node, ast.Call):
                continue
            func = node.func
            name = func.id if isinstance(func, ast.Name) else (
                func.attr if isinstance(func, ast.Attribute) else "")
            if name in GATE_FUNCTIONS:
                offending.append(f"{path.name}:{node.lineno} {name}()")
    assert not offending, f"runtime/durable calls a gate function: {offending}"


# ── 6. the gate is not bypassed ─────────────────────────────────────────────

class Gate:
    """``gateway.security_gate.gate_action`` as the bridge calls it: every
    question is kept, with the number of runs on record when it was asked, and
    every decision it handed out is kept with a copy to compare against."""

    def __init__(self) -> None:
        self.refuse = False
        self.db = None
        self.questions: list[tuple] = []
        self.decisions: list[tuple[dict, dict]] = []

    async def __call__(self, action, parameters=None, context=None, *, operation=None):
        runs = len(rows(self.db, "workflow_runs")) if self.db is not None else None
        self.questions.append((action, json.dumps(parameters, sort_keys=True), operation, runs))
        decision = {"allow": not self.refuse, "evaluation_id": f"ev{len(self.questions)}",
                    "reasons": ["stand-in"]}
        self.decisions.append((decision, copy.deepcopy(decision)))
        return decision


@contextlib.asynccontextmanager
async def gateway(tmp_path, monkeypatch, *, mode: str = "on", name: str = "gw.db"):
    from aiohttp.test_utils import TestClient, TestServer

    from gateway.server import GatewayServer
    from test_route_sweep import SWEEP_CONFIG

    gate = Gate()
    monkeypatch.setattr("gateway.security_gate.gate_action", gate)
    config = {**SWEEP_CONFIG, "memory_dir": str(tmp_path),
              "database": {"path": f"{tmp_path}/{name}"},
              "engines": {"durable": {"mode": mode}}}
    server = GatewayServer(config)
    server.react_loop.router.health_check = AsyncMock(return_value={"stand_in": True})
    effects = Effects()
    services = Services(effects)
    async with TestClient(TestServer(server.create_app())) as client:
        database = server.react_loop.memory.db
        calls = Calls(services, database, check_recorded=(mode == "on"))
        server.service_dispatcher = dispatcher(effects, services)
        if server._durable_engine is not None:
            server._durable_engine.attestations = Attestations(effects)
        gate.db = database
        world = SimpleNamespace(gate=gate, effects=effects, services=services, calls=calls,
                                db=database, tables=None)
        yield client, world
        world.tables = {t: rows(database, t) for t in DURABLE_TABLES}


async def post(client, marker, key):
    headers = {"Idempotency-Key": key} if key is not None else {}
    resp = await client.post("/bridge/v1/action", json={
        "action": ACTION, "params": params_for(ACTION, marker), "session_id": "s1"},
        headers=headers)
    return resp.status, await resp.json()


async def test_a_request_the_gate_blocks_opens_no_run_and_binds_no_key(tmp_path, monkeypatch):
    async with gateway(tmp_path, monkeypatch) as (client, w):
        w.gate.refuse = True
        blocked = [await post(client, 1, "blocked-1") for _ in range(2)]
        assert all(status == 403 for status, _ in blocked), blocked
        assert all(rows(w.db, t) == [] for t in DURABLE_TABLES), (
            f"a request the gate blocked was journaled: "
            f"{ {t: rows(w.db, t) for t in DURABLE_TABLES} }")
        w.gate.refuse = False
        status, allowed = await post(client, 1, "blocked-1")
        assert status == 200 and allowed["ok"] is True, (status, allowed)
    assert w.calls.made == [(ACTION, 1)] and not w.calls.unrecorded, (
        f"blocked requests reached the service, or the allowed one did not run once: "
        f"{w.calls.made}")
    assert len(w.tables["workflow_runs"]) == 1 and len(w.tables["idempotency_keys"]) == 1
    assert [q[3] for q in w.gate.questions] == [0, 0, 0], (
        f"the gate was asked after a run was written: {w.gate.questions}")
    for decision, as_handed_out in w.gate.decisions:
        assert decision == as_handed_out, f"a gate decision was changed after it was made: {decision}"


@pytest.mark.parametrize("first_state", ["COMPLETE", "RUNNING"])
async def test_a_replay_the_gate_refuses_is_refused(first_state, tmp_path, monkeypatch):
    async with gateway(tmp_path, monkeypatch) as (client, w):
        hold = asyncio.Event()
        if first_state == "RUNNING":
            w.services.gates[ACTION] = hold
            first = asyncio.ensure_future(post(client, 1, "refused-replay"))
            deadline = time.monotonic() + 3.0
            while [r["state"] for r in rows(w.db, "workflow_runs")] != ["RUNNING"]:
                assert time.monotonic() < deadline, "the first request's run never ran"
                await asyncio.sleep(0.01)
        else:
            first = asyncio.ensure_future(post(client, 1, "refused-replay"))
            await first
        w.gate.refuse = True
        status, body = await post(client, 1, "refused-replay")
        hold.set()
        first_status, first_body = await first
    assert first_status == 200 and first_body["ok"] is True, first_body
    assert status == 403, f"a replay the gate refused was answered {status}: {body}"
    assert "data" not in body and first_body["data"] not in json.dumps(body), (
        f"a replay the gate refused was given the first answer: {body}")
    assert w.calls.made == [(ACTION, 1)], w.calls.made
    assert len(w.gate.questions) == 2, f"the replay was not put to the gate: {w.gate.questions}"
    assert len(w.tables["workflow_runs"]) == 1, w.tables["workflow_runs"]


async def test_the_gate_is_asked_the_same_questions_in_every_mode(tmp_path, monkeypatch):
    seen = {}
    for mode in ("off", "shadow", "on"):
        async with gateway(tmp_path, monkeypatch, mode=mode, name=f"{mode}.db") as (client, w):
            answers = [await post(client, 1, "same-question") for _ in range(2)]
            w.gate.refuse = True
            answers.append(await post(client, 1, "same-question"))
        seen[mode] = ([q[:3] for q in w.gate.questions], [a[0] for a in answers])
    assert seen["off"] == seen["shadow"] == seen["on"], (
        f"the mode changed what the gate was asked, or its refusal: {seen}")
    assert seen["on"][1] == [200, 200, 403], seen


# ── 7. the invariant test files are unchanged ───────────────────────────────

INVARIANT_FILES = ("tests/test_a_broadcast_is_not_a_settlement.py",
                   "tests/test_a_record_says_what_happened.py",
                   "tests/test_gate_fault_fail_direction.py")


#: sha256 of each invariant file as the target branch holds it, for a checkout
#: in which no ref of that branch can be read. Kept equal to the branch's own
#: copy by the test below wherever the branch can be read, so it never goes
#: stale unnoticed.
INVARIANT_DIGESTS = {
    "tests/test_a_broadcast_is_not_a_settlement.py":
        "35d3c399849645d281c091718038addab3431769e15386a30feabbea4fb10f98",
    "tests/test_a_record_says_what_happened.py":
        "a921361c6b153cb9ac8b9c2df7eb509e511018aa9e8189b5b5da3a62f3dbb499",
    "tests/test_gate_fault_fail_direction.py":
        "903867fc56550e4f8bdfeabc5f32b945e5719d6900630690dd8cb606b0f40bf0",
}
#: Where the target branch is looked for: the local branch, then the ref a
#: CI checkout with its whole history has (``fetch-depth: 0`` fetches every
#: branch as a remote ref and creates no local one).
TARGET_REFS = ("refs/heads/main", "refs/remotes/origin/main")


def _target_copy(path: str) -> bytes | None:
    for ref in TARGET_REFS:
        try:
            shown = subprocess.run(["git", "show", f"{ref}:{path}"], cwd=REPO,
                                   capture_output=True, timeout=30)
        except (FileNotFoundError, subprocess.TimeoutExpired):
            return None
        if shown.returncode == 0:
            return shown.stdout
    return None


@pytest.mark.parametrize("path", INVARIANT_FILES)
def test_an_invariant_test_file_is_byte_identical_to_the_target_branch(path):
    """Phase 2 leaves the invariant test files as they are. Compared with the
    target branch's copy wherever a ref of it can be read (locally, and in CI,
    whose test job fetches the whole history), and otherwise with the recorded
    digest of it — never skipped."""
    here = (REPO / path).read_bytes()
    target = _target_copy(path)
    if target is not None:
        assert hashlib.sha256(target).hexdigest() == INVARIANT_DIGESTS[path], (
            f"INVARIANT_DIGESTS[{path!r}] is not the target branch's copy: record "
            f"{hashlib.sha256(target).hexdigest()}")
        assert here == target, f"{path} differs from the target branch's copy"
    else:
        assert hashlib.sha256(here).hexdigest() == INVARIANT_DIGESTS[path], (
            f"{path} differs from the target branch's copy as recorded")


def test_ci_reads_the_whole_history_so_the_history_checks_bind_there():
    """The invariant files' comparison and the artefacts' provenance check
    (tests/durable_measured_at.py) read the history, which a shallow checkout
    does not have: the CI job that runs the suite fetches all of it."""
    import yaml

    workflow = yaml.safe_load((REPO / ".github" / "workflows" / "ci.yml").read_text())
    steps = workflow["jobs"]["test"]["steps"]
    checkout = next(s for s in steps if str(s.get("uses", "")).startswith("actions/checkout"))
    assert str(checkout.get("with", {}).get("fetch-depth")) == "0", checkout
    assert any("pytest tests/" in str(s.get("run", "")) for s in steps), steps
