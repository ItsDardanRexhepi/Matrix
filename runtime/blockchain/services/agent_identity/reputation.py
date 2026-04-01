"""
AgentReputation -- reputation scoring for autonomous agents.

Tracks agent actions, outcomes, and computes a 0-100 reputation score
based on success rate, response time, user ratings, and total actions.
"""

from __future__ import annotations

import logging
import math
import time
from typing import Any

logger = logging.getLogger(__name__)

# Reputation factor weights (must sum to 1.0)
DEFAULT_WEIGHTS: dict[str, float] = {
    "success_rate": 0.40,
    "response_time": 0.20,
    "user_ratings": 0.25,
    "consistency": 0.15,
}

# Valid action outcomes
VALID_OUTCOMES = {"success", "failure", "partial", "timeout", "error"}


class AgentReputation:
    """
    Reputation scoring system for autonomous agents.

    Maintains per-agent action history and computes a weighted reputation
    score on a 0-100 scale based on multiple factors.

    Config keys (under config["agent_identity"]):
        reputation_weights  -- dict of factor weights
        min_actions_for_score -- min actions before score is meaningful
    """

    def __init__(self, config: dict[str, Any]) -> None:
        self.config = config
        ai = config.get("agent_identity", {})

        self.weights: dict[str, float] = ai.get("reputation_weights", DEFAULT_WEIGHTS)
        self.min_actions: int = ai.get("min_actions_for_score", 5)

        # agent_id -> reputation data
        self._data: dict[str, dict[str, Any]] = {}
        # agent_id -> list of action records
        self._actions: dict[str, list[dict[str, Any]]] = {}

        logger.info("AgentReputation initialised with weights=%s", self.weights)

    async def initialise(self, agent_id: str) -> None:
        """Initialise reputation data for a newly registered agent."""
        self._data[agent_id] = {
            "total_actions": 0,
            "successes": 0,
            "failures": 0,
            "partials": 0,
            "timeouts": 0,
            "errors": 0,
            "total_response_time_ms": 0.0,
            "rating_sum": 0.0,
            "rating_count": 0,
            "score": 50.0,  # Start at neutral
            "created_at": int(time.time()),
        }
        self._actions[agent_id] = []

    async def get_reputation(self, agent_id: str) -> dict[str, Any]:
        """
        Get the current reputation for an agent.

        Args:
            agent_id: The agent identifier.

        Returns:
            Dict with overall score, factor scores, and summary stats.
        """
        data = self._data.get(agent_id)
        if data is None:
            return {
                "agent_id": agent_id,
                "status": "error",
                "error": "No reputation data found for this agent",
            }

        total = data["total_actions"]
        score = await self._compute_score(agent_id)

        # Factor breakdowns
        factors: dict[str, Any] = {}

        # Success rate factor
        if total > 0:
            success_rate = data["successes"] / total
            factors["success_rate"] = {
                "value": round(success_rate, 4),
                "pct": f"{success_rate * 100:.1f}%",
                "weight": self.weights["success_rate"],
            }
        else:
            factors["success_rate"] = {"value": 0.0, "pct": "0.0%", "weight": self.weights["success_rate"]}

        # Response time factor
        if total > 0:
            avg_response = data["total_response_time_ms"] / total
            # Normalise: <100ms = 1.0, >5000ms = 0.0
            rt_score = max(0.0, min(1.0, 1.0 - (avg_response - 100) / 4900))
            factors["response_time"] = {
                "avg_ms": round(avg_response, 1),
                "score": round(rt_score, 4),
                "weight": self.weights["response_time"],
            }
        else:
            factors["response_time"] = {"avg_ms": 0.0, "score": 0.5, "weight": self.weights["response_time"]}

        # User ratings factor
        if data["rating_count"] > 0:
            avg_rating = data["rating_sum"] / data["rating_count"]
            factors["user_ratings"] = {
                "avg_rating": round(avg_rating, 2),
                "total_ratings": data["rating_count"],
                "score": round(avg_rating / 5.0, 4),  # Normalise 0-5 -> 0-1
                "weight": self.weights["user_ratings"],
            }
        else:
            factors["user_ratings"] = {
                "avg_rating": 0.0,
                "total_ratings": 0,
                "score": 0.5,
                "weight": self.weights["user_ratings"],
            }

        # Consistency factor (low variance in outcomes)
        consistency = self._compute_consistency(agent_id)
        factors["consistency"] = {
            "score": round(consistency, 4),
            "weight": self.weights["consistency"],
        }

        return {
            "agent_id": agent_id,
            "score": round(score, 2),
            "score_label": self._score_label(score),
            "total_actions": total,
            "successes": data["successes"],
            "failures": data["failures"],
            "factors": factors,
            "sufficient_data": total >= self.min_actions,
        }

    async def record_action(
        self,
        agent_id: str,
        action: str,
        outcome: str,
        details: dict[str, Any],
    ) -> dict[str, Any]:
        """
        Record an agent action and its outcome.

        Args:
            agent_id: The agent identifier.
            action: Action type/name performed.
            outcome: Result of the action (success/failure/partial/timeout/error).
            details: Additional details (response_time_ms, user_rating, etc.).

        Returns:
            Dict with updated reputation summary.
        """
        if agent_id not in self._data:
            return {"status": "error", "error": f"No reputation data for agent: {agent_id}"}

        outcome = outcome.lower()
        if outcome not in VALID_OUTCOMES:
            return {
                "status": "error",
                "error": f"Invalid outcome: {outcome}. Valid: {sorted(VALID_OUTCOMES)}",
            }

        data = self._data[agent_id]
        data["total_actions"] += 1

        # Track outcome counts
        outcome_key = {
            "success": "successes",
            "failure": "failures",
            "partial": "partials",
            "timeout": "timeouts",
            "error": "errors",
        }[outcome]
        data[outcome_key] += 1

        # Track response time
        response_time = details.get("response_time_ms", 0.0)
        if response_time > 0:
            data["total_response_time_ms"] += response_time

        # Track user rating (0-5 scale)
        user_rating = details.get("user_rating")
        if user_rating is not None:
            clamped = max(0.0, min(5.0, float(user_rating)))
            data["rating_sum"] += clamped
            data["rating_count"] += 1

        # Record action entry
        action_record = {
            "action": action,
            "outcome": outcome,
            "details": details,
            "timestamp": int(time.time()),
            "action_number": data["total_actions"],
        }
        self._actions.setdefault(agent_id, []).append(action_record)

        # Recompute score
        new_score = await self._compute_score(agent_id)
        data["score"] = new_score

        logger.debug(
            "Action recorded: agent=%s action=%s outcome=%s score=%.2f",
            agent_id, action, outcome, new_score,
        )

        return {
            "status": "recorded",
            "agent_id": agent_id,
            "action": action,
            "outcome": outcome,
            "new_score": round(new_score, 2),
            "total_actions": data["total_actions"],
        }

    async def add_rating(
        self, agent_id: str, rating: float, rater: str | None = None
    ) -> dict[str, Any]:
        """Add a user rating (0-5) for an agent."""
        if agent_id not in self._data:
            return {"status": "error", "error": f"No reputation data for agent: {agent_id}"}

        clamped = max(0.0, min(5.0, float(rating)))
        self._data[agent_id]["rating_sum"] += clamped
        self._data[agent_id]["rating_count"] += 1

        new_score = await self._compute_score(agent_id)
        self._data[agent_id]["score"] = new_score

        return {
            "status": "recorded",
            "agent_id": agent_id,
            "rating": clamped,
            "rater": rater,
            "new_score": round(new_score, 2),
        }

    # ------------------------------------------------------------------
    # Internals
    # ------------------------------------------------------------------

    async def _compute_score(self, agent_id: str) -> float:
        """Compute weighted reputation score (0-100)."""
        data = self._data.get(agent_id)
        if data is None or data["total_actions"] == 0:
            return 50.0  # Neutral for new agents

        total = data["total_actions"]

        # Success rate factor (0-1)
        success_factor = data["successes"] / total if total > 0 else 0.5

        # Response time factor (0-1): <100ms = 1.0, >5000ms = 0.0
        if total > 0 and data["total_response_time_ms"] > 0:
            avg_rt = data["total_response_time_ms"] / total
            rt_factor = max(0.0, min(1.0, 1.0 - (avg_rt - 100) / 4900))
        else:
            rt_factor = 0.5

        # User rating factor (0-1): normalised from 0-5 scale
        if data["rating_count"] > 0:
            rating_factor = (data["rating_sum"] / data["rating_count"]) / 5.0
        else:
            rating_factor = 0.5

        # Consistency factor
        consistency_factor = self._compute_consistency(agent_id)

        # Weighted sum
        raw = (
            self.weights["success_rate"] * success_factor
            + self.weights["response_time"] * rt_factor
            + self.weights["user_ratings"] * rating_factor
            + self.weights["consistency"] * consistency_factor
        )

        # Scale to 0-100
        score = raw * 100.0

        # Apply confidence adjustment for low action counts
        if total < self.min_actions:
            confidence = total / self.min_actions
            score = 50.0 + (score - 50.0) * confidence

        return max(0.0, min(100.0, score))

    def _compute_consistency(self, agent_id: str) -> float:
        """
        Compute consistency factor (0-1) based on outcome variance.

        Agents with consistent success get a higher consistency score.
        """
        actions = self._actions.get(agent_id, [])
        if len(actions) < 2:
            return 0.5

        # Look at recent outcomes (last 50)
        recent = actions[-50:]
        outcomes = [1.0 if a["outcome"] == "success" else 0.0 for a in recent]

        mean = sum(outcomes) / len(outcomes)
        variance = sum((x - mean) ** 2 for x in outcomes) / len(outcomes)
        std_dev = math.sqrt(variance)

        # Low std_dev = high consistency
        return max(0.0, min(1.0, 1.0 - std_dev))

    @staticmethod
    def _score_label(score: float) -> str:
        if score >= 90:
            return "excellent"
        if score >= 75:
            return "good"
        if score >= 50:
            return "average"
        if score >= 25:
            return "poor"
        return "critical"
