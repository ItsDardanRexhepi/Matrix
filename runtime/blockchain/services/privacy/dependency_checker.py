"""Dependency Checker - Component 29.

Lists what WOULD block a deletion, by category, with human-readable
explanations. It does not check across the platform's components, which this
used to say: no component is queried. The only dependencies it knows are the
ones declared to it through ``set_user_dependencies``, which nothing in the
platform calls, so for a real user every category is empty. An empty result is
therefore not a clearance, and the result says so (``components_queried`` is
empty and ``can_proceed`` is False).
"""

from __future__ import annotations

import logging
import time
from typing import Any

logger = logging.getLogger(__name__)

# Dependency categories with human-readable descriptions
DEPENDENCY_CATEGORIES = {
    "open_disputes": {
        "component": "Component 30 - Dispute Resolution",
        "description": "Active or pending dispute cases where this user is a party",
        "blocking_reason": (
            "Evidence and records in active disputes must be preserved until "
            "the dispute is fully resolved to ensure fair adjudication."
        ),
    },
    "active_loans": {
        "component": "Component 14 - Lending/DeFi",
        "description": "Outstanding loan positions (as borrower or lender)",
        "blocking_reason": (
            "Active loan positions cannot be deleted because financial "
            "obligations must be settled before data removal."
        ),
    },
    "pending_settlements": {
        "component": "Component 24 - Marketplace",
        "description": "Pending marketplace settlements or escrow holds",
        "blocking_reason": (
            "Pending financial settlements must complete before associated "
            "data can be deleted to prevent fraud and ensure payment integrity."
        ),
    },
    "active_subscriptions": {
        "component": "Component 27 - Subscriptions",
        "description": "Active subscription plans (as subscriber or provider)",
        "blocking_reason": (
            "Active subscriptions must be cancelled and any remaining billing "
            "period completed before subscription data can be deleted."
        ),
    },
    "legal_holds": {
        "component": "Platform Legal",
        "description": "Data subject to legal preservation orders",
        "blocking_reason": (
            "Data under legal hold is required to be preserved by law. "
            "Deletion cannot proceed until the legal hold is lifted."
        ),
    },
    "active_escrow": {
        "component": "Component 12 - Escrow",
        "description": "Funds currently held in escrow",
        "blocking_reason": (
            "Escrow positions must be released or returned before "
            "associated data can be deleted."
        ),
    },
}


class DependencyChecker:
    """Reports the dependencies declared to it that would block a deletion.

    It queries no component (see the module docstring): the categories name
    where such data would live — disputes, loans, settlements, subscriptions,
    legal holds, escrow — and each is empty unless ``set_user_dependencies``
    filled it in.
    """

    def __init__(self, config: dict[str, Any] | None = None) -> None:
        self.config = config or {}
        # Simulated dependency state for each user
        self._user_dependencies: dict[str, dict[str, list]] = {}
        logger.info("DependencyChecker initialised")

    def set_user_dependencies(self, user: str, category: str, items: list[dict]) -> None:
        """Declare dependency data for a user.

        This is the checker's only source. No component is queried, in
        production or anywhere else, and nothing in the platform calls this.

        Args:
            user: User's wallet address.
            category: Dependency category (e.g. 'open_disputes').
            items: List of dependency items.
        """
        if category not in DEPENDENCY_CATEGORIES:
            raise ValueError(f"Unknown dependency category '{category}'")
        self._user_dependencies.setdefault(user, {})[category] = items

    async def check_structural_dependencies(self, user: str) -> dict:
        """Report the declared structural dependencies for a user.

        No component is queried, so ``can_proceed`` is always False: an empty
        list here means nothing was declared, not that nothing blocks.

        Args:
            user: User's wallet address.

        Returns:
            Dict with per-category dependency status.
        """
        if not user:
            raise ValueError("user is required")

        results = {}
        user_deps = self._user_dependencies.get(user, {})

        for category, meta in DEPENDENCY_CATEGORIES.items():
            items = user_deps.get(category, [])
            has_dependencies = len(items) > 0

            results[category] = {
                "component": meta["component"],
                "description": meta["description"],
                "has_dependencies": has_dependencies,
                "count": len(items),
                "items": items if has_dependencies else [],
                "blocking": has_dependencies,
                "blocking_reason": meta["blocking_reason"] if has_dependencies else None,
            }

        total_blocking = sum(1 for r in results.values() if r["blocking"])

        return {
            "user": user,
            "total_categories_listed": len(DEPENDENCY_CATEGORIES),
            "total_blocking_categories": total_blocking,
            "components_queried": [],
            "can_proceed": False,
            "can_proceed_reason": (
                "No platform component was queried. The categories list only "
                "what was declared to this checker, so an empty category is "
                "not a finding that nothing blocks deletion."
            ),
            "categories": results,
            "checked_at": time.time(),
        }

    async def get_blocking_dependencies(self, user: str) -> list:
        """Get only the blocking dependencies with human-readable explanations.

        Args:
            user: User's wallet address.

        Returns:
            List of blocking dependency records with explanations.
        """
        if not user:
            raise ValueError("user is required")

        structural = await self.check_structural_dependencies(user)
        blocking = []

        for category, data in structural["categories"].items():
            if not data["blocking"]:
                continue

            blocking.append({
                "category": category,
                "component": data["component"],
                "description": data["description"],
                "reason": data["blocking_reason"],
                "item_count": data["count"],
                "items": data["items"],
                "resolution_steps": self._get_resolution_steps(category),
            })

        return blocking

    def _get_resolution_steps(self, category: str) -> list[str]:
        """Get human-readable steps to resolve a blocking dependency."""
        steps = {
            "open_disputes": [
                "Wait for all active disputes to be resolved.",
                "If you are a claimant, you may withdraw the dispute.",
                "Contact dispute resolution (Component 30) for expedited review.",
            ],
            "active_loans": [
                "Repay all outstanding loan balances.",
                "Wait for any pending loan transactions to settle.",
                "Contact the lending service to confirm loan closure.",
            ],
            "pending_settlements": [
                "Wait for all pending marketplace settlements to complete.",
                "Cancel any active listings that have not been sold.",
                "Contact marketplace support if settlements are delayed.",
            ],
            "active_subscriptions": [
                "Cancel all active subscriptions.",
                "Wait for the current billing period to end.",
                "If you are a provider, ensure all subscribers are notified.",
            ],
            "legal_holds": [
                "Legal holds can only be lifted by authorised legal personnel.",
                "Contact platform legal support for information about the hold.",
                ("Lifting the hold does not start a deletion: data deletion "
                 "is not available on this platform yet."),
            ],
            "active_escrow": [
                "Wait for escrow conditions to be met and funds released.",
                "Both parties can agree to cancel the escrow arrangement.",
                "Contact escrow service (Component 12) for dispute resolution.",
            ],
        }
        return steps.get(category, ["Contact platform support for assistance."])
