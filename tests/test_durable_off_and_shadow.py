"""Engines Phase 2: durable execution OFF is main, and SHADOW changes no answer.

``engines.durable.mode`` is off by default, and the promise for off is the
strongest one the phase makes: behaviour byte-identical to main. "Identical"
is only a claim until it is measured on both trees with the same instrument,
so this file carries the instrument (``measure``) and a golden it produced AT
MAIN, and recomputes it here.

THE INSTRUMENT. ``ServiceDispatcher.execute`` over EVERY ``ACTION_MAP`` name,
each under every answer in ``CASES`` — a settled success, a broadcast, a
broadcast the chain has not confirmed, a ``not_deployed`` refusal, a plain-text
answer, a raise, a ``NotImplementedError``, the service unavailable, the method
missing, parameters that do not bind, and a settled success with no identity —
against a stand-in registry defined HERE (not the shared durable harness: the
golden must come from running this same code at main, where nothing durable
exists). Per call it records the envelope byte for byte with ``elapsed_ms``
removed, what the service was handed, every ``_attest_action`` /
``_record_broadcast`` / ``_attest_refusal`` call (arguments normalised: the
attestation's ``timestamp`` and its per-process salted ``params_hash`` are
replaced by their shape) and every feed ``ingest``. It uses only
``ServiceDispatcher``, ``ACTION_MAP``, ``_STATE_MODIFYING_ACTIONS`` and
``set_evidence_shadow_sink``, which exist identically on main.

THE GOLDEN, ``tests/baseline/durable_off_envelopes.json``, was written by
running ``measure`` in a separate interpreter whose import path is a checkout of
main (``runtime.durable`` absent there, recorded as such), and names main's
commit by its subject. It keeps one digest per action and one per case — so a difference names
both the action and the answer that moved — the totals per case, and a readable
sample. To re-measure: ``ENGINES_BASELINE=write DURABLE_OFF_MAIN_TREE=<a
checkout of main>``; with ``ENGINES_BASELINE=write`` alone the golden is left
as it is and checked, because a golden measured on this branch would prove
nothing about main.

AT HEAD, OFF. The same measure with ``MATRIX_DURABLE_MODE`` unset and no engine
installed must equal the golden; ``wiring.current()`` stays None and no durable
write, key lookup or outbox row is attempted; ``wiring.keyed`` reads no header;
and a ``GatewayServer`` whose config says nothing installs no engine and answers
``/ready`` with main's body shape.

SHADOW. With a shadow engine installed, for every state-modifying name under
every case the record (envelope, service call, legacy attest/broadcast/refusal
records and feed publishes) equals the off record; one run is written per
dispatch, in the state the answer calls for, with the outbox rows the legacy
path handed off written as handed off (attempts 0, ``next_at`` NULL); a
replayed Idempotency-Key runs again (two effects), both runs carry the key's
digest and ``idempotency_keys`` binds the first; an engine whose every write
fails changes no answer and no effect count; every shadow write is taken with
``wait=False``. The twin tools too: ``ToolDispatcher.dispatch`` of a signing
twin action journals a run and returns the outcome off returns.
"""
from __future__ import annotations

import asyncio
import contextlib
import hashlib
import json
import os
import sqlite3
import subprocess
import sys
import tempfile
from pathlib import Path
from types import SimpleNamespace
from typing import Any

import pytest

# Only what main has: this module is imported at main to write the golden.
from runtime.blockchain.services import service_dispatcher as dispatch
from runtime.blockchain.services.service_dispatcher import (
    ACTION_MAP, ServiceDispatcher, _STATE_MODIFYING_ACTIONS,
)

ROOT = Path(__file__).resolve().parent.parent
GOLDEN = ROOT / "tests" / "baseline" / "durable_off_envelopes.json"
WRITE = os.environ.get("ENGINES_BASELINE", "").strip().lower() == "write"
MAIN_TREE_ENV = "DURABLE_OFF_MAIN_TREE"

WALLET = "0x" + "ab" * 20
OTHER = "0x" + "cd" * 20
ACTIONS = sorted(ACTION_MAP)
STATE_MODIFYING = sorted(a for a in _STATE_MODIFYING_ACTIONS if a in ACTION_MAP)

SETTLED = {"status": "success", "tx_hash": "0x" + "22" * 32, "settled": True, "value_usd": 12.5}
BROADCAST = {"status": "submitted", "tx_hash": "0x" + "33" * 32}
UNCONFIRMED = {"status": "pending", "tx_hash": "0x" + "44" * 32, "settled": False,
               "broadcast": True}
REFUSED = {"status": "not_deployed", "error": "contracts are not deployed"}


class StandInFailure(RuntimeError):
    """What a stand-in service raises when the case says so."""


#: case -> (the service's answer, how the call is made). The answer is a value
#: returned, an exception raised, or a word for what the registry does instead.
CASES: dict[str, dict[str, Any]] = {
    "settled": {"answer": SETTLED},
    "broadcast": {"answer": BROADCAST},
    "unconfirmed": {"answer": UNCONFIRMED},
    "refused": {"answer": REFUSED},
    "text_answer": {"answer": "done"},
    "raises": {"answer": StandInFailure("stand-in service failed")},
    "not_implemented": {"answer": NotImplementedError("stand-in: not in this build")},
    "unavailable": {"answer": SETTLED, "registry": "unavailable"},
    "no_method": {"answer": SETTLED, "registry": "no_method"},
    "unbound": {"answer": SETTLED, "params": "unbound"},
    "anonymous": {"answer": SETTLED, "identity": ""},
}
CASE_NAMES = tuple(CASES)


