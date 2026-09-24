"""G6 — what durable execution costs in latency (engines Phase 2).

The packet's G6: p50/p95 of ``ProtocolStack.pre_action``, ``ServiceDispatcher.
execute`` and ``POST /bridge/v1/action``, n >= 5,000 each, within +10% p95 of
the Phase 1 baseline, the principal to confirm the budget. The instrument is
B4's (a stub service that answers at once, so the figure is the platform's own
cost, never a chain's or a network's), plus the bridge route through the
aiohttp test client.

A LOADED HOST IS NOISY, SO NOTHING IS COMPARED ACROSS TIME. ``measure_g6``
interleaves the durable modes in small blocks inside one process, rotating
their order, so off, shadow and on meet the same machine. ``build`` runs many
short rounds; each round runs three fresh interpreters back to back, in a
rotating order: main (the Phase 1 tree, where the modes do not exist and every
mode is main's own path), this branch with only off (the work main does), and
this branch with off, shadow and on interleaved.

WHAT IS JUDGED is, per mode and instrument, the MEDIAN OVER THE ROUNDS of that
round's p95 over the same round's main p95 (``p95_ratio_to_main``); every
round's ratios are kept in the artefact (``per_round``), so the median can be
recomputed from it. For shadow and on the same-process ratio to the branch's
own off, measured in the same blocks, is kept beside it. Each cell's p50/p95
and ``pooled_p95_ratio_to_main`` are over the samples pooled across all
rounds; they are kept, and are NOT what is judged: one loaded round moves a
pooled p95, which is why pre_action — code this phase does not touch — can
land well over 1.0 pooled.

``tests/baseline/durable_latency.json`` holds the result. The suite checks it is
well formed, that the judged ratio is the median of the kept rounds, and that
it states — rather than hides — which modes are within the budget.
"""

from __future__ import annotations

import asyncio
import json
import os
import platform
import statistics
import sys
import tempfile
import time
from pathlib import Path
from types import SimpleNamespace

sys.path.insert(0, "tests")

ROOT = Path(__file__).resolve().parent.parent
ARTEFACT = ROOT / "tests" / "baseline" / "durable_latency.json"
BUDGET = 1.10
MODES = ("off", "shadow", "on")
INSTRUMENTS = ("pre_action", "execute", "bridge_action")


def _percentiles(samples: list[float]) -> dict:
    ordered = sorted(samples)
    return {"n": len(ordered),
            "p50_us": round(statistics.median(ordered) * 1e6, 1),
            "p95_us": round(ordered[int(0.95 * (len(ordered) - 1))] * 1e6, 1)}


