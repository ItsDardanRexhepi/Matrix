"""Twenty-eight sentences across conversion, creator publishing, real estate,
brand rewards, identity updates, fundraising and the dispatcher, held to code.

Built true where the code could keep the promise:
  * the revenue enforcer's "owner-only setters" — `onlyOwner` was written into
    contracts that declare no owner, which did not compile; an owner-less
    contract gets a deployer-held guard, and a re-run does not charge twice;
  * "never raises" in _compile_and_deploy — an empty compile output raised
    StopIteration;
  * a decode fault after a 2xx is "unknown", not "never left this process";
  * a non-string endpoint's credential no longer reaches the caller;
  * the update monitor's "do not expand beyond authorised scope" — no bound
    from an empty set, and no check at all for non-capability_change types;
  * "individual user data is never exposed" — a config could lower the cohort
    floor to 1, the stats carried single-recipient min/max, and the targeting
    reason named the user's attributes;
  * "emitted on EVERY path" — two community-vote returns left it out;
  * "the same content hash cannot be registered twice" — update() bypassed
    the index;
  * "the ONLY legal transitions" — four writes skipped the check, one wrote
    initiated -> initiated; and the settlement recorded its own hash as the
    lock whether or not it locked;
  * "one constant so the two sides cannot drift" — the injection wrote the
    literal.

Corrected where the sentence was wrong: the fee recipient "always" from
config, the inert contract, the auditor that flags nothing, the "no
statements" verdict, the milestone release "verified with proof", the
readiness guard that "passes only for a real one", `start()` with "no
caller", the byline oracle, the ContextVar entry points, the lru_cache reason,
who a refusal names, and a present-tense "file_claim takes no caller".
"""

from __future__ import annotations

import asyncio
import inspect
import json
import re
import sys
import types
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent


def _prose(text: str) -> str:
    return re.sub(r"\s+", " ", re.sub(r"\s*#\s*", " ", text or ""))


# ── revenue enforcer ───────────────────────────────────────────────────────

NO_OWNER = """pragma solidity ^0.8.20;
contract Tip {
    uint256 public total;
    function tip() public payable {
        total += msg.value;
    }
}
"""

WITH_OWNER = """pragma solidity ^0.8.20;
import "@openzeppelin/contracts/access/Ownable.sol";
contract Tip is Ownable {
    constructor(address o) Ownable(o) {}
    function tip() public payable {}
}
"""

WALLET = "0x" + "ab" * 20


def _enforcer():
    from runtime.blockchain.services.contract_conversion.revenue_enforcer import RevenueEnforcer

    return RevenueEnforcer({"blockchain": {"platform_wallet": WALLET}})


def test_a_contract_without_an_owner_gets_setters_it_can_compile():
    out = _enforcer().inject_fee_logic(NO_OWNER)
    assert "onlyOwner" not in out, (
        "the setters name onlyOwner in a contract that declares none — "
        "an undeclared identifier, so the contract does not compile")
    assert "modifier onlyPlatformFeeAdmin()" in out
    assert out.count("external onlyPlatformFeeAdmin") == 2
    assert "platformFeeAdmin = msg.sender;" in out


def test_a_contract_with_an_owner_keeps_its_owner():
    out = _enforcer().inject_fee_logic(WITH_OWNER)
    assert out.count("external onlyOwner") == 2
    assert "platformFeeAdmin" not in out


def test_injecting_twice_does_not_charge_the_fee_twice():
    once = _enforcer().inject_fee_logic(NO_OWNER)
    twice = _enforcer()._apply_modifier_to_payable(once)
    assert twice.count("collectPlatformFee(msg.value)") == \
        once.count("collectPlatformFee(msg.value)") == 1


def test_the_recipient_sentence_names_the_override():
    from runtime.blockchain.services.contract_conversion import revenue_enforcer

    doc = _prose(revenue_enforcer.__doc__)
    assert "The fee recipient address is always read from config" not in doc
    assert "fee_recipient" in doc


# ── the conversion service ─────────────────────────────────────────────────

