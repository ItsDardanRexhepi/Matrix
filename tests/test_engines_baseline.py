"""Engines Phase 1: the baselines, measured before anything moves.

Nothing in the engines program may change a behaviour it has not first
measured. These are the measurements, written to ``tests/baseline/`` and
committed so each later phase diffs against them rather than against memory:

  B1  urf_outcomes.json — what URFReasoningLoop.decide and RexhepiGate.evaluate
      answer for every dispatchable action, in the three action shapes the
      platform builds (ReAct pre_action, the bridge/funnel gate call, the
      Trinity hand-off), with no parameters and with a high-value amount.
  B2  privileged_vocabulary_coverage.json — how many state changes the
      dispatcher and the funnel can hand the security gate: the public
      denominators of tests/test_privileged_vocabulary_coverage.py. How many of
      them the separately installed core classifies is measured where the core
      is installed and is not pinned in this repository (packet OD-7).
  B3  replay_duplicate.json — the same /bridge/v1/action body sent twice. It
      runs twice; a replay under one Idempotency-Key running once is a strict
      expected failure until the phase that honours the key.
  B4  latency.json — p50/p95 of ProtocolStack.pre_action and
      ServiceDispatcher.execute, with the evidence mode off and in shadow.
  B9  collection.json — how many tests this suite collects.
  B10 restart.json — seconds from starting the gateway to /ready answering 200,
      three runs in each evidence mode. Changing the mode is a restart, so this
      is how long a rollback of the mode took on this host — three samples and
      their median, not a bound on how long one can take.

Two modes. By default every test CHECKS: a deterministic baseline (B1, B2's
public half, B3) is recomputed and must equal the committed file, so a change
to the behaviour it measures fails here and has to be written down on purpose;
a host-dependent one (B4, B9, B10) must be present and well formed. With
``ENGINES_BASELINE=write`` each test measures and rewrites its file instead —
B4, B9 and B10 are measured only then, because they take a stopwatch, a
subprocess suite collection and a gateway boot.

WHAT EACH FILE DESCRIBES, AND WHERE IT WAS MEASURED. Every file was measured on
this branch, not at c637715, and says which of its figures describe c637715:

  * ``describes`` — B1, B2 and B3 measure paths this branch leaves as they
    were at c637715 while the evidence mode is off, and the suite recomputes
    them at every commit, so they describe c637715 and every commit since.
    B4's and B10's ``shadow`` cells and B9's ``collected`` need code that
    exists only on this branch, and each file names those figures.
  * ``measured`` (B4, B9, B10: written only on request) — the commit the
    working tree sat on when the stopwatch ran and whether it carried
    uncommitted changes (the change that commits the file is one). The commit
    that carries the file is ``git log -1 -- <file>``.

Also here: the thirteen adversarial outcome fixtures under
``tests/fixtures/adversarial_outcomes/`` are present and well formed. In ten
of them the false signal is a service's return value, and for those the legacy
answer the fixture records is the one the dispatcher gives today; in the other
three (A7, A8, A11) it is an App Store notification, a client's own statement
and an operator's word, none of them a service's return value, so there is no
dispatcher answer to record and their ``legacy`` is null. Their consuming test
belongs to the phase that builds the evidence engine.
"""

from __future__ import annotations

import asyncio
import copy
import json
import os
import platform
import re
import socket
import statistics
import subprocess
import sys
import tempfile
import time
from pathlib import Path
from types import SimpleNamespace

import pytest

sys.path.insert(0, "tests")

from runtime.blockchain.services import service_dispatcher as dispatch  # noqa: E402
from runtime.blockchain.services.service_dispatcher import (  # noqa: E402
    ACTION_MAP, ServiceDispatcher, _record_verdict,
)
from runtime.protocols import urf  # noqa: E402
from runtime.protocols.outcome_truth import report_of  # noqa: E402
from runtime.protocols.rexhepi_gate import RexhepiGate  # noqa: E402
from runtime.protocols.urf import URFReasoningLoop  # noqa: E402
from runtime.security.action_map import canonical_action  # noqa: E402

