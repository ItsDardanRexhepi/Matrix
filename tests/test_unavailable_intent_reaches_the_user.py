"""The honest-unavailable idiom, driven through the consumer that renders it.

THE RETROACTIVE FINDING. Sixteen capabilities across six closed domains were
disposed of with the `unavailable` intent-guide idiom: keep the keywords so the
request still matches, drop `action_name` so the model cannot dispatch it, and
carry a `follow_up` telling the user honestly. The routing half worked. The
user-facing half NEVER DID.

`match_intent` returns `dict(INTENT_ACTION_MAP[name])` — the whole guide. For an
`unavailable` entry that dict has no `action_name`, and the sole production
consumer (`ProtocolStack.pre_process`) subscripted it. The KeyError was caught by
a bare `except Exception` and logged at DEBUG, discarding the ENTIRE enrichment.
Measured before the fix: all sixteen delivered ZERO enrichments — output
indistinguishable from a message the platform does not recognise at all, which
is exactly what keeping the keywords was supposed to prevent.

Six domains closed with some form of "the user is now told honestly". That was
true of the code and false of the experience.

SECOND OCCURRENCE OF THE INERT-FIX PATTERN, after ACTION_LABELS. Both were found
by an adversarial pass, not by the fix's own tests — because in both cases the
tests asserted the STRUCTURE of the fix (does the entry have the right keys?)
and never drove the CONSUMER that turns structure into words a user reads. Hence
this file: it exists at the layer the originals could not see.

WHAT WAS DELIBERATELY MEASURED AND FOUND *NOT* TO BE TRUE, recorded so the
finding is not inflated: an unavailable match was never WORSE than no match (both
produced zero), and a close unavailable runner-up never destroyed a working top
match (only the `[Intent Alt]` line was lost, because the top's line was appended
first). Both are pinned below so the repair cannot regress them.
"""

from __future__ import annotations

import pytest

from runtime.chat.intent_actions import INTENT_ACTION_MAP
from runtime.protocols.integration import ProtocolStack
from runtime.react_loop import Message, ReActContext

def _name_of(entry: dict) -> str | None:
    """Resolve by keywords, not description — six entries share a description."""
    probe = tuple(entry.get("keywords") or ())
    for action, guide in INTENT_ACTION_MAP.items():
        if tuple(guide.get("keywords") or ()) == probe:
            return action
    return None


UNAVAILABLE = sorted(a for a, g in INTENT_ACTION_MAP.items() if g.get("unavailable"))


async def _intent_enrichments(text: str) -> list[str]:
    """Drive the REAL consumer — this is the whole point of the file."""
    context = ReActContext(
        agent_name="trinity", conversation=[Message(role="user", content=text)]
    )
    context = await ProtocolStack({}, "trinity").pre_process(context)
    return [
        e for e in (context.metadata.get("protocol_enrichments") or [])
        if e.startswith("[Intent")
    ]


def test_the_inventory_is_what_the_measurement_found():
    """16 entries, and the `unavailable` set is EXACTLY the no-`action_name`
    set. If they ever diverge, one of the two halves of the idiom was applied
    without the other."""
    missing_name = {a for a, g in INTENT_ACTION_MAP.items() if "action_name" not in g}

    assert len(UNAVAILABLE) == 16
    assert set(UNAVAILABLE) == missing_name



# ── Branch-owned markers: text NO guide field contains ───────────────────
#
# CONFIRMED VACUOUS BEFORE REPAIR. Asserting `"NOT AVAILABLE" in enrichment`
# passed even with "NOT AVAILABLE" stripped from the branch template, because
# every guide's own description contains the phrase. The test was reading the
# INPUT it fed in, not the OUTPUT the branch produced — wrong-object, verified by
# mutation: 129/129 still green with the branch text removed.
#
# These three strings live only in ProtocolStack.pre_process, so an assertion on
# them cannot be satisfied by the data.
TOP_BRANCH = "The user is asking for a capability that is NOT AVAILABLE"
TOP_GUARD = "Do not attempt this action and do not imply it succeeded"
ALT_BRANCH = "[Intent Alt] Also possible, but NOT AVAILABLE"


def _branch_markers_appear_in_no_guide_field() -> bool:
    for guide in INTENT_ACTION_MAP.values():
        for value in guide.values():
            if isinstance(value, str) and (
                TOP_BRANCH in value or TOP_GUARD in value or ALT_BRANCH in value
            ):
                return False
    return True


