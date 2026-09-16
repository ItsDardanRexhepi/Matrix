"""DOMAIN 18-H — the ownership check compared a string the caller wrote.

THE DEFECT. NEW-78b installed `assert_owner` on the insurance ownership
methods, and each declared its identity parameter as `caller`. The dispatcher
overrides exactly ONE name — `caller_identity` — and only for methods that
declare it. Everything else in `params` is forwarded verbatim into
`method(**params)`, and `params` is the attacker-controlled request body; the
dispatcher's own comment says so in terms.

So `assert_owner` was handed a string the CALLER supplied and compared it to
`policy["holder"]`. Anyone who knew a policy id could claim to be its holder.

MEASURED before the fix, reproducing the dispatcher's binding step exactly: a
caller whose threaded identity was "mallory", sending
`{"policy_id": <alice's>, "caller": "alice"}`, cancelled Alice's policy —
result "cancelled", stored status "cancelled".

17-D'S OWN COMMENT NAMES THIS PRIMITIVE AS THE THING IT REFUSED TO SHIP:

    "`params` is attacker-controlled ... If a client-supplied
     `params["caller_identity"]` were left to stand when the real identity is
     unknown, this fix would ship a brand-new spoofing primitive: assert any
     address, have the platform record it."

It was correct, thorough, and it protected the one name it knew about. The
primitive shipped anyway under a different name, because the OWNERSHIP sweep
and the IDENTITY sweep chose different words for the same idea. That is §AO.2
made concrete: thirteen names for the party acting is the absence of a platform
concept of one, and here the gap between two of those names is an
authorisation bypass.

§AM.3, AGAIN, AND AGAINST A COMMENT THAT WAS RIGHT. The stated principle was
enforced precisely where it was stated and nowhere else. A reader who finds
that comment — as I did, and quoted approvingly in 17-D — reads it as evidence
the class is handled.

THE SECOND HALF, WHICH THE SAME FIX CLOSES. Because the dispatcher never bound
`caller` at all, an HONEST authenticated owner reached `assert_owner` with
`caller=None` and was REFUSED. Every insurance action that can pay out, refund
or renew was unreachable for its rightful owner, while `risk_assess` — which
fabricates its output (D18-L1-C7, still open) — dispatched fine. The safe
direction was dead and the unsafe one was live.
"""

from __future__ import annotations

import pytest

from runtime.blockchain.services import service_dispatcher as sd
from runtime.blockchain.services.insurance.service import InsuranceService

OWNERSHIP_METHODS = ("file_claim", "cancel_policy", "renew_coverage")


async def _issue(holder: str = "alice") -> tuple[InsuranceService, str]:
    svc = InsuranceService({})
    svc._web3.available = True
    svc._policy_contract = "0xC0FFEE"
    svc._web3.is_placeholder = lambda _v: False
    await svc._reserve_fund.deposit(500_000.0)
    pol = await svc.create_policy(
        holder=holder, policy_type="earthquake",
        coverage={"amount": 1_000.0, "magnitude_threshold": 6.0},
        premium=100_000.0,
    )
    return svc, pol["policy_id"]


async def _dispatch(svc, method_name, params, caller_identity):
    """A faithful copy of ServiceDispatcher.execute's binding step.

    Mirrors service_dispatcher.py:1241-1245 — the injection is gated on the
    method declaring `caller_identity`, and then `method(**params)` is called
    with the merged dict. Reproduced here rather than driving `execute()`
    because the dispatcher constructs its own service instances, which cannot
    be seeded with a policy from a test.
    """
    method = getattr(svc, method_name)
    if sd._method_accepts_caller_identity(getattr(InsuranceService, method_name)):
        params = {
            **params,
            "caller_identity": caller_identity or "",
            "caller_source": "authenticated" if caller_identity else "unauthenticated",
        }
    return await method(**params)


@pytest.mark.parametrize("method_name", OWNERSHIP_METHODS)
def test_every_ownership_method_opts_into_dispatcher_identity(method_name):
    """DEFECT-PROVER, AND THE STRUCTURAL FORM OF THE FINDING.

    This is the check that would have caught it: the dispatcher binds identity
    if and only if the method declares `caller_identity`. Every method that
    performs an ownership check must therefore declare it, or it is reading a
    self-asserted string. Asserted for ALL THREE rather than for the one under
    repair — §AK.2: a fix that names one call site while several share the
    defect is a half-fix by construction.
    """
    assert sd._method_accepts_caller_identity(
        getattr(InsuranceService, method_name)
    ) is True, (
        f"{method_name} performs an ownership check but does not declare "
        f"caller_identity, so the dispatcher passes the caller's own claim"
    )


async def test_a_stranger_cannot_assert_the_holders_identity():
    """DEFECT-PROVER. The measured exploit: mallory writes `caller: "alice"`."""
    svc, pid = await _issue("alice")
    with pytest.raises(Exception) as exc:
        await _dispatch(svc, "cancel_policy",
                        {"policy_id": pid, "caller": "alice"}, "mallory")
    assert "does not own" in str(exc.value)
    assert svc._policies[pid]["status"] == "active", (
        "a spoofed cancellation must not touch the stored policy"
    )


async def test_a_call_with_nothing_threaded_is_refused_not_given_the_body_caller():
    """DEFECT-PROVER. The threaded value wins even when EMPTY — a call whose
    entry point bound no identity is a refusal, never a fallback to the body
    `caller`. That distinction is the whole of 17-D's reasoning. It is the
    dispatcher's guard only: on the gateway route with no session, a body
    `wallet` is what gets bound and threaded, so the body can still name the
    caller there (tests/test_bound_identity_is_not_called_authenticated.py)."""
    svc, pid = await _issue("alice")
    with pytest.raises(Exception) as exc:
        await _dispatch(svc, "cancel_policy",
                        {"policy_id": pid, "caller": "alice"}, "")
    assert "required" in str(exc.value)
    assert svc._policies[pid]["status"] == "active"


async def test_the_real_holder_can_finally_act_on_their_own_policy():
    """DEFECT-PROVER FOR THE OTHER HALF. Before this, the dispatcher bound
    NOTHING, so the authenticated owner arrived with caller=None and was
    refused. Every payout/refund/renewal action was dead for its owner while
    the fabricating one (`risk_assess`) dispatched fine."""
    svc, pid = await _issue("alice")
    out = await _dispatch(svc, "cancel_policy", {"policy_id": pid}, "alice")
    assert out["status"] == "cancelled"
    assert svc._policies[pid]["status"] == "cancelled"


async def test_an_internal_caller_is_still_trusted():
    """SCOPE PIN. `check_triggers` files on the holder's behalf with an
    explicit `caller=` and no dispatcher in the path. When `caller_source` is
    absent the call is internal and `caller` stands — otherwise this fix would
    break the automatic settlement path it does not own."""
    svc, pid = await _issue("alice")
    out = await svc.cancel_policy(pid, caller="alice")
    assert out["status"] == "cancelled"


async def test_an_internal_caller_is_still_checked():
    """SCOPE PIN — internal trust is not internal bypass."""
    svc, pid = await _issue("alice")
    with pytest.raises(Exception, match="does not own"):
        await svc.cancel_policy(pid, caller="mallory")
