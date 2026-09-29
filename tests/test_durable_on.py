"""Engines Phase 2: durable execution with ``engines.durable.mode = "on"``.

Mode on moves the LIFECYCLE of the canary's actions to the run, and nothing
else. This file measures that, against the real code — the real
``ServiceDispatcher``, the real ``DurableEngine`` and its outbox loop over the
platform ``Database``, the real ``ToolDispatcher``, and the real gateway
(``GatewayServer`` under aiohttp's test client) for the bridge — over the shared
harness's stand-ins for the services, the chain and the feed:

* THE RUN. A state-modifying dispatch is written RUNNING immediately before its
  service call and ends COMPLETE with the dispatcher's own word on the
  ``return`` step (settled / broadcast / refused), FAIL with a ``raise`` step
  when the service raised, or ABORT — never called — with the step word naming
  the pre-call refusal (service unavailable, no such method, parameters that do
  not bind, a raise before the call). An ABORT binds no key, so a retry runs.
* THE DELIVERY. For a settled answer the outbox — not the dispatcher — delivers
  the attestation (through the batch processor's submission path) and the feed
  entry, each exactly once however many ticks follow; the legacy
  ``_attest_action`` and the ``create_task`` feed publish are not used. When the
  run cannot be opened the service is NOT called and the answer is
  ``service_unavailable`` ("was not run"); when its end cannot be written the
  dispatcher delivers both the legacy way, exactly once.
* THE REPLAY, through ``POST /bridge/v1/action``: a replayed Idempotency-Key gets
  the first answer byte for byte in ``data`` and runs nothing; a different body
  under the key is ``idempotency_conflict`` (422); a replay while the first is
  still in its call is ``idempotency_in_progress``; an invalid key is 400; a key
  presented by another caller scope never sees the first answer; after a restart
  the replay is ``idempotency_answer_not_held`` and runs nothing; the gate is
  asked again on every replay, and a refusal there is the 403 with no replayed
  answer; without a key every request runs.
* THE TWIN TOOLS, through ``ToolDispatcher.dispatch``: a platform-key signing
  call is journaled COMPLETE, a read is not journaled, a timeout is FAIL
  ``unknown_effect``/``timed_out``, a raise is FAIL ``raise``, and a signing
  call whose run cannot be written is not made and answers a failure outcome.
* THE MODE AND /ready. ``durable_mode`` reads the config, the environment wins,
  anything unknown is off; ``/ready`` is 200 while the outbox loop runs and 503
  once it is stopped, cancelled or stale; with the mode off nothing durable is
  checked; the gateway stops and uninstalls its own engine — only its own — on
  cleanup.

Why: mode on is the one mode in which the engine holds authority. Every place
it holds some — whether a call is made, who delivers its records, what a
replayed key is answered — must be the only path, act at most once, and never
decide anything the gate or the dispatcher decides.
"""
from __future__ import annotations

import asyncio
import contextlib
import json
import sqlite3
import sys
import time
from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest

sys.path.insert(0, "tests")

from test_durable_harness import (  # noqa: E402
    ACTION_MAP, BROADCAST, OTHER, REFUSED, SETTLED, WALLET, Attestations, Boom, Clock, Effects,
    Services, bridge_like, drain, engine, installed, open_db, params_for, rows,
)
from test_durable_harness import dispatcher as _harness_dispatcher  # noqa: E402
from runtime.durable import journal, keys, outbox, wiring  # noqa: E402
from runtime.durable.wiring import DurableEngine  # noqa: E402

ACTION = "transfer_stablecoin"
SERVICE = ACTION_MAP[ACTION][0]

DURABLE_TABLES = ("workflow_runs", "workflow_steps", "outbox", "idempotency_keys")


@pytest.fixture(autouse=True)
def _no_mode_env(monkeypatch):
    monkeypatch.delenv("MATRIX_DURABLE_MODE", raising=False)


@pytest.fixture
async def db(tmp_path):
    database = open_db(tmp_path / "on.db")
    yield database
    await database.close()


@pytest.fixture
def clock() -> Clock:
    return Clock()


def dispatcher(effects: Effects, services: Services | None = None):
    """The harness's dispatcher, with a legacy attestation service that records
    ``("attest", action)`` when the dispatcher queues an attestation itself.

    The harness's own ``attestation`` stand-in cannot be built: ACTION_MAP maps
    an action to ``attestation.attest``, so ``SimpleNamespace(attest=...,
    **methods)`` raises TypeError and ``_attest_action`` swallows it — a legacy
    attestation would leave no effect to count."""
    d = _harness_dispatcher(effects, services)
    registry = d._get_registry()

    async def attest(**kwargs):
        effects.log.append(("attest", kwargs.get("data", {}).get("action")))
        return {"status": "queued"}

    def get(name):
        if name == "attestation":
            return SimpleNamespace(attest=attest)
        return registry.get(name)
    fixed = SimpleNamespace(get=get)
    d._get_registry = lambda: fixed
    return d


def _on_engine(db, clock, attestations) -> DurableEngine:
    return DurableEngine(db, mode="on", clock=clock, attestations=attestations)


def _steps(db, run_id: str) -> list[tuple[str, str]]:
    return [(s["name"], s["state"]) for s in journal.get_steps(db, run_id)]