def test_the_branch_markers_are_not_present_in_the_data():
    """GUARD THE GUARD. If a description ever contains the branch's own wording,
    every assertion below silently becomes vacuous again."""
    assert _branch_markers_appear_in_no_guide_field()


@pytest.mark.parametrize("action", UNAVAILABLE)
async def test_every_unavailable_capability_actually_reaches_the_user(action):
    """THE LOAD-BEARING TEST, now asserting on what the BRANCH emits.

    RIGHT-ANSWER-WRONG-BRANCH, also confirmed: `payroll_run` loses its own top
    keyword to the working `send_payment`, so it reaches the user through the ALT
    branch. The previous version asserted the top-branch outcome for it and
    passed anyway — via a substring the alt branch happened to share. Which
    branch ran is now established first, and each gets the assertion that
    belongs to it.
    """
    from runtime.chat.intent_actions import match_intent

    guide = INTENT_ACTION_MAP[action]
    probe = guide["keywords"][0]
    enrichments = await _intent_enrichments(probe)
    joined = "\n".join(enrichments)

    assert enrichments, (
        f"{action}: the request matched but NOTHING reached the model — the "
        "follow_up is unreachable again"
    )

    matches = match_intent(probe)
    is_top = matches and _name_of(matches[0]) == action

    if is_top:
        assert TOP_BRANCH in joined, (
            f"{action} is the top match but the unavailable branch did not run"
        )
        assert TOP_GUARD in joined, (
            f"{action}: the anti-fabrication instruction is missing — the model "
            "is told the capability is unavailable but not that it must refrain"
        )
    else:
        assert ALT_BRANCH in joined, (
            f"{action} is not the top match for {probe!r}, so it must reach the "
            f"user through the alt branch, and did not: {enrichments}"
        )


@pytest.mark.parametrize("action", UNAVAILABLE)
def test_every_unavailable_capability_has_something_honest_to_say(action):
    """A follow_up is the deliverable. An entry without one would produce an
    enrichment that names a problem and offers the user nothing."""
    assert INTENT_ACTION_MAP[action].get("follow_up"), (
        f"{action} has no follow_up — there is nothing for Trinity to say"
    )


@pytest.mark.parametrize("action", UNAVAILABLE)
async def test_the_follow_up_text_itself_is_delivered(action):
    """Not merely 'an unavailable notice' — THE string the guide carries. A
    generic notice would satisfy the test above while dropping the specific,
    verified wording each domain wrote."""
    from runtime.chat.intent_actions import match_intent

    guide = INTENT_ACTION_MAP[action]
    probe = guide["keywords"][0]
    matches = match_intent(probe)
    joined = "\n".join(await _intent_enrichments(probe))

    # KEYWORD COLLISION IS NOT A DEFECT. `payroll` scores higher for the real
    # `send_payment` than for `payroll_run`, so payroll_run is the RUNNER-UP and
    # the alt line carries its description rather than its follow_up. Asserting
    # verbatim delivery there would be asserting on the wrong branch — the
    # right-answer-wrong-branch trap, in reverse. Which branch ran is checked
    # first, and each branch gets the assertion that belongs to it.
    top_is_this_entry = matches and matches[0].get("description") == guide["description"]

    if top_is_this_entry:
        assert guide["follow_up"] in joined, (
            f"{action}: it is the top match, so its follow_up must be delivered "
            "verbatim"
        )
    else:
        assert "NOT AVAILABLE" in joined, (
            f"{action}: it is not the top match for {probe!r}, but the user "
            "must still be told it is unavailable"
        )


# ── The bounded blast radius, pinned in both directions ──────────────────


async def test_an_unrecognised_message_still_produces_nothing():
    """CONTROL AGAINST OVER-FIRING. The repair must not start narrating intent
    for messages that match no capability at all."""
    assert await _intent_enrichments("xyzzy plugh frobnicate") == []


async def test_a_working_action_is_unaffected():
    """CONTROL. The available path is untouched — it still names the action and
    its confidence, and it must not acquire a NOT AVAILABLE notice."""
    enrichments = await _intent_enrichments("I want to send a payment")

    assert len(enrichments) >= 1
    assert any("likely wants: send_payment" in e for e in enrichments)
    assert not any("NOT AVAILABLE" in e for e in enrichments[:1])


