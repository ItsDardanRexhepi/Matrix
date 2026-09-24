"""G8 — replayed bodies never act twice (engines Phase 2).

The packet's G8: duplicate effects over 1,000 replayed bodies must be 0. The
corpus here is 1,000 distinct requests to ``POST /bridge/v1/action`` — every
state-modifying action name in turn, under a service answering settled,
broadcast and refused — each under its own Idempotency-Key, and each replayed:
once, or — every seventh body — twice, and every fifth sent first as two
requests at the same moment. Every request carries a marker the service records, so a duplicate is a
marker the service saw twice. Each run's attestation and feed entry are counted
too, after the outbox loop has drained.

The same corpus in shadow is the measured contrast: shadow runs every replay
again, exactly as main does (B3), and journals each under its key, which is
the corpus the mode on is judged against.

``DURABLE_BASELINE=write`` writes ``tests/baseline/durable_replay.json``.
"""

from __future__ import annotations

import asyncio
import json
import os
import sys
from collections import Counter
from pathlib import Path

import pytest

sys.path.insert(0, "tests")

from aiohttp.test_utils import TestClient, TestServer  # noqa: E402

from durable_harness import (  # noqa: E402
    BROADCAST, REFUSED, SETTLED, STATE_ACTIONS, WALLET, FakeEAS, World, feed_rows, gateway,
    measured_where, stub_dispatcher,
)
from runtime.durable import wiring  # noqa: E402

ROOT = Path(__file__).resolve().parent.parent
ARTEFACT = ROOT / "tests" / "baseline" / "durable_replay.json"
WRITE = os.environ.get("DURABLE_BASELINE", "").strip().lower() == "write"
BODIES = 1000
_SHAPES = [SETTLED, BROADCAST, REFUSED]


async def run_corpus(scratch: Path, mode: str, monkeypatch) -> dict:
    from runtime.blockchain.services.attestation import batch_processor as bp
    world = World()
    monkeypatch.setattr(bp, "_eas_client_for", lambda _cfg: FakeEAS(world), raising=False)

    async def yield_a_little(_when, _kwargs):
        for _ in range(3):
            await asyncio.sleep(0)

    def answer(method, kwargs):
        return _SHAPES[int(kwargs.get("marker", 0)) % len(_SHAPES)]

    server = gateway(scratch, {"mode": mode, "canary": "state_modifying"})
    statuses: Counter = Counter()
    sent = 0
    async with TestClient(TestServer(server.create_app())) as client:
        engine = wiring.current()
        server.service_dispatcher = stub_dispatcher(world, answer, during=yield_a_little,
                                                    feed=server.social_feed_engine)

        async def post(i):
            action = STATE_ACTIONS[i % len(STATE_ACTIONS)]
            resp = await client.post(
                "/bridge/v1/action",
                json={"action": action, "params": {"to": WALLET, "amount": i + 1, "marker": i}},
                headers={"Idempotency-Key": f"g8-body-{i:05d}"})
            await resp.read()
            replayed = resp.headers.get("Idempotent-Replayed") == "true"
            statuses[f"{resp.status}{' replayed' if replayed else ''}"] += 1

        for i in range(BODIES):
            if i % 5 == 0:
                await asyncio.gather(post(i), post(i))
                sent += 2
            else:
                await post(i)
                sent += 1
            await post(i)
            sent += 1
            if i % 7 == 0:
                await post(i)
                sent += 1
        for _ in range(5):
            await engine.loop.tick()
        db = server.react_loop.memory.db
        runs = [dict(r) for r in db.fetchall_sync("SELECT run_id, key, state FROM workflow_runs")]
        feed = feed_rows(db)
        outbox = Counter(r[0] for r in db.fetchall_sync("SELECT state FROM outbox"))
    by_marker = Counter(e[2] for e in world.effects if e[0] == "service")
    attests = Counter(e[1] for e in world.effects if e[0] == "attest")
    runs_per_key = Counter(r["key"] for r in runs if r["key"])
    return {
        "mode": mode,
        "bodies": BODIES,
        "requests": sent,
        "service_calls": sum(by_marker.values()),
        "bodies_acted_on": len(by_marker),
        "duplicate_effects": sum(n - 1 for n in by_marker.values() if n > 1),
        "bodies_acted_on_more_than_once": sum(1 for n in by_marker.values() if n > 1),
        "attestations": sum(attests.values()),
        "attestations_queued_by_the_legacy_path": world.count("legacy_attest"),
        "feed_entries": len(feed),
        "feed_entries_per_run_at_most_one": len({r["id"] for r in feed}) == len(feed),
        "runs": len(runs),
        "keys_with_more_than_one_run": sum(1 for n in runs_per_key.values() if n > 1),
        "answers": dict(sorted(statuses.items())),
        "outbox": dict(sorted(outbox.items())),
    }


async def test_g8_no_replayed_body_acts_twice(tmp_path, monkeypatch):
    monkeypatch.delenv("MATRIX_DURABLE_MODE", raising=False)
    (tmp_path / "on").mkdir()
    on = await run_corpus(tmp_path / "on", "on", monkeypatch)
    assert on["duplicate_effects"] == 0 and on["bodies_acted_on_more_than_once"] == 0
    assert on["bodies_acted_on"] == BODIES, "every body acted exactly once"
    assert on["service_calls"] == BODIES
    assert on["keys_with_more_than_one_run"] == 0
    settled = sum(1 for i in range(BODIES) if i % 3 == 0)
    assert on["attestations"] == settled and on["feed_entries"] == settled
    assert on["attestations_queued_by_the_legacy_path"] == 0, "the loop owns them in mode on"
    assert on["feed_entries_per_run_at_most_one"]
    assert on["requests"] > 2 * BODIES
    # Every answer is the first one, replayed, or a 409 for a request that
    # arrived while its first was running.
    assert set(on["answers"]) <= {"200", "200 replayed", "503", "503 replayed", "409"}, on["answers"]
    assert on["answers"].get("409", 0) <= BODIES // 5

    (tmp_path / "shadow").mkdir()
    shadow = await run_corpus(tmp_path / "shadow", "shadow", monkeypatch)
    assert shadow["duplicate_effects"] == shadow["requests"] - BODIES > 0, "shadow runs every replay"
    assert shadow["keys_with_more_than_one_run"] == BODIES
    assert shadow["attestations"] == 0 and shadow["attestations_queued_by_the_legacy_path"] > settled

    if WRITE:
        ARTEFACT.write_text(json.dumps({
            "gate": "G8",
            "rule": "0 duplicate effects over 1,000 replayed bodies",
            "instrument": ("tests/test_durable_replay_corpus.py: 1,000 distinct POST "
                           "/bridge/v1/action bodies over every state-modifying action name, "
                           "each under its own Idempotency-Key, each replayed once (every "
                           "seventh body twice; every fifth sent first as two requests at "
                           "once), through the "
                           "aiohttp test client with engines.durable in mode on (canary "
                           "state_modifying); the service records a per-body marker, and the "
                           "outbox loop drains before counting"),
            "measured": measured_where(),
            "on": on,
            "shadow_contrast": shadow,
        }, indent=1, sort_keys=True) + "\n", encoding="utf-8")


def test_the_artefact_says_zero_duplicates_over_1000_bodies():
    record = json.loads(ARTEFACT.read_text(encoding="utf-8"))
    assert record["gate"] == "G8"
    on = record["on"]
    assert on["bodies"] >= 1000 and on["duplicate_effects"] == 0
    assert on["bodies_acted_on"] == on["bodies"] == on["service_calls"]
    assert record["shadow_contrast"]["duplicate_effects"] > 0