def _the_run(db) -> dict:
    runs = rows(db, "workflow_runs")
    assert len(runs) == 1, f"expected exactly one run, found {len(runs)}: {runs}"
    return runs[0]


class _Spies:
    """Counts every legacy delivery the dispatcher itself makes: ``_attest_action``
    on this dispatcher, ``_publish_feed`` (the legacy closure mode on hands
    ``hold``), and every task the dispatcher module creates (the shadow/off feed
    publish is ``asyncio.create_task(feed.ingest(...))``)."""

    def __init__(self, monkeypatch, d) -> None:
        import runtime.blockchain.services.service_dispatcher as sd

        self.attest_action: list = []
        self.publish_feed: list = []
        self.tasks: list[str] = []
        original_attest = d._attest_action
        original_publish = sd._publish_feed

        async def attest_action(*args, **kwargs):
            self.attest_action.append(args[0] if args else None)
            return await original_attest(*args, **kwargs)

        def publish_feed(feed_engine, entry):
            self.publish_feed.append(entry.get("action"))
            return original_publish(feed_engine, entry)

        real_asyncio = asyncio

        class _AsyncioProxy:
            def __getattr__(self, name):
                return getattr(real_asyncio, name)

            @staticmethod
            def create_task(coro, *args, **kwargs):
                spies.tasks.append(getattr(coro, "__qualname__", repr(coro)))
                return real_asyncio.create_task(coro, *args, **kwargs)

        spies = self
        d._attest_action = attest_action
        monkeypatch.setattr(sd, "_publish_feed", publish_feed)
        monkeypatch.setattr(sd, "asyncio", _AsyncioProxy())


# ── the service dispatcher: the run ────────────────────────────────────────

@pytest.mark.parametrize("answer, word", [(SETTLED, "settled"), (BROADCAST, "broadcast"),
                                          (REFUSED, "refused")])
async def test_a_dispatch_that_answered_is_complete_with_the_dispatchers_own_word(
        answer, word, db, clock, monkeypatch):
    effects = Effects()
    d = dispatcher(effects)
    d._services.answers[ACTION] = answer
    spies = _Spies(monkeypatch, d)
    with installed(engine(db, "on", clock, effects)):
        envelope = json.loads(await d.execute(ACTION, params=params_for(ACTION, 1),
                                              caller_identity=WALLET))
    assert envelope["status"] == "ok" and envelope["result"] == answer, envelope
    assert effects.count("service", ACTION, 1) == 1, f"service calls: {effects.log}"
    run = _the_run(db)
    assert run["state"] == journal.COMPLETE, f"an answered call ended {run['state']}"
    assert (run["action"], run["service"]) == (ACTION, SERVICE), run
    assert run["actor_hash"] == journal.actor_hash(WALLET), "the run does not name its caller"
    assert run["params_digest"] == journal.digest(params_for(ACTION, 1))
    assert run["terminal_at"] == clock.now and run["key"] == "", run
    assert _steps(db, run["run_id"]) == [("start", "opened"), ("call", "began"),
                                         ("return", word)], _steps(db, run["run_id"])
    kinds = sorted(r["kind"] for r in rows(db, "outbox"))
    assert kinds == (["attest", "feed"] if word == "settled" else []), (
        f"a {word} answer wrote outbox rows {kinds}")
    assert spies.attest_action == [] and spies.publish_feed == [], (
        "the dispatcher delivered an attestation or feed entry itself in mode on")
    assert not any("ingest" in t for t in spies.tasks), f"create_task feed publish: {spies.tasks}"


async def test_a_service_that_raises_is_fail_with_a_raise_step_and_delivers_nothing(
        db, clock, monkeypatch):
    effects = Effects()
    d = dispatcher(effects)
    d._services.answers[ACTION] = Boom("the stand-in service failed")
    spies = _Spies(monkeypatch, d)
    with installed(eng := engine(db, "on", clock, effects)):
        envelope = json.loads(await d.execute(ACTION, params=params_for(ACTION, 1),
                                              caller_identity=WALLET))
        await drain(eng)
    assert envelope["error_category"] == "service_error", envelope
    run = _the_run(db)
    assert run["state"] == journal.FAIL, f"a raised call ended {run['state']}"
    steps = journal.get_steps(db, run["run_id"])
    assert [(s["name"], s["state"]) for s in steps] == [
        ("start", "opened"), ("call", "began"), ("raise", "raised")], steps
    assert steps[-1]["detail"] == "raised:Boom", steps[-1]
    assert rows(db, "outbox") == [] and effects.count("attest_sent") == 0 \
        and effects.count("feed") == 0 and effects.count("attest") == 0, effects.log
    assert spies.attest_action == [] and spies.publish_feed == []


def _registry_without_service():
    def get(name):
        raise KeyError(name)
    return SimpleNamespace(get=get)


def _registry_without_method():
    return SimpleNamespace(get=lambda name: SimpleNamespace())


def _registry_with_strict_method(effects: Effects):
    async def strict(*, only_this_parameter):
        effects.log.append(("service", ACTION, None))
        return dict(SETTLED)
    return SimpleNamespace(get=lambda name: SimpleNamespace(**{ACTION_MAP[ACTION][1]: strict}))


