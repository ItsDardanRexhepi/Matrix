"""Runtime plugin system for 0pnMatrx.

Provides the base class and loader for third-party plugins that
extend the platform's capabilities. Plugins can add new tools,
commands, and integrations.
"""

from runtime.plugins.base import OpenMatrixPlugin
from runtime.plugins.loader import PluginLoader
from runtime.plugins.registry import PluginRegistry

__all__ = ["OpenMatrixPlugin", "PluginLoader", "PluginRegistry"]
