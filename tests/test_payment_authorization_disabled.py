"""NEW-53 — unauthenticated money-state transitions are disabled.

This is a SECURITY disable, not an honesty fix. Everything else this audit has
disabled was a lie (a method claiming work it did not do). These two methods do
real work — the defect is that they do it for ANYONE who asks.

THE HOLE

    async def authorize_payment(self, payment_id: str)
    async def refund_payment(self, payment_id: str)

No owner, no signature, no caller identity. The paying agent is read from the
STORED PAYMENT, never from the caller, so the caller is never compared against
anything. Payment ids are handed out by create_payment / get_payment /
list_payments. Anyone reaching the dispatcher with an id could authorize a
spend against another agent's budget, or refund another agent's payment —
which also restores that agent's spend headroom, a free budget-reset.

WHY THE SECURITY GATE DOES NOT COVER IT — two independent reasons, both
asserted below so neither can quietly stop being true:

  1. ServiceDispatcher.execute never calls gate_action. Only 1 of the 4 entry
     points that reach it gates (gateway/bridge.py); capabilities/registry.py,
     agents/handoff.py and tools/dispatcher.py do not.
  2. Even the gated path would not help: gate_action is an action-TYPE policy
     check. It never asks "does this caller own payment X". Ownership
     verification does not exist anywhere in the codebase (NEW-54).

WHAT THIS FILE DOES NOT CLAIM

It does not prove the methods are safe — they are not, and they are still in
the file. It proves they are UNREACHABLE from every dispatch surface. The
methods are deliberately left in place: their expiry checks, state guards and
spend accounting are real work (real-local-defective), and they are the
starting point for the authenticated versions.
"""

from __future__ import annotations

import inspect
import json

import pytest

DISABLED = ["authorize_payment", "refund_payment"]


def _dispatch(raw: object) -> dict:
    """Parse ServiceDispatcher.execute's JSON-STRING envelope.

    Asserting on the raw return is vacuous — it is a str, so any dict-shaped
    check silently passes. This has bitten twice in this engagement.
    """
    assert isinstance(raw, str), (
        f"dispatcher.execute returned {type(raw).__name__}, expected a JSON "
        "string — the envelope shape changed and these assertions no longer "
        "look at what they think they do."
    )
    env = json.loads(raw)
    assert isinstance(env, dict)
    return env


# ── the disable, on every dispatch surface ─────────────────────────────────


@pytest.mark.parametrize("action", DISABLED)
def test_action_is_not_in_the_action_map(action):
    """ACTION_MAP is the choke point all four dispatch entry points share."""
    from runtime.blockchain.services.service_dispatcher import ACTION_MAP

    assert action not in ACTION_MAP, (
        f"{action} is still dispatchable — an unauthenticated money-state "
        "transition is reachable"
    )


@pytest.mark.parametrize("action", DISABLED)
def test_action_is_not_state_modifying_or_feed_emitting(action):
    from runtime.blockchain.services.service_dispatcher import (
        ACTION_TO_FEED_EVENT,
        _STATE_MODIFYING_ACTIONS,
    )

    assert action not in _STATE_MODIFYING_ACTIONS
    assert action not in ACTION_TO_FEED_EVENT


@pytest.mark.parametrize("action", DISABLED)
async def test_dispatching_the_action_fails(action):
    """Drive the dispatcher the way the tool surface does, and parse first."""
    from runtime.blockchain.services.service_dispatcher import ServiceDispatcher

    env = _dispatch(
        await ServiceDispatcher({}).execute(action=action, params={"payment_id": "pay_x"})
    )

    assert env["status"] == "error", f"{action} still executes: {env!r}"
    assert "unknown action" in env["error"].lower()


@pytest.mark.parametrize("action", DISABLED)
def test_the_model_is_not_told_the_action_works(action):
    from runtime.chat.intent_actions import INTENT_ACTION_MAP

    guide = INTENT_ACTION_MAP[action]
    assert guide.get("unavailable") is True
    assert "action_name" not in guide, "the model can still dispatch it"
    assert "NOT AVAILABLE" in guide["description"]
    assert guide["keywords"], "keywords dropped — the request now matches nothing"


@pytest.mark.parametrize("action", DISABLED)
def test_the_capability_is_not_advertised(action):
    from runtime.capabilities import catalog

    assert catalog.get_by_id(action) is None


@pytest.mark.parametrize("action", DISABLED)
def test_the_ios_registry_does_not_advertise_the_action(action):
    """extensions/registry.json is served live and UserDefaults-cached."""
    from pathlib import Path

    registry = json.loads(
        (Path(__file__).resolve().parents[1] / "extensions" / "registry.json").read_text()
    )
    components = registry["components"] if isinstance(registry, dict) else registry
    advertised = [
        c["id"] for c in components if action in (c.get("gateway_actions") or [])
    ]
    assert not advertised, f"still advertised by components: {advertised}"


@pytest.mark.parametrize("action", DISABLED)
def test_the_platform_action_tool_description_does_not_offer_it(action):
    """What the MODEL is told it can do, distinct from what it can route to."""
    from pathlib import Path

    from runtime.blockchain.services import service_dispatcher

    src = Path(inspect.getsourcefile(service_dispatcher)).read_text()
    start = src.index("PAYMENTS & TRANSFERS")
    block = src[start:start + 600]

    assert action not in block, (
        f"the platform_action tool description still lists {action} — the "
        "model would offer a disabled action and dead-end"
    )


