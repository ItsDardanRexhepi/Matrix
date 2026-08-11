"""NEW-77..81 — the insurance claim precondition set, as one coherent whole.

These ship together because they are all preconditions on a payout, and a
partial set is what produced the defects in the first place.

  NEW-77  shared ownership primitive (runtime/blockchain/services/ownership.py)
  NEW-78  file_claim: ownership + oracle-routed verification, caller-supplied
          trigger_data DELETED
  NEW-79  auto_settle_claim: the preconditions my own NEW-67 delegation omitted
  NEW-80  create_parametric_policy: schema reconciled with what the claim path
          reads
  NEW-81  the /api/v1/insurance/claim/settle route removed (it called a method
          that never existed)

SCENARIO BREADTH IS THE POINT OF THIS FILE. The original NEW-67 tests were
well-formed and still missed three live defects, because every one of them
built a fresh policy via create_policy and settled it exactly once. The
failure was scenario breadth, not assertion strength — fourth instance of the
aimed-off-subject pattern. Each test below therefore names the scenario it
covers, and the three previously-missed scenarios are covered explicitly:

    CANCELLED POLICY   -> test_a_cancelled_policy_cannot_be_settled
    REPEAT SETTLEMENT  -> test_a_policy_cannot_be_settled_twice
    PARAMETRIC POLICY  -> test_a_parametric_policy_can_be_verified_at_all
                          test_filing_on_a_parametric_policy_does_not_crash

PROOF OF FAILURE at HEAD ae9ff80 (pre-fix): 13 failed, 5 passed. The five that
pass pre-fix are named here because a test that passes pre-fix is not passing,
it is not looking — each needs a reason it is exempt:

  test_ownership_refuses_an_absent_caller       ) exercise NEW-77 itself, which
  test_ownership_refuses_a_record_with_no_owner ) did not exist pre-fix. Their
  test_ownership_accepts_only_the_owner         ) proof-of-failure is that
                                                  deleting ownership.py breaks
                                                  collection, not a behaviour
                                                  change in old code.
  test_settle_claim_never_existed_...  a PIN, not a fix-proof. It must hold in
                                       both states; its job is to stop someone
                                       "fixing" NEW-81 by adding a settle_claim
                                       stub instead of routing to the real one.
  test_the_route_module_still_constructs  regression guard on MY removal —
                                       domain 4 showed dangling handlers crash
                                       the router at construction.
"""

from __future__ import annotations

import ast
import inspect
import time
from pathlib import Path

import pytest

from runtime.blockchain.services.insurance import claims_processor as cp_module
from runtime.blockchain.services.insurance.claims_processor import ClaimsProcessor
from runtime.blockchain.services.insurance.service import InsuranceService
from runtime.blockchain.services.ownership import OwnershipError, assert_owner

REPO = Path(__file__).resolve().parent.parent


def _executing_code(module) -> str:
    """Source stripped to what actually RUNS, via an AST round-trip.

    Comments never enter the AST at all; docstrings are dropped explicitly.
    Line-prefix filtering (`startswith("#")`) is not enough here and the
    difference is not cosmetic: this module's docstrings deliberately QUOTE
    the deleted claimant-supplied path so a reader knows what was removed and
    why. A grep-based control cannot tell a quotation of dead code from a use
    of it, and would either fail on honest documentation or be silenced by
    deleting the documentation. Parsing distinguishes them.
    """
    tree = ast.parse(Path(inspect.getfile(module)).read_text())
    for node in ast.walk(tree):
        if not isinstance(
            node,
            (ast.Module, ast.ClassDef, ast.FunctionDef, ast.AsyncFunctionDef),
        ):
            continue
        body = node.body
        if (
            body
            and isinstance(body[0], ast.Expr)
            and isinstance(body[0].value, ast.Constant)
            and isinstance(body[0].value.value, str)
        ):
            node.body = body[1:] or [ast.Pass()]
    return ast.unparse(tree)


def _armed(svc: InsuranceService) -> InsuranceService:
    svc._web3.available = True
    svc._web3.is_placeholder = lambda _a: False
    return svc


async def _policy(svc, holder="alice", amount=5000.0):
    await svc._reserve_fund.deposit(90_000.0)
    p = await svc.create_policy(
        holder=holder, policy_type="flight_delay",
        coverage={"amount": amount, "delay_minutes": 120}, premium=9000.0,
    )
    assert "policy_id" in p, p
    return p["policy_id"]


# ── NEW-77: the shared ownership primitive ───────────────────────────────


