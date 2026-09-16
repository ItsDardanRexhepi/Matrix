"""NEW-89 — Tier 1 + Tier 2 of the broken-binding class, by disposition.

THE RE-SCOPE. 49 of 105 handler->method bindings could not execute. The 11
SERVICE-MISSING routes went at 944c7c7. The remaining 38 were split by WHO IS
AFFECTED rather than by defect class:

  Tier 1 (17)  no client impact — the iOS app never calls them. Ship.
  Tier 2 (3)   the advertised contract invites a caller-names-the-outcome
               primitive AND the app does not call them. Delete.
  Tier 3 (18)  the shipped iOS app CALLS them. HELD — see D8.

THE GOAL IS NOT "MAKE ROUTES WORK", IT IS "MAKE ROUTES HONEST". For several of
these the honest form is a refusal, not a repair. A 400 or a 501 tells the
truth; a route that accepts the wrong shape does not.

SIX DISPOSITIONS, and the split is the finding — "22 mechanical renames" was
wrong, only 3 of Tier 1 are renames:

  RENAME (3)          same concept, different spelling. Contract untouched.
  CONTRACT-GAP (4)    the route never collected something required. A new
                      required body field — a deliberate contract change.
  DROPPED-INTENT (4)  the route accepts something the service cannot honour.
                      REFUSE; never silently discard.
  REPOINT (1)         a real method exists under another name, verified real.
  HONEST-501 (3)      unbuilt, and the near-twin is unusable or fake.
  DELETE (5)          2 whose repoint target is a FABRICATION + 3 Tier 2.
"""

from __future__ import annotations

import json

import pytest
from aiohttp import web
from aiohttp.test_utils import TestClient, TestServer

from gateway.service_routes import ServiceRoutes


@pytest.fixture
async def client():
    routes = ServiceRoutes(config={})
    app = web.Application()
    routes.register_routes(app)
    async with TestClient(TestServer(app)) as c:
        yield c


def _binding_of(handler: str) -> str | None:
    from tests.test_route_binding_detector import find_broken_bindings
    return find_broken_bindings().get(handler)


# ── RENAME — the binding executes; the public contract is unchanged ──────


@pytest.mark.parametrize("handler", [
    "_handle_custody_transfer", "_handle_credential_issue",
    "_handle_crossborder_send",
])
def test_renames_now_bind(handler):
    assert _binding_of(handler) is None


async def test_a_rename_did_not_change_the_wire_contract(client):
    """The whole point of RENAME: the caller sends what it always sent.

    If the fix had also renamed the BODY keys, every existing caller would
    break — a rename that moves the breakage instead of removing it.
    """
    resp = await client.post("/api/v1/crossborder/send", json={
        "sender": "0xA", "recipient": "0xB", "amount": 500.0,
        "source_currency": "USD", "destination_currency": "EUR",
    })
    assert resp.status == 200, await resp.text()
    body = json.loads(await resp.text())
    inner = body.get("data", body)
    assert "recorded_unsettled" in json.dumps(inner)


# ── CONTRACT-GAP — a new REQUIRED field, taken deliberately ──────────────


@pytest.mark.parametrize("path,body", [
    ("/api/v1/nft/bridge", {"owner": "0xA", "token_id": 1, "dest_chain": "base"}),
    ("/api/v1/nft/rent", {"renter": "0xA", "token_id": 1, "duration": 7}),
    ("/api/v1/nft/fractionalize", {"owner": "0xA", "token_id": 1, "fractions": 10}),
    ("/api/v1/nft/royalty/claim", {"creator": "0xA", "token_id": 1}),
])
async def test_contract_gap_routes_now_demand_the_missing_field(client, path, body):
    """SCENARIO: the OLD body shape.

    It must fail with a NAMED missing field, not a TypeError. `collection` was
    never collected and an NFT is identified by (collection, token_id) — a
    token_id alone is ambiguous across collections. Binding `owner` into the
    collection slot would have cleared the TypeError and acted on the wrong
    token.
    """
    resp = await client.post(path, json=body)
    assert resp.status == 400
    assert "collection" in (await resp.text())


async def test_a_contract_gap_route_works_once_the_field_is_supplied(client):
    resp = await client.post("/api/v1/nft/fractionalize", json={
        "owner": "0xA", "token_id": 1, "fractions": 10, "collection": "0xC",
    })
    assert resp.status != 400, await resp.text()


# ── DROPPED-INTENT — refuse, never silently discard ─────────────────────


@pytest.mark.parametrize("path,body,capability", [
    ("/api/v1/social/community/create",
     {"creator": "0xA", "name": "n", "rules": {"no_spam": True}}, "rules"),
    ("/api/v1/governance/snapshot/vote",
     {"voter": "0xA", "proposal_id": "p", "choice": 1, "space": "dao.eth"}, "Snapshot"),
    ("/api/v1/nft/batch-mint",
     {"creator": "0xA", "collection_id": "c", "count": 2,
      "metadata_template": {}, "items": [{"a": 1}, {"b": 2}]}, "batch"),
])
async def test_a_parameter_the_service_cannot_honour_is_refused(
    client, path, body, capability,
):
    """THE DANGEROUS CLASS, and the reason it is dangerous.

    Each of these routes REQUIRED a parameter the service has no way to act
    on. `rules` — social.create_community has no rules concept at all.
    `space` — snapshot_vote has no namespace, and its only free parameter is a
    voting-power BLOCK NUMBER, which is not a space. `items` — batch_mint
    mints `count` copies of ONE template, so a list of distinct items would
    silently mint duplicates.

    Dropping any of them would return 200 while doing something other than
    what the caller asked. 501 is the honest answer.
    """
    resp = await client.post(path, json=body)
    assert resp.status == 501, await resp.text()
    payload = json.loads(await resp.text())
    assert payload["error"] == "not_implemented"
    assert capability.lower() in json.dumps(payload).lower()


