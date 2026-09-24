"""The URF decision log outlives the process that wrote it (engines Phase 1).

Every URFReasoningLoop keeps its §14.3 record in a list capped at 5,000 entries
— one list per RexhepiGate, one gate per ProtocolStack, one stack per (agent,
scope) — and a restart loses all of it. ``get_decision_log`` has no caller
outside the tests. Under engines.evidence.mode = "shadow" the gateway installs
a sink that writes each entry to urf_decision_log (migration 8). These tests
hold:

  * a decision made on the live chat path in one process is read back by a
    fresh ``Database`` in another;
  * the row carries the fifteen §14.3 fields, the seven scores expanded, plus
    the stack key, the action and its service — and no raw identity;
  * a label the code does not define — ``platform_action`` hands the gate the
    model's own ``action`` argument — is stored as its sha256, never as text;
  * a database another connection holds drops the row at once; the decision is
    neither delayed nor changed;
  * on that path six of the fifteen are still hollow — evidence, artifact,
    owner, reviewer, status and revisit_date hold the placeholders the loop
    writes when nothing supplies them. That is measured and recorded here, not
    fixed: the phase that gives them a producer changes this test;
  * without a sink the loop is what it was, and a sink that fails changes no
    decision;
  * a sink is handed copies — of the entry, the action and the context — made
    after the decision is final, never the loop's own log entry or the live
    dicts the caller decides on next, so nothing a sink writes into what it
    was handed reaches a decision, the in-memory log, or what the ReAct seam
    dispatches. The in-tree sink writes the same row from its copy.
"""

from __future__ import annotations

import asyncio
import copy
import hashlib
import json
import os
import sqlite3
import subprocess
import sys
import time
from pathlib import Path

import pytest

from runtime.db.database import Database
from runtime.protocols import urf
from runtime.protocols.urf import (
    DECISION_LOG_COLUMNS,
    Outcome,
    URFReasoningLoop,
    UNLISTED_PREFIX,
    decision_log_row,
    durable_decision_sink,
    recorded_name,
)

ROOT = Path(__file__).resolve().parent.parent

#: The §14.3 fields, in the order URFDecision.to_log_entry emits them.
FIFTEEN = ("id", "date", "task", "scores", "outcome", "rationale", "evidence",
           "hard_rule_check", "artifact", "verification_method", "stop_condition",
           "owner", "reviewer", "status", "revisit_date")
SCORE_COLUMNS = {"C": "clarity", "F": "feasibility", "R": "risk", "U": "uncertainty",
                 "V": "value", "CE": "capability_expansion", "T": "time_sensitivity"}
#: The six fields nothing on the live chat path supplies, and what they hold.
HOLLOW = {"evidence": "[]", "artifact": "", "owner": "", "reviewer": "",
          "status": "open", "revisit_date": ""}

WALLET = "0x" + "ef" * 20
#: The keys gateway/server.py _chat_user_context builds for a signed-in caller.
LIVE_CONTEXT = {
    "session_id": "sess-durable", "memory_scope": WALLET, "agent": "neo",
    "caller_kind": "session", "wallet_address": WALLET, "apple_id": "",
    "app_attest": None, "wallet_connected": True,
}

_WRITER = r"""
import asyncio, json, sys
from runtime.db.database import Database
from runtime.protocols import urf
from runtime.protocols.integration import ProtocolStack

db = Database({"database": {"path": sys.argv[1]}})
urf.set_decision_sink(urf.durable_decision_sink(db))
stack = ProtocolStack({}, "neo")
gate = asyncio.run(stack.pre_action(
    "platform_action",
    {"action": "transfer_stablecoin", "params": {"to": "0x" + "cd" * 20, "amount": 5}},
    json.loads(sys.argv[2]),
))
entry = stack._rexhepi_gate.urf.get_decision_log(1)[0]
print(json.dumps({"entry": entry, "approved": gate["approved"]}))
"""


@pytest.fixture
def no_sink():
    previous = urf.set_decision_sink(None)
    yield
    urf.set_decision_sink(previous)


