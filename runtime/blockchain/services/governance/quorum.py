"""
QuorumLogic — configurable quorum thresholds for the 0pnMatrx governance system.

Default thresholds:
- standard: 10%
- treasury: 20%
- constitutional: 33%
"""

from __future__ import annotations

import logging
from typing import Any

logger = logging.getLogger(__name__)

_DEFAULT_THRESHOLDS: dict[str, float] = {
    "standard": 0.10,
    "treasury": 0.20,
    "constitutional": 0.33,
    "emergency": 0.05,
    "parameter": 0.15,
}


class QuorumLogic:
    """Quorum requirement engine.

    Config keys (under ``config["governance"]``):
        quorum_thresholds (dict): Mapping of proposal_type -> threshold float.
        total_eligible_voters (int): Total addresses eligible to vote (default 1000).
    """

    def __init__(self, config: dict) -> None:
        self._config = config
        g_cfg: dict[str, Any] = config.get("governance", {})

        self._thresholds: dict[str, float] = dict(_DEFAULT_THRESHOLDS)
        custom = g_cfg.get("quorum_thresholds")
        if isinstance(custom, dict):
            self._thresholds.update(custom)

        self._total_eligible: int = int(
            g_cfg.get("total_eligible_voters", 1000)
        )

        logger.info(
            "QuorumLogic initialised (thresholds=%s, eligible=%d).",
            self._thresholds, self._total_eligible,
        )

    @property
    def total_eligible(self) -> int:
        return self._total_eligible

    @total_eligible.setter
    def total_eligible(self, value: int) -> None:
        if value < 0:
            raise ValueError("Total eligible voters cannot be negative")
        self._total_eligible = value

    async def check_quorum(self, proposal_id: str, *, votes: list[dict],
                           proposal_type: str = "standard",
                           voting_model: Any = None) -> dict:
        """Check whether a proposal has met its quorum requirement.

        Args:
            proposal_id: The proposal identifier.
            votes: List of vote records.
            proposal_type: Type of proposal (for threshold lookup).
            voting_model: Optional VotingModel instance for model-specific quorum.

        Returns:
            Dict with quorum status.
        """
        threshold = self._thresholds.get(proposal_type, self._thresholds["standard"])

        if voting_model is not None:
            result = voting_model.check_quorum(votes, self._total_eligible, threshold)
        else:
            unique_voters = len({v["voter"] for v in votes})
            required = int(self._total_eligible * threshold)
            result = {
                "quorum_met": unique_voters >= required,
                "participation": unique_voters,
                "required": required,
                "threshold": threshold,
            }

        result["proposal_id"] = proposal_id
        result["proposal_type"] = proposal_type
        result["total_eligible"] = self._total_eligible

        logger.info(
            "Quorum check: proposal=%s type=%s met=%s",
            proposal_id, proposal_type, result["quorum_met"],
        )
        return result

    async def get_quorum_requirement(self, proposal_type: str) -> dict:
        """Get the quorum requirement for a proposal type.

        Returns:
            Dict with threshold, required count, and total eligible.
        """
        threshold = self._thresholds.get(proposal_type)
        if threshold is None:
            threshold = self._thresholds["standard"]
            logger.warning(
                "Unknown proposal type '%s', using standard threshold.", proposal_type,
            )

        required = int(self._total_eligible * threshold)
        return {
            "proposal_type": proposal_type,
            "threshold": threshold,
            "required_participation": required,
            "total_eligible": self._total_eligible,
        }
