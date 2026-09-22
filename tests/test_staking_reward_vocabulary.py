"""NEW-97 — "claimed" over a claim nobody was paid, and the feed that said so.

THE DISCRIMINATOR, APPLIED. Strip the outcome claim from `claim_rewards` and
ask what work is left. Everything is left: a time-weighted pro-rata accrual, a
5% commission split, and a ledger entry — all real arithmetic. Category 6, so
the disposition is VOCABULARY, not removal. `status: "claimed"` becomes
`recorded_unsettled`; the maths is untouched.

THE CORRECT PATTERN ALREADY EXISTS IN THIS REPO, IN A METHOD OF THE SAME NAME.
`runtime/blockchain/staking.py::_claim_rewards` builds a transaction, signs it,
sends it, waits for a receipt, and returns

    "claimed" if receipt["status"] == 1 else "failed"

— status DERIVED from settlement. Two `claim_rewards`, one real and one
recording-only, and only the real one earned the word. That twin is the
strongest available evidence for what the service one should say, and it is
deliberately left untouched here.

THE FINDING THE VOCABULARY FIX ALONE WOULD HAVE MISSED
------------------------------------------------------
`ACTION_TO_FEED_EVENT["claim_staking_rewards"] = "rewards_claimed"` (installed
from the capability catalog at import) IS KEYED ON THE ACTION NAME, NOT ON THE
RESULT. It fires whatever `claim_rewards` returns. So changing the response's
status did not touch it: the response would have read "not settled" while the
social feed announced that rewards were claimed — and the feed is the louder
surface, published to other people rather than returned to the caller.

This is the mirror image of NEW-96's dashboard defect. There, a downstream
component written to behave correctly was defeated by its caller's default.
Here, a downstream publisher never consults the caller's result at all. Both
are found the same way — by asking what else speaks for this method — and
neither is visible from the method's own return value.

`total_commission_paid` -> `total_commission_recorded` is NEW-91's
`total_royalties_paid` shape in a SECOND domain, recorded as a repeat instance.
Consumer check across both repos: written in exactly two places, read by no
non-test code in The Matrix and none in the MTRX client — so, like `staker_count`
in NEW-95, this is a correctness fix to a PUBLISHED FIELD (it ships inside every
`get_position` response via `_sanitize_position`) and not to a live calculation.
"""

from __future__ import annotations

import pytest

from runtime.blockchain.services.staking.service import StakingService
from runtime.blockchain.web3_manager import Web3Manager


@pytest.fixture(autouse=True)
def _restore_shared_web3():
    shared = Web3Manager.get_shared({})
    before = (shared.available, shared.is_placeholder)
    yield
    shared.available, shared.is_placeholder = before


class _Clock:
    """Controllable stand-in for `time` (NEW-95's lesson: a test that depends
    on the suite running inside one second is not testing the code)."""

    def __init__(self, start: int = 1_700_000_000) -> None:
        self.t = float(start)

    def time(self) -> float:
        return self.t

    def advance(self, seconds: float) -> None:
        self.t += seconds


@pytest.fixture
def clock(monkeypatch):
    from runtime.blockchain.services.staking import service as service_mod

    c = _Clock()
    monkeypatch.setattr(service_mod, "time", c)
    return c


def _armed() -> StakingService:
    svc = StakingService({})
    svc._web3.available = True
    svc._web3.is_placeholder = lambda _a: False
    return svc


async def _claim(clock) -> tuple[StakingService, dict]:
    svc = _armed()
    await svc.stake("0xalice", 100.0)
    clock.advance(86_400)                       # one day of accrual
    return svc, await svc.claim_rewards("0xalice")


# ── The claim itself ─────────────────────────────────────────────────────


async def test_the_claim_no_longer_says_it_was_claimed(clock):
    """SCENARIO: a day's rewards, claimed. Pre-fix: status "claimed", with no
    transfer anywhere in the method."""
    _svc, result = await _claim(clock)

    assert result["status"] == "recorded_unsettled"
    assert result["settled"] is False
    assert result["value_moved"] is False
    assert "RECORDED, NOT PAID" in result["disclosure"]
    assert "no funded source" in result["disclosure"], (
        "the disclosure must name the accrual's missing funded source, not "
        "only the missing transfer — they are different absences"
    )