async def measure_g6(n: int = 5000, blocks: int = 10, raw: bool = False,
                     only: tuple | None = None) -> dict:
    """Per instrument and mode: n samples, taken in *blocks* interleaved blocks.
    On a tree without runtime.durable (main) only "off" exists; *only* narrows
    the modes measured (a process that runs only off is what main runs)."""
    from aiohttp.test_utils import TestClient, TestServer
    from gateway.server import GatewayServer
    from runtime.blockchain.services.service_dispatcher import (
        ACTION_MAP, ServiceDispatcher, _STATE_MODIFYING_ACTIONS,
    )
    from runtime.db.database import Database
    from runtime.protocols.integration import ProtocolStack
    from test_route_sweep import SWEEP_CONFIG
    try:
        from runtime.durable import wiring
        modes = tuple(m for m in MODES if only is None or m in only)
    except ImportError:
        wiring = None
        modes = ("off",)

    names = sorted(ACTION_MAP)
    state_names = sorted(_STATE_MODIFYING_ACTIONS)

    async def ok(**kwargs):
        return {"status": "success", "settled": True}

    class _Service:
        def __getattr__(self, name):
            return ok

    class _Attestation(_Service):
        async def attest(self, **kwargs):
            return {"status": "queued"}

    class _Feed:
        async def ingest(self, **kwargs):
            return None

    registry = SimpleNamespace(get=lambda svc: _Attestation() if svc == "attestation"
                               else _Service())
    ctx = {"caller_kind": "session", "wallet": "0x" + "12" * 20}
    stack = ProtocolStack({"rexhepi": {"rate_limit_window_seconds": 1e-9,
                                       "rate_limit_max_actions": 10 ** 9}}, "neo")
    samples = {op: {m: [] for m in modes} for op in INSTRUMENTS}
    per_block = max(1, n // blocks)
    counter = {"i": 0}
    with tempfile.TemporaryDirectory() as scratch:
        engines = {"off": None}
        dbs = []
        for mode in modes:
            if mode != "off":
                db = Database({"database": {"path": f"{scratch}/g6-{mode}.db"}})
                dbs.append(db)
                engines[mode] = wiring.DurableEngine(db, mode=mode, canary="state_modifying")
        d = ServiceDispatcher({})
        d._get_registry = lambda: registry
        d._feed_engine = _Feed()
        server = GatewayServer({**SWEEP_CONFIG, "memory_dir": f"{scratch}/gw",
                                "database": {"path": f"{scratch}/gw.db"}})
        async with TestClient(TestServer(server.create_app())) as client:
            server.service_dispatcher = d
            # Warm up every path in every mode before anything is timed.
            for mode in modes:
                if wiring is not None:
                    wiring.install(engines[mode])
                try:
                    for w in range(50):
                        await stack.pre_action("platform_action",
                                               {"action": names[w % len(names)], "params": {}},
                                               dict(ctx))
                        await d.execute(names[w % len(names)], params={"marker": -w})
                        resp = await client.post(
                            "/bridge/v1/action",
                            json={"action": state_names[w % len(state_names)], "params": {}},
                            headers={"Idempotency-Key": f"g6-warm-{mode}-{w:04d}"})
                        await resp.read()
                finally:
                    if wiring is not None:
                        wiring.install(None)
            for block in range(blocks):
                order = list(modes[block % len(modes):]) + list(modes[:block % len(modes)])
                for mode in order:
                    if wiring is not None:
                        wiring.install(engines[mode])
                    try:
                        for _ in range(per_block):
                            i = counter["i"] = counter["i"] + 1
                            t0 = time.perf_counter()
                            await stack.pre_action("platform_action",
                                                   {"action": names[i % len(names)], "params": {}},
                                                   dict(ctx))
                            samples["pre_action"][mode].append(time.perf_counter() - t0)
                            t0 = time.perf_counter()
                            await d.execute(names[i % len(names)], params={"marker": i},
                                            caller_identity="0x" + "12" * 20)
                            samples["execute"][mode].append(time.perf_counter() - t0)
                            body = {"action": state_names[i % len(state_names)],
                                    "params": {"to": "0x" + "12" * 20, "marker": i}}
                            t0 = time.perf_counter()
                            resp = await client.post("/bridge/v1/action", json=body,
                                                     headers={"Idempotency-Key": f"g6-{i:08d}"})
                            await resp.read()
                            samples["bridge_action"][mode].append(time.perf_counter() - t0)
                    finally:
                        if wiring is not None:
                            wiring.install(None)
        for db in dbs:
            await db.close()
    if raw:
        return samples
    return {op: {m: _percentiles(v) for m, v in cells.items()} for op, cells in samples.items()}


def _host() -> dict:
    return {"machine": platform.machine(), "system": platform.system(),
            "python": platform.python_version(), "cpus": os.cpu_count()}


def _quiet(threshold: float, patience_s: float) -> float:
    """Wait (up to *patience_s*) for the host's one-minute load to fall under
    *threshold*; return the load the round starts at."""
    deadline = time.monotonic() + patience_s
    while os.getloadavg()[0] >= threshold and time.monotonic() < deadline:
        time.sleep(2)
    return round(os.getloadavg()[0], 2)


def build(main_root: str, branch_root: str, rounds: int = 10, n_per_round: int = 2000,
          quiet_below: float = 8.0, patience_s: float = 120.0) -> dict:
    """*rounds* rounds, each three fresh interpreters in a rotating order: main
    (off, its only path), this branch with only off (the same work main does),
    and this branch with off, shadow and on interleaved in blocks. Each round
    starts when the host's one-minute load is under *quiet_below* (or after
    *patience_s*). A mode is judged on the median over the rounds of its
    round's p95 over the same round's main p95; pooled figures are kept beside
    it."""
    import subprocess
    script = ("import asyncio, json, sys; sys.path.insert(0, 'tests'); "
              "sys.path.insert(0, %r); from test_durable_latency import measure_g6; "
              "print(json.dumps(asyncio.run(measure_g6(%d, blocks=5, raw=True, only=%r))))")
    runs = {"main": (main_root, ("off",)), "branch_off_only": (branch_root, ("off",)),
            "branch_interleaved": (branch_root, MODES)}
    pooled: dict[str, dict] = {name: {} for name in runs}
    load_before = [round(x, 2) for x in os.getloadavg()]
    round_loads: list[float] = []
    per_round: list[dict] = []
    order = list(runs)
    for r in range(rounds):
        round_loads.append(_quiet(quiet_below, patience_s))
        this_round: dict = {}
        for name in order[r % 3:] + order[:r % 3]:
            root, modes = runs[name]
            env = {k: v for k, v in os.environ.items() if not k.startswith("MATRIX_")}
            env.update(PYTHONPATH=root, PYTHONDONTWRITEBYTECODE="1", MATRIX_LOG_LEVEL="ERROR")
            proc = subprocess.run(
                [sys.executable, "-c", script % (str(ROOT / "tests"), n_per_round, modes)],
                cwd=root, env=env, capture_output=True, text=True, timeout=1800)
            if proc.returncode != 0:
                raise RuntimeError(proc.stderr[-3000:])
            run = json.loads(proc.stdout.strip().splitlines()[-1])
            this_round[name] = run
            for op, cells in run.items():
                for mode, values in cells.items():
                    pooled[name].setdefault(op, {}).setdefault(mode, []).extend(values)

        def p95(name, op, mode):
            return _percentiles(this_round[name][op][mode])["p95_us"]
        per_round.append({op: {
            "off": p95("branch_off_only", op, "off") / p95("main", op, "off"),
            "shadow": p95("branch_interleaved", op, "shadow") / p95("main", op, "off"),
            "on": p95("branch_interleaved", op, "on") / p95("main", op, "off"),
            "shadow_over_off_same_process": (p95("branch_interleaved", op, "shadow")
                                             / p95("branch_interleaved", op, "off")),
            "on_over_off_same_process": (p95("branch_interleaved", op, "on")
                                         / p95("branch_interleaved", op, "off")),
        } for op in INSTRUMENTS})

    def median(op, key):
        # Over the ratios as the artefact keeps them (4 places), so the judged
        # figure is recomputable from the artefact alone.
        return round(statistics.median(round(r[op][key], 4) for r in per_round), 3)

    summary: dict = {}
    for op in INSTRUMENTS:
        main = _percentiles(pooled["main"][op]["off"])
        cells = {"main_off": main}
        sources = {"off": ("branch_off_only", "off"), "shadow": ("branch_interleaved", "shadow"),
                   "on": ("branch_interleaved", "on")}
        for mode, (name, key) in sources.items():
            cell = _percentiles(pooled[name][op][key])
            cell["measured_in"] = name
            cell["p95_ratio_to_main"] = median(op, mode)
            cell["pooled_p95_ratio_to_main"] = round(cell["p95_us"] / main["p95_us"], 3)
            cell["p95_added_us"] = round(cell["p95_us"] - main["p95_us"], 1)
            if mode != "off":
                cell["p95_ratio_to_off_in_the_same_process"] = median(
                    op, f"{mode}_over_off_same_process")
            cell["within_budget"] = cell["p95_ratio_to_main"] <= BUDGET
            cells[f"branch_{mode}"] = cell
        summary[op] = cells
    verdict = {mode: {"within_budget": all(summary[op][f"branch_{mode}"]["within_budget"]
                                           for op in INSTRUMENTS),
                      "p95_ratio_to_main": {op: summary[op][f"branch_{mode}"]["p95_ratio_to_main"]
                                            for op in INSTRUMENTS}}
               for mode in MODES}
    return {"gate": "G6", "budget": f"p95 <= {BUDGET:.2f} x main's p95, per instrument "
                                    "(the packet's +10%, which it leaves to the principal to confirm)",
            "judged_on": ("p95_ratio_to_main: the median over the rounds of the round's p95 for "
                          "the mode over the same round's main p95. Off is measured in a process "
                          "that runs only off, as main's does; shadow and on in a process that "
                          "interleaves them with off in blocks, whose own off is kept for the "
                          "same-process ratio. Pooled p95s over all rounds are kept beside and "
                          "are not what is judged: on a shared host one loaded round moves them"),
            "instrument": ("tests/test_durable_latency.py measure_g6: in-process "
                           "time.perf_counter around ProtocolStack.pre_action (every ACTION_MAP "
                           "name in turn), ServiceDispatcher.execute (every ACTION_MAP name, a "
                           "stub service that answers settled at once) and POST "
                           "/bridge/v1/action through the aiohttp test client (every "
                           "state-modifying name, each under a fresh Idempotency-Key), after a "
                           "warm-up; each round three fresh interpreters in a rotating order"),
            "not_measured": ("the outbox loop's own delivery work, which runs after the answer; "
                             "a real service call, a chain or a network; the locust scenario "
                             "against a live gateway, which needs a model provider and a chain"),
            "host": {**_host(), "load_average_before": load_before,
                     "load_average_after": [round(x, 2) for x in os.getloadavg()],
                     "one_minute_load_at_each_round": round_loads,
                     "rounds_started_quiet_below": quiet_below},
            "noise": ("pre_action runs no line this phase changed; its off ratio is how far "
                      "apart two measurements of the same code land on this host"),
            "rounds": rounds, "n_per_cell": rounds * n_per_round,
            "per_round": [{op: {k: round(v, 4) for k, v in cells.items()}
                           for op, cells in r.items()} for r in per_round],
            "summary": summary, "verdict": verdict}


def test_g6_the_measurement_is_there_and_says_which_modes_are_within_budget():
    record = json.loads(ARTEFACT.read_text(encoding="utf-8"))
    assert record["gate"] == "G6" and record["n_per_cell"] >= 5000
    assert record["main"].startswith("main@")
    for op in INSTRUMENTS:
        cells = record["summary"][op]
        base = cells["main_off"]
        assert base["n"] >= 5000 and base["p95_us"] > 0
        for mode in MODES:
            cell = cells[f"branch_{mode}"]
            assert cell["n"] >= 5000
            assert cell["within_budget"] == (cell["p95_ratio_to_main"] <= BUDGET)
    for mode in MODES:
        assert record["verdict"][mode]["within_budget"] == all(
            record["summary"][op][f"branch_{mode}"]["within_budget"] for op in INSTRUMENTS)
    # The judged ratio is the median of the rounds the artefact keeps.
    assert len(record["per_round"]) == record["rounds"]
    for op in INSTRUMENTS:
        for mode in MODES:
            cell = record["summary"][op][f"branch_{mode}"]
            assert cell["p95_ratio_to_main"] == round(statistics.median(
                r[op][mode] for r in record["per_round"]), 3)
            if mode != "off":
                assert cell["p95_ratio_to_off_in_the_same_process"] == round(statistics.median(
                    r[op][f"{mode}_over_off_same_process"] for r in record["per_round"]), 3)
    # The budget is the packet's; mode off must meet it — it is main's path.
    assert record["verdict"]["off"]["within_budget"] is True


async def test_the_instrument_runs_in_every_mode():
    """The measurement function itself, at a small n, so it cannot rot."""
    result = await measure_g6(n=60, blocks=3)
    for op in INSTRUMENTS:
        assert set(result[op]) == set(MODES)
        assert all(cell["n"] == 60 and cell["p50_us"] > 0 for cell in result[op].values())
