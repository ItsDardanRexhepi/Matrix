from __future__ import annotations

"""
SchellingPoint — commit-reveal voting mechanism for dispute resolution.

Jurors submit a hash of their vote (commit phase) then reveal the
actual vote and justification. This prevents copying — each juror must
form an independent opinion. Jurors who vote with the majority are
rewarded from the losing party's stake; jurors voting against the
majority lose a portion of their own stake.
"""

import hashlib
import logging
import time
from enum import Enum
from typing import Any

logger = logging.getLogger(__name__)

# Fraction of a juror's stake that is slashed for voting against the majority.
MINORITY_SLASH_RATIO: float = 0.10


class VotePhase(str, Enum):
    COMMIT = "commit"
    REVEAL = "reveal"
    TALLIED = "tallied"


class SchellingPoint:
    """Commit-reveal Schelling-point voting for dispute outcomes."""

    def __init__(self, config: dict | None = None) -> None:
        self.config = config or {}
        self._slash_ratio = float(
            self.config.get("dispute_resolution", {}).get(
                "minority_slash_ratio", MINORITY_SLASH_RATIO
            )
        )
        # dispute_id -> voting state
        self._votes: dict[str, dict[str, Any]] = {}

    # ------------------------------------------------------------------
    # Commit phase
    # ------------------------------------------------------------------

    async def submit_vote(
        self,
        dispute_id: str,
        juror: str,
        vote: str,
        justification: str,
    ) -> dict:
        """Submit a vote commitment for a dispute.

        The actual vote and justification are hashed together; only the
        hash is stored during the commit phase so other jurors cannot
        see how anyone voted.

        Args:
            dispute_id: Dispute being voted on.
            juror: Address of the voting juror.
            vote: The juror's verdict (e.g. ``"claimant"`` or ``"respondent"``).
            justification: Free-text reasoning.

        Returns:
            Dict with the commit hash and timestamp.

        Raises:
            ValueError: If the juror has already committed for this dispute.
        """
        if vote not in ("claimant", "respondent"):
            raise ValueError(f"Vote must be 'claimant' or 'respondent', got '{vote}'")

        state = self._ensure_state(dispute_id)

        if state["phase"] not in (VotePhase.COMMIT, VotePhase.REVEAL):
            raise ValueError(f"Voting is closed for dispute {dispute_id}")

        if juror in state["commits"]:
            raise ValueError(f"Juror {juror} already committed for dispute {dispute_id}")

        commit_hash = self._hash_vote(dispute_id, juror, vote, justification)

        state["commits"][juror] = {
            "commit_hash": commit_hash,
            "committed_at": time.time(),
        }

        # Keep the plaintext privately for the reveal phase
        state["_secrets"][juror] = {
            "vote": vote,
            "justification": justification,
        }

        logger.info(
            "Vote committed — dispute=%s juror=%s hash=%s",
            dispute_id,
            juror,
            commit_hash[:16],
        )
        return {
            "dispute_id": dispute_id,
            "juror": juror,
            "commit_hash": commit_hash,
            "committed_at": state["commits"][juror]["committed_at"],
        }

    # ------------------------------------------------------------------
    # Reveal phase
    # ------------------------------------------------------------------

    async def reveal_votes(self, dispute_id: str) -> dict:
        """Transition from commit to reveal phase and expose all votes.

        In a production system each juror would individually reveal by
        re-submitting their plaintext vote so the contract can verify the
        hash. Here we auto-reveal from stored secrets for simplicity.

        Returns:
            Dict with all revealed votes and verification status.

        Raises:
            ValueError: If no commits exist for this dispute.
        """
        state = self._ensure_state(dispute_id)

        if not state["commits"]:
            raise ValueError(f"No votes committed for dispute {dispute_id}")

        if state["phase"] == VotePhase.TALLIED:
            raise ValueError(f"Votes already tallied for dispute {dispute_id}")

        state["phase"] = VotePhase.REVEAL

        reveals: dict[str, dict[str, Any]] = {}
        for juror, secret in state["_secrets"].items():
            expected_hash = self._hash_vote(
                dispute_id, juror, secret["vote"], secret["justification"]
            )
            stored_hash = state["commits"][juror]["commit_hash"]
            verified = expected_hash == stored_hash

            reveals[juror] = {
                "vote": secret["vote"],
                "justification": secret["justification"],
                "verified": verified,
            }

        state["reveals"] = reveals
        logger.info(
            "Votes revealed — dispute=%s jurors=%d", dispute_id, len(reveals)
        )
        return {
            "dispute_id": dispute_id,
            "phase": VotePhase.REVEAL.value,
            "reveals": reveals,
        }

    # ------------------------------------------------------------------
    # Tally / outcome
    # ------------------------------------------------------------------

    async def calculate_outcome(self, dispute_id: str) -> dict:
        """Tally revealed votes and determine the outcome.

        Majority wins. Jurors with the majority share the reward pool;
        minority jurors are slashed.

        Returns:
            Dict containing the winner, vote counts, and reward/slash
            breakdown per juror.

        Raises:
            ValueError: If votes have not been revealed yet.
        """
        state = self._ensure_state(dispute_id)

        if not state.get("reveals"):
            raise ValueError(f"Votes not revealed for dispute {dispute_id}")

        if state["phase"] == VotePhase.TALLIED:
            return state["outcome"]

        # Count votes
        tally: dict[str, int] = {"claimant": 0, "respondent": 0}
        for reveal in state["reveals"].values():
            if reveal["verified"]:
                tally[reveal["vote"]] += 1

        winner = "claimant" if tally["claimant"] >= tally["respondent"] else "respondent"

        # Build per-juror reward / slash table
        juror_results: dict[str, dict[str, Any]] = {}
        for juror, reveal in state["reveals"].items():
            voted_with_majority = reveal["vote"] == winner and reveal["verified"]
            juror_results[juror] = {
                "vote": reveal["vote"],
                "voted_with_majority": voted_with_majority,
                "reward": "share_of_loser_stake" if voted_with_majority else None,
                "slashed": self._slash_ratio if not voted_with_majority else 0.0,
            }

        outcome = {
            "dispute_id": dispute_id,
            "winner": winner,
            "tally": tally,
            "total_votes": sum(tally.values()),
            "juror_results": juror_results,
            "resolved_at": time.time(),
        }
        state["outcome"] = outcome
        state["phase"] = VotePhase.TALLIED

        logger.info(
            "Outcome calculated — dispute=%s winner=%s tally=%s",
            dispute_id,
            winner,
            tally,
        )
        return outcome

    # ------------------------------------------------------------------
    # Helpers
    # ------------------------------------------------------------------

    def _ensure_state(self, dispute_id: str) -> dict[str, Any]:
        if dispute_id not in self._votes:
            self._votes[dispute_id] = {
                "phase": VotePhase.COMMIT,
                "commits": {},
                "reveals": {},
                "_secrets": {},
                "outcome": None,
            }
        return self._votes[dispute_id]

    @staticmethod
    def _hash_vote(
        dispute_id: str, juror: str, vote: str, justification: str
    ) -> str:
        payload = f"{dispute_id}|{juror}|{vote}|{justification}"
        return hashlib.sha256(payload.encode()).hexdigest()