async def test_those_routes_still_work_without_the_unhonourable_field(client):
    """The refusal is scoped to the parameter, not the whole capability."""
    resp = await client.post("/api/v1/social/community/create",
                             json={"creator": "0xA", "name": "n"})
    assert resp.status == 200, await resp.text()


# ── REPOINT — verified real, and verified NOT a fabrication ─────────────


def test_the_repoint_binds():
    assert _binding_of("_handle_provenance_log") is None


def test_the_repoint_target_is_not_a_known_fabrication():
    """MY OWN RULE, made executable.

    Six of the eleven SERVICE-MISSING routes had a real-looking implementation
    under another name, and every one of those targets was on D6's fabrication
    list. Repointing converts an honest 404 into a convincing fake — strictly
    worse, because a 404 tells the truth.

    Two more were caught in Tier 1 by the same check: soulbound_mint ->
    nft_services.mint_soulbound and multisig_propose ->
    governance.propose_multisig are both D6 instances, so both routes were
    DELETED rather than repointed.
    """
    from tests.test_uuid_mint_fabrication_shape import KNOWN_FABRICATION_SHAPE

    assert not any(k.endswith(".log_event") for k in KNOWN_FABRICATION_SHAPE)
    # and the two that were refused a repoint still do not do the thing.
    #
    # `propose_multisig` is still a D6 instance and is asserted against that
    # list. `mint_soulbound` LEFT the list in the attest-money cluster — not
    # because it started minting, but because it stopped claiming to: it now
    # answers `recorded_unsettled` with `settled: False`. Asserting against the
    # service rather than against the inventory is the stronger form of the same
    # claim, and it does not go quiet the next time an entry is fixed the same
    # way.
    assert any(k.endswith(".propose_multisig") for k in KNOWN_FABRICATION_SHAPE)

    import asyncio

    from runtime.blockchain.services.nft_services.service import NFTService

    svc = NFTService({})
    svc._web3 = type("_Deployed", (), {
        "available": True,
        "is_placeholder": staticmethod(lambda _a: False),
    })()
    record = asyncio.run(svc.mint_soulbound("0xR", {}, "0xI"))
    assert record["status"] == "recorded_unsettled" and record["settled"] is False, (
        f"the repoint target started claiming to mint again: {record}"
    )


# ── HONEST-501 — unbuilt, and the near-twin is unusable or fake ──────────


@pytest.mark.parametrize("path,body", [
    ("/api/v1/social/message/send",
     {"sender": "0xA", "recipient": "0xB", "content": "hi"}),
    ("/api/v1/governance/multisig/approve",
     {"approver": "0xA", "multisig_address": "0xM", "proposal_id": "p"}),
    ("/api/v1/social/gate/create",
     {"owner": "0xA", "gate_type": "nft", "criteria": {"x": 1}}),
])
async def test_unbuilt_capabilities_answer_501_not_404_by_accident(client, path, body):
    resp = await client.post(path, json=body)
    assert resp.status == 501
    assert json.loads(await resp.text())["error"] == "not_implemented"


def test_the_messaging_501_exists_because_the_twin_is_a_fake_delivery():
    """social.send_message does not exist. Its only near-twin,
    send_encrypted_message, is a D7 instance — "sent" with a uuid
    content_hash and no XMTP client. That is why this is a 501 and not a
    repoint."""
    from tests.test_fake_delivery_detector import KNOWN_FAKE_DELIVERY

    assert any(k.endswith(".send_encrypted_message") for k in KNOWN_FAKE_DELIVERY)


# ── DELETE — 2 repoint-refused + 3 Tier 2 dangerous ─────────────────────


@pytest.mark.parametrize("path", [
    # repoint refused: the target is a D6 fabrication
    "/api/v1/identity/soulbound/mint",
    "/api/v1/governance/multisig/propose",
    # Tier 2: the advertised contract invites a caller-names-the-outcome
    # primitive, and /claim/settle already showed where that leads
    "/api/v1/defi/yield/optimize",
    "/api/v1/governance/treasury/transfer",
    "/api/v1/rwa/fractional/buy",
])
async def test_deleted_routes_are_gone(client, path):
    resp = await client.post(path, json={})
    assert resp.status == 404


def test_the_tier2_contracts_are_not_left_as_a_spec_to_satisfy():
    """NEW-81 applied. `treasury_transfer(dao_address, recipient, token,
    amount)` is a caller-names-the-recipient-and-amount treasury withdrawal;
    `rwa_fractional_buy(buyer, asset_id, fractions)` is a caller-names-the-
    quantity purchase. Neither is implemented. Leaving the route as a
    published contract is an invitation to implement exactly that."""
    src = (
        __import__("pathlib").Path(__file__).resolve().parent.parent
        / "gateway/service_routes.py"
    ).read_text()
    for handler in ("_handle_treasury_transfer", "_handle_rwa_fractional_buy",
                    "_handle_yield_optimize", "_handle_soulbound_mint",
                    "_handle_multisig_propose"):
        assert handler not in src, f"{handler} came back"


def test_no_tier3_route_was_touched():
    """SCOPE BOUNDARY. Tier 3 is the coordination gate — 18 routes the shipped
    client calls. This commit must not have changed any of them, or it would
    have moved a live client breakage rather than leaving it visible."""
    from tests.test_route_binding_detector import (
        KNOWN_BROKEN_BINDINGS, find_broken_bindings,
    )

    assert find_broken_bindings() == KNOWN_BROKEN_BINDINGS
    assert len(KNOWN_BROKEN_BINDINGS) == 18