# ── the stand-ins: a registry, the attestation service, the feed ───────────

def _plain(value: Any) -> Any:
    """A JSON-plain copy (what the golden can hold)."""
    return json.loads(json.dumps(value, sort_keys=True, default=str))


def _normalise_attestation(kwargs: dict) -> dict:
    """The attestation service's arguments with the two fields that differ run
    to run replaced by their shape: the wall-clock ``timestamp`` and
    ``params_hash`` (Python's per-process salted ``hash()``)."""
    out = _plain(kwargs)
    data = out.get("data")
    if isinstance(data, dict):
        if "timestamp" in data:
            data["timestamp"] = "<int>" if isinstance(data["timestamp"], int) else data["timestamp"]
        if "params_hash" in data:
            try:
                int(data["params_hash"])
                data["params_hash"] = "<int as str>"
            except (TypeError, ValueError):
                pass
    return out


def _takes_identity(service: str, method: str) -> bool:
    """About half the stand-in methods declare ``caller_identity`` (a fixed
    choice), so both sides of the dispatcher's injection are measured."""
    return hashlib.sha256(f"{service}.{method}".encode()).hexdigest()[0] in "01234567"


#: service -> its ACTION_MAP methods (and the attestation service's ``attest``).
METHODS: dict[str, set[str]] = {}
for _service, _method in ACTION_MAP.values():
    METHODS.setdefault(_service, set()).add(_method)
METHODS.setdefault("attestation", set()).add("attest")


class StandIns:
    """Every method of every ACTION_MAP service, keyword-only (so parameters
    that do not bind are refused before the call), answering ``answer``. The
    attestation service's ``attest`` is also where ``_attest_action`` delivers,
    told apart by its ``schema_uid`` argument."""

    def __init__(self, answer: Any, registry_mode: str = "") -> None:
        self.answer = answer
        self.registry_mode = registry_mode
        self.log: list[tuple[str, Any]] = []
        self.raw_attestations: list[dict] = []

    def _answer(self, service: str, method: str, params: dict) -> Any:
        self.log.append(("service", {"service": service, "method": method,
                                     "params": _plain(params)}))
        if isinstance(self.answer, BaseException):
            # A fresh exception each call: one instance re-raised grows its traceback.
            raise type(self.answer)(*self.answer.args)
        return dict(self.answer) if isinstance(self.answer, dict) else self.answer

    def _attested(self, schema_uid, data, recipient) -> dict:
        kwargs = {"schema_uid": schema_uid, "data": data, "recipient": recipient}
        self.raw_attestations.append(json.loads(json.dumps(kwargs, default=str)))
        self.log.append(("attestation", _normalise_attestation(kwargs)))
        return {"status": "queued"}

    def method(self, service: str, method: str):
        stand_in = self
        if _takes_identity(service, method):
            async def call(*, to=None, amount=None, marker=None, wallet=None, schema_uid=None,
                           data=None, recipient=None, caller_identity=None, caller_source=None):
                if schema_uid is not None:
                    return stand_in._attested(schema_uid, data, recipient)
                return stand_in._answer(service, method, {
                    "to": to, "amount": amount, "marker": marker, "wallet": wallet,
                    "caller_identity": caller_identity, "caller_source": caller_source})
        else:
            async def call(*, to=None, amount=None, marker=None, wallet=None, schema_uid=None,
                           data=None, recipient=None):
                if schema_uid is not None:
                    return stand_in._attested(schema_uid, data, recipient)
                return stand_in._answer(service, method, {
                    "to": to, "amount": amount, "marker": marker, "wallet": wallet})
        return call

    def registry(self, action: str):
        """A registry whose ``get`` builds the named service's stand-in when
        asked: ``unavailable`` makes *action*'s service raise KeyError, and
        ``no_method`` leaves *action*'s method out."""
        target_service, target_method = ACTION_MAP[action]

        def get(name: str):
            if self.registry_mode == "unavailable" and name == target_service:
                raise KeyError(f"stand-in: {name} is not registered")
            methods = {m: self.method(name, m) for m in METHODS.get(name, ())}
            if self.registry_mode == "no_method" and name == target_service:
                methods.pop(target_method, None)
            return SimpleNamespace(**methods)
        return SimpleNamespace(get=get)


class StandInFeed:
    def __init__(self, log: list) -> None:
        self.log = log

    async def ingest(self, **kwargs):
        self.log.append(("feed", _plain(kwargs)))
        self.log.append(("feed_raw", json.loads(json.dumps(kwargs, default=str))))
        return SimpleNamespace(summary=f"performed {kwargs.get('action')}")


def params_for(case: str) -> dict:
    if CASES[case].get("params") == "unbound":
        return {"marker": case, "not_a_parameter": True}
    return {"to": WALLET, "amount": 5, "marker": case, "wallet": OTHER}