def _registry_that_raises():
    def get(name):
        raise RuntimeError("the registry itself failed")
    return SimpleNamespace(get=get)


PRE_CALL = {
    # case -> (registry builder, the envelope's category, the abort step's word)
    "service_unavailable": (lambda e: _registry_without_service(), "service_unavailable",
                            "service_unavailable"),
    "no_such_method": (lambda e: _registry_without_method(), "service_error", "no_such_method"),
    "invalid_parameters": (_registry_with_strict_method, "validation", "invalid_parameters"),
    "raised_before_call": (lambda e: _registry_that_raises(), "service_error",
                           "raised_before_call"),
}


@pytest.mark.parametrize("case", list(PRE_CALL))
async def test_a_pre_call_refusal_is_abort_with_its_word_binds_no_key_and_a_retry_runs(
        case, db, clock):
    build, category, why = PRE_CALL[case]
    effects = Effects()
    d = dispatcher(effects)
    healthy_registry = d._get_registry()
    broken_registry = build(effects)
    d._get_registry = lambda: broken_registry
    with installed(engine(db, "on", clock, effects)):
        envelope = json.loads(await bridge_like(d, ACTION, params_for(ACTION, 1), key="k-" + case))
        assert envelope["status"] == "error" and envelope["error_category"] == category, envelope
        assert effects.count("service") == 0, f"{case}: the service was called: {effects.log}"
        run = _the_run(db)
        assert run["state"] == journal.ABORT and run["terminal_at"] == clock.now, run
        assert _steps(db, run["run_id"]) == [("start", "opened"), ("abort", why)], (
            f"{case}: {_steps(db, run['run_id'])}")
        assert rows(db, "idempotency_keys") == [], f"{case}: an ABORT bound its key"
        assert rows(db, "outbox") == []

        # The same key again, the service now reachable: it runs, once.
        d._get_registry = lambda: healthy_registry
        again = json.loads(await bridge_like(d, ACTION, params_for(ACTION, 1), key="k-" + case))
    assert again["status"] == "ok", f"{case}: the retry after an ABORT did not run: {again}"
    assert effects.count("service", ACTION, 1) == 1, effects.log
    assert len(rows(db, "idempotency_keys")) == 1


# ── the service dispatcher: the delivery ────────────────────────────────────

async def test_the_outbox_delivers_the_attestation_and_the_feed_entry_exactly_once(
        db, clock, monkeypatch):
    effects = Effects()
    d = dispatcher(effects)
    spies = _Spies(monkeypatch, d)
    with installed(eng := engine(db, "on", clock, effects)):
        envelope = json.loads(await d.execute(ACTION, params=params_for(ACTION, 1),
                                              caller_identity=WALLET))
        assert envelope["status"] == "ok", envelope
        await asyncio.sleep(0)
        await asyncio.sleep(0)
        assert effects.count("attest") == effects.count("attest_sent") == 0 \
            and effects.count("feed") == 0, (
                f"something was delivered before the outbox ran: {effects.log}")
        due = rows(db, "outbox")
        assert sorted(r["kind"] for r in due) == ["attest", "feed"], due
        for r in due:
            assert (r["attempts"], r["done_at"], r["next_at"]) == (0, None, clock.now), r

        await drain(eng)
        for _ in range(4):
            clock.advance(outbox.LEASE_S + journal.ABANDONED_AFTER_S + 1)
            await eng.loop.tick()

    assert effects.count("attest_sent", ACTION) == 1, f"attestations sent: {effects.log}"
    assert effects.count("feed", ACTION) == 1, f"feed entries: {effects.log}"
    assert effects.count("attest") == 0, "the legacy attestation queue was used in mode on"
    assert spies.attest_action == [] and spies.publish_feed == [], (
        f"legacy delivery used: attest {spies.attest_action}, feed {spies.publish_feed}")
    assert not any("ingest" in t for t in spies.tasks), f"create_task feed publish: {spies.tasks}"
    done = rows(db, "outbox")
    for r in done:
        assert r["done_at"] is not None and r["next_at"] is None and r["attempts"] == 1, r
    run = _the_run(db)
    delivered = [("outbox:attest", "delivered"), ("outbox:feed", "delivered")]
    assert _steps(db, run["run_id"])[3:] == delivered, _steps(db, run["run_id"])


async def test_a_run_that_cannot_be_opened_is_not_called_and_answers_was_not_run(
        db, clock, monkeypatch):
    effects = Effects()
    d = dispatcher(effects)
    spies = _Spies(monkeypatch, d)
    writes: list = []

    def unwritable(db_, work, *, wait):
        writes.append(wait)
        raise sqlite3.OperationalError("database is locked")
    monkeypatch.setattr(journal, "transaction", unwritable)
    with installed(eng := engine(db, "on", clock, effects)):
        answer = await bridge_like(d, ACTION, params_for(ACTION, 1), key="k-unwritable")
        await asyncio.sleep(0)
        await asyncio.sleep(0)
    envelope = json.loads(answer)
    assert effects.count("service") == 0, f"a run that was not recorded was run: {effects.log}"
    assert envelope["status"] == "error" and envelope["error_category"] == "service_unavailable", (
        envelope)
    assert "was not run" in envelope["error"], envelope["error"]
    assert writes == [True], f"mode on's open must wait for the database, once: {writes}"
    assert rows(db, "workflow_runs") == [] and rows(db, "idempotency_keys") == []
    assert effects.count("attest") == effects.count("feed") == 0
    assert spies.attest_action == [] and spies.publish_feed == []
    assert eng.loop.held_count() == 0


