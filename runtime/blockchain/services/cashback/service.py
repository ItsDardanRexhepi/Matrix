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
        """Record a claim for all available cashback. THE MONEY IS NOT SENT.

        This method used to write ``cashback_claimed += available`` and answer
        with ``paid_from: <platform revenue wallet>`` and ``cashback_remaining:
        0.0``. There is no payment rail anywhere in this service: no transfer,
        no transaction, no external ledger call. So the claimable balance — which
        IS the platform's liability to the user — was discharged, the user was
        told where the money came from, and nothing moved. The record was the
        only evidence the debt had ever existed, and the record said it was paid.

        The balance is now left standing until something settles the claim, and
        the response says plainly that nothing was sent.

        EACH CLAIM COVERS ITS OWN TRANCHE. Open claims together cover exactly
        the balance that has been claimed and not paid; nothing is claimed
        twice and nothing is left without a claim:

          * a second press with nothing new accrued returns the SAME open claim
            rather than minting another id for the same money — a settlement
            process reading the records must not pay one balance twice;
          * cashback that accrued AFTER the open claim gets a claim of its own,
            for the difference. The first version of the fix above returned the
            first open claim forever, so a user who had since earned another
            $500 was answered with the old claim's $200, and that $500 never
            got a claim record at all.

        ``cashback_remaining`` on a returned claim is the balance outstanding
        NOW — every open claim together — not a figure frozen when the claim was
        first written.
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

        open_claims = self._open_claims(data)
        already_claimed = round(sum(c["amount_requested"] for c in open_claims), 8)
        unclaimed = round(available - already_claimed, 8)

        # AN OPEN CLAIM IS NOT CLAIMED TWICE. Nothing new has accrued beyond
        # what the open claims already cover, so the latest of them is the
        # answer — with today's outstanding balance, not the one it was
        # written with.
        if open_claims and unclaimed < self.config["min_claim_amount"]:
            return {**open_claims[-1], "cashback_remaining": available}

        claim_id = f"claim_{uuid.uuid4().hex[:12]}"
        claim = {
            # `recorded_unsettled` — the word this codebase already uses for a
            # record that exists while nothing has settled.
            "status": "recorded_unsettled",
            "settled": False,
            "value_moved": False,
            "user": user,
            "claim_id": claim_id,
            # This claim's own tranche: everything available that no open
            # claim already covers.
            "amount_requested": unclaimed,
            "payable_from": self.config["platform_revenue_wallet"],
            "cashback_remaining": available,
            "requested_at": time.time(),
            "disclosure": (
                "This service has no payment rail. The claim is RECORDED and "
                "the money has NOT been sent: no transfer was made from "
                f"{self.config['platform_revenue_wallet']} and no transaction "
                "exists. The balance stays claimable until something settles it."
            ),
        }
        data.setdefault("claims", []).append(claim)

        logger.info(
            "User %s requested $%.2f cashback — recorded, NOT paid (claim=%s, "
            "outstanding=$%.2f)",
            user, unclaimed, claim_id, available,
        )
        return dict(claim)

    @staticmethod
    def _open_claims(data: dict) -> list[dict]:
        """The user's unsettled claims, oldest first."""
        return [c for c in data.get("claims", []) if not c.get("settled")]

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
