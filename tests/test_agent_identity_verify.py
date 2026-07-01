"""Phase-1 M2: agent_identity verify checks the AGENT's own attestation, never
unrelated platform-wallet activity."""

import json

import pytest

from runtime.blockchain.agent_identity import AgentIdentity

CFG = {"blockchain": {"network": "base-sepolia"}}
UID = "0x" + "ab" * 32  # 66-char bytes32


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
    svc = AgentIdentity(CFG)
    svc._registrations["neo"] = UID
    async def fake_verify(self, uid):
        return {"uid": uid, "verified": True, "exists": True, "revoked": False,
                "attester": "0xattester"}
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
