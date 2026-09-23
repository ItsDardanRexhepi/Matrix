"""Seventeen runtime-core sentences, each held to the code it describes.

Built true where the code could keep the promise:
  * badge ids — "atomically increment the sequence counter": two issuances
    queued on the write lock both read N and wrote N+1;
  * agent identity — "verified is derived only from the agent's own
    attestation": any live attestation UID verified any agent name;
  * EAS configuration — "only if EAS is fully configured": platform_wallet,
    which attest() sends from, was not checked;
  * the account manager — "only query ... on the connected chain": the chain
    was never compared, so one balance was reported for five chains;
  * IAP — "replaying the same signed transaction records NOTHING new": a
    replay rebound the lineage and revived an expired row; and "fail-closed
    means toward less entitlement": a refund that arrived before the row was
    dropped and the next verify entitled;
  * the SDK — "every verification failure maps to 401": a JWS header that is
    JSON but not an object answered 500.

Corrected where it could not: the blockchain package's "every state-changing
action is attested"; EAS's "permanent, verifiable record ... by whom"; the
Web3Manager "never raises"; config validation's "never starts with broken
config", "never from the committed config file", "never references the
owner-auth factors" and "must be usable"; the migration runner's "only runs
migrations whose version is greater"; and the plugin store's "only Enterprise
tier users can submit".
"""

from __future__ import annotations

import asyncio
import inspect
import json
import re

import pytest

from runtime.db.database import Database


def _prose(text: str) -> str:
    return re.sub(r"\s+", " ", re.sub(r"\s*#\s*", " ", text or ""))


# ── badge ids ──────────────────────────────────────────────────────────────

async def test_two_issuances_queued_on_the_lock_get_two_different_ids(tmp_path):
    from runtime.badges.badge_manager import BadgeManager

    db = Database({"database": {"path": str(tmp_path / "b.db")}})
    mgr = BadgeManager(db)
    await mgr.initialize()
    first = await mgr._next_badge_id(2026)

    lock = db._get_lock()
    await lock.acquire()           # another writer holds the lock
    a = asyncio.create_task(mgr._next_badge_id(2026))
    b = asyncio.create_task(mgr._next_badge_id(2026))
    await asyncio.sleep(0)
    await asyncio.sleep(0)
    lock.release()
    ids = await asyncio.gather(a, b)

    assert first == "GLASSWING-2026-0001"
    assert len(set(ids)) == 2, f"two badges were given the same id: {ids}"
    assert sorted(ids) == ["GLASSWING-2026-0002", "GLASSWING-2026-0003"]


# ── agent identity ─────────────────────────────────────────────────────────

SCHEMA = "0x" + "ab" * 32
WALLET = "0x" + "12" * 20


def _identity(monkeypatch, verify_result):
    from runtime.blockchain import eas_client
    from runtime.blockchain.agent_identity import AgentIdentity

    async def _verify(self, uid):
        return dict(verify_result, uid=uid)

    monkeypatch.setattr(eas_client.EASClient, "verify", _verify)
    return AgentIdentity({"blockchain": {"eas_schema": SCHEMA,
                                         "platform_wallet": WALLET}})


def _data(action: str, agent: str) -> str:
    from eth_abi import encode
    return "0x" + encode(["string", "string", "string", "uint256"],
                         ["The Matrix", action, agent, 1]).hex()


async def test_an_unrelated_live_attestation_does_not_verify_an_agent(monkeypatch):
    ident = _identity(monkeypatch, {
        "verified": True, "exists": True, "revoked": False,
        "schema": "0x" + "ff" * 32, "attester": "0x" + "99" * 20,
        "data": _data("something_else", "mallory")})
    out = json.loads(await ident.execute(action="verify", agent_name="neo",
                                         attestation_uid="0x" + "cd" * 32))
    assert out["verified"] is False, (
        "a live attestation under another schema, by another attester, "
        "verified the agent 'neo'")


async def test_another_agents_registration_does_not_verify_this_one(monkeypatch):
    ident = _identity(monkeypatch, {
        "verified": True, "exists": True, "revoked": False,
        "schema": SCHEMA, "attester": WALLET,
        "data": _data("agent_registration", "trinity")})
    out = json.loads(await ident.execute(action="verify", agent_name="neo",
                                         attestation_uid="0x" + "cd" * 32))
    assert out["verified"] is False and "trinity" in out["reason"]


async def test_the_agents_own_registration_still_verifies(monkeypatch):
    ident = _identity(monkeypatch, {
        "verified": True, "exists": True, "revoked": False,
        "schema": SCHEMA, "attester": WALLET.upper().replace("0X", "0x"),
        "data": _data("agent_registration", "neo")})
    out = json.loads(await ident.execute(action="verify", agent_name="neo",
                                         attestation_uid="0x" + "cd" * 32))
    assert out["verified"] is True