def test_ownership_refuses_an_absent_caller():
    """SCENARIO: no caller supplied — the exact way this check was missing in
    all three domains that needed it. Absence must refuse, not skip."""
    with pytest.raises(OwnershipError, match="Caller identity is required"):
        assert_owner(None, {"holder": "alice"})
    with pytest.raises(OwnershipError):
        assert_owner("", {"holder": "alice"})


def test_ownership_refuses_a_record_with_no_owner():
    """SCENARIO: unenumerated boundary case. A record with no recorded owner
    cannot be owned by anyone — fail closed rather than treat 'no owner' as
    'any owner'."""
    with pytest.raises(OwnershipError, match="no recorded"):
        assert_owner("alice", {"policy_id": "p"})


def test_ownership_accepts_only_the_owner():
    """SCENARIO: match and mismatch."""
    assert assert_owner("alice", {"holder": "alice"}) == "alice"
    with pytest.raises(OwnershipError, match="does not own"):
        assert_owner("mallory", {"holder": "alice"})


# ── NEW-78: file_claim ownership ─────────────────────────────────────────


async def test_a_stranger_cannot_claim_against_someone_elses_policy():
    """SCENARIO: attacker knows a policy id. This was the whole hole — the
    method read `holder` from the stored policy and never asked who called."""
    svc = _armed(InsuranceService({}))
    pid = await _policy(svc, holder="alice")

    with pytest.raises(OwnershipError, match="does not own"):
        await svc.file_claim(pid, caller="mallory")


async def test_an_anonymous_caller_cannot_file_a_claim():
    """SCENARIO: no identity at all — the pre-fix default."""
    svc = _armed(InsuranceService({}))
    pid = await _policy(svc)

    with pytest.raises(OwnershipError, match="required"):
        await svc.file_claim(pid)


async def test_a_stranger_cannot_cancel_someone_elses_policy():
    """SCENARIO: the SIBLING authority path (NEW-78b).

    Found by sweeping every mutating method on the service after file_claim's
    hole was confirmed — the rule being that a partial authority fix is worse
    than a uniformly broken one, because it makes the surface look audited.
    cancel_policy is live on the dispatcher as `cancel_insurance` and is in
    _STATE_MODIFYING_ACTIONS. Pre-fix, anyone who learned a policy id could
    terminate a stranger's coverage."""
    svc = _armed(InsuranceService({}))
    pid = await _policy(svc, holder="alice")

    with pytest.raises(OwnershipError, match="does not own"):
        await svc.cancel_policy(pid, caller="mallory")
    with pytest.raises(OwnershipError, match="required"):
        await svc.cancel_policy(pid)

    assert svc._policies[pid]["status"] == "active", "coverage was terminated"
    assert (await svc.cancel_policy(pid, caller="alice"))["status"] != "error"


def test_every_mutating_policy_method_is_accounted_for():
    """The sweep itself, kept executable.

    Rule 27 says every SIBLING authority path must be checked before an
    authority fix is called complete. A one-time manual sweep decays; this
    fails when a new mutating method appears, forcing the same triage rather
    than letting the next one be forgotten — the exact failure NEW-77 exists
    to prevent.

    Each name below is a decision, not a suppression:
      file_claim, cancel_policy      OWNERSHIP ASSERTED
      create_policy, create_parametric_policy
                                     CREATION — no prior record to own; the
                                     caller names the holder because they are
                                     establishing it, not acting on it
      get_policy                     READ path (lazily refreshes status); a
                                     disclosure question, not a custody one,
                                     and deliberately not conflated with it
      auto_settle_claim, check_triggers
                                     OPERATOR paths, not holder paths. They
                                     decide from the oracle, not the caller.
                                     Their authority question is "who may run
                                     settlement", which is NEW-82's territory.
    """
    import ast
    import inspect

    tree = ast.parse(inspect.getsource(InsuranceService)).body[0]
    mutating = set()
    for node in tree.body:
        if not isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
            continue
        if node.name.startswith("_"):
            continue
        body = ast.unparse(node)
        if any(t in body for t in ("self._policies[", "self._claims[", "_reserve_fund")):
            mutating.add(node.name)

    triaged = {
        "file_claim", "cancel_policy",
        "create_policy", "create_parametric_policy",
        "get_policy", "auto_settle_claim", "check_triggers",
    }
    assert mutating <= triaged, (
        f"new mutating method(s) with no ownership triage: {sorted(mutating - triaged)}"
    )


