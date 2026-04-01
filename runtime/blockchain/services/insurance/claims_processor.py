"""
ClaimsProcessor — processes, approves, and denies insurance claims.

Auto-approves parametric claims when oracle data confirms the trigger
condition.  Denied claims can be routed to Component 30 (dispute
resolution).
"""

from __future__ import annotations

import logging
import time
from typing import Any

logger = logging.getLogger(__name__)


class ClaimsProcessor:
    """Processes insurance claims.

    Auto-approval is the default path for parametric insurance:
    when the oracle data confirms the trigger condition, the claim
    is approved without manual intervention.

    Args:
        config: Platform configuration dict.
        reserve_fund: ReserveFund instance for payout accounting.
    """

    def __init__(self, config: dict, reserve_fund: Any) -> None:
        self._config = config
        self._reserve_fund = reserve_fund

        # claim_id -> processing record
        self._processed: dict[str, dict[str, Any]] = {}

    async def process_claim(
        self,
        claim_id: str,
        claim: dict[str, Any],
        policy: dict[str, Any],
    ) -> dict:
        """Process a claim by verifying trigger data against the policy.

        If the trigger data satisfies the parametric condition, the claim
        is auto-approved and a payout is issued from the reserve fund.

        Args:
            claim_id: Unique claim identifier.
            claim: Claim record (includes trigger_data).
            policy: The associated policy record.

        Returns:
            Updated claim fields (status, payout_amount, etc.).
        """
        trigger_data = claim.get("trigger_data", {})

        # Validate trigger data is present
        if not trigger_data:
            return await self.deny_claim(
                claim_id, "No trigger data provided",
            )

        # Verify the parametric condition
        verified = self._verify_trigger(
            policy.get("policy_type", ""),
            policy.get("coverage", {}),
            trigger_data,
        )

        if verified:
            payout = float(policy["coverage"]["amount"])
            return await self.approve_claim(claim_id, payout)

        return await self.deny_claim(
            claim_id, "Trigger conditions not met by oracle data",
        )

    async def approve_claim(self, claim_id: str, payout_amount: float) -> dict:
        """Approve a claim and issue payout from the reserve.

        Args:
            claim_id: The claim to approve.
            payout_amount: Amount to pay out.

        Returns:
            Approval record.
        """
        # Withdraw from reserve
        try:
            withdrawal = await self._reserve_fund.withdraw(payout_amount)
        except ValueError as exc:
            logger.error("Payout failed for claim %s: %s", claim_id, exc)
            return {
                "status": "pending",
                "reason": f"Reserve insufficient: {exc}",
                "claim_id": claim_id,
            }

        record: dict[str, Any] = {
            "status": "approved",
            "claim_id": claim_id,
            "payout_amount": payout_amount,
            "withdrawal": withdrawal,
            "approved_at": int(time.time()),
        }
        self._processed[claim_id] = record

        # Attest via Component 8 if available
        await self._attest_claim(claim_id, "approved", payout_amount)

        logger.info("Claim approved: id=%s payout=%.6f", claim_id, payout_amount)
        return record

    async def deny_claim(self, claim_id: str, reason: str) -> dict:
        """Deny a claim with a reason.

        Denied claims may be escalated to Component 30 (dispute resolution).

        Args:
            claim_id: The claim to deny.
            reason: Human-readable denial reason.

        Returns:
            Denial record with optional dispute routing.
        """
        record: dict[str, Any] = {
            "status": "denied",
            "claim_id": claim_id,
            "reason": reason,
            "denied_at": int(time.time()),
            "dispute_eligible": True,
            "dispute_instructions": (
                "File a dispute via Component 30 (dispute_resolution) "
                "referencing this claim_id."
            ),
        }
        self._processed[claim_id] = record

        logger.info("Claim denied: id=%s reason=%s", claim_id, reason)
        return record

    # ------------------------------------------------------------------
    # Trigger verification
    # ------------------------------------------------------------------

    @staticmethod
    def _verify_trigger(
        policy_type: str,
        coverage: dict[str, Any],
        trigger_data: dict[str, Any],
    ) -> bool:
        """Verify that trigger data satisfies the policy's parametric condition.

        This mirrors the TriggerManager logic but operates on the claim's
        submitted trigger data rather than live oracle data.
        """
        if policy_type == "weather":
            metric = coverage.get("metric", "temperature")
            threshold = float(coverage.get("threshold", 0))
            comparator = coverage.get("comparator", "gt")
            value = trigger_data.get(metric)
            if value is None:
                return False
            value = float(value)
            if comparator == "gt":
                return value > threshold
            elif comparator == "lt":
                return value < threshold
            elif comparator == "gte":
                return value >= threshold
            elif comparator == "lte":
                return value <= threshold
            return value == threshold

        elif policy_type == "flight_delay":
            delay_thresh = int(coverage.get("delay_minutes", 120))
            actual = int(trigger_data.get("delay_minutes", 0))
            return actual >= delay_thresh

        elif policy_type == "crop":
            threshold = float(coverage.get("rainfall_threshold_mm", 50))
            actual = float(trigger_data.get("rainfall_mm", 999))
            return actual < threshold

        elif policy_type == "earthquake":
            threshold = float(coverage.get("magnitude_threshold", 5.0))
            magnitude = float(trigger_data.get("magnitude", 0))
            return magnitude >= threshold

        elif policy_type == "smart_contract_hack":
            loss_threshold = float(coverage.get("loss_threshold", 0))
            loss = float(trigger_data.get("loss_amount", 0))
            hacked = trigger_data.get("hack_detected", False)
            return bool(hacked) and loss >= loss_threshold

        return False

    # ------------------------------------------------------------------
    # Attestation
    # ------------------------------------------------------------------

    async def _attest_claim(
        self, claim_id: str, outcome: str, payout: float = 0.0,
    ) -> None:
        """Attest claim outcome via AttestationService (Component 8)."""
        try:
            from runtime.blockchain.services.attestation import AttestationService

            svc = AttestationService(self._config)
            await svc.attest(
                schema_uid="primary",
                data={
                    "action": f"insurance_claim_{outcome}",
                    "claim_id": claim_id,
                    "payout": payout,
                    "category": "insurance",
                },
                recipient=self._config.get("blockchain", {}).get(
                    "platform_wallet", ""
                ),
            )
        except ImportError:
            logger.debug("AttestationService not available; skipping attestation.")
        except Exception as exc:
            logger.warning("Claim attestation failed: %s", exc)
