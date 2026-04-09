"""Tests for hivemind.events.EventBus and AgentEvent."""

import json

import pytest
import pytest_asyncio

from hivemind.events import EventBus, EventType, AgentEvent


@pytest.fixture
def event_bus(tmp_path):
    return EventBus(str(tmp_path))


class TestEventBusSubscribeAndEmit:
    """Core subscribe/emit functionality."""

    @pytest.mark.asyncio
    async def test_global_handler_fires(self, event_bus):
        received = []

        async def handler(event):
            received.append(event)

        event_bus.subscribe(EventType.SESSION_STARTED, handler)
        await event_bus.emit(AgentEvent(
            type=EventType.SESSION_STARTED,
            source_agent="orchestrator",
            session_id="s1",
        ))
        assert len(received) == 1
        assert received[0].type == EventType.SESSION_STARTED

    @pytest.mark.asyncio
    async def test_handler_not_fired_for_other_types(self, event_bus):
        received = []

        async def handler(event):
            received.append(event)

        event_bus.subscribe(EventType.SESSION_STARTED, handler)
        await event_bus.emit(AgentEvent(
            type=EventType.SESSION_ENDED,
            source_agent="orchestrator",
        ))
        assert len(received) == 0

    @pytest.mark.asyncio
    async def test_multiple_handlers(self, event_bus):
        counts = {"a": 0, "b": 0}

        async def handler_a(event):
            counts["a"] += 1

        async def handler_b(event):
            counts["b"] += 1

        event_bus.subscribe(EventType.TASK_COMPLETED, handler_a)
        event_bus.subscribe(EventType.TASK_COMPLETED, handler_b)
        await event_bus.emit(AgentEvent(
            type=EventType.TASK_COMPLETED,
            source_agent="neo",
        ))
        assert counts["a"] == 1
        assert counts["b"] == 1

    @pytest.mark.asyncio
    async def test_handler_exception_does_not_break_emit(self, event_bus):
        received = []

        async def bad_handler(event):
            raise RuntimeError("boom")

        async def good_handler(event):
            received.append(event)

        event_bus.subscribe(EventType.AGENT_ERROR, bad_handler)
        event_bus.subscribe(EventType.AGENT_ERROR, good_handler)
        await event_bus.emit(AgentEvent(
            type=EventType.AGENT_ERROR,
            source_agent="neo",
        ))
        # Good handler should still fire despite bad handler raising
        assert len(received) == 1


class TestAgentSpecificHandlers:
    """Handlers scoped to a specific agent."""

    @pytest.mark.asyncio
    async def test_agent_handler_fires_for_target(self, event_bus):
        received = []

        async def handler(event):
            received.append(event)

        event_bus.subscribe(EventType.MESSAGE_SENT, handler, agent_name="trinity")
        await event_bus.emit(AgentEvent(
            type=EventType.MESSAGE_SENT,
            source_agent="neo",
            target_agent="trinity",
        ))
        assert len(received) == 1

    @pytest.mark.asyncio
    async def test_agent_handler_skipped_for_other_target(self, event_bus):
        received = []

        async def handler(event):
            received.append(event)

        event_bus.subscribe(EventType.MESSAGE_SENT, handler, agent_name="trinity")
        await event_bus.emit(AgentEvent(
            type=EventType.MESSAGE_SENT,
            source_agent="neo",
            target_agent="morpheus",
        ))
        assert len(received) == 0

    @pytest.mark.asyncio
    async def test_broadcast_does_not_fire_agent_handler(self, event_bus):
        received = []

        async def handler(event):
            received.append(event)

        event_bus.subscribe(EventType.SESSION_STARTED, handler, agent_name="trinity")
        # Broadcast (no target_agent)
        await event_bus.emit(AgentEvent(
            type=EventType.SESSION_STARTED,
            source_agent="orchestrator",
        ))
        assert len(received) == 0


