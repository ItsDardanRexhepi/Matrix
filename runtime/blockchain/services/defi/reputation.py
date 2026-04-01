"""
LenderReputation — track lender and borrower reliability scores.

Scores are computed from historical events and decay over time to
ensure recent behaviour is weighted more heavily.

Event types and their score impacts:
  - loan_funded: +10
  - loan_repaid_on_time: +15
  - loan_late: -10
  - loan_defaulted: -30
"""

from __future__ import annotations

import logging
import math
import time
from typing import Any

logger = logging.getLogger(__name__)

# Event score impacts
_EVENT_SCORES: dict[str, int] = {
    "loan_funded": 10,
    "loan_repaid_on_time": 15,
    "loan_late": -10,
    "loan_defaulted": -30,
}

# Score bounds
_MIN_SCORE = 0
_MAX_SCORE = 1000
_INITIAL_SCORE = 500

# Decay half-life in days (older events matter less)
_DECAY_HALF_LIFE_DAYS = 90


class LenderReputation:
    """Track lender and borrower reliability scores.

    Parameters
    ----------
    config : dict
        Platform config.  Reads:
        - ``defi.reputation.initial_score`` (default 500)
        - ``defi.reputation.decay_half_life_days`` (default 90)
        - ``defi.reputation.event_scores`` — override impact values
    """

    def __init__(self, config: dict) -> None:
        self._config = config
        rep_cfg = config.get("defi", {}).get("reputation", {})

        self._initial_score: int = int(rep_cfg.get("initial_score", _INITIAL_SCORE))
        self._decay_half_life: float = float(
            rep_cfg.get("decay_half_life_days", _DECAY_HALF_LIFE_DAYS)
        )
        self._event_scores: dict[str, int] = {
            **_EVENT_SCORES,
            **rep_cfg.get("event_scores", {}),
        }

        # Storage: {address: {"events": [...], "cached_score": float}}
        self._profiles: dict[str, dict[str, Any]] = {}

    async def get_score(self, address: str) -> dict[str, Any]:
        """Get the reputation score for an address.

        Returns
        -------
        dict
            Keys: ``address``, ``score``, ``tier``, ``total_events``,
            ``positive_events``, ``negative_events``, ``event_history``.
        """
        profile = self._profiles.get(address)
        if profile is None:
            return {
                "address": address,
                "score": self._initial_score,
                "tier": self._score_to_tier(self._initial_score),
                "total_events": 0,
                "positive_events": 0,
                "negative_events": 0,
                "event_history": [],
            }

        score = self._compute_score(profile)
        events = profile.get("events", [])
        positive = sum(1 for e in events if self._event_scores.get(e["event"], 0) > 0)
        negative = sum(1 for e in events if self._event_scores.get(e["event"], 0) < 0)

        return {
            "address": address,
            "score": round(score, 2),
            "tier": self._score_to_tier(score),
            "total_events": len(events),
            "positive_events": positive,
            "negative_events": negative,
            "event_history": events[-20:],  # last 20 events
        }

    async def update_score(
        self, address: str, event: str
    ) -> dict[str, Any]:
        """Record an event and update the reputation score.

        Parameters
        ----------
        address : str
            Wallet address.
        event : str
            Event type: one of ``loan_funded``, ``loan_repaid_on_time``,
            ``loan_late``, ``loan_defaulted``.

        Returns
        -------
        dict
            Updated score info.
        """
        if event not in self._event_scores:
            raise ValueError(
                f"Unknown event '{event}'. Valid events: "
                f"{', '.join(sorted(self._event_scores))}"
            )

        profile = self._profiles.setdefault(address, {
            "events": [],
            "created_at": int(time.time()),
        })

        event_record: dict[str, Any] = {
            "event": event,
            "impact": self._event_scores[event],
            "timestamp": int(time.time()),
        }
        profile["events"].append(event_record)

        new_score = self._compute_score(profile)

        logger.info(
            "Reputation updated: address=%s event=%s impact=%+d new_score=%.1f tier=%s",
            address, event, self._event_scores[event],
            new_score, self._score_to_tier(new_score),
        )

        return {
            "address": address,
            "event": event,
            "impact": self._event_scores[event],
            "new_score": round(new_score, 2),
            "tier": self._score_to_tier(new_score),
        }

    async def get_top_lenders(self, limit: int = 20) -> list[dict[str, Any]]:
        """Return top-rated lenders by score."""
        scored: list[tuple[str, float]] = []
        for address, profile in self._profiles.items():
            score = self._compute_score(profile)
            scored.append((address, score))

        scored.sort(key=lambda x: x[1], reverse=True)

        results: list[dict[str, Any]] = []
        for address, score in scored[:limit]:
            results.append({
                "address": address,
                "score": round(score, 2),
                "tier": self._score_to_tier(score),
            })
        return results

    async def reset_score(self, address: str) -> dict[str, Any]:
        """Reset a user's reputation (admin action)."""
        if address in self._profiles:
            del self._profiles[address]
        logger.info("Reputation reset for: %s", address)
        return {
            "address": address,
            "score": self._initial_score,
            "tier": self._score_to_tier(self._initial_score),
            "status": "reset",
        }

    # ── Internal ──────────────────────────────────────────────────────

    def _compute_score(self, profile: dict[str, Any]) -> float:
        """Compute time-decayed reputation score from event history."""
        now = time.time()
        score = float(self._initial_score)

        for event_record in profile.get("events", []):
            impact = event_record["impact"]
            age_days = (now - event_record["timestamp"]) / 86400

            # Exponential decay: impact * 2^(-age / half_life)
            decay_factor = math.pow(2, -age_days / self._decay_half_life)
            score += impact * decay_factor

        # Clamp to bounds
        return max(_MIN_SCORE, min(_MAX_SCORE, score))

    @staticmethod
    def _score_to_tier(score: float) -> str:
        """Map a numeric score to a human-readable tier."""
        if score >= 850:
            return "platinum"
        if score >= 700:
            return "gold"
        if score >= 550:
            return "silver"
        if score >= 400:
            return "bronze"
        return "unrated"