async def test_a_run_whose_end_cannot_be_written_is_delivered_the_legacy_way_exactly_once(
        db, clock, monkeypatch):
    effects = Effects()
    d = dispatcher(effects)
    spies = _Spies(monkeypatch, d)
    real = journal.transaction
    calls: list[int] = []

    def the_end_fails(db_, work, *, wait):
        calls.append(1)
        if len(calls) == 2:   # 1: open (RUNNING), 2: finish (COMPLETE + outbox + key)
            raise sqlite3.OperationalError("database is locked")
        return real(db_, work, wait=wait)
    monkeypatch.setattr(journal, "transaction", the_end_fails)
    with installed(eng := engine(db, "on", clock, effects)):
        answer = await bridge_like(d, ACTION, params_for(ACTION, 1), key="k-end")
        await asyncio.sleep(0)
        await asyncio.sleep(0)
        for _ in range(3):
            await drain(eng)
        envelope = json.loads(answer)
        assert envelope["status"] == "ok", f"a lost record changed the answer: {envelope}"
        assert effects.count("service", ACTION, 1) == 1
        assert spies.attest_action == [ACTION] and effects.count("attest", ACTION) == 1, (
            f"legacy attestation: {spies.attest_action}, effects {effects.log}")
        assert spies.publish_feed == [ACTION] and effects.count("feed", ACTION) == 1, (
            f"legacy feed: {spies.publish_feed}, effects {effects.log}")
        assert effects.count("attest_sent") == 0 and rows(db, "outbox") == [], (
            "the outbox delivered a run whose end was never written")
        assert eng.loop.held_count() == 0

        # The run's end could not be written when it answered: the engine keeps
        # it and writes it on the loop's next pass (the database accepts writes
        # again), without outbox rows — those went the legacy way. The run is
        # COMPLETE, never closed by recovery as if its process were gone, and
        # a replay gets the first answer and runs nothing.
        run = _the_run(db)
        assert run["state"] == journal.COMPLETE, f"the kept end was not written: {run['state']}"
        assert _steps(db, run["run_id"])[-1][0] == "return", _steps(db, run["run_id"])
        assert rows(db, "outbox") == [], "the kept end wrote outbox rows for a legacy delivery"
        clock.advance(journal.ABANDONED_AFTER_S + 1)
        await eng.loop.tick()
        assert _the_run(db)["state"] == journal.COMPLETE, "recovery closed a run that answered"
        replay = await bridge_like(d, ACTION, params_for(ACTION, 1), key="k-end")
        assert replay == answer, f"the replay did not get the first answer: {replay}"
    assert effects.count("service") == 1, f"a replay ran the action again: {effects.log}"
    assert effects.count("attest") == effects.count("feed") == 1, effects.log


async def test_a_run_that_raised_under_a_key_answers_its_replay_with_the_same_error(db, clock):
    effects = Effects()
    d = dispatcher(effects)
    d._services.answers[ACTION] = Boom("the stand-in service failed")
    called: list = []
    d._services.before_effect = lambda action, params: called.append(action)
    with installed(engine(db, "on", clock, effects)):
        first = await bridge_like(d, ACTION, params_for(ACTION, 1), key="k-raise")
        again = await bridge_like(d, ACTION, params_for(ACTION, 1), key="k-raise")
    assert json.loads(first)["error_category"] == "service_error", first
    assert again == first, f"the replay of a FAIL run is not its first answer:\n{again}\n{first}"
    assert called == [ACTION], f"the service was called {len(called)} time(s) for one key"
    (bound,) = rows(db, "idempotency_keys")
    assert bound["response_digest"] == journal.text_digest(first)
    assert _the_run(db)["state"] == journal.FAIL


async def test_what_the_outbox_delivers_is_a_copy_taken_when_the_run_ended(db, clock):
    """The attestation and feed entry are the dispatcher's own builders' output,
    deep-copied: a caller mutating its parameters after the answer changes
    nothing the loop delivers."""
    effects = Effects()
    d = dispatcher(effects)
    delivered: dict = {}

    async def ingest(**kwargs):
        delivered["feed"] = kwargs
        return SimpleNamespace(summary="ingested")
    d._feed_engine = SimpleNamespace(ingest=ingest)
    attestations = Attestations(effects)
    submit = attestations._submit_batch

    async def capture(batch):
        delivered["attest"] = batch[0]
        return await submit(batch)
    attestations._submit_batch = capture
    params = {"to": WALLET, "amount": 5, "marker": 1, "memo": {"note": "original"}}
    with installed(eng := _on_engine(db, clock, attestations)):
        await d.execute(ACTION, params=params, caller_identity=WALLET)
        params["memo"]["note"] = "mutated after the answer"
        params["amount"] = 999
        await drain(eng)
    feed = delivered["feed"]
    assert feed["action"] == ACTION and feed["actor"] == WALLET, feed
    assert feed["detail"]["params"]["memo"] == {"note": "original"} \
        and feed["detail"]["params"]["amount"] == 5, f"the feed entry is a live dict: {feed}"
    data = delivered["attest"]["data"]
    assert (data["action"], data["service"], data["actor"], data["actor_source"]) == (
        ACTION, SERVICE, WALLET, "authenticated"), data


