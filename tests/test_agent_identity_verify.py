"""Phase-1 M2: agent_identity verify checks the AGENT's own attestation, never
unrelated platform-wallet activity."""

import json

import pytest

from runtime.blockchain.agent_identity import AgentIdentity

CFG = {"blockchain": {"network": "base-sepolia"}}
UID = "0x" + "ab" * 32  # 66-char bytes32
WALLET = "0x" + "3c" * 20           # the platform wallet: the attester of its own registrations
SCHEMA = "0x" + "cd" * 32           # the platform's configured schema
LIVE = {"blockchain": {"network": "base-sepolia", "platform_wallet": WALLET, "eas_schema": SCHEMA}}


def _found(agent="neo", action="agent_registration", attester=WALLET, schema=SCHEMA):
    """An attestation as EASClient.verify reports one that exists and is not
    revoked, with the data _register writes: (platform, action, agent, time)."""
    from eth_abi import encode
    data = encode(["string", "string", "string", "uint256"], ["The Matrix", action, agent, 1])
    return {"verified": True, "exists": True, "revoked": False, "attester": attester,
            "schema": schema, "data": "0x" + data.hex()}


def _verify(svc, **params):
    import asyncio
    params.setdefault("action", "verify")
    return json.loads(asyncio.run(svc._verify(params)))


def test_unknown_agent_is_not_verified():
    svc = AgentIdentity(CFG)
    out = _verify(svc, agent_name="ghost")
    assert out["verified"] is False
    assert "no registration" in out["reason"].lower()


def test_unconfigured_lookup_is_not_verified(monkeypatch):
    svc = AgentIdentity(CFG)
    svc._registrations["neo"] = UID
    # EASClient.verify with no RPC configured returns an {error, hint} dict.
    async def fake_verify(self, uid):
        return {"uid": uid, "verified": False, "error": "no rpc", "hint": "configure"}
    monkeypatch.setattr("runtime.blockchain.eas_client.EASClient.verify", fake_verify)
    out = _verify(svc, agent_name="neo")
    assert out["verified"] is False
    assert "unconfigured" in out["reason"].lower()


def test_attested_agent_is_verified(monkeypatch):
    svc = AgentIdentity(LIVE)
    svc._registrations["neo"] = UID
    async def fake_verify(self, uid):
        return {"uid": uid, **_found("neo")}
    monkeypatch.setattr("runtime.blockchain.eas_client.EASClient.verify", fake_verify)
    out = _verify(svc, agent_name="neo")
    assert out["verified"] is True
    assert out["attestation_uid"] == UID
    assert out["verified_via"] == "eas:getAttestation"


def test_revoked_attestation_is_not_verified(monkeypatch):
    svc = AgentIdentity(CFG)
    async def fake_verify(self, uid):
        return {"uid": uid, "verified": False, "exists": True, "revoked": True}
    monkeypatch.setattr("runtime.blockchain.eas_client.EASClient.verify", fake_verify)
    out = _verify(svc, agent_name="neo", attestation_uid=UID)  # explicit uid path
    assert out["verified"] is False
    assert "revoked" in out["reason"].lower()


@pytest.mark.parametrize("written", ["Neo", " NEO ", "neo"])
def test_an_agent_registered_under_any_spelling_verifies_under_it(monkeypatch, written):
    """Registering and verifying key on one form of the name. Registration
    learned to lowercase the name (only the platform's own three are signed for)
    while verification still looked the name up as written, so registering "Neo"
    and verifying "Neo" found no registration — a working verification turned
    into a refusal. Fails wherever registration lowercases and verification does
    not; passes where neither does, and where both do."""
    import asyncio

    async def fake_attest(self, action, agent, details, recipient="0x" + "0" * 40):
        return {"status": "attested", "uid": UID}

    async def fake_verify(self, uid):
        return {"uid": uid, **_found("neo"), "verified": uid == UID}

    monkeypatch.setattr("runtime.blockchain.eas_client.EASClient.attest", fake_attest)
    monkeypatch.setattr("runtime.blockchain.eas_client.EASClient.verify", fake_verify)
    svc = AgentIdentity(LIVE)
    asyncio.run(svc.execute(action="register", agent_name=written))
    out = json.loads(asyncio.run(svc.execute(action="verify", agent_name=written)))
    assert out["verified"] is True, out
    assert out["attestation_uid"] == UID


def test_an_identity_read_under_any_spelling_is_that_agents():
    """A read keys on the same form: " Neo " is Neo, not an unknown agent with no
    role and no capabilities."""
    import asyncio
    out = json.loads(asyncio.run(AgentIdentity(CFG).execute(action="get_identity", agent_name=" Neo ")))
    assert out["agent"] == "neo" and out["role"] == "execution" and out["capabilities"], out


# ── an attestation that exists is not a registration ─────────────────────
#
# The uid is the caller's to write (the register-time cache is filled only when
# EASClient.attest returns a uid), and anybody can make an attestation on EAS,
# under any schema, saying anything. verify() checked only that the uid existed
# and was not revoked, so it answered "verified" for any agent the caller named,
# from an attestation the platform never made. At the commit "Every twin
# attestation is the platform's own statement: eas no longer signs or revokes
# on request, and each attestation's subject is the caller or nobody" the
# four [control] tests below fail; the [guard] passes before and after.

def _verify_with(monkeypatch, found, **params):
    import asyncio

    async def fake_verify(self, uid):
        return {"uid": uid, **found}

    monkeypatch.setattr("runtime.blockchain.eas_client.EASClient.verify", fake_verify)
    return json.loads(asyncio.run(AgentIdentity(LIVE).execute(
        action="verify", attestation_uid=UID, **params)))


def test_an_attestation_anybody_made_verifies_no_agent(monkeypatch):
    """[control] The review's reproduction: a stranger's attestation under an
    unrelated schema, presented for an agent the platform does not run."""
    out = _verify_with(monkeypatch, _found("smith", attester="0x" + "e7" * 20,
                                           schema="0x" + "99" * 32), agent_name="smith")
    assert out["verified"] is False, out
    assert "not made by the platform" in out["reason"]


def test_the_platforms_key_under_another_schema_is_not_a_registration(monkeypatch):
    """[control]"""
    out = _verify_with(monkeypatch, _found("neo", schema="0x" + "99" * 32), agent_name="neo")
    assert out["verified"] is False and "schema" in out["reason"], out


def test_one_agents_registration_does_not_verify_another(monkeypatch):
    """[control] Trinity's real registration, presented as Neo's."""
    out = _verify_with(monkeypatch, _found("trinity"), agent_name="neo")
    assert out["verified"] is False and "'neo'" in out["reason"], out


def test_a_platform_statement_that_is_not_a_registration_does_not_verify(monkeypatch):
    """[control] The platform's own record of something else, naming the agent."""
    out = _verify_with(monkeypatch, _found("neo", action="contract_deployed"), agent_name="neo")
    assert out["verified"] is False, out


def test_the_platforms_registration_of_this_agent_verifies(monkeypatch):
    """[guard]"""
    out = _verify_with(monkeypatch, _found("neo"), agent_name=" Neo ")
    assert out["verified"] is True and out["agent"] == "neo", out
