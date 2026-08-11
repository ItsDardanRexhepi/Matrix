"""
RefundManager — handles refunds for failed or underperforming fundraising
campaigns.

Auto-refund if campaign fails to meet goal by deadline.
Pro-rata refunds if milestone verification fails.
"""

from __future__ import annotations

import logging
import time
import uuid
from typing import Any

logger = logging.getLogger(__name__)


class RefundManager:
    """Refund engine for fundraising campaigns.

    Config keys (under ``config["fundraising"]``):
        refund_processing_fee_pct (float): Fee taken on refunds (default 0, i.e. full refund).
        auto_refund_delay (int): Seconds after deadline before auto-refund (default 86400).
    """

    def __init__(self, config: dict) -> None:
        self._config = config
        f_cfg: dict[str, Any] = config.get("fundraising", {})

        self._fee_pct: float = float(f_cfg.get("refund_processing_fee_pct", 0.0))
        self._auto_delay: int = int(f_cfg.get("auto_refund_delay", 86400))

        # (campaign_id, contributor) -> refund record
        self._refunds: dict[tuple[str, str], dict[str, Any]] = {}
        # campaign_id -> bulk refund state
        self._bulk_refunds: dict[str, dict[str, Any]] = {}

        logger.info(
            "RefundManager initialised (fee=%.2f%%, auto_delay=%ds).",
            self._fee_pct, self._auto_delay,
        )

    async def request_refund(
        self, campaign_id: str, contributor: str, *,
        contribution: float = 0.0,
        campaign: dict | None = None,
    ) -> dict:
        """Request a refund for a campaign contribution.

        A refund is allowed if:
        - Campaign has failed (didn't meet goal by deadline).
        - A milestone verification failed.
        - Campaign status is "refunding".

        Args:
            campaign_id: Campaign identifier.
            contributor: Contributor wallet address.
            contribution: Contributor's total contribution (for standalone use).
            campaign: Optional campaign record (for integration with service).

        Returns:
            Refund request record.
        """
        if not campaign_id or not contributor:
            raise ValueError("campaign_id and contributor are required")

        key = (campaign_id, contributor)
        # NEW-68: second instance of the same poisoning. This REFUSED a refund
        # request outright when a prior record said "completed" — a status this
        # module stamped without paying anyone. A contributor whose refund had
        # been "processed" (calculated) could therefore never request a real
        # one. Only a genuinely settled refund may block a new request.
        if key in self._refunds and self._refunds[key].get("settled") is True:
            raise ValueError(
                f"Refund already settled for {contributor} in campaign {campaign_id}"
            )

        # Determine refund eligibility
        eligible = False
        reason = ""

        if campaign is not None:
            status = campaign.get("status", "")
            if status in ("failed", "refunding"):
                eligible = True
                reason = f"Campaign {status}"
            elif status == "active":
                # Check if past deadline
                deadline = campaign.get("deadline", 0)
                raised = campaign.get("raised", 0)
                goal = campaign.get("goal", 0)
                if deadline and int(time.time()) > deadline and raised < goal:
                    eligible = True
                    reason = "Campaign failed to meet goal by deadline"
            elif status == "milestone_failed":
                eligible = True
                reason = "Milestone verification failed"
        else:
            # Without campaign context, allow the request
            eligible = True
            reason = "Manual refund request"

        if not eligible:
            return {
                "campaign_id": campaign_id,
                "contributor": contributor,
                "eligible": False,
                "reason": f"Refund not available: campaign status does not allow refunds",
                "status": "rejected",
            }

        # Calculate refund amount
        refund_amount = contribution * (1 - self._fee_pct / 100)

        refund_record = {
            "refund_id": str(uuid.uuid4()),
            "campaign_id": campaign_id,
            "contributor": contributor,
            "original_contribution": contribution,
            "refund_amount": refund_amount,
            "fee_amount": contribution - refund_amount,
            "eligible": True,
            "reason": reason,
            "status": "pending",
            "requested_at": int(time.time()),
            "processed_at": None,
        }

        self._refunds[key] = refund_record

        logger.info(
            "Refund requested: campaign=%s contributor=%s amount=%.4f",
            campaign_id, contributor, refund_amount,
        )
        return dict(refund_record)

    async def process_refunds(
        self, campaign_id: str, *,
        contributions: dict[str, float] | None = None,
        total_raised: float = 0.0,
        total_released: float = 0.0,
    ) -> dict:
        """Process all pending refunds for a campaign.

        For pro-rata refunds (milestone failure), the refundable amount
        is: (total_raised - total_released) * (contributor_share / total_raised).

        Args:
            campaign_id: Campaign to process refunds for.
            contributions: Mapping of contributor -> contribution amount.
            total_raised: Total amount raised by campaign.
            total_released: Total already released to creator via milestones.

        Returns:
            Bulk refund processing result.
        """
        if not campaign_id:
            raise ValueError("Campaign ID is required")

        if contributions is None:
            contributions = {}

        refundable_pool = max(0.0, total_raised - total_released)
        processed: list[dict[str, Any]] = []
        total_refunded = 0.0

        for contributor, amount in contributions.items():
            key = (campaign_id, contributor)
            existing = self._refunds.get(key)

            # NEW-68: was `existing["status"] == "completed"`. Because this
            # method STAMPED "completed" without paying anything, that skip
            # meant a fabricated completion would cause a REAL refund run — if
            # one is ever implemented — to pass the contributor over. The
            # false record did not merely misreport; it poisoned the ledger
            # against its own correction. Only a genuinely settled record may
            # suppress a re-run, and none can exist yet.
            if existing and existing.get("settled") is True:
                continue

            # Pro-rata calculation
            if total_raised > 0:
                share = amount / total_raised
                refund_amount = refundable_pool * share
            else:
                refund_amount = amount

            refund_amount *= (1 - self._fee_pct / 100)
            now = int(time.time())

            record = {
                "refund_id": str(uuid.uuid4()),
                "campaign_id": campaign_id,
                "contributor": contributor,
                "original_contribution": amount,
                "refund_amount": refund_amount,
                "fee_amount": (amount * self._fee_pct / 100),
                "pro_rata_share": amount / total_raised if total_raised > 0 else 1.0,
                # NEW-68: was `"status": "completed"` with a `processed_at`
                # timestamp. The pro-rata arithmetic above is REAL — it reads
                # each contribution, computes the share against the refundable
                # pool and deducts the fee — but nothing is ever transferred.
                # "completed" asserted that contributors had been refunded.
                # Real-local-defective: genuine computation, false claim.
                #
                # Vocabulary changed rather than softened, in the
                # RECORDED_UNSETTLED idiom already established in x402: a
                # reader cannot mistake "calculated_unpaid" for money returned.
                "status": "calculated_unpaid",
                "settled": False,
                "value_moved": False,
                "disclosure": (
                    "Refund amounts are CALCULATED only. No funds have been "
                    "returned to this contributor and no transfer has been "
                    "initiated."
                ),
                "requested_at": now,
                "calculated_at": now,
            }

            self._refunds[key] = record
            processed.append(record)
            total_refunded += refund_amount

        # NEW-68: the summary carried the same false claim as the per-record
        # status — `total_refunded` and `contributors_refunded` name money
        # returned and people paid. Renamed to what actually happened, with
        # the disclosure repeated at the summary level so a caller reading
        # only the envelope is not misled.
        result = {
            "campaign_id": campaign_id,
            "refundable_pool": refundable_pool,
            "total_calculated": total_refunded,
            "contributors_calculated": len(processed),
            "settled": False,
            "value_moved": False,
            "disclosure": (
                "Pro-rata refund amounts calculated for this campaign. NO "
                "refunds have been paid and no transfers have been initiated."
            ),
            "refunds": processed,
            "calculated_at": int(time.time()),
        }

        self._bulk_refunds[campaign_id] = result

        logger.info(
            "Refunds processed: campaign=%s refunded=%d total=%.4f",
            campaign_id, len(processed), total_refunded,
        )
        return result

    async def get_refund_status(
        self, campaign_id: str, contributor: str
    ) -> dict:
        """Get refund status for a specific contributor.

        Returns:
            Refund record or status indicating no refund found.
        """
        key = (campaign_id, contributor)
        record = self._refunds.get(key)
        if not record:
            return {
                "campaign_id": campaign_id,
                "contributor": contributor,
                "status": "none",
                "message": "No refund request found for this contributor",
            }
        return dict(record)
