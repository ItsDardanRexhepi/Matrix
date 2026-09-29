"""Morpheus's note reaches the user with the result, after the call ran, and a
denied call carries the gate's reason, not his voice.

The pre-action stack decides whether Morpheus has a note for a tool call, and
the reasoning loop prepends that note to the tool's result once the tool has
been dispatched (runtime/react_loop.py). The user reads it with the outcome,
after the call has run. The texts said otherwise:

  * the README put him "Before every irreversible action", docs/agents.md said
    he "explains what the user is about to do before they do it" and "states
    what is about to happen", his own prompt said the same three ways, and
    course 01 and course 03 said he speaks "before an action that cannot be
    undone";
  * the notes he writes said "You are about to interact with ...", "Verify the
    recipient ... carefully", "Proceed only if you are certain" and "Pause and
    consider before proceeding", to a user reading them after the call ran;
  * his prompt said a call the Glasswing audit denies is denied "in Morpheus's
    voice", and that "If the audit fails, Morpheus explains what was found".
    ProtocolStack.pre_action writes a Morpheus message on that denial, and the
    loop reads only the denial reason when a call is not approved: the model
    and the user read "[DENIED] Glasswing audit blocked deployment: ...".

The notes that replaced them then said what the result would hold: "The
address, the amount and the network are in the result that follows", "The
recipient, network and parameters are in the result that follows", "The details
are in the result that follows", and, for a first bridge, "the bridge, the
destination chain and the amount are in the result". A note is written before
the call runs, from its parameters, and the loop adds it to whatever comes back,
a refusal or a failure included; the client is sent the first 200 characters.
A first transaction whose call is refused came back as the note, then "A step in
this request could", with no address, amount or network in it. For the same
reason docs/agents.md's "the user reads it after the action has run" and his
prompt's "once the tool has run ... after the action has happened" were wrong
on a call that is refused or fails.

The premises are measured by running the loop with a scripted model: a vote,
whose first use in governance draws a note, a contract call carrying a
selfdestruct, which the audit denies, and a first transaction whose call does
not happen. The texts are then read against them.

What this cannot see: the timing or the denial described in words outside the
patterns below.
"""

from __future__ import annotations

import asyncio
import json
import re
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
_NOT_READ = {"CHANGELOG.md", "web/terms.html", "web/privacy.html"}
_SELFDESTRUCT = ("pragma solidity ^0.8.0; contract X { function k() public "
                 "{ selfdestruct(payable(msg.sender)); } }")

_BEFORE_THE_ACTION = [
    r"before every irreversible action",
    r"before (?:an|any) (?:irreversible )?action that cannot be undone",
    r"what the user is (?:actually )?(?:about to do|doing) before they do it",
    r"what is about to happen",
    r"speaks before an irreversible action",
    r"guidance before the action outcome",
]
_MORPHEUS_VOICE_ON_A_DENIAL = [
    r"denial is (?:written|given|delivered) in (?:morpheus'?s?|his) voice",
    r"if the audit fails, morpheus explains",
]
_AS_IF_THE_ACTION_HAPPENED = [
    r"after the action has (?:run|happened)",
    r"once the tool has run",
]
_A_NOTE_THAT_SAYS_WHAT_THE_RESULT_HOLDS = re.compile(
    r"\b(?:is|are) in the result\b|\bthe result (?:that follows )?(?:shows|lists|contains|carries|holds|has)\b",
    re.I)
_A_NOTE_WRITTEN_FOR_BEFORE = re.compile(
    r"\byou are about to\b|\byou are entering\b|\bproceed only if\b|\bbefore (?:proceeding|"
    r"submitting|transacting|committing|deploying)\b|\bpause and consider\b|\byou will lose\b"
    r"|\bverify (?:every|the|model|the asset)\b[^.]{0,60}\b(?:carefully|before)\b"
    r"|\btake a moment to verify\b|\breview all (?:details|terms)\b", re.I)


def _flat(text: str) -> str:
    return re.sub(r"\s+", " ", re.sub(r"<[^>]+>", " ", text)).lower()