def test_new_82_is_recorded_as_open_not_silently_assumed_closed():
    """THE BOUNDARY OF THIS COMMIT, made load-bearing.

    assert_owner can only compare the caller it is HANDED. On the gateway
    route that caller is authenticated; on ServiceDispatcher it is whatever
    the requester typed, because execute() does `await method(**params)`.
    So `file_insurance_claim` with caller="<victim>" still impersonates.

    That is NOT fixed here — deliberately, because it is a seam-wide problem
    affecting every service method taking a caller/holder/creator, and a
    per-method patch in one service would make the seam LOOK audited while
    leaving the general case open.

    This test exists so the gap cannot be quietly inherited as closed. It
    fails the moment the dispatcher grows identity binding — which is the
    moment to re-read this commit and delete the caveat.
    """
    import inspect

    from runtime.blockchain.services import service_dispatcher as sd

    src = inspect.getsource(sd.ServiceDispatcher.execute)
    assert "await method(**params)" in src, (
        "ServiceDispatcher.execute no longer forwards raw caller-supplied "
        "params — NEW-82 may now be closed. Re-read the SURFACE CAVEAT on "
        "InsuranceService.file_claim and update it."
    )

    doc = inspect.getdoc(InsuranceService.file_claim) or ""
    assert "SURFACE CAVEAT" in doc and "NEW-82" in doc


# ── NEW-78: verification comes from the oracle, not the claimant ─────────


def test_file_claim_no_longer_accepts_caller_supplied_trigger_data():
    """The parameter is GONE, not ignored. A signature that still accepts it
    invites a caller to keep sending it and a future reader to re-wire it."""
    params = inspect.signature(InsuranceService.file_claim).parameters
    assert "trigger_data" not in params
    assert "caller" in params


def test_the_self_attesting_verifier_is_deleted_not_guarded():
    """SCENARIO: the fundraising lesson applied. A guarded-but-present
    fallback is one refactor from being live again — that is exactly how the
    milestone self-attesting fallback became the live path.

    Asserted against EXECUTING code, so the module can keep documenting what
    it removed without the documentation silencing the control."""
    assert not hasattr(ClaimsProcessor, "_verify_trigger")

    assert "trigger_data" not in _executing_code(cp_module), (
        "ClaimsProcessor still reads claimant-supplied trigger data"
    )


def test_process_claim_cannot_decide_without_an_explicit_verdict():
    """`verified` is keyword-only and non-defaulting on purpose: a caller who
    forgets it gets a TypeError, never a silent approval."""
    params = inspect.signature(ClaimsProcessor.process_claim).parameters
    assert params["verified"].kind is inspect.Parameter.KEYWORD_ONLY
    assert params["verified"].default is inspect.Parameter.empty


async def test_the_owner_cannot_self_approve_with_invented_evidence():
    """SCENARIO: the true holder files with fabricated proof. Pre-fix this
    was an approved $5,000 payout; the claimant simply wrote the numbers."""
    svc = _armed(InsuranceService({}))
    pid = await _policy(svc, holder="alice")

    result = await svc.file_claim(pid, caller="alice")

    assert result["status"] != "approved"
    assert svc._reserve_fund._balance == 90_000.0, "reserve was debited"


async def test_an_unavailable_oracle_is_reported_honestly():
    """SCENARIO: oracle unreachable. 'We could not check' must not be
    reported as 'the event did not happen' — both deny, but they are
    different facts and the claimant is owed the true one."""
    svc = _armed(InsuranceService({}))
    pid = await _policy(svc, holder="alice")

    result = await svc.file_claim(pid, caller="alice")
    assert "authority unavailable" in result.get("reason", "").lower()
    assert "not a determination that the event did not occur" in result["reason"]


# ── NEW-79: the preconditions my own NEW-67 delegation omitted ───────────


async def test_a_cancelled_policy_cannot_be_settled():
    """SCENARIO PREVIOUSLY MISSED: cancelled policy. Reproduced pre-fix as an
    approved $900 payout on a policy the holder had already cancelled."""
    svc = _armed(InsuranceService({}))
    pid = await _policy(svc, holder="alice", amount=900.0)
    await svc.cancel_policy(pid, caller="alice")  # NEW-78b: owner-only now
    assert svc._policies[pid]["status"] == "cancelled"

    result = await svc.auto_settle_claim(pid, {"delay_minutes": 999})

    assert result["status"] == "rejected"
    assert "not active" in result["reason"]


