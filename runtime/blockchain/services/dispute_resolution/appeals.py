"""
Appeals — multi-tier appeal process for dispute resolution.

Each dispute may be appealed at most twice. Every appeal escalates
to a larger juror panel and requires a higher stake from the
appellant.

  Appeal 1 → 7 jurors, 2x base stake
  Appeal 2 → 11 jurors, 3x base stake
"""

import logging
import time
import uuid
from typing import Any

logger = logging.getLogger(__name__)

MAX_APPEALS: int = 2

APPEAL_TIERS: list[dict[str, Any]] = [
    {"level": 1, "juror_count": 7, "stake_multiplier": 2.0},
    {"level": 2, "juror_count": 11, "stake_multiplier": 3.0},
]


class Appeals:
    """Manages the multi-tier appeal process for resolved disputes."""

    def __init__(self, config: dict | None = None) -> None:
        self.config = config or {}
        self._base_stake = float(
            self.config.get("dispute_resolution", {}).get("base_stake", 100.0)
        )
        # appeal_id -> appeal record
        self._appeals: dict[str, dict[str, Any]] = {}
        # dispute_id -> list of appeal_ids (ordered)
        self._dispute_appeals: dict[str, list[str]] = {}

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    async def file_appeal(
        self,
        dispute_id: str,
        appellant: str,
        grounds: str,
        new_evidence: dict,
    ) -> dict:
        """File an appeal against a dispute resolution.

        Args:
            dispute_id: The dispute being appealed.
            appellant: Address of the party filing the appeal.
            grounds: Free-text explanation of appeal grounds.
            new_evidence: Any new evidence supporting the appeal.

        Returns:
            Appeal record dict.

        Raises:
            ValueError: If the maximum number of appeals has been
                reached or required fields are missing.
        """
        if not grounds.strip():
            raise ValueError("Appeal grounds must be provided")

        prior = self._dispute_appeals.get(dispute_id, [])
        if len(prior) >= MAX_APPEALS:
            raise ValueError(
                f"Maximum appeals ({MAX_APPEALS}) reached for dispute {dispute_id}"
            )

        appeal_level = len(prior) + 1
        tier = APPEAL_TIERS[appeal_level - 1]
        required_stake = self._base_stake * tier["stake_multiplier"]

        appeal_id = f"appeal-{uuid.uuid4().hex[:12]}"

        record: dict[str, Any] = {
            "appeal_id": appeal_id,
            "dispute_id": dispute_id,
            "appellant": appellant,
            "grounds": grounds,
            "new_evidence": new_evidence,
            "appeal_level": appeal_level,
            "juror_count": tier["juror_count"],
            "required_stake": required_stake,
            "status": "filed",
            "filed_at": time.time(),
            "resolved_at": None,
            "outcome": None,
        }

        self._appeals[appeal_id] = record
        self._dispute_appeals.setdefault(dispute_id, []).append(appeal_id)

        logger.info(
            "Appeal filed — id=%s dispute=%s level=%d jurors=%d stake=%.2f",
            appeal_id,
            dispute_id,
            appeal_level,
            tier["juror_count"],
            required_stake,
        )
        return record

    async def process_appeal(self, appeal_id: str) -> dict:
        """Mark an appeal as under review and transition its status.

        In a full implementation this would trigger juror selection on
        the larger panel and a new Schelling-point vote. Here we move
        the appeal to ``processing`` status and return the parameters
        needed for the next round of voting.

        Raises:
            KeyError: If the appeal does not exist.
            ValueError: If the appeal is not in ``filed`` status.
        """
        if appeal_id not in self._appeals:
            raise KeyError(f"Appeal not found: {appeal_id}")

        record = self._appeals[appeal_id]

        if record["status"] != "filed":
            raise ValueError(
                f"Appeal {appeal_id} cannot be processed — current status: {record['status']}"
            )

        record["status"] = "processing"
        record["processing_started_at"] = time.time()

        logger.info(
            "Appeal processing started — id=%s dispute=%s level=%d",
            appeal_id,
            record["dispute_id"],
            record["appeal_level"],
        )

        return {
            "appeal_id": appeal_id,
            "dispute_id": record["dispute_id"],
            "status": "processing",
            "juror_count": record["juror_count"],
            "required_stake": record["required_stake"],
            "appeal_level": record["appeal_level"],
        }

    # ------------------------------------------------------------------
    # Query helpers
    # ------------------------------------------------------------------

    def get_appeal(self, appeal_id: str) -> dict:
        if appeal_id not in self._appeals:
            raise KeyError(f"Appeal not found: {appeal_id}")
        return self._appeals[appeal_id]

    def get_appeals_for_dispute(self, dispute_id: str) -> list[dict]:
        ids = self._dispute_appeals.get(dispute_id, [])
        return [self._appeals[aid] for aid in ids]

    def appeals_remaining(self, dispute_id: str) -> int:
        return MAX_APPEALS - len(self._dispute_appeals.get(dispute_id, []))
