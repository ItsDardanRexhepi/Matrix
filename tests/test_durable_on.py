"""Durable execution (engines Phase 2), mode on: lifecycle authority, and only that.

With engines.durable.mode = "on" and the canary covering them, the engine owns
three things for a state-modifying action and nothing else:

* its RUN — recorded before the service is called; an action whose run cannot
  be recorded is not called; a raise is FAIL, a call that never answered stays
  RUNNING;
* its DELIVERY — the attestation and the feed entry are outbox rows written with
  the run's terminal state and delivered by the outbox loop, once; the
  dispatcher no longer hands them to the batch queue or to create_task;
* its REPLAY — on /bridge/v1/action a replayed Idempotency-Key gets the first
  answer and runs nothing.

And these tests pin what it does NOT own: whether the action is allowed (the
gate still decides, replay or not), and what its outcome was (the dispatcher's
own verdict is what the step records, and a refusal delivers nothing).
"""

from __future__ import annotations

import asyncio
import json
import logging
import sqlite3
import sys
from unittest.mock import AsyncMock

import pytest

sys.path.insert(0, "tests")

from aiohttp.test_utils import TestClient, TestServer  # noqa: E402

from durable_harness import (  # noqa: E402
    BROADCAST, REFUSED, SETTLED, WALLET, Clock, FakeEAS, FeedSpy, World, body_for, database,
    engine, feed_rows, gateway, stub_dispatcher,
)
from runtime.durable import journal, keys, outbox, wiring  # noqa: E402

ACTION = "transfer_stablecoin"


@pytest.fixture(autouse=True)
def _no_env_mode(monkeypatch):
    monkeypatch.delenv("MATRIX_DURABLE_MODE", raising=False)


@pytest.fixture
def installed():
    """Install an engine for one test and always take it out again."""
    holder = {}

    def _install(eng):
        holder["previous"] = wiring.install(eng)
        return eng
    yield _install
    wiring.install(holder.get("previous"))


def _runs(db):
    return [dict(r) for r in db.fetchall_sync("SELECT * FROM workflow_runs ORDER BY started_at")]


def _outbox(db):
    return [dict(r) for r in db.fetchall_sync("SELECT * FROM outbox ORDER BY id")]


# ── the dispatcher, owned ────────────────────────────────────────────────────

async def test_a_settled_action_is_journaled_and_its_records_delivered_once(tmp_path, monkeypatch,
                                                                          installed):
    world = World()
    db = database(tmp_path / "a.db")
    feed = FeedSpy(db, world)
    eng = installed(engine(db, world=world, feed=feed, monkeypatch=monkeypatch))
    attested: list = []
    d = stub_dispatcher(world, SETTLED, feed=feed, attested=attested)

    answer = json.loads(await d.execute(ACTION, params={"to": WALLET, "amount": 5},
                                        caller_identity=WALLET))
    await asyncio.sleep(0)
    assert answer["status"] == "ok" and world.count("service") == 1
    assert attested == [] and feed.calls == 0, "the dispatcher delivered nothing itself"
    (run,) = _runs(db)
    assert run["state"] == journal.COMPLETE and run["actor_hash"] == journal.actor_hash(WALLET)
    assert [(s["kind"], s["state"]) for s in journal.get_steps(db, run["run_id"])] == [
        ("start", "recorded"), ("call", "attempting"), ("return", "settled")]
    assert [(r["kind"], r["state"]) for r in _outbox(db)] == [("attest", "pending"),
                                                                ("feed", "pending")]

    assert await eng.loop.tick() == 2
    assert world.count("attest") == 1 and len(feed_rows(db)) == 1
    assert [(r["kind"], r["state"], r["payload"]) for r in _outbox(db)] == [
        ("attest", "done", ""), ("feed", "done", "")]
    for _ in range(3):
        assert await eng.loop.tick() == 0
    assert world.count("attest") == 1 and len(feed_rows(db)) == 1
    (row,) = feed_rows(db)
    assert row["id"] == outbox.feed_event_id(run["run_id"]) and row["event_type"] == ACTION


