"""An owner the platform recorded is compared with the caller in one spelling.

THE DEFECT. The platform names the caller in one spelling (runtime/auth/identity.py):
the session, the wallet bound for a gated HTTP action and the identity a tool is
dispatched with all carry a wallet address as `0x` and lower-case digits. The
owner a service recorded is often written by the client, as it spells it: an
insurance policy's `holder` comes from the request body. The ownership check
compared the two as exact strings. So a client that used its EIP-55 address
throughout, signing in and naming itself as holder, was told "Caller does not
own this policy" when it claimed on its own policy, where the same client passed
the check before the platform settled on one spelling.

THE RULE. Wherever the platform checks that a caller is the party a record
names, it compares the two in the one spelling (`same_caller`). A hex address in
any case, with 0x or 0X, is one wallet; anything else still compares exactly,
so two ids that differ only in case stay two callers.

THE CLASS, AND THE AXES CLOSED HERE
  (a) the shared ownership assertion (`assert_owner`: insurance claims and
      the other insurance owner checks)
  (b) the service checks with the same shape, each owner check a caller must
      pass: marketplace (cancel, and the buyer-is-not-the-seller refusal,
      appeals per seller), gaming (asset transfer), ip_royalties (transfer, and
      the registry's ownership verification), rwa_tokenization (transfer),
      p2p_lending (cancel, repay, and not borrowing from your own offer),
      supply_chain (custody transfer), x402 (spend-limit owner), messaging
      (not messaging yourself)
  (c) the checks that folded case with .lower(), which also merged ids that
      are not addresses: NFT rights and royalty configuration (who may change
      what they set) and the paymaster's body sender
  (d) the follow graph: the follower is the caller in the one spelling, and a
      followee or a queried address written in another spelling of the same
      wallet is the same wallet
  (e) /auth/nonce accepts a wallet address in any spelling /auth/verify
      accepts, 0X included
  (f) SCOPE PINS: a different wallet is still refused everywhere above, and
      ids that are not addresses still compare exactly

§CC, measured: against e0aea6b, with this file added, 19 failed and 2 passed,
on the no-op backend and with the core installed. The two that passed are the
scope pins for assert_owner and the marketplace. The nineteen failed on the
behaviour: each owner check refused its owner's other spelling, and each
self-dealing refusal (buying your own listing, borrowing from your own offer,
messaging yourself) let the same wallet through in another spelling; the
appeal limit counted one seller as two; the royalty and rights checks let
`apple:abc` change what `apple:AbC` set; the follow graph missed a followee
named in another spelling; the insurance claim answered 503 "Caller does not
own this policy" through the gateway; and /auth/nonce answered 400 to 0X and
200 to a value that is not hex. After the change, 21 passed on both backends.
"""

from __future__ import annotations

import sys
import time
from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest

sys.path.insert(0, "tests")

CHK = "0x5aAeb6053F3E94C9b9A09f33669435E7Ef1BeAed"     # an EIP-55 spelling
LOW = CHK.lower()
UP0X = "0X" + CHK[2:].upper()
OTHER = "0x" + "12" * 20


async def _outcome(coro):
    """The text of what a call answered or raised."""
    try:
        return str(await coro)
    except Exception as exc:  # noqa: BLE001
        return f"{type(exc).__name__}: {exc}"


# ── (a) the shared ownership assertion ────────────────────────────────────


@pytest.mark.parametrize("caller", [LOW, UP0X, "  " + CHK])
def test_assert_owner_takes_another_spelling_of_the_holder_as_the_holder(caller):
    from runtime.blockchain.services.ownership import assert_owner
    assert assert_owner(caller, {"holder": CHK}) == caller


def test_assert_owner_still_refuses_another_wallet_and_ids_that_differ_in_case():
    """(f) SCOPE PIN."""
    from runtime.blockchain.services.ownership import OwnershipError, assert_owner
    with pytest.raises(OwnershipError):
        assert_owner(OTHER, {"holder": CHK})
    with pytest.raises(OwnershipError):
        assert_owner("apple:abc", {"holder": "apple:AbC"})
    with pytest.raises(OwnershipError):
        assert_owner("", {"holder": CHK})


# ── (b) the service owner checks ──────────────────────────────────────────


def _listing(seller):
    return {"listing_id": "L1", "seller": seller, "status": "active", "price": 1.0,
            "item_type": "nft", "metadata": {"title": "t", "description": "d"},
            "created_at": 0}


