"""The evidence shadow records the dispatcher's verdict and changes nothing (engines Phase 1).

``ServiceDispatcher.execute`` decides what the durable surfaces may say about a
state change with ``_record_verdict``: settled (attest it, publish it),
broadcast (log the hash, publish nothing) or refused (log the decline). That
verdict is computed from the service's own return value and nothing else, and
until now it left no record of itself — the attestation or the log line it
chose was the only trace, and no later check could be compared against it.

Under engines.evidence.mode = "shadow" each state-modifying
``ServiceDispatcher.execute`` whose service returns an answer writes one
evidence_shadow row (migration 9) naming that verdict. These tests hold, over
dataset 3 of the Phase 0 test plan — every status word in the dispatcher's
three vocabularies, the refusal envelope, the three shapes
``settle_transaction`` returns, ``None``, ``{}`` and a bare string:

  * the row's ``legacy_verdict`` is exactly ``_record_verdict(result)``;
  * the caller is a sha256 and the parameters a sha256 digest — no raw address
    and no raw parameter value is in the row;
  * with the sink installed the envelope a caller receives and every side
    effect the dispatcher takes (the service call, the attestation) are the same
    as with no sink, and a sink that fails changes neither;
  * a database another connection holds does not hold the dispatch: the row is
    dropped at once instead of waiting out sqlite3's five-second busy timeout on
    the event loop's thread, and the dispatch is otherwise the same as with the
    mode off;
  * with no sink — mode "off", the default — nothing is written at all;
  * the gateway installs the sinks at startup only under "shadow", with
    ``MATRIX_EVIDENCE_MODE`` outranking the config, says so in its log only
    then, and takes them out again at shutdown.

And what the table does NOT see, pinned so that no later phase reads it as a
row per state change: a dispatch that ends before the service answers (unknown
action, service unavailable, parameters that do not bind), a service that
raises, and every call through the ``/api/v1`` funnel, which runs service
methods without the dispatcher, write no row.
"""

from __future__ import annotations

import asyncio
import copy
import hashlib
import json
import logging
import sqlite3
import sys
import time
from types import SimpleNamespace
from typing import Any

import pytest

sys.path.insert(0, "tests")
from aiohttp.test_utils import TestClient, TestServer  # noqa: E402

from runtime.blockchain.services import service_dispatcher as dispatch  # noqa: E402
from runtime.blockchain.services.service_dispatcher import (  # noqa: E402
    ACTION_MAP,
    EVIDENCE_SHADOW_COLUMNS,
    ServiceDispatcher,
    _record_verdict,
    evidence_shadow_sink,
    params_digest,
)
from runtime.db.database import Database  # noqa: E402

STATE_ACTION = "transfer_stablecoin"
READ_ACTION = "get_stablecoin_balance"
ACTOR = "0x" + "ab" * 20
RECIPIENT = "0x" + "cd" * 20
PARAMS = {"to": RECIPIENT, "amount": 5, "memo": "rent for march"}
TX = "0x" + "11" * 32


def outcome_shape_corpus() -> list[tuple[str, Any]]:
    """Dataset 3: the input space of the dispatcher's verdict and of report_of.

    Every word of the three status vocabularies as a bare ``{"status": word}``,
    the platform's structured refusal, the three shapes ``settle_transaction``
    returns (tests/test_contract_pairs/test_p4_settle_transaction_shapes.py
    holds that these ARE its shapes), and the shapes with no status at all.
    """
    from runtime.blockchain.services.service_dispatcher import (
        _BROADCAST_STATUSES, _NON_OUTCOME_STATUSES, _REAL_OUTCOME_STATUSES,
    )
    from runtime.blockchain.web3_manager import unconfirmed_broadcast
    from runtime.protocols.outcome_truth import refusal

    cases: list[tuple[str, Any]] = []
    cases += [(f"real:{w}", {"status": w}) for w in sorted(_REAL_OUTCOME_STATUSES)]
    cases += [(f"non:{w}", {"status": w}) for w in sorted(_NON_OUTCOME_STATUSES)]
    cases += [(f"broadcast:{w}", {"status": w, "tx_hash": TX}) for w in sorted(_BROADCAST_STATUSES)]
    cases.append(("refusal-envelope", json.loads(refusal("not available", code="not_deployed"))))
    cases.append(("settle:settled", {
        "tx_hash": TX, "broadcast": True, "status": "submitted", "settled": True,
        "value_moved": True, "block_number": 7, "gas_used": 21000}))
    cases.append(("settle:reverted", {
        "tx_hash": TX, "broadcast": True, "status": "failed", "settled": True,
        "value_moved": False, "block_number": 7,
        "disclosure": "The transaction was mined and REVERTED on-chain. Nothing "
                      "moved. Gas was still spent."}))
    cases.append(("settle:pending", unconfirmed_broadcast(TX)))
    cases.append(("created-pending", {"status": "pending", "created": True}))
    cases.append(("unrecognised-status", {"status": "compliance_hold"}))
    cases.append(("no-status", {"amount_a": 1, "shares_minted": 2}))
    cases.append(("empty", {}))
    cases.append(("none", None))
    cases.append(("bare-string", "done"))
    return cases


