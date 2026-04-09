"""Tests for hivemind.lifecycle.LifecycleManager and AgentSession."""

import json

import pytest

from hivemind.lifecycle import (
    LifecycleManager,
    AgentSession,
    SessionState,
    HookPoint,
)


@pytest.fixture
def manager(tmp_path):
    return LifecycleManager(str(tmp_path))


@pytest.fixture
def session_dir(tmp_path):
    return tmp_path / "hivemind" / "sessions"


class TestSessionStartEnd:
    """Starting and ending sessions."""

    @pytest.mark.asyncio
    async def test_start_session_returns_session(self, manager):
        session = await manager.start_session("trinity", session_id="s1")
        assert isinstance(session, AgentSession)
        assert session.agent_name == "trinity"
        assert session.session_id == "s1"

    @pytest.mark.asyncio
    async def test_start_session_state_is_ready(self, manager):
        session = await manager.start_session("trinity", session_id="s1")
        assert session.state == SessionState.READY

    @pytest.mark.asyncio
    async def test_start_generates_id_if_omitted(self, manager):
        session = await manager.start_session("neo")
        assert len(session.session_id) > 0

    @pytest.mark.asyncio
    async def test_end_session_marks_terminated(self, manager):
        session = await manager.start_session("neo", session_id="s1")
        await manager.end_session("s1")
        assert session.state == SessionState.TERMINATED

    @pytest.mark.asyncio
    async def test_end_nonexistent_session_is_noop(self, manager):
        # Should not raise
        await manager.end_session("does_not_exist")

    @pytest.mark.asyncio
    async def test_get_session(self, manager):
        await manager.start_session("neo", session_id="s1")
        s = manager.get_session("s1")
        assert s is not None
        assert s.agent_name == "neo"

    @pytest.mark.asyncio
    async def test_get_session_missing(self, manager):
        assert manager.get_session("nope") is None


class TestSessionResumeFromDisk:
    """Session persistence and resume."""

    @pytest.mark.asyncio
    async def test_session_persisted_to_disk(self, manager, session_dir):
        await manager.start_session("trinity", session_id="s1")
        path = session_dir / "s1.json"
        assert path.exists()
        data = json.loads(path.read_text())
        assert data["agent_name"] == "trinity"

    @pytest.mark.asyncio
    async def test_resume_from_disk(self, tmp_path):
        # Start and end a session with one manager instance
        mgr1 = LifecycleManager(str(tmp_path))
        await mgr1.start_session("neo", session_id="s1", metadata={"key": "val"})

        # Create a new manager (simulates restart) and resume
        mgr2 = LifecycleManager(str(tmp_path))
        session = await mgr2.resume_session("s1")
        assert session is not None
        assert session.agent_name == "neo"
        assert session.state == SessionState.READY
        assert session.metadata.get("key") == "val"

    @pytest.mark.asyncio
    async def test_resume_nonexistent_returns_none(self, manager):
        result = await manager.resume_session("no_such_session")
        assert result is None

    @pytest.mark.asyncio
    async def test_resume_terminated_returns_none(self, manager):
        await manager.start_session("neo", session_id="s1")
        await manager.end_session("s1")
        result = await manager.resume_session("s1")
        assert result is None

    @pytest.mark.asyncio
    async def test_resume_in_memory_session(self, manager):
        await manager.start_session("neo", session_id="s1")
        session = await manager.resume_session("s1")
        assert session is not None
        assert session.state == SessionState.READY


