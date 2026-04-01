"""Community Cashback Service - Component 25.

Tracks user spending, enforces an annual $10K threshold, and provides
1% cashback on all qualifying spending paid from platform revenue.
"""

from __future__ import annotations

import logging
import time
import uuid
from typing import Any

from .threshold_tracker import ThresholdTracker

logger = logging.getLogger(__name__)

DEFAULT_CONFIG: dict[str, Any] = {
    "annual_threshold": 10_000.0,
    "cashback_rate": 0.01,
    "min_claim_amount": 1.0,
    "platform_revenue_wallet": "0xPLATFORM_REVENUE",
    "spending_categories": [
        "retail", "food", "travel", "entertainment", "services",
        "utilities", "health", "education", "other",
    ],
}


class CashbackService:
    """Community cashback with annual spending threshold.

    Users must spend $10K in a calendar year to qualify. Once qualified,
    1% cashback accrues on all spending (including the initial $10K).
    Cashback resets annually.
    """

    def __init__(self, config: dict[str, Any] | None = None) -> None:
        self.config = {**DEFAULT_CONFIG, **(config or {})}
        self._user_data: dict[str, dict] = {}
        self.threshold_tracker = ThresholdTracker(self.config)
        logger.info(
            "CashbackService initialised (threshold=$%.0f, rate=%.1f%%)",
            self.config["annual_threshold"],
            self.config["cashback_rate"] * 100,
        )

    def _current_year(self) -> int:
        return time.gmtime().tm_year

    def _get_user_data(self, user: str) -> dict:
        year = self._current_year()
        key = f"{user}:{year}"
        if key not in self._user_data:
            self._user_data[key] = {
                "user": user,
                "year": year,
                "total_spending": 0.0,
                "cashback_accrued": 0.0,
                "cashback_claimed": 0.0,
                "qualified": False,
                "qualified_at": None,
                "transactions": [],
                "category_spending": {},
            }
        return self._user_data[key]

    async def track_spending(self, user: str, amount: float, category: str) -> dict:
        """Record a spending transaction and accrue cashback if qualified.

        Args:
            user: User's wallet address.
            amount: Spending amount in platform currency.
            category: Spending category.

        Returns:
            Dict with spending total, cashback accrued, and qualification status.
        """
        if not user:
            raise ValueError("user is required")
        if amount <= 0:
            raise ValueError("amount must be positive")
        valid_categories = self.config["spending_categories"]
        if category not in valid_categories:
            raise ValueError(f"Invalid category '{category}'. Must be one of: {valid_categories}")

        data = self._get_user_data(user)
        data["total_spending"] += amount
        data["category_spending"][category] = data["category_spending"].get(category, 0.0) + amount

        # Update threshold tracker
        await self.threshold_tracker.record_spending(user, amount)

        # Check qualification
        threshold = self.config["annual_threshold"]
        was_qualified = data["qualified"]
        if data["total_spending"] >= threshold and not data["qualified"]:
            data["qualified"] = True
            data["qualified_at"] = time.time()
            # Retroactively accrue cashback on all prior spending
            retroactive = data["total_spending"] * self.config["cashback_rate"]
            data["cashback_accrued"] = round(retroactive, 8)
            logger.info("User %s qualified for cashback (total=$%.2f)", user, data["total_spending"])
        elif data["qualified"]:
            # Already qualified: accrue on this transaction
            cashback = amount * self.config["cashback_rate"]
            data["cashback_accrued"] = round(data["cashback_accrued"] + cashback, 8)

        tx_id = str(uuid.uuid4())
        data["transactions"].append({
            "tx_id": tx_id,
            "amount": amount,
            "category": category,
            "cashback_earned": round(amount * self.config["cashback_rate"], 8) if data["qualified"] else 0.0,
            "timestamp": time.time(),
        })

        return {
            "user": user,
            "transaction_id": tx_id,
            "amount": amount,
            "category": category,
            "total_spending": round(data["total_spending"], 2),
            "qualified": data["qualified"],
            "newly_qualified": data["qualified"] and not was_qualified,
            "cashback_accrued": data["cashback_accrued"],
            "threshold_remaining": max(0, threshold - data["total_spending"]),
        }

    async def get_cashback_balance(self, user: str) -> dict:
        """Get the user's current cashback balance.

        Returns:
            Dict with accrued, claimed, and available cashback amounts.
        """
        if not user:
            raise ValueError("user is required")

        data = self._get_user_data(user)
        available = round(data["cashback_accrued"] - data["cashback_claimed"], 8)

        return {
            "user": user,
            "year": data["year"],
            "qualified": data["qualified"],
            "cashback_accrued": data["cashback_accrued"],
            "cashback_claimed": data["cashback_claimed"],
            "cashback_available": max(0.0, available),
            "total_spending": round(data["total_spending"], 2),
        }

    async def claim_cashback(self, user: str) -> dict:
        """Claim all available cashback.

        Cashback is paid from platform revenue.

        Returns:
            Dict with claimed amount and payment details.
        """
        if not user:
            raise ValueError("user is required")

        data = self._get_user_data(user)
        if not data["qualified"]:
            raise ValueError(
                f"User has not met the annual spending threshold "
                f"(${self.config['annual_threshold']:.0f}). "
                f"Current spending: ${data['total_spending']:.2f}"
            )

        available = round(data["cashback_accrued"] - data["cashback_claimed"], 8)
        if available < self.config["min_claim_amount"]:
            raise ValueError(
                f"Minimum claim amount is ${self.config['min_claim_amount']:.2f}. "
                f"Available: ${available:.2f}"
            )

        claim_id = f"claim_{uuid.uuid4().hex[:12]}"
        data["cashback_claimed"] = round(data["cashback_claimed"] + available, 8)

        logger.info("User %s claimed $%.2f cashback", user, available)

        return {
            "user": user,
            "claim_id": claim_id,
            "amount_claimed": available,
            "paid_from": self.config["platform_revenue_wallet"],
            "cashback_remaining": 0.0,
            "claimed_at": time.time(),
        }

    async def get_spending_summary(self, user: str) -> dict:
        """Get a detailed spending summary for the current year.

        Returns:
            Dict with category breakdown, totals, and cashback info.
        """
        if not user:
            raise ValueError("user is required")

        data = self._get_user_data(user)
        threshold_info = await self.threshold_tracker.check_threshold(user)

        return {
            "user": user,
            "year": data["year"],
            "total_spending": round(data["total_spending"], 2),
            "category_breakdown": dict(data["category_spending"]),
            "transaction_count": len(data["transactions"]),
            "qualified": data["qualified"],
            "qualified_at": data["qualified_at"],
            "threshold": threshold_info,
            "cashback_accrued": data["cashback_accrued"],
            "cashback_claimed": data["cashback_claimed"],
            "cashback_available": round(
                max(0.0, data["cashback_accrued"] - data["cashback_claimed"]), 8
            ),
        }