async def test_an_unavailable_runner_up_no_longer_costs_the_alt_line():
    """THE SECOND-ORDER CASE, re-measured after the repair.

    Before: a close unavailable runner-up raised on `alt['action_name']`, so the
    `[Intent Alt]` line was lost — though the top's line survived, having been
    appended first. That bound the damage, and the bound is asserted here rather
    than assumed.
    """
    enrichments = await _intent_enrichments("send funds from the dao treasury")

    assert len(enrichments) == 2, (
        f"expected the top match AND the alt line, got {len(enrichments)}"
    )
    assert "likely wants: send_payment" in enrichments[0]
    assert "[Intent Alt]" in enrichments[1]
    assert "NOT AVAILABLE" in enrichments[1]


# ── The claims inside the sixteen strings ────────────────────────────────


def test_the_treasury_follow_up_does_not_deny_an_executor_that_exists():
    """FINDING 3, CAUGHT A SECOND TIME BY THE PRE-REPOINT READ.

    The first version of this string said "there's no execution path to move
    treasury funds". FALSE: contracts/MatrixDAO.sol declares
    `treasuryWithdraw(address,uint256)`. The narrow claim — the PLATFORM has no
    wired path to it — is true and grepped: no Python caller exists.

    This was written into a `follow_up` that had never been spoken, so nobody
    would have caught it by using the product. The read-before-arming gate did.
    """
    import pathlib

    text = INTENT_ACTION_MAP["treasury_transfer"]["follow_up"].lower()
    assert "no execution path" not in text

    root = pathlib.Path(__file__).resolve().parent.parent
    solidity = (root / "contracts" / "MatrixDAO.sol").read_text()
    assert "function treasuryWithdraw(" in solidity, (
        "the contract function this string is careful about no longer exists — "
        "the wording should be revisited rather than left"
    )

    # AST, NOT RAW TEXT — the standing rule, and it bit immediately: a raw
    # grep matched the explanatory comment written directly above this string,
    # reporting the platform as a caller of the thing the comment says it does
    # not call. Attribute access is what a real caller looks like.
    import ast

    python_callers = []
    for path in (root / "runtime").rglob("*.py"):
        try:
            tree = ast.parse(path.read_text())
        except SyntaxError:
            continue
        for node in ast.walk(tree):
            if isinstance(node, ast.Attribute) and node.attr == "treasuryWithdraw":
                python_callers.append(str(path.relative_to(root)))
    assert not python_callers, (
        f"the platform now DOES call treasuryWithdraw ({python_callers}) — the "
        "follow_up's narrow claim has become false"
    )


def test_no_unavailable_string_asserts_a_bare_platform_wide_negative():
    """THE STANDING RULE, mechanised for these sixteen strings.

    A negative claim in user-facing text is a measurement. Two of the sixteen
    carried one that did not survive a grep — mine about treasury execution, and
    a pre-existing one asserting no TEE/MPC/FHE implementation exists on the
    platform when an MPCService is registered.

    This does not ban negatives — it bans the UNSCOPED form. "there is no X in
    this platform" must instead say which capability, or which layer, lacks it.
    """
    # THIS GUARD FAILED TWICE ON ITS FIRST OUTING, and both failures are the
    # same mistake in different clothes.
    #
    #   (1) IT SCANNED THE WRONG FIELD. It read `follow_up` only — while the
    #       repair it shipped alongside had just started rendering
    #       `description` verbatim to the model. The corrected claim and the
    #       uncorrected one were delivered side by side in a single enrichment,
    #       and the guard inspected only the corrected half.
    #   (2) ITS PHRASE LIST WAS TOO LITERAL. "no execution path" does not
    #       substring-match "no treasury execution path exists". A banned-phrase
    #       list matched against prose will always be one wording behind.
    #
    # Both fixes below, and the stronger assertion is the one after this test:
    # scan what is RENDERED, not the fields it is assembled from.
    banned = (
        "execution path exists",
        "no execution path",
        "there is no executor",
        "implementation on the platform",
        "nothing executes",
        "anywhere in this repo",
    )
    offenders = []
    for action in UNAVAILABLE:
        guide = INTENT_ACTION_MAP[action]
        for field in ("description", "follow_up"):
            text = (guide.get(field) or "").lower()
            for phrase in banned:
                if phrase in text:
                    offenders.append(f"{action}.{field}: {phrase!r}")

    assert not offenders, (
        "unscoped platform-wide negative(s) in user-facing text — each needs a "
        f"grep or a narrower claim: {offenders}"
    )


