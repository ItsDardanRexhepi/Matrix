"""
ReAct Reasoning Loop — The core reasoning engine for all 0pnMatrx agents.

Implements the Reason-Act cycle:
1. Observe — receive user input and context
2. Think — reason about what to do next
3. Act — call a tool or produce a response
4. Observe — process tool results
5. Repeat until the task is complete

Model-agnostic: works with any provider that implements ModelInterface.
Loads config from openmatrix.config.json. Injects temporal context on
every turn. Loads agent identity from agents/{agent}/identity.md.

Protocol integration: the ProtocolStack is initialised per agent and
wired into the loop at four points — pre-process, pre-action,
post-action, and post-process.
"""

import json
import logging
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from runtime.models.router import ModelRouter
from runtime.tools.dispatcher import ToolDispatcher
from runtime.memory.manager import MemoryManager
from runtime.time.temporal_context import TemporalContext

logger = logging.getLogger(__name__)


@dataclass
class Message:
    role: str
    content: str
    tool_calls: list[dict] | None = None
    tool_call_id: str | None = None
    name: str | None = None


@dataclass
class ReActContext:
    agent_name: str
    conversation: list[Message] = field(default_factory=list)
    system_prompt: str = ""
    tools_enabled: bool = True
    metadata: dict[str, Any] = field(default_factory=dict)


@dataclass
class ReActResult:
    """Result of a ReAct loop execution."""
    response: str
    tool_calls: list[dict] = field(default_factory=list)
    iterations: int = 0
    provider: str = ""


