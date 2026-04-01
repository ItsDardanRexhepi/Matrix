"""Smart Loyalty & Rewards Service - Component 23.

Manages platform-native loyalty points and business-specific reward programs.
Supports earning, redemption, tier management, and ZKP-based eligibility proofs.
"""

from __future__ import annotations

import logging
import time
import uuid
from dataclasses import dataclass, field
from typing import Any

from .programs import ProgramManager
from .zkp_eligibility import ZKPEligibility

logger = logging.getLogger(__name__)

DEFAULT_CONFIG: dict[str, Any] = {
    "platform_program_id": "platform",
    "default_point_rate": 1.0,
    "tiers": {
        "bronze": {"min_points": 0, "multiplier": 1.0},
        "silver": {"min_points": 1000, "multiplier": 1.25},
        "gold": {"min_points": 5000, "multiplier": 1.5},
        "platinum": {"min_points": 20000, "multiplier": 2.0},
        "diamond": {"min_points": 50000, "multiplier": 3.0},
    },
    "action_rates": {
        "purchase": 1.0,
        "referral": 5.0,
        "review": 2.0,
        "social_share": 0.5,
        "checkin": 0.25,
    },
    "reward_costs": {
        "discount_5pct": 500,
        "discount_10pct": 900,
        "free_shipping": 300,
        "cashback_1usd": 100,
        "nft_badge": 1500,
    },
}


@dataclass
class UserLedger:
    """Tracks a user's point balance and history within a program."""

    user: str
    program_id: str
    balance: int = 0
    lifetime_earned: int = 0
    lifetime_redeemed: int = 0
    transactions: list[dict] = field(default_factory=list)
    created_at: float = field(default_factory=time.time)


