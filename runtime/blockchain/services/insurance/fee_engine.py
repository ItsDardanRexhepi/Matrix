"""
FeeEngine — tiered premium calculation for parametric insurance.

Base rates vary by policy type and are adjusted by risk factors.
Coverage tiers:
    < 1 000        → 5.0 %
    1 000 – 10 000 → 3.0 %
    10 000 – 100 000 → 2.0 %
    > 100 000      → 1.5 %
"""

from __future__ import annotations

import logging
import math
from typing import Any

from runtime.blockchain.services.insurance._predicate import trigger_ease

logger = logging.getLogger(__name__)

# Base annual rate multipliers by policy type (applied on top of tier rate)
_BASE_RATE_MULTIPLIERS: dict[str, float] = {
    "weather": 1.0,
    "flight_delay": 0.8,
    "crop": 1.2,
    "earthquake": 1.5,
    "smart_contract_hack": 2.0,
}

# Coverage tiers: (upper_bound, rate)
_TIERS: list[tuple[float, float]] = [
    (1_000.0, 0.05),
    (10_000.0, 0.03),
    (100_000.0, 0.02),
    (float("inf"), 0.015),
]

# 18-P. How much more the easiest underwritable trigger costs than the
# hardest: 1.0 means the near end of the insurable band is priced at double.
# A DECLARED PLATFORM SCHEDULE, of exactly the same kind as the base-rate
# multipliers above — not an actuarial estimate, and the result says so.
_SEVERITY_SPREAD: float = 1.0

# Risk-factor adjustments
_RISK_ADJUSTMENTS: dict[str, float] = {
    "high_frequency_area": 0.25,
    "first_time_buyer": -0.10,
    "multi_policy_discount": -0.05,
    "historical_loss_region": 0.20,
    "long_duration": 0.10,
}


