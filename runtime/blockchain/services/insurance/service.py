"""
InsuranceService — Parametric insurance for the 0pnMatrx platform.

Supports weather, flight delay, crop, earthquake, and smart-contract-hack
policies.  Claims are automatically triggered when oracle data confirms
the parametric condition, removing the need for manual adjudication.
"""

from __future__ import annotations

import logging
import time
import uuid
from typing import Any

from runtime.blockchain.services.insurance._guards import require_finite_money

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

        logger.info("InsuranceService initialised.")

    # ------------------------------------------------------------------
    # Policy lifecycle
    # ------------------------------------------------------------------

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

        # Calculate expected premium
        risk_factors = coverage.get("risk_factors", {})
        premium_calc = await self._fee_engine.calculate_premium(
            policy_type, coverage_amount, duration_days, risk_factors,
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

        # Register auto-trigger if applicable
        trigger_conditions = self._build_trigger_conditions(policy_type, coverage)
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

    async def file_claim(self, policy_id: str, caller: str | None = None) -> dict:
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

          gateway route  /api/v1/insurance/claim  ENFORCING. The handler binds
                         `caller` from current_request_security(); a
                         body-supplied `holder` cannot override it.
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
        caller/holder/creator to the authenticated identity AT the dispatcher) is
        now a real option rather than a missing subsystem.

        RECORDED BECAUSE A DEFERRAL THAT CITES A VANISHED BLOCKER AGES INTO A
        FALSE ONE — 16-U's shape pointed forward. A reader finding this note
        without this paragraph would conclude the mechanism does not exist, and
        would be wrong.
        """
        policy = self._policies.get(policy_id)
        if not policy:
            raise ValueError(f"Policy {policy_id} not found")

        assert_owner(caller, policy, owner_field="holder", what="policy")

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

        if claim["status"] == "approved":
            policy["status"] = "claimed"

        logger.info(
            "Claim filed: id=%s policy=%s status=%s",
            claim_id, policy_id, claim["status"],
        )
        return claim

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

    async def cancel_policy(self, policy_id: str, caller: str | None = None) -> dict:
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

        assert_owner(caller, policy, owner_field="holder", what="policy")

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
        """Build trigger conditions from policy type and coverage params."""
        conditions: dict[str, Any] = {"policy_type": policy_type}

        if policy_type == "weather":
            conditions["location"] = coverage.get("location", "")
            conditions["metric"] = coverage.get("metric", "temperature")
            conditions["threshold"] = coverage.get("threshold", 0)
            conditions["comparator"] = coverage.get("comparator", "gt")

        elif policy_type == "flight_delay":
            conditions["flight_number"] = coverage.get("flight_number", "")
            conditions["delay_minutes"] = coverage.get("delay_minutes", 120)

        elif policy_type == "crop":
            conditions["location"] = coverage.get("location", "")
            conditions["crop_type"] = coverage.get("crop_type", "")
            conditions["rainfall_threshold_mm"] = coverage.get(
                "rainfall_threshold_mm", 50,
            )

        elif policy_type == "earthquake":
            conditions["location"] = coverage.get("location", "")
            conditions["magnitude_threshold"] = coverage.get(
                "magnitude_threshold", 5.0,
            )

        elif policy_type == "smart_contract_hack":
            conditions["contract_address"] = coverage.get("contract_address", "")
            conditions["loss_threshold"] = coverage.get("loss_threshold", 0)

        return conditions

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
            "coverage": {"amount": coverage_amount, "duration_days": duration_days,
                         **(trigger_params or {})},
            "coverage_amount": coverage_amount,
            "premium": premium,
            "premium_paid": premium,
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
        self, policy_id: str, additional_premium: float, extension_days: int = 365,
    ) -> dict:
        """Renew an existing insurance policy."""
        if (
            not self._web3.available
            or self._web3.is_placeholder(self._policy_contract)
        ):
            return not_deployed_response("insurance", {
                "operation": "renew_coverage",
                "requested": {"policy_id": policy_id, "extension_days": extension_days},
            })
        renew_id = f"ren_{uuid.uuid4().hex[:16]}"
        now = int(time.time())
        record: dict[str, Any] = {
            "id": renew_id,
            "status": "renewed",
            "policy_id": policy_id,
            "additional_premium": additional_premium,
            "extension_days": extension_days,
            "new_expiry": now + extension_days * 86400,
            "renewed_at": now,
        }
        logger.info("Coverage renewed: id=%s", renew_id)
        return record

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
        assess_id = f"risk_{uuid.uuid4().hex[:16]}"
        record: dict[str, Any] = {
            "id": assess_id,
            "status": "assessed",
            "holder": holder,
            "policy_type": policy_type,
            "parameters": parameters or {},
            "risk_score": 50,
            "premium_estimate": 0.0,
            "assessed_at": int(time.time()),
        }
        logger.info("Risk assessed: id=%s", assess_id)
        return record