class TestHookFiring:
    """Hooks fire at the correct lifecycle points."""

    @pytest.mark.asyncio
    async def test_pre_session_start_hook(self, manager):
        fired = []

        async def hook(session, ctx):
            fired.append("pre_start")

        manager.register_hook(HookPoint.PRE_SESSION_START, hook)
        await manager.start_session("neo", session_id="s1")
        assert "pre_start" in fired

    @pytest.mark.asyncio
    async def test_post_session_start_hook(self, manager):
        fired = []

        async def hook(session, ctx):
            fired.append(session.state.value)

        manager.register_hook(HookPoint.POST_SESSION_START, hook)
        await manager.start_session("neo", session_id="s1")
        # Post-start fires after state is set to READY
        assert "ready" in fired

    @pytest.mark.asyncio
    async def test_pre_and_post_shutdown_hooks(self, manager):
        fired = []

        async def pre_hook(session, ctx):
            fired.append(("pre", session.state.value))

        async def post_hook(session, ctx):
            fired.append(("post", session.state.value))

        manager.register_hook(HookPoint.PRE_SHUTDOWN, pre_hook)
        manager.register_hook(HookPoint.POST_SHUTDOWN, post_hook)
        await manager.start_session("neo", session_id="s1")
        await manager.end_session("s1")
        assert ("pre", "shutting_down") in fired
        assert ("post", "terminated") in fired

    @pytest.mark.asyncio
    async def test_on_error_hook(self, manager):
        fired = []

        async def hook(session, ctx):
            fired.append(ctx.get("error"))

        manager.register_hook(HookPoint.ON_ERROR, hook)
        await manager.start_session("neo", session_id="s1")
        await manager.record_error("s1", "something broke")
        assert fired == ["something broke"]

    @pytest.mark.asyncio
    async def test_on_resume_hook(self, manager):
        fired = []

        async def hook(session, ctx):
            fired.append(session.session_id)

        manager.register_hook(HookPoint.ON_RESUME, hook)
        await manager.start_session("neo", session_id="s1")
        await manager.resume_session("s1")
        assert "s1" in fired

    @pytest.mark.asyncio
    async def test_pre_post_tool_use_hooks(self, manager):
        fired = []

        async def pre_hook(session, ctx):
            fired.append(("pre_tool", ctx["tool_name"]))

        async def post_hook(session, ctx):
            fired.append(("post_tool", ctx["tool_name"], ctx.get("result")))

        manager.register_hook(HookPoint.PRE_TOOL_USE, pre_hook)
        manager.register_hook(HookPoint.POST_TOOL_USE, post_hook)
        await manager.start_session("neo", session_id="s1")
        await manager.record_tool_use("s1", "bash", {"command": "ls"}, result="file.txt")
        assert ("pre_tool", "bash") in fired
        assert ("post_tool", "bash", "file.txt") in fired

    @pytest.mark.asyncio
    async def test_hook_exception_does_not_crash(self, manager):
        async def bad_hook(session, ctx):
            raise RuntimeError("hook crashed")

        manager.register_hook(HookPoint.POST_SESSION_START, bad_hook)
        # Should not raise
        session = await manager.start_session("neo", session_id="s1")
        assert session.state == SessionState.READY


class TestActivityTracking:
    """Message, tool, and error counters."""

    @pytest.mark.asyncio
    async def test_record_message_increments(self, manager):
        await manager.start_session("neo", session_id="s1")
        await manager.record_message("s1")
        await manager.record_message("s1")
        session = manager.get_session("s1")
        assert session.message_count == 2

    @pytest.mark.asyncio
    async def test_record_message_sets_active_state(self, manager):
        await manager.start_session("neo", session_id="s1")
        await manager.record_message("s1")
        assert manager.get_session("s1").state == SessionState.ACTIVE

    @pytest.mark.asyncio
    async def test_record_tool_use_increments(self, manager):
        await manager.start_session("neo", session_id="s1")
        await manager.record_tool_use("s1", "bash", {})
        await manager.record_tool_use("s1", "web_search", {})
        assert manager.get_session("s1").tool_calls == 2

    @pytest.mark.asyncio
    async def test_record_error_increments_and_sets_state(self, manager):
        await manager.start_session("neo", session_id="s1")
        await manager.record_error("s1", "timeout")
        session = manager.get_session("s1")
        assert session.errors == 1
        assert session.state == SessionState.ERROR

    @pytest.mark.asyncio
    async def test_mark_idle(self, manager):
        await manager.start_session("neo", session_id="s1")
        await manager.record_message("s1")  # sets ACTIVE
        manager.mark_idle("s1")
        assert manager.get_session("s1").state == SessionState.IDLE

    @pytest.mark.asyncio
    async def test_mark_idle_only_from_active(self, manager):
        await manager.start_session("neo", session_id="s1")
        # State is READY, not ACTIVE
        manager.mark_idle("s1")
        assert manager.get_session("s1").state == SessionState.READY

    @pytest.mark.asyncio
    async def test_get_active_sessions(self, manager):
        await manager.start_session("neo", session_id="s1")
        await manager.start_session("trinity", session_id="s2")
        await manager.start_session("morpheus", session_id="s3")
        await manager.end_session("s3")
        active = manager.get_active_sessions()
        assert len(active) == 2

    @pytest.mark.asyncio
    async def test_get_agent_sessions(self, manager):
        await manager.start_session("neo", session_id="s1")
        await manager.start_session("neo", session_id="s2")
        await manager.start_session("trinity", session_id="s3")
        neo_sessions = manager.get_agent_sessions("neo")
        assert len(neo_sessions) == 2


class TestAgentSessionSerialization:
    """AgentSession to_dict/from_dict round-trip."""

    def test_round_trip(self):
        original = AgentSession(
            session_id="s1",
            agent_name="neo",
            state=SessionState.ACTIVE,
            message_count=5,
            tool_calls=3,
            errors=1,
            metadata={"key": "val"},
        )
        d = original.to_dict()
        restored = AgentSession.from_dict(d)
        assert restored.session_id == original.session_id
        assert restored.agent_name == original.agent_name
        assert restored.state == original.state
        assert restored.message_count == original.message_count
        assert restored.metadata == original.metadata