ROOT = Path(__file__).resolve().parent.parent
BASELINE = ROOT / "tests" / "baseline"
FIXTURES = ROOT / "tests" / "fixtures" / "adversarial_outcomes"
WRITE = os.environ.get("ENGINES_BASELINE", "").strip().lower() == "write"
BASE_COMMIT = "c637715"

#: For a deterministic artefact: recomputed at every commit, it describes the
#: base and every commit since.
UNCHANGED_SINCE_BASE = (f"behaviour at {BASE_COMMIT}: these paths run with the evidence mode "
                        "off, which this branch leaves as it was, and the suite recomputes this "
                        "file at every commit and fails if it differs")

#: B9's figure at the base: `pytest tests/ --collect-only -q -p no:cacheprovider`
#: in a scratch export of c637715 (no contract submodules), Python 3.11.
COLLECTED_AT_BASE = 4468


def _measured_where() -> dict:
    """The commit the working tree sat on when a host-dependent figure was
    taken, and whether it carried uncommitted changes."""
    def git(*args):
        return subprocess.run(["git", *args], cwd=ROOT, capture_output=True, text=True,
                              timeout=60).stdout.strip()
    try:
        head = git("rev-parse", "--short", "HEAD")
        dirty = bool(git("status", "--porcelain", "--untracked-files=no"))
    except (OSError, subprocess.SubprocessError):
        head, dirty = "", None
    return {"on_top_of": head or "unknown", "with_uncommitted_changes": dirty}

WALLET = "0x" + "12" * 20


# ── dataset 1: the three action shapes the platform builds ──────────────────

def react_action(name: str, params: dict) -> dict:
    """runtime/protocols/integration.py ProtocolStack._pre_action, for the
    ``platform_action`` mega-tool: the model's arguments ARE ``parameters``."""
    arguments = {"action": name, "params": params}
    action_type, signs = canonical_action("platform_action", arguments)
    return {"action_type": action_type, "type": action_type, "tool": "platform_action",
            "tool_action": arguments.get("action"), "signs_with_platform_key": bool(signs),
            "parameters": arguments}


def bridge_action(name: str, params: dict) -> dict:
    """gateway/security_gate.py gate_action — the bridge's and the funnel's shape."""
    return {"action_type": name, "type": name, "parameters": params}


def handoff_action(name: str, params: dict) -> dict:
    """runtime/agents/handoff.py — Trinity's escalation to Neo."""
    return {"action_type": name, "parameters": params}


BUILDERS = {"react": react_action, "bridge": bridge_action, "handoff": handoff_action}

#: The contexts each path hands its gate. ReAct: gateway/server.py
#: _chat_user_context (anonymous, and a signed-in wallet). Bridge: the
#: per-request security context (security_gate.bind_request_security). Hand-off:
#: the flags handoff.py adds — it carries no identity (ledger 08 H3).
CONTEXTS: dict[str, dict[str, dict]] = {
    "react": {
        "anonymous": {"session_id": "sess-b1", "memory_scope": "conv:sess-b1", "agent": "neo",
                      "caller_kind": "anonymous", "wallet_address": "", "apple_id": "",
                      "app_attest": None},
        "session": {"session_id": "sess-b1", "memory_scope": WALLET, "agent": "neo",
                    "caller_kind": "session", "wallet_address": WALLET, "apple_id": "",
                    "app_attest": None, "wallet_connected": True},
    },
    "bridge": {
        "anonymous": {"wallet": "", "apple_id": "", "session_id": ""},
        "session": {"wallet": WALLET, "apple_id": "", "session_id": "sess-b1"},
    },
    "handoff": {
        "trinity": {"via_agent_flow": True, "origin_agent": "trinity"},
    },
}

PARAM_VARIANTS = {"none": {}, "high_value": {"amount": 50000}}

OUTCOMES = ("EXECUTE", "PROBE", "ASK", "DEFER", "ABORT")


def cells():
    for builder, contexts in CONTEXTS.items():
        for ctx_name in contexts:
            for variant in PARAM_VARIANTS:
                yield builder, ctx_name, variant