@pytest.mark.parametrize("action", UNAVAILABLE)
async def test_the_rendered_text_carries_no_unscoped_negative(action):
    """THE STRONGER FORM, and the lesson from the guard above failing.

    Guarding the FIELDS is guarding the inputs. What reaches the user is the
    assembled enrichment, and the previous version of this control inspected one
    of the two fields that assembly draws from — the one that had already been
    corrected. So this asserts on the RENDERED output, which cannot be scoped to
    the wrong field because it is not scoped to a field at all.
    """
    banned = (
        "execution path exists",
        "no execution path",
        "there is no executor",
        "implementation on the platform",
        "nothing executes",
        "anywhere in this repo",
    )
    rendered = "\n".join(
        await _intent_enrichments(INTENT_ACTION_MAP[action]["keywords"][0])
    ).lower()

    hits = [p for p in banned if p in rendered]
    assert not hits, (
        f"{action}: the text actually delivered to the model asserts an "
        f"unscoped platform-wide negative: {hits}"
    )


# ── DISCLOSURE: the rendered text must not teach the exploit ─────────────
#
# SEVERITY NOTE, kept because it decides the fix order. Eleven of the sixteen
# descriptions leak internal issue IDs and defect post-mortems, which is untidy.
# TWO of them leaked a METHOD: authorize_payment's said "anyone holding an id
# could authorize a spend against another agent's budget", and refund_payment's
# added that it "silently restore[s] that agent's spend headroom" — the effect an
# attacker would want, named. authorize_payment's FOLLOW_UP carried it too
# ("it accepted a payment id from anyone"), which is worse than the description,
# because follow_up is the one field the model is told to say out loud.
#
# These are shipped ahead of the general rule for the same reason a live money
# path jumps its queue: the other eleven cost embarrassment, these two cost a
# user a working recipe.
#
# NOT INTRODUCED BY THE REPAIR. All sixteen strings predate it. What 9eb5c06 did
# was make them REACHABLE — the purest form of the pre-repoint hazard: the text
# was wrong for as long as it existed, and arming the path turned latent
# wrongness into live disclosure without a single character of it changing.

DISCLOSURE_SHAPES = (
    # An attacker-usable statement of who could do what, not a boundary.
    "anyone holding", "anyone with an id", "from anyone", "could authorize",
    "could refund", "spend headroom", "another agent's budget",
    "another agent's payment",
)


@pytest.mark.parametrize("action", ["authorize_payment", "refund_payment"])
async def test_a_security_hold_does_not_describe_the_hole_it_is_holding(action):
    """RENDERED OUTPUT, not fields — the lesson from the last guard being scoped
    to the one field that had already been fixed.

    A security disable must state the BOUNDARY ("this is on hold until callers
    can be verified") and never the METHOD ("it accepted an id from anyone").
    The first is what a user needs; the second is what an attacker needs.
    """
    rendered = "\n".join(
        await _intent_enrichments(INTENT_ACTION_MAP[action]["keywords"][0])
    ).lower()

    hits = [s for s in DISCLOSURE_SHAPES if s in rendered]
    assert not hits, (
        f"{action}: the text delivered to the model describes the exploitable "
        f"pattern rather than the capability boundary: {hits}"
    )


@pytest.mark.parametrize("action", ["authorize_payment", "refund_payment"])
def test_neither_field_carries_it_either(action):
    """BELT AND BRACES, and deliberately at the field layer too.

    The rendered check above is the primary control; this one exists because
    these two strings are a DISCLOSURE rather than a tidiness problem, and a
    field that is not currently rendered can become rendered — which is exactly
    how all sixteen of these became model-facing in the first place.
    """
    guide = INTENT_ACTION_MAP[action]
    for field in ("description", "follow_up"):
        text = (guide.get(field) or "").lower()
        hits = [s for s in DISCLOSURE_SHAPES if s in text]
        assert not hits, f"{action}.{field} carries {hits}"


@pytest.mark.parametrize("action", ["authorize_payment", "refund_payment"])
async def test_the_user_is_still_told_it_is_a_deliberate_hold(action):
    """THE OTHER DIRECTION. Sanitising must not turn a security hold into a
    vague "unavailable" — a user who is told nothing assumes it is broken and
    retries. The honest boundary survives; only the method is gone."""
    rendered = "\n".join(
        await _intent_enrichments(INTENT_ACTION_MAP[action]["keywords"][0])
    ).lower()

    assert "not available" in rendered
    assert "identity" in rendered or "who is asking" in rendered or "entitled" in rendered, (
        f"{action}: the lifting condition was lost along with the exploit"
    )


