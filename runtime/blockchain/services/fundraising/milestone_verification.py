"""
MilestoneVerification — milestone tracking and verification for
community fundraising campaigns.

Verification methods:
- "oracle": external data verification via Component 11 (Oracle Gateway).
- "community_vote": community members vote on milestone completion.

Funds are released per milestone upon successful verification.
"""

from __future__ import annotations

import logging
import time
import uuid
from typing import Any

logger = logging.getLogger(__name__)

_VALID_METHODS = ("oracle", "community_vote")
_VALID_STATUSES = ("pending", "submitted", "verified", "rejected")


class MilestoneVerification:
    """Milestone verification engine for fundraising campaigns.

    Config keys (under ``config["fundraising"]``):
        community_vote_threshold (float): Approval % for community vote (default 0.66).
        oracle_timeout (int): Seconds to wait for oracle response (default 3600).
        min_voters (int): Minimum voters for community verification (default 5).
    """

    def __init__(
        self,
        config: dict,
        oracle_service: Any = None,
        voter_eligibility: Any = None,
    ) -> None:
        """
        NEW-73: ``voter_eligibility`` is an optional callable
        ``(campaign_id) -> set[str]`` returning the addresses entitled to vote
        on that campaign's milestones. When it is None the community-vote path
        FAILS CLOSED rather than tallying caller-supplied voter strings.
        """
        self._config = config
        self._voter_eligibility = voter_eligibility
        f_cfg: dict[str, Any] = config.get("fundraising", {})

        self._vote_threshold: float = float(
            f_cfg.get("community_vote_threshold", 0.66)
        )
        self._oracle_timeout: int = int(f_cfg.get("oracle_timeout", 3600))
        self._min_voters: int = int(f_cfg.get("min_voters", 5))

        self._oracle_service = oracle_service

        # (campaign_id, milestone_idx) -> milestone record
        self._milestones: dict[tuple[str, int], dict[str, Any]] = {}
        # (campaign_id, milestone_idx) -> [votes]
        self._milestone_votes: dict[tuple[str, int], list[dict]] = {}

        logger.info(
            "MilestoneVerification initialised (threshold=%.0f%%, min_voters=%d).",
            self._vote_threshold * 100, self._min_voters,
        )

    async def submit_milestone(
        self, campaign_id: str, milestone_idx: int, proof: dict
    ) -> dict:
        """Submit proof of milestone completion.

        Args:
            campaign_id: The campaign this milestone belongs to.
            milestone_idx: Zero-based milestone index.
            proof: Evidence dict with keys like 'description', 'documents',
                   'metrics', 'links'.

        Returns:
            Milestone submission record.
        """
        if not campaign_id:
            raise ValueError("Campaign ID is required")
        if milestone_idx < 0:
            raise ValueError("Milestone index must be non-negative")
        if not proof:
            raise ValueError("Proof of milestone completion is required")

        key = (campaign_id, milestone_idx)
        existing = self._milestones.get(key)

        if existing and existing["status"] == "verified":
            raise ValueError(
                f"Milestone {milestone_idx} for campaign {campaign_id} "
                f"is already verified"
            )

        now = int(time.time())
        record = {
            "submission_id": str(uuid.uuid4()),
            "campaign_id": campaign_id,
            "milestone_idx": milestone_idx,
            "proof": dict(proof),
            "status": "submitted",
            "submitted_at": now,
            "verified_at": None,
            "verification_method": None,
            "verification_result": None,
        }

        self._milestones[key] = record
        self._milestone_votes[key] = []

        logger.info(
            "Milestone submitted: campaign=%s idx=%d",
            campaign_id, milestone_idx,
        )
        return dict(record)

    async def verify_milestone(
        self, campaign_id: str, milestone_idx: int, method: str
    ) -> dict:
        """Verify a submitted milestone.

        Args:
            campaign_id: Campaign identifier.
            milestone_idx: Milestone index.
            method: "oracle" or "community_vote".

        Returns:
            Verification result.
        """
        if method not in _VALID_METHODS:
            raise ValueError(
                f"Verification method must be one of {_VALID_METHODS}, got '{method}'"
            )

        key = (campaign_id, milestone_idx)
        record = self._milestones.get(key)
        if not record:
            raise ValueError(
                f"Milestone {milestone_idx} for campaign {campaign_id} not found. "
                f"Submit the milestone first."
            )
        if record["status"] not in ("submitted", "pending"):
            raise ValueError(
                f"Milestone is {record['status']}, cannot verify"
            )

        record["verification_method"] = method
        now = int(time.time())

        if method == "oracle":
            result = await self._verify_via_oracle(record)
        else:
            result = await self._verify_via_community_vote(key)

        record["verification_result"] = result

        if result.get("approved"):
            record["status"] = "verified"
            record["verified_at"] = now
            logger.info(
                "Milestone verified: campaign=%s idx=%d method=%s",
                campaign_id, milestone_idx, method,
            )
        else:
            record["status"] = "rejected"
            logger.info(
                "Milestone rejected: campaign=%s idx=%d method=%s reason=%s",
                campaign_id, milestone_idx, method, result.get("reason", ""),
            )

        return {
            "campaign_id": campaign_id,
            "milestone_idx": milestone_idx,
            "method": method,
            "status": record["status"],
            "result": result,
            "verified_at": record["verified_at"],
        }

    def cast_community_vote(
        self, campaign_id: str, milestone_idx: int,
        voter: str, approve: bool,
    ) -> dict:
        """Cast a community verification vote on a milestone.

        Returns:
            Vote record.
        """
        key = (campaign_id, milestone_idx)
        record = self._milestones.get(key)
        if not record:
            raise ValueError(f"Milestone not found")
        if record["status"] != "submitted":
            raise ValueError(f"Milestone is {record['status']}, voting closed")

        votes = self._milestone_votes.setdefault(key, [])

        # Prevent double voting
        if any(v["voter"] == voter for v in votes):
            raise ValueError(f"Voter {voter} has already voted on this milestone")

        vote = {
            "voter": voter,
            "approve": approve,
            "voted_at": int(time.time()),
        }
        votes.append(vote)
        return vote

    async def _verify_via_oracle(self, record: dict) -> dict:
        """REFUSE. There is no authority on this platform that can attest a
        fundraising milestone, so this method declines instead of pretending.

        =====================================================================
        DO NOT "FIX" THIS BY POINTING IT AT OracleGateway.request().
        =====================================================================

        That is the repair this code invites, and it is the defect returning
        in a new costume. The history:

          * NEW-73 removed a self-attestation hole. The original code read the
            SUBMITTER'S OWN `proof` dict and approved on
            `description and (documents or metrics)`. The submitter writes
            that dict, so {"description": "done", "documents": ["x"]}
            released the funds.

          * NEW-73's replacement was `if self._oracle_service is None: refuse`
            — correct WHEN WRITTEN, because the registry constructs
            FundraisingService as cls(config) and an oracle could never be
            supplied.

          * NEW-59 then made the oracle resolvable (service.py `_resolve_oracle`).
            The None-branch became DEAD CODE. The live branch called
            `self._oracle_service.verify(proof)` — and `OracleGateway` HAS NO
            `verify` METHOD. Enumerated: price_feeds, vrf, weather, request,
            request_safe, query_price, request_vrf, query_weather, cache_stats,
            prune_caches, invalidate_cache. So every call raised
            AttributeError, was swallowed by `except Exception`, and returned
            "Oracle verification failed: ..." — which fails closed BY ACCIDENT
            and reads to an operator as a TRANSIENT outage rather than as
            "no such authority exists."

        The obvious repair is to change the method name to one that exists —
        `request_safe("custom", proof)`. DO NOT. `OracleGateway` dispatches
        five oracle types: price_feed, weather, sports, vrf, custom. NONE of
        them can observe whether a fundraising milestone was delivered. A
        price feed knows what ETH costs. `_handle_custom` takes `params` and
        works with what it is handed. `params` WOULD BE `proof`, AND `proof`
        IS WRITTEN BY THE PARTY WHO GETS PAID WHEN IT IS BELIEVED.

        §U — could the party bound by the decision have supplied its input?
        Here, yes, entirely. Routing the submitter's dict through a gateway
        does not make it evidence; it launders it. The result would be the
        NEW-73 hole with an oracle-shaped receipt attached, which is strictly
        worse than the original, because the original at least did not
        produce a document that says an oracle checked.

        LIFTING CONDITION — what must exist before this refusal is removed:

          An authority that verifies a FACT THE SUBMITTER DID NOT SUPPLY.

        Concretely, it must take as input something the submitter does not
        control, and report an observation made independently of them:

          * a named third-party attestor with its own key, signing a
            statement about the deliverable, where the signature is checked
            against a key registered BEFORE the campaign opened;
          * an on-chain fact the milestone was defined against in advance
            (a deployed contract address, a Merkle root committed at campaign
            creation, a token balance at a block height);
          * a delivery receipt from a counterparty with an adverse interest —
            the buyer, the auditor, the escrow agent.

        A URL in `proof` is not this. A hash of a document in `proof` is not
        this — it authenticates a file the submitter chose. An "oracle" that
        echoes `proof` back is not this. If the proposed authority's input can
        be traced back to the submitter, the condition is NOT met.

        Until then the honest answer is the one this returns: we cannot
        verify. `release_milestone_funds` refuses unless status == "verified",
        so this refusal holds the funds rather than releasing them, which is
        the conservative direction. The community-vote path
        (`_verify_via_community_vote`) remains available and is a DIFFERENT
        claim — it reports what voters said, not what happened.
        """
        logger.warning(
            "Milestone verification refused: no authority exists that can "
            "attest a fundraising milestone. campaign=%s",
            record.get("campaign_id"),
        )
        return {
            "approved": False,
            "method": "oracle",
            # Emitted on EVERY path now. The pre-fix live branch dropped this
            # field entirely, so the one machine-readable signal that
            # distinguishes "no authority exists" from "the authority said no"
            # was absent exactly when it was true.
            "authority_available": False,
            "verified": False,
            "reason": (
                "No verification authority is available for fundraising "
                "milestones. This is a deliberate refusal, not an outage. A "
                "milestone cannot be verified from proof supplied by the "
                "party who is paid when it is believed."
            ),
        }

    async def _verify_via_community_vote(
        self, key: tuple[str, int]
    ) -> dict:
        """Verify milestone via community vote tally.

        NEW-73: also fails closed, because this path is self-grantable too.

        cast_community_vote takes `voter` as a caller-supplied STRING. There
        is no signature, no eligibility check against contributors, and no
        exclusion of the campaign creator; double-voting is prevented only by
        string equality. So a submitter clears the default quorum by invoking
        it five times with five invented addresses — demonstrated: 5 votes,
        100% approval, status "verified".

        Both verification methods were therefore self-attestation, and a fix
        covering only the oracle path would have left this one open.

        The TALLY LOGIC BELOW IS REAL and is deliberately preserved rather
        than deleted — quorum, approval rate and threshold are genuine
        computations that a real voter set would need. What is missing is a
        way to know a vote came from someone entitled to cast it, and that
        cannot be decided at this layer: MilestoneVerification has no access
        to the contributor set, and WHO is entitled to vote (contributors?
        weighted by contribution? creator excluded?) is a governance design
        decision, not a defect fix. Choosing one here would be inventing a
        policy under cover of a security fix.

        LIFTING CONDITION: supply `voter_eligibility` — a callable returning
        the set of addresses entitled to vote on a given campaign — and this
        path re-opens with the tally intact.
        """
        if self._voter_eligibility is None:
            logger.warning(
                "Community-vote verification unavailable: no voter "
                "eligibility source configured. Refusing to count "
                "unverifiable votes."
            )
            return {
                "approved": False,
                "method": "community_vote",
                "authority_available": False,
                "reason": (
                    "Verification authority unavailable — voter identity "
                    "cannot be established. Votes are caller-supplied strings "
                    "with no eligibility check, so a tally over them would be "
                    "self-attestation."
                ),
            }

        votes = [
            v for v in self._milestone_votes.get(key, [])
            if v["voter"] in self._voter_eligibility(key[0])
        ]

        if len(votes) < self._min_voters:
            return {
                "approved": False,
                "method": "community_vote",
                "reason": (
                    f"Insufficient votes: {len(votes)} of {self._min_voters} "
                    f"minimum required"
                ),
                "votes_cast": len(votes),
                "min_required": self._min_voters,
            }

        approvals = sum(1 for v in votes if v["approve"])
        approval_rate = approvals / len(votes)

        return {
            "approved": approval_rate >= self._vote_threshold,
            "method": "community_vote",
            "approval_rate": approval_rate,
            "approvals": approvals,
            "rejections": len(votes) - approvals,
            "total_votes": len(votes),
            "threshold": self._vote_threshold,
            "reason": (
                "Community approved" if approval_rate >= self._vote_threshold
                else f"Approval rate {approval_rate:.0%} below threshold {self._vote_threshold:.0%}"
            ),
        }

    def get_milestone_status(self, campaign_id: str, milestone_idx: int) -> dict | None:
        """Get the current status of a milestone."""
        key = (campaign_id, milestone_idx)
        record = self._milestones.get(key)
        return dict(record) if record else None