async def test_the_arithmetic_is_untouched(clock):
    """The argument for vocabulary over removal: strip the claim and a real
    engine remains. 5% commission, 95% net."""
    _svc, result = await _claim(clock)

    gross = result["gross_reward"]
    assert gross > 0
    assert result["commission"] == pytest.approx(gross * 0.05)
    assert result["net_reward"] == pytest.approx(gross * 0.95)
    assert result["commission_pct"] == 5.0


async def test_the_commission_ledger_discloses(clock):
    """Asserted against the STORE, not the return (rule 43) — a reader of
    `_commissions` sees a platform_wallet and must not infer a transfer."""
    svc, _result = await _claim(clock)
    entry = svc._commissions[-1]

    assert entry["settled"] is False
    assert entry["value_moved"] is False
    assert "No transfer was made to the platform wallet" in entry["disclosure"]
    assert entry["commission"] > 0


async def test_the_position_counter_no_longer_says_paid(clock):
    """NEW-91's `total_royalties_paid` shape, second domain."""
    svc, _result = await _claim(clock)
    position = svc._positions[("0xalice", "default")]

    assert "total_commission_paid" not in position, (
        "the 'paid' key is back — it reads as money that left the platform"
    )
    assert position["total_commission_recorded"] > 0


async def test_the_zero_case_still_claims_nothing(clock):
    """SCOPE. The `no_rewards` branch asserts no outcome, so it is untouched."""
    svc = _armed()
    await svc.stake("0xalice", 100.0)          # clock does not move
    result = await svc.claim_rewards("0xalice")

    assert result["status"] == "no_rewards"
    assert result["gross_reward"] == 0.0


# ── The surface the status change did not reach ──────────────────────────


def test_the_feed_event_no_longer_announces_a_claim():
    """THE FINDING THE VOCABULARY FIX ALONE WOULD HAVE MISSED.

    The feed event is keyed on the ACTION, not the result, so it fires whatever
    `claim_rewards` returns. Fixing only the response would have left the
    platform's loudest surface saying rewards were claimed while the response
    said they were not.
    """
    from runtime.blockchain.services.service_dispatcher import ACTION_TO_FEED_EVENT

    assert ACTION_TO_FEED_EVENT["claim_staking_rewards"] == "rewards_recorded"
    assert "rewards_claimed" not in ACTION_TO_FEED_EVENT.values(), (
        "a feed event still announces a claim; a feed event is a public "
        "statement that something happened"
    )


def test_the_sentence_the_feed_actually_emits_claims_nothing():
    """THE MECHANISM, DRIVEN — and my first version of this got it wrong.

    `SocialFeedEngine.ingest` does `ACTION_LABELS.get(action, f"performed
    {action}")`, and the dispatcher passes the ACTION name
    ("claim_staking_rewards"). `ACTION_LABELS` was keyed by the SERVICE METHOD
    name ("claim_rewards"), so the two never met: the live feed emitted
    "performed claim_staking_rewards" and the false sentence "claimed staking
    rewards" was NEVER PUBLISHED for this action.

    So the danger here was LATENT, not live — repair the key mismatch with the
    old text in place and the false claim ships that day. My first version of
    this test asserted on the unreachable key and would have certified a fix to
    dead code.

    This resolves the label the WAY INGEST RESOLVES IT, so it cannot pass over
    a key nobody reads.
    """
    from runtime.social.feed_engine import ACTION_LABELS

    def as_ingest_resolves(action: str) -> str:
        return ACTION_LABELS.get(action, f"performed {action}")

    for action in ("claim_staking_rewards", "claim_rewards"):
        sentence = as_ingest_resolves(action)
        assert sentence != "claimed staking rewards"
        assert "not settled" in sentence, (
            f"the sentence the feed emits for {action!r} is {sentence!r} — it "
            "must not read as a completed claim"
        )