async def test_marketplace_owner_checks_take_the_sellers_other_spellings():
    from runtime.blockchain.services.marketplace.service import MarketplaceService

    svc = MarketplaceService({})
    svc._listings["L1"] = _listing(CHK)
    out = await _outcome(svc.buy_item("L1", LOW))
    assert "Buyer cannot be the seller" in out, out
    out = await _outcome(svc.cancel_listing("L1", UP0X))
    assert "Only the seller" not in out and "cancelled" in out, out
    svc._listings["L2"] = {**_listing(CHK), "listing_id": "L2"}
    found = await svc.search({"seller": LOW})
    assert [x["listing_id"] for x in found] == ["L2"], found


async def test_marketplace_still_refuses_another_wallet():
    """(f) SCOPE PIN."""
    from runtime.blockchain.services.marketplace.service import MarketplaceService

    svc = MarketplaceService({})
    svc._listings["L1"] = _listing(CHK)
    assert "Only the seller" in await _outcome(svc.cancel_listing("L1", OTHER))


def test_marketplace_appeals_count_one_seller_whatever_the_spelling():
    from runtime.blockchain.services.marketplace.appeals import AppealProcess

    appeals = AppealProcess({})
    limit = appeals._max_appeals_per_listing
    appeals._appeals = {f"A{i}": {"listing_id": "L1", "seller": CHK} for i in range(limit)}
    import asyncio
    out = asyncio.run(_outcome(appeals.file_appeal("L1", LOW, "grounds long enough to count")))
    assert "Maximum" in out, out


async def test_gaming_transfer_takes_the_owners_other_spelling():
    from runtime.blockchain.services.gaming.service import GamingService

    svc = GamingService({})
    svc._assets["A1"] = {"asset_id": "A1", "owner": CHK, "transferable": True, "game_id": "g"}
    out = await _outcome(svc.transfer_asset("A1", LOW, OTHER))
    assert "is not owned by" not in out, out
    svc._assets["A2"] = {"asset_id": "A2", "owner": CHK, "transferable": True, "game_id": "g"}
    assert "is not owned by" in await _outcome(svc.transfer_asset("A2", OTHER, LOW))


async def test_ip_transfer_and_ownership_verification_take_the_owners_other_spelling():
    from runtime.blockchain.services.ip_royalties.ip_registry import IPRegistry
    from runtime.blockchain.services.ip_royalties.service import IPRoyaltyService

    svc = IPRoyaltyService({})
    record = {"ip_id": "ip1", "owner": CHK, "ip_type": "patent", "title": "t",
              "content_hash": "h", "registered_at": 0}
    svc._registry._registry["ip1"] = dict(record)
    out = await _outcome(svc.transfer_ip("ip1", UP0X, OTHER))
    assert "is not owned by" not in out, out

    registry = IPRegistry({})
    registry._registry["ip2"] = dict(record, ip_id="ip2")
    assert (await registry.verify_ownership("ip2", LOW))["verified"] is True
    assert (await registry.verify_ownership("ip2", OTHER))["verified"] is False
    assert [r["ip_id"] for r in await registry.search({"owner": LOW})] == ["ip2"]


async def test_rwa_transfer_takes_the_owners_other_spelling():
    from runtime.blockchain.services.rwa_tokenization.service import RWAService

    svc = RWAService({})
    svc._tokens["T1"] = {"token_id": "T1", "owner": CHK, "provenance": [], "fractions": {}}
    out = await _outcome(svc.transfer_ownership("T1", LOW, OTHER))
    assert "is owned by" not in out, out
    svc._tokens["T2"] = {"token_id": "T2", "owner": CHK, "provenance": [], "fractions": {}}
    assert "is owned by" in await _outcome(svc.transfer_ownership("T2", OTHER, LOW))