async def test_the_outbox_carries_what_the_legacy_path_would_have_delivered(tmp_path, monkeypatch,
                                                                            installed):
    """Same builder, same content: the attestation data and the feed entry the
    loop delivers are the ones the dispatcher hands the legacy path."""
    world = World()
    db = database(tmp_path / "a.db")
    installed(engine(db, world=world, feed=FeedSpy(db, world), monkeypatch=monkeypatch))
    d = stub_dispatcher(world, SETTLED, feed=object())
    await d.execute(ACTION, params={"to": WALLET, "amount": 5, "wallet": "0xCLAIMED"},
                    caller_identity=WALLET)
    rows = {r["kind"]: json.loads(r["payload"]) for r in _outbox(db)}
    params = {"to": WALLET, "amount": 5, "wallet": "0xCLAIMED"}
    expected_attest = d._attestation_request(ACTION, "stablecoin", params, actor=WALLET,
                                             actor_source="authenticated",
                                             actor_claimed="0xCLAIMED")
    for volatile in ("timestamp", "params_hash"):
        rows["attest"]["data"].pop(volatile)
        expected_attest["data"].pop(volatile)
    assert rows["attest"] == expected_attest
    assert rows["feed"] == d._feed_publication(ACTION, "stablecoin", params, SETTLED,
                                               actor=WALLET, actor_claimed="0xCLAIMED")


@pytest.mark.parametrize("result,state,word", [
    (REFUSED, journal.FAIL, "refused"),
    (BROADCAST, journal.COMPLETE, "broadcast"),
])
async def test_a_refusal_or_a_broadcast_delivers_nothing(result, state, word, tmp_path, monkeypatch,
                                                         installed, caplog):
    world = World()
    db = database(tmp_path / "a.db")
    eng = installed(engine(db, world=world, feed=FeedSpy(db, world), monkeypatch=monkeypatch))
    d = stub_dispatcher(world, result, feed=object())
    with caplog.at_level(logging.INFO):
        await d.execute(ACTION, params={"to": WALLET}, caller_identity=WALLET)
    (run,) = _runs(db)
    assert run["state"] == state
    assert journal.get_steps(db, run["run_id"])[-1]["state"] == word
    assert _outbox(db) == []
    await eng.loop.tick()
    assert world.count("attest") == 0 and feed_rows(db) == []
    said = "ACTION DECLINED" if word == "refused" else "ACTION BROADCAST"
    assert any(said in r.getMessage() for r in caplog.records), "the legacy record still runs"


async def test_the_twins_canary_leaves_state_modifying_actions_on_the_legacy_path(tmp_path, monkeypatch,
                                                                                  installed):
    world = World()
    db = database(tmp_path / "a.db")
    installed(engine(db, canary="twins", world=world, monkeypatch=monkeypatch))
    attested: list = []
    d = stub_dispatcher(world, SETTLED, attested=attested)
    await d.execute(ACTION, params={"to": WALLET}, caller_identity=WALLET)
    assert len(attested) == 1, "the dispatcher attested it itself"
    assert [(r["kind"], r["state"]) for r in _outbox(db)] == [("attest", "recorded")]
    assert _runs(db)[0]["state"] == journal.COMPLETE


async def test_an_action_whose_run_cannot_be_recorded_is_not_run(tmp_path, monkeypatch, installed):
    world = World()
    db = database(tmp_path / "a.db")
    db._conn.execute("PRAGMA busy_timeout = 50")
    installed(engine(db, world=world, monkeypatch=monkeypatch))
    other = sqlite3.connect(tmp_path / "a.db", isolation_level=None)
    other.execute("BEGIN IMMEDIATE")
    try:
        answer = json.loads(await stub_dispatcher(world, SETTLED).execute(
            ACTION, params={"to": WALLET}, caller_identity=WALLET))
    finally:
        other.execute("ROLLBACK")
        other.close()
    assert answer["status"] == "error" and answer["error_category"] == "service_unavailable"
    assert "Nothing was executed" in answer["error"]
    assert world.effects == [] and _runs(db) == []


