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
        *,
        verified: bool,
        reason: str = "",
    ) -> dict:
        """Approve or deny a claim on an ALREADY-MADE verification decision.

        NEW-78: this used to decide for itself, by calling _verify_trigger on
        `claim["trigger_data"]` — the CLAIMANT'S OWN dict. That method is
        deleted, not guarded: it compared caller-supplied numbers against the
        policy's parametric condition, a condition the claimant can read and
        then satisfy. Its own docstring admitted the gap — "operates on the
        claim's submitted trigger data rather than live oracle data."

        Verification now happens in InsuranceService._verify_via_oracle, which
        routes through TriggerManager -> OracleGateway and fails closed. The
        verdict arrives here as a required keyword, so this class can no
        longer decide a payout from anything the caller wrote. Making
        `verified` keyword-only and non-defaulting is deliberate: a caller
        that forgets it gets a TypeError, not a silent approval.

        Deleting _verify_trigger also removes a DUPLICATE evaluator — the same
        per-policy-type threshold logic lives in TriggerManager._eval_*, and
        the two had already drifted.
        """
        if verified:
            payout = float(policy["coverage"]["amount"])
            return await self.approve_claim(claim_id, payout)

        return await self.deny_claim(
            claim_id, reason or "Trigger conditions not met by oracle data",
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

        # NEW-78: _verify_trigger DELETED, not guarded.
    #
    # It read the decision values straight out of the claimant's own
    # trigger_data dict — no signature, no oracle, no provenance — and its
    # docstring said so: "operates on the claim's submitted trigger data
    # rather than live oracle data." A guarded-but-present version would be
    # one refactor from being the live path again, which is exactly how the
    # fundraising oracle fallback became live.
    #
    # The equivalent threshold logic already exists, correctly fed, in
    # TriggerManager._eval_* against OracleGateway data.

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
