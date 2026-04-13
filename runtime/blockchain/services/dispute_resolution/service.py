from __future__ import annotations

"""
DisputeResolution — main service orchestrating decentralised dispute
resolution across the 0pnMatrx platform.

Coordinates:
  - EvidenceVault   (immutable evidence storage)
  - JurorPool       (VRF-based juror selection via Component 11)
  - SchellingPoint   (commit-reveal voting)
  - Appeals          (multi-tier appeal escalation)

Dispute filing is a TIME-CRITICAL attestation — it is never batched.
Both parties must stake to participate.
"""

import logging
import time
import uuid
from typing import Any

from .appeals import Appeals
from .evidence_vault import EvidenceVault
from .juror_pool import JurorPool
from .schelling_point import SchellingPoint

logger = logging.getLogger(__name__)

VALID_CATEGORIES: set[str] = {
    "transaction",
    "nft_ownership",
    "ip_rights",
    "contract_breach",
    "fraud",
    "service_quality",
}

# Default base stake required to file a dispute (in platform tokens).
DEFAULT_BASE_STAKE: float = 100.0


class DisputeResolution:
    """Orchestrates end-to-end decentralised dispute resolution.

    Args:
        config: Platform configuration dict.  Relevant keys live under
            ``config["dispute_resolution"]``.
        oracle_gateway: Optional Component 11 Oracle Gateway instance
            used by :class:`JurorPool` for Chainlink VRF.
    """

    def __init__(
        self,
        config: dict | None = None,
        oracle_gateway: Any | None = None,
    ) -> None:
        self.config = config or {}
        dr_cfg = self.config.get("dispute_resolution", {})

        self._base_stake = float(dr_cfg.get("base_stake", DEFAULT_BASE_STAKE))

        # Sub-components
        self.evidence_vault = EvidenceVault(config=self.config)
        self.juror_pool = JurorPool(config=self.config, oracle_gateway=oracle_gateway)
        self.schelling = SchellingPoint(config=self.config)
        self.appeals = Appeals(config=self.config)

        # dispute_id -> dispute record
        self._disputes: dict[str, dict[str, Any]] = {}

    # ------------------------------------------------------------------
    # Filing
    # ------------------------------------------------------------------

    async def file_dispute(
        self,
        claimant: str,
        respondent: str,
        category: str,
        evidence: dict,
        stake_amount: float,
    ) -> dict:
        """File a new dispute.

        This is a **time-critical** attestation and is NEVER batched.

        Args:
            claimant: Address of the party filing the dispute.
            respondent: Address of the opposing party.
            category: One of the valid dispute categories.
            evidence: Initial evidence payload from the claimant.
            stake_amount: Tokens staked by the claimant.

        Returns:
            The newly created dispute record.

        Raises:
            ValueError: On invalid category, insufficient stake, or
                if claimant == respondent.
        """
        if category not in VALID_CATEGORIES:
            raise ValueError(
                f"Invalid category '{category}'. Must be one of: {sorted(VALID_CATEGORIES)}"
            )

        if stake_amount < self._base_stake:
            raise ValueError(
                f"Stake {stake_amount} below minimum {self._base_stake}"
            )

        if claimant == respondent:
            raise ValueError("Claimant and respondent must be different addresses")

        dispute_id = f"dispute-{uuid.uuid4().hex[:12]}"

        # Store initial evidence immutably
        ev_result = await self.evidence_vault.store(dispute_id, evidence)

        dispute: dict[str, Any] = {
            "dispute_id": dispute_id,
            "claimant": claimant,
            "respondent": respondent,
            "category": category,
            "status": "filed",
            "claimant_stake": stake_amount,
            "respondent_stake": 0.0,
            "evidence_hashes": [ev_result["evidence_hash"]],
            "jurors": [],
            "filed_at": time.time(),
            "resolved_at": None,
            "outcome": None,
            "appeal_count": 0,
            "time_critical": True,  # never batched
        }

        self._disputes[dispute_id] = dispute

        logger.info(
            "Dispute filed — id=%s claimant=%s respondent=%s category=%s stake=%.2f",
            dispute_id,
            claimant,
            respondent,
            category,
            stake_amount,
        )
        return dispute

    # ------------------------------------------------------------------
    # Evidence submission
    # ------------------------------------------------------------------

    async def submit_evidence(
        self, dispute_id: str, party: str, evidence: dict
    ) -> dict:
        """Submit additional evidence for an open dispute.

        Args:
            dispute_id: The dispute to attach evidence to.
            party: Address of the submitting party.
            evidence: Evidence payload.

        Returns:
            Dict with the evidence hash and updated dispute metadata.

        Raises:
            KeyError: If the dispute does not exist.
            ValueError: If the party is not involved in the dispute or
                the dispute is already resolved.
        """
        dispute = self._get_dispute_or_raise(dispute_id)

        if dispute["status"] in ("resolved", "dismissed"):
            raise ValueError(f"Cannot submit evidence — dispute {dispute_id} is {dispute['status']}")

        if party not in (dispute["claimant"], dispute["respondent"]):
            raise ValueError(
                f"Address {party} is not a party to dispute {dispute_id}"
            )

        # If the respondent is submitting for the first time, require stake
        if party == dispute["respondent"] and dispute["respondent_stake"] == 0.0:
            dispute["respondent_stake"] = self._base_stake
            dispute["status"] = "responded"

        ev_result = await self.evidence_vault.store(dispute_id, evidence)
        dispute["evidence_hashes"].append(ev_result["evidence_hash"])

        logger.info(
            "Evidence submitted — dispute=%s party=%s hash=%s",
            dispute_id,
            party,
            ev_result["evidence_hash"][:16],
        )
        return {
            "dispute_id": dispute_id,
            "evidence_hash": ev_result["evidence_hash"],
            "total_evidence": len(dispute["evidence_hashes"]),
            "status": dispute["status"],
        }

    # ------------------------------------------------------------------
    # Query
    # ------------------------------------------------------------------

    async def get_dispute(self, dispute_id: str) -> dict:
        """Return the full dispute record.

        Raises:
            KeyError: If the dispute does not exist.
        """
        return self._get_dispute_or_raise(dispute_id)

    # ------------------------------------------------------------------
    # Resolution
    # ------------------------------------------------------------------

    async def resolve(self, dispute_id: str) -> dict:
        """Drive a dispute through juror selection, voting, and outcome.

        This orchestration method:
        1. Selects jurors via the JurorPool (VRF-backed).
        2. Calculates the Schelling-point outcome from committed votes.
        3. Updates dispute status to ``resolved``.

        Jurors must have already submitted and revealed their votes via
        the :class:`SchellingPoint` before calling ``resolve``.

        Raises:
            KeyError: If the dispute does not exist.
            ValueError: If the dispute is not in a resolvable state.
        """
        dispute = self._get_dispute_or_raise(dispute_id)

        if dispute["status"] == "resolved":
            raise ValueError(f"Dispute {dispute_id} is already resolved")

        if dispute["status"] == "filed" and dispute["respondent_stake"] == 0.0:
            raise ValueError(
                f"Respondent has not yet staked for dispute {dispute_id}"
            )

        # Step 1: select jurors if not yet selected
        if not dispute["jurors"]:
            juror_count = 5
            appeal_records = self.appeals.get_appeals_for_dispute(dispute_id)
            if appeal_records:
                latest = appeal_records[-1]
                juror_count = latest["juror_count"]

            jurors = await self.juror_pool.select_jurors(
                dispute_id, count=juror_count, category=dispute["category"]
            )
            dispute["jurors"] = [j["address"] for j in jurors]

        # Step 2: tally outcome
        try:
            outcome = await self.schelling.calculate_outcome(dispute_id)
        except ValueError:
            raise ValueError(
                f"Votes not submitted/revealed for dispute {dispute_id}. "
                "Jurors must vote before resolution."
            )

        # Step 3: finalise
        dispute["outcome"] = outcome
        dispute["status"] = "resolved"
        dispute["resolved_at"] = time.time()

        logger.info(
            "Dispute resolved — id=%s winner=%s",
            dispute_id,
            outcome.get("winner"),
        )
        return dispute

    # ------------------------------------------------------------------
    # Appeals
    # ------------------------------------------------------------------

    async def appeal(
        self, dispute_id: str, appellant: str, new_evidence: dict
    ) -> dict:
        """File an appeal against a resolved dispute.

        Args:
            dispute_id: The dispute to appeal.
            appellant: Address of the appealing party.
            new_evidence: Supporting evidence for the appeal.

        Returns:
            The appeal record.

        Raises:
            KeyError: If the dispute does not exist.
            ValueError: If the dispute is not resolved, the appellant
                is not a party, or max appeals are exhausted.
        """
        dispute = self._get_dispute_or_raise(dispute_id)

        if dispute["status"] != "resolved":
            raise ValueError(
                f"Cannot appeal — dispute {dispute_id} status is '{dispute['status']}'"
            )

        if appellant not in (dispute["claimant"], dispute["respondent"]):
            raise ValueError(
                f"Address {appellant} is not a party to dispute {dispute_id}"
            )

        # Store new evidence
        if new_evidence:
            ev_result = await self.evidence_vault.store(dispute_id, new_evidence)
            dispute["evidence_hashes"].append(ev_result["evidence_hash"])

        appeal_record = await self.appeals.file_appeal(
            dispute_id=dispute_id,
            appellant=appellant,
            grounds=f"Appeal by {appellant}",
            new_evidence=new_evidence,
        )

        # Reset dispute for re-adjudication
        dispute["status"] = "appealed"
        dispute["appeal_count"] += 1
        dispute["jurors"] = []  # will be re-selected with larger panel
        dispute["outcome"] = None

        logger.info(
            "Dispute appealed — id=%s appellant=%s level=%d",
            dispute_id,
            appellant,
            appeal_record["appeal_level"],
        )
        return appeal_record

    # ------------------------------------------------------------------
    # Internals
    # ------------------------------------------------------------------

    # ------------------------------------------------------------------
    # Expanded dispute operations
    # ------------------------------------------------------------------

    async def request_arbitration(
        self, claimant: str, respondent: str, category: str, description: str, stake_amount: float = 0,
    ) -> dict:
        """Request formal arbitration for a dispute."""
        arb_id = f"arb_{uuid.uuid4().hex[:16]}"
        now = time.time()
        record: dict[str, Any] = {
            "id": arb_id,
            "status": "requested",
            "claimant": claimant,
            "respondent": respondent,
            "category": category,
            "description": description,
            "stake_amount": stake_amount or self._base_stake,
            "requested_at": now,
        }
        self._disputes[arb_id] = record
        logger.info("Arbitration requested: id=%s", arb_id)
        return record

    # ------------------------------------------------------------------
    # Internals
    # ------------------------------------------------------------------

    def _get_dispute_or_raise(self, dispute_id: str) -> dict:
        if dispute_id not in self._disputes:
            raise KeyError(f"Dispute not found: {dispute_id}")
        return self._disputes[dispute_id]