async def test_an_empty_compile_output_is_an_error_not_a_raise(monkeypatch):
    from runtime.blockchain.services.contract_conversion import service as conv

    svc = conv.ContractConversionService({"blockchain": {}})
    svc._web3 = types.SimpleNamespace(available=True)
    monkeypatch.setattr(conv, "_SOLC_INSTALLED", True)
    monkeypatch.setitem(sys.modules, "solcx",
                        types.SimpleNamespace(compile_source=lambda *a, **k: {}))
    out = await svc._compile_and_deploy("contract X {}", "X")
    assert out["status"] == "error" and out["stage"] == "compile"


def test_the_conversion_comments_say_what_the_contract_and_audit_do():
    from runtime.blockchain.services.contract_conversion import service as conv

    src = _prose(inspect.getsource(conv.ContractConversionService.convert))
    assert "inert contract: the functions exist and do nothing." not in src
    assert "No statements anywhere — the audit cannot render a verdict." not in src
    assert "floating pragma" in src


# ── creator publishing ─────────────────────────────────────────────────────

def test_a_decode_fault_after_a_response_is_not_never_sent():
    from runtime.blockchain.services.creator_platforms._guards import classify_transport_fault

    assert classify_transport_fault(json.JSONDecodeError("x", "", 0)) == "unknown", (
        "a non-JSON 2xx was reported as 'the request never left — retrying is "
        "safe' about a post that may already be permanent")
    assert classify_transport_fault(TypeError("unserialisable")) == "not_sent"


async def test_a_non_string_endpoint_does_not_leak_its_credential():
    from runtime.blockchain.services.creator_platforms.service import CreatorPlatformsService

    svc = CreatorPlatformsService({"services": {"creator_platforms": {
        "enabled": True, "mirror_api_key": "k-live", "mirror_author": "0xAUTHOR",
        "mirror_publication": "pub",
        "mirror_endpoint": ["https://user:SUPERSECRET@gw.example/base"]}}})
    out = await svc.publish_mirror_post(title="t", body="b")
    assert "SUPERSECRET" not in json.dumps(out, default=str), out


# ── identity updates ───────────────────────────────────────────────────────

def test_an_agent_with_nothing_cannot_gain_everything_in_one_update():
    from runtime.blockchain.services.agent_identity.update_monitor import SafetyValidator

    v = SafetyValidator({})
    assert v.validate_capability_scope([], ["read", "write", "search"])["safe"] is False
    assert v.validate_capability_scope([], ["read"])["safe"] is True


def test_the_scope_check_runs_for_every_update_that_carries_capabilities():
    from runtime.blockchain.services.agent_identity.update_monitor import UpdateMonitor

    src = inspect.getsource(UpdateMonitor)
    assert '"new_capabilities" in update' in src


# ── brand rewards ──────────────────────────────────────────────────────────

async def test_the_cohort_floor_cannot_be_configured_away():
    from runtime.blockchain.services.brand_rewards.analytics import CohortAnalytics

    a = CohortAnalytics({"min_cohort_size": 1})
    for i in range(3):
        await a.record_distribution("c", f"0xU{i}", 10.0 * (i + 1))
    out = await a.get_campaign_stats("c")
    assert out["available"] is False, "a cohort of three was described"


async def test_the_stats_carry_no_single_recipient_values():
    from runtime.blockchain.services.brand_rewards.analytics import CohortAnalytics

    a = CohortAnalytics({})
    for i in range(100):
        await a.record_distribution("c", f"0xU{i}", float(i))
    out = await a.get_campaign_stats("c")
    assert out["available"] is True
    assert "min_reward" not in out and "max_reward" not in out


async def test_ineligibility_does_not_describe_the_user():
    from runtime.blockchain.services.brand_rewards.zkp_targeting import ZKPTargeting

    t = ZKPTargeting({})
    await t.create_criteria("c", {"tier_at_least": "gold", "region": "EU"})
    out = await t.check_eligibility("c", "0xU")
    assert out["eligible"] is False
    assert "gold" not in out["reason"] and "region" not in out["reason"]


