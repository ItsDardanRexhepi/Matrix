"""
Hivemind Orchestrator — coordinates the three agents of 0pnMatrx.

Components:
- AgentOrchestrator: central coordinator for task assignment and tracking
- MessageBus: per-agent queues with file-backed persistence
- SharedContextLayer: thread-safe shared state with pub/sub
- TaskRouter: routes tasks based on agent capability
- AgentDelegate: handles cross-agent task delegation (Trinity -> Neo -> Trinity)

Extensible: adding a fourth agent requires one dict entry and one capability list.
"""

import asyncio
import json
import logging
import threading
import time
import uuid
from dataclasses import dataclass, field
from enum import Enum
from pathlib import Path
from typing import Any, Callable, Awaitable

from runtime.react_loop import ReActLoop, ReActContext, ReActResult, Message

logger = logging.getLogger(__name__)


# ─── Data Types ───────────────────────────────────────────────────────────────

class AgentRole(Enum):
    CONVERSATION = "conversation"
    EXECUTION = "execution"
    GUIDANCE = "guidance"


class TaskStatus(Enum):
    PENDING = "pending"
    IN_PROGRESS = "in_progress"
    COMPLETED = "completed"
    FAILED = "failed"


@dataclass
class AgentCapabilities:
    name: str
    role: AgentRole
    enabled: bool
    capabilities: list[str] = field(default_factory=list)
    system_prompt: str = ""


@dataclass
class Task:
    id: str
    type: str
    payload: dict
    source_agent: str
    target_agent: str
    status: TaskStatus = TaskStatus.PENDING
    result: Any = None
    error: str = ""
    created_at: float = field(default_factory=time.time)
    completed_at: float | None = None


# ─── MessageBus ───────────────────────────────────────────────────────────────

class MessageBus:
    """Per-agent message queues with file-backed persistence."""

    def __init__(self, workspace: str = "."):
        self.base_path = Path(workspace) / "hivemind" / "queues"
        self.base_path.mkdir(parents=True, exist_ok=True)
        self._queues: dict[str, asyncio.Queue] = {}

    def _queue_path(self, agent: str) -> Path:
        return self.base_path / f"{agent}.jsonl"

    def _get_queue(self, agent: str) -> asyncio.Queue:
        if agent not in self._queues:
            self._queues[agent] = asyncio.Queue()
            self._load_persisted(agent)
        return self._queues[agent]

    def _load_persisted(self, agent: str):
        """Load persisted messages from disk into the in-memory queue."""
        path = self._queue_path(agent)
        if not path.exists():
            return
        try:
            for line in path.read_text().strip().splitlines():
                if line.strip():
                    msg = json.loads(line)
                    self._queues[agent].put_nowait(msg)
            # Clear the file after loading
            path.write_text("")
        except Exception as e:
            logger.error(f"Failed to load persisted messages for {agent}: {e}")

    async def send(self, agent: str, message: dict):
        """Send a message to an agent's queue. Persists to disk."""
        queue = self._get_queue(agent)
        await queue.put(message)
        # Persist
        try:
            with open(self._queue_path(agent), "a") as f:
                f.write(json.dumps(message, default=str) + "\n")
        except Exception as e:
            logger.error(f"Failed to persist message for {agent}: {e}")

    async def receive(self, agent: str, timeout: float = 5.0) -> dict | None:
        """Receive a message from an agent's queue. Returns None on timeout."""
        queue = self._get_queue(agent)
        try:
            return await asyncio.wait_for(queue.get(), timeout=timeout)
        except asyncio.TimeoutError:
            return None

    def pending_count(self, agent: str) -> int:
        return self._get_queue(agent).qsize()


# ─── SharedContextLayer ──────────────────────────────────────────────────────

class SharedContextLayer:
    """Thread-safe shared state with pub/sub for cross-agent communication."""

    def __init__(self):
        self._state: dict[str, Any] = {}
        self._lock = threading.Lock()
        self._subscribers: dict[str, list[Callable]] = {}

    def set(self, key: str, value: Any):
        with self._lock:
            self._state[key] = value
        self._notify(key, value)

    def get(self, key: str, default: Any = None) -> Any:
        with self._lock:
            return self._state.get(key, default)

    def get_all(self) -> dict:
        with self._lock:
            return dict(self._state)

    def subscribe(self, key: str, callback: Callable):
        """Subscribe to changes on a specific key."""
        if key not in self._subscribers:
            self._subscribers[key] = []
        self._subscribers[key].append(callback)

    def _notify(self, key: str, value: Any):
        for callback in self._subscribers.get(key, []):
            try:
                callback(key, value)
            except Exception as e:
                logger.error(f"Subscriber error for {key}: {e}")


