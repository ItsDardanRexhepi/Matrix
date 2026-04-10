"""
Plugin & Extension Registry — allows developers to extend 0pnMatrx.

Third-party developers can create plugins that:
    - Add new actions to existing components
    - Register entirely new components
    - Provide custom Trinity skills
    - Hook into Morpheus event triggers

Every plugin declares a manifest (JSON) that includes:
    - Required tier (free, pro, enterprise)
    - Feature flags and capabilities
    - Permissions needed
    - Compatibility constraints

When the bridge/packager pulls plugins, it checks the manifest against
the user's subscription tier and only activates eligible plugins.
"""

from __future__ import annotations

__all__ = [
    "ComponentRegistry",
    "PluginManifest",
    "load_plugin",
    "discover_plugins",
]

from plugins.component_registry import ComponentRegistry
from plugins.manifest_schema import PluginManifest
from plugins.loader import load_plugin, discover_plugins
