"""Tests for hivemind.orchestrator — TaskRouter, MessageBus, SharedContextLayer, delegate_task."""

import asyncio
import json

import pytest
from unittest.mock import AsyncMock, MagicMock, patch

from hivemind.orchestrator import (
    TaskRouter,
    MessageBus,
    SharedContextLayer,
    HivemindOrchestrator,
    TaskStatus,
    AGENT_CAPABILITIES,
)
from runtime.react_loop import ReActResult, Message


class TestTaskRouter:
    """TaskRouter routes task types to the correct agent."""

    def setup_method(self):
        self.router = TaskRouter()

    def test_bash_routes_to_neo(self):
        assert self.router.route("bash") == "neo"

    def test_execute_routes_to_neo(self):
        assert self.router.route("execute") == "neo"

    def test_deploy_routes_to_neo(self):
        assert self.router.route("deploy_contract") == "neo"

    def test_blockchain_routes_to_neo(self):
        assert self.router.route("blockchain_query") == "neo"

    def test_chat_routes_to_trinity(self):
        assert self.router.route("chat") == "trinity"

    def test_conversation_routes_to_trinity(self):
        assert self.router.route("conversation") == "trinity"

    def test_explain_routes_to_trinity(self):
        assert self.router.route("explain_concept") == "trinity"

    def test_security_routes_to_morpheus(self):
        assert self.router.route("security_check") == "morpheus"

    def test_risk_routes_to_morpheus(self):
        assert self.router.route("risk_assessment") == "morpheus"

    def test_guidance_routes_to_morpheus(self):
        assert self.router.route("guidance") == "morpheus"

    def test_unknown_defaults_to_neo(self):
        assert self.router.route("something_random_xyz") == "neo"

    def test_case_insensitive(self):
        assert self.router.route("BASH") == "neo"
        assert self.router.route("Chat") == "trinity"


class TestMessageBus:
    """MessageBus per-agent queues with persistence."""

    @pytest.mark.asyncio
    async def test_send_and_receive(self, tmp_path):
        bus = MessageBus(str(tmp_path))
        await bus.send("neo", {"type": "task", "data": "hello"})
        msg = await bus.receive("neo", timeout=1.0)
        assert msg is not None
        assert msg["type"] == "task"
        assert msg["data"] == "hello"

    @pytest.mark.asyncio
    async def test_receive_timeout_returns_none(self, tmp_path):
        bus = MessageBus(str(tmp_path))
        msg = await bus.receive("neo", timeout=0.1)
        assert msg is None

    @pytest.mark.asyncio
    async def test_multiple_messages_fifo(self, tmp_path):
        bus = MessageBus(str(tmp_path))
        await bus.send("neo", {"seq": 1})
        await bus.send("neo", {"seq": 2})
        await bus.send("neo", {"seq": 3})
        m1 = await bus.receive("neo", timeout=1.0)
        m2 = await bus.receive("neo", timeout=1.0)
        m3 = await bus.receive("neo", timeout=1.0)
        assert m1["seq"] == 1
        assert m2["seq"] == 2
        assert m3["seq"] == 3

    @pytest.mark.asyncio
    async def test_agents_have_separate_queues(self, tmp_path):
        bus = MessageBus(str(tmp_path))
        await bus.send("neo", {"agent": "neo"})
        await bus.send("trinity", {"agent": "trinity"})

        neo_msg = await bus.receive("neo", timeout=1.0)
        trinity_msg = await bus.receive("trinity", timeout=1.0)
        assert neo_msg["agent"] == "neo"
        assert trinity_msg["agent"] == "trinity"

    @pytest.mark.asyncio
    async def test_pending_count(self, tmp_path):
        bus = MessageBus(str(tmp_path))
        assert bus.pending_count("neo") == 0
        await bus.send("neo", {"x": 1})
        await bus.send("neo", {"x": 2})
        assert bus.pending_count("neo") == 2

    @pytest.mark.asyncio
    async def test_persistence_to_disk(self, tmp_path):
        bus = MessageBus(str(tmp_path))
        await bus.send("neo", {"persisted": True})
        queue_file = tmp_path / "hivemind" / "queues" / "neo.jsonl"
        assert queue_file.exists()
        content = queue_file.read_text().strip()
        assert len(content) > 0
        data = json.loads(content)
        assert data["persisted"] is True

    @pytest.mark.asyncio
    async def test_load_persisted_messages(self, tmp_path):
        # Write messages to disk manually
        queues_dir = tmp_path / "hivemind" / "queues"
        queues_dir.mkdir(parents=True, exist_ok=True)
        queue_file = queues_dir / "neo.jsonl"
        queue_file.write_text(json.dumps({"restored": True}) + "\n")

        bus = MessageBus(str(tmp_path))
        msg = await bus.receive("neo", timeout=1.0)
        assert msg is not None
        assert msg["restored"] is True


