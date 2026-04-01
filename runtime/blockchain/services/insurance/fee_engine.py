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
from typing import Any

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

        # Determine tier rate
        tier_rate = _TIERS[-1][1]
        tier_label = ">100K"
        for upper, rate in _TIERS:
            if coverage_amount <= upper:
                tier_rate = rate
                if upper == 1_000:
                    tier_label = "<1K"
                elif upper == 10_000:
                    tier_label = "1K-10K"
                elif upper == 100_000:
                    tier_label = "10K-100K"
                else:
                    tier_label = ">100K"
                break

        # Apply base-rate multiplier for policy type
        type_multiplier = self._base_rates.get(policy_type, 1.0)

        # Pro-rate for duration (annual basis = 365 days)
        duration_factor = duration_days / 365.0

        base_premium = coverage_amount * tier_rate * type_multiplier * duration_factor

        # Compute risk adjustment
        adjustment_total = 0.0
        breakdown: list[dict[str, Any]] = []

        for factor_name, factor_value in risk_factors.items():
            adj = self._risk_adjustments.get(factor_name, 0.0)
            if isinstance(factor_value, (int, float)):
                adj *= float(factor_value)
            elif factor_value is True:
                pass  # use adj as-is
            else:
                continue

            adjustment_total += adj
            breakdown.append({
                "factor": factor_name,
                "adjustment": round(adj, 6),
            })

        risk_premium = base_premium * adjustment_total
        total_premium = max(0.01, base_premium + risk_premium)

        result = {
            "policy_type": policy_type,
            "coverage_amount": coverage_amount,
            "duration_days": duration_days,
            "tier": tier_label,
            "tier_rate": tier_rate,
            "type_multiplier": type_multiplier,
            "duration_factor": round(duration_factor, 4),
            "base_premium": round(base_premium, 6),
            "risk_adjustment": round(risk_premium, 6),
            "risk_adjustment_pct": round(adjustment_total, 4),
            "total_premium": round(total_premium, 6),
            "breakdown": breakdown,
        }

        logger.debug(
            "Premium calculated: type=%s coverage=%s total=%s",
            policy_type, coverage_amount, total_premium,
        )
        return result