async def test_a_raise_is_FAIL_and_a_call_that_never_answered_stays_RUNNING(tmp_path, monkeypatch,
                                                                           installed):
    world = World()
    db = database(tmp_path / "a.db")
    installed(engine(db, world=world, monkeypatch=monkeypatch))

    def boom(_method, _kwargs):
        raise RuntimeError("rpc dropped")
    answer = json.loads(await stub_dispatcher(world, boom).execute(ACTION, params={"to": WALLET}))
    assert answer["error_category"] == "service_error"
    (failed,) = _runs(db)
    assert failed["state"] == journal.FAIL
    assert journal.get_steps(db, failed["run_id"])[-1]["kind"] == journal.STEP_RAISE

    gate = asyncio.Event()

    async def hold(when, _kwargs):
        if when == "after":
            await gate.wait()
    task = asyncio.create_task(stub_dispatcher(world, SETTLED, during=hold).execute(
        ACTION, params={"to": WALLET}))
    for _ in range(5):
        await asyncio.sleep(0)
    task.cancel()
    with pytest.raises(asyncio.CancelledError):
        await task
    running = [r for r in _runs(db) if r["run_id"] != failed["run_id"]][0]
    assert running["state"] == journal.RUNNING and running["terminal_at"] is None
    assert journal.get_steps(db, running["run_id"])[-1]["state"] == "cancelled"
    assert _outbox(db) == [], "nothing to deliver for a call nobody saw answer"


# ── the twin tools ───────────────────────────────────────────────────────────

async def test_a_twin_signing_call_is_journaled_and_a_read_is_not(tmp_path, monkeypatch, installed):
    from runtime.tools.dispatcher import ToolDispatcher
    world = World()
    db = database(tmp_path / "a.db")
    installed(engine(db, canary="twins", world=world, monkeypatch=monkeypatch))
    tools = ToolDispatcher({})

    async def payment(**kwargs):
        world.effects.append(("twin", kwargs.get("action")))
        return {"status": "success", "tx_hash": "0x" + "ef" * 32}
    tools._tools["payment"] = payment
    ok = await tools.dispatch("payment", {"action": "send_eth", "to": WALLET, "amount": 1},
                              agent_name="neo", caller_identity=WALLET)
    read = await tools.dispatch("payment", {"action": "get_balance"}, agent_name="neo")
    assert ok.ok and read.ok and world.count("twin") == 2
    (run,) = _runs(db)
    assert (run["action"], run["service"], run["state"]) == ("payment.send_eth", "payment",
                                                             journal.COMPLETE)
    assert journal.get_steps(db, run["run_id"])[-1]["tx_hash"] == "0x" + "ef" * 32


async def test_a_twin_call_that_timed_out_stays_RUNNING_and_one_not_recorded_is_not_made(
        tmp_path, monkeypatch, installed):
    import runtime.tools.dispatcher as tool_dispatcher
    world = World()
    db = database(tmp_path / "a.db")
    installed(engine(db, canary="twins", world=world, monkeypatch=monkeypatch))
    tools = tool_dispatcher.ToolDispatcher({})
    monkeypatch.setattr(tool_dispatcher, "TOOL_TIMEOUT", 0.05)

    async def slow(**kwargs):
        world.effects.append(("twin", kwargs.get("action")))
        await asyncio.sleep(10)
    tools._tools["stake"] = slow
    outcome = await tools.dispatch("stake", {"action": "stake", "amount": 1}, agent_name="neo")
    assert outcome.code == "tool_timeout"
    (run,) = _runs(db)
    assert run["state"] == journal.RUNNING
    assert journal.get_steps(db, run["run_id"])[-1]["state"] == "timed_out"

    db._conn.execute("PRAGMA busy_timeout = 50")
    other = sqlite3.connect(tmp_path / "a.db", isolation_level=None)
    other.execute("BEGIN IMMEDIATE")
    try:
        refused = await tools.dispatch("stake", {"action": "stake", "amount": 1}, agent_name="neo")
    finally:
        other.execute("ROLLBACK")
        other.close()
    assert refused.ok is False and refused.code == "durable_unavailable"
    assert world.count("twin") == 1, "the unrecorded call was not made"