# ─── TaskRouter ──────────────────────────────────────────────────────────────

# Default capability mapping — extensible via config
AGENT_CAPABILITIES = {
    "neo": {
        "role": AgentRole.EXECUTION,
        "capabilities": [
            "bash", "execute", "blockchain", "deploy", "contract",
            "transfer", "tool", "web_search", "web_request", "file_ops",
            "attest", "nft", "defi", "stake", "payment", "compile",
        ],
    },
    "trinity": {
        "role": AgentRole.CONVERSATION,
        "capabilities": [
            "chat", "conversation", "explain", "help", "question",
            "translate", "summarize", "greet",
        ],
    },
    "morpheus": {
        "role": AgentRole.GUIDANCE,
        "capabilities": [
            "security", "risk", "warning", "irreversible", "guidance",
            "first_use", "pivotal", "explain_deep",
        ],
    },
}


class TaskRouter:
    """Routes tasks to the correct agent based on capability matching."""

    def __init__(self, agents: dict[str, AgentCapabilities] | None = None):
        self._agents = agents or {}

    def route(self, task_type: str) -> str:
        """Determine which agent should handle a task type."""
        task_lower = task_type.lower()

        for agent_name, caps in AGENT_CAPABILITIES.items():
            if any(cap in task_lower for cap in caps["capabilities"]):
                return agent_name

        # Default to Neo for unknown task types (execution)
        return "neo"


# ─── AgentOrchestrator ───────────────────────────────────────────────────────

