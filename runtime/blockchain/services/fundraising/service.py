"""
FundraisingService — community fundraising with milestone-based fund
release, vesting schedules, and automatic refunds.
"""

from __future__ import annotations

import logging
import math
import time
import uuid
from typing import Any

from runtime.blockchain.services.fundraising.milestone_verification import (
    MilestoneVerification,
)
from runtime.blockchain.services.fundraising.refunds import RefundManager
from runtime.blockchain.services.fundraising.vesting import VestingManager

logger = logging.getLogger(__name__)

_VALID_STATUSES = (
    "active", "funded", "milestone_in_progress",
    "completed", "failed", "refunding",
)

# ══════════════════════════════════════════════════════════════════════════
# ESCROW GATING CONDITION — READ BEFORE WIRING ANY REAL CUSTODY (NEW-75)
#
# THIS SERVICE MOVES NO MONEY. contribute() records a number, release computes
# a number, refund computes a number. Every "raised" / "released" / "refunded"
# figure is an entry in an in-process dict that does not survive a restart.
# That is the ONLY reason the defects below are latent instead of live.
#
# The moment any real custody is wired — an escrow contract, a payment
# processor, a treasury transfer — three conditions must ALL hold. They are
# coupled: satisfying two of three is not two-thirds safe, it is a specific
# fund-trap, and each partial state has its own failure mode. This is a
# checklist, not a list of suggestions.
#
#   [ ] 1. VERIFICATION IS AUTHORITY-GATED ON BOTH PATHS.               (NEW-73)
#          Milestone verification is the release trigger. Both routes to
#          "verified" were self-grantable by the beneficiary: the oracle path
#          read the submitter's own proof dict, and the community path counted
#          caller-supplied voter strings. Both now fail closed.
#          PARTIAL-STATE FAILURE MODE: if this is not satisfied, a campaign
#          creator self-approves a milestone and drains real contributor funds
#          through a release path that LOOKS authority-gated.
#
#   [ ] 2. RELEASE STAYS GATED ON THAT REAL VERIFICATION, AND REFUND IS
#          WIRED TO REAL FAILURE.                                       (NEW-74)
#          Refund was a complete pro-rata engine with no caller on the failure
#          path; it is now wired at all four failure-detection sites.
#          PARTIAL-STATE FAILURE MODE: release-only wiring is a one-way door —
#          money leaves on milestones and never returns on failure. Refund-only
#          wiring is the mirror: a campaign refunds funds it already released.
#
#   [ ] 3. contribute, release AND refund MIGRATE TO REAL CUSTODY IN ONE
#          CHANGE, OR NONE DO.                                          (NEW-75)
#          PARTIAL-STATE FAILURE MODE, and this is the clause most likely to
#          be violated by accident, because migrating one path at a time feels
#          incremental and safe:
#            * real contribute + dict refund  -> real money in, dict money out.
#              Contributors cannot be repaid. This is the fund-trap in its
#              purest form.
#            * real release + dict contribute -> the service pays out against
#              a balance nobody funded. This is a drain on the treasury.
#            * real refund + dict contribute  -> the service repays money it
#              never received.
#          There is no safe ordering. All three, or none.
#
# Attach this checklist to the config key that turns custody on. As of this
# writing no such key exists — config["fundraising"] has no escrow/contract
# address — and that absence is load-bearing, not an oversight.
#
# Pinned by tests/test_escrow_gating_condition.py, which fails if this block
# is removed or if any money path starts touching real value while the
# clauses are unmet.
# ══════════════════════════════════════════════════════════════════════════


def _require_finite_positive(value: Any, name: str) -> float:
    """20-A. A quantity that is not a finite positive number is not a quantity.

    `nan <= 0` is False and `nan < floor` is False, so every ordered guard in
    this module admits a NaN (§W's fifth shape). On a durable environmental
    claim a NaN or a negative tonnage is not a small amount — it is not an
    amount.
    """
    try:
        v = float(value)
    except (TypeError, ValueError):
        raise ValueError(f"{name} must be a number, got {value!r}") from None
    if not math.isfinite(v):
        raise ValueError(
            f"{name} must be a finite number, got {value!r} — a non-finite "
            f"value satisfies neither bound of a range check and passes both"
        )
    if v <= 0:
        raise ValueError(f"{name} must be positive, got {v}")
    return v