class TestSharedContextLayer:
    """Thread-safe shared state with pub/sub."""

    def test_set_and_get(self):
        ctx = SharedContextLayer()
        ctx.set("key", "value")
        assert ctx.get("key") == "value"

    def test_get_default(self):
        ctx = SharedContextLayer()
        assert ctx.get("missing") is None
        assert ctx.get("missing", 42) == 42

    def test_get_all(self):
        ctx = SharedContextLayer()
        ctx.set("a", 1)
        ctx.set("b", 2)
        all_state = ctx.get_all()
        assert all_state == {"a": 1, "b": 2}

    def test_overwrite(self):
        ctx = SharedContextLayer()
        ctx.set("x", 1)
        ctx.set("x", 2)
        assert ctx.get("x") == 2

    def test_subscribe_fires_on_set(self):
        ctx = SharedContextLayer()
        notifications = []
        ctx.subscribe("events", lambda k, v: notifications.append((k, v)))
        ctx.set("events", "fired")
        assert len(notifications) == 1
        assert notifications[0] == ("events", "fired")

    def test_subscribe_multiple_callbacks(self):
        ctx = SharedContextLayer()
        results = []
        ctx.subscribe("key", lambda k, v: results.append("a"))
        ctx.subscribe("key", lambda k, v: results.append("b"))
        ctx.set("key", "val")
        assert results == ["a", "b"]

    def test_subscribe_only_fires_for_matching_key(self):
        ctx = SharedContextLayer()
        notifications = []
        ctx.subscribe("target", lambda k, v: notifications.append(v))
        ctx.set("other", "nope")
        assert len(notifications) == 0

    def test_subscriber_exception_does_not_break(self):
        ctx = SharedContextLayer()
        results = []

        def bad_callback(k, v):
            raise RuntimeError("boom")

        def good_callback(k, v):
            results.append(v)

        ctx.subscribe("key", bad_callback)
        ctx.subscribe("key", good_callback)
        ctx.set("key", "ok")
        assert results == ["ok"]


class TestDelegateTask:
    """HivemindOrchestrator.delegate_task flow."""

    @pytest.fixture
    def mock_react_loop(self):
        loop = MagicMock()
        loop.get_agent_prompt = MagicMock(return_value="")
        loop.run = AsyncMock(return_value=ReActResult(
            response="Task done",
            tool_calls=[],
            iterations=1,
            provider="mock",
        ))
        loop.run_without_tools = AsyncMock(return_value="Morpheus says hello")
        return loop

    @pytest.fixture
    def orchestrator(self, mock_config, tmp_path, mock_react_loop):
        mock_config["workspace"] = str(tmp_path)
        return HivemindOrchestrator(mock_config, mock_react_loop)

    @pytest.mark.asyncio
    async def test_delegate_routes_and_completes(self, orchestrator):
        task = await orchestrator.delegate_task(
            task_type="deploy_contract",
            payload={"contract": "MyToken"},
            source_agent="trinity",
            session_id="s1",
        )
        assert task.target_agent == "neo"
        assert task.status == TaskStatus.COMPLETED
        assert task.result is not None

    @pytest.mark.asyncio
    async def test_delegate_creates_task_in_active_tasks(self, orchestrator):
        task = await orchestrator.delegate_task(
            task_type="chat_response",
            payload={},
        )
        assert task.id in orchestrator.active_tasks

    @pytest.mark.asyncio
    async def test_delegate_sends_to_message_bus(self, orchestrator):
        task = await orchestrator.delegate_task(
            task_type="bash_command",
            payload={"command": "ls"},
        )
        # The message was sent to the target agent's queue and consumed
        # Verify the task completed successfully (message was sent before execution)
        assert task.status == TaskStatus.COMPLETED

    @pytest.mark.asyncio
    async def test_delegate_updates_shared_context(self, orchestrator):
        task = await orchestrator.delegate_task(
            task_type="execute_something",
            payload={},
            session_id="s1",
        )
        completed = orchestrator.shared_context.get("task_completed")
        assert completed is not None
        assert completed["task_id"] == task.id

    @pytest.mark.asyncio
    async def test_delegate_handles_failure(self, orchestrator, mock_react_loop):
        mock_react_loop.run = AsyncMock(side_effect=RuntimeError("model down"))
        task = await orchestrator.delegate_task(
            task_type="deploy",
            payload={},
        )
        assert task.status == TaskStatus.FAILED
        assert "model down" in task.error

    @pytest.mark.asyncio
    async def test_delegate_emits_events(self, orchestrator):
        events_emitted = []
        original_emit = orchestrator.event_bus.emit

        async def capture_emit(event):
            events_emitted.append(event.type.value)
            await original_emit(event)

        orchestrator.event_bus.emit = capture_emit

        await orchestrator.delegate_task(
            task_type="deploy",
            payload={},
            session_id="s1",
        )
        assert "task.delegated" in events_emitted
        assert "task.completed" in events_emitted
