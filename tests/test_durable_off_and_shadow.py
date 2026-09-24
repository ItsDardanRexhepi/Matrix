"""Durable execution (engines Phase 2), modes off and shadow: off is main, and
shadow only writes rows.

OFF IS MAIN, MEASURED. ``measure_answers`` drives the three surfaces the engine
touches — ``POST /bridge/v1/action`` (with and without an Idempotency-Key, each
keyed request sent twice), ``ServiceDispatcher.execute`` and the tool
dispatcher's twin tools — over every state-modifying action name and every twin
tool action, with a service that answers settled, broadcast and refused, and
records what each answered and what each did (service calls, attestations handed
to the attestation service, feed entries published), with the instants and the
correlation ids taken out. ``tests/baseline/durable_off_answers.json`` holds
that measurement taken ON MAIN, before this phase existed, by running this very
function in a scratch export of main (it imports nothing main lacks). The suite
measures the branch with the mode off and must get the same digests, action by
action.

SHADOW ANSWERS THE SAME. The same measurement with engines.durable.mode =
"shadow" must give the same digests too — the only effect of shadow is rows —
and the rows must be there: a run per state-modifying call, the attestations
and feed entries as ``recorded`` bookkeeping that nothing drains, and the keys.

``DURABLE_BASELINE=write`` rewrites the golden from wherever it runs; it is how
the file was made, in the export of main.
"""

from __future__ import annotations

import asyncio
import hashlib
import json
import logging
import os
import re
import sys
from pathlib import Path
from types import SimpleNamespace

import pytest

sys.path.insert(0, "tests")

ROOT = Path(__file__).resolve().parent.parent
GOLDEN = ROOT / "tests" / "baseline" / "durable_off_answers.json"
WRITE = os.environ.get("DURABLE_BASELINE", "").strip().lower() == "write"

_VOLATILE = {"timestamp", "elapsed_ms", "ref", "queued_at", "submitted_at", "params_hash"}
_REF = re.compile(r"\(ref: [^)]*\)")

SHAPES = {
    "settled": {"status": "success", "settled": True, "tx_hash": "0x" + "ab" * 32},
    "broadcast": {"status": "submitted", "tx_hash": "0x" + "cd" * 32},
    "refused": {"status": "not_deployed", "reason": "no contract"},
}
TOOL_SHAPES = {
    "settled": {"status": "success", "tx_hash": "0x" + "ab" * 32},
    "refused": {"status": "error", "error": "reverted"},
    "text": "sent 0x" + "ab" * 32,
}


def _normalise(value):
    if isinstance(value, dict):
        return {k: _normalise(v) for k, v in sorted(value.items()) if k not in _VOLATILE}
    if isinstance(value, list):
        return [_normalise(v) for v in value]
    if isinstance(value, str):
        if value[:1] in ("{", "["):
            try:
                return {"__json__": _normalise(json.loads(value))}
            except ValueError:
                pass
        return _REF.sub("(ref: *)", value)
    return value


def _digest(value) -> str:
    return hashlib.sha256(json.dumps(value, sort_keys=True, default=str).encode()).hexdigest()