CORPUS = outcome_shape_corpus()


def _dispatcher(result: Any, calls: list, *, action: str = STATE_ACTION) -> ServiceDispatcher:
    """A real ServiceDispatcher over a stub registry: the service returns
    *result*, the attestation service records that it was asked."""
    service, method_name = ACTION_MAP[action]

    async def method(**kwargs):
        calls.append(("service", method_name, json.dumps(kwargs, sort_keys=True, default=str)))
        return copy.deepcopy(result)

    async def attest(**kwargs):
        calls.append(("attest", kwargs["data"]["action"], kwargs["data"]["actor"]))
        return {"uid": "0x0"}

    svc = SimpleNamespace(**{method_name: method})
    attestation = SimpleNamespace(attest=attest)
    d = ServiceDispatcher({})
    d._get_registry = lambda: SimpleNamespace(
        get=lambda name: svc if name == service else attestation)
    return d


def _db(tmp_path) -> Database:
    return Database({"database": {"path": str(tmp_path / "shadow.db")}})


def _rows(db: Database) -> list[dict]:
    return [dict(r) for r in db.fetchall_sync("SELECT * FROM evidence_shadow")]


def _envelope(raw: str) -> dict:
    """The envelope minus its one clock reading."""
    body = json.loads(raw)
    body.pop("elapsed_ms", None)
    return body


@pytest.fixture
def no_sink():
    previous = dispatch.set_evidence_shadow_sink(None)
    yield
    dispatch.set_evidence_shadow_sink(previous)


# ── the row says what the legacy verdict said ────────────────────────────────

@pytest.mark.parametrize("case", CORPUS, ids=[c[0] for c in CORPUS])
async def test_the_shadow_row_is_the_legacy_verdict(case, tmp_path, no_sink):
    _, result = case
    db = _db(tmp_path)
    dispatch.set_evidence_shadow_sink(evidence_shadow_sink(db))
    calls: list = []
    await _dispatcher(result, calls).execute(STATE_ACTION, params=dict(PARAMS),
                                             caller_identity=ACTOR)
    rows = _rows(db)
    assert len(rows) == 1, rows
    row = rows[0]
    assert tuple(row) == EVIDENCE_SHADOW_COLUMNS
    assert row["legacy_verdict"] == _record_verdict(result), (case, row)
    assert row["action"] == STATE_ACTION and row["service"] == ACTION_MAP[STATE_ACTION][0]
    assert row["actor_hash"] == hashlib.sha256(ACTOR.encode()).hexdigest()
    assert row["params_digest"] == params_digest(PARAMS)
    assert row["run_id"].startswith("run_") and row["observed_at"] > 0
    if isinstance(result, dict) and result.get("tx_hash"):
        assert row["tx_hash"] == TX
    else:
        assert row["tx_hash"] == ""


def test_the_corpus_reaches_all_three_legacy_verdicts():
    verdicts = {_record_verdict(r) for _, r in CORPUS}
    assert verdicts == {dispatch.RECORD_SETTLED, dispatch.RECORD_BROADCAST,
                        dispatch.RECORD_REFUSED}