def test_the_identity_docstring_does_not_promise_verifiable_agent_actions():
    from runtime.blockchain import agent_identity

    doc = _prose(agent_identity.__doc__)
    assert "enabling verifiable agent actions" not in doc
    assert "not encoded" in doc


# ── EAS ────────────────────────────────────────────────────────────────────

def test_eas_is_not_configured_without_the_wallet_it_sends_from(monkeypatch):
    from runtime.blockchain import eas_client

    client = eas_client.EASClient({"blockchain": {
        "eas_contract": "0x" + "11" * 20, "eas_schema": SCHEMA,
        "paymaster_private_key": "0x" + "22" * 32, "platform_wallet": ""}})
    monkeypatch.setattr(client._manager, "available", True, raising=False)
    assert client._is_configured() is False


def test_the_eas_docstring_says_what_an_attestation_records():
    from runtime.blockchain import eas_client

    doc = _prose(eas_client.__doc__)
    assert "Every blockchain action in The Matrix is attested" not in doc
    assert "permanent, verifiable record of what was done" not in doc.replace(
        '("a permanent, verifiable record of what was done, by whom, and when")', "")
    assert "revocable" in doc and "NOT encoded" in doc


def test_the_blockchain_package_does_not_say_every_action_is_attested():
    import runtime.blockchain as pkg

    doc = _prose(pkg.__doc__)
    assert "Every state-changing action is attested via EAS" not in doc
    assert "Users never pay gas" not in doc


# ── account manager ────────────────────────────────────────────────────────

class _OneChain:
    available = True
    w3 = object()
    chain_id = 84532

    def get_balance_eth(self, wallet):
        return 1.0


async def test_one_connected_chain_is_not_reported_as_five():
    from runtime.blockchain.wallet_abstraction.account_manager import AccountManager

    mgr = AccountManager({"blockchain": {}})
    mgr._web3 = _OneChain()
    out = await mgr.get_all_balances("0x" + "a" * 40)
    assert out["chains"]["base"]["ETH"] == 1.0
    others = [out["chains"][c]["ETH"] for c in ("ethereum", "polygon", "arbitrum", "optimism")]
    assert others == [0.0, 0.0, 0.0, 0.0], (
        f"the base balance was reported for chains nobody queried: {out['chains']}")


# ── Web3Manager ────────────────────────────────────────────────────────────

def test_the_web3_manager_names_the_methods_that_raise():
    from runtime.blockchain import web3_manager

    doc = _prose(web3_manager.__doc__)
    assert "never raises an unhandled exception from public methods" not in doc.replace(
        '"never raises an unhandled exception from public methods"', "")
    for name in ("load_contract", "wait_for_receipt", "send_transaction",
                 "get_balance_eth"):
        assert name in doc


# ── config validation ──────────────────────────────────────────────────────

def test_the_validation_module_scopes_its_nevers_to_production():
    from runtime.config import validation

    doc = _prose(validation.__doc__)
    assert "The gateway must never start with obviously-broken config" not in doc
    assert "Outside production" in doc
    src = _prose(inspect.getsource(validation))
    assert "the public platform never references the owner-auth factors" not in src
    assert "at least one must be usable" not in src
    assert "at least one SHOULD be usable" in src


# ── migrations ─────────────────────────────────────────────────────────────

def test_a_lower_numbered_migration_added_later_still_runs(tmp_path, monkeypatch):
    """Pins the behaviour the corrected comment describes."""
    from runtime.db import database as dbmod

    path = str(tmp_path / "m.db")
    Database({"database": {"path": path}})           # applies every migration
    late = (0, "a migration numbered below the rest",
            ["CREATE TABLE IF NOT EXISTS late_arrival (x INTEGER)"])
    monkeypatch.setattr(dbmod, "MIGRATIONS", [late, *dbmod.MIGRATIONS])
    db = Database({"database": {"path": path}})
    tables = {r[0] for r in db._conn.execute(
        "SELECT name FROM sqlite_master WHERE type='table'").fetchall()}
    assert "late_arrival" in tables


def test_the_migration_comment_does_not_say_only_higher_versions_run():
    from runtime.db import database

    src = _prose(inspect.getsource(database))
    assert "only runs migrations whose version is greater than that" not in src


# ── plugin store ───────────────────────────────────────────────────────────

async def test_the_plugin_store_does_not_claim_a_tier_gate_or_a_review():
    from runtime.marketplace.plugin_store import PluginMarketplace

    doc = _prose(PluginMarketplace.submit_listing.__doc__)
    assert "Only Enterprise tier users can submit plugins." not in doc
    store = PluginMarketplace({}, None)
    out = await store.submit_listing("anyone", {"name": "p"})
    assert "You will be notified" not in out["message"]
    assert out["status"] == "submitted"