# ── the methods survive, unreachable — and are still unauthenticated ───────


@pytest.mark.parametrize("method_name", DISABLED)
def test_the_method_still_exists_and_is_still_unauthenticated(method_name):
    """Deliberate: the disable is at the routing layer, not a deletion.

    This is the load-bearing negative. If someone "fixes" NEW-53 by adding an
    identity parameter, this test FAILS — which is the signal to re-enable the
    actions, not to weaken the test. It encodes the precondition for undoing
    the disable: the signature must gain a caller identity.
    """
    from runtime.blockchain.services.x402_payments.service import X402PaymentService

    method = getattr(X402PaymentService, method_name, None)
    assert method is not None, (
        f"{method_name} was deleted. The disable is meant to be at the routing "
        "layer — the method's expiry checks, state guards and spend accounting "
        "are real work and are the basis for the authenticated version."
    )

    params = set(inspect.signature(method).parameters) - {"self"}
    identity_params = params & {
        "caller", "caller_id", "caller_identity", "owner", "agent_id",
        "identity", "signature", "principal", "requester",
    }
    assert not identity_params, (
        f"{method_name} now accepts {sorted(identity_params)} — if ownership is "
        "genuinely verified against the payment's agent, NEW-53's disable can "
        "be lifted. Re-enable the action in ACTION_MAP and update this test; do "
        "not simply delete the assertion."
    )


def test_the_dispatcher_still_does_not_gate_which_is_why_this_disable_exists():
    """Pins reason 1: the dispatcher is an ungated path to every action.

    If this ever fails because the dispatcher gained a gate, that is good news
    and NEW-54 should be revisited — but the disable still stands until
    OWNERSHIP (not action-type policy) is checked.
    """
    from pathlib import Path

    from runtime.blockchain.services import service_dispatcher

    src = Path(inspect.getsourcefile(service_dispatcher)).read_text()
    code = "\n".join(
        ln for ln in src.splitlines() if not ln.lstrip().startswith("#")
    )
    assert "gate_action(" not in code, (
        "ServiceDispatcher now calls gate_action — revisit NEW-54. Note this "
        "alone does NOT justify re-enabling: gate_action checks action TYPE, "
        "never object ownership."
    )


def test_the_payment_path_has_no_ownership_check():
    """Pins reason 2 and NEW-54 — CORRECTED SCOPE.

    My first version of this test asserted that ownership verification "does
    not exist anywhere in the codebase". IT FAILED, on its first run, against
    `ip_royalties/ip_registry.py:130 verify_ownership(ip_id, claimant)` — a
    genuine check comparing `record["owner"] == claimant`. The absence claim
    was too strong, exactly the class of claim this engagement has been wrong
    about repeatedly. The test caught its own author.

    The accurate — and more useful — finding is narrower: ownership
    verification exists PER-SERVICE and AD-HOC, over each service's own
    records (ip_royalties, rwa_tokenization). There is no shared primitive and
    no enforcement at the seam, so whether a given object is protected depends
    on whether that service's author happened to write a check. x402_payments
    did not.

    So this asserts the thing that is actually true and actually matters: the
    payment service performs no ownership check on any of its state
    transitions.
    """
    from pathlib import Path

    from runtime.blockchain.services.x402_payments import service as x402

    src = Path(inspect.getsourcefile(x402)).read_text()
    code = "\n".join(
        ln for ln in src.splitlines() if not ln.lstrip().startswith("#")
    )

    ownership_signals = [
        "verify_ownership", "is_owner", "check_owner", "owner ==",
        "!= owner", "caller ==", "== caller",
    ]
    found = [sig for sig in ownership_signals if sig in code]

    assert not found, (
        f"x402_payments now contains ownership signals {found} — if the "
        "payment state transitions genuinely verify the caller owns the "
        "payment, NEW-53's disable can be lifted. Re-enable the actions in "
        "ACTION_MAP and update this test; do not just delete the assertion."
    )


def test_there_is_still_no_shared_ownership_primitive():
    """NEW-54: the systemic gap is the ABSENCE OF A SHARED one, not of any.

    Per-service checks exist (ip_royalties.verify_ownership,
    rwa_tokenization._find_owner). What does not exist is a primitive at the
    seam — somewhere in gateway/security_gate.py or runtime/security/ — that
    every state-modifying action could be made to pass through. Without one,
    every service re-implements ownership or silently skips it, which is how
    the payment rail ended up with none.
    """
    import subprocess
    from pathlib import Path

    root = Path(__file__).resolve().parents[1]
    hits = subprocess.run(
        ["grep", "-rn", "--include=*.py", "-E",
         r"def (verify|check|assert)_(owner|ownership)|def is_owner",
         str(root / "gateway"), str(root / "runtime" / "security")],
        capture_output=True, text=True,
    ).stdout.strip()

    assert not hits, (
        "A seam-level ownership primitive now exists:\n" + hits +
        "\nNEW-54 may be closable. Note the disable still stands until "
        "authorize_payment/refund_payment actually CALL it."
    )