def _run_the_loop(tool: str, arguments: dict, metadata: dict | None = None,
                  fail: bool = False) -> tuple[list[str], list[dict], list[list[str]]]:
    """One scripted turn: the model calls *tool*, then answers. Returns the order
    of events, the tool calls the client is sent, and the tool messages the
    model had been given at each of its turns. With *fail*, the tool raises."""
    sys.path.insert(0, str(ROOT / "tests"))
    import tempfile

    from test_route_sweep import SWEEP_CONFIG

    from runtime.models.model_interface import ModelResponse
    from runtime.react_loop import Message, ReActContext, ReActLoop

    order: list[str] = []
    seen: list[list[str]] = []
    replies = [ModelResponse(tool_calls=[{"id": "c1", "function": {
                   "name": tool, "arguments": json.dumps(arguments)}}]),
               ModelResponse(content="done")]

    async def complete(**kwargs):
        seen.append([m.content for m in kwargs.get("messages") or [] if m.role == "tool"])
        order.append("model")
        return replies.pop(0)

    async def handler(**kwargs):
        order.append("tool ran")
        if fail:
            raise RuntimeError("the node refused the call")
        return json.dumps({"status": "ok"})

    loop = ReActLoop({**SWEEP_CONFIG, "memory_dir": tempfile.mkdtemp()})
    loop.router.complete = complete
    loop.dispatcher._tools[tool] = handler
    result = asyncio.run(loop.run(ReActContext(
        agent_name="neo", conversation=[Message(role="user", content="go")], metadata=metadata or {})))
    return order, result.tool_calls, seen


def _premises() -> list[str]:
    problems = []
    order, calls, seen = _run_the_loop("platform_action", {"action": "vote", "params": {}})
    preview = calls[0]["result_preview"] if calls else ""
    if order != ["model", "tool ran", "model"] or not preview.startswith("[Morpheus]"):
        problems.append(f"a governance first use no longer carries a note after the call ran: "
                        f"{order} {preview[:80]!r}")
    if any("[Morpheus]" in m for m in seen[0]):
        problems.append("a note reached the model before the call ran")
    order, calls, _seen = _run_the_loop("smart_contract", {"action": "compile",
                                                           "source_code": _SELFDESTRUCT})
    preview = calls[0]["result_preview"] if calls else ""
    if "tool ran" in order or not preview.startswith("[DENIED] Glasswing audit blocked deployment"):
        problems.append(f"the audit no longer denies a selfdestruct: {order} {preview[:80]!r}")
    if "morpheus" in preview.lower():
        problems.append(f"a denied call carries a Morpheus note now: {preview[:120]!r}")
    address = "0x" + "5a" * 20
    order, calls, seen = _run_the_loop("payment", {"action": "send_eth", "to": address, "amount": "3.5"},
                                       metadata={"user_context": {"total_transactions": 0}}, fail=True)
    preview = calls[0]["result_preview"] if calls else ""
    after = seen[1][0].split("\n\n", 1)[1] if len(seen) > 1 and "\n\n" in seen[1][0] else ""
    if not preview.startswith("[Morpheus] This is your first transaction") or calls[0]["success"] is not False:
        problems.append(f"a first transaction that does not happen no longer carries a note: {preview[:80]!r}")
    if not after or address in after or "3.5" in after or len(preview) > 200:
        problems.append(f"the result a note is added to carries the call's details now: {after[:120]!r}")
    return problems


def _public_texts():
    out = subprocess.check_output(["git", "ls-files", "*.md", "*.html"], cwd=ROOT, text=True)
    for rel in out.splitlines():
        if rel in _NOT_READ or rel.startswith("tests/") or not (ROOT / rel).is_file():
            continue
        yield rel, _flat((ROOT / rel).read_text(encoding="utf-8"))


def _every_note_morpheus_writes() -> list[str]:
    from runtime.protocols import morpheus_triggers as mt
    system = mt.MorpheusTriggerSystem
    categories = set(mt._ACTION_CATEGORY_MAP.values()) | {"a_category_with_no_intro"}
    notes = [system._gen_first_capability({"category": c, "action": {"action_type": "x"}})
             for c in sorted(categories)]
    kinds = sorted(mt._IRREVERSIBLE_ACTIONS | {"an_action_with_no_note"})
    notes += [system._gen_irreversible({"action": {"action_type": k}}) for k in kinds]
    notes += [system._gen_significant({"action": {}, "user_context": {"total_transactions": 0}}),
              system._gen_significant({"action": {"parameters": {"value": 25000}}, "user_context": {}}),
              system._gen_significant({"action": {}, "user_context": {}}),
              system._gen_on_demand({}), system._gen_fallback({})]
    return notes