class LoyaltyService:
    """Main service for smart loyalty and rewards.

    Operates in two modes:
    - Platform-native loyalty: default 'platform' program for all users.
    - Business-specific programs: custom programs with their own rules.
    """

    def __init__(self, config: dict[str, Any] | None = None) -> None:
        self.config = {**DEFAULT_CONFIG, **(config or {})}
        self._ledgers: dict[str, UserLedger] = {}  # key: f"{user}:{program_id}"
        self.program_manager = ProgramManager(self.config)
        self.zkp = ZKPEligibility(self.config)
        # Ensure the platform program exists
        self.program_manager._programs[self.config["platform_program_id"]] = {
            "program_id": self.config["platform_program_id"],
            "business": "platform",
            "point_rate": self.config["default_point_rate"],
            "tiers": self.config["tiers"],
            "action_rates": self.config["action_rates"],
            "reward_costs": self.config["reward_costs"],
            "status": "active",
            "created_at": time.time(),
        }
        logger.info("LoyaltyService initialised with config: platform_program=%s", self.config["platform_program_id"])

    def _ledger_key(self, user: str, program_id: str) -> str:
        return f"{user}:{program_id}"

    def _get_or_create_ledger(self, user: str, program_id: str) -> UserLedger:
        key = self._ledger_key(user, program_id)
        if key not in self._ledgers:
            self._ledgers[key] = UserLedger(user=user, program_id=program_id)
        return self._ledgers[key]

    def _resolve_tier(self, lifetime_earned: int, tiers: dict[str, dict]) -> str:
        """Determine tier based on lifetime earned points."""
        resolved = "bronze"
        resolved_min = -1
        for tier_name, tier_cfg in tiers.items():
            if lifetime_earned >= tier_cfg["min_points"] and tier_cfg["min_points"] > resolved_min:
                resolved = tier_name
                resolved_min = tier_cfg["min_points"]
        return resolved

    async def _get_program_config(self, program_id: str) -> dict:
        """Get program config, raising if not found."""
        program = await self.program_manager.get_program(program_id)
        if not program:
            raise ValueError(f"Program '{program_id}' not found")
        if program.get("status") != "active":
            raise ValueError(f"Program '{program_id}' is not active (status={program.get('status')})")
        return program

    async def earn_points(self, user: str, action: str, amount: float, program_id: str = "platform") -> dict:
        """Award points for a user action.

        Args:
            user: Wallet address or user identifier.
            action: The action type (e.g. 'purchase', 'referral').
            amount: The base amount (e.g. purchase value in USD).
            program_id: The loyalty program to credit.

        Returns:
            Dict with earned points, new balance, and tier info.
        """
        if not user:
            raise ValueError("user is required")
        if amount < 0:
            raise ValueError("amount must be non-negative")

        program = await self._get_program_config(program_id)
        action_rates = program.get("action_rates", self.config["action_rates"])
        rate = action_rates.get(action, self.config["default_point_rate"])

        tiers = program.get("tiers", self.config["tiers"])
        ledger = self._get_or_create_ledger(user, program_id)

        current_tier = self._resolve_tier(ledger.lifetime_earned, tiers)
        multiplier = tiers.get(current_tier, {}).get("multiplier", 1.0)

        raw_points = int(amount * rate)
        earned = int(raw_points * multiplier)
        if earned < 0:
            earned = 0

        ledger.balance += earned
        ledger.lifetime_earned += earned

        tx = {
            "tx_id": str(uuid.uuid4()),
            "type": "earn",
            "action": action,
            "amount": amount,
            "points": earned,
            "rate": rate,
            "multiplier": multiplier,
            "timestamp": time.time(),
        }
        ledger.transactions.append(tx)

        new_tier = self._resolve_tier(ledger.lifetime_earned, tiers)
        tier_changed = new_tier != current_tier

        logger.info(
            "User %s earned %d points (action=%s, amount=%.2f, program=%s)",
            user, earned, action, amount, program_id,
        )

        return {
            "user": user,
            "program_id": program_id,
            "action": action,
            "points_earned": earned,
            "balance": ledger.balance,
            "tier": new_tier,
            "tier_changed": tier_changed,
            "previous_tier": current_tier if tier_changed else None,
            "transaction_id": tx["tx_id"],
        }

    async def redeem_points(self, user: str, points: int, reward_type: str, program_id: str = "platform") -> dict:
        """Redeem points for a reward.

        Args:
            user: Wallet address or user identifier.
            points: Number of points to redeem.
            reward_type: The reward to claim (e.g. 'discount_5pct').
            program_id: The loyalty program to debit.

        Returns:
            Dict with redemption details and remaining balance.
        """
        if not user:
            raise ValueError("user is required")
        if points <= 0:
            raise ValueError("points must be positive")

        program = await self._get_program_config(program_id)
        reward_costs = program.get("reward_costs", self.config["reward_costs"])

        if reward_type not in reward_costs:
            raise ValueError(f"Unknown reward type '{reward_type}'. Available: {list(reward_costs.keys())}")

        cost = reward_costs[reward_type]
        if points < cost:
            raise ValueError(f"Reward '{reward_type}' costs {cost} points, but only {points} offered")

        ledger = self._get_or_create_ledger(user, program_id)
        if ledger.balance < cost:
            raise ValueError(f"Insufficient balance: have {ledger.balance}, need {cost}")

        ledger.balance -= cost
        ledger.lifetime_redeemed += cost

        tx = {
            "tx_id": str(uuid.uuid4()),
            "type": "redeem",
            "reward_type": reward_type,
            "points_spent": cost,
            "timestamp": time.time(),
        }
        ledger.transactions.append(tx)

        logger.info(
            "User %s redeemed %d points for %s (program=%s)",
            user, cost, reward_type, program_id,
        )

        return {
            "user": user,
            "program_id": program_id,
            "reward_type": reward_type,
            "points_spent": cost,
            "balance": ledger.balance,
            "transaction_id": tx["tx_id"],
            "reward_delivered": True,
        }

    async def get_balance(self, user: str, program_id: str = "platform") -> dict:
        """Get a user's point balance.

        Returns:
            Dict with current balance, lifetime stats, and tier.
        """
        if not user:
            raise ValueError("user is required")

        ledger = self._get_or_create_ledger(user, program_id)
        program = await self._get_program_config(program_id)
        tiers = program.get("tiers", self.config["tiers"])
        tier = self._resolve_tier(ledger.lifetime_earned, tiers)

        return {
            "user": user,
            "program_id": program_id,
            "balance": ledger.balance,
            "lifetime_earned": ledger.lifetime_earned,
            "lifetime_redeemed": ledger.lifetime_redeemed,
            "tier": tier,
            "transaction_count": len(ledger.transactions),
        }

    async def get_tier(self, user: str, program_id: str = "platform") -> dict:
        """Get a user's current tier and progress toward next tier.

        Returns:
            Dict with current tier, next tier, and points needed.
        """
        if not user:
            raise ValueError("user is required")

        ledger = self._get_or_create_ledger(user, program_id)
        program = await self._get_program_config(program_id)
        tiers = program.get("tiers", self.config["tiers"])

        current = self._resolve_tier(ledger.lifetime_earned, tiers)
        current_min = tiers[current]["min_points"]
        current_multiplier = tiers[current]["multiplier"]

        # Find next tier
        sorted_tiers = sorted(tiers.items(), key=lambda x: x[1]["min_points"])
        next_tier = None
        points_to_next = None
        for tier_name, tier_cfg in sorted_tiers:
            if tier_cfg["min_points"] > ledger.lifetime_earned:
                next_tier = tier_name
                points_to_next = tier_cfg["min_points"] - ledger.lifetime_earned
                break

        return {
            "user": user,
            "program_id": program_id,
            "current_tier": current,
            "current_multiplier": current_multiplier,
            "lifetime_earned": ledger.lifetime_earned,
            "next_tier": next_tier,
            "points_to_next_tier": points_to_next,
            "is_max_tier": next_tier is None,
        }