async def test_no_raw_address_or_parameter_reaches_the_row(tmp_path, no_sink):
    db = _db(tmp_path)
    dispatch.set_evidence_shadow_sink(evidence_shadow_sink(db))
    await _dispatcher({"status": "success"}, []).execute(
        STATE_ACTION, params=dict(PARAMS), caller_identity=ACTOR)
    text = json.dumps(_rows(db)).lower()
    for raw in (ACTOR, RECIPIENT, "rent for march", ACTOR[2:], RECIPIENT[2:]):
        assert raw.lower() not in text, raw


async def test_an_injected_caller_identity_is_digested_not_stored(tmp_path, no_sink):
    """A service that declares ``caller_identity`` is called with it; the digest
    covers what the method was called with and the address stays out."""
    db = _db(tmp_path)
    dispatch.set_evidence_shadow_sink(evidence_shadow_sink(db))
    service, method_name = ACTION_MAP[STATE_ACTION]
    seen: dict = {}

    async def method(to, amount, memo, caller_identity="", caller_source=""):
        seen.update(to=to, amount=amount, memo=memo, caller_identity=caller_identity,
                    caller_source=caller_source)
        return {"status": "success"}

    d = ServiceDispatcher({})
    svc = SimpleNamespace(**{method_name: method})
    attestation = SimpleNamespace(attest=lambda **kw: _async_none())
    d._get_registry = lambda: SimpleNamespace(get=lambda n: svc if n == service else attestation)
    await d.execute(STATE_ACTION, params=dict(PARAMS), caller_identity=ACTOR)
    (row,) = _rows(db)
    assert seen["caller_identity"] == ACTOR
    assert row["params_digest"] == params_digest(seen)
    assert ACTOR.lower() not in json.dumps(row).lower()


async def _async_none():
    return None


def test_the_digest_is_the_canonical_form_in_any_process():
    assert params_digest({"b": 1, "a": "é"}) == hashlib.sha256(
        '{"a":"é","b":1}'.encode("utf-8")).hexdigest()
    assert params_digest({"a": 1, "b": 2}) == params_digest({"b": 2, "a": 1})


# ── and nothing else changes ─────────────────────────────────────────────────

@pytest.mark.parametrize("case", CORPUS, ids=[c[0] for c in CORPUS])
async def test_the_envelope_and_the_side_effects_are_the_same_with_the_sink(case, tmp_path, no_sink):
    _, result = case
    calls_off: list = []
    off = await _dispatcher(result, calls_off).execute(
        STATE_ACTION, params=dict(PARAMS), caller_identity=ACTOR)

    dispatch.set_evidence_shadow_sink(evidence_shadow_sink(_db(tmp_path)))
    calls_on: list = []
    on = await _dispatcher(result, calls_on).execute(
        STATE_ACTION, params=dict(PARAMS), caller_identity=ACTOR)

    assert _envelope(on) == _envelope(off)
    assert calls_on == calls_off


async def test_a_failing_sink_changes_nothing(no_sink):
    def broken(row):
        raise RuntimeError("disk full")

    calls_off: list = []
    off = await _dispatcher({"status": "success"}, calls_off).execute(
        STATE_ACTION, params=dict(PARAMS), caller_identity=ACTOR)
    dispatch.set_evidence_shadow_sink(broken)
    calls_on: list = []
    on = await _dispatcher({"status": "success"}, calls_on).execute(
        STATE_ACTION, params=dict(PARAMS), caller_identity=ACTOR)
    assert _envelope(on) == _envelope(off)
    assert calls_on == calls_off and ("attest", STATE_ACTION, ACTOR) in calls_on


async def test_the_sink_is_handed_nothing_the_dispatch_goes_on_to_read(no_sink):
    """The row is built for the sink alone: strings and one float, a digest of
    the parameters and never the parameters or the result. A sink that writes
    into everything it is handed, then empties it, changes neither the envelope
    nor a side effect."""
    handed: list = []

    def writing(row):
        handed.append({key: type(value).__name__ for key, value in row.items()})
        for key in list(row):
            row[key] = "written by the sink"
        row.clear()

    result = {"status": "success", "tx_hash": TX}
    calls_off: list = []
    off = await _dispatcher(result, calls_off).execute(
        STATE_ACTION, params=dict(PARAMS), caller_identity=ACTOR)
    dispatch.set_evidence_shadow_sink(writing)
    calls_on: list = []
    on = await _dispatcher(result, calls_on).execute(
        STATE_ACTION, params=dict(PARAMS), caller_identity=ACTOR)
    assert _envelope(on) == _envelope(off)
    assert calls_on == calls_off and ("attest", STATE_ACTION, ACTOR) in calls_on
    (types,) = handed
    assert tuple(types) == EVIDENCE_SHADOW_COLUMNS
    assert set(types.values()) <= {"str", "float"}, types