async def measure_answers(scratch: Path, durable: dict | None = None) -> dict:
    """What the three surfaces answer and do, action by action. Imports nothing
    that main lacks, so the same function measures main and this branch."""
    from aiohttp.test_utils import TestClient, TestServer
    from gateway.server import GatewayServer
    from runtime.blockchain.services.service_dispatcher import (
        ACTION_MAP, ServiceDispatcher, _STATE_MODIFYING_ACTIONS,
    )
    from runtime.security.action_map import SIGNING_ACTIONS
    from runtime.tools.dispatcher import ToolDispatcher
    from test_route_sweep import SWEEP_CONFIG

    effects: list = []
    shape = {"name": "settled"}

    class _Service:
        def __getattr__(self, method):
            async def call(**kwargs):
                effects.append(["service", method])
                return dict(SHAPES[shape["name"]])
            return call

    class _Attestation:
        async def attest(self, **kwargs):
            effects.append(["attest", _normalise(kwargs)])
            return {"status": "queued"}

    class _Feed:
        async def ingest(self, **kwargs):
            effects.append(["feed", _normalise(kwargs)])

    registry = SimpleNamespace(get=lambda n: _Attestation() if n == "attestation" else _Service())

    def dispatcher():
        d = ServiceDispatcher({})
        d._get_registry = lambda: registry
        d._feed_engine = _Feed()
        return d

    async def settle():
        for _ in range(3):
            await asyncio.sleep(0)

    config = {**SWEEP_CONFIG, "memory_dir": str(scratch), "database": {"path": f"{scratch}/m.db"}}
    if durable is not None:
        config["engines"] = {"durable": durable}
    server = GatewayServer(config)
    out: dict[str, dict] = {"bridge": {}, "dispatch": {}, "tools": {}}
    async with TestClient(TestServer(server.create_app())) as client:
        server.service_dispatcher = dispatcher()
        for action in sorted(_STATE_MODIFYING_ACTIONS):
            record = []
            for name in SHAPES:
                shape["name"] = name
                for headers in (None, {"Idempotency-Key": f"k-{action}-{name}"[:64]}):
                    for _ in range(1 if headers is None else 2):
                        del effects[:]
                        resp = await client.post(
                            "/bridge/v1/action", headers=headers,
                            json={"action": action, "params": {"to": "0x" + "12" * 20,
                                                               "amount": 5}})
                        text = await resp.text()
                        await settle()
                        record.append([name, bool(headers), resp.status,
                                       _normalise(json.loads(text)), list(effects)])
            out["bridge"][action] = record

        d = dispatcher()
        for action in sorted(_STATE_MODIFYING_ACTIONS):
            record = []
            for name in SHAPES:
                shape["name"] = name
                del effects[:]
                answer = await d.execute(action, params={"to": "0x" + "12" * 20, "amount": 5},
                                         caller_identity="0x" + "34" * 20)
                await settle()
                record.append([name, _normalise(json.loads(answer)), list(effects)])
            out["dispatch"][action] = record

        tools = ToolDispatcher({})
        for tool, verbs in sorted(SIGNING_ACTIONS.items()):
            for verb in sorted(verbs):
                record = []
                for name, value in TOOL_SHAPES.items():
                    async def handler(_value=value, **kwargs):
                        effects.append(["tool", tool])
                        return dict(_value) if isinstance(_value, dict) else _value
                    tools._tools[tool] = handler
                    del effects[:]
                    outcome = await tools.dispatch(tool, {"action": verb, "amount": 1},
                                                   agent_name="neo",
                                                   caller_identity="0x" + "34" * 20)
                    record.append([name, outcome.ok, _normalise(outcome.model_text),
                                   _normalise(outcome.client_preview), outcome.code,
                                   outcome.reported, list(effects)])
                out["tools"][f"{tool}.{verb}"] = record
    return out


def _golden_of(measured: dict) -> dict:
    return {surface: {name: _digest(record) for name, record in cases.items()}
            for surface, cases in measured.items()}


def _differences(expected: dict, got: dict) -> list[str]:
    diffs = []
    for surface in sorted(set(expected) | set(got)):
        a, b = expected.get(surface, {}), got.get(surface, {})
        for name in sorted(set(a) | set(b)):
            if a.get(name) != b.get(name):
                diffs.append(f"{surface}:{name}")
    return diffs


async def test_off_answers_are_the_answers_main_gives(tmp_path, monkeypatch):
    monkeypatch.delenv("MATRIX_DURABLE_MODE", raising=False)
    measured = await measure_answers(tmp_path)
    digests = _golden_of(measured)
    if WRITE:
        GOLDEN.write_text(json.dumps({
            "baseline": "durable_off_answers",
            "measured_at": os.environ.get("DURABLE_MEASURED_AT", "unknown"),
            "instrument": ("tests/test_durable_off_and_shadow.py measure_answers: every "
                           "state-modifying action name through POST /bridge/v1/action (no key, "
                           "and a key sent twice) and ServiceDispatcher.execute, and every twin "
                           "tool action through ToolDispatcher.dispatch, over a service answering "
                           "settled, broadcast and refused; each case's normalised answer and "
                           "effects, digested per action"),
            "cases": sum(len(v) for v in digests.values()),
            "digests": digests,
        }, indent=1, sort_keys=True) + "\n", encoding="utf-8")
        return
    golden = json.loads(GOLDEN.read_text(encoding="utf-8"))
    assert _differences(golden["digests"], digests) == []
    # The replayed body ran again with the mode off, as it does on main: the
    # second request under a key did everything the first did.
    for action, record in measured["bridge"].items():
        keyed = [r for r in record if r[1]]
        for first, second in zip(keyed[::2], keyed[1::2]):
            assert second[4] == first[4], action
    assert sum(1 for record in measured["bridge"].values() for r in record
               if r[1] and any(e[0] == "service" for e in r[4])) > 900


