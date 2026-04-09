"""Tests for runtime.memory.manager.MemoryManager."""

import asyncio
import json

import pytest

from runtime.memory.manager import MemoryManager, MAX_CONTEXT_TURNS


class TestMemoryKeyValue:
    """Key/value read, write, and get operations."""

    @pytest.mark.asyncio
    async def test_write_and_read(self, tmp_path):
        mm = MemoryManager({"memory_dir": str(tmp_path)})
        await mm.write("neo", "colour", "blue")
        data = mm.read("neo")
        assert data["kv"]["colour"] == "blue"

    @pytest.mark.asyncio
    async def test_get_existing_key(self, tmp_path):
        mm = MemoryManager({"memory_dir": str(tmp_path)})
        await mm.write("neo", "level", 42)
        assert mm.get("neo", "level") == 42

    def test_get_missing_key_returns_default(self, tmp_path):
        mm = MemoryManager({"memory_dir": str(tmp_path)})
        assert mm.get("neo", "missing") is None
        assert mm.get("neo", "missing", "fallback") == "fallback"

    def test_read_empty_agent(self, tmp_path):
        mm = MemoryManager({"memory_dir": str(tmp_path)})
        data = mm.read("unknown_agent")
        assert data == {"kv": {}, "turns": []}

    @pytest.mark.asyncio
    async def test_overwrite_key(self, tmp_path):
        mm = MemoryManager({"memory_dir": str(tmp_path)})
        await mm.write("neo", "x", 1)
        await mm.write("neo", "x", 2)
        assert mm.get("neo", "x") == 2

    @pytest.mark.asyncio
    async def test_multiple_agents_isolated(self, tmp_path):
        mm = MemoryManager({"memory_dir": str(tmp_path)})
        await mm.write("neo", "key", "neo_val")
        await mm.write("trinity", "key", "trinity_val")
        assert mm.get("neo", "key") == "neo_val"
        assert mm.get("trinity", "key") == "trinity_val"


class TestMemoryConversation:
    """Conversation turn persistence and context retrieval."""

    @pytest.mark.asyncio
    async def test_save_turn_and_get_context(self, tmp_path):
        mm = MemoryManager({"memory_dir": str(tmp_path)})
        await mm.save_turn("neo", "Hello", "Hi there")
        ctx = mm.get_context("neo")
        assert "User: Hello" in ctx
        assert "Agent: Hi there" in ctx

    @pytest.mark.asyncio
    async def test_get_context_empty(self, tmp_path):
        mm = MemoryManager({"memory_dir": str(tmp_path)})
        assert mm.get_context("neo") == ""

    @pytest.mark.asyncio
    async def test_context_returns_last_n_turns(self, tmp_path):
        mm = MemoryManager({"memory_dir": str(tmp_path)})
        for i in range(30):
            await mm.save_turn("neo", f"msg_{i}", f"resp_{i}")
        ctx = mm.get_context("neo")
        # Should only include the last MAX_CONTEXT_TURNS turns
        lines = ctx.strip().split("\n")
        assert len(lines) == MAX_CONTEXT_TURNS * 2  # user + agent per turn

    @pytest.mark.asyncio
    async def test_trimming_at_200_turns(self, tmp_path):
        mm = MemoryManager({"memory_dir": str(tmp_path)})
        for i in range(210):
            await mm.save_turn("neo", f"msg_{i}", f"resp_{i}")
        data = mm.read("neo")
        assert len(data["turns"]) == 200
        # The oldest turns should have been dropped
        assert data["turns"][0]["user"] == "msg_10"

    @pytest.mark.asyncio
    async def test_turn_has_timestamp(self, tmp_path):
        mm = MemoryManager({"memory_dir": str(tmp_path)})
        await mm.save_turn("neo", "q", "a")
        data = mm.read("neo")
        assert "ts" in data["turns"][0]
        assert isinstance(data["turns"][0]["ts"], float)


class TestMemoryPersistence:
    """File persistence across MemoryManager instances."""

    @pytest.mark.asyncio
    async def test_data_survives_new_instance(self, tmp_path):
        mm1 = MemoryManager({"memory_dir": str(tmp_path)})
        await mm1.write("neo", "persist_key", "persist_val")

        mm2 = MemoryManager({"memory_dir": str(tmp_path)})
        assert mm2.get("neo", "persist_key") == "persist_val"

    @pytest.mark.asyncio
    async def test_turns_survive_new_instance(self, tmp_path):
        mm1 = MemoryManager({"memory_dir": str(tmp_path)})
        await mm1.save_turn("neo", "hello", "world")

        mm2 = MemoryManager({"memory_dir": str(tmp_path)})
        ctx = mm2.get_context("neo")
        assert "User: hello" in ctx

    @pytest.mark.asyncio
    async def test_storage_file_created_on_disk(self, tmp_path):
        """Backing store file is materialised under the configured directory."""
        mm = MemoryManager({"memory_dir": str(tmp_path)})
        await mm.write("neo", "k", "v")
        # SQLite places one file (plus optional WAL/SHM siblings) under tmp_path.
        db_files = list(tmp_path.glob("*.db"))
        assert db_files, f"expected at least one .db file in {tmp_path}"

    @pytest.mark.asyncio
    async def test_unusual_agent_names_handled(self, tmp_path):
        """Slashes and other special characters in agent names must round-trip."""
        mm = MemoryManager({"memory_dir": str(tmp_path)})
        await mm.write("agent/with/slashes", "k", "v")
        # Round-trip through a new instance to prove it survived to disk.
        mm2 = MemoryManager({"memory_dir": str(tmp_path)})
        assert mm2.get("agent/with/slashes", "k") == "v"
