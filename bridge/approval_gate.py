"""
Approval Gate — blocks all component deployments until Dardan approves.

No component can be deployed to the public 0pnMatrx runtime without explicit
approval from Dardan via Telegram. This module:

    1. Sends a formatted approval request to Dardan's Telegram
    2. Polls for a response (approve / reject)
    3. Records the decision in the manifest

The approval gate is NON-OPTIONAL. There is no bypass, no auto-approve,
and no timeout-to-approve. If approval is not received, the component
stays in staging indefinitely.
"""

from __future__ import annotations

import asyncio
import logging
import time
from dataclasses import dataclass
from enum import Enum
from typing import Any

from bridge import DARDAN_TELEGRAM_ID
from bridge.exporter import ExportBundle
from bridge.sanitizer import SanitizationResult

logger = logging.getLogger(__name__)


class ApprovalStatus(str, Enum):
    PENDING = "pending"
    APPROVED = "approved"
    REJECTED = "rejected"
    EXPIRED = "expired"


@dataclass
class ApprovalDecision:
    """Records Dardan's approval or rejection."""
    component_name: str
    version: str
    status: ApprovalStatus
    decided_at: float | None = None
    reason: str = ""
    request_id: str = ""

    def to_dict(self) -> dict[str, Any]:
        return {
            "component_name": self.component_name,
            "version": self.version,
            "status": self.status.value,
            "decided_at": self.decided_at,
            "reason": self.reason,
            "request_id": self.request_id,
        }


class ApprovalGate:
    """Blocks deployment until Dardan explicitly approves via Telegram.

    Usage::

        gate = ApprovalGate(telegram_notifier=notifier)
        decision = await gate.request_approval(bundle, sanitizer_result)
        if decision.status == ApprovalStatus.APPROVED:
            # proceed to deploy
            ...
    """

    POLL_INTERVAL = 10          # seconds between Telegram polls
    MAX_WAIT = 3600             # 1 hour max wait (then mark as expired)

    def __init__(self, telegram_notifier=None):
        """Initialize with an optional TelegramNotifier instance.

        If no notifier is provided, approval requests are logged but
        cannot be delivered. Manual approval via set_decision() is
        still supported.
        """
        self.notifier = telegram_notifier
        self._pending: dict[str, ApprovalDecision] = {}

    async def request_approval(
        self,
        bundle: ExportBundle,
        sanitizer_result: SanitizationResult,
    ) -> ApprovalDecision:
        """Send approval request and wait for a decision.

        Args:
            bundle: The component bundle awaiting approval.
            sanitizer_result: Result from the sanitizer stage.

        Returns:
            ApprovalDecision with the final status.
        """
        request_id = f"approval_{bundle.component_name}_{bundle.version}_{int(time.time())}"

        decision = ApprovalDecision(
            component_name=bundle.component_name,
            version=bundle.version,
            status=ApprovalStatus.PENDING,
            request_id=request_id,
        )
        self._pending[request_id] = decision

        # Build human-readable summary
        summary = self._build_summary(bundle, sanitizer_result)

        # Send to Dardan via Telegram
        if self.notifier:
            await self.notifier.send_approval_request(
                chat_id=DARDAN_TELEGRAM_ID,
                message=summary,
                request_id=request_id,
            )
            logger.info("Approval request sent to Dardan: %s", request_id)
        else:
            logger.warning(
                "No Telegram notifier configured. Approval request logged "
                "but not delivered: %s\n%s", request_id, summary,
            )

        # Poll for response
        start = time.time()
        while decision.status == ApprovalStatus.PENDING:
            elapsed = time.time() - start
            if elapsed >= self.MAX_WAIT:
                decision.status = ApprovalStatus.EXPIRED
                decision.reason = f"No response after {self.MAX_WAIT}s"
                logger.warning("Approval request expired: %s", request_id)
                break
            await asyncio.sleep(self.POLL_INTERVAL)

        return decision

    def set_decision(
        self,
        request_id: str,
        approved: bool,
        reason: str = "",
    ) -> ApprovalDecision | None:
        """Manually set a decision (called from Telegram callback or API).

        Args:
            request_id: The approval request ID.
            approved: True to approve, False to reject.
            reason: Optional reason for the decision.

        Returns:
            The updated ApprovalDecision, or None if request_id not found.
        """
        decision = self._pending.get(request_id)
        if not decision:
            logger.warning("Unknown approval request: %s", request_id)
            return None

        decision.status = ApprovalStatus.APPROVED if approved else ApprovalStatus.REJECTED
        decision.decided_at = time.time()
        decision.reason = reason

        logger.info(
            "Approval decision for %s: %s (reason: %s)",
            decision.component_name, decision.status.value, reason or "none",
        )
        return decision

    def get_pending(self) -> list[ApprovalDecision]:
        """Return all pending approval requests."""
        return [d for d in self._pending.values() if d.status == ApprovalStatus.PENDING]

    def _build_summary(
        self,
        bundle: ExportBundle,
        sanitizer_result: SanitizationResult,
    ) -> str:
        """Build a human-readable summary for the Telegram message."""
        sanitizer_status = "CLEAN" if sanitizer_result.is_clean else "VIOLATIONS FOUND"
        violation_text = ""
        if not sanitizer_result.is_clean:
            violation_text = "\n\nViolations:\n"
            for v in sanitizer_result.violations[:10]:
                violation_text += f"  - [{v['category']}] {v['pattern']} in {v['file']}:{v['line']}\n"
            if len(sanitizer_result.violations) > 10:
                violation_text += f"  ... and {len(sanitizer_result.violations) - 10} more\n"

        return (
            f"Bridge Export Approval Request\n"
            f"{'=' * 40}\n"
            f"Component: {bundle.component_name}\n"
            f"Version:   {bundle.version}\n"
            f"Files:     {bundle.file_count}\n"
            f"Hash:      {bundle.content_hash[:16]}...\n"
            f"Sanitizer: {sanitizer_status}\n"
            f"{violation_text}\n"
            f"Reply /approve or /reject to this message."
        )