# ── the bridge: replays, through the real gateway ───────────────────────────

class Gate:
    """``gateway.security_gate.gate_action`` as the bridge calls it: every call
    is counted; ``refuse`` makes the next answers a deny."""

    def __init__(self) -> None:
        self.calls: list[str] = []
        self.refuse = False

    async def __call__(self, action, parameters=None, context=None, *, operation=None):
        self.calls.append(action)
        if self.refuse:
            return {"allow": False, "evaluation_id": f"ev{len(self.calls)}"}
        return {"allow": True, "evaluation_id": f"ev{len(self.calls)}"}


@contextlib.asynccontextmanager
async def gateway(tmp_path, monkeypatch, *, mode: str | None = "on", db_name: str = "a.db"):
    """A GatewayServer in *mode* with the harness's stand-ins in place of the
    services, the chain and the feed; yields ``(server, client, world)``."""
    from aiohttp.test_utils import TestClient, TestServer

    from gateway.server import GatewayServer
    from test_route_sweep import SWEEP_CONFIG

    gate = Gate()
    monkeypatch.setattr("gateway.security_gate.gate_action", gate)
    config = {**SWEEP_CONFIG, "memory_dir": str(tmp_path),
              "database": {"path": f"{tmp_path}/{db_name}"}}
    if mode is not None:
        config["engines"] = {"durable": {"mode": mode}}
    server = GatewayServer(config)
    server.react_loop.router.health_check = AsyncMock(return_value={"stand_in": True})
    effects = Effects()
    services = Services(effects)
    async with TestClient(TestServer(server.create_app())) as client:
        server.service_dispatcher = dispatcher(effects, services)
        if server._durable_engine is not None:
            server._durable_engine.attestations = Attestations(effects)
        db = server.react_loop.memory.db
        world = SimpleNamespace(effects=effects, services=services, gate=gate, db=db, final=None)
        # The database closes with the gateway: what the tables held at that
        # moment is kept, so a test can read them after the block.
        world.table = lambda name: world.final[name] if world.final is not None else rows(db, name)
        yield server, client, world
        world.final = {name: rows(db, name) for name in DURABLE_TABLES}


async def _post(client, params: dict, *, key: str | None, headers: dict | None = None,
                session_id: str = "s1"):
    sent = dict(headers or {})
    if key is not None:
        sent["Idempotency-Key"] = key
    resp = await client.post("/bridge/v1/action", json={
        "action": ACTION, "params": params, "session_id": session_id}, headers=sent)
    return resp.status, await resp.json()


async def _until(predicate, what: str, timeout_s: float = 3.0) -> None:
    deadline = time.monotonic() + timeout_s
    while not predicate():
        if time.monotonic() > deadline:
            raise AssertionError(f"timed out waiting for {what}")
        await asyncio.sleep(0.01)


async def test_a_replayed_key_gets_the_first_answer_byte_for_byte_and_runs_nothing(
        tmp_path, monkeypatch):
    async with gateway(tmp_path, monkeypatch) as (server, client, w):
        first_status, first = await _post(client, params_for(ACTION, 1), key="order-1")
        assert first_status == 200 and first["ok"] is True, first
        await _until(lambda: w.effects.count("feed") == 1 and w.effects.count("attest_sent") == 1,
                     "the outbox loop to deliver the first request's records")
        for _ in range(3):
            status, again = await _post(client, params_for(ACTION, 1), key="order-1")
            assert status == 200, again
            assert again["data"] == first["data"] and isinstance(again["data"], str), (
                f"the replay's answer is not the first one:\n{again['data']}\n{first['data']}")
        await server._durable_engine.loop.tick()
        assert w.effects.count("service") == 1, f"a replay ran the action: {w.effects.log}"
        assert w.effects.count("attest_sent") == 1 and w.effects.count("feed") == 1, w.effects.log
        assert w.gate.calls == [ACTION] * 4, (
            f"the gate was not asked on every replay: {w.gate.calls}")
        runs = w.table("workflow_runs")
        assert len(runs) == 1 and runs[0]["state"] == journal.COMPLETE, runs
        assert runs[0]["decision_ref"] == "ev1", "the run does not carry the gate decision's id"
        (bound,) = w.table("idempotency_keys")
        assert bound["run_id"] == runs[0]["run_id"] and bound["key"] != "order-1", bound
        assert bound["response_digest"] == journal.text_digest(first["data"]), (
            "the recorded digest is not the digest of the answer the client got")