def strip_elapsed(envelope: str) -> str:
    """The envelope, byte for byte, without ``elapsed_ms`` (the one field
    that is a stopwatch reading). Re-dumped from the parsed dict, which keeps
    key order, so every other byte is the dispatcher's own."""
    parsed = json.loads(envelope)
    if isinstance(parsed, dict) and "elapsed_ms" in parsed:
        assert isinstance(parsed["elapsed_ms"], int), f"elapsed_ms is not an int: {envelope}"
        parsed = {k: v for k, v in parsed.items() if k != "elapsed_ms"}
        stripped = json.dumps(parsed)
        assert stripped == envelope.replace(', "elapsed_ms": ' + str(json.loads(envelope)[
            "elapsed_ms"]), "", 1), f"the envelope is not json.dumps' own shape: {envelope}"
        return stripped
    return envelope


async def dispatch_one(action: str, case: str) -> tuple[dict, str, StandIns]:
    """One ``ServiceDispatcher.execute`` of *action* under *case*: the record,
    the raw envelope and the stand-ins (for the raw payloads)."""
    spec = CASES[case]
    stand_ins = StandIns(spec["answer"], spec.get("registry", ""))
    d = ServiceDispatcher({})
    registry = stand_ins.registry(action)
    d._get_registry = lambda: registry
    d.attach_feed_engine(StandInFeed(stand_ins.log))
    original_attest = d._attest_action

    def spy(kind: str, original):
        async def record(action_, service_name, params, result, *, actor="", actor_source="",
                         actor_claimed=""):
            stand_ins.log.append((kind, _plain({
                "action": action_, "service_name": service_name, "params": params,
                "result": result, "actor": actor, "actor_source": actor_source,
                "actor_claimed": actor_claimed})))
            return await original(action_, service_name, params, result, actor=actor,
                                  actor_source=actor_source, actor_claimed=actor_claimed)
        return record

    d._attest_action = spy("attest_action", original_attest)
    d._record_broadcast = spy("broadcast_record", d._record_broadcast)
    d._attest_refusal = spy("refusal_record", d._attest_refusal)

    identity = spec.get("identity", WALLET)
    envelope = await d.execute(action, params=params_for(case), caller_identity=identity,
                               caller_source="" if identity else "handoff")
    # The feed publish is a task the dispatch created; let it run.
    for _ in range(3):
        await asyncio.sleep(0)
    record: dict[str, Any] = {"envelope": strip_elapsed(envelope)}
    for kind in ("service", "attest_action", "attestation", "broadcast_record",
                 "refusal_record", "feed"):
        record[kind] = [entry for k, entry in stand_ins.log if k == kind]
    return record, envelope, stand_ins


async def measure_one(action: str, case: str) -> dict:
    return (await dispatch_one(action, case))[0]


async def measure_records(actions=None, cases=None) -> dict[str, dict[str, dict]]:
    """``{action: {case: record}}`` with no evidence-shadow sink installed."""
    previous = dispatch.set_evidence_shadow_sink(None)
    try:
        out: dict[str, dict[str, dict]] = {}
        for action in actions or ACTIONS:
            out[action] = {case: await measure_one(action, case)
                           for case in (cases or CASE_NAMES)}
        return out
    finally:
        dispatch.set_evidence_shadow_sink(previous)


def _digest(value: Any) -> str:
    return hashlib.sha256(json.dumps(value, sort_keys=True, separators=(",", ":"),
                                     ensure_ascii=False).encode("utf-8")).hexdigest()


def summarise(records: dict[str, dict[str, dict]], unknown: dict) -> dict:
    """The golden's measured half."""
    totals: dict[str, dict[str, Any]] = {}
    for case in CASE_NAMES:
        cell = {k: 0 for k in ("service", "attest_action", "attestation", "broadcast_record",
                               "refusal_record", "feed")}
        outcomes: dict[str, int] = {}
        for action in records:
            record = records[action][case]
            for k in cell:
                cell[k] += len(record[k])
            env = json.loads(record["envelope"])
            word = f"{env.get('status')}/{env.get('call_outcome')}/{env.get('error_category', '-')}"
            outcomes[word] = outcomes.get(word, 0) + 1
        cell["envelopes"] = outcomes
        totals[case] = cell
    sample_actions = sorted({STATE_MODIFYING[0], "create_attestation",
                             sorted(set(ACTIONS) - set(STATE_MODIFYING))[0]})
    unknown_env = json.loads(unknown["envelope"])
    return {
        "cases": list(CASE_NAMES),
        "actions": len(records),
        "state_modifying": len(STATE_MODIFYING),
        "digest_by_action": {a: _digest(records[a]) for a in sorted(records)},
        "digest_by_case": {c: _digest({a: records[a][c] for a in sorted(records)})
                           for c in CASE_NAMES},
        "totals": totals,
        "sample": {a: records[a] for a in sample_actions},
        "unknown_action": {
            "available_actions_digest": _digest(unknown_env.get("available_actions")),
            "envelope_without_available_actions": {
                k: v for k, v in unknown_env.items() if k != "available_actions"},
            "digest": _digest(unknown),
        },
    }


async def measure_async() -> dict:
    records = await measure_records()
    previous = dispatch.set_evidence_shadow_sink(None)
    try:
        unknown = await measure_one_unknown()
    finally:
        dispatch.set_evidence_shadow_sink(previous)
    return summarise(records, unknown)


