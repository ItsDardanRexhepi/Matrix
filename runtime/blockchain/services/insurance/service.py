"""
InsuranceService — Parametric insurance for the Matrix platform.

Supports weather, flight delay, crop, earthquake, and smart-contract-hack
policies.  Claims are automatically triggered when oracle data confirms
the parametric condition, removing the need for manual adjudication.
"""

from __future__ import annotations

import logging
import time
import uuid
from typing import Any

from runtime.blockchain.services.insurance._guards import (
    effective_caller,
    require_finite_money,
)
from runtime.blockchain.services.insurance._predicate import (
    PredicateError,
    build_predicate,
)

from runtime.blockchain.services.ownership import assert_owner
from runtime.blockchain.services.insurance.eligibility import EligibilityTracker
from runtime.blockchain.services.insurance.fee_engine import FeeEngine
from runtime.blockchain.services.insurance.trigger_manager import TriggerManager
from runtime.blockchain.services.insurance.reserve_fund import ReserveFund
from runtime.blockchain.services.insurance.claims_processor import ClaimsProcessor
from runtime.blockchain.web3_manager import Web3Manager, not_deployed_response

logger = logging.getLogger(__name__)

POLICY_TYPES: set[str] = {
    "weather",
    "flight_delay",
    "crop",
    "earthquake",
    "smart_contract_hack",
}