async def test_mode_off_writes_nothing(tmp_path, no_sink):
    db = _db(tmp_path)  # migration 9 applied, no sink installed
    await _dispatcher({"status": "success"}, []).execute(
        STATE_ACTION, params=dict(PARAMS), caller_identity=ACTOR)
    assert _rows(db) == []


async def test_a_read_writes_no_row(tmp_path, no_sink):
    db = _db(tmp_path)
    dispatch.set_evidence_shadow_sink(evidence_shadow_sink(db))
    await _dispatcher({"balance": 3}, [], action=READ_ACTION).execute(
        READ_ACTION, params={"address": ACTOR})
    assert _rows(db) == []


# ── a database someone else holds does not hold the dispatch ────────────────

class _Held:
    """Another connection holding the database's write lock, as an operator's
    sqlite3 session, an external VACUUM or a second gateway process would."""

    def __init__(self, path):
        self.conn = sqlite3.connect(str(path), isolation_level=None)

    def __enter__(self):
        self.conn.execute("BEGIN IMMEDIATE")
        return self

    def __exit__(self, *exc):
        self.conn.execute("ROLLBACK")
        self.conn.close()


async def test_a_locked_database_drops_the_row_instead_of_waiting(tmp_path, no_sink, caplog):
    """Written through the platform connection, this row waited out the
    five-second busy timeout on the event loop's thread before failing; under a
    request's wait_for budget that was a timeout that dropped the attestation.
    Now it fails at once and the dispatch is exactly the mode-off dispatch."""
    calls_off: list = []
    off = await _dispatcher({"status": "success"}, calls_off).execute(
        STATE_ACTION, params=dict(PARAMS), caller_identity=ACTOR)

    db = _db(tmp_path)
    dispatch.set_evidence_shadow_sink(evidence_shadow_sink(db))
    calls_on: list = []
    with _Held(db.db_path), caplog.at_level(logging.WARNING):
        started = time.perf_counter()
        on = await asyncio.wait_for(_dispatcher({"status": "success"}, calls_on).execute(
            STATE_ACTION, params=dict(PARAMS), caller_identity=ACTOR), timeout=1.0)
        elapsed = time.perf_counter() - started
    assert elapsed < 0.5, f"the dispatch waited {elapsed:.2f}s on a held database"
    assert _envelope(on) == _envelope(off) and calls_on == calls_off
    assert ("attest", STATE_ACTION, ACTOR) in calls_on
    assert _rows(db) == []
    assert any("Evidence shadow row not written" in r.getMessage() for r in caplog.records)

    # Released, the next dispatch is recorded again through the same sink.
    await _dispatcher({"status": "success"}, []).execute(
        STATE_ACTION, params=dict(PARAMS), caller_identity=ACTOR)
    assert [r["legacy_verdict"] for r in _rows(db)] == [dispatch.RECORD_SETTLED]


async def test_a_closed_database_writes_nothing_and_changes_nothing(tmp_path, no_sink):
    db = _db(tmp_path)
    dispatch.set_evidence_shadow_sink(evidence_shadow_sink(db))
    await db.close()
    calls_off: list = []
    dispatch.set_evidence_shadow_sink(None)
    off = await _dispatcher({"status": "success"}, calls_off).execute(
        STATE_ACTION, params=dict(PARAMS), caller_identity=ACTOR)
    dispatch.set_evidence_shadow_sink(evidence_shadow_sink(db))
    calls_on: list = []
    on = await _dispatcher({"status": "success"}, calls_on).execute(
        STATE_ACTION, params=dict(PARAMS), caller_identity=ACTOR)
    assert _envelope(on) == _envelope(off) and calls_on == calls_off


