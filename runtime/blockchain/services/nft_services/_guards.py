"""Shared numeric guards for nft_services. DOMAIN 17-B.

THE DOMAIN HAD ZERO `isfinite` GUARDS across 49 methods and 26 ordered
comparisons, 8 of them value-bearing. It never received 16-A's pass.

Every guard in this domain fails the same way. `royalty_enforcement.process_sale`
protects itself with a FLOOR — `if sale_price < _MIN_SALE_PRICE: raise` — and
`NaN < 0.0001` is False, so the guard is skipped and the sale is priced at NaN.
Measured, before the fix:

    nan -> royalty=nan  fee=nan  seller=nan   persisted sale_0b9ac113d9a94dba
    inf -> royalty=inf  fee=inf  seller=nan   persisted sale_ea7e65e151504481

That is the FIFTH guard shape the non-finite class has walked: sign
(`amount <= 0`, 15-D), ratio (`ratio < min`, 16-A), sufficiency
(`amount < total_due`, 16-I), eligibility (`ratio >= threshold`, 16-P), and now
FLOOR (`price < minimum`). The finding was never "sign checks are weak"; it is
that EVERY COMPARISON IS WEAK, and each new shape is another place the intuition
"this guard looks careful" was wrong.

§T.2 — ENUMERATE EVERY VALUE ENTRY POINT BEFORE FIXING ANY. Measured by AST over
the package, 12 caller-supplied value parameters:

    factory.deploy_erc721(royalty_bps)          factory.deploy_erc1155(royalty_bps)
    royalty_enforcement.process_sale(sale_price)
    royalty_enforcement.get_royalty_info(sale_price)
    royalty_enforcement.configure_royalty(bps)
    service.create_collection(royalty_bps)      service.mint(royalty_bps)
    service.process_sale(sale_price)            service.get_royalty_info(sale_price)
    service.list_for_sale(price)                service.rent(price)
    service.fractionalize(price_per_fraction)   valuation.record_sale(price)

The enumeration is stated here rather than in a commit message because the next
person to add a value parameter needs it at the point of use, not in the log.
"""

from __future__ import annotations

import math


def require_finite_amount(value: float, name: str) -> float:
    """A caller-supplied amount that must be a real, positive number.

    Rejects NaN and both infinities BEFORE any comparison, because every
    comparison against them is False and therefore every guard downstream is
    skipped rather than triggered.
    """
    try:
        v = float(value)
    except (TypeError, ValueError):
        raise ValueError(f"{name} must be a number, got {value!r}") from None
    if not math.isfinite(v):
        raise ValueError(
            f"{name} must be a finite number, got {value!r} — a non-finite "
            f"value defeats every ordered comparison that would otherwise "
            f"reject it"
        )
    if v <= 0:
        raise ValueError(f"{name} must be positive, got {v}")
    return v


def require_finite_bps(value: int | float, name: str, cap: int) -> int:
    """A basis-points figure that must be finite and within its cap.

    Separate from `require_finite_amount` because zero IS valid here — a
    collection may set no royalty — and because the cap is the whole point: a
    NaN bps passes `bps > cap` (False) and lands in the record uncapped.
    """
    try:
        v = float(value)
    except (TypeError, ValueError):
        raise ValueError(f"{name} must be a number, got {value!r}") from None
    if not math.isfinite(v):
        raise ValueError(f"{name} must be a finite number, got {value!r}")
    if v < 0 or v > cap:
        raise ValueError(f"{name} must be between 0 and {cap}, got {v}")
    return int(v)