def test_the_defect_history_survives_beside_the_code():
    """MOVED, NOT DROPPED. The post-mortems are the protection against
    re-introduction — three fixes this engagement were undone or nearly undone
    because their reason lived only in commit history, which nobody greps before
    restoring a capability. The text must be adjacent to the entry it guards."""
    import pathlib

    import re

    source = (
        pathlib.Path(__file__).resolve().parent.parent
        / "runtime" / "chat" / "intent_actions.py"
    ).read_text()
    # The preserved text lives in a wrapped comment block, so the phrases are
    # split across lines and `#` prefixes. Normalise before matching — asserting
    # on raw source would fail for formatting reasons and read as "the history
    # was dropped", which is the opposite of what happened.
    flat = re.sub(r"\s*#\s*", " ", source)
    flat = re.sub(r"\s+", " ", flat).lower()

    assert "anyone holding an id could authorize a spend" in flat
    assert "silently restore that agent's spend headroom" in flat
    assert "do not re-enable authorize_payment" in flat


# ── The audit's own findings must not be part of the product ─────────────
#
# MEASURED: 14 of 16 descriptions carried internal issue IDs (NEW-38/48/48b/53/
# 57), past-tense defect post-mortems, or code symbols — and SEVEN follow_ups
# carried post-mortems too, found only by scanning every field rather than the
# one the finding named. Two of the sixteen were already clean and served as the
# worked examples for the rule.
#
# MY FIRST COUNT SAID 13 AND 3-CLEAN, AND IT WAS WRONG, in exactly the way this
# control is built to avoid: the pattern `NEW-\d+\b` does not match "NEW-48b",
# and my post-mortem list omitted "It returned". A phrase list decays; the next
# wording routes around it. Hence SHAPES below — an issue-ID regex that tolerates
# suffixes, backtick-quoted symbols, and past-tense construction — rather than a
# roster of sentences seen so far.
#
# THE CRITERION: a user-facing description states the CURRENT CAPABILITY
# BOUNDARY; the defect history belongs in the code comment beside it.

import re as _re

_ISSUE_ID = _re.compile(r"\b(?:NEW|RUN|P[0-3])-\d+[a-z]?\b", _re.I)
_SYMBOL = _re.compile(r"`[^`]+`|status=['\"]|\bACTION_MAP\b|\b\w+\.py\b|\b\w+\(\)")
_PAST_DEFECT = _re.compile(
    r"\b(?:the former handler|the previous one|it used to|this used to|used to "
    r"trigger|reported success|returned a random|returned status|it discarded|"
    r"never persisted|never touched|deleted nothing|it accepted)\b", _re.I,
)


@pytest.mark.parametrize("action", UNAVAILABLE)
async def test_the_rendered_notice_contains_no_audit_internals(action):
    """RENDERED OUTPUT, SHAPE-BASED. Drives the renderer and inspects the final
    string, so it cannot be scoped to the wrong field — which is how the previous
    version of this control missed a live disclosure."""
    rendered = "\n".join(
        await _intent_enrichments(INTENT_ACTION_MAP[action]["keywords"][0])
    )

    problems = []
    if m := _ISSUE_ID.search(rendered):
        problems.append(f"internal issue id {m.group(0)!r}")
    if m := _SYMBOL.search(rendered):
        problems.append(f"code symbol {m.group(0)!r}")
    if m := _PAST_DEFECT.search(rendered):
        problems.append(f"past-tense defect description {m.group(0)!r}")

    assert not problems, (
        f"{action}: the text delivered to the model leaks audit internals "
        f"({'; '.join(problems)}). A description states the capability boundary; "
        "the defect history belongs in the code comment beside it."
    )


@pytest.mark.parametrize("action", UNAVAILABLE)
def test_no_field_carries_audit_internals_either(action):
    """EVERY FIELD, not the one a finding happened to name.

    The surface rule, learned the hard way: a reported disclosure named two
    descriptions; the same exploit was also sitting in a follow_up, which is the
    field the model is told to RELAY. When a finding names a field, check every
    field that renders to the same surface.
    """
    guide = INTENT_ACTION_MAP[action]
    offenders = []
    for field, value in guide.items():
        if not isinstance(value, str):
            continue
        for label, pattern in (("issue id", _ISSUE_ID), ("symbol", _SYMBOL),
                               ("past-defect", _PAST_DEFECT)):
            if m := pattern.search(value):
                offenders.append(f"{field}: {label} {m.group(0)!r}")

    assert not offenders, f"{action} — {offenders}"