async def test_p2p_lending_owner_checks_take_the_other_spelling():
    from runtime.blockchain.services.defi.p2p_lending import OfferStatus, P2PLending

    svc = P2PLending({})
    far = int(time.time()) + 86400
    base = {"token": "USDC", "amount": 10.0, "remaining_amount": 10.0, "interest_rate": 5.0,
            "duration_days": 30, "expires_at": far, "created_at": 0}
    svc._offers["O1"] = {**base, "offer_id": "O1", "lender": CHK, "status": OfferStatus.OPEN}
    assert "Cannot borrow from your own offer" in await _outcome(
        svc.accept_offer("O1", LOW, {"token": "ETH", "amount": 1, "value_usd": 100}))
    assert "Only the lender" not in await _outcome(svc.cancel_offer("O1", UP0X))
    svc._offers["O2"] = {**base, "offer_id": "O2", "lender": OTHER, "borrower": CHK,
                         "status": OfferStatus.FILLED}
    assert "Only the borrower" not in await _outcome(svc.repay_offer("O2", LOW, 1.0))
    svc._offers["O3"] = {**base, "offer_id": "O3", "lender": CHK, "status": OfferStatus.OPEN}
    listed = await svc.list_offers({"lender": LOW, "status": OfferStatus.OPEN})
    assert [o["offer_id"] for o in listed] == ["O3"], listed
    svc._offers["O4"] = {**base, "offer_id": "O4", "lender": CHK, "status": OfferStatus.OPEN}
    assert "Only the lender" in await _outcome(svc.cancel_offer("O4", OTHER))


async def test_supply_chain_custody_takes_the_holders_other_spelling():
    from runtime.blockchain.services.supply_chain.service import SupplyChainService

    svc = SupplyChainService({})
    svc._registry.get_product = AsyncMock(return_value={"product_id": "p1", "status": "active"})
    svc._custody["p1"] = CHK
    out = await _outcome(svc.transfer_custody("p1", LOW, OTHER))
    assert "Custody mismatch" not in out, out
    svc._custody["p2"] = CHK
    assert "Custody mismatch" in await _outcome(svc.transfer_custody("p2", OTHER, LOW))


async def test_x402_spend_limit_owner_takes_the_owners_other_spelling():
    from runtime.blockchain.services.x402_payments.limit_updater import LimitUpdater

    svc = LimitUpdater({})
    svc.register_agent_owner("agent-1", CHK)
    out = await _outcome(svc.update_limits("agent-1", {"daily": 1.0}, UP0X))
    assert "Only the agent owner" not in out, out
    assert "Only the agent owner" in await _outcome(
        svc.update_limits("agent-1", {"daily": 1.0}, OTHER))


async def test_messaging_yourself_is_refused_in_any_spelling():
    from runtime.blockchain.services.social.messaging import XMTPMessaging

    out = await _outcome(XMTPMessaging({}).send_message(CHK, LOW, "hello"))
    assert "Cannot send a message to yourself" in out, out


# ── (c) the checks that folded case ───────────────────────────────────────


async def test_royalty_configuration_is_changed_only_by_the_caller_that_set_it():
    from runtime.blockchain.services.nft_services.royalty_enforcement import RoyaltyEnforcement

    royalties = RoyaltyEnforcement({})
    coll = "0x" + "cc" * 20
    await royalties.configure_royalty(coll, 1, OTHER, 500, caller_identity=CHK)
    out = await _outcome(royalties.configure_royalty(coll, 1, OTHER, 600, caller_identity=LOW))
    assert "cannot be changed" not in out, out

    await royalties.configure_royalty(coll, 2, OTHER, 500, caller_identity="apple:AbC")
    out = await _outcome(
        royalties.configure_royalty(coll, 2, OTHER, 600, caller_identity="apple:abc"))
    assert "cannot be changed" in out, f"an id that is not an address was folded into another: {out}"


async def test_nft_rights_are_changed_only_by_the_caller_that_set_them():
    from runtime.blockchain.services.nft_services.rights import RightsManagement

    rights = RightsManagement({})
    coll = "0x" + "dd" * 20
    await rights.set_rights(coll, 1, {"commercial": True}, caller_identity=CHK)
    out = await _outcome(rights.set_rights(coll, 1, {"commercial": False}, caller_identity=UP0X))
    assert "cannot be changed" not in out, out

    await rights.set_rights(coll, 2, {"commercial": True}, caller_identity="apple:AbC")
    out = await _outcome(
        rights.set_rights(coll, 2, {"commercial": False}, caller_identity="apple:abc"))
    assert "cannot be changed" in out, f"an id that is not an address was folded into another: {out}"


# ── (d) the follow graph ──────────────────────────────────────────────────


