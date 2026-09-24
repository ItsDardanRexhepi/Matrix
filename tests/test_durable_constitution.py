"""Durable execution (engines Phase 2) holds lifecycle authority and nothing else.

The constitution the phase was built under: deterministic code owns facts, the
Oracle owns authorization, Morpheus owns safety invariants, judgments may
advise and never permit. Phase 2 moves LIFECYCLE authority only — a run's state
machine and its idempotent replay — and only in mode on. These pin the
boundary from the outside:

* the security gate is asked exactly the same question, with exactly the same
  context, whatever the durable mode, and a replay is asked it again;
* a run's states are the five lifecycle words, and the table refuses any other,
  so no verdict can be written into the journal;
* the words a run's steps record are the ones the layer that made the call
  computed (the dispatcher's settled / broadcast / refused), never a new
  reading;
* the engine's only refusal is to not start an effect it could not record: it
  never turns a refusal into a success, a failure into a completion, or a
  denial into a run.
"""

from __future__ import annotations

import json
import sqlite3
import sys

import pytest

sys.path.insert(0, "tests")

from aiohttp.test_utils import TestClient, TestServer  # noqa: E402

from durable_harness import (  # noqa: E402
    BROADCAST, REFUSED, SETTLED, World, body_for, database, engine, gateway, stub_dispatcher,
)
from runtime.blockchain.services.service_dispatcher import (  # noqa: E402
    RECORD_BROADCAST, RECORD_REFUSED, RECORD_SETTLED, _record_verdict,
)
from runtime.durable import journal, wiring  # noqa: E402

ACTION = "transfer_stablecoin"


@pytest.fixture(autouse=True)
def _no_env_mode(monkeypatch):
    monkeypatch.delenv("MATRIX_DURABLE_MODE", raising=False)


async def _gate_questions(tmp_path, monkeypatch, durable, name, real_gate):
    """Every question the bridge asks the gate for one request and its replay."""
    import gateway.security_gate as security_gate
    from runtime.blockchain.services.attestation import batch_processor as bp
    from durable_harness import FakeEAS
    world = World()
    monkeypatch.setattr(bp, "_eas_client_for", lambda _cfg: FakeEAS(world), raising=False)
    asked: list = []

    async def gate(action_type, parameters=None, context=None, *, operation=None):
        asked.append(json.dumps([action_type, parameters, context, operation], sort_keys=True,
                                default=str))
        return await real_gate(action_type, parameters, context, operation=operation)
    monkeypatch.setattr(security_gate, "gate_action", gate)
    (tmp_path / name).mkdir()
    server = gateway(tmp_path / name, durable)
    statuses = []
    async with TestClient(TestServer(server.create_app())) as client:
        server.service_dispatcher = stub_dispatcher(world, SETTLED)
        for _ in range(2):
            resp = await client.post("/bridge/v1/action", json=body_for(ACTION),
                                     headers={"Idempotency-Key": "constitution-1"})
            statuses.append(resp.status)
    return asked, statuses, world.count("service")


async def test_the_gate_is_asked_the_same_question_in_every_mode(tmp_path, monkeypatch):
    import gateway.security_gate as security_gate
    real = security_gate.gate_action
    off = await _gate_questions(tmp_path, monkeypatch, None, "off", real)
    shadow = await _gate_questions(tmp_path, monkeypatch, {"mode": "shadow"}, "shadow", real)
    on = await _gate_questions(tmp_path, monkeypatch,
                               {"mode": "on", "canary": "state_modifying"}, "on", real)
    assert off[0] == shadow[0] == on[0] and len(off[0]) == 2, "one question per request, replay too"
    assert off[1] == shadow[1] == on[1] == [200, 200]
    assert (off[2], shadow[2], on[2]) == (2, 2, 1), "only mode on keeps the replay from acting"


def test_a_run_can_only_be_in_a_lifecycle_state(tmp_path):
    assert journal.STATES == ("START", "RUNNING", "COMPLETE", "ABORT", "FAIL")
    db = database(tmp_path / "a.db")
    for word in ("VERIFIED", "SETTLED", "SUCCESS", "PENDING", "UNKNOWN", "complete"):
        with pytest.raises(sqlite3.IntegrityError):
            db.execute_sync("INSERT INTO workflow_runs (run_id, action, params_digest, state, "
                            "started_at) VALUES (?, 'a', 'd', ?, 1)", (f"run_{word}", word))


@pytest.mark.parametrize("result", [SETTLED, BROADCAST, REFUSED,
                                    {"status": "compliance_hold"}, {"ok": False},
                                    {"status": "pending", "settled": False, "broadcast": True}])
async def test_a_step_records_the_dispatchers_own_word_and_nothing_else(result, tmp_path,
                                                                          monkeypatch):
    world = World()
    db = database(tmp_path / "a.db")
    previous = wiring.install(engine(db, world=world, monkeypatch=monkeypatch))
    try:
        answer = json.loads(await stub_dispatcher(world, result).execute(
            ACTION, params={"to": "0x1"}))
    finally:
        wiring.install(previous)
    (run,) = [dict(r) for r in db.fetchall_sync("SELECT * FROM workflow_runs")]
    word = journal.get_steps(db, run["run_id"])[-1]["state"]
    assert word == _record_verdict(result)
    assert run["state"] == (journal.FAIL if word == RECORD_REFUSED else journal.COMPLETE)
    assert word in (RECORD_SETTLED, RECORD_BROADCAST, RECORD_REFUSED)
    # The caller's answer is the dispatcher's, whatever the journal made of it.
    assert answer["status"] == "ok" and answer["result"] == json.loads(json.dumps(result))


async def test_the_engine_never_turns_a_refusal_into_a_run_that_acted(tmp_path, monkeypatch):
    """A gate denial on the bridge binds nothing and journals nothing: the engine
    runs after the gate and only when the gate allowed."""
    import gateway.security_gate as security_gate
    world = World()

    async def deny(*a, **k):
        return {"allow": False, "reason": "no"}
    monkeypatch.setattr(security_gate, "gate_action", deny)
    (tmp_path / "gw").mkdir()
    server = gateway(tmp_path / "gw", {"mode": "on", "canary": "state_modifying"})
    async with TestClient(TestServer(server.create_app())) as client:
        server.service_dispatcher = stub_dispatcher(world, SETTLED)
        resp = await client.post("/bridge/v1/action", json=body_for(ACTION),
                                 headers={"Idempotency-Key": "constitution-2"})
        db = server.react_loop.memory.db
        rows = {t: db.fetchall_sync(f"SELECT COUNT(*) FROM {t}")[0][0]
                for t in ("workflow_runs", "idempotency_keys", "outbox")}
    assert resp.status == 403 and world.effects == []
    assert rows == {"workflow_runs": 0, "idempotency_keys": 0, "outbox": 0}
