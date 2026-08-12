"""NEW-94 — the staking domain arms as a unit, and the read exemption is a LIST.

THE ASYMMETRY THIS REPLACES. Fifteen methods across three classes; exactly one
was gated (``StakingService.stake``, service.py). The other fourteen behaved
identically whether or not the staking contract existed. That is not a policy,
it is an accident of where someone happened to add a gate.

And the accident was LOAD-BEARING. ``stake`` is the sole writer of
``StakingService._positions``, so gating ``stake`` is the *only* reason
``unstake``, ``claim_rewards`` and ``get_position`` are inert today — they are
not safe, they are merely starved. Replacing the accident with a control is the
whole point: the domain must be inert because something says so, not because a
dictionary happens to be empty.

WHY THE EXEMPTION IS AN ENUMERATED LIST AND NOT A RULE
------------------------------------------------------
The obvious shape is "reads are safe, writes are gated." That rule is WRONG IN
THIS CODEBASE, and the counterexample is in this very domain:

    StakingService.get_position
        ...
        await self._accrue_rewards(position, pool)   # <- service.py

A method named ``get`` MINTS BALANCE as a side effect of being read. Poll it in
a loop and ``pending_rewards`` grows, with no stake, no claim and no caller
intent beyond "show me my position". So ``get_position`` is GATED, and the
read/write distinction is not a safety boundary here.

That is why ``STAKING_UNGATED_READS`` is a list of five methods that were
checked one at a time, not a category anyone may reason their way into. A
future developer who adds ``get_rewards_preview()`` and assumes "it's a getter,
getters are safe" inherits nothing from this file — the structural test in
tests/test_staking_arming.py fails until they put the new method on one list or
the other, deliberately.

THE SCOPE OF THE LISTS. They enumerate the PUBLIC surface of the three staking
classes: every public method and property. Private helpers
(``_accrue_rewards``, ``_compute_avg``, ``_sanitize_position``) are reachable
only through a public entry point, every one of which appears on a list below,
so they inherit their arming state from their callers rather than declaring
their own. The structural test asserts that reachability property rather than
assuming it.

WHAT THIS DOES NOT DO, STATED PLAINLY. This file makes every method obey the
same switch, so that setting the staking contract address flips a DOMAIN rather
than a method. It does not say when that switch may be thrown.

THE COMPOUND ARMING CONDITION IS NOT YET WRITTEN. It is a separate, pending act
(item 4 of the domain-10 disposition), and until it lands this domain must stay
dark. At minimum it must require: an authenticated caller identity bound to
``staker`` rather than a caller-supplied string; position state read from chain
rather than from ``StakingService._positions``; the pool-accounting corrections
in place before arming, since arming makes an unvalidated sign reachable with
real money; a pool status derived from a receipt rather than asserted; and —
the strongest clause — A DEMONSTRATED FUNDED SOURCE FOR REWARDS. Not "a
treasury exists", but: the accrual reads a real balance and refuses when it
cannot cover. ``_accrue_rewards`` creates a balance out of a rate parameter,
compounding with elapsed time, with nothing on the other side of the ledger.
Arm it unfunded and the first honest thing this service does is calculate a
debt.
"""

from __future__ import annotations

import logging
from typing import Any

from runtime.blockchain.web3_manager import not_deployed_response

logger = logging.getLogger(__name__)


# ── The two lists. Every public callable in the domain is on exactly one. ──

#: Refuse with ``not_deployed`` while the staking contract is unset.
#:
#: ``get_position`` is on THIS list and that placement is the reason the other
#: list is a list. It reads nothing without first calling ``_accrue_rewards``,
#: which credits ``pending_rewards`` from elapsed wall-clock time. Reading it
#: creates value. If you are here because you want to move it, read the
#: accrual body first, then read the funded-source clause of the arming
#: condition in service.py.
STAKING_GATED: frozenset[str] = frozenset({
    "APYCalculator.calculate_apy",
    "StakingPoolManager.create_pool",
    "StakingPoolManager.add_stake",
    "StakingPoolManager.remove_stake",
    "StakingService.stake",
    "StakingService.unstake",
    "StakingService.claim_rewards",
    "StakingService.get_position",
})

#: Answer normally while undeployed. FIVE METHODS, EACH CHECKED INDIVIDUALLY —
#: this is not the category "reads", it is these five:
#:
#:   APYCalculator.get_historical_apy  reads ``_history``; the only writer is
#:                                     ``calculate_apy``, now gated, so this
#:                                     returns [] while the domain is dark.
#:   StakingPoolManager.get_pool       returns a config record. Claims no
#:                                     balance the platform must honour.
#:   StakingPoolManager.list_pools     same, plural.
#:   StakingService.apy_calculator     property; hands back the sub-object,
#:   StakingService.pools              whose own methods are gated above.
#:
#: Adding to this list is a deliberate act with a reviewer. It is not a default.
STAKING_UNGATED_READS: frozenset[str] = frozenset({
    "APYCalculator.get_historical_apy",
    "StakingPoolManager.get_pool",
    "StakingPoolManager.list_pools",
    "StakingService.apy_calculator",
    "StakingService.pools",
})


def resolve_staking_contract(config: dict) -> str:
    """The staking contract address, from either config location.

    Extracted verbatim from ``StakingService.__init__`` so that all three
    classes gate on the SAME address. Two classes resolving the contract
    differently would reintroduce the asymmetry this module exists to remove.
    """
    s_cfg: dict[str, Any] = config.get("staking", {})
    bc_cfg: dict[str, Any] = config.get("blockchain", {})
    return (
        s_cfg.get("staking_contract", "")
        or bc_cfg.get("staking_contract", "")
        or ""
    )


def staking_not_deployed(
    web3: Any,
    contract: str,
    operation: str,
    requested: dict[str, Any] | None = None,
) -> dict[str, Any] | None:
    """Return an honest refusal, or ``None`` when the domain is armed.

    REGISTERED WITH D10. This function wraps ``not_deployed_response``, and a
    wrapper HIDES its callers from the discarded-refusal detector — which
    matches on the primitive's name appearing in a method body. Wrapping the
    primitive without registering the wrapper would have widened D10's blind
    spot as a side effect of closing a gate. It is listed in
    ``_REFUSAL_PRIMITIVES`` in tests/test_discarded_refusal_detector.py, and a
    test there fails if any future wrapper is added without the same
    registration.
    """
    if web3.available and not web3.is_placeholder(contract):
        return None

    logger.warning(
        "Staking domain: %s called but staking contract not deployed", operation
    )
    details: dict[str, Any] = {"operation": operation}
    if requested is not None:
        details["requested"] = requested
    return not_deployed_response("staking", details)
