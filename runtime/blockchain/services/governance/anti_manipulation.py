"""
AntiManipulation — detects and prevents governance manipulation.

Protections:
- Flash loan voting: token snapshot at proposal creation.
- Vote buying patterns: anomalous weight clustering.
- Sybil attacks: minimum holding period before voting.
- Bilateral dispute rejection: redirects to Component 30.
"""

from __future__ import annotations

import logging
import time
from typing import Any

logger = logging.getLogger(__name__)

# Minimum seconds a voter must hold tokens before they can vote
_DEFAULT_MIN_HOLDING_PERIOD = 7 * 86400  # 7 days

# Keywords indicating a bilateral dispute (belongs in Component 30)
_BILATERAL_KEYWORDS = frozenset({
    "dispute", "breach", "counterparty", "refund demand",
    "contract violation", "arbitration", "mediation",
    "bilateral", "disagreement between parties",
})


class AntiManipulation:
    """Anti-manipulation engine for platform governance.

    Config keys (under ``config["governance"]``):
        min_holding_period (int): Seconds tokens must be held before vote eligibility.
        max_weight_ratio (float): Max ratio a single vote can be of total weight.
        sybil_detection_enabled (bool): Enable sybil detection (default True).
    """

    def __init__(self, config: dict) -> None:
        self._config = config
        g_cfg: dict[str, Any] = config.get("governance", {})

        self._min_holding: int = int(
            g_cfg.get("min_holding_period", _DEFAULT_MIN_HOLDING_PERIOD)
        )
        self._max_weight_ratio: float = float(
            g_cfg.get("max_weight_ratio", 0.10)
        )
        self._sybil_enabled: bool = bool(
            g_cfg.get("sybil_detection_enabled", True)
        )

        # proposal_id -> {voter_address: token_balance} snapshot
        self._snapshots: dict[str, dict[str, float]] = {}
        # voter_address -> first_token_acquisition_timestamp
        self._holding_timestamps: dict[str, int] = {}
        # Flagged votes
        self._flags: list[dict[str, Any]] = []

        logger.info(
            "AntiManipulation initialised (min_holding=%ds, max_weight_ratio=%.2f).",
            self._min_holding, self._max_weight_ratio,
        )

    def take_snapshot(self, proposal_id: str, balances: dict[str, float]) -> None:
        """Snapshot token balances at proposal creation time.

        This prevents flash loan attacks: only balances at snapshot time count.
        """
        self._snapshots[proposal_id] = dict(balances)
        logger.info(
            "Snapshot taken: proposal=%s addresses=%d",
            proposal_id, len(balances),
        )

    def register_holding(self, voter: str, timestamp: int | None = None) -> None:
        """Register when a voter first acquired tokens.

        Only recorded once (first acquisition).
        """
        if voter not in self._holding_timestamps:
            self._holding_timestamps[voter] = timestamp or int(time.time())

    def get_snapshot_balance(self, proposal_id: str, voter: str) -> float:
        """Get a voter's balance from the snapshot."""
        snapshot = self._snapshots.get(proposal_id, {})
        return snapshot.get(voter, 0.0)

    async def check_vote(
        self, proposal_id: str, voter: str, weight: float, *,
        proposal_text: str = "",
    ) -> dict:
        """Run all anti-manipulation checks on a vote.

        Returns:
            Dict with 'allowed' bool, 'flags' list, and 'adjusted_weight'.
        """
        flags: list[str] = []
        allowed = True
        adjusted_weight = weight

        # 1. Bilateral dispute rejection
        if self._is_bilateral_dispute(proposal_text):
            logger.warning(
                "Bilateral dispute detected in proposal=%s, rejecting.",
                proposal_id,
            )
            return {
                "allowed": False,
                "flags": ["bilateral_dispute"],
                "adjusted_weight": 0.0,
                "reason": (
                    "This appears to be a bilateral dispute. Please use "
                    "Component 30 (Dispute Resolution) instead of platform governance."
                ),
                "redirect": "dispute_resolution",
            }

        # 2. Flash loan detection: compare current weight to snapshot
        snapshot = self._snapshots.get(proposal_id, {})
        snapshot_balance = snapshot.get(voter, None)

        if snapshot and snapshot_balance is not None:
            # Snapshot exists and has data for this voter
            if weight > snapshot_balance > 0:
                flags.append("flash_loan_suspected")
                adjusted_weight = snapshot_balance
                logger.warning(
                    "Flash loan suspected: voter=%s claimed_weight=%.2f snapshot=%.2f",
                    voter, weight, snapshot_balance,
                )
            elif snapshot_balance == 0.0 and len(snapshot) > 0:
                # Voter had no tokens at snapshot time (snapshot has real data)
                flags.append("no_snapshot_balance")
                adjusted_weight = 0.0
                allowed = False
                logger.warning(
                    "No snapshot balance: voter=%s had 0 tokens at proposal creation.",
                    voter,
                )

        # 3. Minimum holding period
        holding_ts = self._holding_timestamps.get(voter)
        if holding_ts is not None:
            elapsed = int(time.time()) - holding_ts
            if elapsed < self._min_holding:
                flags.append("insufficient_holding_period")
                allowed = False
                logger.warning(
                    "Holding period not met: voter=%s elapsed=%ds required=%ds",
                    voter, elapsed, self._min_holding,
                )

        # 4. Sybil detection: check for suspicious weight patterns
        if self._sybil_enabled and adjusted_weight > 0:
            sybil_flag = self._detect_sybil(proposal_id, voter, adjusted_weight)
            if sybil_flag:
                flags.append("sybil_suspected")
                logger.warning("Sybil suspected: voter=%s", voter)

        # 5. Weight cap: single voter cannot exceed max_weight_ratio of total
        # (only warn, don't block)
        total_snapshot = sum(self._snapshots.get(proposal_id, {}).values())
        if total_snapshot > 0 and adjusted_weight / total_snapshot > self._max_weight_ratio:
            flags.append("weight_cap_exceeded")
            adjusted_weight = total_snapshot * self._max_weight_ratio
            logger.info(
                "Weight capped: voter=%s capped_to=%.2f", voter, adjusted_weight,
            )

        if flags:
            self._flags.append({
                "proposal_id": proposal_id,
                "voter": voter,
                "flags": flags,
                "original_weight": weight,
                "adjusted_weight": adjusted_weight,
                "timestamp": int(time.time()),
            })

        return {
            "allowed": allowed,
            "flags": flags,
            "adjusted_weight": adjusted_weight,
            "reason": "; ".join(flags) if flags else "No issues detected",
        }

    def _is_bilateral_dispute(self, text: str) -> bool:
        """Check if proposal text describes a bilateral dispute."""
        if not text:
            return False
        text_lower = text.lower()
        matches = sum(1 for kw in _BILATERAL_KEYWORDS if kw in text_lower)
        return matches >= 2

    def _detect_sybil(self, proposal_id: str, voter: str, weight: float) -> bool:
        """Simple sybil detection: check for clusters of identical weights.

        If 5+ voters in the same proposal have the exact same weight, flag it.
        """
        recent_votes_for_proposal = [
            f for f in self._flags
            if f["proposal_id"] == proposal_id
        ]
        same_weight_count = sum(
            1 for f in recent_votes_for_proposal
            if abs(f["adjusted_weight"] - weight) < 0.001
        )
        return same_weight_count >= 5

    def get_flags(self, proposal_id: str | None = None) -> list[dict]:
        """Get all manipulation flags, optionally filtered by proposal."""
        if proposal_id is None:
            return list(self._flags)
        return [f for f in self._flags if f["proposal_id"] == proposal_id]
