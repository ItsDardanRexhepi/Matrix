"""Content Moderation - Component 28.

Filters hate speech, spam, harassment, and illegal content.
Ban records are TIME-CRITICAL attestations via Component 8.
Links to Component 29 for privacy/deletion requests.
"""

from __future__ import annotations

import logging
import time
import uuid
from typing import Any

logger = logging.getLogger(__name__)

# Keyword-based content filters
FILTER_CATEGORIES: dict[str, list[str]] = {
    "hate_speech": [
        "racial slur", "ethnic slur", "hate group", "white supremacy",
        "nazi", "genocide advocate",
    ],
    "spam": [
        "buy now!!!", "click here free", "act now limited time",
        "congratulations you won", "nigerian prince", "wire transfer",
        "double your crypto",
    ],
    "harassment": [
        "kill yourself", "death threat", "i will find you",
        "doxxing", "swatting",
    ],
    "illegal_content": [
        "child exploitation", "csam", "human trafficking",
        "money laundering instructions", "terrorist recruitment",
    ],
}


class ContentModeration:
    """Content moderation with keyword scanning and report management.

    Filters content against prohibited categories and manages user reports.
    Ban records are intended to be time-critical attestations via Component 8.
    """

    def __init__(self, config: dict[str, Any] | None = None) -> None:
        self.config = config or {}
        self._reports: dict[str, dict] = {}
        self._bans: dict[str, dict] = {}  # address -> ban record
        self._custom_filters: list[str] = self.config.get("custom_content_filters", [])
        logger.info(
            "ContentModeration initialised with %d filter categories",
            len(FILTER_CATEGORIES),
        )

    def _scan_content(self, content: str) -> list[dict]:
        """Scan content against all filter categories."""
        matches = []
        content_lower = content.lower()

        for category, keywords in FILTER_CATEGORIES.items():
            for keyword in keywords:
                if keyword in content_lower:
                    matches.append({"category": category, "keyword": keyword})

        for keyword in self._custom_filters:
            if keyword.lower() in content_lower:
                matches.append({"category": "custom_filter", "keyword": keyword})

        return matches

    async def check_content(self, content: str, content_type: str) -> dict:
        """Check content for policy violations.

        Args:
            content: The text to check.
            content_type: Type of content ('post', 'message', 'bio', 'display_name', etc.).

        Returns:
            Dict with action ('allow', 'warn', 'block'), reason, and violations.
        """
        if not content:
            return {
                "action": "allow",
                "reason": None,
                "violations": [],
                "content_type": content_type,
                "checked_at": time.time(),
            }

        violations = self._scan_content(content)

        if not violations:
            return {
                "action": "allow",
                "reason": None,
                "violations": [],
                "content_type": content_type,
                "checked_at": time.time(),
            }

        # Immediate block categories
        block_categories = {"hate_speech", "illegal_content", "harassment"}
        blocking_violations = [v for v in violations if v["category"] in block_categories]

        if blocking_violations:
            reason = (
                f"Content blocked: violates policy on "
                f"{', '.join(set(v['category'] for v in blocking_violations))}"
            )
            logger.warning("Content BLOCKED (type=%s): %s", content_type, reason)
            return {
                "action": "block",
                "reason": reason,
                "violations": blocking_violations,
                "content_type": content_type,
                "checked_at": time.time(),
            }

        # Warn for soft violations (spam, custom)
        reason = f"Content flagged: {', '.join(set(v['category'] for v in violations))}"
        return {
            "action": "warn",
            "reason": reason,
            "violations": violations,
            "content_type": content_type,
            "checked_at": time.time(),
        }

    async def report_content(self, content_id: str, reporter: str, reason: str) -> dict:
        """Report content for moderation review.

        Args:
            content_id: ID of the content being reported.
            reporter: Reporter's wallet address.
            reason: Reason for the report.

        Returns:
            The report record.
        """
        if not content_id:
            raise ValueError("content_id is required")
        if not reporter:
            raise ValueError("reporter is required")
        if not reason:
            raise ValueError("reason is required")

        report_id = f"report_{uuid.uuid4().hex[:12]}"
        now = time.time()

        report = {
            "report_id": report_id,
            "content_id": content_id,
            "reporter": reporter,
            "reason": reason,
            "status": "pending",
            "created_at": now,
            "reviewed_at": None,
            "reviewer": None,
            "action_taken": None,
        }

        self._reports[report_id] = report
        logger.info("Content %s reported by %s: %s", content_id, reporter, reason)
        return report

    async def review_report(self, report_id: str, reviewer: str, action: str) -> dict:
        """Review a content report and take action.

        Args:
            report_id: The report to review.
            reviewer: Reviewer's wallet address.
            action: Action to take ('dismiss', 'warn_user', 'remove_content', 'ban_user').

        Returns:
            The updated report with action details.
        """
        valid_actions = {"dismiss", "warn_user", "remove_content", "ban_user"}
        if action not in valid_actions:
            raise ValueError(f"Invalid action '{action}'. Must be one of: {valid_actions}")
        if not reviewer:
            raise ValueError("reviewer is required")

        report = self._reports.get(report_id)
        if not report:
            raise ValueError(f"Report '{report_id}' not found")
        if report["status"] != "pending":
            raise ValueError(f"Report already reviewed (status={report['status']})")

        now = time.time()
        report["status"] = "reviewed"
        report["reviewed_at"] = now
        report["reviewer"] = reviewer
        report["action_taken"] = action

        result = {**report}

        if action == "ban_user":
            # Create ban attestation (TIME-CRITICAL, links to Component 8)
            ban_id = f"ban_{uuid.uuid4().hex[:12]}"
            ban_record = {
                "ban_id": ban_id,
                "report_id": report_id,
                "content_id": report["content_id"],
                "banned_at": now,
                "banned_by": reviewer,
                "reason": report["reason"],
                "attestation_pending": True,
                "component_8_attestation_uid": None,
            }
            # In production, immediately create attestation via Component 8
            result["ban_record"] = ban_record
            logger.warning(
                "User ban initiated via report %s (ban_id=%s, pending attestation)",
                report_id, ban_id,
            )

        if action == "remove_content":
            # Link to Component 29 for deletion
            result["deletion_note"] = (
                "Content removed. User may request full data deletion "
                "via Component 29 (Privacy Protection)."
            )

        logger.info("Report %s reviewed by %s: action=%s", report_id, reviewer, action)
        return result
