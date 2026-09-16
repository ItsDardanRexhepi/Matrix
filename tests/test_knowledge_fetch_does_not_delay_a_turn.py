"""The knowledge module says three times that it never delays a response.

`runtime/knowledge/__init__.py`: "a knowledge fetch must never delay or break a
response". `retriever.py`: "This module is completely non-blocking: a failed
knowledge fetch must never delay or break a response."

It was awaited inline, on every turn, in front of the model call
(`runtime/protocols/integration.py` — `knowledge = await
retriever.get_relevant_context(...)`), bounded by a 2.5-second `wait_for`. An
unreachable source added up to two and a half seconds to every single reply.

The 30-second cache that would have hidden most of that never hit once, for a
reason no amount of TTL tuning would fix: the caller constructs a NEW
`KnowledgeRetriever` on every turn and the cache was an instance attribute, so
it arrived empty every time. A cache that is discarded before it can expire is
not a cache.

Both are timing claims, so these checks are about timing: a source that hangs
must not be able to hold a turn, and the second turn must be able to see what
the first one fetched.
"""

from __future__ import annotations

import asyncio
import time

import pytest

from runtime.knowledge import retriever as retriever_mod
from runtime.knowledge.retriever import KnowledgeRetriever


@pytest.fixture(autouse=True)
def _clear_shared_cache():
    # The cache is process-wide by design; a test must not inherit another's.
    clear = getattr(retriever_mod, "clear_cache", lambda: None)
    clear()
    yield
    clear()


class _HangingRetriever(KnowledgeRetriever):
    """Every source hangs. This is the unreachable-source case, exactly."""

    def __init__(self, *a, **kw):
        super().__init__(*a, **kw)
        self.started = 0

    async def _hang(self) -> dict:
        self.started += 1
        await asyncio.sleep(60)
        return {}

    async def _fetch_eth_price(self) -> dict:
        return await self._hang()

    async def _fetch_base_status(self) -> dict:
        return await self._hang()

    async def _fetch_platform_activity(self) -> dict:
        return await self._hang()


@pytest.mark.asyncio
async def test_a_hanging_source_cannot_hold_a_turn():
    r = _HangingRetriever({})
    start = time.monotonic()
    result = await r.get_relevant_context("what is eth worth", "trinity")
    elapsed = time.monotonic() - start
    assert isinstance(result, list)
    assert elapsed < 0.25, (
        f"the turn waited {elapsed:.2f}s on a source that never answers; "
        "'never delay a response' is a timing claim and this is the timing")


@pytest.mark.asyncio
async def test_a_hanging_source_is_still_actually_attempted():
    # §CT — a zero has more than one cause. "Fast" must not mean "the fetch was
    # quietly dropped": the refresh has to be running, just not in front of the
    # reply.
    r = _HangingRetriever({})
    await r.get_relevant_context("q", "trinity")
    await asyncio.sleep(0)  # let the scheduled task start
    await asyncio.sleep(0)
    assert r.started > 0, "no source was contacted at all"


@pytest.mark.asyncio
async def test_a_second_retriever_sees_what_the_first_one_fetched():
    # The caller builds a new retriever per turn. If the cache does not outlive
    # the instance, the 30-second TTL described in the module is unreachable.
    first = KnowledgeRetriever({})
    first._set_cached("eth_price", {
        "source": "eth_price", "content": "ETH: $3,000", "freshness": "live"})

    second = KnowledgeRetriever({})
    got = await second.get_relevant_context("price?", "trinity")
    assert [i["content"] for i in got] == ["ETH: $3,000"], (
        f"a fresh retriever could not see the cached value: {got}")


@pytest.mark.asyncio
async def test_a_stale_entry_is_not_served():
    # Non-blocking must not become "serve anything, however old". The TTL is
    # still the TTL.
    r = KnowledgeRetriever({})
    r._cache["eth_price"] = (
        time.monotonic() - 10_000,
        {"source": "eth_price", "content": "ETH: $1", "freshness": "live"})
    got = await KnowledgeRetriever({}).get_relevant_context("price?", "trinity")
    assert got == [], f"a stale entry was served: {got}"


@pytest.mark.asyncio
async def test_a_raising_source_does_not_break_the_turn():
    # The 'break' half of the claim, kept.
    class _Boom(KnowledgeRetriever):
        async def _fetch_eth_price(self):
            raise RuntimeError("coingecko is down")

        async def _fetch_base_status(self):
            raise RuntimeError("rpc is down")

        async def _fetch_platform_activity(self):
            raise RuntimeError("db is down")

    assert await _Boom({}).get_relevant_context("q", "trinity") == []
    await asyncio.sleep(0)
    await asyncio.sleep(0)