def corpus():
    """Every (cell, action name, action dict, context) in dataset 1."""
    for builder, ctx_name, variant in cells():
        for name in sorted(ACTION_MAP):
            yield ((builder, ctx_name, variant), name,
                   BUILDERS[builder](name, dict(PARAM_VARIANTS[variant])),
                   dict(CONTEXTS[builder][ctx_name]))


@pytest.fixture(autouse=True)
def _no_engine_sinks():
    """Baselines are of the platform as it runs with the mode off."""
    previous = (urf.set_decision_sink(None), dispatch.set_evidence_shadow_sink(None))
    yield
    urf.set_decision_sink(previous[0])
    dispatch.set_evidence_shadow_sink(previous[1])


def _artifact(name: str) -> Path:
    return BASELINE / name


def _write(name: str, payload: dict) -> None:
    BASELINE.mkdir(parents=True, exist_ok=True)
    _artifact(name).write_text(json.dumps(payload, indent=1, sort_keys=True) + "\n",
                               encoding="utf-8")


def _read(name: str) -> dict:
    path = _artifact(name)
    assert path.is_file(), f"{path} missing — run with ENGINES_BASELINE=write"
    return json.loads(path.read_text(encoding="utf-8"))


def _check_or_write(name: str, measured: dict) -> None:
    if WRITE:
        _write(name, measured)
        return
    committed = _read(name)
    assert committed == json.loads(json.dumps(measured)), (
        f"{name} no longer matches what the platform does. If the change is "
        f"intended, rewrite it with ENGINES_BASELINE=write and say why in the commit.")


# ── B1: the URF and gate outcome distribution ───────────────────────────────

async def measure_b1() -> dict:
    per_cell: dict[str, dict] = {}
    for (builder, ctx_name, variant), name, action, ctx in corpus():
        key = f"{builder}/{ctx_name}/{variant}"
        cell = per_cell.setdefault(key, {
            "urf": {o: 0 for o in OUTCOMES}, "gate": {o: 0 for o in OUTCOMES},
            "gate_approved": 0, "urf_not_execute": {}, "gate_not_execute": {}})
        decision = URFReasoningLoop({}).decide(copy.deepcopy(action), copy.deepcopy(ctx))
        # A fresh gate per action: RexhepiGate rate-limits 30 evaluations a
        # minute per instance, and the baseline is of each decision alone.
        gate = await RexhepiGate({}).evaluate(copy.deepcopy(action), copy.deepcopy(ctx))
        for side, outcome in (("urf", decision.outcome.value), ("gate", gate["outcome"])):
            cell[side][outcome] += 1
            if outcome != "EXECUTE":
                cell[f"{side}_not_execute"].setdefault(outcome, []).append(name)
        cell["gate_approved"] += bool(gate["approved"])
    reachable = {side: sorted({o for c in per_cell.values() for o, n in c[side].items() if n})
                 for side in ("urf", "gate")}
    return {
        "baseline": "B1",
        "describes": UNCHANGED_SINCE_BASE,
        "instrument": ("URFReasoningLoop({}).decide and a fresh RexhepiGate({}).evaluate per "
                       "action, over every ACTION_MAP name as the dispatcher holds it after the "
                       "capability catalog is installed, in each builder/context/params cell; "
                       "reads the loop's own outcome, runs no model and no service"),
        "names": len(ACTION_MAP),
        "state_modifying": len(dispatch._STATE_MODIFYING_ACTIONS),
        "cells": per_cell,
        "reachable_outcomes": reachable,
        "urf_on_path": {
            # Which builders' actions reach RexhepiGate today, read from source
            # by test_which_paths_reach_the_urf_gate below.
            "react": True, "bridge": False, "handoff": False,
        },
    }


async def test_b1_urf_outcomes():
    _check_or_write("urf_outcomes.json", await measure_b1())


def test_b1_the_urf_reaches_three_of_its_five_outcomes():
    """Measured, not endorsed (ledger 08 C5): PROBE and DEFER need an
    uncertainty, a feasibility or a clarity signal no live path supplies."""
    reachable = _read("urf_outcomes.json")["reachable_outcomes"]
    assert reachable == {"urf": ["ABORT", "ASK", "EXECUTE"], "gate": ["ABORT", "ASK", "EXECUTE"]}