async def measure_one_unknown() -> dict:
    """An action ACTION_MAP does not name: the not_found envelope."""
    d = ServiceDispatcher({})
    envelope = await d.execute("no_such_action_anywhere", params={"marker": "unknown"},
                               caller_identity=WALLET)
    return {"envelope": strip_elapsed(envelope)}


def measure() -> dict:
    """What the golden records, measured on whatever tree ``runtime`` is
    imported from. Main-safe: nothing here imports ``runtime.durable``."""
    import importlib.util
    measured = asyncio.run(measure_async())
    measured["durable_package_present"] = importlib.util.find_spec("runtime.durable") is not None
    return measured


# ── helpers for the tests below (these may use what only this branch has) ──

@contextlib.contextmanager
def installed(engine):
    from runtime.durable import wiring
    previous = wiring.install(engine)
    try:
        yield engine
    finally:
        wiring.install(previous)


class FixedClock:
    def __init__(self, now: float = 1_800_000_000.0) -> None:
        self.now = now

    def __call__(self) -> float:
        return self.now


def table(db, name: str) -> list[dict]:
    return [dict(r) for r in db.fetchall_sync(f"SELECT * FROM {name}")]


DURABLE_TABLES = ("workflow_runs", "workflow_steps", "outbox", "idempotency_keys")


@pytest.fixture
def no_mode_env(monkeypatch):
    monkeypatch.delenv("MATRIX_DURABLE_MODE", raising=False)


@pytest.fixture
async def shadow_db(tmp_path, no_mode_env):
    from runtime.db.database import Database
    db = Database({"database": {"path": str(tmp_path / "shadow.db")}})
    yield db
    await db.close()


def shadow_engine(db, clock=None):
    from runtime.durable.wiring import DurableEngine
    return DurableEngine(db, mode="shadow", clock=clock or FixedClock())


@pytest.fixture(scope="module")
def off_records():
    """Every state-modifying name under every case, mode off, measured once."""
    from runtime.durable import wiring
    assert wiring.current() is None, "an engine is installed before the off measurement"
    return asyncio.run(measure_records(STATE_MODIFYING))


# ── OFF: HEAD equals the golden measured at main ────────────────────────────

def _read_golden() -> dict:
    assert GOLDEN.is_file(), (f"{GOLDEN} is missing — measure it at main with "
                              f"ENGINES_BASELINE=write {MAIN_TREE_ENV}=<a checkout of main>")
    return json.loads(GOLDEN.read_text(encoding="utf-8"))


def _write_golden_from_main(main_tree: Path) -> None:
    """Run ``measure`` in an interpreter importing ``runtime`` from *main_tree*
    and write the golden with main's commit."""
    with tempfile.TemporaryDirectory() as scratch:
        out = Path(scratch) / "measured.json"
        code = ("import importlib.util, json, sys\n"
                "spec = importlib.util.spec_from_file_location('durable_off_measure', sys.argv[1])\n"
                "m = importlib.util.module_from_spec(spec)\n"
                "spec.loader.exec_module(m)\n"
                "open(sys.argv[2], 'w').write(json.dumps(m.measure()))\n")
        env = {k: v for k, v in os.environ.items() if k != "MATRIX_DURABLE_MODE"}
        env["PYTHONPATH"] = str(main_tree)
        env["PYTHONDONTWRITEBYTECODE"] = "1"   # measure main, never write into it
        done = subprocess.run([sys.executable, "-c", code, str(Path(__file__).resolve()), str(out)],
                              cwd=str(main_tree), env=env, capture_output=True, text=True,
                              timeout=600)
        assert done.returncode == 0, f"measuring at main failed:\n{done.stderr[-4000:]}"
        measured = json.loads(out.read_text(encoding="utf-8"))

    # By subject: an id does not survive a rewrite of the history.
    from tests.durable_measured_at import measured_at
    where = measured_at(main_tree)
    assert measured.pop("durable_package_present") is False, (
        f"{main_tree} has runtime/durable: it is not main")
    golden = {
        "measured_at": "main",
        "main_commit": where["on_top_of"],
        "measured": where,
        "rule": ("engines.durable.mode off is byte-identical to main: every recorded field of "
                 "every call below, recomputed on this branch with MATRIX_DURABLE_MODE unset and "
                 "no engine installed, equals what main produced"),
        "instrument": ("tests/test_durable_off_and_shadow.py measure(), run in a separate "
                       "interpreter importing runtime from a checkout of main: "
                       "ServiceDispatcher.execute over a stand-in registry defined in that file "
                       "(every method keyword-only, about half declaring caller_identity), no "
                       "evidence-shadow sink, a stand-in feed engine attached"),
        "scope": ("every ACTION_MAP name x every case in 'cases', plus one name ACTION_MAP does "
                  "not have. Per call: the envelope with elapsed_ms removed (every other byte "
                  "kept), the arguments the service received, every _attest_action, "
                  "_record_broadcast and _attest_refusal call, what the attestation service's "
                  "attest received (timestamp and the salted params_hash replaced by their "
                  "shape) and every feed ingest's keyword arguments. digest_by_action is sha256 "
                  "over one action's records for all cases, digest_by_case over one case's "
                  "records for all actions; 'sample' holds three actions' records in full"),
        **measured,
    }
    GOLDEN.parent.mkdir(parents=True, exist_ok=True)
    GOLDEN.write_text(json.dumps(golden, indent=1, sort_keys=True) + "\n", encoding="utf-8")


