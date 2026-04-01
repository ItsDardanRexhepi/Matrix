"""
Tool Dispatcher — routes tool calls from the ReAct loop to the correct handler.

All tools register themselves here. The dispatcher validates arguments,
enforces timeouts, and returns results back to the reasoning loop.
"""

import asyncio
import logging
from typing import Any, Callable, Awaitable

from runtime.tools.bash import BashTool
from runtime.tools.file_ops import FileOpsTool
from runtime.tools.web_search import WebSearchTool
from runtime.tools.web import WebTool

logger = logging.getLogger(__name__)

TOOL_TIMEOUT = 30


class ToolDispatcher:
    """
    Central registry and dispatcher for all agent tools.
    Tools are loaded at startup from config and registered here.
    """

    def __init__(self, config: dict):
        self.config = config
        self._tools: dict[str, Any] = {}
        self._schemas: list[dict] = []
        self._register_builtin_tools()

    def _register_builtin_tools(self):
        tools = [
            BashTool(self.config),
            FileOpsTool(self.config),
            WebSearchTool(self.config),
            WebTool(self.config),
        ]
        for tool in tools:
            self.register(tool.name, tool.execute, tool.schema)

    def register(self, name: str, handler: Callable[..., Awaitable[str]], schema: dict):
        self._tools[name] = handler
        self._schemas.append(schema)
        logger.debug(f"Registered tool: {name}")

    def get_tool_schemas(self) -> list[dict]:
        return self._schemas.copy()

    async def dispatch(self, tool_name: str, arguments: dict) -> str:
        handler = self._tools.get(tool_name)
        if not handler:
            return f"Error: unknown tool '{tool_name}'"

        try:
            result = await asyncio.wait_for(
                handler(**arguments),
                timeout=TOOL_TIMEOUT,
            )
            return str(result)
        except asyncio.TimeoutError:
            logger.warning(f"Tool '{tool_name}' timed out after {TOOL_TIMEOUT}s")
            return f"Error: tool '{tool_name}' timed out"
        except Exception as e:
            logger.error(f"Tool '{tool_name}' failed: {e}")
            return f"Error executing '{tool_name}': {e}"
