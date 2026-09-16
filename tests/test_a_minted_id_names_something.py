"""Three claims the route table makes about services that do not keep them.

1. POST /api/v1/groups and POST /api/v1/social/community/create both reach
   `social.create_community`, and the P2 route block promises "WIRE routes run
   through the _call() seam; the rest return an honest 501 (never a fabricated
   200)". `create_community` minted `comm_{uuid4}` with `"status": "active"`
   and RETURNED IT WITHOUT STORING IT — no dict, no db, no chain — so the
   gateway answered 200 with an id for a community that exists nowhere, and
   every read leg is 501, which is where a caller would have found out. The
   sibling in the same class, `create_profile`, has stored its record in
   `self._profiles` all along. A route comment in service_routes.py even
   described the behaviour as "create_community stores creator/name/
   description/token_gate and nothing enforces anything" — the enforcement
   half was right and the storing half was not.

2. `POST /api/v1/disputes/{id}/claim` is documented "Post-resolution
   entitlement claim — idempotent, no funds held here", and the service's own
   section header says "idempotent" too. It was not: a second call by the same
   address raised ValueError, which `_call` maps to HTTP 400. A client whose
   first POST timed out after the claim was recorded got 400 on the retry
   instead of the entitlement the platform holds for it — the exact failure
   idempotency is for. The no-double-record guarantee is real and stays; what
   changes is what the retry is told.

3. The route table said settlement "now requires an owner and oracle
   verification it never supplied". The oracle half is real
   (`_verify_via_oracle`). The owner half is not: `auto_settle_claim(policy_id,
   oracle_data)` takes no caller at all and `assert_owner` is never reached
   from it. That is a KNOWN, DELIBERATE deferral — NEW-82 / 18-C in
   insurance/service.py argues at length that a per-method guard in one service
   would make the dispatcher seam look audited while leaving every other
   service's caller argument unbound. The deferral stands; the sentence that
   contradicts it is what is corrected.
"""

from __future__ import annotations

import inspect

import pytest

from runtime.blockchain.services.dispute_resolution.service import DisputeResolution
from runtime.blockchain.services.insurance.service import InsuranceService
from runtime.blockchain.services.social.service import SocialService


# ── 1. a community id names a community ────────────────────────────────────

async def test_a_created_community_is_held_by_the_service():
    svc = SocialService({})
    record = await svc.create_community(
        creator="0xabc", name="The Construct", description="a load program")
    assert record["id"].startswith("comm_")
    held = svc.get_community(record["id"])
    assert held is not None, (
        "the service minted a community id with status 'active' and stored "
        "nothing: the 200 named a community that exists nowhere")
    assert held["name"] == "The Construct" and held["creator"] == "0xabc"


async def test_the_community_store_is_the_sibling_store_it_reads_like():
    """create_profile has stored its record all along; this is the same shape."""
    svc = SocialService({})
    await svc.create_profile("0xabc", "Neo", "the one")
    await svc.create_community(creator="0xabc", name="Zion")
    assert len(svc._profiles) == 1
    assert len(svc._communities) == 1


async def test_a_community_still_refuses_what_it_refused():
    svc = SocialService({})
    with pytest.raises(ValueError):
        await svc.create_community(creator="", name="Zion")
    with pytest.raises(ValueError):
        await svc.create_community(creator="0xabc", name="")


async def test_two_communities_do_not_share_an_id():
    svc = SocialService({})
    a = await svc.create_community(creator="0xabc", name="Zion")
    b = await svc.create_community(creator="0xabc", name="Zion")
    assert a["id"] != b["id"] and len(svc._communities) == 2


# ── 2. the claim is idempotent, as both its docstrings say ─────────────────

async def _filed(svc):
    return await svc.file_dispute(
        claimant="0xclaimant", respondent="0xrespondent",
        category="contract_breach",
        evidence={"description": "milestone not delivered"},
        stake_amount=100.0,
    )


async def _resolved(svc):
    d = await _filed(svc)
    d["status"] = "resolved"
    d["outcome"] = {"winner": "claimant", "juror_results": {}}
    return svc, d


async def test_a_retried_claim_is_answered_with_what_was_recorded():
    svc, d = await _resolved(DisputeResolution(config={}))
    first = await svc.claim(d["dispute_id"], "0xclaimant")
    again = await svc.claim(d["dispute_id"], "0xclaimant")
    assert again["type"] == first["type"] and again["amount"] == first["amount"]
    assert again.get("replay") is True, (
        "a retry after a timed-out first POST raised 'already claimed', which "
        "_call answers 400 — the caller is refused its own recorded "
        "entitlement")


async def test_a_retried_claim_records_nothing_new():
    svc, d = await _resolved(DisputeResolution(config={}))
    first = await svc.claim(d["dispute_id"], "0xclaimant")
    await svc.claim(d["dispute_id"], "0xclaimant")
    claims = d["claims"]
    assert list(claims) == ["0xclaimant"]
    assert claims["0xclaimant"]["claimed_at"] == first["claimed_at"], (
        "the retry overwrote the recorded claim")


async def test_an_address_with_no_entitlement_is_still_refused():
    svc, d = await _resolved(DisputeResolution(config={}))
    with pytest.raises(ValueError, match="no claim"):
        await svc.claim(d["dispute_id"], "0xstranger")


async def test_an_unresolved_dispute_is_still_refused():
    svc = DisputeResolution(config={})
    d = await _filed(svc)
    with pytest.raises(ValueError, match="not resolved"):
        await svc.claim(d["dispute_id"], "0xclaimant")


# ── 3. the owner requirement that does not exist is not claimed ───────────

def test_auto_settle_takes_no_caller_and_the_table_does_not_say_it_does():
    import gateway.service_routes as service_routes

    params = inspect.signature(InsuranceService.auto_settle_claim).parameters
    assert not {"caller", "caller_identity", "holder"} & set(params), (
        "auto_settle_claim gained a caller — if the NEW-82 deferral was lifted, "
        "the route comment should say so")

    src = inspect.getsource(service_routes.ServiceRoutes.register_routes)
    i = src.find("requires an owner")
    if i != -1:
        # Allowed only as a quotation of what the comment used to say, with
        # the correction beside it.
        assert "used to" in src[max(0, i - 400):i], (
            "the route table still asserts that settlement requires an owner; "
            "auto_settle_claim has no caller argument and never reaches "
            "assert_owner")
        assert "does not exist" in src[i:i + 600], src[i:i + 600]
