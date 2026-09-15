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


def effective_caller(
    caller: str | None,
    caller_identity: str,
    caller_source: str | None,
) -> str | None:
    """Resolve WHICH identity an ownership check may trust. 18-H.

    THE DEFECT THIS EXISTS TO CLOSE. `file_claim`, `cancel_policy` and
    `renew_coverage` each declared a parameter named `caller`. The dispatcher
    overrides exactly one name — `caller_identity` — and only for methods that
    declare it; everything else in `params` is forwarded verbatim into
    `method(**params)`, and `params` is the attacker-controlled request body
    (service_dispatcher.py says so in terms). So `assert_owner` was handed a
    string the CALLER wrote, and compared it to `policy["holder"]`.

    MEASURED: a caller whose threaded identity was "mallory", sending
    `{"policy_id": <alice's>, "caller": "alice"}`, cancelled Alice's policy —
    result "cancelled", stored status "cancelled".

    17-D's own comment names this primitive as the thing it refused to ship:
    "assert any address, have the platform record it". It was live the whole
    time, one parameter name away, because the ownership sweep and the identity
    sweep chose different words for the same idea (§AO.2 — thirteen names for
    the party acting is the absence of a platform concept of one).

    THE RULE. When a call arrives through the dispatcher, `caller_source` is
    present, and ONLY the threaded `caller_identity` is used — including when it
    is empty, which is a refusal and never a fallback to the `caller` param.
    The threaded value is whatever the entry point bound: authenticated when it
    came from a session, and written by the caller when the security middleware
    bound an X-Wallet-Address header or a body field instead. When `caller_source` is absent the call is internal
    (e.g. `check_triggers` filing on the holder's behalf) and `caller` stands.
    """
    if caller_source is not None:
        # Dispatcher-originated. The threaded value always wins, "" included.
        return caller_identity or None
    return caller


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
