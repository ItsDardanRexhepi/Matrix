"""Engines Phase 2, exit gate G8: zero duplicate actions over a replay corpus.

THE CORPUS is every state-modifying name the service dispatcher serves
(``STATE_MODIFYING``: ``_STATE_MODIFYING_ACTIONS`` that ``ACTION_MAP`` routes).
For each name, ``KEYS_PER_PHASE`` Idempotency-Keys in each of two phases, each
key with a body of its own carrying a unique ``marker``, so that the corpus
holds at least the 1,000 replayed bodies G8 is judged over (``G8_BODIES``):

* ``sequential`` — the body is POSTed, answered, then POSTed again;
* ``concurrent`` — the body is POSTed twice at once (``asyncio.gather``), and
  the service holds the call that reaches it open until either the other
  request has been answered or it too has reached the service. So the second
  request is always in flight while the first is inside its call — the race a
  client retrying on a timeout makes — and never merely after it.

Everything runs through the real gateway: ``GatewayServer`` under aiohttp's
test client with an operator key (``Authorization: Bearer``), ``POST
/bridge/v1/action``, the real ``ServiceDispatcher``, the real durable engine
and its outbox loop over the platform database. Stand-ins replace only the
services (each effect is logged with the body's marker), the chain the outbox
hands attestations to, the legacy attestation service, the feed, and the gate
(an allow-all stand-in that counts every call, so a replay is seen to be gated
again). Every service answers settled, so every run has an attestation and a
feed entry to deliver. After the corpus the outbox loop is drained.

WHAT IS COUNTED, per marker: service effects, attestations (handed to the chain
by the outbox, or queued by the legacy path), feed entries; per key: runs;
per run: outbox rows by kind. And every answer's HTTP status and ``code``.

THE RULE (mode on): 0 duplicate actions — effects per marker == 1, attestations
per run <= 1, feed entries per run <= 1, one run per key; a replay is answered
the first answer byte for byte (sequential) or ``idempotency_in_progress``
(concurrent) and runs nothing. THE CONTRAST (shadow): the same corpus runs every
replay again, as mode off does, so each marker acts twice — which is what shows
the corpus reaches the effect path at all.

A body the gateway refuses before the dispatcher (for a reason that has nothing
to do with durability) is recorded in the artefact under ``refused``, never
dropped from the count, and must have made no effect.

THE ARTEFACT, ``tests/baseline/durable_g8_replay.json``: deterministic counts
only (no timings). ``ENGINES_BASELINE=write`` measures and rewrites it; without
it the corpus is measured again and must equal the committed file (all but
``measured``, which says where the file was written).
"""
from __future__ import annotations

import asyncio
import collections
import json
import os
import sys
import tempfile
import time
from pathlib import Path
from types import SimpleNamespace
from typing import Any

import pytest

sys.path.insert(0, "tests")

from test_durable_harness import (  # noqa: E402
    ACTION_MAP, SETTLED, STATE_MODIFYING, WALLET, Attestations, Effects, Services, dispatcher,
    installed, rows,
)
from runtime.durable import journal, keys, outbox, wiring  # noqa: E402
from tests import durable_measured_at  # noqa: E402

ROOT = Path(__file__).resolve().parent.parent
ARTEFACT = ROOT / "tests" / "baseline" / "durable_g8_replay.json"
WRITE = os.environ.get("ENGINES_BASELINE", "").strip().lower() == "write"

OPERATOR_KEY = "g8-operator-key"
PHASES = ("sequential", "concurrent")
#: Keys per name in each phase: enough that the corpus holds at least
#: G8_BODIES bodies over the state-modifying names.
KEYS_PER_PHASE = 3
#: How many replayed bodies the exit gate G8 is judged over, at least.
G8_BODIES = 1_000
#: How long a held call waits for the other request before it is let go anyway
#: (a bound, not a sleep: the release normally comes within a few milliseconds).
HOLD_BOUND_S = 5.0


# ── the stand-ins that know which body each effect belongs to ───────────────

def _params(marker: str) -> dict:
    return {"to": WALLET, "amount": 5, "marker": marker}


def _params_hash(params: dict) -> str:
    """``_attestation_of``'s ``params_hash`` of *params*, as the dispatcher
    computes it (this process's ``hash``; stable within the process)."""
    return str(hash(json.dumps(params, sort_keys=True, default=str)))