async def test_a_policy_cannot_be_settled_twice():
    """SCENARIO PREVIOUSLY MISSED: repeat settlement. Reproduced pre-fix as
    $1,500 paid on a $500 policy — three approvals, one policy."""
    svc = _armed(InsuranceService({}))
    pid = await _policy(svc, holder="alice", amount=500.0)

    # force one approved claim into the store, as a real settlement would
    svc._claims["c1"] = {"claim_id": "c1", "policy_id": pid, "status": "approved"}

    result = await svc.auto_settle_claim(pid, {"delay_minutes": 999})
    assert result["status"] == "rejected"
    assert "already been settled" in result["reason"]


async def test_an_expired_policy_cannot_be_settled():
    """SCENARIO: expiry — the third precondition file_claim had and
    auto_settle_claim did not."""
    svc = _armed(InsuranceService({}))
    pid = await _policy(svc, holder="alice")
    svc._policies[pid]["expires_at"] = int(time.time()) - 1

    result = await svc.auto_settle_claim(pid, {"delay_minutes": 999})
    assert result["status"] == "rejected"
    assert "expired" in result["reason"].lower()


# ── NEW-80: the parametric schema mismatch ──────────────────────────────


async def test_a_parametric_policy_can_be_verified_at_all():
    """SCENARIO PREVIOUSLY MISSED: parametric policy. Pre-fix every ppol_
    record was DENIED unconditionally — it wrote trigger_type/coverage_amount
    while the claim path read policy_type/coverage['amount'], so no oracle
    data could ever have approved one. The point is not that it approves; it
    is that it now carries the shape the claim path reads."""
    svc = _armed(InsuranceService({}))
    await svc._reserve_fund.deposit(90_000.0)
    rec = await svc.create_parametric_policy(
        holder="alice", trigger_type="flight_delay",
        trigger_params={"delay_minutes": 120},
        coverage_amount=1000.0, premium=500.0,
    )

    assert rec["policy_type"] == "flight_delay"
    assert rec["coverage"]["amount"] == 1000.0
    assert "expires_at" in rec
    assert rec.get("trigger_id"), "no trigger registered — nothing to verify against"
    assert rec["policy_id"] == rec["id"], "legacy `id` alias dropped"


async def test_filing_on_a_parametric_policy_does_not_crash():
    """SCENARIO: the parametric defect at its worst, found by probing rather
    than by reading — pre-fix, `file_claim` on a ppol_ record raised
    KeyError('expires_at') and never reached a decision at all.

    So the pre-fix state was not 'parametric claims are denied'. It was:
    auto_settle_claim denied every one unconditionally, AND the primary claim
    path crashed on every one. Parametric policies were uncollectable by
    construction on both paths — while create_parametric_policy took a
    premium. This pins the crash leg separately from the schema keys, because
    a future edit could restore the keys and still leave the path raising."""
    svc = _armed(InsuranceService({}))
    await svc._reserve_fund.deposit(90_000.0)
    rec = await svc.create_parametric_policy(
        holder="alice", trigger_type="flight_delay",
        trigger_params={"delay_minutes": 120},
        coverage_amount=1000.0, premium=500.0,
    )

    result = await svc.file_claim(rec["policy_id"], caller="alice")
    assert result["status"] in {"denied", "rejected"}
    assert svc._reserve_fund._balance == 90_000.0

    with pytest.raises(OwnershipError):
        await svc.file_claim(rec["policy_id"], caller="mallory")


# ── NEW-81: the dead settle route ───────────────────────────────────────


def test_the_dead_settle_route_is_gone_from_both_tables():
    """SCENARIO: a route naming a method that never existed. 404 on every
    request since it was written."""
    src = (REPO / "gateway/service_routes.py").read_text()
    live = [
        ln for ln in src.splitlines()
        if "/api/v1/insurance/claim/settle" in ln
        and not ln.strip().startswith("#")
    ]
    assert live == [], f"route still registered: {live}"

    handler_refs = [
        ln for ln in src.splitlines()
        if "_handle_claim_settle" in ln and not ln.strip().startswith("#")
    ]
    assert handler_refs == [], f"dangling handler reference: {handler_refs}"


def test_settle_claim_never_existed_and_still_does_not():
    """Pins WHY the route was dead, so nobody 're-fixes' it by adding a stub
    named settle_claim instead of routing to the real method."""
    assert not hasattr(InsuranceService, "settle_claim")
    assert hasattr(InsuranceService, "auto_settle_claim")


def test_the_route_module_still_constructs():
    """Presence of a definition is not execution — domain 4's dangling
    handlers crashed the router at construction."""
    import importlib

    assert importlib.import_module("gateway.service_routes") is not None