def test_the_golden_was_measured_on_main():
    golden = json.loads(GOLDEN.read_text(encoding="utf-8"))
    assert golden["measured_at"].startswith("main@"), golden["measured_at"]
    assert golden["cases"] == sum(len(v) for v in golden["digests"].values()) > 150


async def test_shadow_answers_are_the_off_answers_and_writes_the_rows(tmp_path, monkeypatch):
    from runtime.durable import wiring
    monkeypatch.delenv("MATRIX_DURABLE_MODE", raising=False)
    measured = await measure_answers(tmp_path, durable={"mode": "shadow"})
    assert wiring.current() is None, "the gateway took its engine out at shutdown"
    golden = json.loads(GOLDEN.read_text(encoding="utf-8"))
    assert _differences(golden["digests"], _golden_of(measured)) == []

    from runtime.db.database import Database
    db = Database({"database": {"path": f"{tmp_path}/m.db"}})
    runs = [dict(r) for r in db.fetchall_sync("SELECT * FROM workflow_runs")]
    by_state: dict[str, int] = {}
    for r in runs:
        by_state[r["state"]] = by_state.get(r["state"], 0) + 1

    from runtime.blockchain.services.service_dispatcher import ACTION_MAP

    def called(record) -> bool:
        # The measurement's attestation service records its own calls as
        # "attest"; every other service's as "service".
        action, effects = record[0], record[1][-1]
        if ACTION_MAP[action][0] == "attestation":
            return bool(effects)
        return any(e[0] == "service" for e in effects)
    bridge = [(a, r) for a, record in measured["bridge"].items() for r in record]
    dispatch = [(a, r) for a, record in measured["dispatch"].items() for r in record]
    reads = _twin_reads()
    twin_calls = sum(len(record) for name, record in measured["tools"].items()
                     if name.split(".", 1)[1] not in reads)
    answered = sum(map(called, bridge)) + sum(map(called, dispatch)) + twin_calls
    # A call that reached its service is one run that answered; a keyed request
    # that ended before its service (an action whose method does not exist) is
    # one run that ended ABORT; an unkeyed one of those journals nothing.
    assert by_state.get("COMPLETE", 0) + by_state.get("FAIL", 0) == answered
    assert by_state.get("ABORT", 0) == sum(1 for r in bridge if r[1][1] and not called(r))
    assert set(by_state) <= {"COMPLETE", "FAIL", "ABORT"}, by_state
    assert answered > 1500
    outbox = {tuple(r) for r in db.fetchall_sync("SELECT DISTINCT kind, state, payload FROM outbox")}
    assert outbox == {("attest", "recorded", ""), ("feed", "recorded", "")}, outbox
    # (the measurement's attestation service answers its own "queued", not the shape)
    settled = sum(1 for r in bridge + dispatch if r[1][0] == "settled" and called(r)
                  and ACTION_MAP[r[0]][0] != "attestation")
    assert db.fetchall_sync("SELECT COUNT(*) FROM outbox WHERE kind = 'attest'")[0][0] == settled
    keyed_pairs = [((a, first), (a, second)) for a, record in measured["bridge"].items()
                   for first, second in zip([r for r in record if r[1]][::2],
                                            [r for r in record if r[1]][1::2])]
    bound = sum(1 for first, _second in keyed_pairs if called(first))
    keys = db.fetchall_sync("SELECT COUNT(*), SUM(status IS NOT NULL) FROM idempotency_keys")[0]
    assert tuple(keys) == (bound, bound), "every keyed first answer recorded, nothing else bound"
    replays = db.fetchall_sync(
        "SELECT COUNT(*) FROM (SELECT key FROM workflow_runs WHERE key != '' "
        "AND state != 'ABORT' GROUP BY key HAVING COUNT(*) = 2)")[0][0]
    assert replays == bound, "shadow ran each replay again and journaled it under its key"
    await db.close()


def _twin_reads() -> set[str]:
    from runtime.security.action_map import READ, SIGNING_ACTIONS
    return {verb for verbs in SIGNING_ACTIONS.values() for verb, kind in verbs.items()
            if kind == READ}


