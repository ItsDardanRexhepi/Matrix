#!/usr/bin/env python3
"""
Hivemind Orchestration Test — validates task delegation between agents.

Simulates:
1. User sends message to Trinity
2. Trinity delegates a bash command to Neo
3. Neo executes and returns result through Trinity
4. Morpheus triggers on irreversible actions and first-use detection

Run: python -m hivemind.test_orchestration
"""

import asyncio
import json
import sys
import os
from dataclasses import dataclass, field
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock

# Add project root to path
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from hivemind.orchestrator import (
    HivemindOrchestrator,
    MessageBus,
    SharedContextLayer,
    TaskRouter,
    TaskStatus,
    AgentRole,
    AGENT_CAPABILITIES,
)
from runtime.react_loop import ReActResult, Message


# ─── Mock ReAct Loop ────────────────────────────────────────────────────────

class MockReActLoop:
    """Simulates ReAct loop responses for testing without a live model."""

    def __init__(self):
        self.calls: list[dict] = []

    def get_agent_prompt(self, agent: str) -> str:
        prompts = {
            "neo": "You are Neo, the execution agent of 0pnMatrx.",
            "trinity": "You are Trinity, the conversation agent of 0pnMatrx.",
            "morpheus": "You are Morpheus, the guidance agent of 0pnMatrx.",
        }
        return prompts.get(agent, "")

    async def run(self, context) -> ReActResult:
        self.calls.append({
            "agent": context.agent_name,
            "messages": len(context.conversation),
        })

        if context.agent_name == "neo":
            return ReActResult(
                response="Command executed successfully. Output: total 42",
                tool_calls=[{"name": "bash", "arguments": {"command": "ls -la"}}],
                iterations=2,
                provider="mock",
            )
        elif context.agent_name == "trinity":
            return ReActResult(
                response="I've processed your request. Here's what happened.",
                tool_calls=[],
                iterations=1,
                provider="mock",
            )
        else:
            return ReActResult(
                response="Mock response",
                tool_calls=[],
                iterations=1,
                provider="mock",
            )

    async def run_without_tools(self, context) -> str:
        self.calls.append({
            "agent": context.agent_name,
            "type": "no_tools",
            "messages": len(context.conversation),
        })
        if context.agent_name == "morpheus":
            last_msg = context.conversation[-1].content if context.conversation else ""
            if "first time" in last_msg:
                return "Before you proceed: smart contracts are programs deployed to the blockchain. Once deployed, they cannot be modified. Make sure your code is audited."
            if "irreversible" in last_msg:
                return "⚠️ This action is permanent and cannot be undone. Please confirm you understand the consequences."
        return "Guidance provided."


# ─── Test Functions ─────────────────────────────────────────────────────────

passed = 0
failed = 0


def report(name: str, ok: bool, detail: str = ""):
    global passed, failed
    status = "✓ PASS" if ok else "✗ FAIL"
    print(f"  {status}: {name}")
    if not ok and detail:
        print(f"         {detail}")
    if ok:
        passed += 1
    else:
        failed += 1


async def test_message_bus():
    print("\n── MessageBus ──")
    import tempfile
    with tempfile.TemporaryDirectory() as tmpdir:
        bus = MessageBus(tmpdir)

        # Send and receive
        await bus.send("neo", {"task": "test", "data": "hello"})
        report("send succeeds", bus.pending_count("neo") == 1)

        msg = await bus.receive("neo", timeout=1.0)
        report("receive returns message", msg is not None and msg["data"] == "hello")
        report("queue empty after receive", bus.pending_count("neo") == 0)

        # Timeout on empty queue
        msg = await bus.receive("neo", timeout=0.1)
        report("receive returns None on timeout", msg is None)

        # Persistence — send, create new bus, verify loaded
        await bus.send("trinity", {"task": "persist_test"})
        bus2 = MessageBus(tmpdir)
        # Force load by accessing the queue
        msg = await bus2.receive("trinity", timeout=1.0)
        report("persistence across bus instances", msg is not None and msg["task"] == "persist_test")


async def test_shared_context():
    print("\n── SharedContextLayer ──")
    ctx = SharedContextLayer()

    ctx.set("key1", "value1")
    report("set and get", ctx.get("key1") == "value1")
    report("get with default", ctx.get("missing", "default") == "default")

    # Pub/sub
    received = []
    ctx.subscribe("key2", lambda k, v: received.append((k, v)))
    ctx.set("key2", "notified")
    report("subscriber notified", len(received) == 1 and received[0] == ("key2", "notified"))

    # get_all
    all_state = ctx.get_all()
    report("get_all returns full state", "key1" in all_state and "key2" in all_state)