class HivemindOrchestrator:
    """
    Central coordinator that manages task assignment, tracks active tasks,
    handles task completion and failure, and coordinates agent handoffs.
    """

    def __init__(self, config: dict, react_loop: ReActLoop):
        self.config = config
        self.react_loop = react_loop
        workspace = config.get("workspace", ".")

        self.message_bus = MessageBus(workspace)
        self.shared_context = SharedContextLayer()
        self.task_router = TaskRouter()
        self.agents: dict[str, AgentCapabilities] = {}
        self.active_tasks: dict[str, Task] = {}
        self._user_firsts: dict[str, set[str]] = {}

        self._init_agents()

        # Subscribe to task completions so Trinity knows when Neo finishes
        self.shared_context.subscribe("task_completed", self._on_task_completed)

    def _init_agents(self):
        agents_config = self.config.get("agents", {})
        for name, caps_def in AGENT_CAPABILITIES.items():
            cfg = agents_config.get(name, {})
            self.agents[name] = AgentCapabilities(
                name=name,
                role=caps_def["role"],
                enabled=cfg.get("enabled", True),
                capabilities=caps_def["capabilities"],
                system_prompt=self.react_loop.get_agent_prompt(name),
            )

    def _on_task_completed(self, key: str, value: Any):
        """Callback when a task is completed — updates shared context."""
        logger.info(f"Task completed notification: {value}")

    # ─── Public API ────────────────────────────────────────────────────────

    async def handle_message(
        self,
        user_message: str,
        session_id: str,
        conversation: list[Message],
    ) -> dict:
        """
        Process a user message through the hivemind.
        Checks Morpheus triggers, routes to Trinity, delegates to Neo if needed.
        """
        # Check Morpheus triggers first
        morpheus_response = await self._check_morpheus_triggers(
            user_message, session_id, conversation,
        )
        if morpheus_response:
            return {
                "response": morpheus_response,
                "agent": "morpheus",
                "morpheus_triggered": True,
                "tool_calls": [],
            }

        # Route to Trinity for conversation
        context = ReActContext(
            agent_name="trinity",
            conversation=conversation + [Message(role="user", content=user_message)],
            system_prompt=self.agents["trinity"].system_prompt,
        )

        result = await self.react_loop.run(context)

        return {
            "response": result.response,
            "agent": "trinity",
            "morpheus_triggered": False,
            "tool_calls": result.tool_calls,
        }

    async def delegate_task(
        self,
        task_type: str,
        payload: dict,
        source_agent: str = "trinity",
    ) -> Task:
        """
        Create a delegated task. Routes to the correct agent, executes it,
        and returns the result through the source agent.
        """
        target_agent = self.task_router.route(task_type)
        task = Task(
            id=uuid.uuid4().hex[:12],
            type=task_type,
            payload=payload,
            source_agent=source_agent,
            target_agent=target_agent,
        )

        self.active_tasks[task.id] = task
        logger.info(f"Task {task.id}: {source_agent} -> {target_agent} ({task_type})")

        # Send to target agent's queue
        await self.message_bus.send(target_agent, {
            "task_id": task.id,
            "type": task_type,
            "payload": payload,
        })

        # Execute the task via the target agent's ReAct loop
        task.status = TaskStatus.IN_PROGRESS
        try:
            result = await self.execute_operation(task_type, payload, target_agent)
            task.status = TaskStatus.COMPLETED
            task.result = result
            task.completed_at = time.time()

            # Update shared context so source agent knows
            self.shared_context.set("task_completed", {
                "task_id": task.id,
                "type": task_type,
                "result": str(result)[:500],
                "target_agent": target_agent,
            })

        except Exception as e:
            task.status = TaskStatus.FAILED
            task.error = str(e)
            logger.error(f"Task {task.id} failed: {e}")

        return task

    async def execute_operation(
        self,
        operation: str,
        params: dict,
        agent: str = "neo",
    ) -> ReActResult:
        """Execute an operation via a specific agent's ReAct loop."""
        prompt = f"Execute this operation: {operation}\nParameters: {json.dumps(params, default=str)}"
        context = ReActContext(
            agent_name=agent,
            conversation=[Message(role="user", content=prompt)],
            system_prompt=self.agents.get(agent, AgentCapabilities("neo", AgentRole.EXECUTION, True)).system_prompt,
            tools_enabled=True,
        )
        return await self.react_loop.run(context)

    # ─── Morpheus Triggers ─────────────────────────────────────────────────

    async def _check_morpheus_triggers(
        self,
        user_message: str,
        session_id: str,
        conversation: list[Message],
    ) -> str | None:
        morpheus = self.agents.get("morpheus")
        if not morpheus or not morpheus.enabled:
            return None

        if self._is_on_demand_morpheus(user_message):
            return await self._invoke_morpheus(user_message, conversation)

        first_category = self._detect_first_use(user_message, session_id)
        if first_category:
            prompt = (
                f"The user is about to use {first_category} for the first time. "
                f"Explain what they are about to do before they do it. "
                f"Their message: {user_message}"
            )
            return await self._invoke_morpheus(prompt, conversation)

        if self._detect_irreversible(user_message):
            prompt = (
                f"The user is about to take an irreversible action. "
                f"State clearly what is about to happen and that it is permanent. "
                f"Their message: {user_message}"
            )
            return await self._invoke_morpheus(prompt, conversation)

        return None

    def _is_on_demand_morpheus(self, message: str) -> bool:
        triggers = ["explain", "what does this mean", "help me understand", "morpheus"]
        return any(t in message.lower() for t in triggers)

    def _detect_first_use(self, message: str, session_id: str) -> str | None:
        categories = {
            "smart contracts": ["smart contract", "deploy contract", "solidity"],
            "DeFi": ["defi", "loan", "lending", "borrow", "yield", "liquidity"],
            "NFTs": ["nft", "mint nft", "create nft"],
            "DAOs": ["dao", "governance", "vote", "proposal"],
        }
        if session_id not in self._user_firsts:
            self._user_firsts[session_id] = set()
        msg_lower = message.lower()
        for category, keywords in categories.items():
            if category in self._user_firsts[session_id]:
                continue
            if any(kw in msg_lower for kw in keywords):
                self._user_firsts[session_id].add(category)
                return category
        return None

    def _detect_irreversible(self, message: str) -> bool:
        keywords = ["deploy", "execute contract", "transfer", "send eth", "send token", "burn", "swap", "stake"]
        return any(kw in message.lower() for kw in keywords)

    async def _invoke_morpheus(self, prompt: str, conversation: list[Message]) -> str:
        context = ReActContext(
            agent_name="morpheus",
            conversation=conversation + [Message(role="user", content=prompt)],
            system_prompt=self.agents["morpheus"].system_prompt,
            tools_enabled=False,
        )
        return await self.react_loop.run_without_tools(context)
