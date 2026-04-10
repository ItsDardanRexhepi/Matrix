"""Plugin loader for discovering and loading plugins from disk.

Scans configured plugin directories for Python modules that contain
``OpenMatrixPlugin`` subclasses. Handles loading, validation, and
lifecycle management.
"""

from __future__ import annotations

import importlib
import importlib.util
import logging
import os
import sys
from pathlib import Path
from typing import Any

from runtime.plugins.base import OpenMatrixPlugin

logger = logging.getLogger(__name__)


class PluginLoader:
    """Discovers and loads plugins from the filesystem.

    Plugins are Python packages or modules that contain a class
    extending ``OpenMatrixPlugin``. The loader scans configured
    directories and imports valid plugins.
    """

    def __init__(self, plugin_dirs: list[str] | None = None):
        """Initialise the loader.

        Parameters
        ----------
        plugin_dirs : list[str], optional
            Directories to scan for plugins. Defaults to
            ``['plugins/installed']``.
        """
        self.plugin_dirs = plugin_dirs or ["plugins/installed"]
        self.loaded: dict[str, OpenMatrixPlugin] = {}

    async def discover(self) -> list[str]:
        """Discover plugin modules in configured directories.

        Returns
        -------
        list[str]
            List of discovered plugin module paths.
        """
        discovered = []
        for plugin_dir in self.plugin_dirs:
            dir_path = Path(plugin_dir)
            if not dir_path.exists():
                continue

            for item in dir_path.iterdir():
                if item.is_dir() and (item / "__init__.py").exists():
                    discovered.append(str(item))
                elif item.is_file() and item.suffix == ".py" and item.stem != "__init__":
                    discovered.append(str(item))

        logger.info("Discovered %d plugin candidates", len(discovered))
        return discovered

    async def load(self, module_path: str, config: dict | None = None) -> OpenMatrixPlugin | None:
        """Load a single plugin from a module path.

        Parameters
        ----------
        module_path : str
            Path to the plugin module or package.
        config : dict, optional
            Platform configuration to pass to the plugin.

        Returns
        -------
        OpenMatrixPlugin | None
            The loaded plugin instance, or None on failure.
        """
        try:
            path = Path(module_path)
            if path.is_dir():
                module_name = path.name
                init_path = path / "__init__.py"
            else:
                module_name = path.stem
                init_path = path

            spec = importlib.util.spec_from_file_location(
                f"plugins.{module_name}", str(init_path)
            )
            if not spec or not spec.loader:
                logger.warning("Cannot create spec for plugin: %s", module_path)
                return None

            module = importlib.util.module_from_spec(spec)
            sys.modules[f"plugins.{module_name}"] = module
            spec.loader.exec_module(module)

            # Find OpenMatrixPlugin subclasses
            plugin_class = None
            for attr_name in dir(module):
                attr = getattr(module, attr_name)
                if (
                    isinstance(attr, type)
                    and issubclass(attr, OpenMatrixPlugin)
                    and attr is not OpenMatrixPlugin
                ):
                    plugin_class = attr
                    break

            if not plugin_class:
                logger.debug("No OpenMatrixPlugin subclass found in %s", module_path)
                return None

            plugin = plugin_class()
            await plugin.on_load(config or {})
            self.loaded[plugin.name] = plugin
            logger.info("Loaded plugin: %s v%s", plugin.name, plugin.version)
            return plugin

        except Exception as exc:
            logger.error("Failed to load plugin %s: %s", module_path, exc)
            return None

    async def load_all(self, config: dict | None = None) -> list[OpenMatrixPlugin]:
        """Discover and load all plugins.

        Parameters
        ----------
        config : dict, optional
            Platform configuration.

        Returns
        -------
        list[OpenMatrixPlugin]
            List of successfully loaded plugins.
        """
        modules = await self.discover()
        loaded = []
        for module_path in modules:
            plugin = await self.load(module_path, config)
            if plugin:
                loaded.append(plugin)
        return loaded

    async def unload(self, plugin_name: str) -> bool:
        """Unload a plugin by name."""
        plugin = self.loaded.get(plugin_name)
        if not plugin:
            return False
        try:
            await plugin.on_unload()
        except Exception as exc:
            logger.warning("Plugin %s unload error: %s", plugin_name, exc)
        del self.loaded[plugin_name]
        logger.info("Unloaded plugin: %s", plugin_name)
        return True

    async def unload_all(self) -> None:
        """Unload all plugins."""
        for name in list(self.loaded.keys()):
            await self.unload(name)
