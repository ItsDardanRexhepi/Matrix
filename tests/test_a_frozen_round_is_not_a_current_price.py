"""The feed promises "NEVER a stale/invented number" and never checked the age.

`runtime/blockchain/price_feed.py` opens with: "If neither source is available
the feed raises PriceUnavailable — the route then returns an honest 503 and
NEVER a stale/invented number." The invented half is real: nothing here makes a
price up, and an unreachable source raises rather than serving the old cache.

The stale half was unchecked. `_read_chainlink_blocking` pulls `updatedAt` out
of `latestRoundData()`, returns it in the payload, and nobody compares it to
anything. A Chainlink aggregator that has stopped updating — a paused feed, a
dead node set, an aggregator address that is correct but no longer maintained —
keeps answering with its last round forever, and this feed served that answer as
the current price with a truthful-looking `updated_at` beside it.

That price is not only shown to a user. `/api/v1/paymaster/sign` prices every
sponsorship request against it to meter the per-identity daily USD cap, so a
frozen round is also a frozen cap.

The fix is the one the sentence already promised: a round older than the
configured maximum age is not a price. It falls through to the Coinbase
fallback, and if that cannot be reached either, the feed raises and the route
answers the 503 it documents.
"""

from __future__ import annotations

import pytest

from runtime.blockchain import price_feed as price_feed_module
from runtime.blockchain.price_feed import PriceFeed, PriceUnavailable

# Read through getattr so the bound's ABSENCE is a per-assertion failure rather
# than a collection error: before this check existed there was no such name.
DEFAULT_MAX_ROUND_AGE_SECONDS = getattr(
    price_feed_module, "DEFAULT_MAX_ROUND_AGE_SECONDS", 3600.0)

NOW = 1_700_000_000.0


def _cfg(max_age=None):
    feeds = {"eth_usd": "0x" + "ab" * 20}
    if max_age is not None:
        feeds["max_age_seconds"] = max_age
    return {"blockchain": {"chain_id": 84532, "price_feeds": feeds}}


def _chainlink(updated_at):
    async def read():
        return {"price": 3200.5, "decimals": 8, "source": "chainlink",
                "updated_at": int(updated_at)}
    return read


async def _no_source():
    return None


# ── 1. a frozen round is not served ────────────────────────────────────────

async def test_a_round_older_than_the_bound_is_not_the_current_price():
    async def coinbase():
        return {"price": 3150.0, "decimals": 2, "source": "coinbase"}

    pf = PriceFeed(_cfg(),
                   chainlink_reader=_chainlink(NOW - DEFAULT_MAX_ROUND_AGE_SECONDS - 60),
                   coinbase_fetcher=coinbase)
    d = await pf.eth_usd(now=NOW)
    assert d["source"] == "coinbase", (
        "a Chainlink round older than the configured bound was served as the "
        f"current price: {d}")


async def test_a_frozen_round_with_no_fallback_is_a_refusal_not_a_number():
    pf = PriceFeed(_cfg(),
                   chainlink_reader=_chainlink(NOW - 10 * DEFAULT_MAX_ROUND_AGE_SECONDS),
                   coinbase_fetcher=_no_source)
    with pytest.raises(PriceUnavailable):
        await pf.eth_usd(now=NOW)


async def test_the_bound_is_configurable():
    pf = PriceFeed(_cfg(max_age=60),
                   chainlink_reader=_chainlink(NOW - 600),
                   coinbase_fetcher=_no_source)
    with pytest.raises(PriceUnavailable):
        await pf.eth_usd(now=NOW)

    pf = PriceFeed(_cfg(max_age=86400),
                   chainlink_reader=_chainlink(NOW - 600),
                   coinbase_fetcher=_no_source)
    assert (await pf.eth_usd(now=NOW))["source"] == "chainlink"


# ── 2. the directions this must not move ───────────────────────────────────

async def test_a_current_round_is_still_served():
    pf = PriceFeed(_cfg(), chainlink_reader=_chainlink(NOW - 30),
                   coinbase_fetcher=_no_source)
    d = await pf.eth_usd(now=NOW)
    assert d["source"] == "chainlink" and d["price"] == 3200.5


async def test_a_round_timestamped_slightly_ahead_of_us_is_not_stale():
    """A chain timestamp is not our wall clock. Skew the other way is not age,
    and refusing it would turn ordinary drift into an outage."""
    pf = PriceFeed(_cfg(), chainlink_reader=_chainlink(NOW + 120),
                   coinbase_fetcher=_no_source)
    assert (await pf.eth_usd(now=NOW))["source"] == "chainlink"


async def test_the_coinbase_fallback_has_no_round_to_be_stale():
    async def coinbase():
        return {"price": 3150.0, "decimals": 2, "source": "coinbase"}

    pf = PriceFeed(_cfg(), chainlink_reader=_no_source, coinbase_fetcher=coinbase)
    d = await pf.eth_usd(now=NOW)
    assert d["source"] == "coinbase" and d["updated_at"] == int(NOW)


async def test_a_payload_without_a_timestamp_is_not_rejected():
    """An injected or future reader that omits updated_at is not evidence of
    age, and this check must not turn silence into a refusal."""
    async def reader():
        return {"price": 3200.5, "decimals": 8, "source": "chainlink"}

    pf = PriceFeed(_cfg(), chainlink_reader=reader, coinbase_fetcher=_no_source)
    assert (await pf.eth_usd(now=NOW))["price"] == 3200.5


# ── 3. the sponsorship cap is metered against a price, not a memory ────────

async def test_the_module_says_what_it_now_checks():
    assert "max_age_seconds" in (price_feed_module.__doc__ or ""), \
        price_feed_module.__doc__