class ReActLoop:
    """
    The core reasoning loop that drives every agent on 0pnMatrx.
    """

    def __init__(self, config: dict):
        self.config = config
        # Inject notification config into model config for Telegram alerts
        model_config = dict(config.get("model", {}))
        model_config["_notifications"] = config.get("notifications", {}).get("telegram", {})
        self.router = ModelRouter(model_config)
        self.dispatcher = ToolDispatcher(config)
        self.memory = MemoryManager(config)
        self.temporal = TemporalContext(config.get("timezone", "America/Los_Angeles"))
        self.max_steps = config.get("max_steps", 10)
        self._agent_prompts: dict[str, str] = {}
        self._load_agent_prompts()

        # ── Protocol stacks (one per agent, lazily created) ──────────
        self._protocol_stacks: dict[str, Any] = {}

    def _get_protocol_stack(self, agent_name: str):
        """Return the ProtocolStack for *agent_name*, creating it on first
        access.  Returns None if the integration module is unavailable."""
        if agent_name in self._protocol_stacks:
            return self._protocol_stacks[agent_name]

        try:
            from runtime.protocols.integration import ProtocolStack
            stack = ProtocolStack(self.config, agent_name)
            self._protocol_stacks[agent_name] = stack
            return stack
        except Exception:
            logger.exception("Failed to create ProtocolStack for agent=%s", agent_name)
            self._protocol_stacks[agent_name] = None
            return None

    def _load_agent_prompts(self):
        agents_dir = Path("agents")
        if not agents_dir.exists():
            return
        for agent_dir in agents_dir.iterdir():
            if agent_dir.is_dir():
                identity_file = agent_dir / "identity.md"
                if identity_file.exists():
                    self._agent_prompts[agent_dir.name] = identity_file.read_text()

    def get_agent_prompt(self, agent_name: str) -> str:
        return self._agent_prompts.get(agent_name, "")

    async def run(self, context: ReActContext) -> ReActResult:
        """
        Execute the ReAct loop until the agent produces a final response
        or hits the step limit. Returns response text and all tool calls made.
        """
        # ── Protocol pre-process ─────────────────────────────────────
        protocol_stack = self._get_protocol_stack(context.agent_name)
        if protocol_stack is not None:
            try:
                context = await protocol_stack.pre_process(context)
            except Exception:
                logger.exception("Protocol pre-process failed for agent=%s", context.agent_name)

        messages = self._build_messages(context)
        tools_schema = self.dispatcher.get_tool_schemas() if context.tools_enabled else []
        all_tool_calls: list[dict] = []
        provider_used = ""

        for iteration in range(self.max_steps):
            logger.debug(f"[{context.agent_name}] iteration {iteration + 1}/{self.max_steps}")

            start = time.monotonic()
            response = await self.router.complete(
                messages=messages,
                tools=tools_schema if tools_schema else None,
                agent_name=context.agent_name,
            )
            elapsed = time.monotonic() - start
            provider_used = response.provider or provider_used
            logger.debug(f"[{context.agent_name}] model responded in {elapsed:.2f}s via {response.provider}")

            if not response.tool_calls:
                final_text = response.content or ""

                # ── Protocol post-process ────────────────────────────
                if protocol_stack is not None:
                    try:
                        final_text = await protocol_stack.post_process(final_text, context)
                    except Exception:
                        logger.exception("Protocol post-process failed for agent=%s", context.agent_name)

                user_msg = context.conversation[-1].content if context.conversation else ""
                await self.memory.save_turn(context.agent_name, user_msg, final_text)
                return ReActResult(
                    response=final_text,
                    tool_calls=all_tool_calls,
                    iterations=iteration + 1,
                    provider=provider_used,
                )

            messages.append(Message(
                role="assistant",
                content=response.content or "",
                tool_calls=response.tool_calls,
            ))

            for tool_call in response.tool_calls:
                tool_name = tool_call["function"]["name"]
                try:
                    arguments = json.loads(tool_call["function"]["arguments"])
                except (json.JSONDecodeError, KeyError, TypeError):
                    arguments = {}

                # ── Protocol pre-action ──────────────────────────────
                morpheus_prefix = ""
                if protocol_stack is not None:
                    try:
                        gate = await protocol_stack.pre_action(
                            tool_name, arguments, context.metadata.get("user_context", {}),
                        )
                        if not gate.get("approved", True):
                            # Tool call denied by protocol gate
                            denial = gate.get("denial_reason", "Action denied by security protocols.")
                            logger.warning(
                                "[%s] tool %s DENIED: %s", context.agent_name, tool_name, denial,
                            )
                            messages.append(Message(
                                role="tool",
                                content=f"[DENIED] {denial}",
                                tool_call_id=tool_call.get("id", ""),
                                name=tool_name,
                            ))
                            all_tool_calls.append({
                                "tool": tool_name,
                                "arguments": arguments,
                                "result_preview": f"[DENIED] {denial}",
                            })
                            continue  # skip execution, let the model see the denial
                        if gate.get("morpheus_message"):
                            morpheus_prefix = gate["morpheus_message"] + "\n\n"
                    except Exception:
                        logger.exception("Protocol pre-action failed for tool=%s", tool_name)

                logger.info(f"[{context.agent_name}] calling tool: {tool_name}({list(arguments.keys())})")
                result = await self.dispatcher.dispatch(tool_name, arguments)

                tool_result_str = str(result)
                display_result = morpheus_prefix + tool_result_str if morpheus_prefix else tool_result_str

                all_tool_calls.append({
                    "tool": tool_name,
                    "arguments": arguments,
                    "result_preview": display_result[:200],
                })

                messages.append(Message(
                    role="tool",
                    content=display_result,
                    tool_call_id=tool_call.get("id", ""),
                    name=tool_name,
                ))

                # ── Protocol post-action ─────────────────────────────
                if protocol_stack is not None:
                    try:
                        await protocol_stack.post_action(
                            tool_name, arguments, tool_result_str,
                            context.metadata.get("user_context", {}),
                        )
                    except Exception:
                        logger.exception("Protocol post-action failed for tool=%s", tool_name)

        logger.warning(f"[{context.agent_name}] hit max steps ({self.max_steps})")
        return ReActResult(
            response="I've reached the limit of my reasoning steps. Let me know how to proceed.",
            tool_calls=all_tool_calls,
            iterations=self.max_steps,
            provider=provider_used,
        )

    async def run_without_tools(self, context: ReActContext) -> str:
        """Single-pass generation with no tool access."""
        messages = self._build_messages(context)
        response = await self.router.complete(messages=messages, tools=None, agent_name=context.agent_name)
        return response.content or ""

    def _build_messages(self, context: ReActContext) -> list[Message]:
        messages = []

        # System prompt with agent identity
        system_parts = []
        if context.system_prompt:
            system_parts.append(context.system_prompt)
        else:
            agent_prompt = self.get_agent_prompt(context.agent_name)
            if agent_prompt:
                system_parts.append(agent_prompt)

        # Temporal context — injected fresh every turn
        system_parts.append(self.temporal.get_context_string())

        # Protocol enrichments (injected by pre-process)
        protocol_enrichments = context.metadata.get("protocol_enrichments", [])
        if protocol_enrichments:
            system_parts.append("\n".join(protocol_enrichments))

        if system_parts:
            messages.append(Message(role="system", content="\n\n".join(system_parts)))

        # Memory context
        memory_context = self.memory.get_context(context.agent_name)
        if memory_context:
            messages.append(Message(role="system", content=f"Relevant memory:\n{memory_context}"))

        messages.extend(context.conversation)
        return messages
