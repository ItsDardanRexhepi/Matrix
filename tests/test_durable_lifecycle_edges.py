"""Durable execution at its edges: every run still ends, every delivery still
happens once, and nothing about a request's credential lets a key be replayed
under another name.

Each test here pins a path found by reading the engine against the rules it
has to keep, where an earlier build broke one of them:

* a request cut off after its call answered (the gateway's request timeout, a
  shutdown) left its run RUNNING, and — held by a live engine — recovery never
  closed it;
* a raise after the call answered, in mode on, dropped the attestation and
  feed entry mode off delivers;
* in shadow, an attestation record that could not be built changed the answer
  mode off gives;
* ``/ready`` failed a loop that was busy delivering slowly;
* another process sharing the database gave up rows a live process held;
* the recovery window ignored the gateway's own request timeout;
* the key's scope followed the wallet a session resolves to, which linking a
  wallet changes, so a retry after linking ran the action again.
"""
from __future__ import annotations

import asyncio
import json
import sys
from types import SimpleNamespace

sys.path.insert(0, "tests")

from runtime.durable import journal, keys, outbox, wiring  # noqa: E402
from runtime.durable.outbox import Delivery, Held, OutboxLoop  # noqa: E402
from test_durable_harness import (  # noqa: E402
    Clock, Effects, bridge_like, dispatcher, drain, engine, installed, open_db, open_runs,
    params_for, rows, STATE_MODIFYING, WALLET,
)

ACTION = "transfer_stablecoin" if "transfer_stablecoin" in STATE_MODIFYING else STATE_MODIFYING[0]


def _steps(db, run_id):
    return [(r["name"], r["state"], r["detail"]) for r in db.fetchall_sync(
        "SELECT name, state, detail FROM workflow_steps WHERE run_id = ? ORDER BY seq", (run_id,))]


async def _answer_off(action, params):
    effects = Effects()
    d = dispatcher(effects)
    with installed(None):
        answer = await d.execute(action, params=params, caller_identity=WALLET)
    for _ in range(5):
        await asyncio.sleep(0)
    return answer, effects


# ── a request cut off after its call answered ───────────────────────────────

async def test_a_shadow_dispatch_cancelled_after_its_call_answered_ends_its_run(tmp_path):
    db = open_db(tmp_path / "a.db")
    clock = Clock()
    effects = Effects()
    d = dispatcher(effects)
    hold_attest = asyncio.Event()

    async def slow_attest(*args, **kwargs):   # the legacy attestation awaiting the chain
        await hold_attest.wait()
    d._attest_action = slow_attest
    with installed(eng := engine(db, "shadow", clock, effects)):
        task = asyncio.ensure_future(d.execute(ACTION, params=params_for(ACTION, 1),
                                               caller_identity=WALLET))
        for _ in range(10):
            await asyncio.sleep(0)
        assert effects.count("service", ACTION, 1) == 1, "precondition: the call answered"
        task.cancel()
        try:
            await task
        except asyncio.CancelledError:
            pass
        assert open_runs(db) == [], "a run cut off after its call answered was left open"
        (run,) = rows(db, "workflow_runs")
        assert run["state"] == journal.FAIL
        assert _steps(db, run["run_id"])[-1] == (
            journal.STEP_UNKNOWN, "interrupted", "interrupted_after_answer")
        assert eng.health()["open_runs"] == 0, "the engine still holds the ended run"


async def test_a_dispatch_cancelled_in_its_call_ends_fail_with_its_effect_unknown(tmp_path):
    db = open_db(tmp_path / "a.db")
    effects = Effects()
    d = dispatcher(effects)
    d._services.gates[ACTION] = asyncio.Event()   # never set: the call hangs
    with installed(engine(db, "on", Clock(), effects)):
        task = asyncio.ensure_future(d.execute(ACTION, params=params_for(ACTION, 1),
                                               caller_identity=WALLET))
        for _ in range(10):
            await asyncio.sleep(0)
        task.cancel()
        try:
            await task
        except asyncio.CancelledError:
            pass
    (run,) = rows(db, "workflow_runs")
    assert run["state"] == journal.FAIL and open_runs(db) == []
    assert _steps(db, run["run_id"])[-1] == (journal.STEP_UNKNOWN, "cancelled", "call_interrupted")


# ── a raise after the call answered ─────────────────────────────────────────