class Hold:
    """What ``Services.gates[action]`` awaits: counts the calls that reached
    the service and lets them go together."""

    def __init__(self) -> None:
        self.event = asyncio.Event()
        self.arrived = 0

    async def wait(self) -> None:
        self.arrived += 1
        await self.event.wait()


class World:
    """The effect log and the stand-ins over it, each writing the body's marker."""

    def __init__(self) -> None:
        self.effects = Effects()
        self.services = Services(self.effects)
        self.by_hash: dict[str, str] = {}
        self.gate_calls = 0

    def marker_of_attestation(self, data: dict) -> Any:
        return self.by_hash.get(str((data or {}).get("params_hash")))

    def registry(self):
        """The harness's registry, with the attestation service's own ``attest``
        (an action of the corpus, ``create_attestation``) and the legacy path's
        ``attest(schema_uid=, data=, recipient=)`` told apart by their
        arguments rather than colliding on one name."""
        by_service: dict[str, dict[str, Any]] = {}
        for action, (service, method) in ACTION_MAP.items():
            by_service.setdefault(service, {})[method] = self.services.method_for(action)
        action_attest = by_service.get("attestation", {}).get("attest")
        world = self

        async def attest(**kwargs):
            if "marker" in kwargs and action_attest is not None:
                return await action_attest(**kwargs)
            data = kwargs.get("data", {}) or {}
            world.effects.log.append(("attest", data.get("action"),
                                      world.marker_of_attestation(data)))
            return {"status": "queued"}

        def get(name):
            methods = dict(by_service.get(name, {}))
            if name == "attestation":
                methods["attest"] = attest
            return SimpleNamespace(**methods)
        return SimpleNamespace(get=get)


class MarkedAttestations(Attestations):
    """The chain as the outbox reaches it, logging the body's marker."""

    def __init__(self, world: World) -> None:
        super().__init__(world.effects)
        self.world = world

    async def _submit_batch(self, batch):
        out = []
        for att in batch:
            data = att.get("data", {})
            self.effects.log.append(("attest_sent", data.get("action"),
                                     self.world.marker_of_attestation(data)))
            out.append({**self.answer, "id": att["id"]})
        return out


class MarkedFeed:
    def __init__(self, world: World) -> None:
        self.world = world

    async def ingest(self, **kwargs):
        marker = ((kwargs.get("detail") or {}).get("params") or {}).get("marker")
        self.world.effects.log.append(("feed", kwargs.get("action"), marker))
        return SimpleNamespace(summary=f"performed {kwargs.get('action')}")


# ── one mode over the whole corpus ──────────────────────────────────────────

def _code(status: int, body: Any) -> str:
    code = body.get("code") if isinstance(body, dict) else None
    return f"{status} {code}" if code else str(status)


async def _post(client, action: str, params: dict, key: str, world: World) -> tuple[int, dict]:
    resp = await client.post(
        "/bridge/v1/action", json={"action": action, "params": params, "session_id": "g8"},
        headers={"Authorization": f"Bearer {OPERATOR_KEY}", "Idempotency-Key": key})
    try:
        body = await resp.json()
    except Exception:  # noqa: BLE001 — recorded as what it is, never hidden
        body = {"unparsed": await resp.text()}
    return resp.status, body


async def _concurrent(client, action: str, params: dict, key: str, world: World):
    hold = Hold()
    # Names that route to one (service, method) share one stand-in method, which
    # reads the gate of whichever of them was registered last: hold them all.
    aliases = [a for a in ACTION_MAP if ACTION_MAP[a] == ACTION_MAP[action]]
    for name in aliases:
        world.services.gates[name] = hold
    try:
        tasks = [asyncio.ensure_future(_post(client, action, params, key, world))
                 for _ in range(2)]
        deadline = time.monotonic() + HOLD_BOUND_S
        while not any(t.done() for t in tasks) and hold.arrived < 2 \
                and time.monotonic() < deadline:
            await asyncio.sleep(0.001)
        hold.event.set()
        answers = await asyncio.gather(*tasks)
    finally:
        for name in aliases:
            world.services.gates.pop(name, None)
    return list(answers), hold.arrived


async def _drain(server) -> None:
    """Let the legacy path's fire-and-forget feed tasks run, then tick the loop
    until no row is due and no payload is held."""
    for _ in range(5):
        await asyncio.sleep(0)
    engine = server._durable_engine
    db = server.react_loop.memory.db
    for _ in range(50):
        await engine.loop.tick()
        await asyncio.sleep(0)
        if outbox.counts(db)["due"] == 0 and engine.loop.held_count() == 0:
            return