async def test_mode_off_at_head_equals_the_golden_measured_at_main(no_mode_env, monkeypatch):
    from runtime.durable import journal, keys, outbox, wiring

    main_tree = os.environ.get(MAIN_TREE_ENV, "").strip()
    if WRITE and main_tree:
        _write_golden_from_main(Path(main_tree))
    golden = _read_golden()
    assert golden["measured_at"] == "main" and golden["main_commit"], (
        "the golden does not say it was measured at main")

    attempted: list[str] = []

    def refuse(name):
        def call(*a, **k):
            attempted.append(name)
            raise AssertionError(f"mode off reached runtime.durable {name}")
        return call
    monkeypatch.setattr(journal, "transaction", refuse("journal.transaction"))
    monkeypatch.setattr(keys, "lookup", refuse("keys.lookup"))
    monkeypatch.setattr(outbox, "insert", refuse("outbox.insert"))

    assert wiring.current() is None, "an engine is installed with the mode off"
    head = await measure_async()
    assert wiring.current() is None, "the measurement left an engine installed"
    assert attempted == [], f"mode off attempted durable writes or lookups: {attempted}"

    assert head["cases"] == golden["cases"], "the cases differ from the golden's"
    assert head["actions"] == golden["actions"] and \
        head["state_modifying"] == golden["state_modifying"], (
            f"ACTION_MAP has {head['actions']} names ({head['state_modifying']} state-modifying) "
            f"at HEAD, {golden['actions']} ({golden['state_modifying']}) at main")
    moved_actions = sorted(a for a in set(head["digest_by_action"]) | set(golden["digest_by_action"])
                           if head["digest_by_action"].get(a) != golden["digest_by_action"].get(a))
    moved_cases = sorted(c for c in golden["digest_by_case"]
                         if head["digest_by_case"].get(c) != golden["digest_by_case"][c])
    assert not moved_actions and not moved_cases, (
        f"mode off is not main: {len(moved_actions)} action(s) answer or record differently "
        f"(first: {moved_actions[:5]}) under case(s) {moved_cases}")
    assert head["totals"] == golden["totals"], "the per-case totals differ from main's"
    assert head["sample"] == golden["sample"], "the sampled records differ from main's"
    assert head["unknown_action"] == golden["unknown_action"], (
        "the unknown-action envelope differs from main's")


def test_the_golden_is_well_formed_and_records_what_it_claims():
    golden = _read_golden()
    for key in ("measured_at", "main_commit", "measured", "rule", "instrument", "scope",
                "digest_by_action", "digest_by_case", "totals", "sample", "unknown_action"):
        assert key in golden, f"the golden has no {key!r}"
    from tests import durable_measured_at
    durable_measured_at.check(golden["measured"], GOLDEN.name)
    assert golden["main_commit"] == golden["measured"]["on_top_of"], (
        "the golden names one commit as main's and was measured at another")
    assert len(golden["digest_by_action"]) == golden["actions"] == len(ACTIONS)
    settled = golden["totals"]["settled"]
    # The stand-ins reached every path the golden claims to cover.
    assert settled["service"] == len(ACTIONS), settled
    assert settled["attest_action"] == settled["attestation"] > 0, (
        "no settled state-modifying call reached the attestation service at main")
    assert settled["feed"] == settled["attest_action"], settled
    assert golden["totals"]["broadcast"]["broadcast_record"] > 0
    assert golden["totals"]["refused"]["refusal_record"] > 0
    for case in ("unavailable", "no_method", "unbound"):
        assert golden["totals"][case]["service"] == 0, (case, golden["totals"][case])
    size = GOLDEN.stat().st_size
    assert size < 200_000, f"the golden is {size} bytes; keep it a digest and a sample"


def test_with_the_mode_off_keyed_reads_no_header(no_mode_env):
    from runtime.durable import wiring

    class Untouchable:
        @property
        def headers(self):
            raise AssertionError("mode off read the request's headers")
    assert wiring.current() is None
    with wiring.keyed(Untouchable(), scope="operator|" + WALLET, decision={"evaluation_id": "e"}):
        pass


async def test_a_gateway_with_the_mode_off_installs_nothing_and_ready_keeps_its_shape(
        tmp_path, no_mode_env):
    from unittest.mock import AsyncMock

    from aiohttp.test_utils import TestClient, TestServer

    sys.path.insert(0, str(ROOT / "tests"))
    from gateway.server import GatewayServer
    from runtime.durable import wiring
    from test_route_sweep import SWEEP_CONFIG

    before = wiring.current()
    server = GatewayServer({**SWEEP_CONFIG, "memory_dir": str(tmp_path),
                            "database": {"path": f"{tmp_path}/a.db"}})
    server.react_loop.router.health_check = AsyncMock(return_value={"stand_in": True})
    async with TestClient(TestServer(server.create_app())) as client:
        assert getattr(server, "_durable_engine", "absent") is None, (
            "a gateway with the mode off built a durable engine")
        assert wiring.current() is before, "a gateway with the mode off installed an engine"
        resp = await client.get("/ready", headers={"Authorization": "Bearer k"})
        body = await resp.json()
        assert resp.status == 200, f"/ready is not ready with the mode off: {resp.status} {body}"
        assert set(body) == {"ready", "ref"} and body["ready"] is True \
            and isinstance(body["ref"], str), f"/ready's body changed shape: {body}"
        db = server.react_loop.memory.db
        for name in DURABLE_TABLES:
            assert table(db, name) == [], f"{name} has rows with the mode off"
    assert wiring.current() is before