async def test_the_follow_graph_holds_one_wallet_in_one_spelling(tmp_path):
    from runtime.db.database import Database
    from runtime.social.follows import FollowStore

    db = Database({"database": {"path": str(tmp_path / "f.db")}})
    store = FollowStore(db)
    other_chk = "0xfB6916095ca1df60bB79Ce92cE3Ea74c37c5d359"
    await store.follow(LOW, other_chk)          # follower as the session names it
    await store.follow(LOW, other_chk.lower())  # the same followee, another spelling
    assert await store.following(CHK) == [other_chk.lower()]
    assert await store.followers(other_chk) == [LOW]
    await store.follow(CHK, LOW)                # following yourself, in another spelling
    assert await store.followers(LOW) == []
    await store.unfollow(UP0X, other_chk)
    assert await store.following(LOW) == []


# ── (a) through the gateway, and (e) ──────────────────────────────────────


async def _signed_in(client, account, spelling):
    from eth_account.messages import encode_defunct

    r = await client.post("/auth/nonce", json={"address": spelling})
    assert r.status == 200, (spelling, r.status, await r.text())
    ch = await r.json()
    sig = account.sign_message(encode_defunct(text=ch["message"])).signature.hex()
    sig = sig if sig.startswith("0x") else "0x" + sig
    r = await client.post("/auth/verify", json={"address": spelling, "message": ch["message"],
                                                "signature": sig, "nonce": ch["nonce"]})
    assert r.status == 200, await r.text()
    return (await r.json())["token"]


def _gateway(tmp_path):
    from gateway.server import GatewayServer
    from test_route_sweep import SWEEP_CONFIG

    config = {**SWEEP_CONFIG,
              "gateway": {**SWEEP_CONFIG.get("gateway", {}), "api_key": "test-operator-key"},
              "memory_dir": str(tmp_path),
              "database": {**SWEEP_CONFIG.get("database", {}), "path": str(tmp_path / "g.db")}}
    server = GatewayServer(config)
    server.react_loop.router.health_check = AsyncMock(return_value={"ollama": True})
    server.react_loop.run = AsyncMock(
        return_value=SimpleNamespace(response="ok", tool_calls=[], provider="stub"))
    return server


async def test_a_claim_on_ones_own_policy_passes_the_ownership_check_through_the_gateway(
        tmp_path, monkeypatch):
    """(a) end to end: signed in with the EIP-55 address, holder written the
    same way. The claim reaches the policy's own status check, not an
    ownership refusal.

    The claim route is gated, so the gateway's security gate must be up. This
    test's subject is the platform's ownership check, not whether an installed
    core names a caller the platform's way (that is
    tests/test_security_core_names_a_caller_as_the_platform_does.py), so the
    backend is taken to name one the platform's way."""
    from aiohttp.test_utils import TestClient, TestServer
    from eth_account import Account

    import runtime.security as seam
    from runtime.auth.identity import canonical_identity
    monkeypatch.setattr(seam, "_backend_canonical_identity", canonical_identity, raising=False)

    account = Account.create()
    server = _gateway(tmp_path)
    app = server.create_app()
    routes = None
    for resource in app.router.resources():
        if getattr(resource, "canonical", "") == "/api/v1/insurance/claim":
            routes = next(iter(resource)).handler.__self__
    async with TestClient(TestServer(app)) as client:
        token = await _signed_in(client, account, account.address)
        svc = routes._get_registry().get("insurance")
        now = int(time.time())
        svc._policies["pol_1"] = {"policy_id": "pol_1", "holder": account.address,
                                  "policy_type": "weather", "coverage": {"amount": 1.0},
                                  "status": "cancelled", "created_at": now,
                                  "expires_at": now + 86400}
        r = await client.post("/api/v1/insurance/claim", json={"policy_id": "pol_1"},
                              headers={"X-Wallet-Session": token})
        text = await r.text()
        assert "does not own" not in text, (r.status, text)
        assert "not active" in text, (r.status, text)


@pytest.mark.parametrize("spelling", ["0X-upper", "lower", "checksum"])
async def test_auth_nonce_accepts_every_spelling_auth_verify_accepts(tmp_path, spelling):
    """(e): signing in with 0X, as the API reference says, works end to end,
    and every spelling is one caller."""
    from aiohttp.test_utils import TestClient, TestServer
    from eth_account import Account

    account = Account.create()
    spelled = {"0X-upper": "0X" + account.address[2:].upper(),
               "lower": account.address.lower(), "checksum": account.address}[spelling]
    server = _gateway(tmp_path)
    async with TestClient(TestServer(server.create_app())) as client:
        await _signed_in(client, account, spelled)
        r = await client.post("/auth/nonce", json={"address": "0x" + "zz" * 20})
        assert r.status == 400, "a value that is not a hex address is not an address"
