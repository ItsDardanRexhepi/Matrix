"""
LoanManager — manage lending positions with collateralisation tracking,
variable interest rates, and auto-liquidation triggers.

Collateralisation rules:
  - Minimum ratio: 150% (loan creation)
  - Liquidation trigger: below 120%
  - Interest rate: variable, based on pool utilisation
"""

from __future__ import annotations

import logging
import math
import time
import uuid
from enum import Enum
from typing import Any

logger = logging.getLogger(__name__)


class LoanStatus(str, Enum):
    ACTIVE = "active"
    REPAID = "repaid"
    LIQUIDATED = "liquidated"
    DEFAULTED = "defaulted"


# Interest rate model parameters
_BASE_RATE = 0.02         # 2% base annual rate
_SLOPE_1 = 0.04           # slope below optimal utilisation
_SLOPE_2 = 0.75           # slope above optimal utilisation
_OPTIMAL_UTILISATION = 0.8  # 80% optimal utilisation

# Collateralisation thresholds
_MIN_COLLATERAL_RATIO = 1.5    # 150%
_LIQUIDATION_THRESHOLD = 1.2   # 120%
_LIQUIDATION_PENALTY = 0.05    # 5% penalty


class LoanManager:
    """Manage lending positions with collateral tracking.

    Parameters
    ----------
    config : dict
        Platform config.  Reads:
        - ``defi.min_collateral_ratio`` (default 1.5)
        - ``defi.liquidation_threshold`` (default 1.2)
        - ``defi.liquidation_penalty`` (default 0.05)
        - ``defi.base_rate`` (default 0.02)
    """

    def __init__(self, config: dict) -> None:
        self._config = config
        defi_cfg = config.get("defi", {})

        self._min_collateral_ratio: float = float(
            defi_cfg.get("min_collateral_ratio", _MIN_COLLATERAL_RATIO)
        )
        self._liquidation_threshold: float = float(
            defi_cfg.get("liquidation_threshold", _LIQUIDATION_THRESHOLD)
        )
        self._liquidation_penalty: float = float(
            defi_cfg.get("liquidation_penalty", _LIQUIDATION_PENALTY)
        )
        self._base_rate: float = float(
            defi_cfg.get("base_rate", _BASE_RATE)
        )

        # In-memory loan storage (production: on-chain or DB)
        self._loans: dict[str, dict[str, Any]] = {}
        # Pool utilisation tracking per token
        self._pool_total: dict[str, float] = {}     # total deposited
        self._pool_borrowed: dict[str, float] = {}   # total borrowed

    async def create_loan(
        self,
        borrower: str,
        collateral_token: str,
        collateral_amount: float,
        borrow_token: str,
        borrow_amount: float,
        collateral_price: float,
        borrow_price: float,
    ) -> dict[str, Any]:
        """Create a new loan position.

        Parameters
        ----------
        borrower : str
            Borrower wallet address.
        collateral_token : str
            Token used as collateral.
        collateral_amount : float
            Amount of collateral deposited.
        borrow_token : str
            Token being borrowed.
        borrow_amount : float
            Amount to borrow.
        collateral_price : float
            Current USD price of collateral token.
        borrow_price : float
            Current USD price of borrow token.

        Returns
        -------
        dict
            Loan details including ``loan_id``, ``collateral_ratio``,
            ``interest_rate``, ``status``.

        Raises
        ------
        ValueError
            If collateralisation ratio is below minimum.
        """
        if collateral_amount <= 0 or borrow_amount <= 0:
            raise ValueError("Amounts must be positive")

        collateral_value = collateral_amount * collateral_price
        borrow_value = borrow_amount * borrow_price
        collateral_ratio = collateral_value / borrow_value if borrow_value > 0 else 0

        if collateral_ratio < self._min_collateral_ratio:
            raise ValueError(
                f"Collateral ratio {collateral_ratio:.2f} is below minimum "
                f"{self._min_collateral_ratio:.2f}. Deposit more collateral."
            )

        interest_rate = self._calculate_interest_rate(borrow_token)
        loan_id = f"loan_{uuid.uuid4().hex[:16]}"
        now = int(time.time())

        loan: dict[str, Any] = {
            "loan_id": loan_id,
            "borrower": borrower,
            "collateral_token": collateral_token,
            "collateral_amount": collateral_amount,
            "collateral_value_usd": collateral_value,
            "borrow_token": borrow_token,
            "borrow_amount": borrow_amount,
            "borrow_value_usd": borrow_value,
            "collateral_ratio": round(collateral_ratio, 4),
            "interest_rate": round(interest_rate, 6),
            "accrued_interest": 0.0,
            "status": LoanStatus.ACTIVE,
            "created_at": now,
            "last_interest_update": now,
            "liquidation_threshold": self._liquidation_threshold,
        }

        self._loans[loan_id] = loan

        # Update pool utilisation
        self._pool_borrowed[borrow_token] = (
            self._pool_borrowed.get(borrow_token, 0) + borrow_amount
        )

        logger.info(
            "Loan created: id=%s borrower=%s collateral=%.4f %s "
            "borrow=%.4f %s ratio=%.2f rate=%.4f%%",
            loan_id, borrower, collateral_amount, collateral_token,
            borrow_amount, borrow_token, collateral_ratio, interest_rate * 100,
        )
        return loan

    async def get_loan(self, loan_id: str) -> dict[str, Any]:
        """Retrieve a loan by ID with updated accrued interest.

        Raises
        ------
        KeyError
            If loan_id is not found.
        """
        if loan_id not in self._loans:
            raise KeyError(f"Loan '{loan_id}' not found")

        loan = self._loans[loan_id]
        if loan["status"] == LoanStatus.ACTIVE:
            self._accrue_interest(loan)
        return loan

    async def repay_loan(
        self, loan_id: str, amount: float
    ) -> dict[str, Any]:
        """Repay part or all of a loan.

        Parameters
        ----------
        loan_id : str
            The loan identifier.
        amount : float
            Amount to repay in the borrow token.

        Returns
        -------
        dict
            Updated loan state.
        """
        if loan_id not in self._loans:
            raise KeyError(f"Loan '{loan_id}' not found")

        loan = self._loans[loan_id]
        if loan["status"] != LoanStatus.ACTIVE:
            raise ValueError(f"Loan '{loan_id}' is {loan['status']}, cannot repay")

        self._accrue_interest(loan)
        total_owed = loan["borrow_amount"] + loan["accrued_interest"]

        if amount <= 0:
            raise ValueError("Repayment amount must be positive")

        repay_amount = min(amount, total_owed)

        # Apply repayment: first to interest, then principal
        if repay_amount <= loan["accrued_interest"]:
            loan["accrued_interest"] -= repay_amount
        else:
            remainder = repay_amount - loan["accrued_interest"]
            loan["accrued_interest"] = 0.0
            loan["borrow_amount"] -= remainder

        # Update pool
        self._pool_borrowed[loan["borrow_token"]] = max(
            0, self._pool_borrowed.get(loan["borrow_token"], 0) - repay_amount
        )

        # Check if fully repaid
        total_remaining = loan["borrow_amount"] + loan["accrued_interest"]
        if total_remaining <= 1e-18:  # effectively zero
            loan["status"] = LoanStatus.REPAID
            loan["borrow_amount"] = 0.0
            loan["accrued_interest"] = 0.0

        logger.info(
            "Loan repayment: id=%s amount=%.6f remaining=%.6f status=%s",
            loan_id, repay_amount, total_remaining, loan["status"],
        )
        return {
            "loan_id": loan_id,
            "repaid_amount": repay_amount,
            "remaining_principal": loan["borrow_amount"],
            "remaining_interest": loan["accrued_interest"],
            "status": loan["status"],
        }

    async def liquidate(
        self,
        loan_id: str,
        collateral_price: float,
        borrow_price: float,
    ) -> dict[str, Any]:
        """Attempt to liquidate an under-collateralised loan.

        Parameters
        ----------
        loan_id : str
            The loan identifier.
        collateral_price : float
            Current USD price of collateral token.
        borrow_price : float
            Current USD price of borrow token.

        Returns
        -------
        dict
            Liquidation result.

        Raises
        ------
        ValueError
            If loan is not eligible for liquidation.
        """
        if loan_id not in self._loans:
            raise KeyError(f"Loan '{loan_id}' not found")

        loan = self._loans[loan_id]
        if loan["status"] != LoanStatus.ACTIVE:
            raise ValueError(f"Loan '{loan_id}' is {loan['status']}, cannot liquidate")

        self._accrue_interest(loan)

        collateral_value = loan["collateral_amount"] * collateral_price
        total_owed = loan["borrow_amount"] + loan["accrued_interest"]
        borrow_value = total_owed * borrow_price
        current_ratio = collateral_value / borrow_value if borrow_value > 0 else float("inf")

        if current_ratio >= self._liquidation_threshold:
            raise ValueError(
                f"Loan ratio {current_ratio:.2f} is above liquidation threshold "
                f"{self._liquidation_threshold:.2f}. Not eligible."
            )

        # Calculate liquidation
        penalty = total_owed * self._liquidation_penalty
        collateral_seized = (total_owed + penalty) * borrow_price / collateral_price
        collateral_seized = min(collateral_seized, loan["collateral_amount"])

        collateral_remaining = loan["collateral_amount"] - collateral_seized

        loan["status"] = LoanStatus.LIQUIDATED
        loan["collateral_amount"] = collateral_remaining
        loan["borrow_amount"] = 0.0
        loan["accrued_interest"] = 0.0

        # Update pool
        self._pool_borrowed[loan["borrow_token"]] = max(
            0, self._pool_borrowed.get(loan["borrow_token"], 0) - total_owed
        )

        result = {
            "loan_id": loan_id,
            "status": LoanStatus.LIQUIDATED,
            "collateral_seized": round(collateral_seized, 8),
            "collateral_remaining": round(collateral_remaining, 8),
            "debt_repaid": round(total_owed, 8),
            "liquidation_penalty": round(penalty, 8),
            "ratio_at_liquidation": round(current_ratio, 4),
        }

        logger.info(
            "Loan liquidated: id=%s seized=%.6f %s ratio=%.2f",
            loan_id, collateral_seized, loan["collateral_token"], current_ratio,
        )
        return result

    async def check_liquidation_eligibility(
        self,
        loan_id: str,
        collateral_price: float,
        borrow_price: float,
    ) -> dict[str, Any]:
        """Check if a loan is eligible for liquidation.

        Returns
        -------
        dict
            Keys: ``eligible``, ``current_ratio``, ``threshold``.
        """
        if loan_id not in self._loans:
            raise KeyError(f"Loan '{loan_id}' not found")

        loan = self._loans[loan_id]
        if loan["status"] != LoanStatus.ACTIVE:
            return {
                "eligible": False,
                "reason": f"Loan is {loan['status']}",
            }

        self._accrue_interest(loan)
        collateral_value = loan["collateral_amount"] * collateral_price
        total_owed = (loan["borrow_amount"] + loan["accrued_interest"]) * borrow_price
        current_ratio = collateral_value / total_owed if total_owed > 0 else float("inf")

        return {
            "eligible": current_ratio < self._liquidation_threshold,
            "current_ratio": round(current_ratio, 4),
            "threshold": self._liquidation_threshold,
            "loan_id": loan_id,
        }

    def get_all_active_loans(self) -> list[dict[str, Any]]:
        """Return all active loans."""
        return [
            loan for loan in self._loans.values()
            if loan["status"] == LoanStatus.ACTIVE
        ]

    # ── Interest rate model ───────────────────────────────────────────

    def _calculate_interest_rate(self, token: str) -> float:
        """Calculate variable interest rate based on pool utilisation.

        Uses a kinked rate model similar to Aave/Compound:
        - Below optimal utilisation: base_rate + utilisation * slope1
        - Above optimal utilisation: base_rate + optimal * slope1 +
          (utilisation - optimal) * slope2
        """
        total = self._pool_total.get(token, 1.0)
        borrowed = self._pool_borrowed.get(token, 0.0)
        utilisation = min(borrowed / total, 1.0) if total > 0 else 0.0

        if utilisation <= _OPTIMAL_UTILISATION:
            rate = self._base_rate + utilisation * _SLOPE_1
        else:
            excess = utilisation - _OPTIMAL_UTILISATION
            rate = (
                self._base_rate
                + _OPTIMAL_UTILISATION * _SLOPE_1
                + excess * _SLOPE_2
            )
        return rate

    def _accrue_interest(self, loan: dict[str, Any]) -> None:
        """Accrue interest on a loan based on elapsed time."""
        now = int(time.time())
        elapsed = now - loan["last_interest_update"]
        if elapsed <= 0:
            return

        # Continuous compounding: P * e^(r*t) - P
        annual_rate = loan["interest_rate"]
        years = elapsed / (365.25 * 24 * 3600)
        principal = loan["borrow_amount"]
        new_interest = principal * (math.exp(annual_rate * years) - 1)

        loan["accrued_interest"] += new_interest
        loan["last_interest_update"] = now

    async def get_rates(self, token: str) -> dict[str, Any]:
        """Get current interest rates for a token.

        Returns
        -------
        dict
            Keys: ``borrow_rate``, ``utilisation``, ``pool_total``,
            ``pool_borrowed``.
        """
        total = self._pool_total.get(token, 0.0)
        borrowed = self._pool_borrowed.get(token, 0.0)
        utilisation = borrowed / total if total > 0 else 0.0
        rate = self._calculate_interest_rate(token)

        return {
            "token": token,
            "borrow_rate": round(rate, 6),
            "borrow_rate_pct": f"{rate * 100:.2f}%",
            "utilisation": round(utilisation, 4),
            "pool_total": total,
            "pool_borrowed": borrowed,
        }

    def update_pool_total(self, token: str, amount: float) -> None:
        """Update the total pool size for a token (called on deposit/withdraw)."""
        self._pool_total[token] = max(0, self._pool_total.get(token, 0) + amount)
