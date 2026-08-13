"""Numeric guards for insurance. DOMAIN 18-B.

THE DOMAIN HAD ZERO isfinite CHECKS across 45 methods and 28 ordered
comparisons, 13 of them value-bearing. Like nft_services, it never received
16-A's pass.

`create_policy` guards its coverage with a BOUNDED RANGE:

    if coverage_amount <= 0:            raise
    if coverage_amount > self._max_coverage:  raise

A NaN satisfies NEITHER, so it passes both — §W's fifth shape, the one a careful
author writes as defence in depth, landing in THE METHOD THAT SETS THE PAYOUT.
`approve_claim` later pays out `float(policy["coverage"]["amount"])`, so a NaN
coverage becomes a NaN payout on a claim the platform approves. The premium
check `premium < expected_premium` is defeated the same way.

§T.2 — CALLER-SUPPLIED VALUE PARAMETERS ENUMERATED BEFORE ANY WERE FIXED, by AST
over the package (21 total; the money-bearing subset):

    service.create_policy(coverage.amount, premium)
    service.create_parametric_policy(coverage_amount, premium)
    service.renew_coverage(additional_premium)
    fee_engine.calculate_premium(coverage_amount)
    reserve_fund.deposit(amount) · withdraw(amount)
    reserve_fund.add_coverage(amount) · remove_coverage(amount)
    reserve_fund.check_solvency(pending_claims)
    claims_processor.approve_claim(payout_amount)

The list lives here rather than in a commit message because the next person to
add a value parameter needs it at the point of use.
"""

from __future__ import annotations

import math


def require_finite_money(value: float, name: str, *, allow_zero: bool = False) -> float:
    """A caller-supplied money amount: finite, and positive unless stated.

    Rejects NaN and both infinities BEFORE any comparison, because every
    comparison against them is False and therefore every bound downstream is
    skipped rather than triggered.
    """
    try:
        v = float(value)
    except (TypeError, ValueError):
        raise ValueError(f"{name} must be a number, got {value!r}") from None
    if not math.isfinite(v):
        raise ValueError(
            f"{name} must be a finite number, got {value!r} — a non-finite value "
            f"satisfies neither bound of a range check and passes both"
        )
    if v < 0 or (v == 0 and not allow_zero):
        raise ValueError(f"{name} must be positive, got {v}")
    return v
