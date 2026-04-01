"""
ReserveFund — insurance pool management.

Maintains the capital reserve that backs active insurance policies.
Enforces a minimum reserve ratio of 150 % of active coverage.
"""

from __future__ import annotations

import logging
import time
from typing import Any

logger = logging.getLogger(__name__)

_MIN_RESERVE_RATIO = 1.5  # 150 %


class ReserveFund:
    """Manages the insurance reserve pool.

    Config keys (under ``config["insurance"]``):
        min_reserve_ratio (float): Minimum ratio of reserves to active
            coverage (default 1.5 = 150 %).
        initial_reserve (float): Starting balance (default 0).
    """

    def __init__(self, config: dict) -> None:
        self._config = config
        ins_cfg = config.get("insurance", {})

        self._min_ratio: float = float(
            ins_cfg.get("min_reserve_ratio", _MIN_RESERVE_RATIO)
        )
        self._balance: float = float(ins_cfg.get("initial_reserve", 0.0))
        self._active_coverage: float = 0.0
        self._transactions: list[dict[str, Any]] = []

    async def deposit(self, amount: float) -> dict:
        """Deposit funds into the reserve.

        Args:
            amount: Amount to deposit (must be positive).

        Returns:
            Updated balance and solvency info.
        """
        if amount <= 0:
            raise ValueError("Deposit amount must be positive")

        self._balance += amount
        self._transactions.append({
            "type": "deposit",
            "amount": amount,
            "balance_after": self._balance,
            "timestamp": int(time.time()),
        })

        logger.info("Reserve deposit: %.6f (balance now %.6f)", amount, self._balance)
        return {
            "status": "deposited",
            "amount": amount,
            "balance": self._balance,
            "solvency": await self.check_solvency(0),
        }

    async def withdraw(self, amount: float) -> dict:
        """Withdraw funds from the reserve (for approved payouts).

        Args:
            amount: Amount to withdraw.

        Returns:
            Updated balance.
        """
        if amount <= 0:
            raise ValueError("Withdrawal amount must be positive")
        if amount > self._balance:
            raise ValueError(
                f"Insufficient reserve: requested {amount}, available {self._balance}"
            )

        self._balance -= amount
        self._transactions.append({
            "type": "withdrawal",
            "amount": amount,
            "balance_after": self._balance,
            "timestamp": int(time.time()),
        })

        logger.info("Reserve withdrawal: %.6f (balance now %.6f)", amount, self._balance)
        return {
            "status": "withdrawn",
            "amount": amount,
            "balance": self._balance,
        }

    async def get_balance(self) -> dict:
        """Return current reserve balance and statistics."""
        return {
            "balance": self._balance,
            "active_coverage": self._active_coverage,
            "reserve_ratio": (
                self._balance / self._active_coverage
                if self._active_coverage > 0
                else float("inf")
            ),
            "min_required_ratio": self._min_ratio,
            "total_transactions": len(self._transactions),
        }

    async def check_solvency(self, pending_claims: float) -> dict:
        """Check whether the reserve can cover pending claims.

        Args:
            pending_claims: Additional coverage amount to consider.

        Returns:
            Solvency assessment.
        """
        total_exposure = self._active_coverage + pending_claims
        required = total_exposure * self._min_ratio

        solvent = self._balance >= required
        ratio = (
            self._balance / total_exposure
            if total_exposure > 0
            else float("inf")
        )

        return {
            "solvent": solvent,
            "balance": self._balance,
            "active_coverage": self._active_coverage,
            "pending_claims": pending_claims,
            "total_exposure": total_exposure,
            "required_reserve": round(required, 6),
            "current_ratio": round(ratio, 4) if ratio != float("inf") else "inf",
            "min_required_ratio": self._min_ratio,
        }

    async def add_coverage(self, amount: float) -> None:
        """Track newly activated coverage."""
        self._active_coverage += amount

    async def remove_coverage(self, amount: float) -> None:
        """Track deactivated coverage."""
        self._active_coverage = max(0.0, self._active_coverage - amount)