def test_which_paths_reach_the_urf_gate():
    """Only the ReAct path calls RexhepiGate; the bridge and the hand-off call
    the security core alone. B1 scores their shapes anyway, because that is
    what the URF would say if it were asked."""
    bridge = (ROOT / "gateway" / "bridge.py").read_text(encoding="utf-8")
    handoff = (ROOT / "runtime" / "agents" / "handoff.py").read_text(encoding="utf-8")
    integration = (ROOT / "runtime" / "protocols" / "integration.py").read_text(encoding="utf-8")
    assert "_rexhepi_gate.evaluate(" in integration
    for text in (bridge, handoff):
        assert "RexhepiGate" not in text and "pre_action(" not in text and "URFReasoningLoop" not in text


async def test_the_react_builder_is_the_live_shape(monkeypatch):
    """What ProtocolStack.pre_action actually hands RexhepiGate for a
    platform_action call equals react_action — the B1 corpus is the live one."""
    from runtime.protocols.integration import ProtocolStack
    seen: list = []

    async def recording(self, action, context):
        seen.append(copy.deepcopy(action))
        return {"approved": True, "outcome": "EXECUTE"}

    monkeypatch.setattr(RexhepiGate, "evaluate", recording)
    stack = ProtocolStack({}, "neo")
    params = {"to": WALLET, "amount": 5}
    await stack.pre_action("platform_action", {"action": "transfer_stablecoin", "params": params},
                           dict(CONTEXTS["react"]["session"]))
    assert seen and seen[0] == react_action("transfer_stablecoin", params)


# ── B2: privileged-vocabulary coverage (counts) ─────────────────────────────

def test_b2_privileged_vocabulary_coverage():
    from test_privileged_vocabulary_coverage import MEASURED, NUMERATORS, measure
    payload = {
        "baseline": "B2",
        "describes": (f"the dispatcher's and the funnel's tables at {BASE_COMMIT}, which this "
                      "branch does not change"),
        "instrument": ("tests/test_privileged_vocabulary_coverage.py measure(): AST over the "
                       "dispatcher and funnel literals"),
        "counts": measure(),
        "numerators": ("how many of these reach the security gate under a label the separately "
                       "installed core classifies (" + ", ".join(sorted(NUMERATORS)) + ") are "
                       "counts of the core's answers: measured where the core is installed, and "
                       "not written into this repository (packet OD-7)"),
    }
    if WRITE:
        _write("privileged_vocabulary_coverage.json", payload)
        return
    committed = _read("privileged_vocabulary_coverage.json")
    assert committed == payload
    assert committed["counts"] == MEASURED
    assert not set(NUMERATORS) & set(committed["counts"]), "a numerator was written here"


# ── B3: a replayed bridge action ────────────────────────────────────────────

async def measure_b3(scratch: Path, headers: dict | None = None) -> dict:
    from aiohttp.test_utils import TestClient, TestServer
    from gateway.server import GatewayServer
    from test_route_sweep import SWEEP_CONFIG

    action = "transfer_stablecoin"
    service, method_name = ACTION_MAP[action]
    calls: list = []

    async def method(**kwargs):
        calls.append("service")
        return {"status": "success", "tx_hash": "0x" + "22" * 32, "settled": True}

    async def attest(**kwargs):
        calls.append("attest")

    d = ServiceDispatcher({})
    svc, attestation = SimpleNamespace(**{method_name: method}), SimpleNamespace(attest=attest)
    d._get_registry = lambda: SimpleNamespace(get=lambda n: svc if n == service else attestation)

    server = GatewayServer({**SWEEP_CONFIG, "memory_dir": str(scratch),
                            "database": {"path": f"{scratch}/a.db"}})
    body = {"action": action, "params": {"to": WALLET, "amount": 5}, "session_id": "b3"}
    statuses = []
    async with TestClient(TestServer(server.create_app())) as client:
        server.service_dispatcher = d
        for _ in range(2):
            resp = await client.post("/bridge/v1/action", json=body, headers=headers)
            statuses.append(resp.status)
    return {
        "baseline": "B3",
        "describes": UNCHANGED_SINCE_BASE,
        "instrument": ("POST /bridge/v1/action twice with one body through the aiohttp test "
                       "client; the shared ServiceDispatcher over a stub service counts calls"),
        "posts": 2,
        "statuses": statuses,
        "service_calls": calls.count("service"),
        "attestations": calls.count("attest"),
    }