# ── the bridge's Idempotency-Key ─────────────────────────────────────────────

async def _on_gateway(tmp_path, monkeypatch, world, result=SETTLED, **kw):
    """A gateway in mode on over the state-modifying canary, with the stub
    services, a fake chain for the attestation, and a clock the test moves."""
    from runtime.blockchain.services.attestation import batch_processor as bp
    monkeypatch.setattr(bp, "_eas_client_for", lambda _cfg: FakeEAS(world), raising=False)
    server = gateway(tmp_path, {"mode": "on", "canary": "state_modifying"})
    return server


async def _post(client, body, key=None, **headers):
    if key is not None:
        headers["Idempotency-Key"] = key
    resp = await client.post("/bridge/v1/action", json=body, headers=headers)
    return resp, json.loads(await resp.text())


async def test_a_replayed_key_gets_the_first_answer_and_runs_nothing(tmp_path, monkeypatch):
    world = World()
    server = await _on_gateway(tmp_path, monkeypatch, world)
    async with TestClient(TestServer(server.create_app())) as client:
        eng = wiring.current()
        assert eng is server._durable_engine and eng.owns(wiring.STATE_MODIFYING)
        server.service_dispatcher = stub_dispatcher(world, SETTLED,
                                                    feed=server.social_feed_engine)
        first, first_body = await _post(client, body_for(ACTION), key="a-key-0001")
        replays = [await _post(client, body_for(ACTION), key="a-key-0001") for _ in range(5)]
        await eng.loop.tick()
    assert first.status == 200 and "replayed" not in first_body
    for resp, body in replays:
        assert resp.status == 200 and resp.headers["Idempotent-Replayed"] == "true"
        assert body == {**first_body, "replayed": True}
    assert world.count("service") == 1 and world.count("attest") == 1


async def test_a_key_used_for_another_request_is_refused_and_runs_nothing(tmp_path, monkeypatch):
    world = World()
    server = await _on_gateway(tmp_path, monkeypatch, world)
    async with TestClient(TestServer(server.create_app())) as client:
        server.service_dispatcher = stub_dispatcher(world, SETTLED)
        await _post(client, body_for(ACTION, marker=1), key="a-key-0002")
        resp, body = await _post(client, body_for(ACTION, marker=2), key="a-key-0002")
        other_action = await _post(client, body_for("mint_nft", marker=1), key="a-key-0002")
    assert resp.status == 409 and body["code"] == "idempotency_conflict" and "run" not in body
    assert other_action[0].status == 409
    assert world.count("service") == 1


async def test_a_key_whose_first_request_is_still_running_is_refused(tmp_path, monkeypatch):
    world = World()
    hold = asyncio.Event()
    entered = asyncio.Event()

    async def during(when, _kwargs):
        if when == "after":
            entered.set()
            await hold.wait()
    server = await _on_gateway(tmp_path, monkeypatch, world)
    async with TestClient(TestServer(server.create_app())) as client:
        server.service_dispatcher = stub_dispatcher(world, SETTLED, during=during)
        first = asyncio.create_task(_post(client, body_for(ACTION), key="a-key-0003"))
        await asyncio.wait_for(entered.wait(), 5)
        resp, body = await _post(client, body_for(ACTION), key="a-key-0003")
        hold.set()
        done, _ = await first
    assert resp.status == 409 and body["run"]["state"] == journal.RUNNING
    assert done.status == 200 and world.count("service") == 1


