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
import re

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


# ── the LIVE fabrication: a security verdict with no failing input ─────────

class TestCredentialSubsystemWasTheater:
    """`credential_verify` was worse than `stealth_address`, for one reason.

    Every other fabrication found in this phase sat behind a signature mismatch
    that errored the call out before the fabrication could run — accidental
    safety. `did_identity.verify_credential`'s declared parameters MATCHED, so
    it was never in the NEW-13 broken set and was live and callable all along.
    It returned `{"valid": True, "status": "verified"}` for any string:
    no vault lookup, no expiry check, no revocation check, no proof comparison.
    THERE WAS NO INPUT THAT COULD FAIL IT.

    `issue_credential` was the other half — same signature as the vault's real
    issuer, but writing a proofless record straight into the vault's private
    dict. Together they were a complete fake credential system: issue something
    unverifiable, verify something unissued, nothing real in between.

    The load-bearing property of these tests is the inverse of the bug: SOME
    INPUT MUST FAIL.
    """

    def _service(self):
        import sys

        sys.path.insert(0, "tests")
        from test_route_sweep import SWEEP_CONFIG

        from runtime.blockchain.services.did_identity.service import DIDService

        return DIDService(SWEEP_CONFIG)

    async def test_a_credential_that_was_never_issued_does_not_verify(self):
        """The single most important assertion: an input that fails."""
        result = await self._service().verify_credential("vc_never_issued_anywhere")
        assert result.get("valid") is False, (
            f"a credential that does not exist verified as valid: {result}"
        )

    async def test_a_revoked_credential_does_not_verify(self):
        svc = self._service()
        issued = await svc.issue_credential(
            issuer_did="did:key:issuer", subject_did="did:key:subject",
            credential_type="TestCredential", claims={"role": "admin"},
        )
        cred_id = issued["id"]
        assert (await svc.verify_credential(cred_id))["valid"] is True, (
            "a freshly issued credential must verify — fail-closed must not "
            "become fail-always"
        )

        await svc.credential_vault.revoke_credential(cred_id)
        after = await svc.verify_credential(cred_id)
        assert after.get("valid") is False, f"a REVOKED credential verified: {after}"

    async def test_issuance_produces_a_credential_the_real_verifier_accepts(self):
        """The shadow broke the real verifier for anything it wrote: that code
        reads `stored["proof"]["proofValue"]`, which KeyErrors on the proofless
        records the fake issuer created."""
        svc = self._service()
        issued = await svc.issue_credential(
            issuer_did="did:key:issuer", subject_did="did:key:subject",
            credential_type="TestCredential", claims={"role": "admin"},
        )
        assert issued.get("proof", {}).get("proofValue"), (
            f"issued credential carries no proof: {issued}"
        )
        assert "@context" in issued and "VerifiableCredential" in issued.get("type", [])

    async def test_issuance_is_visible_to_the_holder_index(self):
        """The fake wrote past `_holder_index`, so `list_credentials` would
        never return what it issued."""
        svc = self._service()
        issued = await svc.issue_credential(
            issuer_did="did:key:issuer", subject_did="did:key:holder",
            credential_type="TestCredential", claims={"role": "member"},
        )
        listed = await svc.credential_vault.list_credentials("did:key:holder")
        ids = [c["id"] if isinstance(c, dict) else c for c in listed]
        assert issued["id"] in ids, f"issued credential is invisible: {listed}"

    async def test_selective_disclosure_produces_a_real_commitment(self):
        """The third shadow, delegated rather than removed.

        It returned `"status": "disclosed"` with the field names echoed and NO
        PROOF. The real `SelectiveDisclosure` was in the same package, already
        instantiated, replacing undisclosed values with salted sha256
        commitments — and documenting that its store is "populated externally by
        DIDService", the wiring the shadow stood in for and never did.

        An earlier version of this test asserted only that the undisclosed value
        was absent, which the shadow ALSO satisfied (it echoed field names and
        never touched the credential). It passed against the bug. These
        assertions are on the structure the real implementation produces and
        the shadow cannot.
        """
        svc = self._service()
        issued = await svc.issue_credential(
            issuer_did="did:key:issuer", subject_did="did:key:holder",
            credential_type="TestCredential",
            claims={"age": 30, "salary": 100000},
        )
        vp = await svc.selective_disclose(
            did="did:key:holder", credential_id=issued["id"], fields=["age"],
        )

        assert "VerifiablePresentation" in vp.get("type", []), (
            f"not a verifiable presentation: {vp}"
        )
        assert vp.get("proof"), "presentation carries no proof"

        subject = vp["verifiableCredential"][0]["credentialSubject"]
        assert subject.get("age") == 30, "the disclosed field is missing"
        assert "salary" not in subject, "an undisclosed field was revealed"

        commitments = vp["verifiableCredential"][0]["_undisclosedCommitments"]
        assert re.fullmatch(r"[0-9a-f]{64}", commitments["salary"]), (
            f"undisclosed field has no sha256 commitment: {commitments}"
        )

    async def test_selective_disclosure_rejects_an_unknown_credential(self):
        """Some input must fail here too."""
        result = await self._service().selective_disclose(
            did="did:key:holder", credential_id="vc_nonexistent", fields=["age"],
        )
        assert result.get("status") == "error", f"unknown credential accepted: {result}"