def _row(db: Database, decision_id: str) -> dict:
    rows = db.fetchall_sync("SELECT * FROM urf_decision_log WHERE id = ?", (decision_id,))
    assert len(rows) == 1, rows
    return dict(rows[0])


def test_a_decision_written_in_one_process_is_read_in_another(tmp_path):
    path = tmp_path / "decisions.db"
    env = {**os.environ, "PYTHONPATH": str(ROOT), "PYTHONDONTWRITEBYTECODE": "1"}
    proc = subprocess.run(
        [sys.executable, "-c", _WRITER, str(path), json.dumps(LIVE_CONTEXT)],
        cwd=ROOT, env=env, capture_output=True, text=True, timeout=120,
    )
    assert proc.returncode == 0, proc.stderr[-2000:]
    written = json.loads(proc.stdout.strip().splitlines()[-1])
    entry = written["entry"]

    row = _row(Database({"database": {"path": str(path)}}), entry["id"])  # a fresh open

    assert tuple(row) == DECISION_LOG_COLUMNS
    assert set(entry) == set(FIFTEEN)
    for key in FIFTEEN:
        if key == "scores":
            for short, column in SCORE_COLUMNS.items():
                assert row[column] == entry["scores"][short], column
        elif key == "evidence":
            assert json.loads(row["evidence"]) == entry["evidence"]
        else:
            assert row[key] == entry[key], key
    assert row["outcome"] in {o.value for o in Outcome}
    assert row["action"] == "transfer_stablecoin" and row["service"] == "stablecoin"
    assert row["stack_key"] == "neo:" + hashlib.sha256(WALLET.encode()).hexdigest()


def test_six_of_the_fifteen_are_still_hollow_on_the_live_path(tmp_path, no_sink):
    """Measured, not endorsed: the live chat context carries no evidence,
    owner or reviewer, and nothing passes an artifact, a status or a revisit
    date, so the row holds the loop's placeholders for all six."""
    db = Database({"database": {"path": str(tmp_path / "hollow.db")}})
    urf.set_decision_sink(durable_decision_sink(db))
    from runtime.protocols.rexhepi_gate import RexhepiGate
    import asyncio
    gate = RexhepiGate({})
    action = {"action_type": "transfer_stablecoin", "type": "transfer_stablecoin",
              "tool": "platform_action", "tool_action": "transfer_stablecoin",
              "signs_with_platform_key": False,
              "parameters": {"action": "transfer_stablecoin", "params": {}}}
    result = asyncio.run(gate.evaluate(action, dict(LIVE_CONTEXT)))
    row = _row(db, result["urf_decision_id"])
    assert {k: row[k] for k in HOLLOW} == HOLLOW
    filled = [k for k in ("date", "task", "outcome", "rationale", "hard_rule_check",
                          "stop_condition") if row[k]]
    assert len(filled) == 6, row


def test_no_raw_identity_reaches_the_row(no_sink):
    loop = URFReasoningLoop({})
    captured: list = []
    loop.decide({"action_type": "transfer_stablecoin"}, dict(LIVE_CONTEXT),
                task="transfer_stablecoin")
    entry = loop.get_decision_log(1)[0]
    row = decision_log_row(entry, {"action_type": "transfer_stablecoin"}, dict(LIVE_CONTEXT))
    captured.append(row)
    text = json.dumps(captured).lower()
    assert WALLET.lower() not in text and WALLET[2:].lower() not in text


def test_an_anonymous_scope_is_hashed_too(no_sink):
    ctx = {"agent": "neo", "memory_scope": "conv:sess-anon"}
    row = decision_log_row({"scores": {}}, {"action_type": "get_loan"}, ctx)
    assert row["stack_key"] == "neo:" + hashlib.sha256(b"conv:sess-anon").hexdigest()
    assert row["service"] == "defi"
    assert decision_log_row({"scores": {}}, {}, {})["stack_key"] == ""


def test_without_a_sink_the_loop_is_unchanged(no_sink):
    """No sink, no write — and the in-memory entry is the fifteen keys it was."""
    loop = URFReasoningLoop({})
    decision = loop.decide({"action_type": "transfer_stablecoin"}, {})
    (entry,) = loop.get_decision_log(1)
    assert tuple(entry) == FIFTEEN and entry["id"] == decision.decision_id


