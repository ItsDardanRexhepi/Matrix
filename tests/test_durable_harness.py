"""The harness the durable-execution tests share, and its own checks.

Engines Phase 2 (runtime/durable). Everything here drives the real code — the
platform ``Database`` with its migrations, the real ``ServiceDispatcher``, the
real ``DurableEngine`` and its outbox loop — over stand-ins for the three things
a test must not reach: the services (every one records each effect it makes and
answers what the test chose), the chain (the attestation client counts what it
was handed), and the clock (a ``Clock`` the test moves).

A CRASH is the committed state of the database at the instant of the crash —
``snapshot`` copies it through SQLite's backup API, write-ahead log included —
together with the effects made up to that instant. A RESTART is a fresh
``Database`` and ``DurableEngine`` over that copy, with nothing held in memory:
exactly what a process that died and started again has.
"""
from __future__ import annotations

import asyncio
import contextlib
import json
import sqlite3
import sys
from dataclasses import dataclass, field
from pathlib import Path
from types import SimpleNamespace
from typing import Any

import pytest

sys.path.insert(0, "tests")

from runtime.blockchain.services.service_dispatcher import (  # noqa: E402
    ACTION_MAP, ServiceDispatcher, _STATE_MODIFYING_ACTIONS,
)
from runtime.db.database import Database  # noqa: E402
from runtime.durable import journal, wiring  # noqa: E402
from runtime.durable.wiring import DurableEngine  # noqa: E402

WALLET = "0x" + "ab" * 20
OTHER = "0x" + "cd" * 20
STATE_MODIFYING = sorted(a for a in _STATE_MODIFYING_ACTIONS if a in ACTION_MAP)

SETTLED = {"status": "success", "tx_hash": "0x" + "22" * 32, "settled": True}
BROADCAST = {"status": "submitted", "tx_hash": "0x" + "33" * 32}
REFUSED = {"status": "not_deployed", "error": "contracts are not deployed"}


class Clock:
    """A clock the test moves; starts at a fixed instant so runs repeat."""

    def __init__(self, now: float = 1_800_000_000.0) -> None:
        self.now = now

    def __call__(self) -> float:
        return self.now

    def advance(self, seconds: float) -> None:
        self.now += seconds


class Boom(RuntimeError):
    """What a stand-in service raises when told to."""


@dataclass
class Effects:
    """Every effect the stand-ins made, in order: ``("service", action, marker)``,
    ``("attest", action)``, ``("attest_sent", action)``, ``("feed", action)``."""
    log: list = field(default_factory=list)

    def count(self, kind: str, action: str | None = None, marker: Any = None) -> int:
        return sum(1 for e in self.log if e[0] == kind
                   and (action is None or e[1] == action)
                   and (marker is None or (len(e) > 2 and e[2] == marker)))


class Services:
    """A service registry where every method of every service records its
    effect and answers ``answers[action]`` (default: settled), raises when the
    answer is an exception, and awaits ``gates[action]`` when one is set (so a
    test can hold a call open)."""

    def __init__(self, effects: Effects) -> None:
        self.effects = effects
        self.answers: dict[str, Any] = {}
        self.gates: dict[str, asyncio.Event] = {}
        self.before_effect: Any = None
        self.after_effect: Any = None

    def method_for(self, action: str, sharing: tuple[str, ...] = ()):
        """The stand-in for *action*'s method. Several names can share one
        service method; a gate or an answer set for any of them applies."""
        names = (action, *[a for a in sharing if a != action])

        async def method(**params):
            gate = next((self.gates[a] for a in names if a in self.gates), None)
            if gate is not None:
                await gate.wait()
            if self.before_effect is not None:
                self.before_effect(action, params)
            answer = next((self.answers[a] for a in names if a in self.answers), SETTLED)
            if isinstance(answer, BaseException):
                # A fresh instance each time, so no traceback grows across raises.
                raise type(answer)(*answer.args)
            self.effects.log.append(("service", action, params.get("marker")))
            if self.after_effect is not None:
                self.after_effect(action, params)
            return dict(answer)
        return method

    def registry(self):
        sharing: dict[tuple[str, str], list[str]] = {}
        for action, pair in ACTION_MAP.items():
            sharing.setdefault(pair, []).append(action)
        by_service: dict[str, dict[str, Any]] = {}
        for (service, method), actions in sharing.items():
            by_service.setdefault(service, {})[method] = self.method_for(
                actions[-1], tuple(actions))

        effects = self.effects
        service_attest = by_service.get("attestation", {}).get("attest")

        async def attest(**kwargs):
            # The dispatcher's own record of an action (_attest_action) comes
            # with the record's shape; anything else is the attestation
            # service's own action (create_attestation) and is a service effect.
            data = kwargs.get("data")
            if (set(kwargs) == {"schema_uid", "data", "recipient"} and isinstance(data, dict)
                    and "actor_source" in data):
                effects.log.append(("attest", data.get("action")))
                return {"status": "queued"}
            return await service_attest(**kwargs)

        def get(name):
            if name == "attestation":
                return SimpleNamespace(**{**by_service.get("attestation", {}), "attest": attest})
            return SimpleNamespace(**by_service.get(name, {}))
        return SimpleNamespace(get=get)


