"""
VettingPipeline — reviews games before they are listed on the platform.

Criteria: code quality, fair play mechanics, no exploits.
"""

from __future__ import annotations

import logging
import time
import uuid
from typing import Any

logger = logging.getLogger(__name__)

REVIEW_DECISIONS = {"approve", "reject", "needs_changes"}


class VettingPipeline:
    """Game vetting and review pipeline.

    Config keys (under ``config["gaming"]``):
        required_approvals (int): Number of approvals needed (default 2).
    """

    def __init__(self, config: dict) -> None:
        self._config = config
        g_cfg = config.get("gaming", {})
        self._required_approvals: int = int(
            g_cfg.get("required_approvals", 2)
        )

        # submission_id -> submission record
        self._submissions: dict[str, dict[str, Any]] = {}
        # game_id -> latest submission_id
        self._game_submissions: dict[str, str] = {}

    async def submit_for_review(
        self, game_id: str, submission: dict,
    ) -> dict:
        """Submit a game for review.

        Args:
            game_id: The game to review.
            submission: Dict with ``code_hash``, ``description``,
                        ``changelog``, and optional ``docs_url``.

        Returns:
            Submission record.
        """
        submission_id = f"sub_{uuid.uuid4().hex[:16]}"
        now = int(time.time())

        record: dict[str, Any] = {
            "submission_id": submission_id,
            "game_id": game_id,
            "code_hash": submission.get("code_hash", ""),
            "description": submission.get("description", ""),
            "changelog": submission.get("changelog", ""),
            "docs_url": submission.get("docs_url", ""),
            "status": "pending",
            "reviews": [],
            "approval_count": 0,
            "rejection_count": 0,
            "submitted_at": now,
        }
        self._submissions[submission_id] = record
        self._game_submissions[game_id] = submission_id

        logger.info(
            "Game submitted for review: submission=%s game=%s",
            submission_id, game_id,
        )
        return record

    async def review(
        self,
        submission_id: str,
        reviewer: str,
        decision: str,
        notes: str,
    ) -> dict:
        """Submit a review for a game submission.

        Args:
            submission_id: The submission to review.
            reviewer: Address of the reviewer.
            decision: One of "approve", "reject", "needs_changes".
            notes: Reviewer notes.

        Returns:
            Updated submission record.
        """
        if decision not in REVIEW_DECISIONS:
            raise ValueError(
                f"Invalid decision '{decision}'. "
                f"Must be one of: {', '.join(sorted(REVIEW_DECISIONS))}"
            )

        sub = self._submissions.get(submission_id)
        if not sub:
            raise ValueError(f"Submission {submission_id} not found")

        # Prevent duplicate reviews from the same reviewer
        existing = [r for r in sub["reviews"] if r["reviewer"] == reviewer]
        if existing:
            raise ValueError(
                f"Reviewer {reviewer} has already reviewed submission {submission_id}"
            )

        review_record: dict[str, Any] = {
            "reviewer": reviewer,
            "decision": decision,
            "notes": notes,
            "reviewed_at": int(time.time()),
            "criteria": {
                "code_quality": decision != "reject",
                "fair_play": decision != "reject",
                "no_exploits": decision != "reject",
            },
        }
        sub["reviews"].append(review_record)

        if decision == "approve":
            sub["approval_count"] += 1
        elif decision == "reject":
            sub["rejection_count"] += 1

        # Determine overall status
        if sub["approval_count"] >= self._required_approvals:
            sub["status"] = "approved"
        elif sub["rejection_count"] > 0:
            sub["status"] = "rejected"
        elif decision == "needs_changes":
            sub["status"] = "needs_changes"

        logger.info(
            "Review submitted: submission=%s reviewer=%s decision=%s status=%s",
            submission_id, reviewer, decision, sub["status"],
        )
        return sub

    async def get_review_status(self, game_id: str) -> dict:
        """Get the current review status for a game."""
        submission_id = self._game_submissions.get(game_id)
        if not submission_id:
            return {
                "game_id": game_id,
                "status": "no_submission",
                "message": "No submission found for this game",
            }

        sub = self._submissions.get(submission_id, {})
        return {
            "game_id": game_id,
            "submission_id": submission_id,
            "status": sub.get("status", "unknown"),
            "review_count": len(sub.get("reviews", [])),
            "approval_count": sub.get("approval_count", 0),
            "rejection_count": sub.get("rejection_count", 0),
            "required_approvals": self._required_approvals,
        }