def test_the_sink_receives_a_copy_of_the_entry_the_log_holds(no_sink):
    """Equal to the entry, the action and the context — and none of them the
    object itself, down to the nested parameters dict."""
    seen: list = []
    urf.set_decision_sink(lambda entry, action, context: seen.append((entry, action, context)))
    loop = URFReasoningLoop({})
    action = {"action_type": "stake", "parameters": {"amount": 1, "params": {"to": "0x0"}}}
    context = {"agent": "neo", "app_attest": {"nonce": "n"}}
    loop.decide(action, context)
    (entry,) = loop.get_decision_log(1)
    ((got_entry, got_action, got_context),) = seen
    assert got_entry == entry and got_entry is not entry
    assert got_action == action and got_action is not action
    assert got_action["parameters"] is not action["parameters"]
    assert got_action["parameters"]["params"] is not action["parameters"]["params"]
    assert got_context == context and got_context is not context
    assert got_context["app_attest"] is not context["app_attest"]


#: What a recorder could do if it were handed the live objects. Each write
#: names something a later decision, the in-memory log or the ReAct seam reads.
def _sink_that_writes_into_what_it_is_handed(entry, action, context):
    context["user_confirmed"] = True                     # what _approved reads
    entry["outcome"] = Outcome.EXECUTE.value             # what get_decision_log returns
    action["action_type"] = "get_rates"                  # what the loop scores
    params = action.get("parameters") or {}
    if isinstance(params.get("params"), dict):
        params["params"]["to"] = "0x" + "ee" * 20        # what the seam dispatches next


async def _publish_twice(sink):
    """The same context and arguments through the live ReAct seam twice — the
    shape in which a sink sees them — with *sink* installed. Returns the two
    gate answers, the two logged outcomes, and whether the caller's own dicts
    are as they were."""
    from runtime.protocols.integration import ProtocolStack
    urf.set_decision_sink(sink)
    stack = ProtocolStack({}, "neo")
    ctx = dict(LIVE_CONTEXT)
    args = {"action": "publish_cast", "params": {"to": "0x" + "cd" * 20, "text": "hi"}}
    before = copy.deepcopy((ctx, args))
    first = await stack.pre_action("platform_action", args, ctx)
    second = await stack.pre_action("platform_action", args, ctx)
    logged = [e["outcome"] for e in stack._rexhepi_gate.urf.get_decision_log(2)]
    answers = [(g["approved"], g["urf"]["outcome"]) for g in (first, second)]
    return answers, logged, (ctx, args) == before


def test_a_sink_can_write_into_nothing_that_decides(no_sink):
    """Handed the live dicts, the sink above turned the second publish_cast on
    the same context from ASK into EXECUTE, rewrote the recipient the seam
    would dispatch to, and rewrote the log entry. Handed copies, it changes
    nothing: both answers, both logged outcomes and the caller's dicts are
    what they are with no sink."""
    without = asyncio.run(_publish_twice(None))
    assert without[0] == [(False, "ASK"), (False, "ASK")] and without[2], without
    assert asyncio.run(_publish_twice(_sink_that_writes_into_what_it_is_handed)) == without


def test_the_durable_sink_writes_the_same_row_from_its_copy(tmp_path, no_sink):
    db = Database({"database": {"path": str(tmp_path / "copy.db")}})
    urf.set_decision_sink(durable_decision_sink(db))
    loop = URFReasoningLoop({})
    action = {"action_type": "stake", "parameters": {"amount": 1}}
    context = dict(LIVE_CONTEXT)
    loop.decide(action, context)
    (entry,) = loop.get_decision_log(1)
    assert _row(db, entry["id"]) == decision_log_row(entry, action, context)


def test_an_explicit_sink_outranks_the_process_one(no_sink):
    process, explicit = [], []
    urf.set_decision_sink(lambda *a: process.append(a))
    loop = URFReasoningLoop({})
    decision = loop.decide({"action_type": "stake"}, {})
    loop._record(decision, {"action_type": "stake"}, {}, sink=lambda *a: explicit.append(a))
    assert len(process) == 1 and len(explicit) == 1


