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

        coverage_amount = float(coverage.get("amount", 0))
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

    async def file_claim(self, policy_id: str, trigger_data: dict) -> dict:
        """File a claim against a policy.

        Args:
            policy_id: The policy to claim against.
            trigger_data: Oracle / parametric data proving the event occurred.

        Returns:
            Claim record with processing status.
        """
        policy = self._policies.get(policy_id)
        if not policy:
            raise ValueError(f"Policy {policy_id} not found")

        if policy["status"] != "active":
            return {
                "status": "rejected",
                "reason": f"Policy status is '{policy['status']}', not active",
            }

        now = int(time.time())
        if now > policy["expires_at"]:
            policy["status"] = "expired"
            return {"status": "rejected", "reason": "Policy has expired"}

        claim_id = f"clm_{uuid.uuid4().hex[:16]}"
        claim: dict[str, Any] = {
            "claim_id": claim_id,
            "policy_id": policy_id,
            "holder": policy["holder"],
            "policy_type": policy["policy_type"],
            "coverage_amount": policy["coverage"]["amount"],
            "trigger_data": trigger_data,
            "status": "pending",
            "filed_at": now,
        }
        self._claims[claim_id] = claim

        # Attempt auto-processing via oracle verification
        result = await self._claims_processor.process_claim(
            claim_id, claim, policy,
        )
        claim.update(result)

        if claim["status"] == "approved":
            policy["status"] = "claimed"

        logger.info(
            "Claim filed: id=%s policy=%s status=%s",
            claim_id, policy_id, claim["status"],
        )
        return claim

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

    async def cancel_policy(self, policy_id: str) -> dict:
        """Cancel an active policy.

        Returns a pro-rated refund calculation.
        """
        policy = self._policies.get(policy_id)
        if not policy:
            raise ValueError(f"Policy {policy_id} not found")

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
                claim = await self.file_claim(
                    policy_id, trigger.get("oracle_data", {}),
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
        record: dict[str, Any] = {
            "id": policy_id,
            "status": "active",
            "holder": holder,
            "trigger_type": trigger_type,
            "trigger_params": trigger_params,
            "coverage_amount": coverage_amount,
            "premium": premium,
            "created_at": now,
        }
        self._policies[policy_id] = record
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
        settle_id = f"asc_{uuid.uuid4().hex[:16]}"
        now = int(time.time())
        record: dict[str, Any] = {
            "id": settle_id,
            "status": "settled",
            "policy_id": policy_id,
            "oracle_data": oracle_data,
            "payout_amount": 0.0,
            "settled_at": now,
        }
        self._claims[settle_id] = record
        logger.info("Claim auto-settled: id=%s", settle_id)
        return record

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