class FundraisingService:
    """Community fundraising service with milestone-based releases.

    Config keys (under ``config["fundraising"]``):
        max_campaign_days (int): Maximum campaign duration in days (default 90).
        min_goal (float): Minimum fundraising goal (default 100).
        max_milestones (int): Maximum milestones per campaign (default 10).
        All keys from VestingManager, MilestoneVerification, and
        RefundManager are also supported.
    """

    def __init__(self, config: dict, oracle_service: Any = None) -> None:
        self._config = config
        f_cfg: dict[str, Any] = config.get("fundraising", {})

        self._max_days: int = int(f_cfg.get("max_campaign_days", 90))
        self._min_goal: float = float(f_cfg.get("min_goal", 100.0))
        self._max_milestones: int = int(f_cfg.get("max_milestones", 10))

        self._vesting = VestingManager(config)
        # NEW-59 (fundraising instance). THE PARAGRAPH THAT USED TO SIT HERE
        # SAID "`oracle_service` is never supplied ... so this was always
        # None". That stopped being true on the line below it, which NEW-59
        # itself added: `_resolve_oracle()` supplies one. The comment went on
        # describing the world it had just ended, and it read as authoritative
        # BECAUSE it named the hazard precisely — an artifact that explicitly
        # names the failure it is committing reads as immune to it (§AM.3).
        #
        # The consequence was not cosmetic. NEW-73's fail-closed branch in
        # MilestoneVerification is keyed on `oracle_service is None`, so
        # supplying one turned that branch into DEAD CODE and moved execution
        # onto a live branch that called a method OracleGateway does not have.
        #
        # `_verify_via_oracle` now refuses unconditionally and explains why;
        # read its docstring before changing anything here, and in particular
        # before making this oracle "work".
        self._oracle_service = oracle_service
        self._milestones = MilestoneVerification(config, self._resolve_oracle())
        self._refunds = RefundManager(config)

        # campaign_id -> campaign record
        self._campaigns: dict[str, dict[str, Any]] = {}
        # campaign_id -> {contributor: total_amount}
        self._contributions: dict[str, dict[str, float]] = {}

        logger.info(
            "FundraisingService initialised (max_days=%d, min_goal=%.2f).",
            self._max_days, self._min_goal,
        )

    async def _fail_campaign(self, campaign: dict[str, Any]) -> dict | None:
        """Mark a campaign failed AND compute every contributor's refund.

        NEW-74: the refund half of the release/refund pair.

        Before this, failure detection set ``status = "failed"`` and stopped.
        RefundManager.process_refunds — a complete, correct pro-rata engine
        that reads each contribution, computes the share against
        (raised - released) and deducts the fee — had NO caller on the failure
        path. Refund was neither missing nor fake: it was an orphaned real
        mechanism. Release, meanwhile, fired on verification. That asymmetry
        is the fund-trap: an outflow path that triggers and an inflow-return
        path that never does.

        Wiring it here rather than at one call site is deliberate —
        assume-multiplicity. Failure is detected in FOUR places (contribute,
        get_campaign, list_campaigns, and trigger_refunds' own check), and a
        contributor's entitlement to a refund computation must not depend on
        which method happened to notice the deadline first. trigger_refunds
        keeps its own explicit call because it must RETURN the bulk result;
        process_refunds writes by (campaign_id, contributor) key, so a later
        recomputation overwrites rather than duplicates.

        STAYS DICT-CUSTODY. This computes and records refunds over the
        in-process ledger; it initiates no transfer. Every record carries
        settled=False / value_moved=False from the NEW-68 vocabulary fix, so
        wiring the trigger does not silently upgrade a calculation into a
        payment claim. Moving real funds is the deferred real-custody project
        and is gated by the compound escrow condition.
        """
        campaign["status"] = "failed"
        contribs = self._contributions.get(campaign["campaign_id"], {})
        if not contribs:
            return None
        return await self._refunds.process_refunds(
            campaign["campaign_id"],
            contributions=contribs,
            total_raised=campaign["raised"],
            total_released=campaign["released"],
        )

    def _resolve_oracle(self) -> Any:
        """Lazily resolve the OracleGateway (NEW-59, fundraising instance).

        Same template as the defi fix: the registry cannot inject an oracle,
        so resolve the registry-resolvable OracleGateway directly from config
        (its __init__ takes only config). It is itself credential-gated and
        returns errors when no feed is configured — which the verification
        path treats as "no authority" and FAILS CLOSED, rather than falling
        back to the submitter's own proof.

        Resolved eagerly in __init__ rather than on first use, because unlike
        a price lookup the dependency here decides whether an authority
        EXISTS; deferring it would leave the security posture dependent on
        call order.
        """
        if self._oracle_service is None:
            try:
                from runtime.blockchain.services.oracle_gateway import (
                    OracleGateway,
                )
                self._oracle_service = OracleGateway(self._config)
            except Exception as exc:  # noqa: BLE001 - resolution is best-effort
                # Fail closed: no authority resolved means verification
                # refuses, which is the safe direction.
                logger.warning(
                    "Oracle gateway could not be resolved (%s); milestone "
                    "verification will refuse rather than self-attest.", exc,
                )
                return None
        return self._oracle_service

    @property
    def vesting(self) -> VestingManager:
        return self._vesting

    @property
    def milestone_verification(self) -> MilestoneVerification:
        return self._milestones

    @property
    def refund_manager(self) -> RefundManager:
        return self._refunds

    # ------------------------------------------------------------------
    # Campaign lifecycle
    # ------------------------------------------------------------------

    async def create_campaign(
        self,
        creator: str,
        title: str,
        goal: float,
        deadline_days: int,
        milestones: list,
    ) -> dict:
        """Create a new fundraising campaign.

        Args:
            creator: Campaign creator wallet address.
            title: Campaign title.
            goal: Fundraising goal amount.
            deadline_days: Days until campaign deadline.
            milestones: List of milestone dicts, each with 'title',
                        'description', and 'release_pct' (percentage of
                        funds released upon verification).

        Returns:
            Campaign record.
        """
        if not creator:
            raise ValueError("Creator address is required")
        if not title:
            raise ValueError("Campaign title is required")
        # 20-C. EVERY ordered guard below admits a NaN: `nan < floor` is
        # False, `nan <= 0` is False, `nan > cap` is False. A NaN satisfies
        # neither bound of a range check and therefore passes BOTH.
        goal = _require_finite_positive(goal, "goal")
        deadline_days = _require_finite_positive(deadline_days, "deadline_days")
        if goal < self._min_goal:
            raise ValueError(f"Goal must be at least {self._min_goal}")
        if deadline_days <= 0:
            raise ValueError("Deadline must be positive")
        if deadline_days > self._max_days:
            raise ValueError(
                f"Campaign duration cannot exceed {self._max_days} days"
            )
        if not milestones:
            raise ValueError("At least one milestone is required")
        if len(milestones) > self._max_milestones:
            raise ValueError(
                f"Maximum {self._max_milestones} milestones allowed"
            )

        # 20-E. §I.13 — THE GUARD VALIDATED A DIFFERENT VALUE THAN THE ONE
        # STORED. The check was `sum(m.get("release_pct", 0) ...)`; the store
        # below was `m.get("release_pct", 100 / len(milestones))`. TWO
        # DIFFERENT DEFAULTS FOR ONE KEY: an absent key contributed 0 to the
        # conservation check and a FULL SHARE to the stored schedule.
        #
        # MEASURED at the pin, two milestones, the second omitting the key:
        #     guard sees 100 -> passes
        #     stored         -> [100, 50.0] = 150%
        #     released       -> campaign["released"] = 1500.0 on raised 1000.0
        #     campaign then marks itself "completed"
        #
        # 150% of contributor money released, by a campaign creator, using a
        # field they simply left out. Not malformed input — ABSENT input.
        #
        # The fix is not a better default. It is to NORMALISE ONCE and then
        # validate THE NORMALISED LIST, so the conservation check and the
        # release schedule cannot disagree by construction (§T.4): there is
        # now no second value for them to disagree about.
        normalised_pcts: list[float] = []
        for i, m in enumerate(milestones):
            if not isinstance(m, dict):
                raise ValueError(f"Milestone {i} must be an object")
            if "release_pct" not in m:
                raise ValueError(
                    f"Milestone {i} does not declare `release_pct`. It is not "
                    f"inferred: a missing share silently became a full share, "
                    f"and the sum that was checked was not the sum that was "
                    f"spent."
                )
            normalised_pcts.append(
                _require_finite_positive(m["release_pct"], f"milestone[{i}].release_pct")
            )

        total_pct = sum(normalised_pcts)
        if abs(total_pct - 100.0) > 0.01:
            raise ValueError(
                f"Milestone release percentages must sum to 100, got {total_pct}"
            )

        campaign_id = str(uuid.uuid4())
        now = int(time.time())

        processed_milestones = []
        for i, m in enumerate(milestones):
            processed_milestones.append({
                "idx": i,
                "title": m.get("title", f"Milestone {i + 1}"),
                "description": m.get("description", ""),
                # 20-E. Reads the SAME list the conservation check summed.
                "release_pct": normalised_pcts[i],
                "status": "pending",
                "released_amount": 0.0,
            })

        campaign = {
            "campaign_id": campaign_id,
            "creator": creator,
            "title": title,
            "goal": goal,
            "raised": 0.0,
            "released": 0.0,
            "contributor_count": 0,
            "deadline": now + (deadline_days * 86400),
            "deadline_days": deadline_days,
            "milestones": processed_milestones,
            "status": "active",
            "created_at": now,
            "funded_at": None,
            "completed_at": None,
        }

        self._campaigns[campaign_id] = campaign
        self._contributions[campaign_id] = {}

        logger.info(
            "Campaign created: id=%s title='%s' goal=%.2f deadline=%dd milestones=%d",
            campaign_id, title, goal, deadline_days, len(milestones),
        )
        return dict(campaign)

    async def contribute(
        self, campaign_id: str, contributor: str, amount: float
    ) -> dict:
        """Contribute funds to a campaign.

        Args:
            campaign_id: Target campaign.
            contributor: Contributor wallet address.
            amount: Contribution amount.

        Returns:
            Contribution record.
        """
        campaign = self._campaigns.get(campaign_id)
        if not campaign:
            raise ValueError(f"Campaign {campaign_id} not found")
        if campaign["status"] != "active":
            raise ValueError(
                f"Campaign is {campaign['status']}, not accepting contributions"
            )
        amount = _require_finite_positive(amount, "amount")
        if amount <= 0:
            raise ValueError("Contribution amount must be positive")

        now = int(time.time())
        if now > campaign["deadline"]:
            # Check if goal was met
            if campaign["raised"] < campaign["goal"]:
                await self._fail_campaign(campaign)   # NEW-74
                raise ValueError(
                    "Campaign deadline has passed without meeting goal"
                )

        # Record contribution
        contribs = self._contributions[campaign_id]
        prev = contribs.get(contributor, 0.0)
        contribs[contributor] = prev + amount

        if prev == 0:
            campaign["contributor_count"] += 1

        campaign["raised"] += amount

        # Check if goal reached
        if campaign["raised"] >= campaign["goal"] and campaign["funded_at"] is None:
            campaign["funded_at"] = now
            campaign["status"] = "funded"
            logger.info("Campaign funded: id=%s raised=%.2f", campaign_id, campaign["raised"])

        contribution = {
            "contribution_id": str(uuid.uuid4()),
            "campaign_id": campaign_id,
            "contributor": contributor,
            "amount": amount,
            "total_contributed": contribs[contributor],
            "campaign_raised": campaign["raised"],
            "campaign_goal": campaign["goal"],
            "progress_pct": (campaign["raised"] / campaign["goal"] * 100),
            "contributed_at": now,
        }

        logger.info(
            "Contribution: campaign=%s contributor=%s amount=%.4f total_raised=%.4f",
            campaign_id, contributor, amount, campaign["raised"],
        )
        return contribution

    async def get_campaign(self, campaign_id: str) -> dict:
        """Get full campaign details.

        Includes auto-fail check if deadline passed without meeting goal.

        Returns:
            Campaign record with contributions summary.
        """
        campaign = self._campaigns.get(campaign_id)
        if not campaign:
            raise ValueError(f"Campaign {campaign_id} not found")

        # Auto-fail check
        now = int(time.time())
        if (campaign["status"] == "active"
                and now > campaign["deadline"]
                and campaign["raised"] < campaign["goal"]):
            await self._fail_campaign(campaign)   # NEW-74
            logger.info(
                "Campaign auto-failed, refunds computed: id=%s", campaign_id
            )

        result = dict(campaign)
        result["milestones"] = [dict(m) for m in campaign["milestones"]]

        contribs = self._contributions.get(campaign_id, {})
        result["contributions_summary"] = {
            "total_contributors": len(contribs),
            "total_raised": campaign["raised"],
            "goal": campaign["goal"],
            "progress_pct": (campaign["raised"] / campaign["goal"] * 100) if campaign["goal"] > 0 else 0,
        }

        return result

    async def list_campaigns(self, status: str | None = None) -> list:
        """List all campaigns, optionally filtered by status.

        Returns:
            List of campaign summaries.
        """
        results = []
        now = int(time.time())

        for campaign in self._campaigns.values():
            # Auto-fail check
            if (campaign["status"] == "active"
                    and now > campaign["deadline"]
                    and campaign["raised"] < campaign["goal"]):
                await self._fail_campaign(campaign)   # NEW-74

            if status is not None and campaign["status"] != status:
                continue

            results.append({
                "campaign_id": campaign["campaign_id"],
                "title": campaign["title"],
                "creator": campaign["creator"],
                "goal": campaign["goal"],
                "raised": campaign["raised"],
                "progress_pct": (campaign["raised"] / campaign["goal"] * 100) if campaign["goal"] > 0 else 0,
                "contributor_count": campaign["contributor_count"],
                "status": campaign["status"],
                "deadline": campaign["deadline"],
                "created_at": campaign["created_at"],
            })

        results.sort(key=lambda c: c["created_at"], reverse=True)
        return results

    # ------------------------------------------------------------------
    # Milestone-triggered fund release
    # ------------------------------------------------------------------

    async def release_milestone_funds(
        self, campaign_id: str, milestone_idx: int
    ) -> dict:
        """Release funds for a verified milestone.

        Only releases if the milestone has been verified.

        Returns:
            Release record.
        """
        campaign = self._campaigns.get(campaign_id)
        if not campaign:
            raise ValueError(f"Campaign {campaign_id} not found")

        if milestone_idx < 0 or milestone_idx >= len(campaign["milestones"]):
            raise ValueError(f"Invalid milestone index {milestone_idx}")

        milestone = campaign["milestones"][milestone_idx]
        if milestone["status"] == "released":
            raise ValueError(f"Milestone {milestone_idx} funds already released")

        # Check verification status via MilestoneVerification
        ms_status = self._milestones.get_milestone_status(campaign_id, milestone_idx)
        if not ms_status or ms_status["status"] != "verified":
            raise ValueError(
                f"Milestone {milestone_idx} must be verified before funds can be released"
            )

        release_amount = campaign["raised"] * (milestone["release_pct"] / 100.0)
        milestone["status"] = "released"
        milestone["released_amount"] = release_amount
        campaign["released"] += release_amount

        # Check if all milestones completed
        all_released = all(m["status"] == "released" for m in campaign["milestones"])
        if all_released:
            campaign["status"] = "completed"
            campaign["completed_at"] = int(time.time())
            logger.info("Campaign completed: id=%s", campaign_id)

        logger.info(
            "Milestone funds released: campaign=%s idx=%d amount=%.4f",
            campaign_id, milestone_idx, release_amount,
        )
        return {
            "campaign_id": campaign_id,
            "milestone_idx": milestone_idx,
            "release_amount": release_amount,
            "total_released": campaign["released"],
            "remaining": campaign["raised"] - campaign["released"],
            "campaign_status": campaign["status"],
        }

    async def trigger_refunds(self, campaign_id: str) -> dict:
        """Trigger refunds for a failed campaign.

        Auto-refund if campaign failed, or pro-rata if milestone failed.

        Returns:
            Bulk refund result.
        """
        campaign = self._campaigns.get(campaign_id)
        if not campaign:
            raise ValueError(f"Campaign {campaign_id} not found")

        if campaign["status"] not in ("failed", "milestone_failed", "refunding"):
            # Check auto-fail
            now = int(time.time())
            if (campaign["status"] == "active"
                    and now > campaign["deadline"]
                    and campaign["raised"] < campaign["goal"]):
                campaign["status"] = "failed"
            else:
                raise ValueError(
                    f"Campaign {campaign_id} is {campaign['status']}, "
                    f"refunds only available for failed campaigns"
                )

        campaign["status"] = "refunding"

        contribs = self._contributions.get(campaign_id, {})
        result = await self._refunds.process_refunds(
            campaign_id,
            contributions=contribs,
            total_raised=campaign["raised"],
            total_released=campaign["released"],
        )

        logger.info(
            "Refund amounts calculated (NOT paid): campaign=%s contributors=%d",
            campaign_id, result["contributors_calculated"],
        )
        return result

    # ------------------------------------------------------------------
    # Energy and sustainability operations
    # ------------------------------------------------------------------

    async def buy_carbon_credit(
        self, buyer: str, amount: float, project: str = "", vintage_year: int = 0,
    ) -> dict:
        """Purchase carbon credits."""
        credit_id = f"cc_{uuid.uuid4().hex[:16]}"
        now = int(time.time())
        # 20-A. `tonnes_remaining` is the registry's balance and the ONLY
        # field `retire_carbon_credit` may decrement. Without it a retirement
        # had nothing to check itself against.
        amount = _require_finite_positive(amount, "amount")
        record: dict[str, Any] = {
            "id": credit_id,
            "status": "purchased",
            "buyer": buyer,
            "amount": amount,
            "project": project,
            "vintage_year": vintage_year or 2024,
            "tonnes_co2": amount,
            "tonnes_remaining": amount,
            "purchased_at": now,
            # 20-B. The dispatcher reads these FIRST to decide whether to
            # attest and publish. They had ZERO writers here, so all four
            # green actions were published to the durable public feed as real
            # outcomes. Nothing is settled and no value moves — this is an
            # in-process record.
            "settled": False,
            "value_moved": False,
            "disclosure": (
                "Recorded in the platform's own registry. No credit was "
                "acquired from a registry operator and no value moved."
            ),
        }
        self._campaigns[f"_carbon_{credit_id}"] = record
        logger.info("Carbon credit purchased: id=%s", credit_id)
        return record

    async def retire_carbon_credit(
        self, holder: str, credit_id: str, tonnes: float,
    ) -> dict:
        """Retire carbon credits to offset emissions."""
        # 20-A. A RETIREMENT IS A CLAIM SOMEONE OUTSIDE THE PLATFORM RELIES ON.
        #
        # This method read NO field of any credit record and decremented
        # nothing. MEASURED at pin e6cbc018: a credit_id that was never
        # purchased returned status "retired"; the SAME id retired twice
        # returned "retired" both times; NEGATIVE tonnage was accepted — and
        # the record carried `tonnes=None`, so it did not even carry the
        # quantity it claimed to retire. Unbounded, any caller, any id.
        #
        # §E.18 with the worst subject matter in the census: a retired carbon
        # credit is a representation about an environmental commodity, relied
        # on by an offset registry, a disclosure, or a regulator. Unlike a
        # wrong internal balance, THE COUNTERPARTY FOR THIS RECORD IS OUTSIDE
        # THE PLATFORM, and the retirement was attested and published to the
        # durable public feed as a real outcome (20-B).
        #
        # ALREADY-PUBLISHED RETIREMENTS ARE NOT RETRACTED BY THIS FIX. Feed
        # rows attesting retirements of credits that were never purchased
        # persist. Same shape as the qr_secret prerequisite: a fix that stops
        # new false records does not withdraw the old ones. Whether that is
        # actionable is an operator decision, recorded in the close.
        tonnes = _require_finite_positive(tonnes, "tonnes")
        credit = self._campaigns.get(f"_carbon_{credit_id}")
        if credit is None:
            raise ValueError(
                f"credit {credit_id!r} is not in the registry — nothing to "
                f"retire. A retirement names a credit that was purchased."
            )
        if str(credit.get("buyer", "")).lower() != str(holder).lower():
            raise PermissionError(
                f"{holder!r} does not hold credit {credit_id!r}; it belongs to "
                f"{credit.get('buyer')!r}."
            )
        remaining = float(credit.get("tonnes_remaining", 0.0))
        if tonnes > remaining:
            raise ValueError(
                f"cannot retire {tonnes} tonnes of credit {credit_id!r}: only "
                f"{remaining} remain. Retiring more than was bought is a "
                f"double-count of the same offset."
            )
        credit["tonnes_remaining"] = remaining - tonnes
        if credit["tonnes_remaining"] <= 0:
            credit["status"] = "retired"

        retire_id = f"ccr_{uuid.uuid4().hex[:16]}"
        now = int(time.time())
        record: dict[str, Any] = {
            "id": retire_id,
            "status": "retired",
            "holder": holder,
            "credit_id": credit_id,
            "tonnes_retired": tonnes,
            "tonnes_remaining": credit["tonnes_remaining"],
            "retired_at": now,
            "settled": False,
            "value_moved": False,
            "disclosure": (
                "Retired in the platform's own registry only. No retirement "
                "was filed with an external offset registry."
            ),
        }
        self._campaigns[f"_retire_{retire_id}"] = record
        logger.info("Carbon credit retired: id=%s", retire_id)
        return record

    async def buy_renewable_cert(
        self, buyer: str, energy_mwh: float, source: str = "solar", region: str = "",
    ) -> dict:
        """Purchase a renewable energy certificate."""
        cert_id = f"rec_{uuid.uuid4().hex[:16]}"
        now = int(time.time())
        energy_mwh = _require_finite_positive(energy_mwh, "energy_mwh")
        record: dict[str, Any] = {
            "id": cert_id,
            "status": "purchased",
            "buyer": buyer,
            "energy_mwh": energy_mwh,
            "source": source,
            "region": region,
            "purchased_at": now,
            # 20-B. Four green actions share this; fixing the two carbon ones
            # and leaving these would be §AK.2's half-fix in the remediation.
            "settled": False,
            "value_moved": False,
            "disclosure": (
                "Recorded in the platform's own registry. No certificate was "
                "acquired from a registry operator and no value moved."
            ),
        }
        self._campaigns[f"_rec_{cert_id}"] = record
        logger.info("Renewable cert purchased: id=%s", cert_id)
        return record

    async def invest_green_bond(
        self, investor: str, amount: float, bond_name: str = "", maturity_years: int = 5,
    ) -> dict:
        """Invest in a green bond."""
        bond_id = f"gb_{uuid.uuid4().hex[:16]}"
        now = int(time.time())
        amount = _require_finite_positive(amount, "amount")
        record: dict[str, Any] = {
            "id": bond_id,
            "status": "invested",
            "investor": investor,
            "amount": amount,
            "settled": False,
            "value_moved": False,
            "disclosure": (
                "Recorded in the platform's own registry. No bond was "
                "purchased from an issuer and no value moved."
            ),
            "bond_name": bond_name,
            "maturity_years": maturity_years,
            "invested_at": now,
        }
        self._campaigns[f"_bond_{bond_id}"] = record
        logger.info("Green bond investment: id=%s", bond_id)
        return record
