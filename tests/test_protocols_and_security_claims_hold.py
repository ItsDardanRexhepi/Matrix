"""The protocols, the security seam and the agent boundary, held to the code.

Built true:
  * Friday's "critical events always notify" — suppression and cooldown were
    checked first, so a critical event in a suppressed category, or inside a
    cooldown, was dropped;
  * the no-op gate "logs that it ran" — it made no logger call at all;
  * the morpheus_triggers guard "pinned so a cleanup cannot silently drop it"
    — the pinning test named four of its nine entries.

Corrected where the sentence was wrong: "only 'not installed' degrades" (an
ImportError inside an installed core does too), the deletion intents that
"nothing can dispatch", the Rexhepi gate that "every operation must pass" and
its wallet and network checks, Vision's "always follows", the conversational
initiative's "only", and outcome storage called "append-only JSONL".

Not here: the sentences about the agent boundary — Trinity "never any
state-changing action" and "only this single, gated channel", "a subverted
agent cannot reach another agent's tools", "never fails open". Whether the
boundary is built to what they say or they are corrected to what the code
keeps is the owner's decision, and they stay as written until he makes it.
"""

from __future__ import annotations

import logging
import re
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent


def _text(rel: str) -> str:
    raw = (ROOT / rel).read_text(encoding="utf-8")
    return re.sub(r"\s+", " ", re.sub(r"\s*#\s*", " ", raw))


# ── Friday ─────────────────────────────────────────────────────────────────

async def test_a_critical_event_in_a_suppressed_category_still_notifies():
    from runtime.protocols.friday import FridayProtocol

    f = FridayProtocol({})
    f.suppress_category("security")
    assert await f.should_notify({"category": "security", "urgency": "critical",
                                  "id": "e1"}) is True


async def test_a_critical_event_inside_a_cooldown_still_notifies():
    from runtime.protocols.friday import FridayProtocol

    f = FridayProtocol({})
    event = {"category": "wallet", "urgency": "critical", "id": "e2"}
    assert await f.should_notify(event) is True
    assert await f.should_notify(event) is True, "a second critical event was held by a cooldown"


# ── the no-op gate ─────────────────────────────────────────────────────────

async def test_the_noop_gate_logs_each_evaluation(caplog):
    import runtime.security as seam

    if seam.SECURITY_BACKEND != "noop" or not hasattr(seam, "_NoopMorpheus"):
        return  # a checkout with the private core installed has no no-op to test
    with caplog.at_level(logging.DEBUG, logger="runtime.security"):
        out = await seam._NoopMorpheus().evaluate({"action_type": "transfer"}, {})
    assert out["allow"] is True
    assert any("observe no-op evaluated" in r.getMessage() for r in caplog.records), (
        "the no-op gate says it logs that it ran, and it logged nothing")


# ── the guard pin ──────────────────────────────────────────────────────────

def test_the_guard_block_is_pinned_entry_by_entry():
    pin = (ROOT / "tests" / "test_defi_exotics_removed.py").read_text()
    loop = re.search(r"for name in \(([^)]*)\):\s*(?:#[^\n]*\s*)*"
                     r"assert _ACTION_CATEGORY_MAP\.get\(name\) == \"defi\"", pin)
    assert loop, "the category pin moved; re-read it"
    pinned = set(re.findall(r'"([a-z_]+)"', loop.group(1)))
    for name in ("flash_loan", "yield_optimize", "liquidity_provide", "perp_trade",
                 "options_trade", "vault_deposit", "leverage_position",
                 "collateral_manage", "synthetic_asset"):
        assert name in pinned, f"{name} is in the guard block and not pinned"


# ── the sentences ──────────────────────────────────────────────────────────

def test_the_seam_sentences_say_what_holds():
    seam = _text("runtime/security/__init__.py")
    assert "every action is allowed and logged, nothing is enforced" not in seam
    assert "Only the first is caught now." not in seam


def test_the_protocol_sentences_say_what_the_code_does():
    assert "(so nothing can dispatch them)" not in _text("runtime/chat/intent_actions.py")
    assert "Only generate initiative for stressed or uncertain states" not in _text(
        "runtime/protocols/conversational.py")
    assert "Append-only JSONL storage" not in _text("runtime/protocols/outcome_schema.py").replace(
        '"Append-only JSONL storage"', "")
    gate = _text("runtime/protocols/rexhepi_gate.py")
    assert "Every platform operation MUST pass through this gate before execution." not in gate
    assert "Cannot transact without a connected wallet" not in gate.replace(
        '"cannot transact without a connected wallet"', "")
    assert "historically always follows with action Y" not in _text("runtime/protocols/vision.py")