async def test_b3_a_replayed_body(tmp_path):
    """What the replay does is the golden's to say (it runs twice, and is
    attested twice); a change to it fails here until the file is rewritten."""
    _check_or_write("replay_duplicate.json", await measure_b3(tmp_path))


@pytest.mark.xfail(strict=True, raises=AssertionError, reason=(
    "Phase 2 (Durable Execution): gateway/bridge.py execute_action reads no Idempotency-Key; "
    "the phase records the outcome under the key and returns it on a replay"))
async def test_a_replay_under_one_idempotency_key_runs_once(tmp_path):
    measured = await measure_b3(tmp_path, headers={"Idempotency-Key": "b3-replay"})
    if measured["statuses"][0] != 200 or measured["service_calls"] < 1:
        # Not the property: the first request did not run at all.
        raise RuntimeError(f"the first request did not execute: {measured}")
    assert measured["service_calls"] == 1, (
        f"one request under one key ran {measured['service_calls']} times")


# ── B4: latency ─────────────────────────────────────────────────────────────

def _percentiles(samples: list[float]) -> dict:
    ordered = sorted(samples)
    return {"n": len(ordered),
            "p50_us": round(statistics.median(ordered) * 1e6, 1),
            "p95_us": round(ordered[int(0.95 * (len(ordered) - 1))] * 1e6, 1)}


async def measure_b4(n: int = 5000) -> dict:
    from runtime.db.database import Database
    from runtime.protocols.integration import ProtocolStack

    names = sorted(ACTION_MAP)
    ctx = CONTEXTS["react"]["session"]

    async def ok(**kwargs):
        return {"status": "success"}

    class _Service:
        """Every method of every service returns at once."""
        def __getattr__(self, name):
            return ok

    registry = SimpleNamespace(get=lambda svc: _Service())
    # One stack, as the gateway keeps one per (agent, scope); its gate's
    # per-instance rate limit is widened so it never refuses mid-measurement.
    stack_config = {"rexhepi": {"rate_limit_window_seconds": 1e-9,
                                "rate_limit_max_actions": 10 ** 9}}
    out: dict[str, dict] = {"pre_action": {}, "execute": {}}
    with tempfile.TemporaryDirectory() as scratch:
        db = Database({"database": {"path": f"{scratch}/b4.db"}})
        for mode in ("off", "shadow"):
            urf.set_decision_sink(urf.durable_decision_sink(db) if mode == "shadow" else None)
            dispatch.set_evidence_shadow_sink(
                dispatch.evidence_shadow_sink(db) if mode == "shadow" else None)
            samples = []
            stack = ProtocolStack(stack_config, "neo")
            for i in range(n):
                name = names[i % len(names)]
                t0 = time.perf_counter()
                await stack.pre_action("platform_action", {"action": name, "params": {}}, dict(ctx))
                samples.append(time.perf_counter() - t0)
            out["pre_action"][mode] = _percentiles(samples)
            d = ServiceDispatcher({})
            d._get_registry = lambda: registry
            samples = []
            for i in range(n):
                name = names[i % len(names)]
                t0 = time.perf_counter()
                await d.execute(name, params={}, caller_identity=WALLET)
                samples.append(time.perf_counter() - t0)
            out["execute"][mode] = _percentiles(samples)
        await db.close()
    return {
        "baseline": "B4",
        "describes": ("off: this branch's code with the evidence mode off — the paths of "
                      f"{BASE_COMMIT} plus one check for an unset sink per decision and per "
                      "dispatch. shadow: this branch's sinks, which do not exist at "
                      f"{BASE_COMMIT}. Each shadow row is one INSERT on the platform "
                      "connection with a zero busy timeout."),
        "measured": _measured_where(),
        "instrument": ("in-process time.perf_counter around ProtocolStack.pre_action "
                       "(platform_action, every ACTION_MAP name in turn, the no-op security "
                       "backend) and ServiceDispatcher.execute (a stub service that returns at "
                       "once: the dispatcher's own cost, no chain, no network), n calls each, "
                       "with the evidence mode off and in shadow over a scratch SQLite file. "
                       "Not the locust scenario against a live gateway: no model provider or "
                       "chain is reachable where this was measured. Host-dependent."),
        "host": {"machine": platform.machine(), "system": platform.system(),
                 "python": platform.python_version()},
        **out,
    }


