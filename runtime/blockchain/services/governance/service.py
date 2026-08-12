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

#: Voting models whose result depends on a token balance. `one_person_one_vote`
#: is deliberately absent: it returns 1.0 regardless of the weight passed in, so
#: a forged weight cannot move it.
_WEIGHT_DEPENDENT_MODELS = frozenset({"token_weighted", "quadratic"})

#: Options that constitute APPROVAL. `finalize` claims a proposal passed only
#: when the winning option is one of these. Options are arbitrary strings, so
#: for any other winner the service reports who won and declines to assert
#: passage — declining beats guessing on a governance outcome.
_APPROVAL_OPTIONS = frozenset({"yes", "approve", "for", "in_favour", "in_favor", "aye"})

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

        # CLUSTER A: the seam a real balance source plugs into. While it is
        # None, weight-dependent voting refuses (step 1) and no snapshot is
        # fabricated (step 2). Wiring it lifts both, in one place.
        self._balance_source = None

        # CLUSTER B: timelock records live HERE, not in _proposals. Writing
        # them into the proposal store under a `_timelock_` key made
        # list_proposals() raise KeyError: 'title'.
        self._timelocks: dict[str, dict[str, Any]] = {}

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
        # ── CLUSTER A, STEP 2: no snapshot is fabricated.
        #
        # This called `take_snapshot(proposal_id, {})`. An EMPTY dict is falsy,
        # so `check_vote`'s guard `if snapshot and snapshot_balance is not None`
        # skipped the entire flash-loan branch — the protection was present,
        # wired, and inert, and `get_flags()` returned [] for a voter with a
        # snapshot balance of 0.0 voting at weight 999999.
        #
        # Recording an empty snapshot is worse than recording none: it makes
        # the service look protected. With no balance source there is nothing
        # honest to snapshot, so nothing is stored, and `check_vote` now
        # REFUSES a weight-dependent vote whose snapshot is absent rather than
        # silently skipping (fail-closed).
        if self._balance_source is not None:                       # pragma: no cover
            balances = await self._balance_source.balances_at_now()
            self._anti_manipulation.take_snapshot(proposal_id, balances)

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

        # ── CLUSTER A, STEP 1: the weight is no longer the caller's to declare.
        #
        # `weight` arrived from the request body and was used as-is. Nothing
        # read a balance: this service has no web3, no token service, no
        # account manager, and no reference to any balance getter — verified by
        # inspecting its instance attributes. So a caller supplied their own
        # voting power and the platform recorded it as `effective_weight`.
        #
        # THE HONEST FORM IS THAT WEIGHTED VOTING IS UNAVAILABLE, NOT THAT IT
        # IS CALLER-ASSERTED. The two weight-dependent models are refused until
        # a real balance source is wired; `one_person_one_vote` is unaffected
        # because it discards the weight by construction (verified: it returns
        # 1.0 for an input of 999).
        #
        # FAIL-CLOSED: the refusal is on the ABSENCE of a source, so wiring one
        # lifts it and nothing else has to be remembered.
        model_name = proposal["voting_model"]
        if model_name in _WEIGHT_DEPENDENT_MODELS and self._balance_source is None:
            raise ValueError(
                f"Weighted voting is unavailable: the '{model_name}' model "
                "derives voting power from a token balance, and this service "
                "has no balance source wired. A caller-supplied weight would "
                "be voting power the voter asserted about themselves. Use "
                "'one_person_one_vote', or wire a balance source. "
                "(Cluster A step 1)"
            )

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

        # ── CLUSTER A, STEP 3: the outcome is derived from the RESULT, not
        # from the fact that someone voted.
        #
        # This was:
        #     proposal["status"] = "passed" if tally.get("winner") else "rejected"
        #
        # `tally["winner"]` is `max(totals, key=totals.get)` — an argmax, so it
        # is a non-empty string whenever ANY vote exists. The condition
        # therefore asked "did anyone vote?" while appearing to ask "did it
        # pass?". Driven: 999999 "no" against 1 "yes" finalized as PASSED. The
        # votes were counted correctly and then discarded one line later — the
        # same shape as NFT's discarded refusal and the dashboard's misspelled
        # key, now on the governance outcome itself.
        #
        # WHAT "PASSED" CAN HONESTLY MEAN. Options are arbitrary strings, so
        # this service cannot in general know which one constitutes approval.
        # It claims passage only when the winning option is a recognised
        # approval word; otherwise it reports the winner and does not assert
        # passage. Refusing to answer beats guessing, and `outcome_basis` says
        # which case applied so a reader is never left inferring.
        winner = tally.get("winner")
        if not quorum["quorum_met"]:
            outcome, basis = "rejected", "quorum not met"
        elif winner is None:
            outcome, basis = "rejected", "no votes cast"
        else:
            # The models report their margin under different key names —
            # token_weighted uses winner_weight/total_weight, one_person_one_vote
            # uses vote counts. Read the totals map, which every model returns,
            # rather than printing "None of None" into a governance outcome.
            totals = tally.get("totals") or {}
            margin = (
                f"{totals.get(winner)} of {sum(totals.values())}"
                if totals else "an unreported margin"
            )
            if winner in _APPROVAL_OPTIONS:
                outcome = "passed"
                basis = f"'{winner}' won with {margin}"
            else:
                outcome = "rejected"
                basis = (
                    f"'{winner}' won with {margin}; it is not an approval "
                    f"option ({sorted(_APPROVAL_OPTIONS)})"
                )
        proposal["status"] = outcome

        proposal["result"] = {
            "tally": tally,
            "quorum": quorum,
            "outcome": outcome,
            "outcome_basis": basis,
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

    async def list_proposals_detailed(self, dao_id: str | None = None) -> list:
        """List proposals in the MTRX client's ``Proposal`` shape.

        The client's DAO tab needs ``proposal_id, title, description, status,
        votes_for, votes_against, quorum, end_time`` (end_time as an ISO-8601
        string). The tally + quorum are extracted HERE — the voting-model
        knowledge lives on the server, never the client. Unknown tallies are an
        honest 0.0, never fabricated. ``dao_id`` is accepted for the route shape
        (proposals are global today) and reserved for per-DAO scoping.
        """
        from datetime import datetime, timezone

        out: list = []
        now = int(time.time())
        for pid, proposal in self._proposals.items():
            if proposal["status"] == "active" and now > proposal["ends_at"]:
                proposal["status"] = "expired"

            votes = self._votes.get(pid, [])
            model = get_voting_model(proposal["voting_model"])
            totals = (model.tally(votes) or {}).get("totals", {})

            def _pick(*keys: str) -> float:
                for k in keys:
                    if k in totals:
                        return float(totals[k])
                return 0.0

            votes_for = _pick("for", "yes", "approve", "aye")
            votes_against = _pick("against", "no", "reject", "nay")

            quorum_val = 0.0
            try:
                q = await self._quorum.check_quorum(
                    pid, votes=votes,
                    proposal_type=proposal.get("proposal_type", "standard"),
                    voting_model=model,
                )
                if isinstance(q, dict):
                    quorum_val = float(
                        q.get("required")
                        or q.get("threshold")
                        or q.get("quorum_required")
                        or q.get("total_required")
                        or 0.0
                    )
            except Exception:  # pragma: no cover — quorum is best-effort here
                quorum_val = 0.0

            out.append({
                "proposal_id": pid,
                "title": proposal.get("title", ""),
                "description": proposal.get("description", ""),
                "status": proposal["status"],
                "votes_for": votes_for,
                "votes_against": votes_against,
                "quorum": quorum_val,
                "end_time": datetime.fromtimestamp(
                    proposal.get("ends_at", now), tz=timezone.utc
                ).isoformat(),
            })

        out.sort(key=lambda p: p["end_time"], reverse=True)
        return out

    # ------------------------------------------------------------------
    # Internals
    # ------------------------------------------------------------------

    # ------------------------------------------------------------------
    # Expanded governance operations
    # ------------------------------------------------------------------

    async def queue_timelock(
        self, proposal_id: str, delay_seconds: int = 86400,
    ) -> dict:
        """Queue a passed proposal into a timelock."""
        # ── CLUSTER B. Two defects, and removing only the first leaves
        # listing broken, so both are fixed together.
        #
        # (a) THE CLAIM. "queued" says a passed proposal is now awaiting
        #     timelocked execution. It never looked the proposal up, never
        #     changed its status, and NOTHING EXECUTES a timelock anywhere in
        #     this repo — there is no executor, so `executable_at` is a date on
        #     which nothing will happen. Recorded, not queued.
        #
        # (b) THE STORE CORRUPTION. The record went into `self._proposals`
        #     under a `_timelock_` key, so `list_proposals()` — which assumes
        #     every value there is a proposal — raised `KeyError: 'title'`. A
        #     fabrication that also breaks a real read path: deleting the
        #     fabrication alone would have left listing broken, because the
        #     pollution is the store choice, not the claim.
        proposal = self._proposals.get(proposal_id)
        if not proposal:
            raise ValueError(f"Proposal {proposal_id} not found")

        tl_id = f"tl_{uuid.uuid4().hex[:16]}"
        now = int(time.time())
        record = {
            "id": tl_id,
            "status": "recorded_unqueued",
            "proposal_id": proposal_id,
            "delay_seconds": delay_seconds,
            "earliest_execution_if_built": now + delay_seconds,
            "recorded_at": now,
            "settled": False,
            "executed": False,
            "disclosure": (
                "RECORDED, NOT QUEUED. No timelock executor exists in this "
                "platform, so nothing will act on this record at any time. "
                "The target proposal's status is unchanged."
            ),
        }
        self._timelocks[tl_id] = record
        logger.info("Timelock queued: id=%s", tl_id)
        return record

    async def propose_multisig(
        self, proposer: str, signers: list[str], threshold: int, action: str, params: dict,
    ) -> dict:
        """Create a multisig proposal."""
        ms_id = f"ms_{uuid.uuid4().hex[:16]}"
        now = int(time.time())
        record = {
            "id": ms_id,
            "status": "proposed",
            "proposer": proposer,
            "signers": signers,
            "threshold": threshold,
            "action": action,
            "params": params,
            "approvals": [proposer],
            "proposed_at": now,
        }
        self._proposals[f"_multisig_{ms_id}"] = record
        logger.info("Multisig proposed: id=%s", ms_id)
        return record

    async def approve_multisig(
        self, multisig_id: str, signer: str,
    ) -> dict:
        """Approve a multisig proposal.

        CLUSTER B — REFUSES. Strip the claim and nothing remains: it minted
        `msa_<uuid>`, returned `"status": "approved"`, echoed its two arguments
        and a timestamp, and touched no store. Driven: every dict and list on
        the service is byte-identical before and after. It never checked the
        signer against the multisig's `signers`, never appended to its
        `approvals`, never evaluated the `threshold`.

        THE SUBSTRATE EXISTS, WHICH IS WHY THIS REFUSES RATHER THAN BEING
        DELETED. `propose_multisig` writes a real record with `signers`,
        `threshold` and an `approvals` list seeded with the proposer, so an
        honest approval is genuinely buildable local work — a multisig
        approval record IS the artifact. Building it is implementation, not
        audit, so the capability is marked unavailable and the condition names
        exactly what is already there to build on.

        LIFTING CONDITION — all of: resolve `multisig_id` in the
        `_multisig_*` records and refuse an unknown one; verify `signer` is in
        that record's `signers` and has not already approved; append to
        `approvals`; derive the returned status from `len(approvals) >=
        threshold` rather than asserting it; and bind `signer` to an
        authenticated caller (deferred register item 0 — otherwise anyone can
        approve as anyone).
        """
        raise NotImplementedError(
            "Multisig approval is unavailable: this method recorded nothing "
            "and checked nothing — it never verified the signer, never "
            "appended to the multisig's approvals, and never evaluated the "
            "threshold. An honest implementation is buildable against the "
            "existing `_multisig_*` records; until then an approval reported "
            "here would be an approval no multisig received. (Cluster B)"
        )

    async def snapshot_vote(
        self, proposal_id: str, voter: str, choice: str, block_number: int = 0,
    ) -> dict:
        """Cast an off-chain snapshot vote.

        CLUSTER B — REFUSES. Strip the claim and nothing remains: it minted a
        uuid, returned `"status": "cast"`, echoed its arguments, and touched no
        store. Driven: every dict and list on the service is byte-identical
        before and after.

        AND NOTHING LOCAL COULD SUBSTANTIATE IT. Snapshot is an EXTERNAL
        off-chain voting system; a vote is cast by signing a message and
        submitting it to a Snapshot hub. This platform has no hub client, no
        signer for it, and no space configuration — the gateway route already
        refuses `space` as unbuilt (NEW-89). So unlike a proposal or a
        membership, there is no local artifact that a record here could BE.

        LIFTING CONDITION — all of: a Snapshot hub endpoint; a signer that can
        produce the voter's EIP-712 signature (which this service cannot, as it
        holds no keys); a configured space; and a status derived from the hub's
        acknowledgement rather than asserted.
        """
        raise NotImplementedError(
            "Snapshot voting is unavailable: casting an off-chain Snapshot "
            "vote requires a Snapshot hub client and the voter's signature, "
            "neither of which exists in this platform. A record here would "
            "report a vote that was never submitted anywhere. (Cluster B)"
        )

    async def parameter_change(
        self, parameter: str, old_value: Any, new_value: Any, proposer: str,
    ) -> dict:
        """Propose a protocol parameter change."""
        pc_id = f"pc_{uuid.uuid4().hex[:16]}"
        record = {
            "id": pc_id,
            "status": "proposed",
            "parameter": parameter,
            "old_value": old_value,
            "new_value": new_value,
            "proposer": proposer,
            "proposed_at": int(time.time()),
        }
        self._proposals[f"_param_{pc_id}"] = record
        logger.info("Parameter change proposed: id=%s param=%s", pc_id, parameter)
        return record

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
