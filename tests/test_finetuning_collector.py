"""Tests for the fine-tuning data collector."""

import asyncio
import json
import sqlite3
import tempfile
from pathlib import Path

import pytest

from runtime.finetuning.collector import FinetuningCollector


# ── Helpers ────────────────────────────────────────────────────────


class FakeDB:
    """Minimal async SQLite wrapper matching Database interface."""

    def __init__(self, db_path=":memory:"):
        self.conn = sqlite3.connect(db_path)
        self.conn.row_factory = sqlite3.Row

    async def execute(self, sql, params=(), commit=True):
        self.conn.execute(sql, params)
        if commit:
            self.conn.commit()

    async def executemany(self, sql, params_list, commit=True):
        self.conn.executemany(sql, params_list)
        if commit:
            self.conn.commit()

    async def fetchall(self, sql, params=()):
        return self.conn.execute(sql, params).fetchall()

    async def fetchone(self, sql, params=()):
        return self.conn.execute(sql, params).fetchone()


@pytest.fixture
def fake_db():
    return FakeDB()


@pytest.fixture
def collector(fake_db):
    c = FinetuningCollector(fake_db)
    asyncio.run(c.initialize())
    return c


# ── Record ─────────────────────────────────────────────────────────


class TestRecord:

    @pytest.mark.asyncio
    async def test_record_returns_id(self, collector):
        eid = await collector.record_example(
            "trinity", "What is staking?", "Staking is...", session_id="s1",
        )
        assert isinstance(eid, str)
        assert len(eid) == 16

    @pytest.mark.asyncio
    async def test_record_persists(self, collector):
        await collector.record_example(
            "neo", "Deploy contract", "Deploying...", session_id="s2",
        )
        examples = await collector.get_training_set(agent="neo", min_rating=0)
        assert len(examples) == 1
        assert examples[0]["agent"] == "neo"

    @pytest.mark.asyncio
    async def test_record_with_tool_calls(self, collector):
        tools = [{"name": "deploy_contract", "args": {"chain": "base"}}]
        await collector.record_example(
            "neo", "Deploy", "Done", tool_calls=tools, session_id="s3",
        )
        examples = await collector.get_training_set(agent="neo", min_rating=0)
        assert json.loads(examples[0]["tool_calls"]) == tools


# ── Rate ───────────────────────────────────────────────────────────


class TestRate:

    @pytest.mark.asyncio
    async def test_rate_example(self, collector):
        eid = await collector.record_example("trinity", "Hi", "Hello!", session_id="s4")
        await collector.rate_example(eid, 5, flags=["excellent"])
        examples = await collector.get_training_set(agent="trinity", min_rating=5)
        assert len(examples) == 1
        assert examples[0]["rating"] == 5
        assert "excellent" in json.loads(examples[0]["flags"])

    @pytest.mark.asyncio
    async def test_rating_clamped(self, collector):
        eid = await collector.record_example("trinity", "Hi", "Hello!", session_id="s5")
        await collector.rate_example(eid, 10)  # should clamp to 5
        examples = await collector.get_training_set(agent="trinity", min_rating=0)
        assert examples[0]["rating"] == 5

    @pytest.mark.asyncio
    async def test_min_rating_filter(self, collector):
        e1 = await collector.record_example("trinity", "Q1", "A1", session_id="s6")
        e2 = await collector.record_example("trinity", "Q2", "A2", session_id="s6")
        await collector.rate_example(e1, 2)
        await collector.rate_example(e2, 5)
        high = await collector.get_training_set(agent="trinity", min_rating=4)
        assert len(high) == 1


# ── Export ─────────────────────────────────────────────────────────


class TestExport:

    @pytest.mark.asyncio
    async def test_export_jsonl(self, collector):
        eid = await collector.record_example("trinity", "Hi", "Hello!", session_id="s7")
        await collector.rate_example(eid, 5)

        with tempfile.TemporaryDirectory() as tmpdir:
            path = str(Path(tmpdir) / "test.jsonl")
            count = await collector.export_jsonl("trinity", path, min_rating=4)
            assert count == 1

            with open(path) as f:
                line = json.loads(f.readline())
                assert "messages" in line
                assert len(line["messages"]) == 3
                assert line["messages"][1]["content"] == "Hi"
                assert line["messages"][2]["content"] == "Hello!"

    @pytest.mark.asyncio
    async def test_export_empty(self, collector):
        with tempfile.TemporaryDirectory() as tmpdir:
            path = str(Path(tmpdir) / "empty.jsonl")
            count = await collector.export_jsonl("neo", path)
            assert count == 0


# ── Stats ──────────────────────────────────────────────────────────


class TestStats:

    @pytest.mark.asyncio
    async def test_stats_empty(self, collector):
        stats = await collector.get_stats()
        assert stats["agents"] == {}
        assert stats["ready_for_finetuning"] is False

    @pytest.mark.asyncio
    async def test_stats_with_data(self, collector):
        for i in range(5):
            eid = await collector.record_example("trinity", f"Q{i}", f"A{i}", session_id="s8")
            await collector.rate_example(eid, 4 + (i % 2))
        stats = await collector.get_stats()
        assert "trinity" in stats["agents"]
        assert stats["agents"]["trinity"]["total_examples"] == 5
        assert stats["agents"]["trinity"]["high_quality"] == 5
