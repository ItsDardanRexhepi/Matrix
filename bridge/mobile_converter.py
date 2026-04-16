"""
Mobile Converter — converts deployed 0pnMatrx components for the MTRX iOS app.

Takes bridge-validated, Dardan-approved components and packages them for the
MTRX iOS app. Generates:

    - Trinity conversational routes (4 per component: chat, query, explain, summarize)
    - Morpheus event triggers (5 types per component)
    - API endpoints (4 per component: status, execute, config, trigger)
    - Push notification hooks (4 per component)
    - On-device Ollama integration config
    - ERC-4337 smart account wallet bindings
    - XMTP messaging channel config

Guard: Verifies configured components are deployed before packaging
"""

from __future__ import annotations

import json
import logging
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# iOS Package Configuration
# ---------------------------------------------------------------------------

@dataclass
class IOSPackageConfig:
    """Configuration constants for MTRX iOS packaging."""
    bundle_id: str = "com.mtrx.app"
    min_ios_version: str = "16.0"
    ollama_model: str = "llama3"
    ollama_quantization: str = "q4_0"
    ollama_memory_limit_mb: int = 512
    erc4337_entrypoint: str = "0x5FF137D4b0FDCD49DcA30c7CF57E578a026d2789"
    xmtp_env: str = "production"
    base_api_path: str = "/api/v1"


@dataclass
class IOSComponent:
    """A single component packaged for iOS."""
    component_name: str
    api_endpoints: list[dict[str, str]]
    trinity_routes: list[dict[str, str]]
    morpheus_triggers: list[dict[str, str]]
    push_notification_hooks: list[dict[str, str]]
    files: list[str] = field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        return {
            "component_name": self.component_name,
            "api_endpoints": self.api_endpoints,
            "trinity_routes": self.trinity_routes,
            "morpheus_triggers": self.morpheus_triggers,
            "push_notification_hooks": self.push_notification_hooks,
            "files": self.files,
        }


@dataclass
class IOSPackageResult:
    """Result of the full iOS packaging run."""
    components_packaged: int = 0
    total_api_endpoints: int = 0
    trinity_integration: bool = False
    morpheus_integration: bool = False
    ollama_integration: bool = False
    erc4337_integration: bool = False
    xmtp_integration: bool = False
    push_integration: bool = False
    package_manifest: dict[str, Any] = field(default_factory=dict)
    errors: list[str] = field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        return {
            "components_packaged": self.components_packaged,
            "total_api_endpoints": self.total_api_endpoints,
            "integrations": {
                "trinity": self.trinity_integration,
                "morpheus": self.morpheus_integration,
                "ollama": self.ollama_integration,
                "erc4337": self.erc4337_integration,
                "xmtp": self.xmtp_integration,
                "push": self.push_integration,
            },
            "errors": self.errors,
        }


# All configured component names that must be present before packaging
REQUIRED_COMPONENTS = [
    "contract_conversion", "defi", "nft_services", "rwa_tokenization",
    "did_identity", "dao_management", "stablecoin", "attestation",
    "agent_identity", "x402_payments", "oracle_gateway", "supply_chain",
    "insurance", "gaming", "ip_royalties", "staking",
    "cross_border", "securities_exchange", "governance", "dashboard",
    "dex", "fundraising", "loyalty", "marketplace",
    "cashback", "brand_rewards", "subscriptions", "social",
    "privacy", "dispute_resolution",
]


