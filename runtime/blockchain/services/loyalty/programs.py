"""Loyalty Program Manager - Component 23.

Manages business-specific loyalty programs, each with its own point rates,
tiers, and reward catalog.
"""

from __future__ import annotations

import logging
import time
import uuid
from typing import Any

logger = logging.getLogger(__name__)

DEFAULT_TIERS: dict[str, dict] = {
    "bronze": {"min_points": 0, "multiplier": 1.0},
    "silver": {"min_points": 500, "multiplier": 1.15},
    "gold": {"min_points": 2500, "multiplier": 1.4},
    "platinum": {"min_points": 10000, "multiplier": 1.75},
}

DEFAULT_ACTION_RATES: dict[str, float] = {
    "purchase": 1.0,
    "referral": 3.0,
    "review": 1.5,
}

DEFAULT_REWARD_COSTS: dict[str, int] = {
    "discount_5pct": 500,
    "discount_10pct": 900,
    "free_item": 1000,
}


class ProgramManager:
    """Manages creation and lifecycle of loyalty programs.

    Each program has independent point rates, tier thresholds, and reward catalogs.
    The platform program is pre-seeded by LoyaltyService; additional programs are
    created by businesses.
    """

    def __init__(self, config: dict[str, Any] | None = None) -> None:
        self.config = config or {}
        self._programs: dict[str, dict] = {}
        logger.info("ProgramManager initialised")

    async def create_program(self, business: str, config: dict) -> dict:
        """Create a new loyalty program for a business.

        Args:
            business: Business identifier / wallet address.
            config: Program configuration including name, tiers, rates, rewards.

        Returns:
            The created program record.
        """
        if not business:
            raise ValueError("business identifier is required")

        program_id = config.get("program_id", f"prog_{uuid.uuid4().hex[:12]}")
        if program_id in self._programs:
            raise ValueError(f"Program '{program_id}' already exists")

        name = config.get("name", f"{business}_loyalty")
        tiers = config.get("tiers", DEFAULT_TIERS)
        action_rates = config.get("action_rates", DEFAULT_ACTION_RATES)
        reward_costs = config.get("reward_costs", DEFAULT_REWARD_COSTS)
        point_rate = config.get("point_rate", 1.0)

        program = {
            "program_id": program_id,
            "business": business,
            "name": name,
            "point_rate": point_rate,
            "tiers": tiers,
            "action_rates": action_rates,
            "reward_costs": reward_costs,
            "status": "active",
            "created_at": time.time(),
            "updated_at": time.time(),
            "total_points_issued": 0,
            "total_points_redeemed": 0,
            "member_count": 0,
        }

        self._programs[program_id] = program
        logger.info("Created program '%s' for business '%s'", program_id, business)
        return program

    async def update_program(self, program_id: str, updates: dict) -> dict:
        """Update an existing program's configuration.

        Args:
            program_id: The program to update.
            updates: Fields to change (tiers, action_rates, reward_costs, status, name).

        Returns:
            The updated program record.
        """
        if program_id not in self._programs:
            raise ValueError(f"Program '{program_id}' not found")

        program = self._programs[program_id]
        allowed_fields = {"name", "tiers", "action_rates", "reward_costs", "point_rate", "status"}
        applied = []
        for key, value in updates.items():
            if key in allowed_fields:
                program[key] = value
                applied.append(key)
            else:
                logger.warning("Ignoring disallowed update field '%s' for program '%s'", key, program_id)

        program["updated_at"] = time.time()
        logger.info("Updated program '%s': fields=%s", program_id, applied)
        return program

    async def get_program(self, program_id: str) -> dict | None:
        """Retrieve a program by ID.

        Returns:
            The program record, or None if not found.
        """
        return self._programs.get(program_id)

    async def list_programs(self) -> list:
        """List all registered programs.

        Returns:
            List of program records.
        """
        return list(self._programs.values())