class FeeEngine:
    """Tiered premium calculator.

    Config keys (under ``config["insurance"]``):
        base_rate_overrides (dict): per-type multiplier overrides.
        risk_adjustment_overrides (dict): per-factor adjustment overrides.
    """

    def __init__(self, config: dict) -> None:
        self._config = config
        ins_cfg = config.get("insurance", {})

        self._base_rates: dict[str, float] = {
            **_BASE_RATE_MULTIPLIERS,
            **ins_cfg.get("base_rate_overrides", {}),
        }
        self._risk_adjustments: dict[str, float] = {
            **_RISK_ADJUSTMENTS,
            **ins_cfg.get("risk_adjustment_overrides", {}),
        }

    async def calculate_premium(
        self,
        policy_type: str,
        coverage_amount: float,
        duration_days: int,
        risk_factors: dict,
        trigger_conditions: dict | None = None,
    ) -> dict:
        """Calculate the premium for a policy.

        Args:
            policy_type: Insurance category.
            coverage_amount: Total coverage in base units.
            duration_days: Policy duration.
            risk_factors: Dict of factor_name → bool/float.

        Returns:
            Dict with ``base_premium``, ``risk_adjustment``,
            ``total_premium``, ``tier``, ``rate``, ``breakdown``.
        """
        if coverage_amount <= 0:
            raise ValueError("coverage_amount must be positive")
        if duration_days <= 0:
            raise ValueError("duration_days must be positive")

        # 18-Q. TIERS ARE APPLIED MARGINALLY, LIKE TAX BRACKETS.
        #
        # The tier rate used to be selected by the WHOLE coverage amount and
        # then multiplied across all of it, which made the premium
        # NON-MONOTONIC IN THE AMOUNT INSURED. Measured pre-fix, weather, 365d:
        #
        #     coverage      999 -> premium    49.95
        #     coverage    1,000 -> premium    50.00
        #     coverage    1,001 -> premium    30.03   <- MORE cover, LESS premium
        #     coverage    9,999 -> premium   299.97
        #     coverage   10,001 -> premium   200.02   <- again
        #     coverage   99,999 -> premium 1,999.98
        #     coverage  100,001 -> premium 1,500.02   <- again
        #
        # Three cliffs, each an arbitrage: buy a pound more cover, pay less for
        # it. Marginal application makes the premium monotonically
        # non-decreasing in coverage, which is the property that removes the
        # arbitrage rather than merely moving the cliff.
        marginal: list[dict[str, Any]] = []
        weighted_rate_numerator = 0.0
        lower = 0.0
        for upper, rate in _TIERS:
            if coverage_amount <= lower:
                break
            slice_top = min(coverage_amount, upper)
            slice_amount = slice_top - lower
            if slice_amount > 0:
                weighted_rate_numerator += slice_amount * rate
                marginal.append({
                    "from": lower,
                    "to": slice_top,
                    "rate": rate,
                    "amount": round(slice_amount * rate, 6),
                })
            lower = upper

        # The EFFECTIVE rate across the whole amount, reported so the existing
        # `tier_rate` field keeps meaning something to its readers.
        tier_rate = weighted_rate_numerator / coverage_amount
        if coverage_amount <= 1_000:
            tier_label = "<1K"
        elif coverage_amount <= 10_000:
            tier_label = "1K-10K"
        elif coverage_amount <= 100_000:
            tier_label = "10K-100K"
        else:
            tier_label = ">100K"

        # Apply base-rate multiplier for policy type
        type_multiplier = self._base_rates.get(policy_type, 1.0)

        # Pro-rate for duration (annual basis = 365 days)
        duration_factor = duration_days / 365.0

        # 18-P. THE PREMIUM WAS CONSTANT IN THE THING THAT DECIDES THE PAYOUT.
        # Measured pre-fix, 50,000 of heat cover for a year: a trigger at >35C
        # (which fires most summers) and one at >59C (which essentially never
        # fires) both cost 1,000.00 exactly.
        #
        # THE DEFERRAL THAT PRECEDED THIS, AND WHY IT WAS REVERSED. 18-E filed
        # this as registered-not-closed on the grounds that pricing the
        # threshold needs an actuarial model this repository does not have, and
        # inventing one would fabricate a control. Re-examined at close, that
        # premise does not hold: THIS ENGINE ALREADY PRICES BY DECLARED
        # MULTIPLIERS WITH NO ACTUARIAL DERIVATION — `earthquake: 1.5`,
        # `smart_contract_hack: 2.0`, and the tier rates themselves. A declared
        # severity multiplier is the same KIND of object the engine is built
        # from, not a new kind of claim. Keeping `earthquake: 1.5` while
        # refusing to price the threshold is inconsistent, and it leaves the
        # premium constant in the variable that most determines whether the
        # platform pays at all.
        #
        # What this is NOT: an estimate of how often a peril occurs. It says
        # where inside the platform's OWN declared insurable band the buyer
        # chose to sit, and charges more nearer the easy end. `trigger_ease`
        # returns None where no bounded scale exists (the hack loss floor is
        # unbounded above), and the result then carries `severity_priced: False`
        # rather than a silent 1.0 — a refusal to guess is not a neutral value.
        ease = (
            trigger_ease(policy_type, trigger_conditions)
            if trigger_conditions else None
        )
        severity_multiplier = 1.0 + (_SEVERITY_SPREAD * ease) if ease is not None else 1.0

        base_premium = (
            coverage_amount * tier_rate * type_multiplier * duration_factor
            * severity_multiplier
        )

        # Compute risk adjustment
        adjustment_total = 0.0
        breakdown: list[dict[str, Any]] = []

        # 18-A / §AN — THE PLATFORM'S OWN CONSTANT WAS AN ATTACKER-SCALED
        # PARAMETER. `adj` is the platform's number (`first_time_buyer: -0.10`);
        # `factor_value` is the CALLER'S. Multiplying one by the other let the
        # party who PAYS the premium scale the discount the platform defined.
        # Measured pre-fix: {} -> 2000.00 · {first_time_buyer: True} -> 1800.00 ·
        # {first_time_buyer: 10} -> 0.01 · 1000, NaN and inf -> 0.01 as well,
        # because the floor clamp turned every abusive value into the same
        # unremarkable minimum (§AN.1 — a clamp reads as the control, and here
        # it was what made the abuse quiet).
        #
        # A CALLER MAY SELECT A FACTOR. A CALLER MAY NOT SCALE ONE. Declaring
        # `first_time_buyer` is a claim the platform prices; deciding it is worth
        # ten times the platform's own figure is not a claim, it is arithmetic on
        # the platform's policy. Numeric values are therefore treated as a
        # PRESENCE FLAG, not a multiplier.
        #
        # NOT FIXED HERE, RECORDED INSTEAD (conservative disposition): nothing
        # verifies `first_time_buyer` itself. Selecting a discount you are not
        # entitled to is still possible and is §U's open half — it needs an
        # underwriting source that does not exist in this repo, and inventing one
        # would fabricate a control. The REJECTED ALTERNATIVE was to drop
        # negative adjustments entirely; rejected because it silently reprices
        # every honest policy that legitimately qualifies, trading a bounded
        # abuse for an unbounded overcharge.
        for factor_name, factor_value in risk_factors.items():
            if factor_name not in self._risk_adjustments:
                continue
            if factor_value is False or factor_value is None:
                continue
            if isinstance(factor_value, (int, float)) and not isinstance(factor_value, bool):
                if not math.isfinite(float(factor_value)) or float(factor_value) <= 0:
                    continue          # not a declaration at all
            adj = self._risk_adjustments[factor_name]

            adjustment_total += adj
            breakdown.append({
                "factor": factor_name,
                "adjustment": round(adj, 6),
                # 18-R. WHOSE CLAIM THIS IS. Nothing in this repository verifies
                # `first_time_buyer`, `multi_policy_discount` or any other
                # factor — 18-A closed the SCALING half (a caller may select a
                # factor, not scale one) and explicitly recorded this half as
                # open, because verifying it needs an underwriting source that
                # does not exist here and inventing one would fabricate a
                # control.
                #
                # Measured: declaring first_time_buyer + multi_policy_discount
                # takes a 1,450.00 premium to 850.00 — 41% off, asserted by the
                # party who pays it, checked by nobody. That figure is not
                # reduced by disclosure. What disclosure changes is that the
                # quote no longer presents it as a priced fact (16-G idiom).
                "source": "caller_asserted",
                "verified": False,
            })

        risk_premium = base_premium * adjustment_total
        total_premium = max(0.01, base_premium + risk_premium)

        result = {
            "policy_type": policy_type,
            "coverage_amount": coverage_amount,
            "duration_days": duration_days,
            "tier": tier_label,
            "tier_rate": round(tier_rate, 8),
            "tier_slices": marginal,
            "severity_priced": ease is not None,
            "trigger_ease": None if ease is None else round(ease, 4),
            "severity_multiplier": round(severity_multiplier, 4),
            "type_multiplier": type_multiplier,
            "duration_factor": round(duration_factor, 4),
            "base_premium": round(base_premium, 6),
            "risk_adjustment": round(risk_premium, 6),
            "risk_adjustment_pct": round(adjustment_total, 4),
            "risk_factors_verified": False if breakdown else None,
            "risk_factors_disclosure": (
                "Risk factors are DECLARED BY THE APPLICANT and are not "
                "verified — no underwriting source exists to check them. The "
                "adjustment above is applied on the applicant's own claim."
            ) if breakdown else "",
            "total_premium": round(total_premium, 6),
            "breakdown": breakdown,
        }

        logger.debug(
            "Premium calculated: type=%s coverage=%s total=%s",
            policy_type, coverage_amount, total_premium,
        )
        return result