class InsuranceService:
    """Main parametric insurance service.

    Config keys (under ``config["insurance"]``):
        default_duration_days, max_coverage, platform_wallet.

    Also reads ``config["blockchain"]`` for attestation and oracle wiring.
    """

    def __init__(self, config: dict) -> None:
        self._config = config
        ins_cfg: dict[str, Any] = config.get("insurance", {})

        self._default_duration: int = int(ins_cfg.get("default_duration_days", 365))
        self._max_coverage: float = float(ins_cfg.get("max_coverage", 1_000_000.0))
        self._policy_contract: str = ins_cfg.get("policy_contract", "") or ""
        self._web3 = Web3Manager.get_shared(config)

        self._eligibility = EligibilityTracker(config)
        self._fee_engine = FeeEngine(config)
        self._trigger_manager = TriggerManager(config)
        self._reserve_fund = ReserveFund(config)
        self._claims_processor = ClaimsProcessor(config, self._reserve_fund)

        # In-memory store; production would back this with a database.
        self._policies: dict[str, dict[str, Any]] = {}
        self._claims: dict[str, dict[str, Any]] = {}

        # 18-J. The reserve's solvency gate weighed only the policy being
        # written, because the exposure counter it read had no writers. It now
        # asks the policy book directly, on every decision.
        self._reserve_fund.set_exposure_provider(self._active_exposure)

        logger.info("InsuranceService initialised.")

    # ------------------------------------------------------------------
    # Policy lifecycle
    # ------------------------------------------------------------------

    def _active_exposure(self) -> float:
        """Total coverage the platform is on the hook for RIGHT NOW. 18-J.

        Derived from the policy book rather than accumulated, so a lapse or a
        payout is reflected without an event to hook. A policy counts only
        while it is `active` AND unexpired: an expired policy cannot be
        claimed against (`file_claim` and `auto_settle_claim` both refuse it),
        so counting it would over-state exposure and refuse honest business.
        """
        now = int(time.time())
        return sum(
            float(p.get("coverage", {}).get("amount", 0.0))
            for p in self._policies.values()
            if p.get("status") == "active" and int(p.get("expires_at", 0)) > now
        )

    async def create_policy(
        self,
        holder: str,
        policy_type: str,
        coverage: dict,
        premium: float,
    ) -> dict:
        """Create a new parametric insurance policy.

        Args:
            holder: Address of the policyholder.
            policy_type: One of the supported POLICY_TYPES.
            coverage: Dict with ``amount``, ``duration_days``, and
                      type-specific parameters (e.g. ``location`` for weather).
            premium: Premium amount paid by the holder.

        Returns:
            Created policy record.
        """
        if policy_type not in POLICY_TYPES:
            raise ValueError(
                f"Unknown policy_type '{policy_type}'. "
                f"Must be one of: {', '.join(sorted(POLICY_TYPES))}"
            )

        if (
            not self._web3.available
            or self._web3.is_placeholder(self._policy_contract)
        ):
            logger.warning(
                "Service %s called but contract not deployed",
                self.__class__.__name__,
            )
            return not_deployed_response("insurance", {
                "operation": "create_policy",
                "requested": {
                    "holder": holder,
                    "policy_type": policy_type,
                    "premium": premium,
                },
            })

        # 18-B. THE BOUNDED RANGE BELOW CANNOT SEE NaN. `nan <= 0` is False and
        # `nan > max` is False, so a NaN coverage satisfies NEITHER bound and
        # passes both — §W's fifth shape, in the method that SETS THE PAYOUT
        # (`approve_claim` pays out `float(policy["coverage"]["amount"])`).
        # Rejected before the comparisons that are supposed to reject it.
        coverage_amount = require_finite_money(
            coverage.get("amount", 0), "coverage.amount")
        if coverage_amount <= 0:
            raise ValueError("coverage.amount must be positive")
        if coverage_amount > self._max_coverage:
            raise ValueError(
                f"coverage.amount {coverage_amount} exceeds max {self._max_coverage}"
            )

        duration_days = int(coverage.get("duration_days", self._default_duration))

        # Check eligibility
        elig = await self._eligibility.check_eligibility(holder, policy_type)
        if not elig.get("eligible", False):
            return {
                "status": "rejected",
                "reason": elig.get("reason", "Not eligible"),
                "eligibility": elig,
            }

        # 18-P. The predicate is built BEFORE pricing, because the premium now
        # depends on it. Building it first also means an unissuable predicate
        # is refused before any of the work below runs.
        trigger_conditions = self._build_trigger_conditions(policy_type, coverage)

        # Calculate expected premium
        risk_factors = coverage.get("risk_factors", {})
        premium_calc = await self._fee_engine.calculate_premium(
            policy_type, coverage_amount, duration_days, risk_factors,
            trigger_conditions=trigger_conditions,
        )
        expected_premium = premium_calc["total_premium"]

        # 18-B: `nan < expected` is False, so a NaN premium walked through the
        # sufficiency check as well — the policy is priced by a number that is
        # not one.
        premium = require_finite_money(premium, "premium", allow_zero=True)
        if premium < expected_premium:
            return {
                "status": "rejected",
                "reason": (
                    f"Premium {premium} is below required {expected_premium}"
                ),
                "premium_required": expected_premium,
            }

        # Check reserve solvency
        solvency = await self._reserve_fund.check_solvency(coverage_amount)
        if not solvency.get("solvent", False):
            return {
                "status": "rejected",
                "reason": "Reserve fund insufficient for additional coverage",
                "solvency": solvency,
            }

        now = int(time.time())
        policy_id = f"pol_{uuid.uuid4().hex[:16]}"

        policy: dict[str, Any] = {
            "policy_id": policy_id,
            "holder": holder,
            "policy_type": policy_type,
            "coverage": {
                "amount": coverage_amount,
                "duration_days": duration_days,
                **{k: v for k, v in coverage.items()
                   if k not in ("amount", "duration_days", "risk_factors")},
            },
            "premium_paid": premium,
            "premium_breakdown": premium_calc,
            "status": "active",
            "created_at": now,
            "expires_at": now + duration_days * 86400,
        }

        self._policies[policy_id] = policy

        # Register auto-trigger if applicable (built above, before pricing)
        if trigger_conditions:
            trigger = await self._trigger_manager.register_trigger(
                policy_id, policy_type, trigger_conditions,
            )
            policy["trigger_id"] = trigger.get("trigger_id")

        # Record in eligibility history
        await self._eligibility.record_policy(holder, policy)

        logger.info(
            "Policy created: id=%s type=%s holder=%s coverage=%s",
            policy_id, policy_type, holder, coverage_amount,
        )
        return policy

    async def file_claim(
        self,
        policy_id: str,
        caller: str | None = None,
        caller_identity: str = "",
        caller_source: str | None = None,
    ) -> dict:
        """File a claim against a policy. NEW-78.

        TWO HOLES CLOSED HERE, and neither alone was sufficient.

        (1) OWNERSHIP. This took no caller identity at all — it read `holder`
            from the STORED policy, so anyone who learned a policy id could
            claim against a stranger's policy. Same shape as domain 4's
            authorize_payment. `caller` is now required and asserted against
            policy["holder"] through the shared primitive (NEW-77).

        (2) SELF-ATTESTED TRIGGER. The `trigger_data` parameter is GONE, not
            guarded. It was the claimant's own dict, and
            ClaimsProcessor._verify_trigger compared it against the policy's
            parametric condition — a condition the claimant can read and then
            satisfy. The docstring called it "Oracle / parametric data proving
            the event occurred"; it was proof the claimant wrote. Verification
            now runs against data fetched from the OracleGateway through
            TriggerManager, and FAILS CLOSED when no trigger or no oracle is
            available.

        Fixing ownership alone would still let the true holder self-approve a
        fraudulent claim; fixing the trigger alone would still let anyone file
        on a policy they do not hold. Both, or neither.

        SURFACE CAVEAT — WHERE THIS CHECK IS REAL, AND WHERE IT IS NOT.
        `assert_owner` can only compare the caller it is HANDED. It is a real
        authorization control exactly as far as the identity reaching it is
        authenticated, and that differs by surface:

          gateway route  /api/v1/insurance/claim  ENFORCING ONLY WITH A
                         SESSION. The handler binds `caller` from
                         current_request_security(), and a body-supplied
                         `holder` cannot override a bound identity. That
                         identity is derived only when a session is presented.
                         Without one it is the X-Wallet-Address header or a
                         body wallet/from/sender/account field, written by the
                         caller (who holds the operator key, or is on a gateway
                         with auth off), and with none of those the body
                         `holder` is used. On that path the check compares
                         the policy holder with an address the caller chose.
          ServiceDispatcher  `file_insurance_claim` / `cancel_insurance`
                         NOT ENFORCING. execute() does `await method(**params)`
                         with caller-supplied params, so an attacker simply
                         passes caller="<victim>". Verified live, not inferred.

        This is filed as NEW-82: identity binding is missing at the dispatcher
        seam, and it is NOT specific to insurance — every service method that
        takes a caller/holder/creator argument has the same property there.
        Recorded here rather than half-patched, because a per-method guard in
        one service would make the seam look audited while leaving the general
        case open, which is the failure NEW-77 exists to prevent.

        18-C [2026-08-13] — NEW-82's STATED BLOCKER HAS BEEN REMOVED, AND THE
        FINDING IS STILL OPEN. Both halves matter.

        REMOVED: 17-D built the identity binding this deferral said was missing.
        `ServiceDispatcher.execute` now takes a keyword-only `caller_identity`,
        `gateway/bridge.py` and `runtime/capabilities/registry.py` both pass the
        wallet the security middleware already bound, and the dispatcher injects
        it into the service call. The seam NEW-82 described as absent EXISTS.

        STILL OPEN: the injection is SIGNATURE-GATED on the exact parameter name
        `caller_identity`. Measured — `file_claim(policy_id, caller)`,
        `cancel_policy(policy_id, caller)`, `renew_coverage(...)` and
        `auto_settle_claim(...)` are each reached: False. THE NAMES DO NOT MATCH,
        so an attacker still passes `caller="<victim>"` exactly as recorded.

        NOT PATCHED HERE, AND DELIBERATELY. Renaming these four parameters would
        close it for insurance and leave every other service's caller/holder/
        creator argument unbound — which is the precise failure this deferral was
        written to avoid, so the original ruling STANDS ON ITS OWN TERMS and is
        not overturned. What changed is the cost: the platform-wide fix (map
        caller/holder/creator to the threaded identity AT the dispatcher) is
        now a real option rather than a missing subsystem.

        RECORDED BECAUSE A DEFERRAL THAT CITES A VANISHED BLOCKER AGES INTO A
        FALSE ONE — 16-U's shape pointed forward. A reader finding this note
        without this paragraph would conclude the mechanism does not exist, and
        would be wrong.
        """
        policy = self._policies.get(policy_id)
        if not policy:
            raise ValueError(f"Policy {policy_id} not found")

        assert_owner(
            effective_caller(caller, caller_identity, caller_source),
            policy, owner_field="holder", what="policy",
        )

        if policy["status"] != "active":
            return {
                "status": "rejected",
                "reason": f"Policy status is '{policy['status']}', not active",
            }

        now = int(time.time())
        if now > policy["expires_at"]:
            policy["status"] = "expired"
            return {"status": "rejected", "reason": "Policy has expired"}

        # NEW-78: verification runs against ORACLE data, never caller data.
        verified, reason = await self._verify_via_oracle(policy)

        claim_id = f"clm_{uuid.uuid4().hex[:16]}"
        claim: dict[str, Any] = {
            "claim_id": claim_id,
            "policy_id": policy_id,
            "holder": policy["holder"],
            "policy_type": policy["policy_type"],
            "coverage_amount": policy["coverage"]["amount"],
            "status": "pending",
            "filed_at": now,
        }
        self._claims[claim_id] = claim

        result = await self._claims_processor.process_claim(
            claim_id, claim, policy, verified=verified, reason=reason,
        )
        claim.update(result)

        # 18-K. RECORD THE OUTCOME AGAINST THE HOLDER'S HISTORY.
        # `EligibilityTracker.record_claim` had ZERO CALLERS tree-wide, so
        # `_history` never received a claim event, `_compute_risk_score`
        # returned 0.0 for everyone forever, and TWO OF THE THREE
        # `check_eligibility` gates were structurally unreachable — while both
        # `check_eligibility` and `get_history` reported `risk_score` and
        # `total_claims` as measured facts. A control fed by a writer that is
        # never called is not a lenient control, it is an absent one wearing a
        # control's clothes.
        await self._eligibility.record_claim(
            policy["holder"], claim_id, claim.get("status", "unknown"),
        )

        if claim["status"] == "approved":
            policy["status"] = "claimed"

        logger.info(
            "Claim filed: id=%s policy=%s status=%s",
            claim_id, policy_id, claim["status"],
        )

        # 18-N. THE SAME LEDGER CALL, CLASSIFIED IN OPPOSITE DIRECTIONS.
        # `auto_settle_claim` and this method both reach
        # `ReserveFund.withdraw`, which is `self._balance -= amount` plus a
        # ledger append — no transfer occurs on either. The sibling says so
        # (`value_moved: False` plus a disclosure); this one returned an
        # "approved" claim carrying a `payout_amount` and said nothing, so the
        # identical fact was disclosed on one path and not the other.
        #
        # A claimant reading "approved, payout_amount 50000.0" concludes they
        # have been paid. The divergence was caused by a single missing field,
        # and it is the more dangerous half: this is the path a claimant
        # actually files on.
        return {
            **claim,
            "value_moved": False,
            "disclosure": (
                "Claim decision and reserve accounting are real; the payout is "
                "a reserve-ledger entry, NOT a transfer to the claimant. No "
                "funds have been sent."
            ),
        }

    async def _verify_via_oracle(self, policy: dict) -> tuple[bool, str]:
        """Decide a parametric claim from ORACLE data. Fails closed. NEW-78.

        The real verification path already existed and already worked:
        TriggerManager.evaluate_condition fetches live data through
        OracleGateway (_fetch_oracle_data resolves it directly). It was
        reachable only from check_triggers, which has ZERO callers — so the
        correct verifier sat unreachable while the self-attesting one served
        every live claim. Third instance of that shape in this census
        (fundraising's refund engine, fundraising's oracle path, now this).

        The fix is ROUTING, not resolution: point the live path at the
        verifier that already exists.

        Fails closed on every unenumerated case — no trigger registered, no
        trigger record, or an oracle error — because "cannot verify" must
        never read as "verified".
        """
        trigger_id = policy.get("trigger_id")
        if not trigger_id:
            return False, (
                "No parametric trigger is registered for this policy, so the "
                "covered event cannot be verified."
            )

        trigger = self._trigger_manager.get_trigger(trigger_id)
        if not trigger:
            return False, "Registered trigger not found; cannot verify."

        # Fetch explicitly so an UNAVAILABLE oracle is distinguishable from
        # an oracle that answered "no". Both deny, but they are different
        # facts and a claimant is owed the true one: "we could not check" must
        # not be reported as "the event did not happen".
        try:
            oracle_data = await self._trigger_manager._fetch_oracle_data(trigger)
        except Exception as exc:  # noqa: BLE001 - any oracle fault fails closed
            logger.warning("Oracle fetch failed: %s", exc)
            oracle_data = None

        if not oracle_data:
            return False, (
                "Verification authority unavailable — oracle data could not "
                "be obtained, so the covered event could not be checked. This "
                "is not a determination that the event did not occur."
            )

        try:
            verdict = await self._trigger_manager.evaluate_condition_detailed(
                trigger, oracle_data=oracle_data,
            )
        except Exception as exc:  # noqa: BLE001 - any evaluation fault fails closed
            logger.warning("Oracle evaluation failed: %s", exc)
            return False, "Verification failed; the claim cannot be verified."

        # 18-D. THE GUARD ABOVE TESTS THE ENVELOPE, NOT THE MEASUREMENT, and
        # an envelope is never empty — the gateway merges `oracle_type`,
        # `cached` and `timestamp` into every response. So `if not oracle_data`
        # passed on a `data: {}` body, the evaluators substituted their
        # insurer-favourable defaults, and this method reported a determination
        # about an event nobody had measured. In one direction that denied
        # every honest claim; in the other it APPROVED A FULL PAYOUT.
        #
        # The docstring above forbids exactly this conflation and the method
        # committed it anyway, one call deeper. Reading `measured` is what
        # makes the stated principle load-bearing rather than aspirational.
        if not verdict.measured:
            return False, (
                f"Verification authority unavailable — {verdict.reason} "
                f"This is not a determination that the event did not occur."
            )

        if not verdict.met:
            return False, f"Oracle data does not satisfy the policy trigger. {verdict.reason}"
        return True, f"Oracle data satisfies the policy trigger. {verdict.reason}"

    def _already_settled(self, policy_id: str) -> bool:
        """Has an approved claim already been paid on this policy? NEW-79."""
        return any(
            c.get("policy_id") == policy_id and c.get("status") == "approved"
            for c in self._claims.values()
        )

    async def get_policy(self, policy_id: str) -> dict:
        """Retrieve a policy by ID."""
        policy = self._policies.get(policy_id)
        if not policy:
            raise ValueError(f"Policy {policy_id} not found")

        # Check expiry
        now = int(time.time())
        if policy["status"] == "active" and now > policy["expires_at"]:
            policy["status"] = "expired"

        return policy

    async def cancel_policy(
        self,
        policy_id: str,
        caller: str | None = None,
        caller_identity: str = "",
        caller_source: str | None = None,
    ) -> dict:
        """Cancel an active policy.

        Returns a pro-rated refund calculation.

        NEW-78b: ownership asserted here for the same reason as `file_claim`,
        and found by the same sweep. This method took no caller either, so
        anyone who learned a policy id could cancel a stranger's coverage —
        terminating protection they had paid for, and producing a refund
        calculation against their premium. It is live on the ServiceDispatcher
        as `cancel_insurance` and is in _STATE_MODIFYING_ACTIONS.

        Fixed in the same commit as file_claim deliberately: a partial
        authority fix is worse than a uniformly broken one, because it makes
        the surface look audited. See the SURFACE CAVEAT on `file_claim` for
        the boundary of what this check can enforce.
        """
        policy = self._policies.get(policy_id)
        if not policy:
            raise ValueError(f"Policy {policy_id} not found")

        assert_owner(
            effective_caller(caller, caller_identity, caller_source),
            policy, owner_field="holder", what="policy",
        )

        if policy["status"] != "active":
            return {
                "status": "error",
                "reason": f"Cannot cancel policy with status '{policy['status']}'",
            }

        now = int(time.time())
        elapsed = now - policy["created_at"]
        total_duration = policy["expires_at"] - policy["created_at"]

        remaining_ratio = max(0.0, 1.0 - elapsed / total_duration)
        refund = policy["premium_paid"] * remaining_ratio * 0.9  # 10% cancellation fee

        policy["status"] = "cancelled"
        policy["cancelled_at"] = now
        policy["refund_amount"] = round(refund, 6)

        # Deregister trigger
        trigger_id = policy.get("trigger_id")
        if trigger_id:
            await self._trigger_manager.deregister_trigger(trigger_id)

        logger.info("Policy cancelled: id=%s refund=%s", policy_id, refund)
        return policy

    # ------------------------------------------------------------------
    # Trigger checking (called periodically)
    # ------------------------------------------------------------------

    async def check_triggers(self) -> list:
        """Check all active triggers against oracle data.

        Auto-files claims when parametric conditions are met.
        """
        triggered = await self._trigger_manager.check_triggers()
        results: list[dict[str, Any]] = []

        for trigger in triggered:
            policy_id = trigger["policy_id"]
            if policy_id in self._policies:
                # NEW-78: this used to pass the trigger's oracle_data as the
                # second positional arg — which is now `caller`. The
                # oracle-driven path is the AUTHORISED one, and it files on
                # the holder's behalf, so it passes the policy's own holder as
                # the caller. Verification still re-runs against live oracle
                # data inside file_claim; nothing here is taken on trust.
                policy = self._policies[policy_id]
                claim = await self.file_claim(
                    policy_id, caller=policy.get("holder"),
                )
                results.append(claim)

        return results

    # ------------------------------------------------------------------
    # Helpers
    # ------------------------------------------------------------------

    @staticmethod
    def _build_trigger_conditions(
        policy_type: str, coverage: dict,
    ) -> dict[str, Any]:
        """Build a VALIDATED trigger predicate from the buyer's coverage dict.

        18-E. This method used to lift `metric`, `comparator` and `threshold`
        verbatim out of the buyer's own dict, so the policyholder wrote the
        test their payout was decided by. NEW-78 removed the claimant's
        DATA from the claim decision and left the claimant's PREDICATE in it.

        Validation lives in `_predicate.build_predicate`, which refuses to
        issue rather than returning a predicate the platform will not stand
        behind. See that module for the measured exploits, the bands and their
        stated basis, and for what deliberately REMAINS open (the premium does
        not vary with the threshold — D18-FEE-C2, registered, not closed).
        """
        return build_predicate(policy_type, coverage)

    # ------------------------------------------------------------------
    # Expanded insurance operations
    # ------------------------------------------------------------------

    async def create_parametric_policy(
        self, holder: str, trigger_type: str, trigger_params: dict, coverage_amount: float, premium: float,
    ) -> dict:
        """Create a parametric insurance policy with automated triggers."""
        if (
            not self._web3.available
            or self._web3.is_placeholder(self._policy_contract)
        ):
            return not_deployed_response("insurance", {
                "operation": "create_parametric_policy",
                "requested": {"holder": holder, "trigger_type": trigger_type, "coverage_amount": coverage_amount},
            })
        # 18-F. THE UNPRICED TWIN. This method wrote a claimable policy having
        # called the fee engine ZERO times, check_eligibility ZERO times and
        # check_solvency ZERO times, and having never validated trigger_type
        # against POLICY_TYPES or coverage_amount against max_coverage. The
        # buyer supplied BOTH the coverage amount AND the premium and nothing
        # reconciled them — §U taken to its limit: in the priced path the buyer
        # manipulates an input to the price; here the buyer simply states it.
        #
        # Measured at the census pin, all with ordinary finite floats:
        #   coverage 90,000 / premium 0.0 -> approved, reserve driven to 0.0,
        #     against an honest quote of 1,440.0, on BOTH claim surfaces;
        #   policy_type "banana" -> active, trigger registered, published to
        #     the public feed as insurance_policy_created;
        #   coverage NaN -> ReserveFund._balance becomes NaN, after which the
        #     CORRECTLY-PRICED path is rejected forever with "Reserve fund
        #     insufficient" while this one becomes unbounded. This method was
        #     the sole injection point for that: the twin rejects NaN
        #     incidentally at solvency (balance >= NaN is False).
        #
        # The gates below are the twin's gates, in the twin's order. NEW-80
        # made these records claimable; it is what turned an unpriced record
        # into an obligation.
        if trigger_type not in POLICY_TYPES:
            raise ValueError(
                f"Unknown trigger_type '{trigger_type}'. "
                f"Must be one of: {', '.join(sorted(POLICY_TYPES))}"
            )

        coverage_amount = require_finite_money(coverage_amount, "coverage_amount")
        if coverage_amount > self._max_coverage:
            raise ValueError(
                f"coverage_amount {coverage_amount} exceeds max "
                f"{self._max_coverage}"
            )
        premium = require_finite_money(premium, "premium", allow_zero=True)

        elig = await self._eligibility.check_eligibility(holder, trigger_type)
        if not elig.get("eligible", False):
            return {
                "status": "rejected",
                "reason": elig.get("reason", "Not eligible"),
                "eligibility": elig,
            }

        duration_days_gate = int(self._default_duration)
        gate_conditions = self._build_trigger_conditions(
            trigger_type, trigger_params or {})
        premium_calc = await self._fee_engine.calculate_premium(
            trigger_type, coverage_amount, duration_days_gate,
            (trigger_params or {}).get("risk_factors", {}),
            trigger_conditions=gate_conditions,
        )
        expected_premium = premium_calc["total_premium"]
        if premium < expected_premium:
            return {
                "status": "rejected",
                "reason": f"Premium {premium} is below required {expected_premium}",
                "premium_required": expected_premium,
            }

        solvency = await self._reserve_fund.check_solvency(coverage_amount)
        if not solvency.get("solvent", False):
            return {
                "status": "rejected",
                "reason": "Reserve fund insufficient for additional coverage",
                "solvency": solvency,
            }

        policy_id = f"ppol_{uuid.uuid4().hex[:16]}"
        now = int(time.time())
        # NEW-80: SCHEMA RECONCILED WITH THE POLICY SHAPE THE CLAIM PATH
        # READS. This wrote `trigger_type` / `coverage_amount` while
        # ClaimsProcessor and _verify_via_oracle read `policy_type` /
        # `coverage["amount"]` / `expires_at`. Every parametric policy was
        # therefore DENIED unconditionally — verified before this fix — and no
        # oracle data could ever change that. Two writers into one store with
        # different shapes is the twin-path bug in miniature.
        #
        # The legacy keys are retained as aliases so any existing reader keeps
        # working; the canonical keys are added, and a trigger is registered
        # so the claim path has an oracle to consult.
        duration_days = int(self._default_duration)
        record: dict[str, Any] = {
            "id": policy_id,
            "policy_id": policy_id,
            "status": "active",
            "holder": holder,
            "policy_type": trigger_type,
            "trigger_type": trigger_type,
            "trigger_params": trigger_params,
            # 18-I. THE SPLAT USED TO COME LAST AND EXCLUDE NOTHING, so a
            # buyer-supplied `trigger_params["amount"]` OVERWROTE the value
            # every gate above had just validated. 18-F added the twin's gates
            # and not the twin's RECORD CONSTRUCTION: the gates checked a
            # number the record then threw away.
            #
            # MEASURED at 5eee277, with all of 18-F's gates in place: an
            # honest premium of 75.0 for 1,000 of cover, a legitimate in-band
            # predicate, and an HONEST oracle reporting a real M7.8 paid out
            # 5,000,000 — five times max_coverage, which solvency and the fee
            # engine never saw. The NaN variant reinstated the reserve
            # poisoning that 18-F's own commit message claimed to have closed.
            #
            # §AK.2 in its sharpest form: a fix that guards the INPUT to a
            # record while leaving the record's own construction unguarded has
            # moved the defect one field over, not removed it. The exclusion
            # list is now the twin's, verbatim.
            "coverage": {"amount": coverage_amount, "duration_days": duration_days,
                         **{k: v for k, v in (trigger_params or {}).items()
                            if k not in ("amount", "duration_days",
                                         "risk_factors")}},
            "coverage_amount": coverage_amount,
            "premium": premium,
            "premium_paid": premium,
            "premium_breakdown": premium_calc,
            "created_at": now,
            "expires_at": now + duration_days * 86400,
        }
        self._policies[policy_id] = record
        conditions = self._build_trigger_conditions(trigger_type, record["coverage"])
        if conditions:
            trg = await self._trigger_manager.register_trigger(
                policy_id, trigger_type, conditions,
            )
            record["trigger_id"] = trg.get("trigger_id")
        logger.info("Parametric policy created: id=%s", policy_id)
        return record

    async def auto_settle_claim(
        self, policy_id: str, oracle_data: dict,
    ) -> dict:
        """Auto-settle a claim based on oracle data."""
        if (
            not self._web3.available
            or self._web3.is_placeholder(self._policy_contract)
        ):
            return not_deployed_response("insurance", {
                "operation": "auto_settle_claim",
                "requested": {"policy_id": policy_id},
            })
        # NEW-67: DELEGATED. This method used to be a shadow over the real
        # claims processor:
        #
        #     record = {"status": "settled", "payout_amount": 0.0,
        #               "oracle_data": oracle_data, ...}
        #     self._claims[settle_id] = record
        #     return record
        #
        # It accepted oracle_data and never read it, computed no payout, and
        # returned "settled" with payout_amount hardcoded to 0.0 — closing a
        # claim while paying nothing. A settled-for-zero claim is a DENIAL
        # WEARING A PAYMENT'S NAME: the claimant is told their claim was
        # settled, and what happened is the opposite of what they were told.
        #
        # The real twin was already here and already constructed in __init__ —
        # self._claims_processor — and the sibling file_claim already used it.
        # It verifies the parametric trigger against the policy, computes the
        # payout from the policy's coverage amount, debits the reserve (which
        # REFUSES on insufficiency), and DENIES with a stated reason when the
        # trigger is not met. oracle_data is exactly its trigger_data.
        policy = self._policies.get(policy_id)
        if policy is None:
            return {
                "status": "error",
                "error_category": "not_found",
                "error": f"Policy '{policy_id}' not found",
                "policy_id": policy_id,
            }

        # NEW-79: THE PRECONDITIONS MY OWN NEW-67 DELEGATION OMITTED.
        # I delegated the DECISION to the real processor without delegating
        # file_claim's GUARDS, so a cancelled policy settled ($900 on a
        # cancelled policy), and one policy settled repeatedly ($1,500 on a
        # $500 policy, three times). Both reproduced before this fix. The
        # original NEW-67 tests missed them because every scenario built a
        # fresh policy via create_policy and settled it once — the defect was
        # scenario breadth, not assertion strength.
        if policy.get("status") != "active":
            return {
                "status": "rejected",
                "reason": f"Policy status is '{policy.get('status')}', not active",
                "policy_id": policy_id,
            }
        if int(time.time()) > policy.get("expires_at", 0):
            policy["status"] = "expired"
            return {"status": "rejected", "reason": "Policy has expired",
                    "policy_id": policy_id}
        if self._already_settled(policy_id):
            return {
                "status": "rejected",
                "reason": "This policy has already been settled; coverage is exhausted.",
                "policy_id": policy_id,
            }

        # NEW-78: the verdict comes from the ORACLE path, never from
        # caller-supplied oracle_data.
        verified, reason = await self._verify_via_oracle(policy)

        claim_id = f"asc_{uuid.uuid4().hex[:16]}"
        claim: dict[str, Any] = {
            "claim_id": claim_id,
            "policy_id": policy_id,
            "status": "pending",
            "filed_at": int(time.time()),
        }
        self._claims[claim_id] = claim

        result = await self._claims_processor.process_claim(
            claim_id, claim, policy, verified=verified, reason=reason,
        )
        claim.update(result)

        # 18-K. RECORD THE OUTCOME AGAINST THE HOLDER'S HISTORY.
        # `EligibilityTracker.record_claim` had ZERO CALLERS tree-wide, so
        # `_history` never received a claim event, `_compute_risk_score`
        # returned 0.0 for everyone forever, and TWO OF THE THREE
        # `check_eligibility` gates were structurally unreachable — while both
        # `check_eligibility` and `get_history` reported `risk_score` and
        # `total_claims` as measured facts. A control fed by a writer that is
        # never called is not a lenient control, it is an absent one wearing a
        # control's clothes.
        await self._eligibility.record_claim(
            policy["holder"], claim_id, claim.get("status", "unknown"),
        )
        if claim.get("status") == "approved":
            policy["status"] = "claimed"

        # CUSTODY DISCLOSURE (NEW-64's standing rule, applied to the very next
        # case). The delegate is real AS COMPUTATION — a genuine parametric
        # decision plus reserve accounting with a real insufficiency guard —
        # but ReserveFund.withdraw is `self._balance -= amount` and a ledger
        # append. No transfer occurs. Approving a claim here debits a reserve
        # ledger; it does not pay a claimant, and the response says so rather
        # than letting "approved" be read as "paid".
        return {
            **claim,
            "value_moved": False,
            "disclosure": (
                "Claim decision and reserve accounting are real; the payout is "
                "a reserve-ledger entry, NOT a transfer to the claimant. No "
                "funds have been sent."
            ),
        }

    async def renew_coverage(
        self,
        policy_id: str,
        additional_premium: float,
        extension_days: int = 365,
        caller: str | None = None,
        caller_identity: str = "",
        caller_source: str | None = None,
    ) -> dict:
        """Renew an existing insurance policy — and actually renew it.

        18-G. THIS METHOD RENEWED NOTHING. It never looked up the policy, never
        wrote to `self._policies`, and never extended `expires_at`. It built a
        fresh dict containing `status: "renewed"` and returned it. `renewed` is
        in `_REAL_OUTCOME_STATUSES`, so `_outcome_is_real` returned True, the
        dispatcher ATTESTED `cover_renew` into the platform's own audit record
        and PUBLISHED it to the public social feed — while the stored policy
        expired on its original date and all three read paths (`file_claim`,
        `auto_settle_claim`, `get_policy`) then refused the holder as expired.

        A live denial of coverage, announced publicly as its opposite.

        It was reachable with TWO ordinary scalars, no authentication and no
        ownership check, on shipped config. `new_expiry` was the sharpest part:
        a measured-looking field computed as `now + extension_days`, never read
        from the policy's actual `expires_at` and never written anywhere. A
        reader treats a returned expiry as the policy's new expiry; it was an
        arithmetic expression over the caller's own argument.

        §AG CORRECTION, from the verification pass. This was filed as biting
        because of NEW-79. It does not: `file_claim`'s expiry refusal exists in
        the original commit and predates `renew_coverage` entirely — NEW-79
        only extended that same refusal to `auto_settle_claim`. The defect has
        been a live denial on the PRIMARY claim path since the method was born.
        The composition frame was unearned and the finding is older than filed.

        `caller` is required, per the NEW-78b ownership idiom: the sweep that
        covered `file_claim` and `cancel_policy` never reached this method.
        """
        if (
            not self._web3.available
            or self._web3.is_placeholder(self._policy_contract)
        ):
            return not_deployed_response("insurance", {
                "operation": "renew_coverage",
                "requested": {"policy_id": policy_id, "extension_days": extension_days},
            })

        policy = self._policies.get(policy_id)
        if not policy:
            return {
                "status": "not_found",
                "reason": f"Policy {policy_id} not found; nothing was renewed.",
                "policy_id": policy_id,
            }

        assert_owner(
            effective_caller(caller, caller_identity, caller_source),
            policy, owner_field="holder", what="policy",
        )

        if policy["status"] not in ("active", "expired"):
            return {
                "status": "rejected",
                "reason": (
                    f"Cannot renew a policy with status '{policy['status']}'; "
                    f"nothing was renewed."
                ),
                "policy_id": policy_id,
            }

        extension_days = int(extension_days)
        if extension_days <= 0:
            raise ValueError("extension_days must be positive")
        additional_premium = require_finite_money(
            additional_premium, "additional_premium", allow_zero=True)

        # The renewal must be PRICED, or it is a free extension of cover. Same
        # engine, same sufficiency test as issuance.
        coverage_amount = require_finite_money(
            policy.get("coverage", {}).get("amount", 0), "coverage.amount")
        renew_trigger = self._trigger_manager.get_trigger(
            policy.get("trigger_id") or "") or {}
        quote = await self._fee_engine.calculate_premium(
            policy["policy_type"], coverage_amount, extension_days,
            policy.get("coverage", {}).get("risk_factors", {}),
            trigger_conditions=renew_trigger.get("conditions"),
        )
        required = quote["total_premium"]
        if additional_premium < required:
            return {
                "status": "rejected",
                "reason": (
                    f"Additional premium {additional_premium} is below the "
                    f"required {required}; nothing was renewed."
                ),
                "premium_required": required,
                "policy_id": policy_id,
            }

        now = int(time.time())
        # Extend from whichever is later: an unexpired policy extends from its
        # own expiry, a lapsed one from today. Extending a lapsed policy from
        # its old expiry would silently sell cover for a period already past.
        base = max(int(policy.get("expires_at", now)), now)
        new_expiry = base + extension_days * 86400

        policy["expires_at"] = new_expiry
        policy["status"] = "active"
        policy["premium_paid"] = (
            require_finite_money(policy.get("premium_paid", 0), "premium_paid",
                                 allow_zero=True)
            + additional_premium
        )
        policy.setdefault("renewals", []).append({
            "renewed_at": now,
            "extension_days": extension_days,
            "additional_premium": additional_premium,
            "premium_breakdown": quote,
            "new_expiry": new_expiry,
        })

        renew_id = f"ren_{uuid.uuid4().hex[:16]}"
        logger.info(
            "Coverage renewed: id=%s policy=%s new_expiry=%s",
            renew_id, policy_id, new_expiry,
        )
        return {
            "id": renew_id,
            "status": "renewed",
            "policy_id": policy_id,
            "additional_premium": additional_premium,
            "extension_days": extension_days,
            "new_expiry": new_expiry,
            "renewed_at": now,
            "premium_breakdown": quote,
        }

    async def assess_risk(
        self, holder: str, policy_type: str, parameters: dict | None = None,
    ) -> dict:
        """Assess risk for a potential policy."""
        if (
            not self._web3.available
            or self._web3.is_placeholder(self._policy_contract)
        ):
            return not_deployed_response("insurance", {
                "operation": "assess_risk",
                "requested": {"holder": holder, "policy_type": policy_type},
            })
        # 18-L. BOTH NUMBERS WERE LITERALS. `risk_score: 50` and
        # `premium_estimate: 0.0` were hard-coded — no engine consulted, no
        # history read, identical for every holder and every policy type. The
        # status "assessed" is a real outcome, so the dispatcher attested and
        # published a "risk assessment" that had assessed nothing. Measured
        # against the honest engine: premium_estimate 0.0 versus 2000.0.
        #
        # This is the one insurance action that reached its caller through the
        # dispatcher while the ownership actions were dead (18-H) — the
        # fabricating path worked and the honest ones did not.
        if policy_type not in POLICY_TYPES:
            raise ValueError(
                f"Unknown policy_type '{policy_type}'. "
                f"Must be one of: {', '.join(sorted(POLICY_TYPES))}"
            )

        params = parameters or {}
        coverage_amount = require_finite_money(
            params.get("coverage_amount", params.get("amount", 0)),
            "coverage_amount",
        )
        duration_days = int(params.get("duration_days", self._default_duration))

        try:
            enquiry_conditions = build_predicate(policy_type, params)
        except PredicateError:
            # An estimate for a predicate we would refuse to underwrite is
            # still worth quoting, at the un-severity-adjusted base — but it
            # must not silently look like a quote for an issuable policy.
            enquiry_conditions = None
        quote = await self._fee_engine.calculate_premium(
            policy_type, coverage_amount, duration_days,
            params.get("risk_factors", {}),
            trigger_conditions=enquiry_conditions,
        )
        history = await self._eligibility.get_history(holder)

        assess_id = f"risk_{uuid.uuid4().hex[:16]}"
        record: dict[str, Any] = {
            "id": assess_id,
            "status": "assessed",
            "holder": holder,
            "policy_type": policy_type,
            "parameters": params,
            # 0..1 from the holder's real claim history (18-K wired the writer
            # that feeds it), scaled to the 0..100 this field has always been
            # documented as.
            "risk_score": round(
                float(history.get("risk_score", 0.0)) * 100.0, 2),
            "premium_estimate": quote["total_premium"],
            "premium_breakdown": quote,
            "claims_on_record": history.get("total_claims", 0),
            # §U / 16-G idiom: the amount this is quoted against is the
            # ENQUIRER'S OWN, and no policy is created here. An estimate that
            # did not say so would be read as a price the platform had agreed.
            "estimate_basis": "caller_supplied_coverage_amount",
            "estimate_is_binding": False,
            "assessed_at": int(time.time()),
        }
        logger.info(
            "Risk assessed: id=%s premium_estimate=%s risk_score=%s",
            assess_id, record["premium_estimate"], record["risk_score"],
        )
        return record