class TestEventLogPersistence:
    """Event log writing and in-memory retention."""

    @pytest.mark.asyncio
    async def test_events_logged_in_memory(self, event_bus):
        await event_bus.emit(AgentEvent(
            type=EventType.TASK_DELEGATED,
            source_agent="trinity",
            target_agent="neo",
            session_id="s1",
        ))
        events = event_bus.get_events()
        assert len(events) == 1
        assert events[0].type == EventType.TASK_DELEGATED

    @pytest.mark.asyncio
    async def test_events_persisted_to_disk(self, event_bus, tmp_path):
        await event_bus.emit(AgentEvent(
            type=EventType.AUDIT_BLOCKED,
            source_agent="glasswing",
            payload={"reason": "critical vuln"},
        ))
        log_path = tmp_path / "hivemind" / "events.jsonl"
        assert log_path.exists()
        lines = log_path.read_text().strip().splitlines()
        assert len(lines) == 1
        data = json.loads(lines[0])
        assert data["type"] == "security.audit_blocked"

    @pytest.mark.asyncio
    async def test_log_trimmed_at_max_size(self, event_bus):
        for i in range(1100):
            await event_bus.emit(AgentEvent(
                type=EventType.AGENT_IDLE,
                source_agent="neo",
                payload={"i": i},
            ))
        # Internal log should be capped at 1000
        assert len(event_bus._event_log) <= 1000

    @pytest.mark.asyncio
    async def test_clear_log(self, event_bus):
        await event_bus.emit(AgentEvent(
            type=EventType.SESSION_STARTED,
            source_agent="orchestrator",
        ))
        assert len(event_bus._event_log) == 1
        event_bus.clear_log()
        assert len(event_bus._event_log) == 0


class TestEventFiltering:
    """get_events filtering by type, agent, and session."""

    @pytest.mark.asyncio
    async def test_filter_by_type(self, event_bus):
        await event_bus.emit(AgentEvent(type=EventType.SESSION_STARTED, source_agent="o"))
        await event_bus.emit(AgentEvent(type=EventType.TASK_COMPLETED, source_agent="neo"))
        await event_bus.emit(AgentEvent(type=EventType.SESSION_STARTED, source_agent="o"))

        results = event_bus.get_events(event_type=EventType.SESSION_STARTED)
        assert len(results) == 2

    @pytest.mark.asyncio
    async def test_filter_by_agent(self, event_bus):
        await event_bus.emit(AgentEvent(type=EventType.TASK_COMPLETED, source_agent="neo"))
        await event_bus.emit(AgentEvent(type=EventType.TASK_FAILED, source_agent="trinity"))
        await event_bus.emit(AgentEvent(type=EventType.MESSAGE_SENT, source_agent="neo", target_agent="trinity"))

        results = event_bus.get_events(agent="neo")
        assert len(results) == 2  # source=neo and target involving neo

    @pytest.mark.asyncio
    async def test_filter_by_session(self, event_bus):
        await event_bus.emit(AgentEvent(type=EventType.SESSION_STARTED, source_agent="o", session_id="s1"))
        await event_bus.emit(AgentEvent(type=EventType.SESSION_STARTED, source_agent="o", session_id="s2"))
        await event_bus.emit(AgentEvent(type=EventType.MESSAGE_SENT, source_agent="neo", session_id="s1"))

        results = event_bus.get_events(session_id="s1")
        assert len(results) == 2

    @pytest.mark.asyncio
    async def test_limit_parameter(self, event_bus):
        for _ in range(10):
            await event_bus.emit(AgentEvent(type=EventType.AGENT_IDLE, source_agent="neo"))
        results = event_bus.get_events(limit=3)
        assert len(results) == 3


class TestAgentEventSerialization:
    """AgentEvent to_dict / from_dict round-trip."""

    def test_round_trip(self):
        original = AgentEvent(
            type=EventType.MORPHEUS_INTERVENTION,
            source_agent="morpheus",
            target_agent="trinity",
            payload={"trigger": "first_use"},
            session_id="sess123",
        )
        d = original.to_dict()
        restored = AgentEvent.from_dict(d)
        assert restored.type == original.type
        assert restored.source_agent == original.source_agent
        assert restored.target_agent == original.target_agent
        assert restored.payload == original.payload
        assert restored.session_id == original.session_id

    def test_to_dict_type_is_string(self):
        event = AgentEvent(type=EventType.SESSION_STARTED, source_agent="o")
        d = event.to_dict()
        assert isinstance(d["type"], str)
        assert d["type"] == "session.started"
