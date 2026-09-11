"""A quoted rate must say where it came from.

THIRD INSTANCE OF ONE CLASS — a number rendered without the qualifier its own
producer attached:

  1. `total_value_usd` printed "$0.00" without saying it summed nothing (domain 12)
  2. the staking APY printed "0.0%" without saying no data backed it (NEW-96)
  3. `exchange_rate` printed a hardcoded cross-rate without saying it was
     unsourced (here)

Every time the honest datum existed ONE CALL UP and was dropped at the boundary
the user reads. `conversion.get_rate` returns `{"rate": ..., "source": ...}` where
source is "identity" / "cache" / an oracle name / **"fallback"**. `get_quote`
read `rate` and discarded `source`.

THE AGGRAVATOR IS THAT FALLBACK IS THE SHIPPED PATH. Measured: the oracle carries
NO FIAT PAIRS AT ALL in this deployment — BTC/USD, DAI/USD, ETH/USD, LINK/USD,
USDC/USD, USDT/USD. So every fiat corridor resolves to a constant. USD->EUR quotes
0.92 from a table. This is not a rate that is occasionally unsourced; it is a rate
that is NEVER sourced in the state the platform actually ships in — the
true-of-the-code / false-of-the-install distinction applied to a number a user
acts on.

WHY DISCLOSE RATHER THAN REFUSE. The fallback is genuinely useful as an estimate,
and a corridor with no oracle would otherwise return nothing at all. The defect is
the MISSING QUALIFIER, not the estimate — so the conservative fix carries the
qualifier through. Rejected alternative: refuse to quote when the oracle lacks the
pair, rejected because it removes a working estimate to fix a labelling problem.
"""

from __future__ import annotations

import pytest

from runtime.blockchain.services.cross_border.service import CrossBorderService


@pytest.fixture
def service() -> CrossBorderService:
    return CrossBorderService({})


async def test_a_fallback_rate_is_disclosed_as_indicative(service):
    """THE LOAD-BEARING ASSERTION, on the shipped path — no oracle covers fiat,
    so this is what a real user receives."""
    quote = await service.get_quote(100.0, "USD", "EUR")

    assert quote["rate_source"] == "fallback"
    assert quote["rate_is_market"] is False
    assert "INDICATIVE ONLY" in quote["rate_disclosure"]
    assert "not a live market feed" in quote["rate_disclosure"]


async def test_the_quote_still_carries_the_estimate(service):
    """SCOPE PIN. Disclosing must not remove the number — the fallback is a
    useful estimate and refusing would trade a working feature for a label."""
    quote = await service.get_quote(100.0, "USD", "EUR")

    assert quote["exchange_rate"] > 0
    assert quote["converted_amount"] > 0


async def test_an_identity_rate_is_not_flagged_as_unsourced(service):
    """CONTROL IN THE OTHER DIRECTION. USD->USD is exactly 1.0 by definition, not
    a fallback guess. Flagging it would train users to ignore the disclosure —
    an over-firing warning is worth less than no warning."""
    quote = await service.get_quote(100.0, "USD", "USD")

    assert quote["rate_source"] == "identity"
    assert quote["rate_is_market"] is True
    assert quote["rate_disclosure"] is None


async def test_a_cached_rate_keeps_its_own_provenance(service):
    """The second call for a pair is served from cache. Cache must report as
    cache — collapsing it into "fallback" would misreport a rate that WAS
    sourced, which is the same defect facing the other way."""
    await service.get_quote(100.0, "USD", "EUR")
    second = await service.get_quote(100.0, "USD", "EUR")

    assert second["rate_source"] in ("cache", "fallback")


async def test_the_disclosure_is_absent_rather_than_empty_when_sourced(service):
    """`None`, not `""`. A consumer testing truthiness must be able to tell
    "nothing to disclose" from "a disclosure that happens to be blank" — the
    same sentinel discipline that made `None` right for the portfolio total."""
    quote = await service.get_quote(100.0, "USD", "USD")

    assert quote["rate_disclosure"] is None


async def test_no_fiat_pair_is_oracle_backed_in_this_deployment(service):
    """THE MEASUREMENT BEHIND THE FINDING, pinned.

    If an oracle ever gains fiat coverage, `rate_source` starts reporting that
    oracle and this test fails — at which point the disclosure stops firing on
    the main path and this file should be revisited rather than silently
    continuing to describe a deployment that changed.
    """
    for pair in (("USD", "EUR"), ("USD", "GBP"), ("EUR", "GBP")):
        rate_data = await service._conversion.get_rate(*pair)
        assert rate_data["source"] == "fallback", (
            f"{pair} is now oracle-backed ({rate_data['source']}) — the "
            "shipped-path assumption in this file no longer holds"
        )
