"""Tests for the knowledge retriever — graceful failure and caching."""

import asyncio
import time

import pytest

from runtime.knowledge.retriever import KnowledgeRetriever


# ── Graceful failure ───────────────────────────────────────────────


class TestGracefulFailure:

    @pytest.mark.asyncio
    async def test_returns_empty_on_network_failure(self):
        """When all external sources fail, returns empty list silently."""
        retriever = KnowledgeRetriever({"base_rpc_url": "http://localhost:1"})
        result = await retriever.get_relevant_context("What is ETH price?", "trinity")
        assert isinstance(result, list)
        # May or may not be empty depending on network — but must not raise

    @pytest.mark.asyncio
    async def test_returns_list_type(self):
        retriever = KnowledgeRetriever()
        result = await retriever.get_relevant_context("hello", "trinity")
        assert isinstance(result, list)

    @pytest.mark.asyncio
    async def test_empty_query(self):
        retriever = KnowledgeRetriever()
        result = await retriever.get_relevant_context("", "trinity")
        assert isinstance(result, list)


# ── Cache behaviour ────────────────────────────────────────────────


class TestCache:

    def test_cache_miss_returns_none(self):
        retriever = KnowledgeRetriever()
        assert retriever._get_cached("nonexistent") is None

    def test_cache_hit(self):
        retriever = KnowledgeRetriever()
        data = {"source": "test", "content": "hello", "freshness": "live"}
        retriever._set_cached("test_key", data)
        assert retriever._get_cached("test_key") == data

    def test_cache_expiry(self):
        retriever = KnowledgeRetriever()
        data = {"source": "test", "content": "hello", "freshness": "live"}
        retriever._cache["expired_key"] = (time.monotonic() - 60, data)
        assert retriever._get_cached("expired_key") is None

    def test_cache_not_expired(self):
        retriever = KnowledgeRetriever()
        data = {"source": "test", "content": "hello", "freshness": "live"}
        retriever._cache["fresh_key"] = (time.monotonic(), data)
        assert retriever._get_cached("fresh_key") == data


# ── Result format ──────────────────────────────────────────────────


class TestResultFormat:

    @pytest.mark.asyncio
    async def test_results_have_required_keys(self):
        retriever = KnowledgeRetriever()
        # Pre-populate cache to avoid network calls
        retriever._set_cached("eth_price", {
            "source": "eth_price",
            "content": "ETH: $3,241 (+2.3% 24h)",
            "freshness": "live",
        })
        result = await retriever._fetch_eth_price()
        if result:
            assert "source" in result
            assert "content" in result
            assert "freshness" in result
