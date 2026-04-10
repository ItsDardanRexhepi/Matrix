"""
Plugin Manifest Schema — defines the structure every plugin must declare.

A plugin manifest is a JSON file (plugin.json) that lives at the root of
every plugin directory. It tells the platform:
    - What the plugin does
    - What tier it requires (free / pro / enterprise)
    - What permissions it needs
    - What components or actions it registers
    - Compatibility with platform versions

Example manifest::

    {
        "name": "advanced-analytics",
        "version": "1.0.0",
        "display_name": "Advanced Analytics",
        "description": "Portfolio analytics with ML-powered forecasting",
        "author": "developer@example.com",
        "requires_tier": "pro",
        "min_platform_version": "1.0.0",
        "permissions": ["read_portfolio", "read_transactions"],
        "components": [
            {
                "name": "analytics_engine",
                "actions": ["run_analysis", "get_forecast", "export_report"],
                "feature_flags": {
                    "requires_pro_tier": true,
                    "requires_enterprise_tier": false,
                    "beta": false
                }
            }
        ],
        "trinity_skills": ["analyze portfolio", "forecast prices"],
        "morpheus_hooks": ["threshold_breach", "scheduled_check"],
        "ios_compatible": true,
        "entry_point": "main.py"
    }
"""

from __future__ import annotations

import json
import logging
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

logger = logging.getLogger(__name__)


# Valid subscription tiers
VALID_TIERS = {"free", "pro", "enterprise"}

# Valid permissions a plugin can request
VALID_PERMISSIONS = {
    "read_portfolio",
    "read_transactions",
    "read_wallet_address",
    "propose_transaction",
    "read_contract_state",
    "execute_action",
    "read_trinity_context",
    "send_notifications",
    "network_access",
    "read_health_data",
    "read_market_data",
    "write_storage",
}

# Valid Morpheus hook types
VALID_MORPHEUS_HOOKS = {
    "state_change",
    "alert",
    "threshold_breach",
    "scheduled_check",
    "user_action",
}


@dataclass
class ComponentDeclaration:
    """A component or action set declared by a plugin."""
    name: str
    actions: list[str] = field(default_factory=list)
    feature_flags: dict[str, bool] = field(default_factory=dict)

    @property
    def requires_pro(self) -> bool:
        return self.feature_flags.get("requires_pro_tier", False)

    @property
    def requires_enterprise(self) -> bool:
        return self.feature_flags.get("requires_enterprise_tier", False)

    @property
    def is_beta(self) -> bool:
        return self.feature_flags.get("beta", False)

    def to_dict(self) -> dict[str, Any]:
        return {
            "name": self.name,
            "actions": self.actions,
            "feature_flags": self.feature_flags,
        }

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> ComponentDeclaration:
        return cls(
            name=data["name"],
            actions=data.get("actions", []),
            feature_flags=data.get("feature_flags", {}),
        )


@dataclass
class PluginManifest:
    """Parsed and validated plugin manifest."""
    name: str
    version: str
    display_name: str
    description: str
    author: str
    requires_tier: str = "free"
    min_platform_version: str = "1.0.0"
    permissions: list[str] = field(default_factory=list)
    components: list[ComponentDeclaration] = field(default_factory=list)
    trinity_skills: list[str] = field(default_factory=list)
    morpheus_hooks: list[str] = field(default_factory=list)
    ios_compatible: bool = True
    entry_point: str = "main.py"

    def to_dict(self) -> dict[str, Any]:
        return {
            "name": self.name,
            "version": self.version,
            "display_name": self.display_name,
            "description": self.description,
            "author": self.author,
            "requires_tier": self.requires_tier,
            "min_platform_version": self.min_platform_version,
            "permissions": self.permissions,
            "components": [c.to_dict() for c in self.components],
            "trinity_skills": self.trinity_skills,
            "morpheus_hooks": self.morpheus_hooks,
            "ios_compatible": self.ios_compatible,
            "entry_point": self.entry_point,
        }

    @classmethod
    def from_file(cls, manifest_path: str | Path) -> PluginManifest:
        """Load and validate a plugin manifest from a JSON file.

        Raises:
            FileNotFoundError: If the manifest file doesn't exist.
            ValueError: If the manifest is invalid.
        """
        path = Path(manifest_path)
        if not path.exists():
            raise FileNotFoundError(f"Manifest not found: {path}")

        data = json.loads(path.read_text())
        return cls.from_dict(data)

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> PluginManifest:
        """Parse and validate a manifest from a dictionary.

        Raises:
            ValueError: If required fields are missing or values are invalid.
        """
        # Validate required fields
        required = ["name", "version", "display_name", "description", "author"]
        for field_name in required:
            if field_name not in data:
                raise ValueError(f"Manifest missing required field: '{field_name}'")

        # Validate tier
        tier = data.get("requires_tier", "free")
        if tier not in VALID_TIERS:
            raise ValueError(f"Invalid tier '{tier}'. Must be one of: {VALID_TIERS}")

        # Validate permissions
        permissions = data.get("permissions", [])
        invalid_perms = set(permissions) - VALID_PERMISSIONS
        if invalid_perms:
            raise ValueError(f"Invalid permissions: {invalid_perms}")

        # Validate morpheus hooks
        hooks = data.get("morpheus_hooks", [])
        invalid_hooks = set(hooks) - VALID_MORPHEUS_HOOKS
        if invalid_hooks:
            raise ValueError(f"Invalid Morpheus hooks: {invalid_hooks}")

        # Parse components
        components = [
            ComponentDeclaration.from_dict(c)
            for c in data.get("components", [])
        ]

        return cls(
            name=data["name"],
            version=data["version"],
            display_name=data["display_name"],
            description=data["description"],
            author=data["author"],
            requires_tier=tier,
            min_platform_version=data.get("min_platform_version", "1.0.0"),
            permissions=permissions,
            components=components,
            trinity_skills=data.get("trinity_skills", []),
            morpheus_hooks=hooks,
            ios_compatible=data.get("ios_compatible", True),
            entry_point=data.get("entry_point", "main.py"),
        )

    def is_available_for_tier(self, user_tier: str) -> bool:
        """Check if this plugin is available for a given user tier.

        Tier hierarchy: free < pro < enterprise
        Enterprise users can access everything.
        Pro users can access free + pro.
        Free users can only access free.
        """
        tier_level = {"free": 0, "pro": 1, "enterprise": 2}
        user_level = tier_level.get(user_tier, 0)
        required_level = tier_level.get(self.requires_tier, 0)
        return user_level >= required_level

    def get_available_actions(self, user_tier: str) -> list[str]:
        """Return all actions available for a given tier."""
        actions = []
        tier_level = {"free": 0, "pro": 1, "enterprise": 2}
        user_level = tier_level.get(user_tier, 0)

        for comp in self.components:
            if comp.requires_enterprise and user_level < 2:
                continue
            if comp.requires_pro and user_level < 1:
                continue
            actions.extend(comp.actions)

        return actions
