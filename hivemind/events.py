"""
Agent Event System — typed, async event-driven communication between agents.

Inspired by managed agent orchestration patterns where agents communicate
through structured events rather than direct function calls. Each event
carries a type, source, target, and payload — enabling decoupled, auditable
inter-agent communication.

Event Types:
- session.started / session.ended — session lifecycle
- agent.spawned / agent.idle / agent.error — agent lifecycle
- agent.message_sent / agent.message_received — inter-agent messaging
- task.delegated / task.completed / task.failed — task lifecycle
- security.audit_requested / security.audit_completed — Glasswing audit events
- morpheus.intervention — Morpheus triggered
"""

import asyncio
import json
import logging
import time
import uuid
from dataclasses import dataclass, field, asdict
from enum import Enum
from pathlib import Path
from typing import Any, Callable, Awaitable

logger = logging.getLogger(__name__)


class EventType(str, Enum):
    # Session lifecycle
    SESSION_STARTED = "session.started"
    SESSION_ENDED = "session.ended"
    SESSION_RESUMED = "session.resumed"

    # Agent lifecycle
    AGENT_SPAWNED = "agent.spawned"
    AGENT_IDLE = "agent.idle"
    AGENT_ERROR = "agent.error"

    # Inter-agent communication
    MESSAGE_SENT = "agent.message_sent"
    MESSAGE_RECEIVED = "agent.message_received"

    # Task lifecycle
    TASK_DELEGATED = "task.delegated"
    TASK_COMPLETED = "task.completed"
    TASK_FAILED = "task.failed"

    # Security / Glasswing
    AUDIT_REQUESTED = "security.audit_requested"
    AUDIT_COMPLETED = "security.audit_completed"
    AUDIT_BLOCKED = "security.audit_blocked"

    # Morpheus
    MORPHEUS_INTERVENTION = "morpheus.intervention"
    MORPHEUS_FIRST_USE = "morpheus.first_use"

    # Protocol
    PROTOCOL_ENRICHMENT = "protocol.enrichment"
    CONSENSUS_REACHED = "hivemind.consensus"


@dataclass
class AgentEvent:
    """A typed event flowing between agents."""

    type: EventType
    source_agent: str
    target_agent: str | None = None  # None = broadcast
    payload: dict = field(default_factory=dict)
    session_id: str = ""
    event_id: str = field(default_factory=lambda: uuid.uuid4().hex[:12])
    timestamp: float = field(default_factory=time.time)

    def to_dict(self) -> dict:
        d = asdict(self)
        d["type"] = self.type.value
        return d

    @classmethod
    def from_dict(cls, d: dict) -> "AgentEvent":
        d = dict(d)
        d["type"] = EventType(d["type"])
        return cls(**d)


# Type alias for event handlers
EventHandler = Callable[[AgentEvent], Awaitable[None]]


class EventBus:
    """
    Central event bus for agent-to-agent communication.

    Supports:
    - Typed event subscriptions (subscribe to specific EventTypes)
    - Broadcast events (no target_agent — all subscribers see it)
    - Directed events (only handlers for target_agent + type fire)
    - Event log with persistence for audit trails
    - Async handler execution
    """

    def __init__(self, workspace: str = "."):
        self._handlers: dict[EventType, list[EventHandler]] = {}
        self._agent_handlers: dict[str, dict[EventType, list[EventHandler]]] = {}
        self._event_log: list[AgentEvent] = []
        self._max_log_size = 1000
        self._log_path = Path(workspace) / "hivemind" / "events.jsonl"
        self._log_path.parent.mkdir(parents=True, exist_ok=True)

    def subscribe(
        self,
        event_type: EventType,
        handler: EventHandler,
        agent_name: str | None = None,
    ):
        """
        Subscribe to an event type.

        If agent_name is provided, the handler only fires for events
        targeted at that agent. Otherwise it fires for all events of
        this type (including broadcasts).
        """
        if agent_name:
            if agent_name not in self._agent_handlers:
                self._agent_handlers[agent_name] = {}
            if event_type not in self._agent_handlers[agent_name]:
                self._agent_handlers[agent_name][event_type] = []
            self._agent_handlers[agent_name][event_type].append(handler)
        else:
            if event_type not in self._handlers:
                self._handlers[event_type] = []
            self._handlers[event_type].append(handler)

    async def emit(self, event: AgentEvent):
        """
        Emit an event to all matching subscribers.

        Fires global handlers for the event type, plus agent-specific
        handlers if a target_agent is set.
        """
        # Log the event
        self._record(event)

        # Fire global handlers for this event type
        for handler in self._handlers.get(event.type, []):
            try:
                await handler(event)
            except Exception as e:
                logger.error(
                    f"Event handler error ({event.type.value}): {e}",
                    exc_info=True,
                )

        # Fire agent-specific handlers
        if event.target_agent:
            agent_handlers = self._agent_handlers.get(event.target_agent, {})
            for handler in agent_handlers.get(event.type, []):
                try:
                    await handler(event)
                except Exception as e:
                    logger.error(
                        f"Agent handler error ({event.target_agent}, "
                        f"{event.type.value}): {e}",
                        exc_info=True,
                    )

    def _record(self, event: AgentEvent):
        """Append to in-memory log and persist to disk."""
        self._event_log.append(event)
        if len(self._event_log) > self._max_log_size:
            self._event_log = self._event_log[-self._max_log_size:]

        try:
            with open(self._log_path, "a") as f:
                f.write(json.dumps(event.to_dict(), default=str) + "\n")
        except Exception as e:
            logger.error(f"Failed to persist event: {e}")

    def get_events(
        self,
        event_type: EventType | None = None,
        agent: str | None = None,
        session_id: str | None = None,
        limit: int = 50,
    ) -> list[AgentEvent]:
        """Query the event log with optional filters."""
        events = self._event_log
        if event_type:
            events = [e for e in events if e.type == event_type]
        if agent:
            events = [
                e for e in events
                if e.source_agent == agent or e.target_agent == agent
            ]
        if session_id:
            events = [e for e in events if e.session_id == session_id]
        return events[-limit:]

    def clear_log(self):
        """Clear the in-memory event log."""
        self._event_log.clear()