# ── SHADOW: every answer and every legacy effect is off's ───────────────────

def _expected_run(record: dict) -> tuple[str, list[tuple[str, str]], set[str]]:
    """The run a shadow dispatch writes, derived from what the OFF record says
    the dispatcher did: (state, [(step, state)], outbox kinds)."""
    env = json.loads(record["envelope"])
    if env.get("status") == "ok":
        word = ("settled" if record["attest_action"] else
                "broadcast" if record["broadcast_record"] else "refused")
        kinds = ({"attest"} if record["attest_action"] else set()) | \
            ({"feed"} if record["feed"] else set())
        return "COMPLETE", [("start", "opened"), ("call", "began"), ("return", word)], kinds
    if record["service"]:
        # The service was called and raised (its call is logged before it raises).
        return "FAIL", [("start", "opened"), ("call", "began"), ("raise", "raised")], set()
    why = {"service_unavailable": "service_unavailable", "validation": "invalid_parameters",
           "service_error": "no_such_method"}[env["error_category"]]
    return "ABORT", [("start", "opened"), ("abort", why)], set()


def _no_raw_address(db) -> None:
    raw = [WALLET.lower(), WALLET[2:].lower(), OTHER.lower(), OTHER[2:].lower()]
    for name in DURABLE_TABLES:
        for row in table(db, name):
            text = json.dumps(row, default=str).lower()
            assert not any(r in text for r in raw), f"{name} holds a raw address: {row}"


async def test_shadow_answers_and_legacy_effects_equal_off_and_one_run_is_written_per_dispatch(
        shadow_db, off_records, monkeypatch):
    from runtime.durable import journal, wiring

    db = shadow_db
    clock = FixedClock()
    engine = shadow_engine(db, clock)
    waits: list[bool] = []
    real_transaction = journal.transaction

    def watched(db_, work, *, wait):
        waits.append(wait)
        return real_transaction(db_, work, wait=wait)
    monkeypatch.setattr(journal, "transaction", watched)

    seen: set[str] = set()
    last_rowid = 0
    dispatches = 0
    with installed(engine):
        for action in STATE_MODIFYING:
            for case in CASE_NAMES:
                record, envelope, stand_ins = await dispatch_one(action, case)
                dispatches += 1
                off = off_records[action][case]
                assert record == off, (
                    f"shadow changed {action}/{case}: "
                    f"{ {k: (record[k], off[k]) for k in record if record[k] != off[k]} }")
                new = [dict(r) for r in db.fetchall_sync(
                    "SELECT rowid AS n, * FROM workflow_runs WHERE rowid > ? ORDER BY rowid",
                    (last_rowid,))]
                assert len(new) == 1, f"{action}/{case} wrote {len(new)} runs, not one"
                run = new[0]
                last_rowid = run.pop("n")
                assert run["run_id"] not in seen, f"{action}/{case}: a run id was reused"
                seen.add(run["run_id"])
                state, steps, kinds = _expected_run(off)
                assert (run["action"], run["service"]) == (action, ACTION_MAP[action][0])
                assert run["state"] == state, (
                    f"{action}/{case}: run is {run['state']}, the answer calls for {state}")
                assert run["terminal_at"] == clock.now and run["started_at"] == clock.now
                assert run["key"] == "" and run["decision_ref"] == ""
                assert run["params_digest"] == journal.digest(params_for(case))
                identity = CASES[case].get("identity", WALLET)
                assert run["actor_hash"] == journal.actor_hash(identity)
                got_steps = [(s["name"], s["state"]) for s in journal.get_steps(db, run["run_id"])]
                assert got_steps == steps, f"{action}/{case}: steps {got_steps}, expected {steps}"
                rows = [dict(r) for r in db.fetchall_sync(
                    "SELECT * FROM outbox WHERE run_id = ?", (run["run_id"],))]
                assert {r["kind"] for r in rows} == kinds and len(rows) == len(kinds), (
                    f"{action}/{case}: outbox rows {rows}, the legacy path handed off {kinds}")
                for r in rows:
                    assert (r["attempts"], r["next_at"], r["done_at"]) == (0, None, clock.now), (
                        f"{action}/{case}: a shadow outbox row is not written as handed off: {r}")
                    if r["kind"] == "feed":
                        delivered = [e for k, e in stand_ins.log if k == "feed_raw"]
                        assert r["payload_digest"] == journal.digest(delivered[0]), (
                            f"{action}/{case}: the feed row does not describe what was published")
                    else:
                        sent = stand_ins.raw_attestations[0]
                        ts = sent["data"]["timestamp"]
                        candidates = {journal.digest({**sent, "data": {**sent["data"],
                                                                        "timestamp": t}})
                                      for t in (ts - 1, ts, ts + 1)}
                        assert r["payload_digest"] in candidates, (
                            f"{action}/{case}: the attest row does not describe what was attested")
        assert wiring.current() is engine
        # The loop, in shadow, delivers nothing: the legacy path already did.
        outbox_before = table(db, "outbox")
        assert await engine.loop.tick() == 0
        assert table(db, "outbox") == outbox_before, "the shadow loop touched the outbox"

    assert len(seen) == dispatches == len(STATE_MODIFYING) * len(CASE_NAMES)
    assert table(db, "idempotency_keys") == [], "a dispatch with no key bound one"
    assert waits and not any(waits), (
        f"{sum(waits)} of {len(waits)} shadow writes waited for the database")
    assert engine.health()["open_runs"] == 0, "a shadow run was left open in memory"
    _no_raw_address(db)


