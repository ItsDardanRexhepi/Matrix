"""
Plugin Loader — discovers and loads third-party plugins from the plugins directory.

Scans for plugin directories containing a valid plugin.json manifest,
validates them, and registers their components with the ComponentRegistry.
"""

from __future__ import annotations

import importlib.util
import logging
import sys
from pathlib import Path
from typing import Any

from plugins.manifest_schema import PluginManifest
from plugins.component_registry import ComponentRegistry

logger = logging.getLogger(__name__)

# Default plugins directory
DEFAULT_PLUGINS_DIR = Path(__file__).parent


def discover_plugins(
    plugins_dir: str | Path | None = None,
) -> list[PluginManifest]:
    """Discover all valid plugins in the plugins directory.

    Scans for subdirectories containing a plugin.json manifest file,
    validates each manifest, and returns the list of valid manifests.

    Args:
        plugins_dir: Path to scan for plugins. Defaults to the plugins/ directory.

    Returns:
        List of validated PluginManifest objects.
    """
    search_dir = Path(plugins_dir) if plugins_dir else DEFAULT_PLUGINS_DIR
    if not search_dir.exists():
        logger.warning("Plugins directory does not exist: %s", search_dir)
        return []

    manifests: list[PluginManifest] = []

    for entry in sorted(search_dir.iterdir()):
        if not entry.is_dir():
            continue

        manifest_path = entry / "plugin.json"
        if not manifest_path.exists():
            continue

        try:
            manifest = PluginManifest.from_file(manifest_path)
            manifests.append(manifest)
            logger.info("Discovered plugin: %s v%s", manifest.name, manifest.version)
        except (ValueError, FileNotFoundError) as exc:
            logger.warning("Invalid plugin in %s: %s", entry.name, exc)

    logger.info("Discovered %d plugins in %s", len(manifests), search_dir)
    return manifests


def load_plugin(
    manifest: PluginManifest,
    registry: ComponentRegistry,
    plugins_dir: str | Path | None = None,
) -> bool:
    """Load a plugin into the runtime and register its components.

    1. Validates the manifest
    2. Imports the plugin's entry point module
    3. Registers components with the ComponentRegistry
    4. Calls the plugin's setup() function if present

    Args:
        manifest: The validated plugin manifest.
        registry: The ComponentRegistry to register components into.
        plugins_dir: Base plugins directory. Defaults to plugins/.

    Returns:
        True if the plugin loaded successfully.
    """
    search_dir = Path(plugins_dir) if plugins_dir else DEFAULT_PLUGINS_DIR
    plugin_dir = search_dir / manifest.name

    if not plugin_dir.exists():
        logger.error("Plugin directory not found: %s", plugin_dir)
        return False

    # Register components
    registered = registry.register_plugin(manifest)

    # Try to import and initialize the plugin module
    entry_path = plugin_dir / manifest.entry_point
    if entry_path.exists():
        try:
            spec = importlib.util.spec_from_file_location(
                f"plugins.{manifest.name}", entry_path
            )
            if spec and spec.loader:
                module = importlib.util.module_from_spec(spec)
                sys.modules[f"plugins.{manifest.name}"] = module
                spec.loader.exec_module(module)

                # Call setup() if the plugin defines it
                if hasattr(module, "setup"):
                    module.setup(registry)
                    logger.info("Called setup() for plugin: %s", manifest.name)

        except Exception as exc:
            logger.exception("Failed to import plugin %s: %s", manifest.name, exc)
            return False

    logger.info(
        "Loaded plugin '%s': %d components registered",
        manifest.name, len(registered),
    )
    return True


def load_all_plugins(
    registry: ComponentRegistry,
    plugins_dir: str | Path | None = None,
    user_tier: str = "free",
) -> dict[str, Any]:
    """Discover and load all plugins available for a given tier.

    Args:
        registry: The ComponentRegistry instance.
        plugins_dir: Path to plugins directory.
        user_tier: The user's subscription tier (free/pro/enterprise).

    Returns:
        Summary dict with loaded/skipped/failed counts.
    """
    manifests = discover_plugins(plugins_dir)

    loaded = 0
    skipped = 0
    failed = 0

    for manifest in manifests:
        if not manifest.is_available_for_tier(user_tier):
            logger.info(
                "Skipping plugin '%s' (requires %s, user has %s)",
                manifest.name, manifest.requires_tier, user_tier,
            )
            skipped += 1
            continue

        success = load_plugin(manifest, registry, plugins_dir)
        if success:
            loaded += 1
        else:
            failed += 1

    return {
        "discovered": len(manifests),
        "loaded": loaded,
        "skipped_tier": skipped,
        "failed": failed,
    }
