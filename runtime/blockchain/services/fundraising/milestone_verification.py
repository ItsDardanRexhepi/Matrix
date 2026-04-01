"""
MilestoneVerification — milestone tracking and verification for
community fundraising campaigns.

Verification methods:
- "oracle": external data verification via Component 11 (Oracle Gateway).
- "community_vote": community members vote on milestone completion.

Funds are released per milestone upon successful verification.
"""

from __future__ import annotations

import logging
import time
import uuid
from typing import Any

logger = logging.getLogger(__name__)

_VALID_METHODS = ("oracle", "community_vote")
_VALID_STATUSES = ("pending", "submitted", "verified", "rejected")


class MilestoneVerification:
    """Milestone verification engine for fundraising campaigns.

    Config keys (under ``config["fundraising"]``):
        community_vote_threshold (float): Approval % for community vote (default 0.66).
        oracle_timeout (int): Seconds to wait for oracle response (default 3600).
        min_voters (int): Minimum voters for community verification (default 5).
    """

    def __init__(self, config: dict, oracle_service: Any = None) -> None:
        self._config = config
        f_cfg: dict[str, Any] = config.get("fundraising", {})

        self._vote_threshold: float = float(
            f_cfg.get("community_vote_threshold", 0.66)
        )
        self._oracle_timeout: int = int(f_cfg.get("oracle_timeout", 3600))
        self._min_voters: int = int(f_cfg.get("min_voters", 5))

        self._oracle_service = oracle_service

        # (campaign_id, milestone_idx) -> milestone record
        self._milestones: dict[tuple[str, int], dict[str, Any]] = {}
        # (campaign_id, milestone_idx) -> [votes]
        self._milestone_votes: dict[tuple[str, int], list[dict]] = {}

        logger.info(
            "MilestoneVerification initialised (threshold=%.0f%%, min_voters=%d).",
            self._vote_threshold * 100, self._min_voters,
        )

    async def submit_milestone(
        self, campaign_id: str, milestone_idx: int, proof: dict
    ) -> dict:
        """Submit proof of milestone completion.

        Args:
            campaign_id: The campaign this milestone belongs to.
            milestone_idx: Zero-based milestone index.
            proof: Evidence dict with keys like 'description', 'documents',
                   'metrics', 'links'.

        Returns:
            Milestone submission record.
        """
        if not campaign_id:
            raise ValueError("Campaign ID is required")
        if milestone_idx < 0:
            raise ValueError("Milestone index must be non-negative")
        if not proof:
            raise ValueError("Proof of milestone completion is required")

        key = (campaign_id, milestone_idx)
        existing = self._milestones.get(key)

        if existing and existing["status"] == "verified":
            raise ValueError(
                f"Milestone {milestone_idx} for campaign {campaign_id} "
                f"is already verified"
            )

        now = int(time.time())
        record = {
            "submission_id": str(uuid.uuid4()),
            "campaign_id": campaign_id,
            "milestone_idx": milestone_idx,
            "proof": dict(proof),
            "status": "submitted",
            "submitted_at": now,
            "verified_at": None,
            "verification_method": None,
            "verification_result": None,
        }

        self._milestones[key] = record
        self._milestone_votes[key] = []

        logger.info(
            "Milestone submitted: campaign=%s idx=%d",
            campaign_id, milestone_idx,
        )
        return dict(record)

    async def verify_milestone(
        self, campaign_id: str, milestone_idx: int, method: str
    ) -> dict:
        """Verify a submitted milestone.

        Args:
            campaign_id: Campaign identifier.
            milestone_idx: Milestone index.
            method: "oracle" or "community_vote".

        Returns:
            Verification result.
        """
        if method not in _VALID_METHODS:
            raise ValueError(
                f"Verification method must be one of {_VALID_METHODS}, got '{method}'"
            )

        key = (campaign_id, milestone_idx)
        record = self._milestones.get(key)
        if not record:
            raise ValueError(
                f"Milestone {milestone_idx} for campaign {campaign_id} not found. "
                f"Submit the milestone first."
            )
        if record["status"] not in ("submitted", "pending"):
            raise ValueError(
                f"Milestone is {record['status']}, cannot verify"
            )

        record["verification_method"] = method
        now = int(time.time())

        if method == "oracle":
            result = await self._verify_via_oracle(record)
        else:
            result = await self._verify_via_community_vote(key)

        record["verification_result"] = result

        if result.get("approved"):
            record["status"] = "verified"
            record["verified_at"] = now
            logger.info(
                "Milestone verified: campaign=%s idx=%d method=%s",
                campaign_id, milestone_idx, method,
            )
        else:
            record["status"] = "rejected"
            logger.info(
                "Milestone rejected: campaign=%s idx=%d method=%s reason=%s",
                campaign_id, milestone_idx, method, result.get("reason", ""),
            )

        return {
            "campaign_id": campaign_id,
            "milestone_idx": milestone_idx,
            "method": method,
            "status": record["status"],
            "result": result,
            "verified_at": record["verified_at"],
        }

    def cast_community_vote(
        self, campaign_id: str, milestone_idx: int,
        voter: str, approve: bool,
    ) -> dict:
        """Cast a community verification vote on a milestone.

        Returns:
            Vote record.
        """
        key = (campaign_id, milestone_idx)
        record = self._milestones.get(key)
        if not record:
            raise ValueError(f"Milestone not found")
        if record["status"] != "submitted":
            raise ValueError(f"Milestone is {record['status']}, voting closed")

        votes = self._milestone_votes.setdefault(key, [])

        # Prevent double voting
        if any(v["voter"] == voter for v in votes):
            raise ValueError(f"Voter {voter} has already voted on this milestone")

        vote = {
            "voter": voter,
            "approve": approve,
            "voted_at": int(time.time()),
        }
        votes.append(vote)
        return vote

    async def _verify_via_oracle(self, record: dict) -> dict:
        """Verify milestone using Component 11 (Oracle Gateway)."""
        if self._oracle_service is None:
            logger.warning(
                "Oracle service not available, using proof-based verification."
            )
            # Fallback: check that proof has sufficient documentation
            proof = record.get("proof", {})
            has_docs = bool(proof.get("documents"))
            has_metrics = bool(proof.get("metrics"))
            has_desc = bool(proof.get("description"))

            if has_desc and (has_docs or has_metrics):
                return {
                    "approved": True,
                    "method": "oracle_fallback",
                    "reason": "Sufficient proof documentation provided",
                }
            return {
                "approved": False,
                "method": "oracle_fallback",
                "reason": "Insufficient proof documentation",
            }

        # Use oracle service for external verification
        try:
            proof = record.get("proof", {})
            oracle_result = await self._oracle_service.verify(proof)
            return {
                "approved": oracle_result.get("verified", False),
                "method": "oracle",
                "oracle_response": oracle_result,
            }
        except Exception as exc:
            logger.error("Oracle verification failed: %s", exc)
            return {
                "approved": False,
                "method": "oracle",
                "reason": f"Oracle verification failed: {exc}",
            }

    async def _verify_via_community_vote(
        self, key: tuple[str, int]
    ) -> dict:
        """Verify milestone via community vote tally."""
        votes = self._milestone_votes.get(key, [])

        if len(votes) < self._min_voters:
            return {
                "approved": False,
                "method": "community_vote",
                "reason": (
                    f"Insufficient votes: {len(votes)} of {self._min_voters} "
                    f"minimum required"
                ),
                "votes_cast": len(votes),
                "min_required": self._min_voters,
            }

        approvals = sum(1 for v in votes if v["approve"])
        approval_rate = approvals / len(votes)

        return {
            "approved": approval_rate >= self._vote_threshold,
            "method": "community_vote",
            "approval_rate": approval_rate,
            "approvals": approvals,
            "rejections": len(votes) - approvals,
            "total_votes": len(votes),
            "threshold": self._vote_threshold,
            "reason": (
                "Community approved" if approval_rate >= self._vote_threshold
                else f"Approval rate {approval_rate:.0%} below threshold {self._vote_threshold:.0%}"
            ),
        }

    def get_milestone_status(self, campaign_id: str, milestone_idx: int) -> dict | None:
        """Get the current status of a milestone."""
        key = (campaign_id, milestone_idx)
        record = self._milestones.get(key)
        return dict(record) if record else None