class Attestations:
    """The chain, as the batch processor's submission path reaches it."""

    def __init__(self, effects: Effects, answer: dict | None = None) -> None:
        self.effects = effects
        self.answer = answer or {"status": "success", "attestation_uid": "0x" + "44" * 32,
                                 "tx_hash": "0x" + "55" * 32}
        self.answers: list = []

    async def _submit_batch(self, batch):
        out = []
        for att in batch:
            answer = self.answers.pop(0) if self.answers else self.answer
            if isinstance(answer, BaseException):
                raise answer
            self.effects.log.append(("attest_sent", att.get("data", {}).get("action")))
            out.append({**answer, "id": att["id"]})
        return out


class Feed:
    def __init__(self, effects: Effects) -> None:
        self.effects = effects

    async def ingest(self, **kwargs):
        self.effects.log.append(("feed", kwargs.get("action")))
        return SimpleNamespace(summary=f"performed {kwargs.get('action')}")


def open_db(path: Path) -> Database:
    return Database({"database": {"path": str(path)}})


def dispatcher(effects: Effects, services: Services | None = None) -> ServiceDispatcher:
    services = services or Services(effects)
    d = ServiceDispatcher({})
    registry = services.registry()
    d._get_registry = lambda: registry
    d._feed_engine = Feed(effects)
    d._services = services
    return d


def engine(db: Database, mode: str, clock: Clock, effects: Effects, **kw) -> DurableEngine:
    return DurableEngine(db, mode=mode, clock=clock, attestations=Attestations(effects), **kw)


@contextlib.contextmanager
def installed(eng: DurableEngine | None):
    previous = wiring.install(eng)
    try:
        yield eng
    finally:
        wiring.install(previous)


def snapshot(db: Database, dest: Path) -> Path:
    """The committed state of *db*, as a process that died now leaves it."""
    src = sqlite3.connect(str(db.db_path))
    out = sqlite3.connect(str(dest))
    try:
        src.backup(out)
    finally:
        src.close()
        out.close()
    return dest


def rows(db: Database, table: str) -> list[dict]:
    return [dict(r) for r in db.fetchall_sync(f"SELECT * FROM {table}")]


def open_runs(db: Database) -> list[dict]:
    return [dict(r) for r in db.fetchall_sync(
        "SELECT * FROM workflow_runs WHERE state NOT IN ('COMPLETE', 'ABORT', 'FAIL')")]


async def drain(eng: DurableEngine) -> None:
    """Let fire-and-forget tasks run, then one full tick of the loop."""
    await asyncio.sleep(0)
    await asyncio.sleep(0)
    await eng.loop.tick()


def params_for(action: str, marker: Any) -> dict:
    return {"to": WALLET, "amount": 5, "marker": marker}


async def bridge_like(d: ServiceDispatcher, action: str, params: dict, *, key: str | None,
                      identity: str = WALLET, blocked: bool = False,
                      decision: dict | None = None) -> str | None:
    """The sequence POST /bridge/v1/action runs, at the dispatcher: the gate's
    answer (``blocked`` → the 403, and nothing else runs), then the dispatch
    under the request's key. None stands for the 403."""
    if blocked:
        return None
    request = SimpleNamespace(headers={} if key is None else {"Idempotency-Key": key})
    with wiring.keyed(request, scope=lambda: f"operator|{identity.lower()}",
                      decision=decision or {}):
        return await d.execute(action, params=params, caller_identity=identity)


# ── the harness's own checks ────────────────────────────────────────────────

def test_the_stand_in_service_records_one_effect_per_call(tmp_path):
    effects = Effects()
    d = dispatcher(effects)
    answer = asyncio.run(d.execute(STATE_MODIFYING[0], params={"marker": 1}))
    assert json.loads(answer)["status"] == "ok"
    assert effects.count("service", STATE_MODIFYING[0], 1) == 1


def test_a_snapshot_holds_what_was_committed_and_nothing_after(tmp_path):
    db = open_db(tmp_path / "a.db")
    db.execute_sync("INSERT INTO idempotency_keys (key, run_id, response_digest, created_at) "
                    "VALUES ('k', 'r', '', 1)")
    copy = open_db(snapshot(db, tmp_path / "b.db"))
    db.execute_sync("DELETE FROM idempotency_keys")
    assert [r["key"] for r in rows(copy, "idempotency_keys")] == ["k"]
    assert rows(db, "idempotency_keys") == []


@pytest.fixture
def clock() -> Clock:
    return Clock()
