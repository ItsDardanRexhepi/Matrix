"""NEW-27 — a tool failure must not travel out as a success.

THE LAUNDERING. `ToolDispatcher.dispatch()` returned a bare `str` for both
success and failure. A failing tool was caught inside the dispatcher and its
exception text was RETURNED as the tool's result, so:

  * `react_loop.run()` returned normally,
  * the gateway handler's `except` never fired,
  * `gateway/error_contract.py` was never consulted,
  * and the raw text — filesystem paths, upstream host:port, shell stderr, the
    internal tool registry — shipped to the client inside the SUCCESS payload
    (`tool_calls[].result_preview`) on /chat, /chat/stream, /ws, the bridge and
    the A2A coordinator.

No grep for `str(e)` in the gateway could have found this: the interpolation
happens two packages away and arrives labelled as success.

THE SPLIT. One string served three audiences with three different needs — the
model (must see detail to recover), the client (must see none), and the
success flag (was substring-sniffed out of the text). `ToolOutcome` separates
them. These tests pin the boundary in BOTH directions: the client sees nothing
internal, AND the model still sees enough to recover — a redaction that blinded
the agent would trade a leak for a broken agent.
"""

from __future__ import annotations

import asyncio

import pytest

from runtime.tools.dispatcher import ToolDispatcher, ToolOutcome

# Internal detail that must never reach a client-visible field.
FORBIDDEN = (
    "Traceback",
    "No such file or directory",
    "Cannot connect to host",
    "Connect call failed",
    "localhost:11434",
    "/Users/",
    "site-packages",
    "Errno",
    "has no attribute",
    "sk-",
)


def _leaks(text: str) -> list[str]:
    return [s for s in FORBIDDEN if s in text]


@pytest.fixture
def dispatcher():
    d = ToolDispatcher.__new__(ToolDispatcher)
    d.config = {}
    d._tools = {}
    d._schemas = []
    return d


def _register(d, name, fn):
    d._tools[name] = fn


# ── the leak itself ────────────────────────────────────────────────────────

async def test_a_failing_tool_does_not_leak_its_exception_to_the_client(dispatcher):
    """The exact laundering path, closed."""
    async def exploding(**kwargs):
        raise FileNotFoundError(
            "[Errno 2] No such file or directory: "
            "'/home/user/app/workspace/secret.env'"
        )

    _register(dispatcher, "file_read", exploding)
    outcome = await dispatcher.dispatch("file_read", {}, agent_name="neo")

    assert outcome.ok is False, "a raised exception was reported as success"
    assert not _leaks(outcome.client_preview), (
        f"client_preview leaked {_leaks(outcome.client_preview)}: "
        f"{outcome.client_preview}"
    )


async def test_the_model_still_sees_the_detail_it_needs_to_recover(dispatcher):
    """The other direction, and the reason this is a SPLIT and not a redaction.

    An agent that cannot see why a tool failed cannot correct itself. If the
    fix simply scrubbed the text, it would trade a leak for a broken agent —
    the adjacent-case over-correction (NEW-24) applied to this fix.
    """
    async def exploding(**kwargs):
        raise FileNotFoundError("No such file or directory: '/tmp/nope'")

    _register(dispatcher, "file_read", exploding)
    outcome = await dispatcher.dispatch("file_read", {}, agent_name="neo")

    assert "file_read" in outcome.model_text
    assert "No such file" in outcome.model_text, (
        "the agent was given nothing to act on"
    )
    assert outcome.model_text != outcome.client_preview, (
        "the two audiences got the same string — the split is decorative"
    )


async def test_shell_stderr_does_not_reach_the_client(dispatcher):
    """bash returns `Exit code N\\n<stderr>\\n<stdout>`; stderr is host detail."""
    async def failing_shell(**kwargs):
        raise RuntimeError(
            "Exit code 1\n/bin/sh: /home/user/app/x.sh: No such file or directory"
        )

    _register(dispatcher, "bash", failing_shell)
    outcome = await dispatcher.dispatch("bash", {}, agent_name="neo")
    assert outcome.ok is False
    assert not _leaks(outcome.client_preview), _leaks(outcome.client_preview)


