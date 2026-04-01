"""
ReAct Reasoning Loop — The core reasoning engine for all 0pnMatrx agents.

Implements the Reason-Act cycle:
1. Observe — receive user input and context
2. Think — reason about what to do next
3. Act — call a tool or produce a response
4. Observe — process tool results
5. Repeat until the task is complete

Model-agnostic: works with any provider that implements ModelInterface.
"""

import json
import logging
import time
from dataclasses import dataclass, field
from typing import Any

from runtime.models.router import ModelRouter
from runtime.tools.dispatcher import ToolDispatcher
from runtime.memory.manager import MemoryManager

logger = logging.getLogger(__name__)

MAX_ITERATIONS = 20
TOOL_CALL_TIMEOUT = 30


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


class ReActLoop:
    """
    The core reasoning loop that drives every agent on 0pnMatrx.

    Each iteration:
    - Sends the conversation history to the model
    - If the model returns a tool call, executes it and feeds the result back
    - If the model returns a text response with no tool calls, returns it as the final answer
    """

    def __init__(self, config: dict):
        self.config = config
        self.router = ModelRouter(config.get("model", {}))
        self.dispatcher = ToolDispatcher(config)
        self.memory = MemoryManager(config)

    async def run(self, context: ReActContext) -> str:
        """
        Execute the ReAct loop until the agent produces a final response
        or hits the iteration limit.
        """
        messages = self._build_messages(context)
        tools_schema = self.dispatcher.get_tool_schemas() if context.tools_enabled else []

        for iteration in range(MAX_ITERATIONS):
            logger.debug(f"[{context.agent_name}] iteration {iteration + 1}")

            start = time.monotonic()
            response = await self.router.complete(
                messages=messages,
                tools=tools_schema if tools_schema else None,
                agent_name=context.agent_name,
            )
            elapsed = time.monotonic() - start
            logger.debug(f"[{context.agent_name}] model responded in {elapsed:.2f}s")

            if not response.tool_calls:
                final_text = response.content or ""
                await self.memory.save_turn(
                    agent=context.agent_name,
                    user_message=context.conversation[-1].content if context.conversation else "",
                    assistant_message=final_text,
                )
                return final_text

            messages.append(Message(
                role="assistant",
                content=response.content or "",
                tool_calls=response.tool_calls,
            ))

            for tool_call in response.tool_calls:
                tool_name = tool_call["function"]["name"]
                try:
                    arguments = json.loads(tool_call["function"]["arguments"])
                except (json.JSONDecodeError, KeyError):
                    arguments = {}

                logger.info(f"[{context.agent_name}] calling tool: {tool_name}")
                result = await self.dispatcher.dispatch(tool_name, arguments)

                messages.append(Message(
                    role="tool",
                    content=str(result),
                    tool_call_id=tool_call["id"],
                    name=tool_name,
                ))

        logger.warning(f"[{context.agent_name}] hit max iterations ({MAX_ITERATIONS})")
        return "I've reached the limit of my reasoning steps for this request. Let me know how you'd like to proceed."

    def _build_messages(self, context: ReActContext) -> list[Message]:
        messages = []

        if context.system_prompt:
            messages.append(Message(role="system", content=context.system_prompt))

        memory_context = self.memory.get_context(context.agent_name)
        if memory_context:
            messages.append(Message(
                role="system",
                content=f"Relevant memory:\n{memory_context}",
            ))

        messages.extend(context.conversation)
        return messages

    async def run_without_tools(self, context: ReActContext) -> str:
        """
        Single-pass generation with no tool access.
        Used for the first pass in the two-pass ReAct pattern:
        first pass produces a natural response, second pass enables tools.
        """
        messages = self._build_messages(context)

        response = await self.router.complete(
            messages=messages,
            tools=None,
            agent_name=context.agent_name,
        )

        return response.content or ""
