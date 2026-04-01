"""
Voting models for the 0pnMatrx governance system.

Three models:
- TokenWeightedVoting: vote weight equals token balance.
- OnePersonOneVote: each address gets exactly one vote.
- QuadraticVoting: cost = votes^2, prevents plutocracy.
"""

from __future__ import annotations

import logging
import math
from abc import ABC, abstractmethod
from typing import Any

logger = logging.getLogger(__name__)


class VotingModel(ABC):
    """Base class for voting models."""

    @abstractmethod
    def calculate_weight(self, voter: str, raw_weight: float, context: dict) -> float:
        """Calculate the effective vote weight for a voter."""
        ...

    @abstractmethod
    def tally(self, votes: list[dict]) -> dict:
        """Tally votes and produce results."""
        ...

    @abstractmethod
    def check_quorum(self, votes: list[dict], total_eligible: int, threshold: float) -> dict:
        """Check whether quorum has been met."""
        ...


class TokenWeightedVoting(VotingModel):
    """Vote weight equals the voter's token balance.

    This is the simplest model: if you hold 100 tokens, your vote carries
    100x the weight of someone with 1 token.
    """

    def calculate_weight(self, voter: str, raw_weight: float, context: dict) -> float:
        """Weight is the voter's token balance (passed as raw_weight)."""
        token_balance = context.get("token_balance", raw_weight)
        if token_balance < 0:
            return 0.0
        return float(token_balance)

    def tally(self, votes: list[dict]) -> dict:
        """Tally by summing weights per choice."""
        totals: dict[str, float] = {}
        total_weight = 0.0

        for vote in votes:
            choice = vote["choice"]
            weight = vote.get("effective_weight", 1.0)
            totals[choice] = totals.get(choice, 0.0) + weight
            total_weight += weight

        # Determine winner
        if not totals:
            return {"totals": {}, "winner": None, "total_weight": 0.0}

        winner = max(totals, key=totals.get)  # type: ignore[arg-type]
        return {
            "totals": totals,
            "winner": winner,
            "winner_weight": totals[winner],
            "total_weight": total_weight,
            "model": "token_weighted",
        }

    def check_quorum(self, votes: list[dict], total_eligible: int, threshold: float) -> dict:
        total_weight = sum(v.get("effective_weight", 1.0) for v in votes)
        met = total_weight >= (total_eligible * threshold) if total_eligible > 0 else False
        return {
            "quorum_met": met,
            "participation_weight": total_weight,
            "required_weight": total_eligible * threshold,
            "threshold": threshold,
        }


class OnePersonOneVote(VotingModel):
    """Each address gets exactly one vote regardless of token balance."""

    def calculate_weight(self, voter: str, raw_weight: float, context: dict) -> float:
        """Always returns 1.0."""
        return 1.0

    def tally(self, votes: list[dict]) -> dict:
        """Tally by counting unique voters per choice."""
        totals: dict[str, int] = {}
        voters_seen: set[str] = set()

        for vote in votes:
            voter = vote["voter"]
            if voter in voters_seen:
                continue  # Deduplicate
            voters_seen.add(voter)
            choice = vote["choice"]
            totals[choice] = totals.get(choice, 0) + 1

        if not totals:
            return {"totals": {}, "winner": None, "total_votes": 0}

        winner = max(totals, key=totals.get)  # type: ignore[arg-type]
        total_votes = len(voters_seen)
        return {
            "totals": totals,
            "winner": winner,
            "winner_votes": totals[winner],
            "total_votes": total_votes,
            "model": "one_person_one_vote",
        }

    def check_quorum(self, votes: list[dict], total_eligible: int, threshold: float) -> dict:
        unique_voters = len({v["voter"] for v in votes})
        required = math.ceil(total_eligible * threshold) if total_eligible > 0 else 1
        return {
            "quorum_met": unique_voters >= required,
            "participation": unique_voters,
            "required": required,
            "threshold": threshold,
        }


class QuadraticVoting(VotingModel):
    """Quadratic voting: cost of N votes = N^2 credits.

    This prevents plutocracy by making each additional vote progressively
    more expensive. A voter with 100 credits can cast 10 votes (10^2=100).
    """

    def calculate_weight(self, voter: str, raw_weight: float, context: dict) -> float:
        """Weight = sqrt(credits spent).

        raw_weight is the number of credits the voter wants to spend.
        """
        credits = max(0.0, float(raw_weight))
        return math.sqrt(credits)

    def tally(self, votes: list[dict]) -> dict:
        """Tally using quadratic vote weights."""
        totals: dict[str, float] = {}
        total_weight = 0.0

        for vote in votes:
            choice = vote["choice"]
            weight = vote.get("effective_weight", 1.0)
            totals[choice] = totals.get(choice, 0.0) + weight
            total_weight += weight

        if not totals:
            return {"totals": {}, "winner": None, "total_weight": 0.0}

        winner = max(totals, key=totals.get)  # type: ignore[arg-type]
        return {
            "totals": totals,
            "winner": winner,
            "winner_weight": totals[winner],
            "total_weight": total_weight,
            "model": "quadratic",
        }

    def check_quorum(self, votes: list[dict], total_eligible: int, threshold: float) -> dict:
        unique_voters = len({v["voter"] for v in votes})
        required = math.ceil(total_eligible * threshold) if total_eligible > 0 else 1
        return {
            "quorum_met": unique_voters >= required,
            "participation": unique_voters,
            "required": required,
            "threshold": threshold,
        }


# Registry mapping model names to classes
VOTING_MODELS: dict[str, type[VotingModel]] = {
    "token_weighted": TokenWeightedVoting,
    "one_person_one_vote": OnePersonOneVote,
    "quadratic": QuadraticVoting,
}


def get_voting_model(name: str) -> VotingModel:
    """Instantiate a voting model by name.

    Raises:
        ValueError: If the model name is unknown.
    """
    cls = VOTING_MODELS.get(name.lower())
    if cls is None:
        raise ValueError(
            f"Unknown voting model '{name}'; choose from {list(VOTING_MODELS)}"
        )
    return cls()
