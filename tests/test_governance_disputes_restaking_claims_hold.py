"""Governance, dispute resolution and restaking, held to what they claim.

Built true:
  * "only balances at snapshot time count" — a voter absent from the snapshot
    kept the weight they declared; absent now means zero, and is refused;
  * "wiring a balance source lifts the refusal and nothing else has to be
    remembered" — the caller's weight still reached the model; with a source
    wired the weight is the snapshot balance;
  * restaking's "the real call is only attempted once the operator has
    populated the config" — a caller-supplied strategy satisfied the gate;
  * every juror selection now says where its randomness came from.

Corrected: juror selection's Chainlink VRF / provably fair / unmanipulable /
staked tokens (a local uuid4 seed and a declared number), its "deterministic"
fallback, dispute filing's "time-critical attestation, never batched" (no
attestation exists), "both parties must stake" (numbers, not deposits), the
appeal's round-2 winners, the commit phase's "only the hash is stored", the
holding period that gates no vote, the weight cap that "only warns", the
bilateral detector, the lazy-expiry justification, the Snapshot client that
"does not exist in this platform", migrate_members "appearing once", and an
ABI said to hold only what is invoked.
"""

from __future__ import annotations

import inspect
import re

import pytest


def _prose(text: str) -> str:
    return re.sub(r"\s+", " ", re.sub(r"\s*#\s*", " ", text or ""))


# ── the snapshot ───────────────────────────────────────────────────────────

async def test_a_voter_absent_from_the_snapshot_does_not_vote_their_declared_weight():
    from runtime.blockchain.services.governance.anti_manipulation import AntiManipulation

    am = AntiManipulation({})
    am.take_snapshot("p", {"0xHOLDER": 100.0})
    out = await am.check_vote("p", "0xFLASH", 999_999.0)
    assert out["allowed"] is False, (
        "a voter who held nothing at snapshot time voted with the weight they declared")


class _Balances:
    async def balances_at_now(self):
        return {"0xA": 10.0, "0xB": 90.0}


async def test_with_a_balance_source_the_weight_is_the_snapshot_balance():
    from runtime.blockchain.services.governance.service import GovernanceService

    svc = GovernanceService({})
    svc._balance_source = _Balances()
    p = await svc.create_proposal("0xP", "Raise the fee", "a platform parameter",
                                  "token_weighted", ["yes", "no"])
    vote = await svc.vote(p["proposal_id"], "0xA", "yes", weight=1_000_000.0)
    assert vote["effective_weight"] <= 10.0, (
        f"the caller's declared weight reached the tally: {vote['effective_weight']}")


# ── restaking ──────────────────────────────────────────────────────────────

async def test_a_caller_cannot_choose_the_strategy_the_platform_withdraws_from():
    from runtime.blockchain.services.restaking.service import RestakingService

    svc = RestakingService({"services": {"restaking": {
        "enabled": True,
        "strategy_address": "0x" + "11" * 20,
        "delegation_manager_address": "0x" + "22" * 20}}})
    out = await svc.withdraw_restake(strategy="0x" + "99" * 20, shares=1)
    assert out.get("refused") is True and out["status"] == "invalid_request"


# ── jurors ─────────────────────────────────────────────────────────────────

async def test_a_selection_says_its_seed_is_not_verifiable():
    from runtime.blockchain.services.dispute_resolution.juror_pool import JurorPool

    pool = JurorPool({})
    for i in range(5):
        await pool.register_juror(f"0xJ{i}", ["fraud"], 100.0)
    await pool.select_jurors("d1", count=3)
    assert pool.last_seed_source == "local_uuid4_not_verifiable"


def test_the_juror_pool_does_not_promise_verifiable_or_staked_selection():
    from runtime.blockchain.services.dispute_resolution import juror_pool

    # The module's docstring follows its `from __future__` import, so it is
    # not `__doc__` (which is None): read the source.
    doc = _prose(inspect.getsource(juror_pool))
    for phrase in ("Uses Chainlink VRF (via Component 11 Oracle Gateway) to ensure",
                   "Jurors must stake tokens to participate"):
        assert phrase not in doc
    assert "# Fallback: deterministic but not verifiable" not in inspect.getsource(juror_pool)


def test_the_dispute_service_does_not_promise_an_attestation_or_stakes():
    from runtime.blockchain.services.dispute_resolution import schelling_point, service

    doc = _prose(inspect.getsource(service))   # docstring after the future import
    assert "Dispute filing is a TIME-CRITICAL attestation — it is never batched." not in doc
    assert "Both parties must stake to participate." not in doc
    src = _prose(inspect.getsource(service))
    assert 'or both the round-1 and round-2 "winners" would hold' not in src
    sp = _prose(inspect.getsource(schelling_point.SchellingPoint))
    assert "only the hash is stored during the commit phase" not in sp


# ── governance text ────────────────────────────────────────────────────────

def test_the_governance_sentences_say_what_the_code_does():
    from runtime.blockchain.services.advanced_governance import service as adv
    from runtime.blockchain.services.dao_management import conversion_wizard
    from runtime.blockchain.services.governance import anti_manipulation, service as gov

    g = _prose(inspect.getsource(gov))
    assert "detected and rejected" not in _prose(gov.__doc__)
    assert "neither of which exists in this platform" not in g
    assert "lazy expiry is the only thing moving proposals out of" not in g
    am = _prose(inspect.getsource(anti_manipulation))
    assert "(only warn, don't block)" not in am
    assert "gates no vote" in am
    assert "(only the function we actually invoke)" not in _prose(inspect.getsource(adv))
    assert "appears exactly once in the repo — its own definition" not in _prose(
        inspect.getsource(conversion_wizard))
