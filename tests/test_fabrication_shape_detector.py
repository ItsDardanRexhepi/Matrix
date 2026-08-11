"""D6 — repo-wide fabrication-shape detector (promoted from NEW-61).

NEW-61 culled ten methods from the defi service that shared one body shape:
mint a uuid, set a hardcoded success status, write the dict into an in-process
store, return it — with no await and no external call. The cull was scoped to
the SERVICE. The shape is not confined to that service, so the pattern, not the
package, is the unit of work. This promotes the defi-scoped shape test to a
repo-wide CI control alongside D1 (route sweep), D2 (handler collapse)
and D5 (intent/action contract). D5 was already taken; this is D6.

WHAT IT MEASURES — and what it deliberately does NOT claim
Purely structural: a public method in a service class that
  * calls uuid4()/uuid1(),
  * assigns into a `self.<store>[...]`,
  * contains a hardcoded "status": "<literal>" in a dict, and
  * has ZERO await expressions.

MEASURED: 50 at introduction (not the 11 a preliminary sweep reported — the
ratchet takes the measured number). NOW 49: NEW-67 delegated
insurance.auto_settle_claim to the real claims processor, so it awaits and no
longer matches the shape. That is the burn-down working — the entry was struck
rather than left stale, and the ratchet tightened with it.

The shape does NOT by itself mean "fabrication". Some hits are legitimate local
record-keeping: a governance proposal, a filed appeal, a moderation report, a
subscription plan, a DEX pool ARE records, and creating one locally is the
honest operation. Others assert that something happened OUTSIDE the process —
value moved, a counterparty was paid, a contract was deployed — while only
writing a dict, and those are the NEW-61 pattern proper.

NO STRUCTURAL TEST SEPARATES THE TWO. I tried: the presence of a
not_deployed_response gate looked like a discriminator (7 gated / 43 ungated),
but it is not — cross_border.remit ("sent"), fundraising.buy_carbon_credit
("purchased") and agent_identity.sell_training_data ("sold") are all UNGATED
and all assert external value movement. Ungated does not mean local; it often
means nobody gated it, which is exactly the gate-asymmetry finding in
test_gate_asymmetry_ratchet below. Telling the two apart requires reading the
body — the standing rule — so the split is a per-domain census judgment, not
something this detector adjudicates.

WHAT THE CONTROL THEREFORE DOES
Freezes the 50 BY NAME. A new instance fails. An entry may only leave the list
by being fixed or by being reviewed and reclassified in its domain's census,
and the list may only shrink. Freezing by name rather than by count means the
ratchet cannot be satisfied by removing one instance and adding another.
"""

from __future__ import annotations

import ast
import pathlib

SERVICES = pathlib.Path(__file__).resolve().parent.parent / (
    "runtime/blockchain/services"
)


# ── The detector ──────────────────────────────────────────────────────────


def _shape(fn: ast.AST) -> tuple[bool, bool, bool, bool]:
    """Return (mints_uuid, writes_store, has_await, has_status_literal)."""
    mints = writes = awaits = status = False
    for node in ast.walk(fn):
        if isinstance(node, ast.Await):
            awaits = True
        elif isinstance(node, ast.Call):
            name = getattr(node.func, "attr", None) or getattr(
                node.func, "id", None
            )
            if name in ("uuid4", "uuid1"):
                mints = True
        elif isinstance(node, ast.Assign):
            for target in node.targets:
                if (
                    isinstance(target, ast.Subscript)
                    and isinstance(target.value, ast.Attribute)
                    and isinstance(target.value.value, ast.Name)
                    and target.value.value.id == "self"
                ):
                    writes = True
        elif isinstance(node, ast.Dict):
            for key, value in zip(node.keys, node.values):
                if (
                    isinstance(key, ast.Constant)
                    and key.value == "status"
                    and isinstance(value, ast.Constant)
                    and isinstance(value.value, str)
                ):
                    status = True
    return mints, writes, awaits, status


def find_fabrication_shape() -> set[str]:
    """Every public service method matching the shape, as 'module::Class.method'."""
    found: set[str] = set()
    for path in sorted(SERVICES.rglob("*.py")):
        try:
            tree = ast.parse(path.read_text())
        except SyntaxError:
            continue
        module = str(path.relative_to(SERVICES))
        for cls in [n for n in ast.walk(tree) if isinstance(n, ast.ClassDef)]:
            for fn in cls.body:
                if not isinstance(fn, (ast.FunctionDef, ast.AsyncFunctionDef)):
                    continue
                if fn.name.startswith("_"):
                    continue
                mints, writes, awaits, status = _shape(fn)
                if mints and writes and status and not awaits:
                    found.add(f"{module}::{cls.name}.{fn.name}")
    return found


# ── The frozen inventory (measured 2026-08-11; ratchet: may only shrink) ──
#
# 50 at introduction -> 49 after NEW-67 (auto_settle_claim delegated).