async def test_a_different_request_under_the_same_key_is_a_conflict_and_runs_nothing(
        tmp_path, monkeypatch):
    async with gateway(tmp_path, monkeypatch) as (server, client, w):
        status, _first = await _post(client, params_for(ACTION, 1), key="order-2")
        assert status == 200
        status, body = await _post(client, params_for(ACTION, 2), key="order-2")
    assert status == 422 and body.get("code") == "idempotency_conflict", (status, body)
    assert "data" not in body, body
    assert w.effects.count("service") == 1 and w.effects.count("service", ACTION, 2) == 0, (
        f"the conflicting request ran: {w.effects.log}")


async def test_a_replay_while_the_first_request_is_in_its_call_is_in_progress(
        tmp_path, monkeypatch):
    async with gateway(tmp_path, monkeypatch) as (server, client, w):
        hold = asyncio.Event()
        w.services.gates[ACTION] = hold
        first = asyncio.ensure_future(_post(client, params_for(ACTION, 1), key="order-3"))
        await _until(lambda: [r["state"] for r in w.table("workflow_runs")] == ["RUNNING"],
                     "the first request's run to be RUNNING")
        status, body = await _post(client, params_for(ACTION, 1), key="order-3")
        assert status == 422 and body.get("code") == "idempotency_in_progress", (status, body)
        assert w.effects.count("service") == 0
        hold.set()
        first_status, first_body = await first
        assert first_status == 200 and first_body["ok"] is True, first_body
        status, replay = await _post(client, params_for(ACTION, 1), key="order-3")
    assert status == 200 and replay["data"] == first_body["data"], (status, replay)
    assert w.effects.count("service") == 1, f"the action ran more than once: {w.effects.log}"


@pytest.mark.parametrize("bad_key", ["k" * (keys.MAX_CLIENT_KEY + 1), "tab\there"])
async def test_an_invalid_key_is_a_400_and_runs_nothing(bad_key, tmp_path, monkeypatch):
    async with gateway(tmp_path, monkeypatch) as (server, client, w):
        status, body = await _post(client, params_for(ACTION, 1), key=bad_key)
    assert status == 400 and body.get("code") == "validation", (status, body)
    assert w.effects.count("service") == 0, f"a request with an invalid key ran: {w.effects.log}"
    assert w.table("workflow_runs") == [] and w.table("idempotency_keys") == []


async def test_a_key_from_another_caller_scope_never_sees_the_first_answer(tmp_path, monkeypatch):
    async with gateway(tmp_path, monkeypatch) as (server, client, w):
        now = time.time()
        for token, address in (("session-a", WALLET), ("session-b", OTHER)):
            await server.wallet_sessions.add(token=token, address=address, issued_at=now,
                                             expires_at=now + 3600)
        params = params_for(ACTION, 1)
        answers = []
        for headers in ({"X-Wallet-Session": "session-a"}, {"X-Wallet-Session": "session-b"},
                        {}):
            status, body = await _post(client, params, key="shared-key", headers=headers)
            assert status == 200 and body["ok"] is True, (headers, status, body)
            answers.append(body)
        # The first caller's own replay is still its first answer.
        status, replay = await _post(client, params, key="shared-key",
                                     headers={"X-Wallet-Session": "session-a"})
        assert status == 200 and replay["data"] == answers[0]["data"]
    assert w.effects.count("service", ACTION, 1) == 3, (
        f"one caller's key answered for another (the action ran "
        f"{w.effects.count('service', ACTION, 1)} time(s) for three callers)")
    runs = w.table("workflow_runs")
    assert len(runs) == 3 and len({r["key"] for r in runs}) == 3, runs
    callers = {journal.actor_hash(WALLET), journal.actor_hash(OTHER), ""}
    assert {r["actor_hash"] for r in runs} == callers, runs
    assert len(w.table("idempotency_keys")) == 3


async def test_the_bridges_key_scope_is_the_identity_the_gate_saw_not_x_wallet_address(
        tmp_path, monkeypatch):
    """On /bridge/v1/action the operator's ``X-Wallet-Address`` is not an
    identity: the gate and the dispatcher see the same caller either way, so the
    header does not open a second scope — the replay is the same caller's."""
    async with gateway(tmp_path, monkeypatch) as (server, client, w):
        params = params_for(ACTION, 1)
        status, first = await _post(client, params, key="op-key",
                                    headers={"X-Wallet-Address": WALLET})
        assert status == 200
        status, second = await _post(client, params, key="op-key",
                                     headers={"X-Wallet-Address": OTHER})
    assert status == 200 and second["data"] == first["data"], (status, second)
    assert w.effects.count("service") == 1, w.effects.log
    (run,) = w.table("workflow_runs")
    assert run["actor_hash"] == "", "the bridge dispatched under the X-Wallet-Address header"


async def test_a_replay_after_a_restart_is_answer_not_held_and_runs_nothing(
        tmp_path, monkeypatch):
    async with gateway(tmp_path, monkeypatch) as (server, client, w):
        status, first = await _post(client, params_for(ACTION, 1), key="order-4")
        assert status == 200
    assert w.effects.count("service") == 1
    async with gateway(tmp_path, monkeypatch) as (server2, client2, w2):
        status, body = await _post(client2, params_for(ACTION, 1), key="order-4")
        assert status == 422 and body.get("code") == "idempotency_answer_not_held", (status, body)
        assert "data" not in body
        assert w2.effects.count("service") == 0, f"the replay ran after a restart: {w2.effects.log}"
        runs = w2.table("workflow_runs")
        assert len(runs) == 1 and runs[0]["state"] == journal.COMPLETE, runs