# ── fundraising, gaming, IP ────────────────────────────────────────────────

async def test_every_verification_return_says_whether_an_authority_existed():
    from runtime.blockchain.services.fundraising.milestone_verification import MilestoneVerification

    mv = MilestoneVerification({}, voter_eligibility=lambda cid: {"0xA"})
    mv._milestones[("c", 0)] = {"status": "submitted", "campaign_id": "c"}
    out = await mv._verify_via_community_vote(("c", 0))
    assert out["authority_available"] is True


def test_the_gaming_release_sentence_says_the_proof_is_not_verified():
    from runtime.blockchain.services.gaming import milestone_funding

    doc = _prose(milestone_funding.__doc__)
    assert "Funds are released only when milestones are verified with proof." not in doc.replace(
        '"funds are released only when milestones are verified with proof"', "")
    assert "RECORDED, not verified" in doc


async def test_an_update_cannot_smuggle_a_second_copy_of_a_hash():
    from runtime.blockchain.services.ip_royalties.ip_registry import IPRegistry

    reg = IPRegistry({})
    a = await reg.register({"owner": "0xA", "content_hash": "H1"})
    rec = dict(a, content_hash="H2")
    await reg.update(a["ip_id"], rec)
    with pytest.raises(ValueError):
        await reg.register({"owner": "0xB", "content_hash": "H2"})
    b = await reg.register({"owner": "0xB", "content_hash": "H1"})
    with pytest.raises(ValueError):
        await reg.update(b["ip_id"], dict(b, content_hash="H2"))


# ── real estate ────────────────────────────────────────────────────────────

async def test_the_escrow_history_holds_only_legal_transitions(tmp_path):
    from tests.test_real_estate_service import BUYER, ESCROW, _ready_purchase, _settled_receipt

    svc, prop, eid = await _ready_purchase(tmp_path)
    svc._web3.w3.eth._receipt = _settled_receipt(eid, BUYER, ESCROW)
    result = await svc.confirm_settlement(eid, "0x" + "ee" * 32)
    esc = result["escrow"]
    states = [h["state"] for h in esc["history"]]
    assert states.count("initiated") == 1, (
        f"attaching a ref wrote an initiated -> initiated transition: {states}")
    assert esc["tx_hashes"]["lock"] != "0x" + "ee" * 32, (
        "a receipt with no FundsLocked event was recorded as the lock")


async def test_an_illegal_move_raises(tmp_path):
    from tests.test_real_estate_service import _ready_purchase

    svc, prop, eid = await _ready_purchase(tmp_path)
    escrow = await svc._store.get_escrow(eid)
    with pytest.raises(ValueError):
        await svc._move(escrow, "complete")


def test_the_readiness_comment_does_not_overstate_the_contract_guard():
    src = _prose((ROOT / "runtime/blockchain/services/real_estate/service.py").read_text())
    assert "guard passes only for a real one" not in src.replace(
        'the guard "passes only for a real one"', "")


# ── the dispatcher, attestation, ownership ─────────────────────────────────

def test_the_dispatcher_injects_through_the_constant():
    from runtime.blockchain.services import service_dispatcher as sd

    src = inspect.getsource(sd.ServiceDispatcher.execute)
    assert '"caller_identity": caller_identity' not in src
    assert "CALLER_IDENTITY_PARAM: caller_identity" in src
    mod = _prose(inspect.getsource(sd))
    assert "caching those would both miss every time" not in mod
    assert "the other three (capabilities/registry.py, agents/handoff.py, tools/dispatcher.py) never bind it" not in mod


def test_the_attestation_start_sentences_name_the_real_gap():
    from runtime.blockchain.services.attestation import batch_processor

    src = _prose(inspect.getsource(batch_processor))
    assert "which currently has no caller anywhere in the repo" not in src


def test_the_ownership_history_is_in_the_past_tense():
    from runtime.blockchain.services import ownership

    doc = _prose(ownership.__doc__)
    assert "insurance `file_claim` — takes no caller identity" not in doc
