"""
GovernanceService — platform governance and voting for the 0pnMatrx platform.

IMPORTANT: This is PLATFORM governance only. Bilateral disputes must
use Component 30 (Dispute Resolution). Attempts to file bilateral
disputes as governance proposals are detected and rejected.
"""

from __future__ import annotations

import logging
import time
import uuid
from typing import Any

from runtime.blockchain.services.governance.anti_manipulation import AntiManipulation
from runtime.blockchain.services.governance.quorum import QuorumLogic
from runtime.blockchain.services.governance.voting_models import (
    VotingModel,
    get_voting_model,
)

logger = logging.getLogger(__name__)

_VALID_STATUSES = ("active", "passed", "rejected", "expired", "finalized")

_PROPOSAL_TYPE_MAP: dict[str, str] = {
    "standard": "standard",
    "treasury": "treasury",
    "constitutional": "constitutional",
    "emergency": "emergency",
    "parameter": "parameter",
}


class GovernanceService:
    """Main platform governance service.

    Config keys (under ``config["governance"]``):
        voting_duration (int): Default voting period in seconds (default 7 days).
        default_model (str): Default voting model (default "token_weighted").
        All keys from QuorumLogic and AntiManipulation are also supported.
    """

    def __init__(self, config: dict) -> None:
        self._config = config
        g_cfg: dict[str, Any] = config.get("governance", {})

        self._voting_duration: int = int(
            g_cfg.get("voting_duration", 7 * 86400)
        )
        self._default_model: str = g_cfg.get("default_model", "token_weighted")

        self._quorum = QuorumLogic(config)
        self._anti_manipulation = AntiManipulation(config)

        # proposal_id -> proposal record
        self._proposals: dict[str, dict[str, Any]] = {}
        # proposal_id -> [vote records]
        self._votes: dict[str, list[dict[str, Any]]] = {}
        # (proposal_id, voter) -> True  (prevents double voting)
        self._voter_registry: dict[tuple[str, str], bool] = {}

        logger.info(
            "GovernanceService initialised (duration=%ds, model=%s).",
            self._voting_duration, self._default_model,
        )

    @property
    def quorum(self) -> QuorumLogic:
        return self._quorum

    @property
    def anti_manipulation(self) -> AntiManipulation:
        return self._anti_manipulation

    # ------------------------------------------------------------------
    # Proposals
    # ------------------------------------------------------------------

    async def create_proposal(
        self,
        proposer: str,
        title: str,
        description: str,
        voting_model: str,
        options: list,
    ) -> dict:
        """Create a new governance proposal.

        Args:
            proposer: Address of the proposer.
            title: Short title.
            description: Full description.
            voting_model: "token_weighted", "one_person_one_vote", or "quadratic".
            options: List of voting options (e.g. ["yes", "no", "abstain"]).

        Returns:
            Proposal record.
        """
        if not proposer:
            raise ValueError("Proposer address is required")
        if not title:
            raise ValueError("Title is required")
        if not options or len(options) < 2:
            raise ValueError("At least two voting options are required")

        # Bilateral dispute detection on proposal text
        combined_text = f"{title} {description}"
        if self._anti_manipulation._is_bilateral_dispute(combined_text):
            raise ValueError(
                "This appears to be a bilateral dispute. Please use "
                "Component 30 (Dispute Resolution) instead of platform governance. "
                "Governance proposals are for platform-wide decisions only."
            )

        # Validate voting model
        model = get_voting_model(voting_model or self._default_model)

        proposal_id = str(uuid.uuid4())
        now = int(time.time())

        # Determine proposal type from title/description heuristics
        proposal_type = self._classify_proposal(title, description)

        proposal = {
            "proposal_id": proposal_id,
            "proposer": proposer,
            "title": title,
            "description": description,
            "voting_model": voting_model or self._default_model,
            "options": list(options),
            "proposal_type": proposal_type,
            "status": "active",
            "created_at": now,
            "ends_at": now + self._voting_duration,
            "finalized_at": None,
            "result": None,
            "vote_count": 0,
        }

        self._proposals[proposal_id] = proposal
        self._votes[proposal_id] = []

        # Take a token snapshot for anti-flash-loan protection
        # In production, this would pull real balances from the chain
        self._anti_manipulation.take_snapshot(proposal_id, {})

        logger.info(
            "Proposal created: id=%s type=%s title='%s' model=%s",
            proposal_id, proposal_type, title, voting_model,
        )
        return dict(proposal)

    async def vote(
        self,
        proposal_id: str,
        voter: str,
        choice: str,
        weight: float = 1.0,
    ) -> dict:
        """Cast a vote on a proposal.

        Args:
            proposal_id: Target proposal.
            voter: Voter wallet address.
            choice: Must be one of the proposal's options.
            weight: Vote weight (interpretation depends on voting model).

        Returns:
            Vote record.
        """
        proposal = self._proposals.get(proposal_id)
        if not proposal:
            raise ValueError(f"Proposal {proposal_id} not found")
        if proposal["status"] != "active":
            raise ValueError(f"Proposal {proposal_id} is {proposal['status']}, voting closed")

        now = int(time.time())
        if now > proposal["ends_at"]:
            proposal["status"] = "expired"
            raise ValueError(f"Proposal {proposal_id} voting period has ended")

        if choice not in proposal["options"]:
            raise ValueError(
                f"Invalid choice '{choice}'; must be one of {proposal['options']}"
            )

        # Prevent double voting
        vote_key = (proposal_id, voter)
        if vote_key in self._voter_registry:
            raise ValueError(f"Voter {voter} has already voted on proposal {proposal_id}")

        # Anti-manipulation check
        manipulation_result = await self._anti_manipulation.check_vote(
            proposal_id, voter, weight,
            proposal_text=f"{proposal['title']} {proposal['description']}",
        )
        if not manipulation_result["allowed"]:
            raise ValueError(
                f"Vote rejected: {manipulation_result['reason']}"
            )

        # Calculate effective weight via voting model
        model = get_voting_model(proposal["voting_model"])
        effective_weight = model.calculate_weight(
            voter, manipulation_result["adjusted_weight"],
            context={"token_balance": manipulation_result["adjusted_weight"]},
        )

        vote_record = {
            "vote_id": str(uuid.uuid4()),
            "proposal_id": proposal_id,
            "voter": voter,
            "choice": choice,
            "raw_weight": weight,
            "effective_weight": effective_weight,
            "flags": manipulation_result.get("flags", []),
            "cast_at": now,
        }

        self._votes[proposal_id].append(vote_record)
        self._voter_registry[vote_key] = True
        proposal["vote_count"] += 1

        logger.info(
            "Vote cast: proposal=%s voter=%s choice=%s weight=%.4f",
            proposal_id, voter, choice, effective_weight,
        )
        return dict(vote_record)

    async def get_proposal(self, proposal_id: str) -> dict:
        """Get full proposal details including current vote tally.

        Returns:
            Proposal record with tally and quorum status.
        """
        proposal = self._proposals.get(proposal_id)
        if not proposal:
            raise ValueError(f"Proposal {proposal_id} not found")

        result = dict(proposal)

        # Include current tally
        votes = self._votes.get(proposal_id, [])
        model = get_voting_model(proposal["voting_model"])
        result["tally"] = model.tally(votes)

        # Include quorum status
        quorum = await self._quorum.check_quorum(
            proposal_id,
            votes=votes,
            proposal_type=proposal.get("proposal_type", "standard"),
            voting_model=model,
        )
        result["quorum"] = quorum

        # Auto-expire if past deadline
        now = int(time.time())
        if proposal["status"] == "active" and now > proposal["ends_at"]:
            proposal["status"] = "expired"
            result["status"] = "expired"

        return result

    async def finalize(self, proposal_id: str) -> dict:
        """Finalize a proposal: tally votes, check quorum, set result.

        Returns:
            Finalized proposal record.
        """
        proposal = self._proposals.get(proposal_id)
        if not proposal:
            raise ValueError(f"Proposal {proposal_id} not found")
        if proposal["status"] == "finalized":
            raise ValueError(f"Proposal {proposal_id} is already finalized")

        now = int(time.time())
        votes = self._votes.get(proposal_id, [])
        model = get_voting_model(proposal["voting_model"])

        # Tally
        tally = model.tally(votes)

        # Quorum check
        quorum = await self._quorum.check_quorum(
            proposal_id,
            votes=votes,
            proposal_type=proposal.get("proposal_type", "standard"),
            voting_model=model,
        )

        if quorum["quorum_met"]:
            proposal["status"] = "passed" if tally.get("winner") else "rejected"
        else:
            proposal["status"] = "rejected"

        proposal["result"] = {
            "tally": tally,
            "quorum": quorum,
            "outcome": proposal["status"],
        }
        proposal["finalized_at"] = now
        proposal["status"] = "finalized"

        logger.info(
            "Proposal finalized: id=%s outcome=%s winner=%s quorum_met=%s",
            proposal_id, proposal["result"]["outcome"],
            tally.get("winner"), quorum["quorum_met"],
        )
        return dict(proposal)

    async def list_proposals(self, status: str | None = None) -> list:
        """List all proposals, optionally filtered by status.

        Returns:
            List of proposal summary dicts.
        """
        results = []
        now = int(time.time())

        for proposal in self._proposals.values():
            # Auto-expire
            if proposal["status"] == "active" and now > proposal["ends_at"]:
                proposal["status"] = "expired"

            if status is not None and proposal["status"] != status:
                continue

            results.append({
                "proposal_id": proposal["proposal_id"],
                "title": proposal["title"],
                "status": proposal["status"],
                "voting_model": proposal["voting_model"],
                "proposal_type": proposal.get("proposal_type", "standard"),
                "vote_count": proposal["vote_count"],
                "created_at": proposal["created_at"],
                "ends_at": proposal["ends_at"],
            })

        results.sort(key=lambda p: p["created_at"], reverse=True)
        return results

    # ------------------------------------------------------------------
    # Internals
    # ------------------------------------------------------------------

    def _classify_proposal(self, title: str, description: str) -> str:
        """Classify proposal type from text heuristics."""
        text = f"{title} {description}".lower()

        if any(w in text for w in ("treasury", "funding", "budget", "spend")):
            return "treasury"
        if any(w in text for w in ("constitution", "charter", "fundamental", "amendment")):
            return "constitutional"
        if any(w in text for w in ("emergency", "urgent", "critical")):
            return "emergency"
        if any(w in text for w in ("parameter", "threshold", "fee", "rate")):
            return "parameter"
        return "standard"
