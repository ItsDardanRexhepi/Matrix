"""Shared pieces of the durable-execution tests (engines Phase 2).

Not a test module (no ``test_`` prefix): the ``test_durable_*`` files import it
with ``sys.path.insert(0, "tests")``, as the suite does for ``test_route_sweep``.
"""

from __future__ import annotations

import json
import shutil
import sqlite3
from pathlib import Path
from types import SimpleNamespace
from typing import Any, Callable

from runtime.blockchain.services.service_dispatcher import (
    ACTION_MAP, ServiceDispatcher, _STATE_MODIFYING_ACTIONS,
)
from runtime.db.database import Database
from runtime.durable import outbox as durable_outbox
from runtime.durable.wiring import DurableEngine

WALLET = "0x" + "12" * 20
OTHER_WALLET = "0x" + "34" * 20

#: The state-modifying action names, sorted — the canary's second stage.
STATE_ACTIONS: list[str] = sorted(_STATE_MODIFYING_ACTIONS)

SETTLED = {"status": "success", "settled": True, "tx_hash": "0x" + "ab" * 32}
BROADCAST = {"status": "submitted", "tx_hash": "0x" + "cd" * 32}
REFUSED = {"status": "not_deployed", "reason": "no contract"}


class Clock:
    """A clock a test moves by hand."""

    def __init__(self, now: float = 1_800_000_000.0) -> None:
        self.now = now

    def __call__(self) -> float:
        return self.now

    def advance(self, seconds: float) -> None:
        self.now += seconds


class World:
    """What happened outside the process: every effect, in order. It outlives a
    'crash' because it is not the process's state."""

    def __init__(self) -> None:
        self.effects: list[tuple] = []
        #: False while a "killed" process runs on: what it does after its
        #: death never happened.
        self.alive = True

    def record(self, *effect) -> None:
        if self.alive:
            self.effects.append(tuple(effect))

    def count(self, kind: str, key: Any = None) -> int:
        return sum(1 for e in self.effects if e[0] == kind and (key is None or e[1] == key))


def database(path: Path | str) -> Database:
    return Database({"database": {"path": str(path)}})


def snapshot(db_path: Path | str, dest: Path | str) -> Path:
    """The file as a process killed NOW would leave it: what is committed, read
    through a connection of its own, never the writer's view."""
    src = sqlite3.connect(str(db_path))
    try:
        target = sqlite3.connect(str(dest))
        try:
            src.backup(target)
        finally:
            target.close()
    finally:
        src.close()
    return Path(dest)


def copy_file(src: Path | str, dest: Path | str) -> Path:
    shutil.copyfile(str(src), str(dest))
    return Path(dest)


def projection(db: Database) -> dict:
    """Everything recovery decides, without the instants it decided it at."""
    q = db.fetchall_sync
    return {
        "runs": [tuple(r) for r in q(
            "SELECT run_id, key, action, service, actor_hash, params_digest, state, "
            "decision_ref, terminal_at IS NULL FROM workflow_runs ORDER BY run_id")],
        "steps": [tuple(r) for r in q(
            "SELECT run_id, seq, kind, payload_digest, tx_hash, state FROM workflow_steps "
            "ORDER BY run_id, seq")],
        "outbox": [tuple(r) for r in q(
            "SELECT run_id, kind, payload, payload_digest, state, attempts FROM outbox "
            "ORDER BY run_id, kind")],
        "keys": [tuple(r) for r in q(
            "SELECT key, run_id, request_digest, status, response IS NULL, response_digest "
            "FROM idempotency_keys ORDER BY key")],
    }


class FakeEAS:
    """The attestation client the batch processor submits through."""

    def __init__(self, world: World, answer: dict | Callable[[dict], Any] | None = None,
                 on_call: Callable[[dict], Any] | None = None,
                 after_call: Callable[[dict], Any] | None = None) -> None:
        self.world = world
        self.answer = answer if answer is not None else {"status": "attested",
                                                          "attestation_tx": "0xfeed"}
        self.on_call = on_call
        self.after_call = after_call

    async def attest(self, **kwargs) -> dict:
        if self.on_call is not None:
            await _maybe_await(self.on_call(kwargs))
        details = kwargs.get("details") or {}
        self.world.record("attest", details.get("action"), details.get("actor"))
        if self.after_call is not None:
            await _maybe_await(self.after_call(kwargs))
        answer = self.answer(kwargs) if callable(self.answer) else self.answer
        return dict(answer)


async def _maybe_await(value):
    if hasattr(value, "__await__"):
        await value


class FeedSpy:
    """A feed engine over the scratch database that counts what it stores."""

    def __init__(self, db: Database, world: World) -> None:
        from runtime.social.feed_engine import SocialFeedEngine
        self._engine = SocialFeedEngine(db)
        self.world = world
        self.before_insert: Callable[[], Any] | None = None
        self.after_insert: Callable[[], Any] | None = None
        self.calls = 0

    async def ingest(self, **kwargs):
        self.calls += 1
        if self.before_insert is not None:
            await _maybe_await(self.before_insert())
        event = await self._engine.ingest(**kwargs)
        if self.after_insert is not None:
            await _maybe_await(self.after_insert())
        return event


