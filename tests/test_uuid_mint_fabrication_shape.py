"""D6 — repo-wide UUID-MINT-NO-AWAIT shape detector (promoted from NEW-61).

RENAMED 2026-08-11, and the rename is the point. This was called
`test_fabrication_shape_detector.py` — "the fabrication shape detector" — a
name that promises coverage of the whole fabrication class. It does not have
it. The shape below requires ZERO awaits, so a fabrication that awaits local
helpers is invisible to it. `CrossBorderService.send_payment` — the largest
fabrication on the money path — awaits compliance, FX conversion and
attestation, all in-process, and slips through.

A control whose NAME overstates its SCOPE is the same defect as a method whose
docstring overstates its behaviour, and this engagement has found seven of
those. Green here means "no new uuid-mint-no-await instances", not "no new
fabrications". The delivery-claim half is D7
(`test_fake_delivery_detector.py`), which detects on a different axis: what a
method CLAIMS rather than what it LACKS.

Widening this shape to cover D7's class was tried and measured, and it is
wrong in both directions — it drops 5 known instances and falsely flags
`InsuranceService.file_claim`, which NEW-78 had just made genuinely real. Two
detectors, two axes, is the honest structure. Do not merge them without
re-running that measurement.


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

from tests import refusal_primitives
from tests.state_mutation import (
    MUTATING_CALLS as _MUTATING_CALLS,
    base_name as _base_name,
    mutates_service_state,
    state_aliases as _state_aliases,
)

SERVICES = pathlib.Path(__file__).resolve().parent.parent / (
    "runtime/blockchain/services"
)


# ── The detector ──────────────────────────────────────────────────────────


def _shape(fn: ast.AST) -> tuple[bool, bool, bool, bool]:
    """Return (mints_uuid, writes_store, has_await, has_status_literal).

    ALIAS-AWARE SINCE 2026-08-12, matching `_mutates`. The store-write clause
    had the same blind spot the gate-asymmetry side did (NEW-99): it saw only
    `self.<store>[k] = v` and missed the ordinary idiom

        record = self._rights.get(key)   # alias
        record["updated_at"] = now       # write through it

    KNOWN REMAINING GAP, MEASURED AND STATED RATHER THAN LEFT IMPLICIT.
    This clause still counts only ASSIGNMENTS. `_mutates` also counts mutating
    CALLS (`append`/`setdefault`/`pop`/…); this does not, so a method that
    records its fabrication with `self._store.append(...)` instead of
    `self._store[k] = ...` is invisible here.

    Measured 2026-08-12: closing that gap too would take the inventory from 47
    to 52. The five it would add are

        governance/service.py::GovernanceService.queue_timelock
        rwa_tokenization/service.py::RWAService.fractional_buy
        social/service.py::SocialService.follow_wallet
        social/service.py::SocialService.publish_post
        supply_chain/service.py::SupplyChainService.log_event

    They are NOT added here, because each needs the same individual
    adjudication the alias entry got — the NFTService.process_sale rejection is
    why raw detector output never enters this list. The number is recorded so
    that 47 is read as "47 under an assignment-only write clause", not as a
    measurement of the whole shape. A count whose scope is undocumented is the
    same defect as a control whose name overstates it.
    """
    mints = writes = awaits = status = False
    aliases = _state_aliases(fn)
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
                if not isinstance(target, ast.Subscript):
                    continue
                if (
                    isinstance(target.value, ast.Attribute)
                    and isinstance(target.value.value, ast.Name)
                    and target.value.value.id == "self"
                ):
                    writes = True
                elif _base_name(target) in aliases:
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
# 50 at introduction -> 49 after NEW-67 (auto_settle_claim delegated) -> 46 as
# domain censuses struck entries -> 47 on the 2026-08-12 alias re-baseline.
#
# RE-BASELINE 2026-08-12 — 46 -> 47.  UPWARD, AND A CORRECTION.
#   OLD: 46.  NEW: 47.  DATE: 2026-08-12.
#   MECHANISM: `_shape`'s store-write clause matched only
#   `self.<store>[k] = v` and was blind to a write through an alias bound from
#   service state — the same gap NEW-99 closed on the gate-asymmetry side, in
#   the sibling function, left half-fixed for one commit.
#   Nothing in the platform changed on this date. The detector did.
#
#   THE ONE ENTRY ADDED WAS ADJUDICATED INDIVIDUALLY, not taken from detector
#   output (the NFTService.process_sale rejection under NEW-99 is why):
#     nft_services/rights.py::RightsManagement.transfer_rights
#       - TRUE shape member: mints rt_<uuid>, writes `record["updated_at"]`
#         and `right["holder"]` through an alias of self._rights, returns a
#         hardcoded "status": "transferred", awaits nothing.
#       - BUT PROBABLY CATEGORY 1, not a fabrication. rights.py carries no
#         gate at all, and for LICENSING RIGHTS the platform ledger plausibly
#         IS the artifact — the same reasoning that exempted
#         SupplyChainService.transfer_custody from D7 ("for custody, the record
#         IS the asset"). Unlike token OWNERSHIP, which domain 9 established
#         lives on-chain, there is no external rights registry this contradicts.
#       - It is listed because this inventory has always contained legitimate
#         local records (see the module docstring: a proposal, an appeal, a
#         moderation report). Membership means "matches the shape", not
#         "is a fabrication".
#       - HONEST NOTE: domain 9 closed without ever seeing this entry. The
#         disposition would probably not have changed, but it was never put to
#         the test. Filed known-and-dispositioned for the Phase-6 detector-delta
#         pass rather than reopening the domain.

# STRUCK 2026-08-12 (47 -> 46): governance/service.py::GovernanceService.create_proposal
#   IT WAS NOT FIXED — the shape stopped matching. Cluster A step 2 replaced its
#   unconditional `take_snapshot(pid, {})` with a guarded `await` on a balance
#   source, and this shape requires ZERO awaits. Recorded explicitly because an
#   entry leaving for a STRUCTURAL reason rather than a behavioural one is
#   exactly what a ratchet must not accept silently.
#   Its census verdict is unchanged: category 5 (it planted an empty snapshot
#   that shadowed real balance state), never a fabrication — a proposal record
#   IS the artifact. Its presence here was always a shape match, not a finding.
KNOWN_FABRICATION_SHAPE = {
    # ADDED 2026-08-12 (46 -> 47) — and it became VISIBLE rather than newly
    # wrong. Cluster B moved queue_timelock's write from
    # `self._proposals.setdefault(...)` (a CALL, which this shape's
    # assignment-only clause cannot see) to `self._timelocks[id] = record` (an
    # ASSIGN, which it can). The call-form gap documented in `_shape` closed
    # itself for this one method as a side effect of fixing the store
    # corruption.
    # ADJUDICATED HONEST: it now returns `recorded_unqueued` with `executed:
    # False` and a disclosure stating no timelock executor exists. A shape
    # member, not a fabrication — the distinction this inventory has always
    # carried.
    "governance/service.py::GovernanceService.queue_timelock",
    "nft_services/rights.py::RightsManagement.transfer_rights",
    "agent_identity/service.py::AgentIdentityService.trade_model_access",
    "agent_identity/service.py::AgentIdentityService.sell_training_data",
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
    "governance/service.py::GovernanceService.propose_multisig",
    "governance/service.py::GovernanceService.parameter_change",
    # NEW-80 (2026-08-11): create_parametric_policy left the shape. It now
    # awaits TriggerManager.register_trigger, so the record it writes is
    # bound to something a later claim can actually be checked against.
    # 49 -> 48.
    "insurance/trigger_manager.py::TriggerManager.register_trigger",
    "ip_royalties/distribution.py::RoyaltyDistribution.claim",
    "ip_royalties/ip_registry.py::IPRegistry.register",
    "ip_royalties/service.py::IPRoyaltyService.grant_license",
    "ip_royalties/service.py::IPRoyaltyService.execute_agreement",
    "loyalty/programs.py::ProgramManager.create_program",
    "marketplace/appeals.py::AppealProcess.file_appeal",
    "marketplace/compliance_filter.py::ComplianceFilter.flag_listing",
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

    BURN-DOWN: 50 at introduction -> 49 (NEW-67) -> 48 (NEW-80) -> 46
    (NEW-86 delegated remit, NEW-87 disabled bridge_transfer). Both were on
    BOTH detectors' lists; a fix has to tighten every ratchet it clears, or
    the next reader inherits a stale inventory.

    THEN 46 -> 47 ON 2026-08-12, UPWARD, AND A CORRECTION rather than a
    regression — `_shape`'s write clause became alias-aware, closing the gap
    NEW-99 had closed on the sibling function one commit earlier. Nothing in
    the platform changed on that date; the detector stopped being blind. The
    single added entry was adjudicated individually before being listed. See
    the re-baseline block above KNOWN_FABRICATION_SHAPE, and `_shape`'s
    docstring for the call-form gap that remains OPEN and measured (+5).
    """
    assert len(KNOWN_FABRICATION_SHAPE) == 46
    assert len(find_fabrication_shape()) == 46