async def test_a_raise_after_the_answer_in_mode_on_still_delivers_what_mode_off_delivers(tmp_path):
    """A settled answer the envelope cannot encode (a tuple key) makes the
    dispatcher raise after the attestation and feed entry were handed over. Mode
    off had delivered both by then; mode on delivers both, the legacy way, once."""
    answer = {"status": "success", "tx_hash": "0x" + "22" * 32, "settled": True, (1, 2): "x"}
    params = params_for(ACTION, 1)
    off_answer, off_effects = await _answer_off_with(ACTION, params, answer)

    db = open_db(tmp_path / "a.db")
    effects = Effects()
    d = dispatcher(effects)
    d._services.answers[ACTION] = answer
    with installed(eng := engine(db, "on", Clock(), effects)):
        on_answer = await d.execute(ACTION, params=params, caller_identity=WALLET)
        await drain(eng)
    assert json.loads(on_answer)["error_category"] == json.loads(off_answer)["error_category"]
    for kind in ("service", "attest", "feed"):
        assert effects.count(kind) == off_effects.count(kind) == 1, (kind, effects.log)
    assert effects.count("attest_sent") == 0, "the outbox also delivered a run that failed"
    (run,) = rows(db, "workflow_runs")
    assert run["state"] == journal.FAIL


async def _answer_off_with(action, params, answer):
    effects = Effects()
    d = dispatcher(effects)
    d._services.answers[action] = answer
    with installed(None):
        out = await d.execute(action, params=params, caller_identity=WALLET)
    for _ in range(5):
        await asyncio.sleep(0)
    return out, effects


async def test_an_attestation_that_cannot_be_built_changes_no_answer_in_shadow(tmp_path):
    """``json.dumps(params, sort_keys=True)`` cannot order mixed key types; mode
    off's attestation fails inside its own guard and the answer is still ok."""
    params = {"to": WALLET, "amount": 5, "marker": 1, "meta": {1: "a", "b": 2}}
    off_answer, off_effects = await _answer_off(ACTION, params)
    db = open_db(tmp_path / "a.db")
    effects = Effects()
    d = dispatcher(effects)
    with installed(engine(db, "shadow", Clock(), effects)):
        answer = await d.execute(ACTION, params=params, caller_identity=WALLET)
        for _ in range(5):
            await asyncio.sleep(0)

    def strip(text):
        env = json.loads(text)
        env.pop("elapsed_ms", None)
        return env
    assert strip(answer) == strip(off_answer)
    assert [e[0] for e in effects.log] == [e[0] for e in off_effects.log]


# ── /ready and a loop busy with slow deliveries ─────────────────────────────

async def test_a_loop_busy_with_slow_deliveries_stays_healthy(tmp_path):
    db = open_db(tmp_path / "a.db")
    clock = Clock()
    loop = OutboxLoop(db, deliver=True, clock=clock, tick_s=3600.0)
    step = outbox.DELIVERY_TIMEOUT_S - 1       # each delivery nearly as slow as allowed
    health: list[bool] = []

    def run(tx):
        journal.insert_run(tx, run_id="run_a", action=ACTION, service="s", actor_hash="",
                           params_digest="p", state=journal.COMPLETE, started_at=clock.now,
                           terminal_at=clock.now)
    journal.transaction(db, run, wait=True)
    for n in range(4):
        async def slow() -> Delivery:
            clock.advance(step)
            await asyncio.sleep(0)
            health.append(loop.healthy())
            return Delivery(outbox.DELIVERED, "landed")
        row_id = journal.transaction(db, lambda tx, n=n: outbox.insert(
            tx, run_id="run_a", kind="attest" if n % 2 else "feed", payload_digest=f"d{n}",
            now=clock.now, deliver=True), wait=True)
        loop.hold(row_id, Held("run_a", "attest" if n % 2 else "feed", f"d{n}", slow))
    loop._task = asyncio.ensure_future(asyncio.sleep(3600))   # alive, for healthy()
    try:
        await loop.tick()
    finally:
        loop._task.cancel()
    assert len(health) == 4 and all(health), f"a busy loop reported unhealthy: {health}"
    assert outbox.counts(db)["handed_off"] == 4


# ── another process sharing the database ────────────────────────────────────