class MobileConverter:
    """Converts deployed runtime components into MTRX iOS app packages.

    Usage::

        converter = MobileConverter(
            runtime_dir="runtime/blockchain/services",
            output_dir="data/bridge/ios_packages",
        )
        result = await converter.package_all()
        if result.components_packaged == 30:
            # Full package ready
            ...
    """

    def __init__(
        self,
        runtime_dir: str = "runtime/blockchain/services",
        output_dir: str = "data/bridge/ios_packages",
        config: IOSPackageConfig | None = None,
    ):
        self.runtime_dir = Path(runtime_dir)
        self.output_dir = Path(output_dir)
        self.config = config or IOSPackageConfig()

    async def package_all(self) -> IOSPackageResult:
        """Package all configured components for iOS.

        Guard: Will only proceed if all required components are deployed.

        Returns:
            IOSPackageResult with packaging status and manifest.
        """
        result = IOSPackageResult()

        # Check all configured components are deployed
        missing = self._check_required_components()
        if missing:
            result.errors.append(
                f"Cannot package for iOS: {len(missing)} components missing: "
                f"{', '.join(missing[:5])}{'...' if len(missing) > 5 else ''}"
            )
            logger.warning("iOS packaging blocked: %d components missing", len(missing))
            return result

        self.output_dir.mkdir(parents=True, exist_ok=True)
        components: list[IOSComponent] = []

        for component_name in REQUIRED_COMPONENTS:
            try:
                ios_component = await self._package_component(component_name)
                components.append(ios_component)
            except Exception as exc:
                result.errors.append(f"Failed to package {component_name}: {exc}")
                logger.exception("Failed to package %s", component_name)

        result.components_packaged = len(components)
        result.total_api_endpoints = sum(
            len(c.api_endpoints) for c in components
        )

        # Generate integration configs
        result.trinity_integration = await self._generate_trinity_config(components)
        result.morpheus_integration = await self._generate_morpheus_config(components)
        result.ollama_integration = await self._generate_ollama_config()
        result.erc4337_integration = await self._generate_erc4337_config()
        result.xmtp_integration = await self._generate_xmtp_config()
        result.push_integration = await self._generate_push_config(components)

        # Write package manifest
        result.package_manifest = self._build_manifest(components, result)
        manifest_path = self.output_dir / "ios_package_manifest.json"
        manifest_path.write_text(json.dumps(result.package_manifest, indent=2))

        logger.info(
            "iOS packaging complete: %d components, %d endpoints",
            result.components_packaged, result.total_api_endpoints,
        )

        return result

    async def package_single(self, component_name: str) -> IOSComponent:
        """Package a single component (does not enforce the 30-component guard)."""
        return await self._package_component(component_name)

    def _check_required_components(self) -> list[str]:
        """Return list of missing required components."""
        missing = []
        for name in REQUIRED_COMPONENTS:
            component_dir = self.runtime_dir / name
            if not component_dir.exists():
                missing.append(name)
        return missing

    async def _package_component(self, component_name: str) -> IOSComponent:
        """Generate iOS integration layer for a single component."""
        base = self.config.base_api_path

        # 4 API endpoints per component
        api_endpoints = [
            {"method": "GET", "path": f"{base}/{component_name}/status", "description": f"Get {component_name} status"},
            {"method": "POST", "path": f"{base}/{component_name}/execute", "description": f"Execute {component_name} action"},
            {"method": "GET", "path": f"{base}/{component_name}/config", "description": f"Get {component_name} config"},
            {"method": "POST", "path": f"{base}/{component_name}/trigger", "description": f"Trigger {component_name} event"},
        ]

        # 4 Trinity conversational routes per component
        trinity_routes = [
            {"route": f"{base}/trinity/{component_name}/chat", "type": "conversational"},
            {"route": f"{base}/trinity/{component_name}/query", "type": "query"},
            {"route": f"{base}/trinity/{component_name}/explain", "type": "explanation"},
            {"route": f"{base}/trinity/{component_name}/summarize", "type": "summary"},
        ]

        # 5 Morpheus event triggers per component
        morpheus_triggers = [
            {"event": "state_change", "component": component_name},
            {"event": "alert", "component": component_name},
            {"event": "threshold_breach", "component": component_name},
            {"event": "scheduled_check", "component": component_name},
            {"event": "user_action", "component": component_name},
        ]

        # 4 push notification hooks per component
        push_hooks = [
            {"hook": "alert", "component": component_name, "priority": "high"},
            {"hook": "status_update", "component": component_name, "priority": "default"},
            {"hook": "morpheus_trigger", "component": component_name, "priority": "high"},
            {"hook": "trinity_response", "component": component_name, "priority": "default"},
        ]

        # Write the iOS component config
        comp_dir = self.output_dir / component_name
        comp_dir.mkdir(parents=True, exist_ok=True)

        config_data = IOSComponent(
            component_name=component_name,
            api_endpoints=api_endpoints,
            trinity_routes=trinity_routes,
            morpheus_triggers=morpheus_triggers,
            push_notification_hooks=push_hooks,
        )

        config_path = comp_dir / "ios_config.json"
        config_path.write_text(json.dumps(config_data.to_dict(), indent=2))

        return config_data

    async def _generate_trinity_config(self, components: list[IOSComponent]) -> bool:
        """Generate Trinity conversational interface config for all components."""
        routes = []
        for comp in components:
            routes.extend(comp.trinity_routes)

        config = {
            "version": "1.0.0",
            "total_routes": len(routes),
            "routes": routes,
        }

        path = self.output_dir / "trinity_config.json"
        path.write_text(json.dumps(config, indent=2))
        return True

    async def _generate_morpheus_config(self, components: list[IOSComponent]) -> bool:
        """Generate Morpheus event trigger config for all components."""
        triggers = []
        for comp in components:
            triggers.extend(comp.morpheus_triggers)

        config = {
            "version": "1.0.0",
            "total_triggers": len(triggers),
            "event_types": ["state_change", "alert", "threshold_breach", "scheduled_check", "user_action"],
            "triggers": triggers,
        }

        path = self.output_dir / "morpheus_config.json"
        path.write_text(json.dumps(config, indent=2))
        return True

    async def _generate_ollama_config(self) -> bool:
        """Generate on-device Ollama processing config."""
        config = {
            "model": self.config.ollama_model,
            "quantization": self.config.ollama_quantization,
            "memory_limit_mb": self.config.ollama_memory_limit_mb,
            "fallback_to_cloud": True,
            "system_prompt_prefix": "You are Trinity, the AI assistant for 0pnMatrx.",
        }

        path = self.output_dir / "ollama_config.json"
        path.write_text(json.dumps(config, indent=2))
        return True

    async def _generate_erc4337_config(self) -> bool:
        """Generate ERC-4337 smart account wallet config."""
        config = {
            "entrypoint": self.config.erc4337_entrypoint,
            "features": {
                "social_recovery": True,
                "biometric_auth": True,
                "paymaster_support": True,
                "batch_transactions": True,
            },
        }

        path = self.output_dir / "erc4337_config.json"
        path.write_text(json.dumps(config, indent=2))
        return True

    async def _generate_xmtp_config(self) -> bool:
        """Generate XMTP messaging config."""
        config = {
            "environment": self.config.xmtp_env,
            "features": {
                "mls_encryption": True,
                "direct_messages": True,
                "group_chats": True,
                "component_notifications": True,
            },
        }

        path = self.output_dir / "xmtp_config.json"
        path.write_text(json.dumps(config, indent=2))
        return True

    async def _generate_push_config(self, components: list[IOSComponent]) -> bool:
        """Generate push notification config for all components."""
        hooks = []
        for comp in components:
            hooks.extend(comp.push_notification_hooks)

        config = {
            "version": "1.0.0",
            "provider": "apns",
            "total_hooks": len(hooks),
            "hook_types": ["alert", "status_update", "morpheus_trigger", "trinity_response"],
            "hooks": hooks,
        }

        path = self.output_dir / "push_config.json"
        path.write_text(json.dumps(config, indent=2))
        return True

    def _build_manifest(
        self,
        components: list[IOSComponent],
        result: IOSPackageResult,
    ) -> dict[str, Any]:
        """Build the final iOS package manifest."""
        return {
            "bundle_id": self.config.bundle_id,
            "min_ios_version": self.config.min_ios_version,
            "packaged_at": time.time(),
            "components": [c.component_name for c in components],
            "total_components": len(components),
            "total_api_endpoints": result.total_api_endpoints,
            "integrations": {
                "trinity": result.trinity_integration,
                "morpheus": result.morpheus_integration,
                "ollama": {
                    "enabled": result.ollama_integration,
                    "model": self.config.ollama_model,
                    "quantization": self.config.ollama_quantization,
                },
                "erc4337": {
                    "enabled": result.erc4337_integration,
                    "entrypoint": self.config.erc4337_entrypoint,
                },
                "xmtp": {
                    "enabled": result.xmtp_integration,
                    "environment": self.config.xmtp_env,
                },
                "push": result.push_integration,
            },
        }