# ── Gate asymmetry (NEW-65b) ─────────────────────────────────────────────


def _is_gated(fn: ast.AST) -> bool:
    """True if this method can return an honest refusal.

    Matches EVERY registered refusal primitive, not just the base one. See
    tests/refusal_primitives.py: NEW-94 wrapped `not_deployed_response` in
    `staking_not_deployed` and this detector, which matched one literal name,
    stopped seeing the staking package entirely — while its count fell, which
    read as progress.
    """
    for node in ast.walk(fn):
        if isinstance(node, ast.Call):
            name = getattr(node.func, "attr", None) or getattr(
                node.func, "id", None
            )
            if refusal_primitives.is_refusal_name(name):
                return True
    return False


def _mutates(fn: ast.AST) -> bool:
    """True if this method mutates service state.

    DELEGATES to tests/state_mutation.py. That rule has been wrong twice and
    fixed twice (NEW-99 alias writes, NEW-99b the sibling clause in this same
    file), and D11 is now a third consumer — three copies of a twice-corrected
    rule is the vocabulary-drift problem in a new costume. One implementation,
    every consumer.
    """
    return mutates_service_state(fn)


def find_gate_asymmetry() -> dict[str, list[str]]:
    """Classes that HAVE a deployment gate but leave a state-modifying
    sibling ungated. Keyed 'module::Class' -> ungated mutating method names."""
    out: dict[str, list[str]] = {}
    for path in sorted(SERVICES.rglob("*.py")):
        text = path.read_text()
        # The file-level skip must ask about EVERY refusal primitive. When it
        # asked only about the base name, NEW-94's wrapper made the whole
        # staking package invisible here — and the resulting drop in the count
        # looked exactly like a fix.
        if not refusal_primitives.mentions_refusal(text):
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