@pytest.mark.parametrize("action", UNAVAILABLE)
def test_the_defect_history_moved_rather_than_vanished(action):
    """MOVED, NOT DROPPED — and this is the assertion that makes the whole
    cleanup safe to do at scale.

    The post-mortems are the protection against re-introduction: three fixes this
    engagement were undone or nearly undone because the reason lived only in
    commit history, which nobody greps before restoring a capability. Each entry
    must still carry, in the source beside it, both the history and an explicit
    bar for putting the capability back.

    Whitespace-normalised before matching: the preserved text lives in a wrapped
    comment, and asserting against raw source produced a FALSE NEGATIVE reading
    "the history was dropped" when it was intact — the failure mode that gets a
    correct fix reverted by someone restoring what is already there.
    """
    import pathlib

    source = (
        pathlib.Path(__file__).resolve().parent.parent
        / "runtime" / "chat" / "intent_actions.py"
    ).read_text()
    entry_start = source.index(f'"{action}": {{')
    entry = source[entry_start:source.index("\n    },", entry_start)]
    flat = _re.sub(r"\s*#\s*", " ", entry)
    flat = _re.sub(r"\s+", " ", flat).lower()

    assert "defect history" in flat, (
        f"{action}: no preserved history beside the entry — if this capability "
        "is restored, nothing tells the next person what it used to do"
    )
    assert "re-enable bar:" in flat, (
        f"{action}: history kept but no explicit bar for putting it back. "
        "Silence reads as 'nobody thought about it'."
    )



# ── A claim about the platform is a claim about THIS deployment ──────────
#
# Existence is not the test; configuration is. Driven under the shipped config
# ({} — what a fresh install has), not a test config:
#
#   private_vote        "the ordinary governance vote, which is real"
#                       -> governance.vote returns a real weighted vote record. TRUE.
#   query_attestations  "I can verify it on-chain, which is real"
#                       -> "Missing EAS config: rpc_url, eas_contract, ...". FALSE.
#   confidential_compute "Ordinary compute jobs do reach a real provider"
#                       -> status "not_deployed". FALSE.
#   arweave_store       "... IF YOU HAVE STORAGE CREDENTIALS CONFIGURED"
#                       -> not_deployed + credential-gated. TRUE — it named its
#                          condition, and is the model the other two now follow.
#
# Same shape as available=False not meaning unreachable, one layer up: the
# capability exists and the user still cannot have it.

@pytest.mark.parametrize("action", ["query_attestations", "confidential_compute",
                                    "arweave_store"])
def test_a_conditional_offer_names_its_condition(action):
    """An offer that only holds under some configuration must say so. Without
    the condition it is a promise a fresh deployment cannot keep."""
    text = INTENT_ACTION_MAP[action]["follow_up"].lower()

    # THE MARKER MUST NAME THE DEPLOYMENT, NOT ANY CONDITION.
    #
    # The first version of this list included "if you have", and
    # query_attestations FALSE-PASSED on it: its old text read "If you have a
    # specific attestation UID I can verify it on-chain, which is real" — the
    # conditional qualifies the UID the USER supplies, not the configuration the
    # DEPLOYMENT lacks. Right word, wrong object, and the proof-of-failure run
    # exposed it by showing one failure where two were expected.
    assert any(marker in text for marker in
               ("this deployment", "configured", "deployed", "configuration")), (
        f"{action}'s follow_up offers an alternative without naming the "
        "DEPLOYMENT condition it depends on — a conditional about what the user "
        "supplies is not a conditional about what the install has"
    )


async def test_the_governance_vote_alternative_really_works():
    """The one unconditional offer of the four, so it is the one that must be
    driven rather than trusted."""
    from runtime.blockchain.services.registry import ServiceRegistry

    governance = ServiceRegistry({}).get("governance")
    proposal = await governance.create_proposal(
        "0xp", "T", "d", "one_person_one_vote", ["yes", "no"])
    record = await governance.vote(proposal["proposal_id"], "0xa", "yes")

    assert record.get("vote_id") and record.get("effective_weight") is not None, (
        "private_vote's follow_up sends the user to the ordinary governance "
        f"vote as a real alternative, and it no longer works: {record}"
    )
