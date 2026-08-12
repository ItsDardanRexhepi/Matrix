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


@pytest.mark.parametrize("action", UNAVAILABLE)
async def test_every_unavailable_capability_actually_reaches_the_user(action):
    """THE LOAD-BEARING TEST. Before the repair every one of these delivered
    zero enrichments; the honest text existed in the guide and was unreachable."""
    guide = INTENT_ACTION_MAP[action]
    enrichments = await _intent_enrichments(guide["keywords"][0])

    assert enrichments, (
        f"{action}: the request matched but NOTHING reached the model — the "
        "follow_up is unreachable again"
    )
    assert any("NOT AVAILABLE" in e for e in enrichments), (
        f"{action}: an enrichment was produced but it does not tell the model "
        f"the capability is unavailable: {enrichments}"
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
    treasury funds". FALSE: contracts/OpenMatrixDAO.sol declares
    `treasuryWithdraw(address,uint256)`. The narrow claim — the PLATFORM has no
    wired path to it — is true and grepped: no Python caller exists.

    This was written into a `follow_up` that had never been spoken, so nobody
    would have caught it by using the product. The read-before-arming gate did.
    """
    import pathlib

    text = INTENT_ACTION_MAP["treasury_transfer"]["follow_up"].lower()
    assert "no execution path" not in text

    root = pathlib.Path(__file__).resolve().parent.parent
    solidity = (root / "contracts" / "OpenMatrixDAO.sol").read_text()
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

