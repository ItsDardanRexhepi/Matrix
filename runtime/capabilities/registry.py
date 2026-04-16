"""
Capability Registry — programmatic interface on top of the catalog.

Wraps ServiceDispatcher so callers can:
    * enumerate capabilities (by category, protocol, tier)
    * fetch metadata for a single capability
    * invoke a capability generically via its id

Trinity's ReAct tool (`platform_action`) still works unchanged — this
class is a higher-level facade used by the gateway's /api/v1/capabilities
endpoints and by tooling that needs descriptor metadata.
"""

from __future__ import annotations

import logging
from typing import Any

from runtime.capabilities import catalog

logger = logging.getLogger(__name__)


class CapabilityRegistry:
    """Facade over the capability catalog + service dispatcher."""

    def __init__(self, config: dict, dispatcher: Any | None = None) -> None:
        self._config = config
        self._dispatcher = dispatcher  # ServiceDispatcher instance (optional)

    # ── Read-only views ───────────────────────────────────────────────────

    def list_capabilities(
        self,
        *,
        category: str | None = None,
        available_only: bool = False,
        min_tier: str | None = None,
    ) -> list[dict]:
        results = catalog.CAPABILITIES
        if category:
            results = [c for c in results if c["category"] == category]
        if available_only:
            results = [c for c in results if c["available"]]
        if min_tier:
            tier_order = ["free", "pro", "enterprise"]
            if min_tier in tier_order:
                max_idx = tier_order.index(min_tier)
                results = [c for c in results if tier_order.index(c["min_tier"]) <= max_idx]
        return list(results)

    def list_by_category(self) -> list[dict]:
        """Return categories with their capabilities embedded."""
        out = []
        for cat in catalog.list_categories():
            out.append({
                **cat,
                "capabilities": catalog.get_by_category(cat["id"]),
            })
        return out

    def list_categories(self) -> list[dict]:
        return catalog.list_categories()

    def describe(self, capability_id: str) -> dict | None:
        return catalog.get_by_id(capability_id)

    # ── Invocation ────────────────────────────────────────────────────────

    async def invoke(self, capability_id: str, params: dict | None = None) -> dict:
        """Execute a capability via its descriptor.

        Translates the capability id to its ACTION_MAP action and delegates
        to the underlying ServiceDispatcher. If no dispatcher was injected,
        lazy-loads one from the standard registry.
        """
        cap = catalog.get_by_id(capability_id)
        if cap is None:
            return {
                "status": "error",
                "error": "unknown_capability",
                "capability_id": capability_id,
            }

        dispatcher = self._dispatcher
        if dispatcher is None:
            # Lazy import to avoid circular deps at module import time.
            from runtime.blockchain.services.service_dispatcher import (
                ServiceDispatcher,
            )
            from runtime.blockchain.services.registry import ServiceRegistry

            service_registry = ServiceRegistry(self._config)
            dispatcher = ServiceDispatcher(self._config, service_registry)
            self._dispatcher = dispatcher

        action = cap["action"]
        payload = {"action": action, "params": params or {}}

        try:
            result = await dispatcher.execute(payload)
        except AttributeError:
            # Fall back to the lower-level dispatch method if execute()
            # isn't present under that name in older builds.
            raw = await dispatcher.dispatch_tool(
                tool_name="platform_action",
                arguments={"action": action, "params": params or {}},
            )
            result = raw
        return {
            "status": "ok",
            "capability_id": capability_id,
            "action": action,
            "result": result,
        }


__all__ = ["CapabilityRegistry"]