def test_the_mode_the_config_and_the_environment_name(monkeypatch):
    from runtime.durable import wiring
    monkeypatch.delenv("MATRIX_DURABLE_MODE", raising=False)
    assert wiring.durable_mode({}) == "off"
    assert wiring.durable_mode({"engines": {"durable": {}}}) == "off"
    assert wiring.durable_mode({"engines": {"durable": {"mode": "shadow"}}}) == "shadow"
    assert wiring.durable_mode({"engines": {"durable": {"mode": " ON "}}}) == "on"
    for junk in ("enforce", "yes", "1", 3, ["on"]):
        assert wiring.durable_mode({"engines": {"durable": {"mode": junk}}}) == "off"
    monkeypatch.setenv("MATRIX_DURABLE_MODE", "shadow")
    assert wiring.durable_mode({"engines": {"durable": {"mode": "on"}}}) == "shadow"
    monkeypatch.setenv("MATRIX_DURABLE_MODE", "off")
    assert wiring.durable_mode({"engines": {"durable": {"mode": "on"}}}) == "off"
    assert wiring.durable_canary({}) == "twins"
    assert wiring.durable_canary({"engines": {"durable": {"canary": "state_modifying"}}}) == \
        "state_modifying"
    assert wiring.durable_canary({"engines": {"durable": {"canary": "all"}}}) == "twins"


def test_the_example_config_ships_off():
    example = json.loads((ROOT / "matrix.config.json.example").read_text(encoding="utf-8"))
    assert example["engines"]["durable"] == {"mode": "off", "canary": "twins"}


async def test_an_off_gateway_installs_nothing_reads_no_key_and_says_nothing(tmp_path, monkeypatch,
                                                                             caplog):
    from aiohttp.test_utils import TestClient, TestServer
    from durable_harness import World, body_for, gateway, stub_dispatcher
    from runtime.durable import wiring
    monkeypatch.delenv("MATRIX_DURABLE_MODE", raising=False)
    world = World()
    server = gateway(tmp_path)
    with caplog.at_level(logging.DEBUG):
        async with TestClient(TestServer(server.create_app())) as client:
            assert wiring.current() is None and server._durable_engine is None
            server.service_dispatcher = stub_dispatcher(world)
            for _ in range(2):
                resp = await client.post("/bridge/v1/action", json=body_for("transfer_stablecoin"),
                                         headers={"Idempotency-Key": "not a valid key!"})
                assert resp.status == 200 and "Idempotent-Replayed" not in resp.headers
            db = server.react_loop.memory.db
            for table in ("workflow_runs", "workflow_steps", "outbox", "idempotency_keys"):
                assert db.fetchall_sync(f"SELECT COUNT(*) FROM {table}")[0][0] == 0, table
    assert world.count("service") == 2, "off runs a replay twice, as main does"
    assert not [r for r in caplog.records if "durable" in r.getMessage().lower()]


async def test_a_shadow_gateway_says_so_and_takes_its_engine_out(tmp_path, monkeypatch, caplog):
    from aiohttp.test_utils import TestClient, TestServer
    from durable_harness import gateway
    from runtime.durable import wiring
    monkeypatch.delenv("MATRIX_DURABLE_MODE", raising=False)
    server = gateway(tmp_path, {"mode": "shadow"})
    with caplog.at_level(logging.INFO, logger="gateway.server"):
        async with TestClient(TestServer(server.create_app())):
            engine = wiring.current()
            assert engine is server._durable_engine and engine.mode == "shadow"
            assert engine.loop.alive and engine.loop.deliver is False
    assert wiring.current() is None and not engine.loop.alive
    lines = [r.getMessage() for r in caplog.records if r.getMessage().startswith("Engines: durable")]
    assert len(lines) == 1 and lines[0].startswith("Engines: durable mode=shadow canary=twins")


async def test_a_shadow_row_that_cannot_be_written_is_dropped_and_the_action_runs(tmp_path):
    """Another writer holds the database: shadow drops its rows at once and the
    dispatch answers as it would with the mode off."""
    import sqlite3
    import time
    from durable_harness import World, database, stub_dispatcher
    from runtime.durable.wiring import DurableEngine, install
    world = World()
    db = database(tmp_path / "a.db")
    previous = install(DurableEngine(db, mode="shadow"))
    other = sqlite3.connect(tmp_path / "a.db", isolation_level=None)
    other.execute("BEGIN IMMEDIATE")
    try:
        t0 = time.perf_counter()
        answer = json.loads(await stub_dispatcher(world).execute(
            "transfer_stablecoin", params={"to": "0x1", "amount": 1}))
        assert time.perf_counter() - t0 < 1.0, "shadow waited for the lock"
        assert answer["status"] == "ok" and world.count("service") == 1
    finally:
        other.execute("ROLLBACK")
        other.close()
        install(previous)
    assert db.fetchall_sync("SELECT COUNT(*) FROM workflow_runs")[0][0] == 0