async def test_a_replay_is_gated_again_and_a_refusal_there_is_a_403_with_no_replayed_answer(
        tmp_path, monkeypatch):
    async with gateway(tmp_path, monkeypatch) as (server, client, w):
        status, first = await _post(client, params_for(ACTION, 1), key="order-5")
        assert status == 200
        w.gate.refuse = True
        status, body = await _post(client, params_for(ACTION, 1), key="order-5")
    assert status == 403, (status, body)
    assert "data" not in body and first["data"] not in json.dumps(body), (
        f"a request the gate refused was given the first answer: {body}")
    assert w.gate.calls == [ACTION, ACTION], f"the replay was not gated again: {w.gate.calls}"
    assert w.effects.count("service") == 1


async def test_without_an_idempotency_key_every_request_runs(tmp_path, monkeypatch):
    async with gateway(tmp_path, monkeypatch) as (server, client, w):
        for _ in range(3):
            status, body = await _post(client, params_for(ACTION, 1), key=None)
            assert status == 200 and body["ok"] is True, body
    assert w.effects.count("service", ACTION, 1) == 3, w.effects.log
    runs = w.table("workflow_runs")
    assert len(runs) == 3 and all(r["key"] == "" for r in runs), runs
    assert w.table("idempotency_keys") == []


# ── the twin tools ─────────────────────────────────────────────────────────

TWIN_ANSWER = {"status": "success", "tx_hash": "0x" + "66" * 32, "settled": True}


@pytest.fixture(scope="module")
def tool_dispatcher():
    from runtime.tools.dispatcher import ToolDispatcher
    return ToolDispatcher({})


def _nft(tool_dispatcher, behaviour: str) -> list:
    calls: list = []

    async def nft(**kwargs):
        calls.append(dict(kwargs))
        if behaviour == "raises":
            raise Boom("the stand-in nft tool failed")
        if behaviour == "hangs":
            await asyncio.Event().wait()
        return dict(TWIN_ANSWER)
    tool_dispatcher.register("nft", nft, {"name": "nft"})
    return calls


TWINS = {
    # case -> (arguments, behaviour, the run's state or None for no run, its last step, detail)
    "mint": ({"action": "mint", "to": WALLET, "token_uri": "ipfs://x"}, "returns",
             journal.COMPLETE, ("return", "success"), None),
    "get_owner": ({"action": "get_owner", "token_id": 1}, "returns", None, None, None),
    "timeout": ({"action": "mint", "to": WALLET}, "hangs", journal.FAIL,
                ("unknown_effect", "timed_out"), "call_timed_out"),
    "raise": ({"action": "transfer", "to": WALLET, "token_id": 1}, "raises", journal.FAIL,
              ("raise", "raised"), "raised:Boom"),
}


@pytest.mark.parametrize("case", list(TWINS))
async def test_a_twin_signing_call_is_journaled_and_a_read_is_not(
        case, tool_dispatcher, db, clock, monkeypatch):
    arguments, behaviour, state, last, detail = TWINS[case]
    monkeypatch.setattr("runtime.tools.dispatcher.TOOL_TIMEOUT", 0.05)
    calls = _nft(tool_dispatcher, behaviour)
    with installed(engine(db, "on", clock, Effects())):
        outcome = await tool_dispatcher.dispatch("nft", dict(arguments), agent_name="neo",
                                                 caller_identity=WALLET, caller_source="session")
    assert len(calls) == 1, f"{case}: the handler ran {len(calls)} time(s)"
    assert outcome.ok is (behaviour == "returns"), f"{case}: {outcome!r}"
    if behaviour == "hangs":
        assert outcome.code == "tool_timeout", outcome
    runs = rows(db, "workflow_runs")
    if state is None:
        assert runs == [], f"a twin read was journaled: {runs}"
        return
    assert len(runs) == 1, f"{case}: {len(runs)} runs for one signing call"
    run = runs[0]
    assert run["state"] == state, f"{case}: the run ended {run['state']}, expected {state}"
    assert (run["action"], run["service"]) == (f"nft.{arguments['action']}", "nft"), run
    assert run["actor_hash"] == journal.actor_hash(WALLET)
    assert run["params_digest"] == journal.digest(arguments), "the run digests other params"
    steps = journal.get_steps(db, run["run_id"])
    assert [(s["name"], s["state"]) for s in steps] == [
        ("start", "opened"), ("call", "began"), last], f"{case}: {steps}"
    if detail is not None:
        assert steps[-1]["detail"] == detail, steps[-1]
    assert rows(db, "outbox") == [] and rows(db, "idempotency_keys") == []