async def test_a_replay_is_gated_again_and_a_refused_request_binds_no_key(tmp_path, monkeypatch):
    import gateway.security_gate as security_gate
    world = World()
    server = await _on_gateway(tmp_path, monkeypatch, world)
    decisions = iter([{"allow": False, "reason": "no"}, {"allow": True}, {"allow": False}])
    gate_calls: list = []

    async def gate(action_type, *a, **k):
        gate_calls.append(action_type)
        return next(decisions)
    monkeypatch.setattr(security_gate, "gate_action", gate)
    async with TestClient(TestServer(server.create_app())) as client:
        server.service_dispatcher = stub_dispatcher(world, SETTLED)
        denied, _ = await _post(client, body_for(ACTION), key="a-key-0004")
        allowed, _ = await _post(client, body_for(ACTION), key="a-key-0004")
        replay_denied, _ = await _post(client, body_for(ACTION), key="a-key-0004")
    assert [denied.status, allowed.status, replay_denied.status] == [403, 200, 403]
    assert len(gate_calls) == 3, "the replay went through the gate like any request"
    assert world.count("service") == 1


async def test_a_request_that_never_reached_its_service_gives_its_key_back(tmp_path, monkeypatch):
    world = World()
    server = await _on_gateway(tmp_path, monkeypatch, world)
    available = {"now": False}
    async with TestClient(TestServer(server.create_app())) as client:
        d = stub_dispatcher(world, SETTLED)
        registry = d._get_registry()

        def get(name):
            if not available["now"] and name != "attestation":
                raise KeyError(name)
            return registry.get(name)
        d._get_registry = lambda: type("R", (), {"get": staticmethod(get)})()
        server.service_dispatcher = d
        unavailable, _ = await _post(client, body_for(ACTION), key="a-key-0005")
        available["now"] = True
        ran, _ = await _post(client, body_for(ACTION), key="a-key-0005")
        replay, _ = await _post(client, body_for(ACTION), key="a-key-0005")
        db = server.react_loop.memory.db
        states = sorted(r["state"] for r in _runs(db))
    assert [unavailable.status, ran.status, replay.status] == [503, 200, 200]
    assert replay.headers.get("Idempotent-Replayed") == "true"
    assert states == [journal.ABORT, journal.COMPLETE] and world.count("service") == 1


async def test_one_callers_key_never_answers_for_another(tmp_path, monkeypatch):
    world = World()
    server = await _on_gateway(tmp_path, monkeypatch, world)
    server._session_identity = lambda request: request.headers.get("X-Test-Identity", "")
    async with TestClient(TestServer(server.create_app())) as client:
        server.service_dispatcher = stub_dispatcher(world, SETTLED)
        a, _ = await _post(client, body_for(ACTION), "a-key-0006", **{"X-Test-Identity": "0xA"})
        b, body_b = await _post(client, body_for(ACTION), "a-key-0006", **{"X-Test-Identity": "0xB"})
    assert a.status == b.status == 200 and "replayed" not in body_b
    assert world.count("service") == 2


async def test_a_read_is_never_keyed_and_a_malformed_key_is_refused(tmp_path, monkeypatch):
    from runtime.blockchain.services.service_dispatcher import ACTION_MAP, _STATE_MODIFYING_ACTIONS
    read = sorted(set(ACTION_MAP) - set(_STATE_MODIFYING_ACTIONS))[0]
    world = World()
    server = await _on_gateway(tmp_path, monkeypatch, world)
    async with TestClient(TestServer(server.create_app())) as client:
        server.service_dispatcher = stub_dispatcher(world, {"status": "success", "value": 1})
        for _ in range(2):
            resp, _ = await _post(client, body_for(read), key="a-key-0007")
            assert resp.status == 200 and "Idempotent-Replayed" not in resp.headers
        bad, body = await _post(client, body_for(ACTION), key="has spaces in it")
    assert world.count("service") == 2, "a read runs every time"
    assert bad.status == 400 and body["code"] == "invalid_request"


