"""
EligibilityTracker — applicant eligibility assessment for parametric insurance.

Evaluates claim history, risk score, and coverage overlap to determine
whether an applicant may purchase a given policy type.
"""

from __future__ import annotations

import logging
import time
from typing import Any

logger = logging.getLogger(__name__)

# Maximum active policies per holder per type
_MAX_ACTIVE_PER_TYPE = 3

# Claim-count thresholds that raise the risk flag
_HIGH_CLAIM_THRESHOLD = 5
_COOLDOWN_SECONDS = 30 * 86400  # 30-day cooldown after denied claim


class EligibilityTracker:
    """Tracks applicant eligibility for insurance policies.

    Factors considered:
    - Claim history (frequency, recent denials)
    - Risk score (computed from past behaviour)
    - Coverage overlap (too many active policies of same type)
    """

    def __init__(self, config: dict) -> None:
        self._config = config
        ins_cfg = config.get("insurance", {})

        self._max_active_per_type: int = int(
            ins_cfg.get("max_active_per_type", _MAX_ACTIVE_PER_TYPE)
        )
        self._high_claim_threshold: int = int(
            ins_cfg.get("high_claim_threshold", _HIGH_CLAIM_THRESHOLD)
        )

        # In-memory stores
        self._history: dict[str, list[dict[str, Any]]] = {}
        self._policies: dict[str, list[dict[str, Any]]] = {}

    async def check_eligibility(
        self, applicant: str, policy_type: str,
    ) -> dict:
        """Determine whether *applicant* may purchase *policy_type*.

        Returns:
            Dict with ``eligible`` bool, ``risk_score``, and optional
            ``reason`` if ineligible.
        """
        history = self._history.get(applicant, [])
        policies = self._policies.get(applicant, [])

        risk_score = self._compute_risk_score(history)
        active_of_type = sum(
            1 for p in policies
            if p.get("policy_type") == policy_type
            and p.get("status") == "active"
        )

        # Check coverage overlap
        if active_of_type >= self._max_active_per_type:
            return {
                "eligible": False,
                "risk_score": risk_score,
                "reason": (
                    f"Maximum active policies ({self._max_active_per_type}) "
                    f"for type '{policy_type}' already reached"
                ),
                "active_of_type": active_of_type,
            }

        # Check cooldown after recent denial
        now = int(time.time())
        recent_denials = [
            e for e in history
            if e.get("event") == "claim_denied"
            and now - e.get("timestamp", 0) < _COOLDOWN_SECONDS
        ]
        if recent_denials:
            return {
                "eligible": False,
                "risk_score": risk_score,
                "reason": "Cooldown period after denied claim has not elapsed",
                "cooldown_remaining_s": (
                    _COOLDOWN_SECONDS
                    - (now - recent_denials[-1].get("timestamp", 0))
                ),
            }

        # Check high-risk score
        if risk_score > 0.85:
            return {
                "eligible": False,
                "risk_score": risk_score,
                "reason": "Risk score exceeds acceptable threshold (0.85)",
            }

        logger.debug(
            "Eligibility check passed: applicant=%s type=%s risk=%.2f",
            applicant, policy_type, risk_score,
        )
        return {
            "eligible": True,
            "risk_score": risk_score,
            "active_of_type": active_of_type,
        }

    async def get_history(self, address: str) -> dict:
        """Return the full eligibility history for an address."""
        history = self._history.get(address, [])
        policies = self._policies.get(address, [])

        return {
            "address": address,
            "events": history,
            "total_policies": len(policies),
            "active_policies": sum(
                1 for p in policies if p.get("status") == "active"
            ),
            "total_claims": sum(
                1 for e in history if e.get("event", "").startswith("claim_")
            ),
            "risk_score": self._compute_risk_score(history),
        }

    async def record_policy(self, holder: str, policy: dict) -> None:
        """Record a new policy in the holder's history."""
        self._policies.setdefault(holder, []).append(policy)
        self._history.setdefault(holder, []).append({
            "event": "policy_created",
            "policy_id": policy.get("policy_id"),
            "policy_type": policy.get("policy_type"),
            "timestamp": int(time.time()),
        })

    async def record_claim(
        self, holder: str, claim_id: str, outcome: str,
    ) -> None:
        """Record a claim outcome (approved / denied)."""
        self._history.setdefault(holder, []).append({
            "event": f"claim_{outcome}",
            "claim_id": claim_id,
            "timestamp": int(time.time()),
        })

    # ------------------------------------------------------------------
    # Internal
    # ------------------------------------------------------------------

    def _compute_risk_score(self, history: list[dict[str, Any]]) -> float:
        """Compute a 0..1 risk score from event history.

        Factors:
        - Number of claims filed (more = higher risk)
        - Ratio of denied claims
        - Recency of claims
        """
        if not history:
            return 0.0

        claims = [e for e in history if e.get("event", "").startswith("claim_")]
        if not claims:
            return 0.0

        total = len(claims)
        denied = sum(1 for c in claims if c["event"] == "claim_denied")

        # Frequency component: approaches 1 as claims approach threshold
        freq = min(1.0, total / max(1, self._high_claim_threshold))

        # Denial ratio component
        denial_ratio = denied / total if total else 0.0

        # Recency: boost score if many recent claims
        now = int(time.time())
        recent = sum(
            1 for c in claims
            if now - c.get("timestamp", 0) < 90 * 86400  # 90 days
        )
        recency = min(1.0, recent / 3.0)

        score = 0.4 * freq + 0.3 * denial_ratio + 0.3 * recency
        return round(min(1.0, score), 4)