async def test_task_router():
    print("\n── TaskRouter ──")
    router = TaskRouter()

    report("bash routes to neo", router.route("bash") == "neo")
    report("deploy routes to neo", router.route("deploy contract") == "neo")
    report("chat routes to trinity", router.route("chat") == "trinity")
    report("explain routes to trinity", router.route("explain this") == "trinity")
    report("security routes to morpheus", router.route("security check") == "morpheus")
    report("risk routes to morpheus", router.route("risk assessment") == "morpheus")
    report("unknown defaults to neo", router.route("something_unknown_xyz") == "neo")


async def test_orchestrator_handle_message():
    print("\n── Orchestrator: handle_message ──")
    mock_loop = MockReActLoop()
    config = {"workspace": "/tmp/test_hivemind", "agents": {}}
    orch = HivemindOrchestrator(config, mock_loop)

    # Normal conversation — should route to Trinity
    result = await orch.handle_message(
        "Hello, how are you?",
        session_id="test-session-1",
        conversation=[],
    )
    report("routes to trinity", result["agent"] == "trinity")
    report("returns response", len(result["response"]) > 0)
    report("morpheus not triggered", result["morpheus_triggered"] is False)


async def test_orchestrator_morpheus_triggers():
    print("\n── Orchestrator: Morpheus Triggers ──")
    mock_loop = MockReActLoop()
    config = {"workspace": "/tmp/test_hivemind", "agents": {}}
    orch = HivemindOrchestrator(config, mock_loop)

    # On-demand Morpheus
    result = await orch.handle_message(
        "explain what a smart contract is",
        session_id="test-session-2",
        conversation=[],
    )
    report("on-demand morpheus triggers", result["agent"] == "morpheus" and result["morpheus_triggered"])

    # First-use detection
    result = await orch.handle_message(
        "I want to deploy a smart contract",
        session_id="test-session-3",
        conversation=[],
    )
    report("first-use morpheus triggers", result["agent"] == "morpheus" and result["morpheus_triggered"])

    # Irreversible action (new session so first-use doesn't interfere)
    orch._user_firsts["test-session-4"] = {"smart contracts", "DeFi", "NFTs", "DAOs"}
    result = await orch.handle_message(
        "transfer 1 ETH to 0xabc",
        session_id="test-session-4",
        conversation=[],
    )
    report("irreversible action morpheus triggers", result["agent"] == "morpheus" and result["morpheus_triggered"])


async def test_delegate_task():
    print("\n── Orchestrator: Task Delegation ──")
    mock_loop = MockReActLoop()
    config = {"workspace": "/tmp/test_hivemind", "agents": {}}
    orch = HivemindOrchestrator(config, mock_loop)

    # Trinity delegates bash execution to Neo
    task = await orch.delegate_task(
        task_type="bash",
        payload={"command": "ls -la"},
        source_agent="trinity",
    )
    report("task created", task.id is not None)
    report("routed to neo", task.target_agent == "neo")
    report("task completed", task.status == TaskStatus.COMPLETED)
    report("result returned", task.result is not None)
    report("task tracked", task.id in orch.active_tasks)

    # Verify shared context was updated
    completed = orch.shared_context.get("task_completed")
    report("shared context updated", completed is not None and completed["task_id"] == task.id)


async def test_agent_capabilities():
    print("\n── Agent Capabilities ──")
    report("neo is execution", AGENT_CAPABILITIES["neo"]["role"] == AgentRole.EXECUTION)
    report("trinity is conversation", AGENT_CAPABILITIES["trinity"]["role"] == AgentRole.CONVERSATION)
    report("morpheus is guidance", AGENT_CAPABILITIES["morpheus"]["role"] == AgentRole.GUIDANCE)
    report("neo has blockchain caps", "blockchain" in AGENT_CAPABILITIES["neo"]["capabilities"])
    report("trinity has chat caps", "chat" in AGENT_CAPABILITIES["trinity"]["capabilities"])
    report("morpheus has security caps", "security" in AGENT_CAPABILITIES["morpheus"]["capabilities"])


# ─── Main ───────────────────────────────────────────────────────────────────

async def main():
    print("=" * 60)
    print("  0pnMatrx Hivemind Orchestration Test")
    print("=" * 60)

    await test_message_bus()
    await test_shared_context()
    await test_task_router()
    await test_agent_capabilities()
    await test_orchestrator_handle_message()
    await test_orchestrator_morpheus_triggers()
    await test_delegate_task()

    print("\n" + "=" * 60)
    print(f"  Results: {passed} passed, {failed} failed")
    print("=" * 60)

    if failed > 0:
        sys.exit(1)
    print("\n  All orchestration tests passed.\n")


if __name__ == "__main__":
    asyncio.run(main())