KNOWN_FABRICATION_SHAPE = {
    "agent_identity/service.py::AgentIdentityService.trade_model_access",
    "agent_identity/service.py::AgentIdentityService.sell_training_data",
    "cross_border/service.py::CrossBorderService.bridge_transfer",
    "cross_border/service.py::CrossBorderService.remit",
    "dao_management/factory.py::DAOFactory.deploy",
    "dex/pools.py::LiquidityPoolManager.create_pool",
    "did_identity/service.py::DIDService.create_did",
    "dispute_resolution/appeals.py::Appeals.file_appeal",
    "dispute_resolution/service.py::DisputeResolution.request_arbitration",
    "fundraising/milestone_verification.py::MilestoneVerification.submit_milestone",
    "fundraising/refunds.py::RefundManager.request_refund",
    "fundraising/refunds.py::RefundManager.process_refunds",
    "fundraising/service.py::FundraisingService.create_campaign",
    "fundraising/service.py::FundraisingService.buy_carbon_credit",
    "fundraising/service.py::FundraisingService.retire_carbon_credit",
    "fundraising/service.py::FundraisingService.buy_renewable_cert",
    "fundraising/service.py::FundraisingService.invest_green_bond",
    "fundraising/vesting.py::VestingManager.create_vesting",
    "gaming/milestone_funding.py::MilestoneFunding.create_funding",
    "gaming/service.py::GamingService.register_game",
    "gaming/service.py::GamingService.enter_tournament",
    "gaming/service.py::GamingService.trade_item",
    "gaming/service.py::GamingService.attest_achievement",
    "gaming/service.py::GamingService.create_prediction_market",
    "gaming/service.py::GamingService.place_prediction_bet",
    "gaming/service.py::GamingService.resolve_market",
    "gaming/vetting.py::VettingPipeline.submit_for_review",
    "governance/service.py::GovernanceService.create_proposal",
    "governance/service.py::GovernanceService.propose_multisig",
    "governance/service.py::GovernanceService.parameter_change",
    "insurance/service.py::InsuranceService.create_parametric_policy",
    "insurance/trigger_manager.py::TriggerManager.register_trigger",
    "ip_royalties/distribution.py::RoyaltyDistribution.claim",
    "ip_royalties/ip_registry.py::IPRegistry.register",
    "ip_royalties/service.py::IPRoyaltyService.grant_license",
    "ip_royalties/service.py::IPRoyaltyService.execute_agreement",
    "loyalty/programs.py::ProgramManager.create_program",
    "marketplace/appeals.py::AppealProcess.file_appeal",
    "marketplace/compliance_filter.py::ComplianceFilter.flag_listing",
    "nft_services/service.py::NFTService.fractionalize",
    "nft_services/service.py::NFTService.rent",
    "nft_services/service.py::NFTService.mint_soulbound",
    "rwa_tokenization/legal_bridge.py::LegalBridge.create_legal_wrapper",
    "securities_exchange/exchange.py::ExchangeContract.place_order",
    "securities_exchange/negotiation.py::TermsNegotiation.create_offer",
    "social/content_moderation.py::ContentModeration.report_content",
    "staking/pools.py::StakingPoolManager.create_pool",
    "subscriptions/grace_period.py::GracePeriodManager.enter_grace",
    "subscriptions/service.py::SubscriptionService.create_plan",
}


def test_no_new_fabrication_shape_instances():
    """THE RATCHET. A new instance of the shape fails CI.

    If this fails on code you just wrote, the method mints a uuid, stamps a
    success status, stores a dict and awaits nothing. Either it should do real
    work, or it should say plainly that it does not (the RECORDED_UNSETTLED
    idiom: settled=False / value_moved=False), or — if it is genuinely a local
    record and nothing more — add it here WITH a one-line justification in the
    review that says why the record is the whole operation.
    """
    current = find_fabrication_shape()
    new = current - KNOWN_FABRICATION_SHAPE
    assert not new, (
        "new fabrication-shape method(s) — mint a uuid, stamp a status, store "
        f"a dict, await nothing:\n  " + "\n  ".join(sorted(new))
    )


def test_the_inventory_only_shrinks():
    """The list must not accumulate stale entries.

    An entry that no longer matches has been fixed or removed; drop it from
    KNOWN_FABRICATION_SHAPE so the ratchet tightens. This is what converts a
    frozen list into a burn-down.
    """
    current = find_fabrication_shape()
    stale = KNOWN_FABRICATION_SHAPE - current
    assert not stale, (
        "these no longer match the shape — remove them from "
        f"KNOWN_FABRICATION_SHAPE to tighten the ratchet:\n  "
        + "\n  ".join(sorted(stale))
    )


