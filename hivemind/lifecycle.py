"""
Agent Lifecycle Manager — manages agent sessions, hooks, and state transitions.

Provides a managed lifecycle for each agent session:
  init → ready → active → idle → (active → idle)* → shutdown

Hooks fire at each transition, enabling logging, metrics, security checks,
and cross-agent coordination without modifying agent logic.

Hook Points:
- pre_session_start  — before agent context is built
- post_session_start — after agent is ready to receive messages
- pre_tool_use       — before any tool call executes
- post_tool_use      — after tool call returns
- pre_shutdown       — before session cleanup
- post_shutdown      — after session is torn down
- on_error           — when an unrecoverable error occurs
- on_resume          — when a session is restored from persistence
"""

import asyncio
import json
import logging
import time
import uuid
from dataclasses import dataclass, field
from enum import Enum
from pathlib import Path
from typing import Any, Callable, Awaitable

logger = logging.getLogger(__name__)


class SessionState(str, Enum):
    INITIALIZING = "initializing"
    READY = "ready"
    ACTIVE = "active"
    IDLE = "idle"
    SHUTTING_DOWN = "shutting_down"
    TERMINATED = "terminated"
    ERROR = "error"


class HookPoint(str, Enum):
    PRE_SESSION_START = "pre_session_start"
    POST_SESSION_START = "post_session_start"
    PRE_TOOL_USE = "pre_tool_use"
    POST_TOOL_USE = "post_tool_use"
    PRE_SHUTDOWN = "pre_shutdown"
    POST_SHUTDOWN = "post_shutdown"
    ON_ERROR = "on_error"
    ON_RESUME = "on_resume"


# Type for lifecycle hook functions
LifecycleHook = Callable[["AgentSession", dict], Awaitable[None]]


@dataclass
class AgentSession:
    """Represents a running agent instance within a session."""

    session_id: str
    agent_name: str
    state: SessionState = SessionState.INITIALIZING
    created_at: float = field(default_factory=time.time)
    last_active: float = field(default_factory=time.time)
    message_count: int = 0
    tool_calls: int = 0
    errors: int = 0
    metadata: dict = field(default_factory=dict)

    def to_dict(self) -> dict:
        return {
            "session_id": self.session_id,
            "agent_name": self.agent_name,
            "state": self.state.value,
            "created_at": self.created_at,
            "last_active": self.last_active,
            "message_count": self.message_count,
            "tool_calls": self.tool_calls,
            "errors": self.errors,
            "metadata": self.metadata,
        }

    @classmethod
    def from_dict(cls, d: dict) -> "AgentSession":
        d = dict(d)
        d["state"] = SessionState(d["state"])
        return cls(**d)