async def test_shadow_reads_are_not_journaled(shadow_db):
    db = shadow_db
    reads = sorted(set(ACTIONS) - set(STATE_MODIFYING))[:10]
    off = await measure_records(reads, ["settled", "raises"])
    with installed(shadow_engine(db)):
        on = await measure_records(reads, ["settled", "raises"])
    assert on == off, "shadow changed a read's answer"
    assert table(db, "workflow_runs") == [], "shadow journaled a read"


async def test_a_replayed_key_in_shadow_runs_again_and_both_runs_carry_the_key(
        shadow_db, off_records):
    from runtime.durable import journal, keys, wiring

    db = shadow_db
    engine = shadow_engine(db)
    scope = "operator|" + WALLET
    with installed(engine):
        for action in STATE_MODIFYING:
            client_key = f"replay-{action}"
            answers = []
            effects = 0
            for n in range(2):
                request = SimpleNamespace(headers={"Idempotency-Key": client_key})
                with wiring.keyed(request, scope=scope, decision={"evaluation_id": f"ev-{n}"}):
                    record, envelope, stand_ins = await dispatch_one(action, "settled")
                answers.append(envelope)
                effects += len(record["service"])
                assert record == off_records[action]["settled"], (
                    f"shadow changed the answer to a keyed {action} (request {n + 1})")
            assert effects == 2, f"a replayed key in shadow ran {action} {effects} time(s), not 2"
            digest = keys.scoped(wiring.BRIDGE_ACTION, scope, client_key)
            runs = [dict(r) for r in db.fetchall_sync(
                "SELECT * FROM workflow_runs WHERE action = ? ORDER BY rowid", (action,))]
            assert len(runs) == 2 and all(r["state"] == "COMPLETE" for r in runs), runs
            assert [r["key"] for r in runs] == [digest, digest], (
                f"{action}: both runs must carry the key's digest: {[r['key'] for r in runs]}")
            assert [r["decision_ref"] for r in runs] == ["ev-0", "ev-1"]
            bound = keys.lookup(db, digest)
            assert bound == (runs[0]["run_id"], journal.text_digest(answers[0])), (
                f"{action}: idempotency_keys binds {bound}, not the first run and its answer")
    assert len(table(db, "idempotency_keys")) == len(STATE_MODIFYING)
    _no_raw_address(db)


async def test_a_key_another_process_binds_between_lookup_and_call_still_leaves_a_run_in_shadow(
        shadow_db, off_records, monkeypatch):
    """Shadow records every journaled action. The key is looked up when the
    run begins and bound when it opens; another gateway process on the same
    database can bind it in between (here: while the dispatcher asks the
    registry for the service, which is between the two). The dispatch still
    runs, as it does with the mode off — so it must still leave its run, carrying
    the key's digest, as the sequential replay above does."""
    from runtime.durable import keys, wiring

    db = shadow_db
    action = STATE_MODIFYING[0]
    scope = "operator|" + WALLET
    digest = keys.scoped(wiring.BRIDGE_ACTION, scope, "raced")
    plain_registry = StandIns.registry

    def racing_registry(self, action_):
        registry = plain_registry(self, action_)

        def get(name):
            db.execute_sync("INSERT OR IGNORE INTO idempotency_keys (key, run_id, response_digest, "
                            "created_at) VALUES (?, 'run_of_another_process', '', 1)", (digest,))
            return registry.get(name)
        return SimpleNamespace(get=get)
    monkeypatch.setattr(StandIns, "registry", racing_registry)

    with installed(shadow_engine(db)):
        request = SimpleNamespace(headers={"Idempotency-Key": "raced"})
        with wiring.keyed(request, scope=scope):
            record = await measure_one(action, "settled")
    assert record == off_records[action]["settled"], "shadow changed the answer"
    assert len(record["service"]) == 1, "the dispatch did not run"
    runs = table(db, "workflow_runs")
    assert [(r["action"], r["state"], r["key"]) for r in runs] == [(action, "COMPLETE", digest)], (
        f"shadow ran {action} and wrote no run for it: {runs}")


async def test_an_invalid_key_in_shadow_is_not_refused(shadow_db, off_records):
    from runtime.durable import wiring

    action = STATE_MODIFYING[0]
    with installed(shadow_engine(shadow_db)):
        for bad in ("", " padded ", "x" * 256, "café"):
            request = SimpleNamespace(headers={"Idempotency-Key": bad})
            with wiring.keyed(request, scope="operator|" + WALLET):
                record = await measure_one(action, "settled")
            assert record == off_records[action]["settled"], (
                f"shadow answered an invalid key {bad!r} differently from off")
    assert table(shadow_db, "idempotency_keys") == []