def test_the_detector_actually_detects():
    """Positive control: the detector must fire on a known instance.

    Without this, an inventory test passes trivially if the detector silently
    stops matching anything — the failure mode where a control reports 'all
    clear' because it went blind. Asserted against a synthetic body so it does
    not depend on any particular production method surviving.
    """
    synthetic = ast.parse(
        "class S:\n"
        "    def make(self):\n"
        "        rid = uuid.uuid4().hex\n"
        "        rec = {'id': rid, 'status': 'executed'}\n"
        "        self._store[rid] = rec\n"
        "        return rec\n"
    )
    fn = synthetic.body[0].body[0]
    mints, writes, awaits, status = _shape(fn)
    assert (mints, writes, awaits, status) == (True, True, False, True)

    # and it must NOT fire on a method that does real awaited work
    honest = ast.parse(
        "class S:\n"
        "    async def make(self):\n"
        "        rid = uuid.uuid4().hex\n"
        "        rec = {'id': rid, 'status': 'executed'}\n"
        "        await self._chain.send(rec)\n"
        "        self._store[rid] = rec\n"
        "        return rec\n"
    )
    fn2 = honest.body[0].body[0]
    assert _shape(fn2)[2] is True, "await not detected — the filter is blind"


def test_the_measured_count_is_recorded():
    """The number in the ratchet is the MEASURED one.

    A preliminary sweep reported 11 instances; the detector measures 50. The
    discrepancy is recorded here rather than smoothed over, because the ratchet
    is only as honest as the census behind it.
    """
    assert len(KNOWN_FABRICATION_SHAPE) == 49
    assert len(find_fabrication_shape()) == 49


# ── Gate asymmetry (NEW-65b) ─────────────────────────────────────────────


def _is_gated(fn: ast.AST) -> bool:
    for node in ast.walk(fn):
        if isinstance(node, ast.Call):
            name = getattr(node.func, "attr", None) or getattr(
                node.func, "id", None
            )
            if name == "not_deployed_response":
                return True
    return False


def _mutates(fn: ast.AST) -> bool:
    for node in ast.walk(fn):
        if isinstance(node, ast.Assign):
            for target in node.targets:
                if (
                    isinstance(target, ast.Subscript)
                    and isinstance(target.value, ast.Attribute)
                    and isinstance(target.value.value, ast.Name)
                    and target.value.value.id == "self"
                ):
                    return True
        if isinstance(node, ast.Call):
            f = node.func
            if (
                isinstance(f, ast.Attribute)
                and f.attr in ("append", "update", "setdefault", "pop")
                and isinstance(f.value, ast.Attribute)
                and isinstance(f.value.value, ast.Name)
                and f.value.value.id == "self"
            ):
                return True
    return False


def find_gate_asymmetry() -> dict[str, list[str]]:
    """Classes that HAVE a deployment gate but leave a state-modifying
    sibling ungated. Keyed 'module::Class' -> ungated mutating method names."""
    out: dict[str, list[str]] = {}
    for path in sorted(SERVICES.rglob("*.py")):
        text = path.read_text()
        if "not_deployed_response" not in text:
            continue
        try:
            tree = ast.parse(text)
        except SyntaxError:
            continue
        module = str(path.relative_to(SERVICES))
        for cls in [n for n in ast.walk(tree) if isinstance(n, ast.ClassDef)]:
            gated, ungated_mutating = [], []
            for fn in cls.body:
                if not isinstance(fn, (ast.FunctionDef, ast.AsyncFunctionDef)):
                    continue
                if fn.name.startswith("_"):
                    continue
                if _is_gated(fn):
                    gated.append(fn.name)
                elif _mutates(fn):
                    ungated_mutating.append(fn.name)
            if gated and ungated_mutating:
                out[f"{module}::{cls.name}"] = sorted(ungated_mutating)
    return out


KNOWN_GATE_ASYMMETRY = {
    "defi/loans.py::LoanManager": ["liquidate", "repay_loan", "update_pool_total"],
    "dex/service.py::DEXService": ["add_liquidity", "remove_liquidity"],
    "insurance/service.py::InsuranceService": ["file_claim"],
    "ip_royalties/service.py::IPRoyaltyService": ["license_ip", "transfer_ip"],
    "privacy/service.py::PrivacyService": ["get_privacy_commitment"],
    "rwa_tokenization/service.py::RWAService": ["tokenize_asset"],
    "staking/service.py::StakingService": ["claim_rewards"],
}


def test_no_new_gate_asymmetry():
    """NEW-65b — 'this service is gated' has never been a service-level
    property in this codebase, only a per-method accident.

    MEASURED: 7 classes, 11 ungated state-modifying methods, each inside a
    class whose author DID establish a deployment gate on a sibling. The gate
    documents an intention the code does not enforce.

    The sharpest instance: staking.stake is gated while claim_rewards is not —
    a user can be refused permission to OPEN a position and still 'claim'
    rewards on the position they were never allowed to open.

    This is the shape that produced NEW-64: DeFiService.create_loan gated, the
    collateral siblings not, so the service looked gated while exposing an
    ungated value path. Every gate claim needs per-method verification.
    """
    current = find_gate_asymmetry()
    new = {
        k: v for k, v in current.items()
        if k not in KNOWN_GATE_ASYMMETRY
        or set(v) - set(KNOWN_GATE_ASYMMETRY.get(k, []))
    }
    assert not new, (
        "new ungated state-modifying method(s) in a class that gates a "
        f"sibling:\n  {new}"
    )


def test_the_gate_asymmetry_count_is_recorded():
    current = find_gate_asymmetry()
    assert len(current) == 7
    assert sum(len(v) for v in current.values()) == 11
