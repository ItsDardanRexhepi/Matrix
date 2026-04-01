"""Grace Period Manager - Component 27.

Manages the 48-hour grace period for failed subscription payments.
Auto-cancels subscriptions after grace period expires.
"""

from __future__ import annotations

import logging
import time
import uuid
from typing import Any

logger = logging.getLogger(__name__)


class GracePeriodManager:
    """Manages grace periods for failed subscription payments.

    When a renewal payment fails, the subscription enters a 48-hour
    grace window. If payment is retried successfully within that window,
    the subscription continues. Otherwise, it is auto-cancelled.
    """

    def __init__(self, config: dict[str, Any] | None = None) -> None:
        self.config = config or {}
        self._grace_records: dict[str, dict] = {}
        self._grace_hours = self.config.get("grace_period_hours", 48)
        self._grace_seconds = self._grace_hours * 3600
        logger.info("GracePeriodManager initialised (grace=%dh)", self._grace_hours)

    async def enter_grace(self, subscription_id: str) -> dict:
        """Enter grace period for a subscription.

        Args:
            subscription_id: The subscription entering grace.

        Returns:
            Grace period record with expiration time.
        """
        if not subscription_id:
            raise ValueError("subscription_id is required")

        now = time.time()
        grace_id = f"grace_{uuid.uuid4().hex[:12]}"

        record = {
            "grace_id": grace_id,
            "subscription_id": subscription_id,
            "entered_at": now,
            "expires_at": now + self._grace_seconds,
            "status": "active",
            "retry_count": 0,
            "resolved": False,
            "resolved_at": None,
            "resolution": None,
        }

        self._grace_records[subscription_id] = record
        logger.info(
            "Subscription %s entered grace period (expires in %dh)",
            subscription_id, self._grace_hours,
        )
        return record

    async def check_grace(self, subscription_id: str) -> dict:
        """Check the status of a grace period.

        Args:
            subscription_id: The subscription to check.

        Returns:
            Dict with grace status, time remaining, and whether expired.
        """
        record = self._grace_records.get(subscription_id)
        if not record:
            return {
                "subscription_id": subscription_id,
                "in_grace": False,
                "expired": False,
                "message": "No grace period found",
            }

        if record["resolved"]:
            return {
                "subscription_id": subscription_id,
                "in_grace": False,
                "expired": False,
                "resolved": True,
                "resolution": record["resolution"],
                "resolved_at": record["resolved_at"],
            }

        now = time.time()
        expired = now >= record["expires_at"]
        remaining_seconds = max(0, record["expires_at"] - now)
        remaining_hours = round(remaining_seconds / 3600, 2)

        if expired:
            record["status"] = "expired"
            logger.info("Grace period for subscription %s has expired", subscription_id)

        return {
            "subscription_id": subscription_id,
            "grace_id": record["grace_id"],
            "in_grace": not expired,
            "expired": expired,
            "entered_at": record["entered_at"],
            "expires_at": record["expires_at"],
            "remaining_hours": remaining_hours,
            "retry_count": record["retry_count"],
        }

    async def resolve_grace(self, subscription_id: str, paid: bool) -> dict:
        """Resolve a grace period.

        Args:
            subscription_id: The subscription to resolve.
            paid: True if payment was successful, False to cancel.

        Returns:
            The resolved grace record.
        """
        record = self._grace_records.get(subscription_id)
        if not record:
            raise ValueError(f"No grace period found for subscription '{subscription_id}'")
        if record["resolved"]:
            raise ValueError("Grace period already resolved")

        now = time.time()
        expired = now >= record["expires_at"]

        if expired and paid:
            logger.warning(
                "Payment received for subscription %s after grace expiry; accepting anyway",
                subscription_id,
            )

        record["resolved"] = True
        record["resolved_at"] = now
        record["retry_count"] += 1

        if paid:
            record["status"] = "resolved_paid"
            record["resolution"] = "payment_successful"
            logger.info("Grace period for %s resolved: payment successful", subscription_id)
        else:
            record["status"] = "resolved_cancelled"
            record["resolution"] = "cancelled"
            logger.info("Grace period for %s resolved: cancelled", subscription_id)

        return record