def test_the_scans_catch_the_old_copy():
    old = _flat("Before every irreversible action. Guidance — explains what the user is about to "
                "do before they do it. Morpheus states what is about to happen. Morpheus explains "
                "what the user is actually doing before they do it. When he speaks before an "
                "irreversible action. before an action that cannot be undone. sees Morpheus's "
                "guidance before the action outcome. A Critical finding denies the call, and the "
                "denial is written in Morpheus's voice. If the audit fails, Morpheus explains what "
                "was found.")
    assert {p for p in _BEFORE_THE_ACTION + _MORPHEUS_VOICE_ON_A_DENIAL if re.search(p, old)} == set(
        _BEFORE_THE_ACTION + _MORPHEUS_VOICE_ON_A_DENIAL)
    for note in ("[Morpheus] You are about to stake tokens.",
                 "[Morpheus] You are entering the world of decentralised finance.",
                 "[Morpheus] This is an irreversible action. Proceed only if you are certain.",
                 "[Morpheus] Pause and consider before proceeding.",
                 "Transferring ownership is permanent. You will lose control of this contract.",
                 "Take a moment to verify every detail — the address, the amount, the network.",
                 "Verify the recipient, network, and parameters carefully.",
                 "[Morpheus] This is a significant moment. Review all details before proceeding."):
        assert _A_NOTE_WRITTEN_FOR_BEFORE.search(note), note
    assert not _A_NOTE_WRITTEN_FOR_BEFORE.search("[Morpheus] This is your first staking action. Its result follows.")
    for note in ("[Morpheus] This is your first transaction. Welcome. The address, the amount and the network "
                 "are in the result that follows.",
                 "This is a significant amount. The recipient, network and parameters are in the result that follows.",
                 "[Morpheus] This is a significant moment. The details are in the result that follows.",
                 "Bridge exploits are among the most costly in crypto — the bridge, the destination chain and the "
                 "amount are in the result."):
        assert _A_NOTE_THAT_SAYS_WHAT_THE_RESULT_HOLDS.search(note), note
    assert not _A_NOTE_THAT_SAYS_WHAT_THE_RESULT_HOLDS.search(
        "[Morpheus] Consider what this action does; its result follows.")


def test_no_text_puts_morpheus_before_the_action_or_his_voice_on_a_denial():
    premises = _premises()
    assert not premises, "re-derive this check: " + "; ".join(premises)
    offenders = [f"{rel}: ...{flat[max(0, m.start() - 60):m.end() + 30]}..."
                 for rel, flat in _public_texts()
                 for pattern in _BEFORE_THE_ACTION + _MORPHEUS_VOICE_ON_A_DENIAL
                 for m in re.finditer(pattern, flat)]
    assert not offenders, "\n".join(offenders)


def test_no_note_morpheus_writes_is_worded_for_before_the_call():
    premises = _premises()
    assert not premises, "re-derive this check: " + "; ".join(premises)
    notes = _every_note_morpheus_writes()
    assert len(notes) > 30
    wrong = [note for note in notes if _A_NOTE_WRITTEN_FOR_BEFORE.search(note)]
    assert not wrong, "\n".join(wrong)


def test_no_text_says_the_note_follows_an_action_that_happened():
    premises = _premises()
    assert not premises, "re-derive this check: " + "; ".join(premises)
    old = _flat("his note is added to the action's result, so the user reads it after the action has run. "
                "This message is prepended to the tool result once the tool has run, so the model reads "
                "Morpheus's guidance ahead of the outcome in the same reply, after the action has happened.")
    assert all(re.search(p, old) for p in _AS_IF_THE_ACTION_HAPPENED)
    offenders = [f"{rel}: ...{flat[max(0, m.start() - 60):m.end() + 30]}..."
                 for rel, flat in _public_texts()
                 for pattern in _AS_IF_THE_ACTION_HAPPENED
                 for m in re.finditer(pattern, flat)]
    assert not offenders, "\n".join(offenders)


def test_no_note_morpheus_writes_says_what_the_result_holds():
    premises = _premises()
    assert not premises, "re-derive this check: " + "; ".join(premises)
    notes = _every_note_morpheus_writes()
    assert len(notes) > 30
    wrong = [note for note in notes if _A_NOTE_THAT_SAYS_WHAT_THE_RESULT_HOLDS.search(note)]
    assert not wrong, "\n".join(wrong)