def test_no_action_label_anywhere_still_announces_a_staking_claim():
    """The ratchet across BOTH keys, so fixing the key mismatch later cannot
    resurrect the old text from whichever entry was left behind."""
    from runtime.social.feed_engine import ACTION_LABELS

    offenders = {
        k: v for k, v in ACTION_LABELS.items()
        if "claim" in k and "staking" in v and "not settled" not in v
    }
    assert not offenders, f"a staking label still announces a claim: {offenders}"


def test_the_feed_event_map_has_no_reader_and_is_recorded_as_such():
    """HONEST SCOPE. `ACTION_TO_FEED_EVENT` is renamed correctly here, but a
    repo-wide search finds NO reader of it outside its own definition and the
    catalog install — `ingest` sets `event_type=action`, not the mapped value.

    So this rename is correct-but-currently-inert, exactly like `staker_count`
    (NEW-95) and `total_commission_recorded` (this commit): a published value
    with no live consumer. Saying it "fixes the feed" would overstate it, and
    that overstatement is what the first draft of this file did.
    """
    from runtime.blockchain.services.service_dispatcher import ACTION_TO_FEED_EVENT

    assert ACTION_TO_FEED_EVENT["claim_staking_rewards"] == "rewards_recorded"
    assert "rewards_claimed" not in ACTION_TO_FEED_EVENT.values()


# ── The read that publishes the accrual ──────────────────────────────────


async def test_the_position_read_discloses_the_unfunded_accrual(clock):
    """`get_position` publishes pending_rewards, total_rewards_earned and the
    commission total — all produced from a configured rate with no treasury."""
    svc = _armed()
    await svc.stake("0xalice", 100.0)
    clock.advance(86_400)

    position = await svc.get_position("0xalice")

    assert position["pending_rewards"] > 0
    assert position["rewards_settled"] is False
    assert "ACCRUED, NOT FUNDED" in position["rewards_disclosure"]


# ── The real twin, deliberately untouched ────────────────────────────────


def test_the_receipt_derived_twin_still_says_claimed():
    """SCOPE PIN, and the evidence for the whole disposition.

    `runtime/blockchain/staking.py::_claim_rewards` derives its status from a
    transaction receipt. It has EARNED the word "claimed" and must keep it — if
    this ever fails, someone has applied NEW-97 to the wrong method and made a
    real settlement report as though it were a local record.
    """
    import ast
    import inspect

    from runtime.blockchain import staking as staking_tool

    src = inspect.getsource(staking_tool)
    tree = ast.parse(src)
    fn = next(
        n for n in ast.walk(tree)
        if isinstance(n, (ast.FunctionDef, ast.AsyncFunctionDef))
        and n.name == "_claim_rewards"
    )
    body = ast.unparse(fn)

    assert "'claimed' if receipt['status'] == 1 else 'failed'" in body, (
        "the receipt-derived twin no longer derives its status from a receipt"
    )
    # The receipt comes through the shared wait, `BlockchainInterface._receipt`,
    # which answers None for a wait that runs out so the method can report an
    # unconfirmed broadcast with its hash instead of "Claim failed". It used to
    # call `wait_for_transaction_receipt` inline, and this line pinned that
    # name; the census in tests/test_a_sent_transaction_is_not_a_refusal.py
    # now holds that no capability names the raw wait at all.
    assert "self._receipt(" in body, (
        "the receipt-derived twin no longer waits for its receipt"
    )
    assert "send_raw_transaction" in body


async def test_the_new_94_gate_still_precedes_the_vocabulary(clock):
    """SCOPE PIN. An undeployed domain must still REFUSE, not return a
    recorded-unsettled record — a refusal and an honest non-settlement are
    different answers and the gate owns the first."""
    svc = StakingService({})
    svc._web3.available = False

    result = await svc.claim_rewards("0xalice")
    assert result["status"] == "not_deployed"
    assert result["operation"] == "claim_rewards"