# ══════════════════════════════════════════════════════════════════════════
# RE-BASELINE 2026-08-12 — 6 classes / 10 methods  ->  7 classes / 15 methods
# ══════════════════════════════════════════════════════════════════════════
#
# THE NUMBER WENT UP AND THAT IS A CORRECTION, NOT A REGRESSION. Nothing in
# the platform got worse on this date. `_mutates` got honest.
#
# MECHANISM. The old `_mutates` matched exactly two syntactic shapes —
# `self.<store>[k] = v` and `self.<store>.append(...)` — and was blind to the
# ORDINARY Python idiom for mutating a nested structure:
#
#     dao = await self.get_dao(dao_id)     # bind an alias to service state
#     dao["members"].append(record)        # mutate through the alias
#     dao["member_count"] = len(...)
#
# That is how DAOService.join_dao and .leave_dao change persistent membership.
# The class has two GATED methods (create_dao, treasury_transfer) and three
# ungated siblings, one of which takes a `stake: float` and one of which
# returns "stake_returned" — the exact asymmetry this detector exists to find —
# and it reported nothing.
#
# THIS IS A SECOND, DISTINCT BLINDING MECHANISM. The first (staking, NEW-94c)
# was VOCABULARY drift: a wrapper renamed the refusal primitive and the
# detector stopped matching. The shared registry fixed that. This one is a
# SHAPE mismatch — nothing was renamed, and the registry cannot help. A
# syntactic detector is blind to every semantically equivalent form it did not
# enumerate, and the form missed here is the default way Python mutates a
# nested structure. The blind spot was therefore not an edge case; it was a
# large fraction of ordinary code.
#
# EVERY CLEAN READING TAKEN AGAINST THE OLD NUMBER WAS FALSE ASSURANCE,
# including the 6/10 recorded in the domain-10 close. A number wrong in the
# direction of comfort is worse than a larger honest one.
#
# THE FIVE ADDED ENTRIES WERE EACH ADJUDICATED BY HAND before entering this
# list, because a detector fix that over-fires produces false alarms and false
# alarms are how a detector gets muted. One candidate was REJECTED:
# NFTService.process_sale, whose `sale_result = dict(sale_result)` rebinds the
# name to a local copy (the NEW-90 fix). Firing there would have flagged the
# very method where the aliasing bug was corrected. See `_state_aliases`.
#
# REACH-BACK, and it is not hypothetical: this detector has been blind for
# every domain closed so far. Re-running it across all ten closed domains is a
# REQUIRED Phase-6 item, not a sweep candidate.
#
# NOTE, five instances now: get_policy and get_privacy_commitment are `get_`
# methods that WRITE. With staking's get_position, governance's get_proposal
# auto-expire, and insurance's get_policy, that is a pattern — and it is why
# the staking read exemption had to be an enumerated whitelist rather than a
# naming convention.
# ══════════════════════════════════════════════════════════════════════════

