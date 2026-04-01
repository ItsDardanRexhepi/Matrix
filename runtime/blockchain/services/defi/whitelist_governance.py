"""
WhitelistGovernance — govern which tokens are accepted as collateral
or for lending on the DeFi layer.

Uses a simple proposal/vote mechanism where token holders can propose
new tokens and vote on their inclusion.
"""

from __future__ import annotations

import logging
import time
import uuid
from enum import Enum
from typing import Any

logger = logging.getLogger(__name__)


class ProposalStatus(str, Enum):
    ACTIVE = "active"
    PASSED = "passed"
    REJECTED = "rejected"
    EXECUTED = "executed"
    EXPIRED = "expired"


class WhitelistGovernance:
    """Govern which tokens are accepted on the DeFi platform.

    Parameters
    ----------
    config : dict
        Platform config.  Reads:
        - ``defi.governance.voting_period_days`` (default 7)
        - ``defi.governance.quorum`` (default 100) — votes needed
        - ``defi.governance.approval_threshold`` (default 0.6) — 60%
        - ``defi.governance.initial_whitelist`` — list of initially
          accepted token addresses
    """

    def __init__(self, config: dict) -> None:
        self._config = config
        gov_cfg = config.get("defi", {}).get("governance", {})

        self._voting_period: int = int(gov_cfg.get("voting_period_days", 7))
        self._quorum: int = int(gov_cfg.get("quorum", 100))
        self._approval_threshold: float = float(
            gov_cfg.get("approval_threshold", 0.6)
        )

        # Whitelist: set of accepted token addresses
        initial = gov_cfg.get("initial_whitelist", [])
        self._whitelist: set[str] = set(initial)

        # Proposals
        self._proposals: dict[str, dict[str, Any]] = {}
        # Track who has voted: {proposal_id: {voter: bool}}
        self._votes: dict[str, dict[str, bool]] = {}

    async def propose_token(
        self, token_address: str, proposer: str
    ) -> dict[str, Any]:
        """Propose a new token for the whitelist.

        Parameters
        ----------
        token_address : str
            Token contract address to propose.
        proposer : str
            Address of the proposer.

        Returns
        -------
        dict
            Proposal details including ``proposal_id``.
        """
        if not token_address or not token_address.startswith("0x"):
            raise ValueError("Invalid token address")

        if token_address in self._whitelist:
            raise ValueError(f"Token {token_address} is already whitelisted")

        # Check for duplicate active proposals
        for proposal in self._proposals.values():
            if (
                proposal["token_address"] == token_address
                and proposal["status"] == ProposalStatus.ACTIVE
            ):
                raise ValueError(
                    f"Active proposal already exists for {token_address}: "
                    f"{proposal['proposal_id']}"
                )

        proposal_id = f"prop_{uuid.uuid4().hex[:16]}"
        now = int(time.time())

        proposal: dict[str, Any] = {
            "proposal_id": proposal_id,
            "token_address": token_address,
            "proposer": proposer,
            "status": ProposalStatus.ACTIVE,
            "votes_for": 0,
            "votes_against": 0,
            "created_at": now,
            "voting_ends_at": now + (self._voting_period * 86400),
            "quorum": self._quorum,
            "approval_threshold": self._approval_threshold,
        }

        self._proposals[proposal_id] = proposal
        self._votes[proposal_id] = {}

        logger.info(
            "Token whitelist proposal created: id=%s token=%s proposer=%s",
            proposal_id, token_address, proposer,
        )
        return proposal

    async def vote_on_proposal(
        self, proposal_id: str, voter: str, support: bool
    ) -> dict[str, Any]:
        """Cast a vote on a whitelist proposal.

        Parameters
        ----------
        proposal_id : str
            The proposal to vote on.
        voter : str
            Address of the voter.
        support : bool
            True for yes, False for no.

        Returns
        -------
        dict
            Updated vote tally.
        """
        if proposal_id not in self._proposals:
            raise KeyError(f"Proposal '{proposal_id}' not found")

        proposal = self._proposals[proposal_id]
        now = int(time.time())

        # Check expiry
        if now > proposal["voting_ends_at"]:
            self._finalize_proposal(proposal)
            raise ValueError(
                f"Voting period has ended. Final status: {proposal['status']}"
            )

        if proposal["status"] != ProposalStatus.ACTIVE:
            raise ValueError(
                f"Proposal is {proposal['status']}, cannot vote"
            )

        # Check duplicate vote
        proposal_votes = self._votes[proposal_id]
        if voter in proposal_votes:
            raise ValueError(f"Voter {voter} has already voted on this proposal")

        # Record vote
        proposal_votes[voter] = support
        if support:
            proposal["votes_for"] += 1
        else:
            proposal["votes_against"] += 1

        # Check if quorum reached and auto-finalize
        total_votes = proposal["votes_for"] + proposal["votes_against"]
        if total_votes >= self._quorum:
            self._finalize_proposal(proposal)

        logger.info(
            "Vote cast: proposal=%s voter=%s support=%s (for=%d against=%d)",
            proposal_id, voter, support,
            proposal["votes_for"], proposal["votes_against"],
        )

        return {
            "proposal_id": proposal_id,
            "voter": voter,
            "support": support,
            "votes_for": proposal["votes_for"],
            "votes_against": proposal["votes_against"],
            "total_votes": total_votes,
            "status": proposal["status"],
        }

    async def get_whitelist(self) -> list[str]:
        """Return the current list of whitelisted token addresses."""
        return sorted(self._whitelist)

    async def get_proposal(self, proposal_id: str) -> dict[str, Any]:
        """Get a proposal by ID."""
        if proposal_id not in self._proposals:
            raise KeyError(f"Proposal '{proposal_id}' not found")

        proposal = self._proposals[proposal_id]
        now = int(time.time())

        # Auto-finalize expired proposals
        if (
            proposal["status"] == ProposalStatus.ACTIVE
            and now > proposal["voting_ends_at"]
        ):
            self._finalize_proposal(proposal)

        return proposal

    async def list_proposals(
        self, status: str | None = None
    ) -> list[dict[str, Any]]:
        """List all proposals, optionally filtered by status."""
        now = int(time.time())
        results: list[dict[str, Any]] = []

        for proposal in self._proposals.values():
            # Auto-finalize expired
            if (
                proposal["status"] == ProposalStatus.ACTIVE
                and now > proposal["voting_ends_at"]
            ):
                self._finalize_proposal(proposal)

            if status and proposal["status"] != status:
                continue
            results.append(proposal)

        return results

    def is_whitelisted(self, token_address: str) -> bool:
        """Check if a token is whitelisted."""
        return token_address in self._whitelist

    def add_to_whitelist(self, token_address: str) -> None:
        """Directly add a token (admin override)."""
        self._whitelist.add(token_address)
        logger.info("Token added to whitelist (admin): %s", token_address)

    def remove_from_whitelist(self, token_address: str) -> None:
        """Directly remove a token (admin override)."""
        self._whitelist.discard(token_address)
        logger.info("Token removed from whitelist (admin): %s", token_address)

    # ── Internal ──────────────────────────────────────────────────────

    def _finalize_proposal(self, proposal: dict[str, Any]) -> None:
        """Finalize a proposal based on vote tally."""
        if proposal["status"] != ProposalStatus.ACTIVE:
            return

        total = proposal["votes_for"] + proposal["votes_against"]

        if total < self._quorum:
            proposal["status"] = ProposalStatus.EXPIRED
            logger.info(
                "Proposal %s expired: quorum not met (%d/%d)",
                proposal["proposal_id"], total, self._quorum,
            )
            return

        approval_rate = proposal["votes_for"] / total if total > 0 else 0

        if approval_rate >= self._approval_threshold:
            proposal["status"] = ProposalStatus.PASSED
            # Auto-execute: add to whitelist
            self._whitelist.add(proposal["token_address"])
            proposal["status"] = ProposalStatus.EXECUTED
            logger.info(
                "Proposal %s passed and executed: token %s added (%.0f%% approval)",
                proposal["proposal_id"],
                proposal["token_address"],
                approval_rate * 100,
            )
        else:
            proposal["status"] = ProposalStatus.REJECTED
            logger.info(
                "Proposal %s rejected: %.0f%% approval (needed %.0f%%)",
                proposal["proposal_id"],
                approval_rate * 100,
                self._approval_threshold * 100,
            )