async def test_rows_a_live_process_holds_are_never_given_up_by_another(tmp_path):
    path = tmp_path / "a.db"
    clock = Clock()
    db1, db2 = open_db(path), open_db(path)
    window = 300.0
    p1 = OutboxLoop(db1, deliver=True, clock=clock, abandoned_after_s=window)
    p2 = OutboxLoop(db2, deliver=True, clock=clock, abandoned_after_s=window)

    def run(tx):
        journal.insert_run(tx, run_id="run_a", action=ACTION, service="s", actor_hash="",
                           params_digest="p", state=journal.COMPLETE, started_at=clock.now,
                           terminal_at=clock.now)
    journal.transaction(db1, run, wait=True)
    sent: list[int] = []
    gate = asyncio.Event()

    def deliverer(n):
        async def deliver() -> Delivery:
            if n == 0:
                await gate.wait()                 # P1 is stuck on its first delivery
            sent.append(n)
            return Delivery(outbox.DELIVERED, "landed")
        return deliver
    ids = []
    for n in range(3):
        row_id = journal.transaction(db1, lambda tx, n=n: outbox.insert(
            tx, run_id="run_a", kind="attest", payload_digest=f"d{n}", now=clock.now,
            deliver=True), wait=True)
        p1.hold(row_id, Held("run_a", "attest", f"d{n}", deliverer(n)))
        ids.append(row_id)
    p1._renew(clock.now)                          # a pass of P1's loop
    clock.advance(window * 0.6)
    p1._renew(clock.now)                          # P1, still alive, passes again
    clock.advance(window * 0.6)
    await p2.drain()                              # P2's loop, past the first window
    assert outbox.counts(db1)["given_up"] == 0, "another process gave up rows P1 still holds"
    gate.set()
    await p1.tick()
    assert sorted(sent) == [0, 1, 2] and outbox.counts(db1)["handed_off"] == 3


async def test_a_row_given_up_elsewhere_is_dropped_from_what_this_process_holds(tmp_path):
    db = open_db(tmp_path / "a.db")
    clock = Clock()
    loop = OutboxLoop(db, deliver=True, clock=clock)
    row_id = journal.transaction(db, lambda tx: outbox.insert(
        tx, run_id="run_a", kind="feed", payload_digest="d", now=clock.now, deliver=True),
        wait=True)

    async def never() -> Delivery:
        raise AssertionError("a row given up elsewhere was delivered")
    loop.hold(row_id, Held("run_a", "feed", "d", never))
    db.execute_sync("UPDATE outbox SET next_at = NULL WHERE id = ?", (row_id,))
    row = (row_id, "run_a", "feed", "d", 0, clock.now)
    assert loop._claim(row, clock.now) is None
    assert loop.held_count() == 0


# ── the recovery window and the request timeout ─────────────────────────────

def test_the_recovery_window_follows_the_gateways_request_timeout():
    assert wiring.abandoned_window({}) == journal.ABANDONED_AFTER_S
    assert wiring.abandoned_window({"gateway": {"request_timeout_seconds": 60}}) == 300.0
    assert wiring.abandoned_window({"gateway": {"request_timeout_seconds": 600}}) == 1260.0
    assert wiring.abandoned_window({"gateway": {"request_timeout_seconds": 0}}) == 3600.0
    assert wiring.abandoned_window({"gateway": {"request_timeout_seconds": "x"}}) == 300.0


# ── whose key it is ─────────────────────────────────────────────────────────

def test_a_keys_scope_is_the_sessions_own_subject_not_the_wallet_it_resolves_to():
    request = object()
    apple = SimpleNamespace(_wallet_session_from_request=lambda r: {"address": "apple:Sub-1"})
    before_link = wiring.caller_scope(apple, request, "session", "apple:Sub-1")
    after_link = wiring.caller_scope(apple, request, "session", "0x" + "AB" * 20)
    assert before_link == after_link == "session|apple:Sub-1"
    siwe = SimpleNamespace(_wallet_session_from_request=lambda r: {"address": "0x" + "CD" * 20})
    assert wiring.caller_scope(siwe, request, "session", "0x" + "CD" * 20) == (
        "session|0x" + "cd" * 20)
    no_session = SimpleNamespace(_wallet_session_from_request=lambda r: None)
    assert wiring.caller_scope(no_session, request, "operator", "0x" + "Ab" * 20) == (
        "operator|0x" + "ab" * 20)
    assert wiring.caller_scope(no_session, request, "operator", "0xAb") == "operator|0xAb"
    assert wiring.caller_scope(object(), request, "", "") == "unknown|"