async def test_a_twin_signing_call_whose_run_cannot_be_written_is_not_made(
        tool_dispatcher, db, clock, monkeypatch):
    calls = _nft(tool_dispatcher, "returns")

    def unwritable(db_, work, *, wait):
        raise sqlite3.OperationalError("database is locked")
    monkeypatch.setattr(journal, "transaction", unwritable)
    with installed(engine(db, "on", clock, Effects())):
        outcome = await tool_dispatcher.dispatch(
            "nft", {"action": "mint", "to": WALLET}, agent_name="neo",
            caller_identity=WALLET, caller_source="session")
        read = await tool_dispatcher.dispatch(
            "nft", {"action": "get_owner", "token_id": 1}, agent_name="neo",
            caller_identity=WALLET, caller_source="session")
    assert [c["action"] for c in calls] == ["get_owner"], (
        f"a signing call that could not be recorded was made: {calls}")
    assert outcome.ok is False and outcome.code, f"not a failure outcome: {outcome!r}"
    assert "not made" in outcome.model_text, outcome.model_text
    assert read.ok is True, "an unrecordable journal refused a read, which it never journals"
    assert rows(db, "workflow_runs") == []


# ── the mode ───────────────────────────────────────────────────────────────

@pytest.mark.parametrize("config, env, expected", [
    ({"engines": {"durable": {"mode": "on"}}}, None, "on"),
    ({"engines": {"durable": {"mode": "shadow"}}}, None, "shadow"),
    ({"engines": {"durable": {"mode": " ON "}}}, None, "on"),
    ({}, None, "off"),
    ({"engines": {"durable": {}}}, None, "off"),
    ("not a config", None, "off"),
    ({"engines": {"durable": {"mode": "on"}}}, "shadow", "shadow"),
    ({"engines": {"durable": {"mode": "on"}}}, "off", "off"),
    ({}, "on", "on"),
    ({"engines": {"durable": {"mode": "on"}}}, "", "on"),
    ({"engines": {"durable": {"mode": "yes"}}}, None, "off"),
    ({"engines": {"durable": {"mode": True}}}, None, "off"),
    ({"engines": {"durable": {"mode": "on"}}}, "enabled", "off"),
])
def test_durable_mode_reads_config_the_environment_wins_and_unknown_is_off(
        config, env, expected, monkeypatch):
    if env is not None:
        monkeypatch.setenv("MATRIX_DURABLE_MODE", env)
    assert wiring.durable_mode(config) == expected, (config, env)


def test_build_engine_builds_nothing_when_the_mode_is_off(db, monkeypatch):
    monkeypatch.setenv("MATRIX_DURABLE_MODE", "off")
    assert wiring.build_engine({"engines": {"durable": {"mode": "on"}}}, db) is None
    monkeypatch.setenv("MATRIX_DURABLE_MODE", "sideways")
    assert wiring.build_engine({}, db) is None


# ── /ready and the gateway's own engine ────────────────────────────────────

async def test_ready_follows_the_outbox_loop_in_mode_on(tmp_path, monkeypatch):
    async with gateway(tmp_path, monkeypatch) as (server, client, w):
        eng = server._durable_engine
        assert eng is not None and eng.mode == "on" and wiring.current() is eng

        async def ready():
            resp = await client.get("/ready")
            body = await resp.json()
            assert set(body) == {"ready", "ref"}, f"/ready's body carries detail: {body}"
            return resp.status

        assert await ready() == 200, "/ready is not ready while the loop runs"
        await eng.loop.stop()
        assert await ready() == 503, "/ready is ready with the outbox loop stopped"

        eng.start()
        assert await ready() == 200, "/ready is not ready after the loop started again"
        eng.loop._task.cancel()
        await _until(lambda: eng.loop._task.done(), "the cancelled loop task to end")
        assert await ready() == 503, "/ready is ready with the outbox loop cancelled"

        ticks = eng.loop.ticks
        eng.start()
        await _until(lambda: eng.loop.ticks > ticks, "the restarted loop's first tick")
        eng.loop.last_tick_at = eng.loop.last_progress_at = time.time() - 100_000
        assert await ready() == 503, "/ready is ready with a loop that stopped ticking"


async def test_ready_with_the_mode_off_checks_nothing_durable(tmp_path, monkeypatch):
    before = wiring.current()
    async with gateway(tmp_path, monkeypatch, mode="off") as (server, client, w):
        assert server._durable_engine is None and wiring.current() is before
        resp = await client.get("/ready")
        assert resp.status == 200, await resp.text()


async def test_the_gateway_stops_and_uninstalls_its_own_engine_and_only_its_own(
        tmp_path, monkeypatch):
    before = wiring.current()
    async with gateway(tmp_path, monkeypatch) as (server, client, w):
        eng = server._durable_engine
        assert wiring.current() is eng and eng.loop.alive
    assert wiring.current() is before, "the gateway left its engine installed after cleanup"
    assert not eng.loop.alive, "the gateway left its outbox loop running after cleanup"
    assert server._durable_engine is None

    stranger_db = open_db(tmp_path / "stranger.db")
    stranger = engine(stranger_db, "on", Clock(), Effects())
    try:
        with installed(stranger):
            async with gateway(tmp_path, monkeypatch, db_name="b.db") as (server2, client2, w2):
                eng2 = server2._durable_engine
                assert wiring.current() is eng2
                wiring.install(stranger)          # another installer replaced it mid-life
            assert wiring.current() is stranger, (
                "the gateway uninstalled an engine it did not install")
            assert not eng2.loop.alive, "the gateway did not stop its own loop"
    finally:
        await stranger_db.close()
    assert wiring.current() is before
