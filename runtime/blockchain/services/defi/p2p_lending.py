"""
P2PLending — peer-to-peer lending marketplace where lenders create
offers and borrowers accept them with collateral.

Offers have configurable interest rates, durations, and collateral
requirements.
"""

from __future__ import annotations

import logging
import time
import uuid
from enum import Enum
from typing import Any

logger = logging.getLogger(__name__)


class OfferStatus(str, Enum):
    OPEN = "open"
    FILLED = "filled"
    CANCELLED = "cancelled"
    EXPIRED = "expired"
    REPAID = "repaid"
    DEFAULTED = "defaulted"


class P2PLending:
    """Peer-to-peer lending marketplace.

    Parameters
    ----------
    config : dict
        Platform config.  Reads:
        - ``defi.p2p.min_duration_days`` (default 1)
        - ``defi.p2p.max_duration_days`` (default 365)
        - ``defi.p2p.max_interest_rate`` (default 0.50 = 50%)
        - ``defi.p2p.min_collateral_ratio`` (default 1.5)
        - ``defi.p2p.platform_fee_bps`` (default 50 = 0.5%)
    """

    def __init__(self, config: dict) -> None:
        self._config = config
        p2p_cfg = config.get("defi", {}).get("p2p", {})

        self._min_duration: int = int(p2p_cfg.get("min_duration_days", 1))
        self._max_duration: int = int(p2p_cfg.get("max_duration_days", 365))
        self._max_interest: float = float(p2p_cfg.get("max_interest_rate", 0.50))
        self._min_collateral_ratio: float = float(
            p2p_cfg.get("min_collateral_ratio", 1.5)
        )
        self._platform_fee_bps: int = int(p2p_cfg.get("platform_fee_bps", 50))
        self._platform_wallet: str = config.get("blockchain", {}).get(
            "platform_wallet", ""
        )

        # In-memory storage
        self._offers: dict[str, dict[str, Any]] = {}

    async def create_offer(
        self,
        lender: str,
        token: str,
        amount: float,
        interest_rate: float,
        duration_days: int,
    ) -> dict[str, Any]:
        """Create a lending offer.

        Parameters
        ----------
        lender : str
            Lender wallet address.
        token : str
            Token being offered for lending.
        amount : float
            Amount available to lend.
        interest_rate : float
            Annual interest rate (0.05 = 5%).
        duration_days : int
            Loan duration in days.

        Returns
        -------
        dict
            Offer details including ``offer_id``.
        """
        if amount <= 0:
            raise ValueError("Amount must be positive")
        if interest_rate < 0 or interest_rate > self._max_interest:
            raise ValueError(
                f"Interest rate must be between 0 and {self._max_interest:.0%}"
            )
        if duration_days < self._min_duration or duration_days > self._max_duration:
            raise ValueError(
                f"Duration must be between {self._min_duration} and "
                f"{self._max_duration} days"
            )

        offer_id = f"p2p_{uuid.uuid4().hex[:16]}"
        now = int(time.time())

        offer: dict[str, Any] = {
            "offer_id": offer_id,
            "lender": lender,
            "token": token,
            "amount": amount,
            "remaining_amount": amount,
            "interest_rate": interest_rate,
            "duration_days": duration_days,
            "status": OfferStatus.OPEN,
            "created_at": now,
            "expires_at": now + (30 * 86400),  # offers expire in 30 days
            "borrower": None,
            "collateral": None,
            "accepted_at": None,
            "repayment_due": None,
            "platform_fee_bps": self._platform_fee_bps,
        }

        self._offers[offer_id] = offer

        logger.info(
            "P2P offer created: id=%s lender=%s token=%s amount=%.4f rate=%.2f%% days=%d",
            offer_id, lender, token, amount, interest_rate * 100, duration_days,
        )
        return offer

    async def accept_offer(
        self,
        offer_id: str,
        borrower: str,
        collateral: dict[str, Any],
    ) -> dict[str, Any]:
        """Accept a lending offer as a borrower.

        Parameters
        ----------
        offer_id : str
            The offer to accept.
        borrower : str
            Borrower wallet address.
        collateral : dict
            Collateral info: ``{"token": str, "amount": float, "value_usd": float}``.

        Returns
        -------
        dict
            Accepted offer with borrower details and repayment schedule.
        """
        if offer_id not in self._offers:
            raise KeyError(f"Offer '{offer_id}' not found")

        offer = self._offers[offer_id]

        if offer["status"] != OfferStatus.OPEN:
            raise ValueError(f"Offer '{offer_id}' is {offer['status']}")

        now = int(time.time())
        if now > offer["expires_at"]:
            offer["status"] = OfferStatus.EXPIRED
            raise ValueError(f"Offer '{offer_id}' has expired")

        if offer["lender"] == borrower:
            raise ValueError("Cannot borrow from your own offer")

        # Validate collateral
        collateral_token = collateral.get("token", "")
        collateral_amount = collateral.get("amount", 0)
        collateral_value = collateral.get("value_usd", 0)

        if not collateral_token or collateral_amount <= 0:
            raise ValueError("Valid collateral is required")

        # Check collateral ratio
        # Estimate loan value from amount (simplified)
        loan_value = collateral.get("loan_value_usd", offer["amount"])
        ratio = collateral_value / loan_value if loan_value > 0 else 0
        if ratio < self._min_collateral_ratio:
            raise ValueError(
                f"Collateral ratio {ratio:.2f} is below minimum "
                f"{self._min_collateral_ratio:.2f}"
            )

        # Calculate platform fee
        platform_fee = (offer["amount"] * self._platform_fee_bps) / 10000

        # Calculate total repayment
        interest = offer["amount"] * offer["interest_rate"] * (offer["duration_days"] / 365)
        total_repayment = offer["amount"] + interest + platform_fee
        repayment_due = now + (offer["duration_days"] * 86400)

        offer["status"] = OfferStatus.FILLED
        offer["borrower"] = borrower
        offer["collateral"] = {
            "token": collateral_token,
            "amount": collateral_amount,
            "value_usd": collateral_value,
        }
        offer["accepted_at"] = now
        offer["repayment_due"] = repayment_due
        offer["interest_amount"] = round(interest, 8)
        offer["platform_fee"] = round(platform_fee, 8)
        offer["total_repayment"] = round(total_repayment, 8)

        logger.info(
            "P2P offer accepted: id=%s borrower=%s collateral=%.4f %s "
            "repayment=%.4f due=%d",
            offer_id, borrower, collateral_amount, collateral_token,
            total_repayment, repayment_due,
        )

        return offer

    async def list_offers(
        self, filters: dict[str, Any] | None = None
    ) -> list[dict[str, Any]]:
        """List lending offers with optional filters.

        Supported filters:
            - ``status`` (str): filter by status
            - ``token`` (str): filter by token
            - ``lender`` (str): filter by lender
            - ``min_amount`` (float): minimum amount
            - ``max_rate`` (float): maximum interest rate
            - ``limit`` (int): max results (default 50)
        """
        filters = filters or {}
        now = int(time.time())
        results: list[dict[str, Any]] = []

        status_filter = filters.get("status")
        token_filter = filters.get("token")
        lender_filter = filters.get("lender")
        min_amount = filters.get("min_amount", 0)
        max_rate = filters.get("max_rate", float("inf"))
        limit = filters.get("limit", 50)

        for offer in self._offers.values():
            # Auto-expire
            if (
                offer["status"] == OfferStatus.OPEN
                and now > offer["expires_at"]
            ):
                offer["status"] = OfferStatus.EXPIRED

            if status_filter and offer["status"] != status_filter:
                continue
            if token_filter and offer["token"] != token_filter:
                continue
            if lender_filter and offer["lender"] != lender_filter:
                continue
            if offer["remaining_amount"] < min_amount:
                continue
            if offer["interest_rate"] > max_rate:
                continue

            results.append(offer)
            if len(results) >= limit:
                break

        logger.info("P2P offers listed: %d results (filters=%s)", len(results), filters)
        return results

    async def cancel_offer(self, offer_id: str, lender: str) -> dict[str, Any]:
        """Cancel an open offer. Only the lender can cancel."""
        if offer_id not in self._offers:
            raise KeyError(f"Offer '{offer_id}' not found")

        offer = self._offers[offer_id]
        if offer["lender"] != lender:
            raise ValueError("Only the lender can cancel their offer")
        if offer["status"] != OfferStatus.OPEN:
            raise ValueError(f"Offer is {offer['status']}, cannot cancel")

        offer["status"] = OfferStatus.CANCELLED
        logger.info("P2P offer cancelled: id=%s", offer_id)
        return {"offer_id": offer_id, "status": OfferStatus.CANCELLED}

    async def repay_offer(
        self, offer_id: str, borrower: str, amount: float
    ) -> dict[str, Any]:
        """Repay a filled P2P lending offer."""
        if offer_id not in self._offers:
            raise KeyError(f"Offer '{offer_id}' not found")

        offer = self._offers[offer_id]
        if offer["status"] != OfferStatus.FILLED:
            raise ValueError(f"Offer is {offer['status']}, cannot repay")
        if offer["borrower"] != borrower:
            raise ValueError("Only the borrower can repay")

        total_due = offer.get("total_repayment", offer["amount"])
        if amount < total_due:
            raise ValueError(
                f"Partial repayment not supported. Full amount due: {total_due:.6f}"
            )

        offer["status"] = OfferStatus.REPAID

        logger.info(
            "P2P offer repaid: id=%s borrower=%s amount=%.6f",
            offer_id, borrower, amount,
        )
        return {
            "offer_id": offer_id,
            "status": OfferStatus.REPAID,
            "amount_repaid": amount,
            "collateral_released": offer.get("collateral"),
        }
