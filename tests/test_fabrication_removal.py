"""Phase 3.5 — fabrications are REMOVED, never repaired into working.

A fabrication is a method that returns a plausible-looking result without
performing the operation. When one sits behind an action whose declared
parameters do not match its signature, the mismatch is the only thing stopping
it from running — and "fixing the spec" converts a dead endpoint into a live
lie. In this codebase that is not hypothetical:

  `stealth_address` returned `f"0x{uuid.uuid4().hex[:40]}"` — a random string
  shaped like an Ethereum address, documented against ERC-5564, with no key
  derivation anywhere. No private key for that address exists or can be
  reconstructed, so funds sent there are not at risk, they are DESTROYED. The
  NEW-13 classification filed it as `fix-the-spec`: rename `base_address` to
  `owner`. That one-word "fix" would have shipped a working funds-destroyer.

A signature bug in front of a fabrication is load-bearing safety. These tests
pin the removals so no future tidy-up can restore the surface.
"""

from __future__ import annotations

import json
import pathlib

import pytest

ROOT = pathlib.Path(__file__).resolve().parents[1]

# Actions confirmed as fabrications and removed rather than repaired.
REMOVED_FABRICATIONS = ["stealth_address"]


@pytest.mark.parametrize("action", REMOVED_FABRICATIONS)
def test_action_is_absent_from_every_routing_surface(action):
    """Removal has to be total. An action left in ANY of these can still be
    reached, and a partial removal is the worst outcome — the capability looks
    retired while one path still answers."""
    from runtime.blockchain.services.service_dispatcher import (
        ACTION_MAP, ACTION_TO_FEED_EVENT, _STATE_MODIFYING_ACTIONS)
    from runtime.capabilities.catalog import CAPABILITIES
    from runtime.chat.intent_actions import INTENT_ACTION_MAP

    assert action not in ACTION_MAP, "still routable via platform_action"
    assert action not in _STATE_MODIFYING_ACTIONS
    assert action not in ACTION_TO_FEED_EVENT
    assert action not in INTENT_ACTION_MAP, "the model is still told this action exists"
    assert not [c for c in CAPABILITIES if c.get("id") == action], (
        "still advertised in the capability catalog"
    )


def test_the_stealth_address_method_is_gone():
    """The fabrication itself, not just its routing."""
    from runtime.blockchain.services.privacy.service import PrivacyService

    assert not hasattr(PrivacyService, "generate_stealth_address"), (
        "the method that minted unspendable addresses is still callable"
    )


def test_the_stealth_address_route_is_gone():
    import sys

    sys.path.insert(0, "tests")
    from test_route_sweep import SWEEP_CONFIG

    from gateway.server import GatewayServer

    app = GatewayServer(SWEEP_CONFIG).create_app()
    paths = {getattr(r, "canonical", "") for r in app.router.resources()}
    assert "/api/v1/privacy/stealth-address" not in paths


async def test_requesting_a_stealth_address_is_refused_not_faked():
    """The behaviour that matters to a user.

    Before: a random address with `status: "generated"`, which Trinity's own
    scripted dialogue described as one where "only you can access funds sent to
    it". After: the platform does not recognise the action at all, and says so.
    What must never happen again is a 0x-shaped string coming back.
    """
    import sys

    sys.path.insert(0, "tests")
    from test_route_sweep import SWEEP_CONFIG

    from runtime.blockchain.services.service_dispatcher import ServiceDispatcher

    dispatcher = ServiceDispatcher(SWEEP_CONFIG)
    raw = await dispatcher.execute(action="stealth_address", params={"owner": "0xabc"})
    body = json.loads(raw) if isinstance(raw, str) else raw

    assert body.get("status") != "ok", f"the fabrication still answers: {body}"
    rendered = json.dumps(body)
    # (An earlier draft had a third assertion here ending in `or True` — a
    # vacuous check that could never fail. Removed rather than left in a file
    # whose whole subject is things that look verified and are not.)
    # The load-bearing assertion: no address-shaped value comes back.
    import re

    assert not re.search(r"0x[0-9a-f]{40}", rendered), (
        f"an address-shaped value was returned for a removed capability: {rendered}"
    )


def test_trinity_is_no_longer_scripted_to_promise_recoverable_funds():
    """The lie was written into the agent's own example dialogue: "Share this
    with the sender — only you can access funds sent to it." """
    src = (ROOT / "runtime" / "chat" / "intent_actions.py").read_text()
    assert "only you can access funds sent to it" not in src
    assert "stealth address" not in src.lower()