class LifecycleManager:
    """
    Manages agent sessions and lifecycle hooks.

    Each session tracks an agent's state, activity counts, and metadata.
    Hooks are registered per HookPoint and fire in order during state
    transitions. Sessions can be persisted and resumed.
    """

    def __init__(self, workspace: str = "."):
        self._sessions: dict[str, AgentSession] = {}
        self._hooks: dict[HookPoint, list[LifecycleHook]] = {
            hp: [] for hp in HookPoint
        }
        self._session_dir = Path(workspace) / "hivemind" / "sessions"
        self._session_dir.mkdir(parents=True, exist_ok=True)

    # ─── Hook Registration ────────────────────────────────────────────────

    def register_hook(self, point: HookPoint, hook: LifecycleHook):
        """Register a lifecycle hook for a specific point."""
        self._hooks[point].append(hook)

    async def _fire_hooks(self, point: HookPoint, session: AgentSession, ctx: dict):
        """Fire all hooks registered at the given point."""
        for hook in self._hooks[point]:
            try:
                await hook(session, ctx)
            except Exception as e:
                logger.error(
                    f"Lifecycle hook error at {point.value} for "
                    f"{session.agent_name}/{session.session_id}: {e}",
                    exc_info=True,
                )

    # ─── Session Management ───────────────────────────────────────────────

    async def start_session(
        self,
        agent_name: str,
        session_id: str | None = None,
        metadata: dict | None = None,
    ) -> AgentSession:
        """
        Start a new agent session. Fires pre/post session start hooks.
        """
        sid = session_id or uuid.uuid4().hex[:16]
        session = AgentSession(
            session_id=sid,
            agent_name=agent_name,
            metadata=metadata or {},
        )

        self._sessions[sid] = session

        # Pre-start hooks (can modify metadata, validate, etc.)
        await self._fire_hooks(HookPoint.PRE_SESSION_START, session, {})

        session.state = SessionState.READY
        self._persist_session(session)

        # Post-start hooks (logging, metrics, notifications)
        await self._fire_hooks(HookPoint.POST_SESSION_START, session, {})

        logger.info(f"Session started: {agent_name}/{sid}")
        return session

    async def end_session(self, session_id: str):
        """
        End a session gracefully. Fires pre/post shutdown hooks.
        """
        session = self._sessions.get(session_id)
        if not session:
            return

        session.state = SessionState.SHUTTING_DOWN
        await self._fire_hooks(HookPoint.PRE_SHUTDOWN, session, {})

        session.state = SessionState.TERMINATED
        self._persist_session(session)

        await self._fire_hooks(HookPoint.POST_SHUTDOWN, session, {})

        logger.info(
            f"Session ended: {session.agent_name}/{session_id} "
            f"(messages={session.message_count}, tools={session.tool_calls})"
        )

    async def resume_session(self, session_id: str) -> AgentSession | None:
        """
        Resume a previously persisted session. Returns None if not found.
        """
        # Check in-memory first
        if session_id in self._sessions:
            session = self._sessions[session_id]
            if session.state == SessionState.TERMINATED:
                return None
            session.state = SessionState.READY
            await self._fire_hooks(HookPoint.ON_RESUME, session, {})
            return session

        # Try loading from disk
        path = self._session_dir / f"{session_id}.json"
        if not path.exists():
            return None

        try:
            data = json.loads(path.read_text())
            session = AgentSession.from_dict(data)
            session.state = SessionState.READY
            self._sessions[session_id] = session
            await self._fire_hooks(HookPoint.ON_RESUME, session, {})
            logger.info(f"Session resumed: {session.agent_name}/{session_id}")
            return session
        except Exception as e:
            logger.error(f"Failed to resume session {session_id}: {e}")
            return None

    # ─── Activity Tracking ────────────────────────────────────────────────

    async def record_message(self, session_id: str):
        """Record that a message was processed in this session."""
        session = self._sessions.get(session_id)
        if session:
            session.message_count += 1
            session.last_active = time.time()
            session.state = SessionState.ACTIVE

    async def record_tool_use(
        self,
        session_id: str,
        tool_name: str,
        arguments: dict,
        result: Any = None,
    ):
        """Record a tool call. Fires pre/post tool use hooks."""
        session = self._sessions.get(session_id)
        if not session:
            return

        ctx = {"tool_name": tool_name, "arguments": arguments}
        await self._fire_hooks(HookPoint.PRE_TOOL_USE, session, ctx)

        session.tool_calls += 1
        session.last_active = time.time()

        ctx["result"] = result
        await self._fire_hooks(HookPoint.POST_TOOL_USE, session, ctx)

    async def record_error(self, session_id: str, error: str):
        """Record an error in this session."""
        session = self._sessions.get(session_id)
        if session:
            session.errors += 1
            session.state = SessionState.ERROR
            await self._fire_hooks(
                HookPoint.ON_ERROR, session, {"error": error}
            )

    def mark_idle(self, session_id: str):
        """Mark a session as idle (finished processing current request)."""
        session = self._sessions.get(session_id)
        if session and session.state == SessionState.ACTIVE:
            session.state = SessionState.IDLE

    # ─── Queries ──────────────────────────────────────────────────────────

    def get_session(self, session_id: str) -> AgentSession | None:
        return self._sessions.get(session_id)

    def get_active_sessions(self) -> list[AgentSession]:
        return [
            s for s in self._sessions.values()
            if s.state in (SessionState.READY, SessionState.ACTIVE, SessionState.IDLE)
        ]

    def get_agent_sessions(self, agent_name: str) -> list[AgentSession]:
        return [
            s for s in self._sessions.values()
            if s.agent_name == agent_name
        ]

    # ─── Persistence ──────────────────────────────────────────────────────

    def _persist_session(self, session: AgentSession):
        """Save session state to disk."""
        try:
            path = self._session_dir / f"{session.session_id}.json"
            path.write_text(json.dumps(session.to_dict(), default=str, indent=2))
        except Exception as e:
            logger.error(f"Failed to persist session {session.session_id}: {e}")