KNOWN_GATE_ASYMMETRY = {
    # + join_dao / leave_dao: alias-mutation, invisible before the fix
    "dao_management/service.py::DAOService": ["join_dao", "leave_dao"],
    "defi/loans.py::LoanManager": ["liquidate", "repay_loan", "update_pool_total"],
    "dex/service.py::DEXService": ["add_liquidity", "remove_liquidity"],
    # + cancel_policy / get_policy: alias-mutation (get_policy WRITES on read)
    "insurance/service.py::InsuranceService": [
        "cancel_policy", "file_claim", "get_policy",
    ],
    "ip_royalties/service.py::IPRoyaltyService": ["license_ip", "transfer_ip"],
    "privacy/service.py::PrivacyService": ["get_privacy_commitment"],
    # + transfer_ownership: alias-mutation, and it reassigns token["owner"]
    "rwa_tokenization/service.py::RWAService": [
        "tokenize_asset", "transfer_ownership",
    ],
    # staking/service.py::StakingService — REMOVED by NEW-94 (was:
    # ["claim_rewards"]). The whole domain now gates on one switch, so the
    # class has no asymmetry left to record. Kept as a comment rather than
    # deleted: this was the exemplar the docstring below is written around,
    # and a reader needs to see that the entry left because it was fixed.
}