async def test_an_answer_is_kept_24_hours_then_the_key_still_runs_nothing(tmp_path, monkeypatch):
    world = World()
    server = await _on_gateway(tmp_path, monkeypatch, world)
    clock = Clock()
    async with TestClient(TestServer(server.create_app())) as client:
        eng = wiring.current()
        eng._clock = clock
        server.service_dispatcher = stub_dispatcher(world, SETTLED)
        await _post(client, body_for(ACTION), key="a-key-0008")
        clock.advance(keys.ANSWER_KEPT_S + 1)
        eng.maintain()
        resp, body = await _post(client, body_for(ACTION), key="a-key-0008")
        stored = server.react_loop.memory.db.fetchall_sync(
            "SELECT response FROM idempotency_keys")[0][0]
    assert resp.status == 409 and body["run"]["state"] == journal.COMPLETE
    assert stored is None and world.count("service") == 1


async def test_a_recorded_answer_withholds_secret_named_fields(tmp_path, monkeypatch):
    world = World()
    server = await _on_gateway(tmp_path, monkeypatch, world)
    async with TestClient(TestServer(server.create_app())) as client:
        server.service_dispatcher = stub_dispatcher(
            world, {"status": "success", "mnemonic": "alpha beta", "tx_hash": "0x1"})
        first, first_body = await _post(client, body_for(ACTION), key="a-key-0009")
        replay, replay_body = await _post(client, body_for(ACTION), key="a-key-0009")
        stored = server.react_loop.memory.db.fetchall_sync(
            "SELECT response FROM idempotency_keys")[0][0]
    assert "alpha beta" in first_body["data"], "the first caller got its answer"
    assert "alpha beta" not in stored and "alpha beta" not in json.dumps(replay_body)
    assert json.loads(replay_body["data"])["result"]["mnemonic"] == keys.WITHHELD


async def test_ready_fails_when_the_outbox_loop_is_not_running(tmp_path, monkeypatch):
    world = World()
    server = await _on_gateway(tmp_path, monkeypatch, world)
    server.react_loop.router.health_check = AsyncMock(return_value={"ollama": True})
    async with TestClient(TestServer(server.create_app())) as client:
        assert (await client.get("/ready")).status == 200
        await wiring.current().loop.stop()
        resp = await client.get("/ready")
        body = await resp.json()
    assert resp.status == 503 and body["ready"] is False and set(body) == {"ready", "ref"}
    assert wiring.current() is None


# ── a write that is dropped never makes another record false ────────────────

def _drop(db, calls):
    """Make the durable transactions numbered in *calls* (1-based, in the order
    the engine writes them) fail the way a database another writer holds does.
    For a keyed bridge request they are: 1 the key's claim, 2 the run's RUNNING
    mark, 3 its answer and terminal state, 4 the answer the request sent."""
    real = db.transaction_sync
    seen = {"n": 0}

    def flaky(work, *, wait=True):
        seen["n"] += 1
        if seen["n"] in calls:
            raise sqlite3.OperationalError("database is locked (injected)")
        return real(work, wait=wait)
    db.transaction_sync = flaky
    return lambda: setattr(db, "transaction_sync", real)


def _steps_of(db, run_id):
    return [(s["kind"], s["state"]) for s in journal.get_steps(db, run_id)]


NOT_OWNING = [{"mode": "shadow", "canary": "state_modifying"}, {"mode": "on", "canary": "twins"}]


