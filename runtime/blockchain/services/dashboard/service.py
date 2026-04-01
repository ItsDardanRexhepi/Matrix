"""
DashboardService — unified dashboard aggregating all 30 components of the
0pnMatrx platform.

Activity-based visibility: only shows components the user has interacted with.
All descriptions in plain English (no jargon).
"""

from __future__ import annotations

import logging
import time
from typing import Any

from runtime.blockchain.services.dashboard.aggregator import DataAggregator
from runtime.blockchain.services.dashboard.formatters import PlainEnglishFormatter

logger = logging.getLogger(__name__)

# All 30 platform components
_ALL_COMPONENTS = [
    "did_identity", "agent_identity", "attestation", "contract_conversion",
    "cross_border", "dao_management", "defi", "stablecoin",
    "nft_services", "oracle_gateway", "ip_royalties", "gaming",
    "insurance", "supply_chain", "rwa_tokenization", "staking",
    "x402_payments", "securities_exchange", "governance", "dashboard",
    "dex", "fundraising",
    # Components 23-30 (placeholders for full 30)
    "analytics", "messaging", "storage", "bridge",
    "identity_recovery", "compliance_engine", "notification",
    "dispute_resolution",
]


class DashboardService:
    """Unified dashboard service for the 0pnMatrx platform.

    Config keys (under ``config["dashboard"]``):
        max_activity (int): Maximum activity items (default 50).
        cache_ttl (int): Cache lifetime in seconds (default 30).
    """

    def __init__(self, config: dict, services: dict[str, Any] | None = None) -> None:
        self._config = config
        d_cfg: dict[str, Any] = config.get("dashboard", {})

        self._max_activity: int = int(d_cfg.get("max_activity", 50))

        self._aggregator = DataAggregator(config, services)
        self._formatter = PlainEnglishFormatter()

        # Track which components each user has interacted with
        # address -> set of component names
        self._user_components: dict[str, set[str]] = {}

        logger.info("DashboardService initialised.")

    @property
    def aggregator(self) -> DataAggregator:
        return self._aggregator

    @property
    def formatter(self) -> PlainEnglishFormatter:
        return self._formatter

    def record_interaction(self, address: str, component: str) -> None:
        """Record that a user has interacted with a component.

        Used for activity-based visibility in the dashboard.
        """
        self._user_components.setdefault(address, set()).add(component)

    async def get_overview(self, user_address: str) -> dict:
        """Get a complete overview of everything the user has.

        Only shows components the user has interacted with (activity-based
        visibility). All descriptions are in plain English.

        Returns:
            Dict with portfolio, active components, and formatted summaries.
        """
        if not user_address:
            raise ValueError("User address is required")

        portfolio = await self._aggregator.aggregate_portfolio(user_address)

        # Determine which components the user has interacted with
        active_components = self._user_components.get(user_address, set())

        # Also infer from portfolio data
        if portfolio.get("staking_positions"):
            active_components.add("staking")
        if portfolio.get("defi_positions"):
            active_components.add("defi")
        if portfolio.get("nfts"):
            active_components.add("nft_services")
        if portfolio.get("securities"):
            active_components.add("securities_exchange")
        if portfolio.get("rwa_holdings"):
            active_components.add("rwa_tokenization")
        if portfolio.get("liquidity_positions"):
            active_components.add("dex")

        # Format portfolio summary in plain English
        summary_text = self._formatter.format_portfolio_summary(portfolio)

        # Format individual sections
        staking_summaries = []
        for pos in portfolio.get("staking_positions", []):
            staking_summaries.append(self._formatter.format_staking_info(pos))

        defi_summaries = []
        for pos in portfolio.get("defi_positions", []):
            defi_summaries.append(self._formatter.format_defi_position(pos))

        return {
            "user_address": user_address,
            "summary": summary_text,
            "portfolio": portfolio,
            "active_components": sorted(active_components),
            "staking_summaries": staking_summaries,
            "defi_summaries": defi_summaries,
            "generated_at": int(time.time()),
        }

    async def get_activity(
        self, user_address: str, limit: int = 50
    ) -> dict:
        """Get recent activity across all components.

        All transactions are formatted in plain English.

        Returns:
            Dict with raw activities and formatted descriptions.
        """
        if not user_address:
            raise ValueError("User address is required")

        limit = min(limit, self._max_activity)
        activities = await self._aggregator.aggregate_activity(user_address, limit)

        # Format each activity in plain English
        formatted = []
        for activity in activities:
            formatted.append({
                "raw": activity,
                "description": self._formatter.format_transaction(activity),
                "component": activity.get("component", "unknown"),
            })

        return {
            "user_address": user_address,
            "total_activities": len(activities),
            "activities": formatted,
            "generated_at": int(time.time()),
        }

    async def get_component_status(self, component: str) -> dict:
        """Get the health status of a specific component.

        Returns:
            Dict with component name, status, and plain English description.
        """
        if component not in _ALL_COMPONENTS:
            raise ValueError(
                f"Unknown component '{component}'. "
                f"Valid components: {_ALL_COMPONENTS}"
            )

        service = self._aggregator._services.get(component)

        status: dict[str, Any]
        if service is None:
            status = {
                "component": component,
                "status": "not_registered",
                "healthy": False,
                "message": "Service is not currently available.",
            }
        else:
            # Check if service has a health check method
            if hasattr(service, "health_check"):
                try:
                    health = await service.health_check()
                    status = {
                        "component": component,
                        "status": "active",
                        "healthy": True,
                        "details": health,
                    }
                except Exception as exc:
                    status = {
                        "component": component,
                        "status": "degraded",
                        "healthy": False,
                        "error": str(exc),
                    }
            else:
                status = {
                    "component": component,
                    "status": "active",
                    "healthy": True,
                }

        status["description"] = self._formatter.format_component_status(
            component, status
        )
        status["checked_at"] = int(time.time())
        return status

    async def get_platform_stats(self) -> dict:
        """Get aggregate platform statistics.

        Returns:
            Dict with overall platform health, component counts, and metrics.
        """
        total = len(_ALL_COMPONENTS)
        registered = len(self._aggregator._services)
        healthy = 0

        component_statuses = {}
        for comp_name in _ALL_COMPONENTS:
            svc = self._aggregator._services.get(comp_name)
            if svc is not None:
                component_statuses[comp_name] = "active"
                healthy += 1
            else:
                component_statuses[comp_name] = "not_registered"

        total_users = len(self._user_components)

        return {
            "platform": "0pnMatrx",
            "total_components": total,
            "registered_components": registered,
            "healthy_components": healthy,
            "total_active_users": total_users,
            "component_statuses": component_statuses,
            "generated_at": int(time.time()),
        }