async def _run_corpus(mode: str, scratch: Path) -> dict:
    """Every body of the corpus through the gateway in *mode*; the raw record."""
    from aiohttp.test_utils import TestClient, TestServer

    import gateway.security_gate as security_gate
    from gateway.server import GatewayServer
    from test_route_sweep import SWEEP_CONFIG

    world = World()

    async def gate(action, parameters=None, context=None, *, operation=None):
        world.gate_calls += 1
        return {"allow": True, "evaluation_id": f"g8-{world.gate_calls}"}

    record: dict[str, Any] = {"answers": [], "held": {}}
    with pytest.MonkeyPatch.context() as mp:
        mp.delenv("MATRIX_DURABLE_MODE", raising=False)
        mp.setattr(security_gate, "gate_action", gate)
        config = {**SWEEP_CONFIG,
                  "gateway": {**SWEEP_CONFIG["gateway"], "api_key": OPERATOR_KEY},
                  "memory_dir": str(scratch), "database": {"path": f"{scratch}/g8.db"},
                  "engines": {"durable": {"mode": mode}}}
        with installed(wiring.current()):
            server = GatewayServer(config)
            async with TestClient(TestServer(server.create_app())) as client:
                assert server._durable_engine is not None \
                    and server._durable_engine.mode == mode, (
                        f"the gateway did not build a {mode} engine from its config")
                d = dispatcher(world.effects, world.services)
                registry = world.registry()
                d._get_registry = lambda: registry
                d._feed_engine = MarkedFeed(world)
                server.service_dispatcher = d
                server._durable_engine.attestations = MarkedAttestations(world)
                for action in STATE_MODIFYING:
                    world.services.answers[action] = dict(SETTLED)
                    for phase, k in ((p, k) for p in PHASES for k in range(KEYS_PER_PHASE)):
                        marker = f"g8|{mode}|{phase}|{action}|{k}"
                        params = _params(marker)
                        world.by_hash[_params_hash(params)] = marker
                        key = f"g8-{phase}-{action}-{k}"
                        if phase == "sequential":
                            answers = [await _post(client, action, params, key, world)
                                       for _ in range(2)]
                        else:
                            answers, arrived = await _concurrent(client, action, params, key,
                                                                 world)
                            record["held"][marker] = arrived
                        record["answers"].append({
                            "action": action, "phase": phase, "marker": marker, "key": key,
                            "params": params, "answers": answers})
                await _drain(server)
                db = server.react_loop.memory.db
                record["runs"] = rows(db, "workflow_runs")
                record["outbox"] = rows(db, "outbox")
                record["keys"] = rows(db, "idempotency_keys")
                record["loop_alive"] = server._durable_engine.loop.alive
    record["effects"] = list(world.effects.log)
    record["gate_calls"] = world.gate_calls
    record["unmapped_hashes"] = sum(1 for e in world.effects.log
                                    if e[0] in ("attest", "attest_sent") and e[2] is None)
    return record


# ── from the raw record to the counts ───────────────────────────────────────

