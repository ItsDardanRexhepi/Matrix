"""NEW-78/NEW-81 at the SEAM — the insurance claim route.

Source-level assertions live in test_insurance_claim_preconditions.py. This
file exercises the same two changes through the real aiohttp router, because
presence of a definition is not execution and reading a route table is not
serving one:

  NEW-81  /api/v1/insurance/claim/settle is GONE. Pre-fix it was registered in
          both tables and dispatched to `insurance.settle_claim` — a method
          that has never existed in this codebase. Verified at HEAD ae9ff80:

              POST {"claim_id": "c1", "settlement_amount": 999999}
              -> 404 {"error": "Method 'settle_claim' not found on 'insurance'"}

          WHY REMOVED RATHER THAN IMPLEMENTED. Look at the contract that dead
          route advertised: `claim_id` and `settlement_amount`. A developer
          "fixing" the 404 by writing the method the route asks for would be
          building a primitive where THE CALLER NAMES THE PAYOUT AMOUNT — the
          same shape as NEW-76, arrived at by trying to be helpful. The real
          settlement path (auto_settle_claim) derives the amount from the
          policy's own coverage and never accepts one. Deleting the route
          removes the invitation.

  NEW-78  /api/v1/insurance/claim binds the caller to the wallet the security
          middleware authenticated for THIS request. Pre-fix the handler
          forwarded a claimant-supplied `trigger_data` dict as the evidence a
          payout was decided on, and never asked who was calling at all.

WHY THE BODY-HOLDER FALLBACK IS NOT A HOLE THAT UNDOES THE FIX. When no
authenticated identity is present the handler falls back to `body["holder"]`,
which an attacker controls. That is the same dev-mode idiom as
_handle_governance_vote and it is deliberately NOT the security boundary —
authentication is, and it is enforced upstream by the security middleware.
The property this file pins is narrower and is the one the handler owns:
whenever an authenticated identity EXISTS, it wins, and a body that disagrees
cannot override it. A handler that preferred the body would let an
authenticated user claim as anyone.
"""

from __future__ import annotations

from pathlib import Path

import pytest
from aiohttp import web
from aiohttp.test_utils import TestClient, TestServer

from gateway.service_routes import ServiceRoutes

REPO = Path(__file__).resolve().parent.parent


@pytest.fixture
async def client():
    routes = ServiceRoutes(config={})
    app = web.Application()
    routes.register_routes(app)
    async with TestClient(TestServer(app)) as c:
        yield c


# ── NEW-81: the dead route ───────────────────────────────────────────────


async def test_the_settle_route_is_no_longer_served(client):
    """SCENARIO: a client that still calls the old endpoint.

    404 is the honest answer — the route dispatched to a method that never
    existed, so it never could have settled anything. Serving it was worse
    than not serving it: it advertised a capability that did not exist.
    """
    resp = await client.post(
        "/api/v1/insurance/claim/settle", json={"policy_id": "pol_x"}
    )
    assert resp.status == 404


async def test_removing_it_did_not_take_the_live_claim_route_with_it(client):
    """The removal was surgical. Both routes lived in both tables and share a
    prefix — a sloppy edit takes out the sibling. Anything but 404 proves the
    live route is still registered and reaching its handler."""
    resp = await client.post("/api/v1/insurance/claim", json={"policy_id": "x"})
    assert resp.status != 404, "the LIVE claim route was removed by accident"


# ── NEW-78: caller binding ───────────────────────────────────────────────


async def test_an_authenticated_identity_beats_a_body_supplied_holder(client, monkeypatch):
    """SCENARIO: authenticated mallory POSTs `holder: alice`.

    This is the escalation the ownership check would not catch on its own —
    assert_owner compares whatever the handler hands it, so if the handler
    preferred the body, an authenticated attacker would simply declare
    themselves the owner and pass. The handler's job is to hand it the
    authenticated identity.
    """
    # Patched at the SOURCE module, not at gateway.service_routes: the handler
    # imports this function-locally (matching _handle_governance_vote), so it
    # re-resolves from gateway.security_gate on every request. Patching the
    # importing module binds a name nothing reads, and the test would pass
    # while proving nothing — this is the same shape as the domain-4 control
    # that manufactured its own condition.
    import gateway.security_gate as sg

    monkeypatch.setattr(sg, "current_request_security", lambda: {"wallet": "mallory"})
    seen: dict = {}

    async def spy(service, method, **kwargs):
        seen.update(kwargs)
        return {"status": "denied"}

    monkeypatch.setattr(ServiceRoutes, "_call", staticmethod(spy))

    await client.post(
        "/api/v1/insurance/claim",
        json={"policy_id": "pol_x", "holder": "alice"},
    )

    assert seen.get("caller") == "mallory", (
        f"handler forwarded caller={seen.get('caller')!r} — a body-supplied "
        "holder overrode the authenticated identity"
    )


async def test_the_handler_forwards_no_claimant_supplied_evidence(client, monkeypatch):
    """SCENARIO: a client that keeps sending the old `trigger_data`.

    It must be dropped at the seam, not passed through for the service to
    ignore — a forwarded-but-unused parameter is how a future edit re-wires
    it. Asserted on what the handler ACTUALLY forwards, not on the signature.
    """
    seen: dict = {}

    async def spy(service, method, **kwargs):
        seen.update(kwargs)
        seen["__method"] = method
        return {"status": "denied"}

    monkeypatch.setattr(ServiceRoutes, "_call", staticmethod(spy))

    await client.post(
        "/api/v1/insurance/claim",
        json={
            "policy_id": "pol_x",
            "holder": "alice",
            "trigger_data": {"delay_minutes": 9999},
        },
    )

    assert seen["__method"] == "file_claim"
    assert set(seen) == {"policy_id", "caller", "__method"}, (
        f"handler forwarded unexpected keys: {sorted(set(seen))}"
    )
    assert "trigger_data" not in seen


async def test_policy_id_is_still_required(client):
    """A precondition the rewrite must not have dropped while moving code."""
    resp = await client.post("/api/v1/insurance/claim", json={"holder": "alice"})
    assert resp.status >= 400