async def test_rows_land_in_the_file_the_database_reads_after_a_restore(tmp_path, no_sink):
    """``Database.restore_from`` replaces the file and the connection. The rows
    go through the Database's own connection, so the restored file is what is
    read and written afterwards — a second connection held open beside it kept
    the old write-ahead log alive, and the restore read the old rows back."""
    db = _db(tmp_path)
    sink = evidence_shadow_sink(db)
    dispatch.set_evidence_shadow_sink(sink)
    await _dispatcher({"status": "success"}, []).execute(
        STATE_ACTION, params=dict(PARAMS), caller_identity=ACTOR)
    snapshot = tmp_path / "snapshot.db"
    await db.backup_to(snapshot)
    await _dispatcher({"status": "success"}, []).execute(
        STATE_ACTION, params=dict(PARAMS), caller_identity=ACTOR)
    assert len(_rows(db)) == 2
    await db.restore_from(snapshot)
    assert len(_rows(db)) == 1
    await _dispatcher({"status": "success"}, []).execute(
        STATE_ACTION, params=dict(PARAMS), caller_identity=ACTOR)
    assert len(_rows(db)) == 2
    await db.close()


# ── what the table does not see ─────────────────────────────────────────────

def _failing_dispatcher(case: str, calls: list) -> tuple[ServiceDispatcher, str]:
    service, method_name = ACTION_MAP[STATE_ACTION]

    async def raises_not_implemented(**kwargs):
        calls.append("service")
        raise NotImplementedError("not in this build")

    async def raises(**kwargs):
        calls.append("service")
        raise ValueError("the service failed")

    async def narrow(to, amount):  # PARAMS carries a memo: the call cannot bind
        calls.append("service")
        return {"status": "success"}

    methods = {"raises-not-implemented": raises_not_implemented, "raises": raises,
               "params-do-not-bind": narrow}
    d = ServiceDispatcher({})
    if case == "service-unavailable":
        def get(name):
            raise KeyError(name)
        d._get_registry = lambda: SimpleNamespace(get=get)
    else:
        svc = SimpleNamespace(**{method_name: methods.get(case, narrow)})
        d._get_registry = lambda: SimpleNamespace(get=lambda n: svc)
    return d, ("no_such_action_p1" if case == "unknown-action" else STATE_ACTION)


@pytest.mark.parametrize("case", ["unknown-action", "service-unavailable", "params-do-not-bind",
                                  "raises-not-implemented", "raises"])
async def test_a_dispatch_the_verdict_never_reads_writes_no_row(case, tmp_path, no_sink):
    """Pinned as it is: the shadow sits after ``_record_verdict``, which only a
    returned answer reaches. These dispatches report an error and leave no row;
    the phase that records them changes this test."""
    db = _db(tmp_path)
    dispatch.set_evidence_shadow_sink(evidence_shadow_sink(db))
    calls: list = []
    d, action = _failing_dispatcher(case, calls)
    envelope = json.loads(await d.execute(action, params=dict(PARAMS), caller_identity=ACTOR))
    assert envelope["status"] == "error", envelope
    assert calls == (["service"] if case.startswith("raises") else [])
    assert _rows(db) == []


async def test_the_api_v1_funnel_writes_no_row(tmp_path, no_sink):
    """Pinned as it is: ``ServiceRoutes._call`` runs the service method itself,
    so a state change made through the /api/v1 routes never reaches the
    dispatcher and never reaches the shadow."""
    from gateway.service_routes import ServiceRoutes
    db = _db(tmp_path)
    dispatch.set_evidence_shadow_sink(evidence_shadow_sink(db))
    service, method_name = ACTION_MAP[STATE_ACTION]
    calls: list = []

    async def method(**kwargs):
        calls.append(kwargs)
        return {"status": "success", "tx_hash": TX, "settled": True}

    svc = SimpleNamespace(**{method_name: method})
    routes = SimpleNamespace(_get_registry=lambda: SimpleNamespace(get=lambda n: svc),
                             _maybe_ripple=lambda *args: None)
    result = await ServiceRoutes._call(routes, service, method_name, **PARAMS)
    assert calls == [PARAMS] and result["status"] == "success"
    assert _rows(db) == []