@pytest.mark.parametrize("durable", NOT_OWNING, ids=["shadow", "on-twins"])
@pytest.mark.parametrize("dropped,state,steps,answer_kept", [
    # the RUNNING mark only: written late, with the answer, saying so
    ({2}, journal.COMPLETE,
     [("start", "observed"), ("call", "began_before_recorded"), ("return", "settled")], True),
    # the mark and the run's end: the request's own answer marks it late
    ({2, 3}, journal.RUNNING,
     [("start", "observed"), ("call", "began_before_recorded"),
      ("unknown_effect", "no_answer_recorded")], True),
    # everything after the claim: recovery leaves it START, and keeps the key
    ({2, 3, 4}, journal.START, [("start", "observed"), ("unknown_effect", "not_known_if_called")],
     False),
], ids=["mark", "mark+end", "mark+end+answer"])
async def test_a_run_whose_mark_was_dropped_is_never_journaled_not_attempted(
        durable, dropped, state, steps, answer_kept, tmp_path, monkeypatch):
    """An engine that does not own a keyed request's run (shadow; on with the
    twins canary) drops a write it cannot make at once, and the action runs, as
    it does with the mode off. The journal then says the call began — never
    ABORT/not_attempted — and the key stays bound, so when the canary later
    moves to state_modifying a replay under the same key does not act again."""
    import time
    world = World()
    from runtime.blockchain.services.attestation import batch_processor as bp
    monkeypatch.setattr(bp, "_eas_client_for", lambda _cfg: FakeEAS(world), raising=False)
    server = gateway(tmp_path, durable)
    async with TestClient(TestServer(server.create_app())) as client:
        eng = wiring.current()
        await eng.loop.stop()
        db = server.react_loop.memory.db
        server.service_dispatcher = stub_dispatcher(world, SETTLED)
        restore = _drop(db, dropped)
        try:
            first, _ = await _post(client, body_for(ACTION), key="drop-key-0001")
        finally:
            restore()
        assert first.status == 200 and world.count("service") == 1
        # A later process, past every window, recovers the file.
        later = engine(db, world=world, monkeypatch=monkeypatch,
                       clock=Clock(time.time() + journal.ABANDONED_AFTER_S + 60))
        later.maintain()
        (run,) = _runs(db)
        assert run["state"] == state and run["state"] != journal.ABORT
        assert _steps_of(db, run["run_id"]) == steps
        (key,) = db.fetchall_sync("SELECT run_id, status FROM idempotency_keys")
        assert key[0] == run["run_id"] and (key[1] == 200) is answer_kept
        # The operator moves the canary to state_modifying; the client replays.
        previous = wiring.install(engine(db, world=world, monkeypatch=monkeypatch))
        try:
            replay, body = await _post(client, body_for(ACTION), key="drop-key-0001")
        finally:
            wiring.install(previous)
    assert world.count("service") == 1, "the replay acted again"
    if answer_kept:
        assert replay.status == 200 and replay.headers.get("Idempotent-Replayed") == "true"
    else:
        assert replay.status == 409 and body["run"] == {"run_id": run["run_id"],
                                                         "state": journal.START}


async def test_an_owned_run_whose_mark_is_dropped_is_not_run_and_gives_its_key_back(tmp_path,
                                                                                    monkeypatch):
    """The contrast: an engine that owns the run does not call what it could
    not mark, so there — and only there — START means not attempted."""
    world = World()
    server = await _on_gateway(tmp_path, monkeypatch, world)
    async with TestClient(TestServer(server.create_app())) as client:
        await wiring.current().loop.stop()
        db = server.react_loop.memory.db
        server.service_dispatcher = stub_dispatcher(world, SETTLED)
        restore = _drop(db, {2})
        try:
            first, _ = await _post(client, body_for(ACTION), key="drop-key-0002")
        finally:
            restore()
        (run,) = _runs(db)
        steps = _steps_of(db, run["run_id"])
        keys_left = db.fetchall_sync("SELECT COUNT(*) FROM idempotency_keys")[0][0]
        again, _ = await _post(client, body_for(ACTION), key="drop-key-0002")
    assert first.status == 503 and world.count("service") == 1
    assert run["state"] == journal.ABORT and steps == [("start", "recorded"),
                                                       ("abort", "not_attempted")]
    assert keys_left == 0 and again.status == 200 and "Idempotent-Replayed" not in again.headers


@pytest.mark.parametrize("result", [SETTLED, REFUSED, BROADCAST], ids=["settled", "refused",
                                                                       "broadcast"])
