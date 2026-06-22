"""
Approval Gate — blocks all component deployments until the OWNER approves.

No component crosses the private->public bridge into the 0pnMatrx runtime without
the OTP-verified owner's explicit approval. Telegram is gone; approval is now the
same phone-OTP owner-verification used everywhere else (runtime/security/owner.py).

This module:
    1. Delivers a formatted approval request to the owner (SMS, best-effort)
    2. Waits for the owner to approve by submitting a valid OTP code
    3. Records the decision in the manifest

The approval gate is NON-OPTIONAL. There is no bypass, no auto-approve, and no
timeout-to-approve: if approval is not received, the component stays in staging.
Approving is an owner-gated action ("approve_component") — it requires the bound
owner identity (Apple ID + wallet) AND a fresh OTP. Rejecting is always allowed.
"""

from __future__ import annotations

import asyncio
import logging
import time
from dataclasses import dataclass
from enum import Enum
from typing import Any

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
    """Records the owner's approval or rejection."""
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
    """Blocks deployment until the OTP-verified owner explicitly approves.

    Usage::

        gate = ApprovalGate(owner_verification=owner, notifier=dispatcher)
        decision = await gate.request_approval(bundle, result,
                                               owner_apple_id=aid, owner_wallet=w)
        # owner submits an OTP code out-of-band:
        await gate.approve(decision.request_id, aid, w, otp_code)
    """

    POLL_INTERVAL = 5           # seconds between decision checks
    MAX_WAIT = 3600             # 1 hour max wait (then mark as expired)

    def __init__(self, owner_verification=None, notifier=None):
        """Args:
            owner_verification: an ``OwnerVerification`` (OTP gating). Without it,
                ``approve`` cannot authorize — the gate is effectively sealed.
            notifier: optional notification dispatcher to deliver the summary to
                the owner (SMS). If absent, the request is logged only.
        """
        self.owner = owner_verification
        self.notifier = notifier
        self._pending: dict[str, ApprovalDecision] = {}

    async def request_approval(
        self,
        bundle: ExportBundle,
        sanitizer_result: SanitizationResult,
        *,
        owner_apple_id: str | None = None,
        owner_wallet: str | None = None,
    ) -> ApprovalDecision:
        """Deliver an approval request to the owner and wait for a decision."""
        request_id = f"approval_{bundle.component_name}_{bundle.version}_{int(time.time())}"
        decision = ApprovalDecision(
            component_name=bundle.component_name,
            version=bundle.version,
            status=ApprovalStatus.PENDING,
            request_id=request_id,
        )
        self._pending[request_id] = decision

        summary = self._build_summary(bundle, sanitizer_result)

        # Deliver the summary to the owner (SMS), best-effort.
        if self.notifier is not None:
            try:
                await self.notifier.broadcast(summary, level="critical", channels=["sms"])
            except Exception:
                logger.exception("Failed to deliver approval summary to owner")
        else:
            logger.warning("No notifier configured. Approval request logged only:\n%s", summary)

        # Start an owner OTP so the owner can approve with a code.
        if self.owner is not None and owner_apple_id and owner_wallet:
            try:
                await self.owner.start_owner_otp(owner_apple_id, owner_wallet)
            except Exception:
                logger.exception("Failed to start owner OTP for approval")

        logger.info("Approval request pending owner OTP: %s", request_id)

        start = time.time()
        while decision.status == ApprovalStatus.PENDING:
            if time.time() - start >= self.MAX_WAIT:
                decision.status = ApprovalStatus.EXPIRED
                decision.reason = f"No response after {self.MAX_WAIT}s"
                logger.warning("Approval request expired: %s", request_id)
                break
            await asyncio.sleep(self.POLL_INTERVAL)

        return decision

    async def approve(
        self,
        request_id: str,
        apple_id: str | None,
        wallet: str | None,
        otp_code: str | None,
        *,
        device_assertion: dict | None = None,
    ) -> ApprovalDecision | None:
        """Approve a pending request — verified owner only.

        Requires the bound owner identity AND a fresh THIRD factor. The third factor
        is biometric-preferred: a Secure-Enclave **device assertion** (App Attest)
        when present, else the SMS **OTP** fallback. The private OwnerVerification
        decides which applies; this gate just forwards both. Returns the updated
        decision on success, or the still-PENDING decision (unchanged) if
        authorization fails.
        """
        decision = self._pending.get(request_id)
        if not decision:
            logger.warning("Unknown approval request: %s", request_id)
            return None
        if self.owner is None:
            logger.error("No OwnerVerification configured — cannot approve.")
            return decision

        auth = await self.owner.authorize_owner_action(
            "approve_component", apple_id, wallet, otp_code,
            device_assertion=device_assertion,
        )
        if not auth.get("authorized"):
            logger.warning("Approval denied for %s: %s", request_id, auth.get("reason"))
            decision.reason = auth.get("reason", "Owner authorization failed.")
            return decision  # stays PENDING

        decision.status = ApprovalStatus.APPROVED
        decision.decided_at = time.time()
        decision.reason = "Approved by OTP-verified owner."
        logger.info("Approved by owner: %s", decision.component_name)
        return decision

    def reject(self, request_id: str, reason: str = "") -> ApprovalDecision | None:
        """Reject a pending request. Always allowed (rejecting is the safe path)."""
        decision = self._pending.get(request_id)
        if not decision:
            return None
        decision.status = ApprovalStatus.REJECTED
        decision.decided_at = time.time()
        decision.reason = reason or "Rejected."
        logger.info("Rejected: %s (%s)", decision.component_name, decision.reason)
        return decision

    def get_pending(self) -> list[ApprovalDecision]:
        return [d for d in self._pending.values() if d.status == ApprovalStatus.PENDING]

    def _build_summary(
        self,
        bundle: ExportBundle,
        sanitizer_result: SanitizationResult,
    ) -> str:
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
            f"To APPROVE, submit your owner OTP code. To reject, decline."
        )