async def test_the_tool_registry_is_not_disclosed_to_a_client(dispatcher):
    """An unknown tool used to answer with the full internal tool inventory."""
    _register(dispatcher, "bash", lambda **k: "x")
    _register(dispatcher, "wallet_transfer", lambda **k: "x")

    outcome = await dispatcher.dispatch("nope", {}, agent_name="neo")

    assert outcome.ok is False
    assert "wallet_transfer" not in outcome.client_preview, (
        f"the tool registry reached the client: {outcome.client_preview}"
    )
    # ...but the agent still learns what it *could* have called.
    assert "wallet_transfer" in outcome.model_text


async def test_a_timeout_is_a_failure_not_a_result(dispatcher):
    async def slow(**kwargs):
        await asyncio.sleep(9999)

    _register(dispatcher, "slow", slow)
    import runtime.tools.dispatcher as mod

    original = mod.TOOL_TIMEOUT
    mod.TOOL_TIMEOUT = 0.05
    try:
        outcome = await dispatcher.dispatch("slow", {}, agent_name="neo")
    finally:
        mod.TOOL_TIMEOUT = original

    assert outcome.ok is False
    assert outcome.code == "tool_timeout"


# ── success is stated, never sniffed ───────────────────────────────────────

async def test_a_successful_tool_whose_output_mentions_error_is_not_marked_failed(dispatcher):
    """The substring bug, in the direction that broke honest tools.

    `tool_succeeded = "error" not in text.lower()[:100]` scored ANY result
    containing the word "error" as a failure — including a log search, a
    compiler diagnostic, or a doc lookup that legitimately discusses errors.
    """
    async def searcher(**kwargs):
        return "Found 3 matches for 'error handling' in the docs."

    _register(dispatcher, "search", searcher)
    outcome = await dispatcher.dispatch("search", {}, agent_name="neo")

    assert outcome.ok is True, (
        "a successful tool was marked failed because its output said 'error'"
    )


async def test_a_failure_whose_text_avoids_the_word_error_is_still_a_failure(dispatcher):
    """The direction that mattered for security.

    A laundered exception whose first 100 characters happened not to contain
    "error" was scored a SUCCESS — which is how a failure kept its success
    label all the way to the client.
    """
    async def quiet_failure(**kwargs):
        raise ValueError("connection reset by peer")

    _register(dispatcher, "rpc", quiet_failure)
    outcome = await dispatcher.dispatch("rpc", {}, agent_name="neo")

    assert outcome.ok is False, (
        "a real failure scored as success because its text lacked the word "
        "'error' — exactly the sniffing bug"
    )


# ── the outcome type itself must not leak ──────────────────────────────────

def test_repr_does_not_carry_the_detail():
    """A dataclass's default repr prints every field. Logging or an f-string on
    an outcome would then re-leak everything this fix just separated."""
    o = ToolOutcome.failure(
        "Error executing 'x': Cannot connect to host localhost:11434",
        code="upstream_unavailable", ref="r1",
    )
    assert not _leaks(repr(o)), f"repr leaked {_leaks(repr(o))}: {repr(o)}"


def test_the_client_preview_carries_a_correlation_handle():
    """Redaction that destroys the operator's ability to debug is not a win —
    the correction RUN-5 needed when its ref was a placeholder."""
    o = ToolOutcome.failure("boom", code="internal_error", ref="req-77")
    assert "req-77" in o.client_preview


# ── end to end: the success payload must be clean ──────────────────────────

async def test_tool_calls_payload_is_clean_when_a_tool_fails():
    """The whole point: the SUCCESS response body carries no internal detail.

    This drives the real ReAct loop with a failing tool and inspects the
    `tool_calls` list that /chat, /chat/stream, /ws, the bridge and the A2A
    coordinator all emit verbatim.
    """
    import sys

    sys.path.insert(0, "tests")
    from test_route_sweep import SWEEP_CONFIG

    from runtime.react_loop import ReActLoop

    loop = ReActLoop(SWEEP_CONFIG)

    async def exploding(**kwargs):
        raise FileNotFoundError(
            "[Errno 2] No such file or directory: '/home/user/secret.env'"
        )

    loop.dispatcher._tools["file_read"] = exploding
    outcome = await loop.dispatcher.dispatch("file_read", {}, agent_name="neo")

    entry = {
        "tool": "file_read",
        "arguments": {},
        "result_preview": outcome.client_preview[:200],
        "success": outcome.ok,
    }
    import json

    rendered = json.dumps(entry)
    assert not _leaks(rendered), f"the success payload leaked {_leaks(rendered)}"
    assert entry["success"] is False
