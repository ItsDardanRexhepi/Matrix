"""Base class for 0pnMatrx plugins.

All third-party plugins must extend ``OpenMatrixPlugin`` and implement
the required lifecycle methods. The platform calls these methods at
specific points during startup, request handling, and shutdown.
"""

from __future__ import annotations

import logging
from abc import ABC, abstractmethod
from typing import Any

logger = logging.getLogger(__name__)


class OpenMatrixPlugin(ABC):
    """Base class for all 0pnMatrx plugins.

    Subclasses must implement:
      - ``name`` — unique plugin identifier
      - ``version`` — semantic version string
      - ``on_load()`` — called when the plugin is loaded
      - ``on_unload()`` — called when the plugin is unloaded

    Optional overrides:
      - ``on_message(agent, message)`` — intercept chat messages
      - ``on_tool_call(tool_name, args)`` — intercept tool calls
      - ``get_tools()`` — register custom tools
      - ``get_commands()`` — register slash commands
    """

    @property
    @abstractmethod
    def name(self) -> str:
        """Unique plugin identifier (e.g. 'my-analytics-plugin')."""
        ...

    @property
    @abstractmethod
    def version(self) -> str:
        """Semantic version string (e.g. '1.0.0')."""
        ...

    @property
    def description(self) -> str:
        """Human-readable plugin description."""
        return ""

    @property
    def min_tier(self) -> str:
        """Minimum subscription tier required ('free', 'pro', 'enterprise')."""
        return "free"

    @property
    def author(self) -> str:
        """Plugin author name."""
        return "Unknown"

    async def on_load(self, config: dict) -> None:
        """Called when the plugin is loaded during platform startup.

        Parameters
        ----------
        config : dict
            The platform's configuration dict.
        """
        pass

    async def on_unload(self) -> None:
        """Called when the plugin is unloaded during platform shutdown."""
        pass

    async def on_message(self, agent: str, message: str) -> str | None:
        """Intercept a chat message before it reaches the agent.

        Return the modified message, or None to pass through unchanged.

        Parameters
        ----------
        agent : str
            The target agent name.
        message : str
            The user's message.
        """
        return None

    async def on_tool_call(
        self, tool_name: str, arguments: dict
    ) -> dict | None:
        """Intercept a tool call before execution.

        Return a modified arguments dict, or None to pass through.
        """
        return None

    def get_tools(self) -> list[dict]:
        """Return custom tool definitions to register with the agent.

        Each tool dict should have:
          - name: str
          - description: str
          - parameters: dict (JSON Schema)
          - handler: async callable
        """
        return []

    def get_commands(self) -> list[dict]:
        """Return slash commands this plugin provides.

        Each command dict should have:
          - name: str (e.g. '/hello')
          - description: str
          - handler: async callable
        """
        return []

    def __repr__(self) -> str:
        return f"<Plugin {self.name} v{self.version}>"