# ── the gateway switch ───────────────────────────────────────────────────────

def test_the_mode_defaults_to_off(monkeypatch):
    from gateway.server import evidence_mode
    monkeypatch.delenv("MATRIX_EVIDENCE_MODE", raising=False)
    assert evidence_mode({}) == "off"
    assert evidence_mode({"engines": {}}) == "off"
    assert evidence_mode({"engines": {"evidence": {"mode": "shadow"}}}) == "shadow"


def test_the_environment_outranks_the_config(monkeypatch):
    from gateway.server import evidence_mode
    monkeypatch.setenv("MATRIX_EVIDENCE_MODE", "shadow")
    assert evidence_mode({"engines": {"evidence": {"mode": "off"}}}) == "shadow"
    monkeypatch.setenv("MATRIX_EVIDENCE_MODE", "off")
    assert evidence_mode({"engines": {"evidence": {"mode": "shadow"}}}) == "off"


@pytest.mark.parametrize("value", ["enforce", "on", "SHADOWS", "1"])
def test_an_unknown_mode_records_nothing(value, monkeypatch):
    from gateway.server import evidence_mode
    monkeypatch.delenv("MATRIX_EVIDENCE_MODE", raising=False)
    assert evidence_mode({"engines": {"evidence": {"mode": value}}}) == "off"


def test_the_example_config_ships_off():
    example = json.loads(open("matrix.config.json.example", encoding="utf-8").read())
    assert example["engines"]["evidence"]["mode"] == "off"


def _gateway(mode: str | None, scratch):
    """A gateway over *scratch* (a pytest tmp_path, which pytest prunes)."""
    from gateway.server import GatewayServer
    from test_route_sweep import SWEEP_CONFIG
    config = {**SWEEP_CONFIG, "memory_dir": str(scratch),
              "database": {"path": f"{scratch}/a.db"}}
    if mode is not None:
        config["engines"] = {"evidence": {"mode": mode}}
    return GatewayServer(config)


def _engine_lines(caplog) -> list[str]:
    return [r.getMessage() for r in caplog.records
            if r.name == "gateway.server" and r.getMessage().startswith("Engines:")]


async def test_a_shadow_gateway_installs_both_sinks_and_removes_them(tmp_path, caplog):
    from runtime.protocols import urf
    server = _gateway("shadow", tmp_path)
    with caplog.at_level(logging.INFO, logger="gateway.server"):
        async with TestClient(TestServer(server.create_app())):
            assert server._evidence_mode == "shadow"
            assert urf.current_decision_sink() is not None
            assert dispatch.current_evidence_shadow_sink() is not None
    assert urf.current_decision_sink() is None
    assert dispatch.current_evidence_shadow_sink() is None
    (line,) = _engine_lines(caplog)
    assert line.startswith("Engines: evidence mode=shadow (security backend=")


@pytest.mark.parametrize("mode", [None, "off"])
async def test_an_off_gateway_installs_nothing_and_says_nothing(mode, tmp_path, caplog):
    from runtime.protocols import urf
    server = _gateway(mode, tmp_path)
    with caplog.at_level(logging.DEBUG):
        async with TestClient(TestServer(server.create_app())):
            assert server._evidence_mode == "off"
            assert urf.current_decision_sink() is None
            assert dispatch.current_evidence_shadow_sink() is None
    assert _engine_lines(caplog) == []


async def test_a_bridge_action_on_a_shadow_gateway_writes_one_row(tmp_path):
    server = _gateway("shadow", tmp_path)
    calls: list = []
    async with TestClient(TestServer(server.create_app())) as client:
        server.service_dispatcher = _dispatcher({"status": "success"}, calls)
        resp = await client.post("/bridge/v1/action",
                                 json={"action": STATE_ACTION, "params": dict(PARAMS)})
        assert resp.status == 200, await resp.text()
        rows = [dict(r) for r in server.react_loop.memory.db.fetchall_sync(
            "SELECT * FROM evidence_shadow")]
    assert [r["legacy_verdict"] for r in rows] == [dispatch.RECORD_SETTLED]
    assert rows[0]["action"] == STATE_ACTION