async def test_b4_latency():
    if WRITE:
        _write("latency.json", await measure_b4())
    b4 = _read("latency.json")
    for op in ("pre_action", "execute"):
        for mode in ("off", "shadow"):
            cell = b4[op][mode]
            assert cell["n"] >= 5000 and 0 < cell["p50_us"] <= cell["p95_us"], (op, mode, cell)


# ── B9: collection count ────────────────────────────────────────────────────

def measure_b9() -> dict:
    proc = subprocess.run(
        [sys.executable, "-m", "pytest", "tests/", "-q", "-p", "no:cacheprovider", "--collect-only"],
        cwd=ROOT, capture_output=True, text=True, timeout=600,
        env={**os.environ, "PYTHONPATH": str(ROOT), "PYTHONDONTWRITEBYTECODE": "1",
             "ENGINES_BASELINE": ""},
    )
    match = re.search(r"(\d+) tests? collected", proc.stdout)
    assert match, proc.stdout[-2000:] + proc.stderr[-2000:]
    return {"baseline": "B9",
            "describes": ("collected: this branch's suite, at the commit that carries this "
                          f"file; collected_at_base: {BASE_COMMIT}'s, a fixed figure measured "
                          "by the same command in a scratch export of that commit"),
            "not_recorded": NOT_RECORDED_IN_B9,
            "measured": _measured_where(),
            "instrument": "pytest tests/ --collect-only, Python " + platform.python_version(),
            "collected": int(match.group(1)),
            "collected_at_base": COLLECTED_AT_BASE}


#: The packet's B9 row covers four repositories; this file covers one.
NOT_RECORDED_IN_B9 = (
    "The B9 row of the plan also lists the collection counts of the Oracle Server, the "
    "security core and the iOS app. Those repositories are private, and their counts are "
    "deliberately not written into this public tree; each is measured where it is checked "
    "out. This file holds The Matrix's count only.")


def test_b9_collection():
    if WRITE:
        _write("collection.json", measure_b9())
    b9 = _read("collection.json")
    assert b9["collected"] > b9["collected_at_base"] == COLLECTED_AT_BASE
    assert b9["not_recorded"] == NOT_RECORDED_IN_B9


# ── B10: restart to ready, per mode ─────────────────────────────────────────

def _free_port() -> int:
    with socket.socket() as s:
        s.bind(("127.0.0.1", 0))
        return s.getsockname()[1]


async def _boot_to_ready(mode: str, provider_url: str) -> dict:
    import aiohttp
    port = _free_port()
    with tempfile.TemporaryDirectory() as scratch:
        config = {
            "gateway": {"host": "127.0.0.1", "port": port},
            "database": {"path": f"{scratch}/b10.db"},
            "backup": {"enabled": False},
            "model": {"provider": "ollama",
                      "providers": {"ollama": {"base_url": provider_url, "model": "stub"}}},
            "engines": {"evidence": {"mode": mode}},
        }
        Path(scratch, "matrix.config.json").write_text(json.dumps(config), encoding="utf-8")
        env = {k: v for k, v in os.environ.items() if not k.startswith("MATRIX_")}
        env.update(PYTHONPATH=str(ROOT), PYTHONDONTWRITEBYTECODE="1", MATRIX_LOG_LEVEL="WARNING")
        log = open(Path(scratch, "gateway.log"), "wb")
        started = time.perf_counter()
        proc = await asyncio.create_subprocess_exec(
            sys.executable, "-m", "gateway.server", cwd=scratch, env=env,
            stdout=asyncio.subprocess.DEVNULL, stderr=log)
        health = ready = None
        try:
            async with aiohttp.ClientSession() as session:
                while time.perf_counter() - started < 60 and ready is None:
                    try:
                        async with session.get(f"http://127.0.0.1:{port}/ready",
                                               timeout=aiohttp.ClientTimeout(total=5)) as r:
                            if health is None:
                                health = time.perf_counter() - started
                            if r.status == 200:
                                ready = time.perf_counter() - started
                    except aiohttp.ClientError:
                        pass
                    if ready is None:
                        await asyncio.sleep(0.05)
        finally:
            proc.terminate()
            await proc.wait()
            log.close()
        assert ready is not None, (mode, Path(scratch, "gateway.log").read_text()[-2000:])
        return {"first_answer_s": round(health, 3), "ready_200_s": round(ready, 3)}


