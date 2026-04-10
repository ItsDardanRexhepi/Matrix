"""Plugin registry — tracks loaded plugins and their capabilities.

Provides a unified view of all active plugins, their tools, commands,
and hooks for the gateway and ReAct loop to query.
"""

from __future__ import annotations

import logging
from typing import Any

from runtime.plugins.base import OpenMatrixPlugin
from runtime.plugins.loader import PluginLoader

logger = logging.getLogger(__name__)


class PluginRegistry:
    """Central registry of loaded plugins and their capabilities.

    The gateway and ReAct loop query this registry to discover
    plugin-provided tools, commands, and message hooks.
    """

    def __init__(self, loader: PluginLoader | None = None):
        """Initialise with an optional loader.

        Parameters
        ----------
        loader : PluginLoader, optional
            The plugin loader. If not provided, creates a default one.
        """
        self.loader = loader or PluginLoader()
        self._plugins: dict[str, OpenMatrixPlugin] = {}

    async def initialize(self, config: dict | None = None) -> None:
        """Load all plugins and build the registry."""
        plugins = await self.loader.load_all(config)
        for plugin in plugins:
            self._plugins[plugin.name] = plugin
        logger.info(
            "Plugin registry initialised: %d plugins loaded",
            len(self._plugins),
        )

    @property
    def plugins(self) -> dict[str, OpenMatrixPlugin]:
        """All loaded plugins keyed by name."""
        return dict(self._plugins)

    def get_all_tools(self) -> list[dict]:
        """Collect tool definitions from all plugins."""
        tools = []
        for plugin in self._plugins.values():
            try:
                tools.extend(plugin.get_tools())
            except Exception as exc:
                logger.warning("Plugin %s get_tools error: %s", plugin.name, exc)
        return tools

    def get_all_commands(self) -> list[dict]:
        """Collect slash commands from all plugins."""
        commands = []
        for plugin in self._plugins.values():
            try:
                commands.extend(plugin.get_commands())
            except Exception as exc:
                logger.warning("Plugin %s get_commands error: %s", plugin.name, exc)
        return commands

    async def run_message_hooks(self, agent: str, message: str) -> str:
        """Run all plugin message hooks, returning the final message."""
        result = message
        for plugin in self._plugins.values():
            try:
                modified = await plugin.on_message(agent, result)
                if modified is not None:
                    result = modified
            except Exception as exc:
                logger.warning("Plugin %s message hook error: %s", plugin.name, exc)
        return result

    async def shutdown(self) -> None:
        """Unload all plugins."""
        await self.loader.unload_all()
        self._plugins.clear()

    def to_dict(self) -> list[dict]:
        """Serialise plugin info for API responses."""
        return [
            {
                "name": p.name,
                "version": p.version,
                "description": p.description,
                "author": p.author,
                "min_tier": p.min_tier,
                "tools": len(p.get_tools()),
                "commands": len(p.get_commands()),
            }
            for p in self._plugins.values()
        ]