def feed_rows(db: Database) -> list[dict]:
    try:
        return [dict(r) for r in db.fetchall_sync("SELECT * FROM social_feed_events")]
    except sqlite3.OperationalError:
        return []


def engine(db: Database, *, mode: str = "on", canary: str = "state_modifying",
           clock: Callable[[], float] | None = None, world: World | None = None,
           eas: Any = None, feed: Any = None, monkeypatch=None) -> DurableEngine:
    """An engine over *db* whose attestations go to *eas* (through the real batch
    processor) and whose feed entries go to *feed*. Its loop is NOT started:
    tests tick it by hand."""
    from runtime.blockchain.services.attestation import batch_processor as bp

    world = world or World()
    if eas is None:
        eas = FakeEAS(world)
    if monkeypatch is not None:
        monkeypatch.setattr(bp, "_eas_client_for", lambda _cfg: eas, raising=False)
    deliverers = {"attest": durable_outbox.attestation_deliverer(bp.BatchProcessor({}))}
    if feed is not None:
        deliverers["feed"] = durable_outbox.feed_deliverer(feed, db)
    kwargs = {"clock": clock} if clock is not None else {}
    return DurableEngine(db, mode=mode, canary=canary, deliverers=deliverers, **kwargs)


def stub_dispatcher(world: World, result: dict | Callable[[str, dict], Any] = None, *,
                    feed: Any = None, attested: list | None = None,
                    during: Callable[[str, dict], Any] | None = None,
                    get_hook: Callable[[str], Any] | None = None) -> ServiceDispatcher:
    """A ServiceDispatcher whose every service method records one effect in
    *world* and answers *result*; the legacy attestation path records into
    *attested* (the in-memory batch queue it would hand it to)."""
    answer = result if result is not None else SETTLED
    d = ServiceDispatcher({})
    attested = attested if attested is not None else []

    class _Service:
        def __init__(self, name: str) -> None:
            self.name = name

        def __getattr__(self, method):
            async def call(**kwargs):
                if during is not None:
                    await _maybe_await(during("before", kwargs))
                world.record("service", method, kwargs.get("marker"))
                if during is not None:
                    await _maybe_await(during("after", kwargs))
                value = answer(method, kwargs) if callable(answer) else answer
                return dict(value)
            return call

    class _Attestation(_Service):
        """The attestation service: the dispatcher's own record of an action it
        completed arrives as attest(schema_uid=, data=, recipient=); an action
        this service serves arrives like any other service call."""

        async def attest(self, **kwargs):
            if "schema_uid" in kwargs and isinstance(kwargs.get("data"), dict):
                attested.append(kwargs)
                world.record("legacy_attest", kwargs["data"]["action"], kwargs["data"]["actor"])
                return {"status": "queued"}
            return await _Service.__getattr__(self, "attest")(**kwargs)

    services: dict[str, Any] = {}

    def get(name):
        if get_hook is not None:
            get_hook(name)
        if name == "attestation":
            return services.setdefault(name, _Attestation(name))
        return services.setdefault(name, _Service(name))

    d._get_registry = lambda: SimpleNamespace(get=get)
    if feed is not None:
        d._feed_engine = feed
    return d


def gateway(scratch: Path, durable: dict | None = None, **extra):
    """A GatewayServer over *scratch* (a pytest tmp_path), with
    engines.durable set to *durable* when given."""
    from gateway.server import GatewayServer
    from test_route_sweep import SWEEP_CONFIG
    config = {**SWEEP_CONFIG, "memory_dir": str(scratch),
              "database": {"path": f"{scratch}/gateway.db"}, **extra}
    if durable is not None:
        config["engines"] = {"durable": durable}
    return GatewayServer(config)


def measured_where() -> dict:
    """The commit the working tree sat on when an artefact was measured, and
    whether it carried uncommitted changes (the commit that adds the artefact
    is one): ``git log -1 -- <file>`` names the commit that carries it."""
    import subprocess
    root = Path(__file__).resolve().parent.parent

    def git(*args):
        return subprocess.run(["git", *args], cwd=root, capture_output=True, text=True,
                              timeout=60).stdout.strip()
    try:
        head = git("rev-parse", "--short", "HEAD")
        dirty = bool(git("status", "--porcelain", "--untracked-files=no"))
    except (OSError, subprocess.SubprocessError):
        head, dirty = "", None
    return {"on_top_of": head or "unknown", "with_uncommitted_changes": dirty}


def body_for(action: str, marker: Any = 1) -> dict:
    return {"action": action, "params": {"to": WALLET, "amount": 5, "marker": marker},
            "session_id": "durable"}


def service_of(action: str) -> str:
    return ACTION_MAP[action][0]


def loads(text: str) -> Any:
    return json.loads(text)