async def measure_b10(runs: int = 3) -> dict:
    from aiohttp import web
    async def tags(request):
        return web.json_response({"models": []})

    app = web.Application()
    app.router.add_get("/api/tags", tags)
    runner = web.AppRunner(app)
    await runner.setup()
    port = _free_port()
    await web.TCPSite(runner, "127.0.0.1", port).start()
    try:
        results = {mode: [await _boot_to_ready(mode, f"http://127.0.0.1:{port}") for _ in range(runs)]
                   for mode in ("off", "shadow")}
    finally:
        await runner.cleanup()
    return {
        "baseline": "B10",
        "describes": ("off: this branch's gateway with the evidence mode off. shadow: the same "
                      "with the two sinks installed, which does not exist at "
                      f"{BASE_COMMIT}."),
        "measured": _measured_where(),
        "instrument": ("wall clock from starting `python -m gateway.server` in a scratch "
                       "directory to GET /ready answering 200, polled every 50 ms; the model "
                       "provider is a local stub that answers its health probe, because /ready "
                       "requires a reachable provider. A mode change is a restart, so each run is "
                       "how long a rollback of engines.evidence.mode took on this host: three "
                       "samples per mode and their median, not a bound."),
        "host": {"machine": platform.machine(), "system": platform.system(),
                 "python": platform.python_version()},
        "runs": results,
        "median_ready_200_s": {m: statistics.median(r["ready_200_s"] for r in v)
                               for m, v in results.items()},
    }


async def test_b10_restart_to_ready():
    if WRITE:
        _write("restart.json", await measure_b10())
    b10 = _read("restart.json")
    for mode in ("off", "shadow"):
        runs = b10["runs"][mode]
        assert len(runs) >= 3 and all(0 < r["first_answer_s"] <= r["ready_200_s"] for r in runs)
        assert b10["median_ready_200_s"][mode] < 60


# ── the adversarial outcome corpus (fixtures only in Phase 1) ───────────────

FIXTURE_KEYS = {"id", "case", "false_signal", "producer", "fact_source", "expected",
                "legacy", "head_behaviour"}


def _fixtures() -> list[dict]:
    return [json.loads(p.read_text(encoding="utf-8")) for p in sorted(FIXTURES.glob("*.json"))]


def test_the_thirteen_adversarial_fixtures_are_present():
    fixtures = _fixtures()
    assert [f["id"] for f in fixtures] == [f"A{i}" for i in range(1, 14)]
    for f in fixtures:
        assert set(f) == FIXTURE_KEYS, (f["id"], set(f) ^ FIXTURE_KEYS)
        assert f["expected"]["verdict"] in {"VERIFIED", "FAILED", "PENDING", "UNKNOWN", "REJECTED"}
        assert f["producer"]["kind"] and f["fact_source"]["kind"]


def test_each_fixture_records_the_legacy_answer_the_dispatcher_gives_today():
    """Where the producer is a service's return value, ``legacy`` is what
    _record_verdict and report_of answer for it at this commit — measured."""
    checked = 0
    for f in _fixtures():
        if f["producer"]["kind"] != "service_result":
            assert f["legacy"] is None, f["id"]
            continue
        payload = f["producer"]["payload"]
        assert f["legacy"] == {"record_verdict": _record_verdict(payload),
                               "report": report_of(payload)}, f["id"]
        checked += 1
    assert checked == 10
