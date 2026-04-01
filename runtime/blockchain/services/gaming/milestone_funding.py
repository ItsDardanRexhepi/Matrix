"""
MilestoneFunding — fund game development in stages.

Funds are released only when milestones are verified with proof.
"""

from __future__ import annotations

import logging
import time
import uuid
from typing import Any

logger = logging.getLogger(__name__)


class MilestoneFunding:
    """Milestone-based game funding manager.

    Config keys (under ``config["gaming"]``):
        max_milestones (int): Maximum milestones per funding (default 20).
    """

    def __init__(self, config: dict) -> None:
        self._config = config
        g_cfg = config.get("gaming", {})
        self._max_milestones: int = int(g_cfg.get("max_milestones", 20))

        # funding_id -> funding record
        self._fundings: dict[str, dict[str, Any]] = {}

    async def create_funding(
        self,
        game_id: str,
        milestones: list[dict],
        total_amount: float,
    ) -> dict:
        """Create a milestone-based funding plan.

        Args:
            game_id: The game being funded.
            milestones: List of dicts, each with ``title``, ``description``,
                        ``amount``, and ``deadline`` (unix timestamp).
            total_amount: Total funding amount deposited.

        Returns:
            Funding record.
        """
        if not milestones:
            raise ValueError("At least one milestone is required")
        if len(milestones) > self._max_milestones:
            raise ValueError(
                f"Maximum {self._max_milestones} milestones allowed"
            )
        if total_amount <= 0:
            raise ValueError("total_amount must be positive")

        # Validate milestone amounts sum to total
        milestone_sum = sum(float(m.get("amount", 0)) for m in milestones)
        if abs(milestone_sum - total_amount) > 0.01:
            raise ValueError(
                f"Milestone amounts ({milestone_sum}) must sum to "
                f"total_amount ({total_amount})"
            )

        funding_id = f"fund_{uuid.uuid4().hex[:16]}"
        now = int(time.time())

        enriched_milestones: list[dict[str, Any]] = []
        for idx, m in enumerate(milestones):
            enriched_milestones.append({
                "index": idx,
                "title": m.get("title", f"Milestone {idx + 1}"),
                "description": m.get("description", ""),
                "amount": float(m.get("amount", 0)),
                "deadline": int(m.get("deadline", 0)),
                "status": "pending",
                "proof": None,
                "released_at": None,
            })

        funding: dict[str, Any] = {
            "funding_id": funding_id,
            "game_id": game_id,
            "total_amount": total_amount,
            "released_amount": 0.0,
            "remaining_amount": total_amount,
            "milestones": enriched_milestones,
            "status": "active",
            "created_at": now,
        }
        self._fundings[funding_id] = funding

        logger.info(
            "Funding created: id=%s game=%s total=%.6f milestones=%d",
            funding_id, game_id, total_amount, len(milestones),
        )
        return funding

    async def release_milestone(
        self,
        funding_id: str,
        milestone_idx: int,
        proof: dict,
    ) -> dict:
        """Release funds for a completed milestone.

        Args:
            funding_id: The funding plan.
            milestone_idx: Index of the milestone to release.
            proof: Dict with evidence of completion (e.g. ``commit_hash``,
                   ``demo_url``, ``reviewer_approval``).

        Returns:
            Updated funding record.
        """
        funding = self._fundings.get(funding_id)
        if not funding:
            raise ValueError(f"Funding {funding_id} not found")
        if funding["status"] != "active":
            raise ValueError(f"Funding {funding_id} is not active")

        milestones = funding["milestones"]
        if milestone_idx < 0 or milestone_idx >= len(milestones):
            raise ValueError(
                f"Invalid milestone_idx {milestone_idx}. "
                f"Valid range: 0-{len(milestones) - 1}"
            )

        milestone = milestones[milestone_idx]
        if milestone["status"] == "released":
            return {
                "status": "already_released",
                "funding_id": funding_id,
                "milestone_idx": milestone_idx,
            }

        # Verify prior milestones are released (sequential release)
        for i in range(milestone_idx):
            if milestones[i]["status"] != "released":
                raise ValueError(
                    f"Milestone {i} must be released before milestone {milestone_idx}"
                )

        # Validate proof
        if not proof:
            raise ValueError("Proof of completion is required")

        now = int(time.time())
        amount = milestone["amount"]

        milestone["status"] = "released"
        milestone["proof"] = proof
        milestone["released_at"] = now

        funding["released_amount"] += amount
        funding["remaining_amount"] -= amount

        # Check if all milestones are released
        if all(m["status"] == "released" for m in milestones):
            funding["status"] = "completed"
            funding["completed_at"] = now

        logger.info(
            "Milestone released: funding=%s idx=%d amount=%.6f",
            funding_id, milestone_idx, amount,
        )
        return funding

    async def get_funding_status(self, funding_id: str) -> dict:
        """Get the status of a funding plan."""
        funding = self._fundings.get(funding_id)
        if not funding:
            raise ValueError(f"Funding {funding_id} not found")

        completed = sum(
            1 for m in funding["milestones"] if m["status"] == "released"
        )
        return {
            "funding_id": funding_id,
            "game_id": funding["game_id"],
            "status": funding["status"],
            "total_amount": funding["total_amount"],
            "released_amount": funding["released_amount"],
            "remaining_amount": funding["remaining_amount"],
            "milestones_completed": completed,
            "milestones_total": len(funding["milestones"]),
            "milestones": funding["milestones"],
        }