def test_a_keys_scope_keeps_the_one_spelling_rule_two_subjects_apart():
    """The scope is the caller in the platform's one spelling
    (runtime/auth/identity.py): every spelling of one wallet address is one
    caller, and two subjects that are not addresses and differ only in case are
    two callers, so neither can be answered from the other's key."""
    request = object()

    def scope(subject, kind="session"):
        server = SimpleNamespace(_wallet_session_from_request=lambda r: {"address": subject})
        return wiring.caller_scope(server, request, kind, subject)
    assert scope("apple:000123.ABCDEF") != scope("apple:000123.abcdef")
    assert scope("0x" + "AB" * 20) == scope("0x" + "ab" * 20) == scope("0X" + "aB" * 20)
    no_session = SimpleNamespace(_wallet_session_from_request=lambda r: None)
    assert (wiring.caller_scope(no_session, request, "operator", "user-A")
            != wiring.caller_scope(no_session, request, "operator", "user-a"))
    assert keys.scoped(wiring.BRIDGE_ACTION, scope("apple:000123.ABCDEF"), "k-1") != keys.scoped(
        wiring.BRIDGE_ACTION, scope("apple:000123.abcdef"), "k-1")


async def test_a_retry_after_linking_a_wallet_is_the_same_key(tmp_path):
    """The first request under a key, before the session linked a wallet, and its
    retry after: one scope, so the retry is a replay and runs nothing."""
    db = open_db(tmp_path / "a.db")
    effects = Effects()
    d = dispatcher(effects)
    server = SimpleNamespace(_wallet_session_from_request=lambda r: {"address": "apple:sub"})
    request = SimpleNamespace(headers={"Idempotency-Key": "k-link"})
    with installed(engine(db, "on", Clock(), effects)):
        for identity in ("apple:sub", WALLET):
            with wiring.keyed(request, scope=lambda: wiring.caller_scope(
                    server, request, "session", identity)):
                await d.execute(ACTION, params=params_for(ACTION, 1), caller_identity=identity)
    assert effects.count("service", ACTION, 1) == 1, f"the retry ran again: {effects.log}"


# ── a key the bridge could not scope is not honoured ────────────────────────

async def test_a_scope_that_raises_drops_the_key_and_the_request_runs_unkeyed(tmp_path):
    db = open_db(tmp_path / "a.db")
    effects = Effects()
    d = dispatcher(effects)
    request = SimpleNamespace(headers={"Idempotency-Key": "k"})

    def broken_scope():
        raise RuntimeError("no scope")
    with installed(engine(db, "on", Clock(), effects)):
        with wiring.keyed(request, scope=broken_scope):
            answer = await d.execute(ACTION, params=params_for(ACTION, 1), caller_identity=WALLET)
    assert json.loads(answer)["status"] == "ok"
    assert rows(db, "idempotency_keys") == [] and len(rows(db, "workflow_runs")) == 1


# ── round two: a real loop, a long delivery, another process ────────────────

async def test_a_long_delivery_never_lets_another_process_take_the_rows_behind_it(tmp_path):
    """No hand-called renewal: process A's own tick, whose first delivery takes
    most of the delivery timeout while process B drains past the window."""
    path = tmp_path / "a.db"
    clock = Clock()
    db1, db2 = open_db(path), open_db(path)
    window = 300.0
    a = OutboxLoop(db1, deliver=True, clock=clock, abandoned_after_s=window)
    b = OutboxLoop(db2, deliver=True, clock=clock, abandoned_after_s=window)

    def run(tx):
        journal.insert_run(tx, run_id="run_a", action=ACTION, service="s", actor_hash="",
                           params_digest="p", state=journal.COMPLETE, started_at=clock.now,
                           terminal_at=clock.now)
    journal.transaction(db1, run, wait=True)
    sent: list[int] = []

    def deliverer(n):
        async def deliver() -> Delivery:
            clock.advance(outbox.DELIVERY_TIMEOUT_S - 10)  # a slow receipt, within the timeout
            await b.drain()                              # B passes meanwhile
            sent.append(n)
            return Delivery(outbox.DELIVERED, "landed")
        return deliver
    for n in range(3):
        row_id = journal.transaction(db1, lambda tx, n=n: outbox.insert(
            tx, run_id="run_a", kind="attest", payload_digest=f"d{n}", now=clock.now,
            deliver=True), wait=True)
        a.hold(row_id, Held("run_a", "attest", f"d{n}", deliverer(n)))
    clock.advance(149)                                  # A was busy before its tick
    await a.tick()
    assert sorted(sent) == [0, 1, 2], f"rows A held were taken by B: sent {sent}"
    assert outbox.counts(db1) == {"due": 0, "handed_off": 3, "given_up": 0}