async def test_a_shadow_engine_whose_every_write_fails_changes_no_answer_and_no_effect(
        shadow_db, off_records, monkeypatch):
    from runtime.durable import journal, wiring

    db = shadow_db
    failed: list[bool] = []

    def locked(db_, work, *, wait):
        failed.append(wait)
        raise sqlite3.OperationalError("database is locked")
    monkeypatch.setattr(journal, "transaction", locked)

    with installed(shadow_engine(db)):
        for action in STATE_MODIFYING:
            for case in CASE_NAMES:
                record = await measure_one(action, case)
                assert record == off_records[action][case], (
                    f"a failing shadow write changed {action}/{case}")
            request = SimpleNamespace(headers={"Idempotency-Key": f"k-{action}"})
            for _ in range(2):
                with wiring.keyed(request, scope="operator|" + WALLET):
                    record = await measure_one(action, "settled")
                assert record == off_records[action]["settled"], (
                    f"a failing shadow write changed a keyed {action}")
    assert failed and not any(failed), "a shadow write waited"
    for name in DURABLE_TABLES:
        assert table(db, name) == [], f"{name} has rows although every write failed"


# ── SHADOW: the twin tools ──────────────────────────────────────────────────

def _tool_dispatcher(handler):
    from runtime.tools.dispatcher import ToolDispatcher
    d = ToolDispatcher.__new__(ToolDispatcher)
    d._schemas = []
    d._tools = {"defi": handler}
    return d


def _twin_handler(calls: list, behaviour: str):
    async def handler(**kwargs):
        calls.append(dict(kwargs))
        if behaviour == "raises":
            raise StandInFailure("stand-in twin failed")
        if behaviour == "hangs":
            await asyncio.Event().wait()
        return {"status": "success", "tx_hash": "0x" + "66" * 32, "settled": True}
    return handler


TWIN_CASES = {
    # (arguments, behaviour) -> (run action or None, run state, the step after "call")
    "signs": ({"action": "supply", "asset": "USDC", "amount": 1}, "returns"),
    "undeclared": ({"action": "sweep_everything", "amount": 1}, "returns"),
    "raises": ({"action": "borrow", "asset": "USDC", "amount": 1}, "raises"),
    "times_out": ({"action": "repay", "asset": "USDC", "amount": 1}, "hangs"),
    "read": ({"action": "get_rates", "asset": "USDC"}, "returns"),
}


async def _twin_outcome(case: str) -> tuple[Any, list]:
    arguments, behaviour = TWIN_CASES[case]
    calls: list = []
    d = _tool_dispatcher(_twin_handler(calls, behaviour))
    outcome = await d.dispatch("defi", dict(arguments), agent_name="neo",
                               caller_identity=WALLET, caller_source="session")
    return outcome, calls


@pytest.mark.parametrize("case", list(TWIN_CASES))
async def test_a_twin_signing_call_in_shadow_is_journaled_and_answers_as_off(
        case, shadow_db, monkeypatch):
    from runtime.durable import journal
    from runtime.protocols.outcome_truth import report_of
    from runtime.security.action_map import canonical_action

    monkeypatch.setattr("runtime.tools.dispatcher.TOOL_TIMEOUT", 0.05)
    off, off_calls = await _twin_outcome(case)
    with installed(shadow_engine(shadow_db)):
        shadow, shadow_calls = await _twin_outcome(case)
    assert shadow == off and shadow.model_text == off.model_text, (
        f"shadow changed the twin outcome for {case}: {shadow!r} vs {off!r}")
    assert len(shadow_calls) == len(off_calls) == 1, (
        f"{case}: the handler ran {len(shadow_calls)} time(s) in shadow, {len(off_calls)} off")

    arguments, behaviour = TWIN_CASES[case]
    runs = table(shadow_db, "workflow_runs")
    if not canonical_action("defi", arguments)[1]:
        assert runs == [], f"a twin read was journaled: {runs}"
        return
    assert len(runs) == 1, f"{case}: {len(runs)} runs for one signing call"
    run = runs[0]
    verb = arguments["action"]
    assert run["action"] == ("defi.undeclared" if case == "undeclared" else f"defi.{verb}")
    assert run["service"] == "defi" and run["actor_hash"] == journal.actor_hash(WALLET)
    assert run["params_digest"] == journal.digest(arguments)
    steps = [(s["name"], s["state"]) for s in journal.get_steps(shadow_db, run["run_id"])]
    expected = {
        "returns": ("COMPLETE", ("return", str(report_of(
            {"status": "success", "tx_hash": "0x" + "66" * 32, "settled": True})))),
        "raises": ("FAIL", ("raise", "raised")),
        "hangs": ("FAIL", ("unknown_effect", "timed_out")),
    }[behaviour]
    assert run["state"] == expected[0], f"{case}: run {run['state']}, expected {expected[0]}"
    assert steps == [("start", "opened"), ("call", "began"), expected[1]], f"{case}: {steps}"
    _no_raw_address(shadow_db)


async def test_a_twin_call_in_shadow_with_every_write_failing_answers_as_off(
        shadow_db, monkeypatch):
    from runtime.durable import journal

    off, off_calls = await _twin_outcome("signs")

    def locked(db_, work, *, wait):
        raise sqlite3.OperationalError("database is locked")
    monkeypatch.setattr(journal, "transaction", locked)
    with installed(shadow_engine(shadow_db)):
        shadow, shadow_calls = await _twin_outcome("signs")
    assert shadow == off and len(shadow_calls) == len(off_calls) == 1
    assert table(shadow_db, "workflow_runs") == []