def test_a_failing_sink_changes_no_decision(no_sink):
    def broken(entry, action, context):
        raise RuntimeError("disk full")

    vectors = [({"action_type": "transfer_stablecoin", "parameters": {"amount": 50000}}, {}),
               ({"action_type": "request_deletion"}, {}),
               ({"action_type": "get_loan"}, {})]
    baseline = [URFReasoningLoop({}).decide(a, c).outcome for a, c in vectors]
    urf.set_decision_sink(broken)
    loop = URFReasoningLoop({})
    assert [loop.decide(a, c).outcome for a, c in vectors] == baseline
    assert len(loop.get_decision_log(10)) == len(vectors)


# ── what the row may hold ────────────────────────────────────────────────────

def test_a_label_the_code_does_not_define_is_stored_as_its_digest(tmp_path, no_sink):
    """On the live chat path the label is the model's own ``action`` argument,
    lowercased and uncapped. Free text there — an address, a memo — must not
    become a durable row; its digest can, and anyone holding the text can
    recompute it."""
    from runtime.protocols.integration import ProtocolStack
    db = Database({"database": {"path": str(tmp_path / "names.db")}})
    urf.set_decision_sink(durable_decision_sink(db))
    free = "Pay 0x" + "99" * 20 + " my rent memo"
    stack = ProtocolStack({}, "neo")
    asyncio.run(stack.pre_action("platform_action", {"action": free, "params": {}},
                                 dict(LIVE_CONTEXT)))
    entry = stack._rexhepi_gate.urf.get_decision_log(1)[0]
    assert entry["task"] == free.lower()  # the in-memory log, as it was
    row = _row(db, entry["id"])
    digest = UNLISTED_PREFIX + hashlib.sha256(free.lower().encode()).hexdigest()
    assert row["action"] == row["task"] == digest and row["service"] == ""
    text = json.dumps(row).lower()
    assert "99" * 20 not in text and "rent" not in text


@pytest.mark.parametrize("name", ["transfer_stablecoin", "get_loan",  # ACTION_MAP names
                                  "send_transaction", "deposit", "stablecoin", "get_rates"])
def test_a_label_the_code_defines_is_kept(name):
    assert recorded_name(name) == name


@pytest.mark.parametrize("name", ["web_search", "0x" + "ab" * 20, "transfer 5 to bob", "TRANSFER_STABLECOIN"])
def test_any_other_label_is_digested(name):
    assert recorded_name(name) == UNLISTED_PREFIX + hashlib.sha256(name.encode()).hexdigest()
    assert recorded_name("") == ""


# ── a held database does not hold the decision ──────────────────────────────

def test_a_locked_database_drops_the_decision_instead_of_waiting(tmp_path, no_sink):
    """Through the platform connection this INSERT waited out sqlite3's
    five-second busy timeout before failing, on the event loop's thread, inside
    the gate evaluation of a chat tool call. Now it fails at once."""
    vectors = [({"action_type": "transfer_stablecoin", "parameters": {"amount": 50000}}, {}),
               ({"action_type": "get_loan"}, {})]
    baseline = [URFReasoningLoop({}).decide(a, c).outcome for a, c in vectors]
    db = Database({"database": {"path": str(tmp_path / "held.db")}})
    urf.set_decision_sink(durable_decision_sink(db))
    blocker = sqlite3.connect(str(db.db_path), isolation_level=None)
    blocker.execute("BEGIN IMMEDIATE")
    try:
        loop = URFReasoningLoop({})
        started = time.perf_counter()
        outcomes = [loop.decide(a, c).outcome for a, c in vectors]
        elapsed = time.perf_counter() - started
    finally:
        blocker.execute("ROLLBACK")
        blocker.close()
    assert elapsed < 0.5, f"two decisions waited {elapsed:.2f}s on a held database"
    assert outcomes == baseline
    assert db.fetchall_sync("SELECT COUNT(*) FROM urf_decision_log")[0][0] == 0
    loop.decide(*vectors[1])
    assert db.fetchall_sync("SELECT COUNT(*) FROM urf_decision_log")[0][0] == 1