async def test_a_retry_whose_row_was_given_up_elsewhere_is_not_revived(tmp_path):
    db = open_db(tmp_path / "a.db")
    clock = Clock()
    loop = OutboxLoop(db, deliver=True, clock=clock)
    row_id = journal.transaction(db, lambda tx: outbox.insert(
        tx, run_id="run_a", kind="attest", payload_digest="d", now=clock.now, deliver=True),
        wait=True)
    row = (row_id, "run_a", "attest", "d", 0, clock.now)
    db.execute_sync("UPDATE outbox SET next_at = NULL WHERE id = ?", (row_id,))  # given up elsewhere
    loop._settle(row, Delivery(outbox.RETRY, "skipped"))
    assert outbox.counts(db)["given_up"] == 1, "a given-up row was made due again"
    assert loop.held_count() == 0


async def test_an_answer_with_no_canonical_json_still_ends_its_run(tmp_path):
    """Keys of mixed types cannot be sorted: the digest falls back, and the run
    ends COMPLETE with its answer on record — a replay gets the first answer."""
    db = open_db(tmp_path / "a.db")
    effects = Effects()
    d = dispatcher(effects)
    d._services.answers[ACTION] = {"status": "success", "settled": True,
                                   "tx_hash": "0x" + "22" * 32, "by_block": {1: "a", "t": 1}}
    with installed(eng := engine(db, "on", Clock(), effects)):
        first = await bridge_like(d, ACTION, params_for(ACTION, 1), key="k-mixed")
        replay = await bridge_like(d, ACTION, params_for(ACTION, 1), key="k-mixed")
        await drain(eng)
    (run,) = rows(db, "workflow_runs")
    assert run["state"] == journal.COMPLETE and replay == first
    assert effects.count("service") == 1
    assert journal.digest({1: "a", "t": 1}) == journal.digest({1: "a", "t": 1})


async def test_a_stopping_engine_writes_the_ends_it_could_not_write_before(tmp_path, monkeypatch):
    db = open_db(tmp_path / "a.db")
    effects = Effects()
    d = dispatcher(effects)
    real = journal.transaction
    calls: list[int] = []

    def the_end_fails_once(db_, work, *, wait):
        calls.append(1)
        if len(calls) == 2:
            raise __import__("sqlite3").OperationalError("database is locked")
        return real(db_, work, wait=wait)
    monkeypatch.setattr(journal, "transaction", the_end_fails_once)
    eng = engine(db, "on", Clock(), effects)
    with installed(eng):
        await d.execute(ACTION, params=params_for(ACTION, 1), caller_identity=WALLET)
        assert rows(db, "workflow_runs")[0]["state"] == journal.RUNNING
        eng.start()
        await eng.stop()
    (run,) = rows(db, "workflow_runs")
    assert run["state"] == journal.COMPLETE, "a stopping engine left a known end unwritten"


async def test_an_identity_no_encoder_accepts_changes_nothing_in_shadow_and_is_run_in_on(tmp_path):
    """A lone surrogate is legal JSON and reaches the dispatch as the caller's
    identity; digesting it must never change an answer or refuse the action."""
    identity = "0xab\ud800"
    for mode in ("shadow", "on"):
        db = open_db(tmp_path / f"{mode}.db")
        effects = Effects()
        d = dispatcher(effects)
        with installed(engine(db, mode, Clock(), effects)):
            answer = await d.execute(ACTION, params=params_for(ACTION, 1),
                                     caller_identity=identity)
        assert json.loads(answer)["status"] == "ok", (mode, answer)
        assert effects.count("service") == 1, mode
        assert [r["state"] for r in rows(db, "workflow_runs")] == [journal.COMPLETE], mode

    from runtime.tools.dispatcher import ToolDispatcher
    called: list[int] = []

    async def mint(**kwargs):
        called.append(1)
        return {"status": "success"}
    tools = ToolDispatcher({})
    tools._tools["nft"] = mint
    db = open_db(tmp_path / "tool.db")
    with installed(engine(db, "shadow", Clock(), Effects())):
        outcome = await tools.dispatch("nft", {"action": "mint"}, caller_identity=identity)
    assert outcome.ok and called == [1], outcome