async def test_an_answer_lost_after_the_run_ended_is_still_the_replays(result, tmp_path, monkeypatch):
    """The packet's X1.W4: the process dies after the run's terminal commit and
    before the request records what it sent. The run's end recorded the answer
    in its own transaction, so the replay gets it — the same status, marked
    replayed — and nothing runs twice."""
    world = World()
    server = await _on_gateway(tmp_path, monkeypatch, world)
    async with TestClient(TestServer(server.create_app())) as client:
        eng = wiring.current()
        server.service_dispatcher = stub_dispatcher(world, result)
        sent = eng.bridge_finish
        eng.bridge_finish = lambda claim, *, status, body: None
        try:
            first, first_body = await _post(client, body_for(ACTION), key="lost-key-0001")
        finally:
            eng.bridge_finish = sent
        replay, replay_body = await _post(client, body_for(ACTION), key="lost-key-0001")
    assert replay.status == first.status and replay.headers["Idempotent-Replayed"] == "true"
    assert replay_body["ok"] == first_body["ok"] and replay_body["replayed"] is True
    assert world.count("service") == 1


async def test_a_twin_run_names_a_declared_verb_or_undeclared_never_the_models_string(
        tmp_path, monkeypatch, installed):
    """The verb of a twin call is the model's own arguments["action"], unbounded,
    and an undeclared one is treated as signing. The run is named by the verb
    the tool declares, or ``undeclared``; the string itself is only inside the
    parameters' digest."""
    from runtime.tools.dispatcher import ToolDispatcher
    world = World()
    db = database(tmp_path / "a.db")
    installed(engine(db, mode="shadow", canary="twins", world=world, monkeypatch=monkeypatch))
    tools = ToolDispatcher({})

    async def payment(**kwargs):
        world.effects.append(("twin", kwargs.get("action")))
        return {"status": "success"}
    tools._tools["payment"] = payment
    free_text = "send to jane.doe@example.com phone 555-0100 " + "x" * 300
    await tools.dispatch("payment", {"action": free_text, "to": WALLET}, agent_name="neo")
    await tools.dispatch("payment", {"action": "send_eth", "to": WALLET}, agent_name="neo")
    assert sorted(r["action"] for r in _runs(db)) == ["payment.send_eth", "payment.undeclared"]
    dump = "\n".join(str(tuple(r)) for table in ("workflow_runs", "workflow_steps", "outbox",
                                                  "idempotency_keys")
                     for r in db.fetchall_sync(f"SELECT * FROM {table}"))
    assert "jane.doe" not in dump and "555-0100" not in dump
    undeclared = [r for r in _runs(db) if r["action"] == "payment.undeclared"][0]
    assert undeclared["params_digest"] == journal.digest({"action": free_text, "to": WALLET})


async def test_a_request_whose_engine_left_mid_request_is_never_read_as_not_attempted(
        tmp_path, monkeypatch):
    """The CallMark is set by the engine the dispatcher consults. If the engine
    is taken out while a keyed request is between its claim and its dispatch
    (a stopping gateway), the dispatcher finds none and calls the service
    unmarked — so the bridge, finding its run still START, cannot tell, and
    does not close it as not attempted or give its key back."""
    world = World()
    server = await _on_gateway(tmp_path, monkeypatch, world)
    async with TestClient(TestServer(server.create_app())) as client:
        eng = wiring.current()
        await eng.loop.stop()
        db = server.react_loop.memory.db

        def leave(name):
            if name != "attestation":
                wiring.install(None)
        server.service_dispatcher = stub_dispatcher(world, SETTLED, get_hook=leave)
        try:
            first, _ = await _post(client, body_for(ACTION), key="leave-key-01")
        finally:
            wiring.install(eng)
        (run,) = _runs(db)
        steps = _steps_of(db, run["run_id"])
        server.service_dispatcher = stub_dispatcher(world, SETTLED)
        replay, _ = await _post(client, body_for(ACTION), key="leave-key-01")
    assert first.status == 200 and world.count("service") == 1
    assert run["state"] == journal.START and steps == [
        ("start", "recorded"), ("unknown_effect", "not_known_if_called")]
    assert replay.status == 200 and replay.headers.get("Idempotent-Replayed") == "true"