def test_no_new_gate_asymmetry():
    """NEW-65b — 'this service is gated' has never been a service-level
    property in this codebase, only a per-method accident.

    MEASURED at introduction: 7 classes, 11 ungated state-modifying methods,
    each inside a class whose author DID establish a deployment gate on a
    sibling. The gate documents an intention the code does not enforce.
    BURN-DOWN: 7/11 -> 6/10 (NEW-94 closed staking).

    The sharpest instance WAS staking: `stake` gated while `claim_rewards` was
    not — a user could be refused permission to OPEN a position and still
    'claim' rewards on the position they were never allowed to open. NEW-94
    fixed it by arming the domain as a unit.

    AND THE FIRST VERSION OF THIS NOTE GOT THE EVIDENCE WRONG, WHICH IS THE
    MORE USEFUL LESSON. It claimed the 7/11 -> 6/10 drop was an INDEPENDENT
    confirmation that the asymmetry was gone. It was not. NEW-94 wrapped
    `not_deployed_response` in `staking_not_deployed`, and this detector both
    matched that one literal name AND skipped whole files that never mention
    it — so the staking package became INVISIBLE here. An adversarial verifier
    disabled every staking gate and re-ran: still 6/10, still no staking entry.
    The count had fallen because the instrument stopped looking.

    A number that moves because the defect was fixed and a number that moves
    because the detector went blind are indistinguishable from the outside.
    The fix is tests/refusal_primitives.py — one shared registry of refusal
    primitives, imported by every name-matching detector, so registering a
    wrapper once restores all of them. With it registered, this detector reads
    all three staking files, sees 8 gated methods, finds no ungated mutating
    sibling, and the 6/10 is now evidence rather than an artefact. Proven by
    mutation: remove `claim_rewards`' gate and this test fails.

    Two things that domain taught, which this docstring now carries:

      * The asymmetry was LOAD-BEARING. `stake` was the sole writer of
        `_positions`, so gating it was the only reason the ungated siblings
        were inert. The class was not partly protected — it was starved, and
        a count of "1 gated" overstated what was actually enforced.
      * "Reads are safe" is not a valid way to close one of these. Staking's
        `get_position` accrues rewards as a side effect of being read, so the
        remaining six must be closed by reading each body, not by category.

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
    """RATCHET: 7/11 -> 6/10 (NEW-94) -> 7/15 (2026-08-12 alias re-baseline).

    THE LAST MOVE WAS UPWARD AND IT IS A CORRECTION, NOT A REGRESSION — see
    the re-baseline block above KNOWN_GATE_ASYMMETRY. Nothing got worse; the
    detector stopped being blind to alias mutation. A ratchet that silently
    moves up is indistinguishable from a ratchet that failed, so the reason
    lives next to the number.

    Tightened rather than relaxed. If a later change makes staking asymmetric
    again, `test_no_new_gate_asymmetry` fails on it as a NEW finding, which is
    the correct treatment — the domain gate is a control now, not a habit.
    """
    current = find_gate_asymmetry()
    assert len(current) == 7
    assert sum(len(v) for v in current.values()) == 15

    assert not [k for k in current if k.startswith("staking/")], (
        "staking has gate asymmetry again — NEW-94 armed the domain as a unit "
        "via runtime/blockchain/services/staking/arming.py, so a partially "
        "gated staking class means a method was added outside that scheme. "
        "See tests/test_staking_arming.py."
    )


def test_alias_mutation_is_detected_in_both_directions():
    """The 2026-08-12 fix, proven to DISCRIMINATE rather than merely to fire.

    A detector fix that over-fires is worse than the blind spot it closes:
    false alarms are how a detector gets muted, and this one nearly flagged
    NFTService.process_sale — the method where the aliasing bug was FIXED.
    """
    def m(src: str) -> bool:
        return _mutates(ast.parse(src.strip()).body[0])

    # FIRES — the ordinary idiom the old version missed
    assert m('''
async def f(self, i):
    dao = await self.get_dao(i)
    dao["members"].append({})
'''), "alias mutation is invisible again — the 2026-08-12 blind spot is back"

    assert m('''
async def f(self, i):
    p = self._policies.get(i)
    p["status"] = "expired"
''')

    # DOES NOT FIRE — an alias bound purely for READING
    assert not m('''
async def f(self, i):
    dao = await self.get_dao(i)
    return {"n": dao["member_count"], "members": list(dao["members"])}
'''), "the detector fires on a read-only alias — that is a false alarm"

    # DOES NOT FIRE — rebound to a local copy (the NEW-90 defensive copy)
    assert not m('''
async def f(self, i):
    r = await self._royalty.process(i)
    r = dict(r)
    r["status"] = "recorded_unsettled"
'''), (
        "the detector flags a defensive copy — it would fire on NEW-90's fix "
        "and teach the next reader to remove it"
    )

    # DOES NOT FIRE — a plain local with no relationship to service state
    assert not m('''
async def f(self):
    out = {}
    out["a"] = 1
''')

    # STILL FIRES — the classic shape must not regress
    assert m('''
async def f(self, i):
    self._store[i] = {}
''')
    assert m('''
async def f(self, x):
    self._log.append(x)
''')


def test_the_rejected_candidate_stays_rejected():
    """NFTService.process_sale was adjudicated and EXCLUDED. Pinned by name so
    a later loosening of `_state_aliases` cannot quietly re-admit it."""
    import inspect

    from runtime.blockchain.services.nft_services.service import NFTService

    fn = ast.parse(inspect.getsource(NFTService.process_sale).strip()).body[0]
    assert not _mutates(fn), (
        "process_sale is being read as service-state mutation again. Its "
        "`sale_result = dict(sale_result)` rebinds to a local copy (NEW-90). "
        "Re-read _state_aliases before accepting this."
    )
    assert "dao_management/service.py::DAOService" in KNOWN_GATE_ASYMMETRY
    assert "nft_services/service.py::NFTService" not in KNOWN_GATE_ASYMMETRY


def test_shape_write_detection_is_alias_aware_in_both_directions():
    """The 2026-08-12 `_shape` fix, proven to DISCRIMINATE.

    Same standard as `_mutates`: a detector fix that over-fires is worse than
    the blind spot, because false alarms are how a detector gets muted and a
    detector that fires on a defensive copy pressures the next reader to remove
    the copy.
    """
    def shape(src: str):
        return _shape(ast.parse(src.strip()).body[0])

    # FIRES — uuid + alias write + status literal + no await
    mints, writes, awaits, status = shape('''
def f(self, k):
    record = self._rights.get(k)
    record["updated_at"] = 1
    return {"id": uuid.uuid4().hex, "status": "transferred"}
''')
    assert (mints, writes, awaits, status) == (True, True, False, True), (
        "the alias write is invisible to _shape again"
    )

    # DOES NOT FIRE — alias bound purely for READING
    assert not shape('''
def f(self, k):
    record = self._rights.get(k)
    return {"id": uuid.uuid4().hex, "status": "ok", "n": record["count"]}
''')[1], "_shape counts a read-only alias as a store write"

    # DOES NOT FIRE — rebound to a defensive copy (the NEW-90 shape)
    assert not shape('''
def f(self, k):
    r = self._ledger.get(k)
    r = dict(r)
    r["status"] = "recorded_unsettled"
    return {"id": uuid.uuid4().hex, "status": "recorded_unsettled"}
''')[1], (
        "_shape flags a defensive copy — it would fire on NEW-90's fix"
    )

    # STILL FIRES — the classic shape must not regress
    assert shape('''
def f(self, k):
    self._store[k] = {}
    return {"id": uuid.uuid4().hex, "status": "created"}
''')[1]


def test_the_shape_inventory_is_at_the_documented_baseline():
    """46 under an ASSIGNMENT-ONLY write clause — the scope is part of the
    number. It was 47 until `NFTService.fractionalize` stopped matching the
    shape: it now awaits an on-chain ownership read before minting an id, so
    the ratchet tightened by one (the §CD sibling pass over NEW-89). See
    `_shape`'s docstring for the measured +5 the call-form gap would add,
    which is deliberately NOT included pending adjudication."""
    current = find_fabrication_shape()
    assert len(KNOWN_FABRICATION_SHAPE) == 46
    assert "nft_services/rights.py::RightsManagement.transfer_rights" in current