def _count(record: dict) -> tuple[dict, list[dict]]:
    """``(summary, per_body)``: the artefact's figures for one mode, and one
    row per body for the assertions."""
    by_marker = collections.defaultdict(collections.Counter)
    for kind, _action, marker in record["effects"]:
        by_marker[marker][kind] += 1
    runs_by_digest = collections.defaultdict(list)
    for run in record["runs"]:
        runs_by_digest[run["params_digest"]].append(run)
    outbox_by_run = collections.defaultdict(list)
    for row in record["outbox"]:
        outbox_by_run[row["run_id"]].append(row)
    keys_by_run = {k["run_id"]: k for k in record["keys"]}

    per_body = []
    answers = {phase: collections.Counter() for phase in PHASES}
    refused: dict[str, dict[str, list[str]]] = {}
    for body in record["answers"]:
        statuses = [_code(s, b) for s, b in body["answers"]]
        answers[body["phase"]].update(statuses)
        is_refused = not any(s == 200 for s, _b in body["answers"])
        if is_refused:
            refused.setdefault(body["action"], {})[body["phase"]] = statuses
        runs = runs_by_digest.get(journal.digest(body["params"]), [])
        run_rows = {r["run_id"]: outbox_by_run.get(r["run_id"], []) for r in runs}
        ok = [b for s, b in body["answers"] if s == 200]
        per_body.append({
            "action": body["action"], "phase": body["phase"], "marker": body["marker"],
            "client_key": body["key"], "statuses": statuses, "refused": is_refused,
            "effects": dict(by_marker.get(body["marker"], {})),
            "runs": runs, "outbox": run_rows,
            "bound": [keys_by_run[r["run_id"]] for r in runs if r["run_id"] in keys_by_run],
            "data": [b.get("data") for b in ok],
            "held_arrived": record["held"].get(body["marker"]),
        })

    kinds = ("service", "attest", "attest_sent", "feed")
    totals = {k: sum(c[k] for c in by_marker.values()) for k in kinds}
    per_marker_max = {k: max((row["effects"].get(k, 0) for row in per_body), default=0)
                      for k in kinds}
    per_run_max = {kind: max((sum(1 for r in rows_ if r["kind"] == kind)
                              for row in per_body for rows_ in row["outbox"].values()),
                             default=0) for kind in outbox.KINDS}
    # Attestations and feed entries per run, from the effects: a body's effects
    # over the runs recorded for it, rounded up (a body with no run counts as one).
    per_run_effects_max = {
        k: max((-(-row["effects"].get(k, 0) // max(1, len(row["runs"]))) for row in per_body),
               default=0) for k in ("attest", "attest_sent", "feed")}
    summary = {
        "posts": sum(len(b["answers"]) for b in record["answers"]),
        "bodies": len(record["answers"]),
        "gate_calls": record["gate_calls"],
        "answers": {phase: dict(sorted(c.items())) for phase, c in answers.items()},
        "effects": totals,
        "per_marker_max": per_marker_max,
        "markers_acting_more_than_once": sum(1 for row in per_body
                                             if row["effects"].get("service", 0) > 1),
        "duplicate_actions": sum(max(0, row["effects"].get("service", 0) - 1)
                                 for row in per_body),
        "runs": len(record["runs"]),
        "runs_by_state": dict(sorted(collections.Counter(
            r["state"] for r in record["runs"]).items())),
        "per_key_max_runs": max((len(row["runs"]) for row in per_body), default=0),
        "outbox_per_run_max": per_run_max,
        "attestations_per_run_max": max(per_run_effects_max["attest"],
                                        per_run_effects_max["attest_sent"]),
        "feed_per_run_max": per_run_effects_max["feed"],
        "outbox": {kind: dict(sorted(collections.Counter(
            "handed_off" if r["done_at"] is not None else
            "due" if r["next_at"] is not None else "given_up"
            for r in record["outbox"] if r["kind"] == kind).items()))
            for kind in outbox.KINDS},
        "keys_bound": len(record["keys"]),
        "refused": refused,
    }
    return summary, per_body


_CACHE: dict[str, tuple[dict, list[dict], dict]] = {}


def _measured(mode: str) -> tuple[dict, list[dict], dict]:
    """The corpus in *mode*, measured once per session: ``(summary, per_body,
    raw)``. Its own event loop, its own scratch directory."""
    if mode not in _CACHE:
        with tempfile.TemporaryDirectory(prefix="g8-") as scratch:
            raw = asyncio.run(_run_corpus(mode, Path(scratch)))
        summary, per_body = _count(raw)
        if mode == "on":
            # Only a replay that ran nothing can repeat the first answer byte for
            # byte; in shadow the replay runs again and its envelope carries its
            # own elapsed_ms, so the figure is neither meaningful nor stable there.
            summary["replays_byte_identical"] = sum(
                1 for row in per_body if len(row["data"]) == 2
                and isinstance(row["data"][0], str) and row["data"][0] == row["data"][1])
        _CACHE[mode] = (summary, per_body, raw)
    return _CACHE[mode]


def _artefact() -> dict:
    on, _p, _r = _measured("on")
    shadow, _p, _r = _measured("shadow")
    return {
        "gate": "G8",
        "rule": ("engines.durable.mode = on: 0 duplicate actions over the corpus — service "
                 "effects per marker == 1, attestations per run <= 1, feed entries per run <= 1, "
                 "one run per Idempotency-Key, for every key sent twice in sequence and every "
                 "key sent twice concurrently; a body the gateway refused has 0 effects. Shadow "
                 "is the contrast: a replay runs again there, as with the mode off."),
        "instrument": ("POST /bridge/v1/action through GatewayServer under aiohttp's test "
                       "client with the operator key, the real ServiceDispatcher, durable engine "
                       "and outbox loop over a scratch SQLite database; stand-in services that "
                       "log each effect with the body's marker and answer settled, stand-ins for "
                       "the chain (the outbox's attestation submission), the legacy attestation "
                       "service and the feed, and an allow-all gate that counts its calls. The "
                       "outbox loop is drained after the corpus. Counts only: no timings."),
        "scope": ("every name in _STATE_MODIFYING_ACTIONS that ACTION_MAP routes; per name "
                  f"{KEYS_PER_PHASE} Idempotency-Keys in each of two phases, with a body each: "
                  "'sequential' (POST, answer, POST again) and 'concurrent' (two POSTs "
                  "gathered, the call that reaches the service held open until the other "
                  "request is answered or also reaches it). Twin tools are not in this corpus."),
        "measured": durable_measured_at.measured_at(),
        "corpus": {"actions": len(STATE_MODIFYING),
                   "keys_per_action": len(PHASES) * KEYS_PER_PHASE,
                   "posts_per_key": 2, "service_answer": "settled",
                   "names": list(STATE_MODIFYING)},
        "on": on,
        "shadow": shadow,
    }


# ── the gate ────────────────────────────────────────────────────────────────

def test_mode_on_acts_at_most_once_per_key_over_the_whole_corpus():
    summary, per_body, raw = _measured("on")
    assert raw["loop_alive"], "the outbox loop was not running when the corpus ended"
    assert raw["unmapped_hashes"] == 0, (
        "an attestation could not be traced to the body it attests (params_hash unknown)")
    assert summary["bodies"] == len(STATE_MODIFYING) * len(PHASES) * KEYS_PER_PHASE
    assert raw["gate_calls"] == summary["posts"], (
        f"the gate was asked {raw['gate_calls']} times for {summary['posts']} posts: "
        "a replay skipped the gate")
    problems = []
    for row in per_body:
        e, where = row["effects"], f"{row['action']} ({row['phase']})"
        if row["refused"]:
            continue
        if e.get("service", 0) != 1:
            problems.append(f"{where}: acted {e.get('service', 0)} times, not once")
        if e.get("attest_sent", 0) > 1 or e.get("feed", 0) > 1:
            problems.append(f"{where}: {e.get('attest_sent', 0)} attestation(s), "
                            f"{e.get('feed', 0)} feed entr(y/ies) for one body")
        if e.get("attest_sent", 0) != 1 or e.get("feed", 0) != 1:
            problems.append(f"{where}: a settled run's records were not delivered once each: {e}")
        if e.get("attest", 0):
            problems.append(f"{where}: the legacy attestation path ran in mode on")
        if len(row["runs"]) != 1:
            problems.append(f"{where}: {len(row['runs'])} runs for one key")
            continue
        (run,) = row["runs"]
        if run["state"] != journal.COMPLETE:
            problems.append(f"{where}: its run ended {run['state']}, not COMPLETE")
        expected_key = keys.scoped(wiring.BRIDGE_ACTION, "operator|", row["client_key"])
        if run["key"] != expected_key:
            problems.append(f"{where}: the run is not bound to the request's scoped key")
        (rows_,) = row["outbox"].values()
        kinds = collections.Counter(r["kind"] for r in rows_)
        if kinds != collections.Counter({"attest": 1, "feed": 1}):
            problems.append(f"{where}: outbox rows by kind {dict(kinds)}, not one of each")
        if any(r["done_at"] is None for r in rows_):
            problems.append(f"{where}: an outbox row was not handed off after the drain: {rows_}")
        if len(row["bound"]) != 1:
            problems.append(f"{where}: {len(row['bound'])} key rows bound to its run")
        if row["phase"] == "sequential":
            if row["statuses"] != ["200", "200"]:
                problems.append(f"{where}: answers {row['statuses']}, not two 200s")
            elif not (len(row["data"]) == 2 and row["data"][0] == row["data"][1]):
                problems.append(f"{where}: the replay was not the first answer byte for byte")
            elif row["bound"] and row["bound"][0]["response_digest"] != \
                    journal.text_digest(row["data"][0]):
                problems.append(f"{where}: the key's digest is not that of the answer given")
        else:
            if sorted(row["statuses"]) != ["200", "422 idempotency_in_progress"]:
                problems.append(f"{where}: concurrent answers {row['statuses']}, not one 200 "
                                "and one idempotency_in_progress")
            if row["held_arrived"] != 1:
                problems.append(f"{where}: {row['held_arrived']} calls reached the held service")
    assert not problems, (f"{len(problems)} duplicate-action or lifecycle defect(s) in mode on:\n"
                          + "\n".join(problems[:40]))
    assert summary["duplicate_actions"] == 0 and summary["per_key_max_runs"] <= 1
    assert summary["attestations_per_run_max"] <= 1 and summary["feed_per_run_max"] <= 1
    assert summary["outbox_per_run_max"] == {"attest": 1, "feed": 1}, summary


def test_shadow_runs_every_replay_again_which_is_the_contrast():
    """Shadow owns nothing: the replay runs, is attested and published again,
    and gets a run of its own — the duplicates mode on removes."""
    summary, per_body, raw = _measured("shadow")
    assert raw["unmapped_hashes"] == 0
    problems = []
    for row in per_body:
        e, where = row["effects"], f"{row['action']} ({row['phase']})"
        if row["refused"]:
            continue
        if e.get("service", 0) != 2:
            problems.append(f"{where}: acted {e.get('service', 0)} times in shadow, not twice")
        if e.get("attest", 0) != 2 or e.get("feed", 0) != 2 or e.get("attest_sent", 0):
            problems.append(f"{where}: shadow's legacy records are not the mode-off ones: {e}")
        if row["statuses"] != ["200", "200"]:
            problems.append(f"{where}: shadow changed an answer: {row['statuses']}")
        if len(row["runs"]) != 2 or {r["state"] for r in row["runs"]} != {journal.COMPLETE}:
            problems.append(f"{where}: runs {[r['state'] for r in row['runs']]}")
        for rows_ in row["outbox"].values():
            if sorted(r["kind"] for r in rows_) != ["attest", "feed"] \
                    or any(r["done_at"] is None for r in rows_):
                problems.append(f"{where}: shadow outbox rows are not one handed-off row per "
                                f"kind per run: {rows_}")
        if row["phase"] == "concurrent" and row["held_arrived"] != 2:
            problems.append(f"{where}: {row['held_arrived']} calls reached the held service, "
                            "not both")
    assert not problems, (f"{len(problems)} shadow contrast defect(s):\n"
                          + "\n".join(problems[:40]))
    assert summary["attestations_per_run_max"] <= 1 and summary["feed_per_run_max"] <= 1


@pytest.mark.parametrize("mode", ["on", "shadow"])
def test_a_body_the_gateway_refused_made_no_effect(mode):
    summary, per_body, _raw = _measured(mode)
    for row in per_body:
        if row["refused"]:
            assert row["effects"] == {} and row["runs"] == [], (
                f"{row['action']} ({row['phase']}) was refused ({row['statuses']}) "
                f"and still acted: {row['effects']}, runs {row['runs']}")
    refused = {(a, p) for a, phases in summary["refused"].items() for p in phases}
    assert refused == {(r["action"], r["phase"]) for r in per_body if r["refused"]}


def test_g8_artefact():
    measured = _artefact()
    if WRITE:
        ARTEFACT.parent.mkdir(parents=True, exist_ok=True)
        ARTEFACT.write_text(json.dumps(measured, indent=1, sort_keys=True) + "\n",
                            encoding="utf-8")
    assert ARTEFACT.is_file(), f"{ARTEFACT} missing — run with ENGINES_BASELINE=write"
    committed = json.loads(ARTEFACT.read_text(encoding="utf-8"))
    durable_measured_at.check(committed.pop("measured", None), ARTEFACT.name)
    measured.pop("measured")
    assert committed == json.loads(json.dumps(measured)), (
        "durable_g8_replay.json no longer matches what the corpus does. If the change is "
        "intended, rewrite it with ENGINES_BASELINE=write and say why in the commit.")
    assert committed["on"]["duplicate_actions"] == 0, "the committed G8 artefact records duplicates"
    assert committed["corpus"]["posts_per_key"] == 2 and committed["on"]["bodies"] >= G8_BODIES, (
        f"G8 is judged over at least {G8_BODIES:,} replayed bodies; the artefact holds "
        f"{committed['on']['bodies']:,}")
