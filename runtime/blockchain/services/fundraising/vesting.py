"""
VestingManager — token vesting for campaign rewards.

Supports linear and cliff vesting schedules.
"""

from __future__ import annotations

import logging
import time
import uuid
from typing import Any

logger = logging.getLogger(__name__)


class VestingManager:
    """Token vesting manager for campaign reward distribution.

    Config keys (under ``config["fundraising"]``):
        min_vesting_days (int): Minimum vesting period in days (default 30).
        max_vesting_days (int): Maximum vesting period in days (default 1460 = 4 years).
    """

    def __init__(self, config: dict) -> None:
        self._config = config
        f_cfg: dict[str, Any] = config.get("fundraising", {})

        self._min_days: int = int(f_cfg.get("min_vesting_days", 30))
        self._max_days: int = int(f_cfg.get("max_vesting_days", 1460))

        # vesting_id -> vesting record
        self._vestings: dict[str, dict[str, Any]] = {}

        logger.info(
            "VestingManager initialised (min=%dd, max=%dd).",
            self._min_days, self._max_days,
        )

    async def create_vesting(
        self,
        beneficiary: str,
        token: str,
        total_amount: float,
        schedule: dict,
    ) -> dict:
        """Create a new vesting schedule.

        Args:
            beneficiary: Wallet address that will receive vested tokens.
            token: Token symbol/address.
            total_amount: Total amount to vest.
            schedule: Dict with keys:
                - type: "linear" or "cliff"
                - duration_days: Total vesting period in days.
                - cliff_days: (cliff only) Days until first release.
                - cliff_pct: (cliff only) Percentage released at cliff (default 25).

        Returns:
            Vesting record.
        """
        if not beneficiary:
            raise ValueError("Beneficiary address is required")
        if total_amount <= 0:
            raise ValueError("Total amount must be positive")

        vesting_type = schedule.get("type", "linear")
        if vesting_type not in ("linear", "cliff"):
            raise ValueError(f"Vesting type must be 'linear' or 'cliff', got '{vesting_type}'")

        duration_days = int(schedule.get("duration_days", 365))
        if duration_days < self._min_days:
            raise ValueError(
                f"Vesting duration must be at least {self._min_days} days"
            )
        if duration_days > self._max_days:
            raise ValueError(
                f"Vesting duration must not exceed {self._max_days} days"
            )

        vesting_id = str(uuid.uuid4())
        now = int(time.time())
        duration_seconds = duration_days * 86400

        vesting: dict[str, Any] = {
            "vesting_id": vesting_id,
            "beneficiary": beneficiary,
            "token": token,
            "total_amount": total_amount,
            "claimed_amount": 0.0,
            "vesting_type": vesting_type,
            "duration_days": duration_days,
            "start_at": now,
            "end_at": now + duration_seconds,
            "created_at": now,
            "status": "active",
        }

        if vesting_type == "cliff":
            cliff_days = int(schedule.get("cliff_days", duration_days // 4))
            cliff_pct = float(schedule.get("cliff_pct", 25.0))
            vesting["cliff_at"] = now + (cliff_days * 86400)
            vesting["cliff_pct"] = cliff_pct
            vesting["cliff_amount"] = total_amount * (cliff_pct / 100.0)
            vesting["cliff_released"] = False

        self._vestings[vesting_id] = vesting

        logger.info(
            "Vesting created: id=%s beneficiary=%s amount=%.4f type=%s duration=%dd",
            vesting_id, beneficiary, total_amount, vesting_type, duration_days,
        )
        return dict(vesting)

    async def claim_vested(self, vesting_id: str) -> dict:
        """Claim available vested tokens.

        Returns:
            Dict with claimed amount and updated vesting status.
        """
        vesting = self._vestings.get(vesting_id)
        if not vesting:
            raise ValueError(f"Vesting {vesting_id} not found")
        if vesting["status"] != "active":
            raise ValueError(f"Vesting {vesting_id} is {vesting['status']}")

        now = int(time.time())
        available = self._calculate_available(vesting, now)
        claimable = available - vesting["claimed_amount"]

        if claimable <= 0:
            return {
                "vesting_id": vesting_id,
                "claimed": 0.0,
                "total_claimed": vesting["claimed_amount"],
                "total_amount": vesting["total_amount"],
                "message": "No tokens available to claim yet",
            }

        vesting["claimed_amount"] += claimable

        # Mark cliff as released if applicable
        if (vesting["vesting_type"] == "cliff"
                and not vesting.get("cliff_released", True)
                and now >= vesting.get("cliff_at", 0)):
            vesting["cliff_released"] = True

        # Check if fully vested
        if vesting["claimed_amount"] >= vesting["total_amount"] - 1e-9:
            vesting["claimed_amount"] = vesting["total_amount"]
            vesting["status"] = "completed"

        logger.info(
            "Vesting claimed: id=%s amount=%.6f total_claimed=%.6f",
            vesting_id, claimable, vesting["claimed_amount"],
        )
        return {
            "vesting_id": vesting_id,
            "claimed": claimable,
            "total_claimed": vesting["claimed_amount"],
            "total_amount": vesting["total_amount"],
            "remaining": vesting["total_amount"] - vesting["claimed_amount"],
            "status": vesting["status"],
        }

    async def get_vesting_status(self, vesting_id: str) -> dict:
        """Get current vesting status with available-to-claim calculation.

        Returns:
            Full vesting record with current claimable amount.
        """
        vesting = self._vestings.get(vesting_id)
        if not vesting:
            raise ValueError(f"Vesting {vesting_id} not found")

        now = int(time.time())
        available = self._calculate_available(vesting, now)
        claimable = max(0.0, available - vesting["claimed_amount"])

        result = dict(vesting)
        result["available_now"] = available
        result["claimable_now"] = claimable
        result["pct_vested"] = (available / vesting["total_amount"] * 100) if vesting["total_amount"] > 0 else 0

        elapsed = now - vesting["start_at"]
        total_duration = vesting["end_at"] - vesting["start_at"]
        result["time_elapsed_pct"] = min(100.0, (elapsed / total_duration * 100)) if total_duration > 0 else 100.0

        return result

    def _calculate_available(self, vesting: dict, now: int) -> float:
        """Calculate total amount available (vested) at a given time."""
        if now >= vesting["end_at"]:
            return vesting["total_amount"]

        if now <= vesting["start_at"]:
            return 0.0

        if vesting["vesting_type"] == "linear":
            elapsed = now - vesting["start_at"]
            total = vesting["end_at"] - vesting["start_at"]
            fraction = elapsed / total
            return vesting["total_amount"] * fraction

        elif vesting["vesting_type"] == "cliff":
            cliff_at = vesting.get("cliff_at", vesting["start_at"])

            if now < cliff_at:
                return 0.0

            cliff_amount = vesting.get("cliff_amount", 0.0)
            remaining = vesting["total_amount"] - cliff_amount

            if remaining <= 0:
                return cliff_amount

            # Linear vesting of remaining after cliff
            elapsed_after_cliff = now - cliff_at
            total_after_cliff = vesting["end_at"] - cliff_at
            if total_after_cliff <= 0:
                return vesting["total_amount"]

            linear_fraction = elapsed_after_cliff / total_after_cliff
            return cliff_amount + (remaining * linear_fraction)

        return 0.0
