"""DOMAIN 19 — the restaking guards: who may act, who benefits, and what the
chain actually did.

Three findings, one module. Each is a caller-supplied or unverified input on a
path that moves the PLATFORM'S OWN treasury, signed by the platform paymaster.

19-A  WHO MAY ACT      `services.restaking.enabled` had ZERO READERS while
                       being the only key the shipped example config sets for
                       this service. An operator following our own
                       documentation sets `enabled: false`, believes the
                       service is gated, and all seven value-moving methods
                       execute normally.

                       It is now READ, and it FAILS CLOSED. The seven actions
                       refuse unless an operator explicitly opts in.

                       This also closes the reachability half. `catalog.py`
                       marks all seven capabilities `available=False`, and
                       `install_action_map` NEVER CONSULTS IT — measured, 62
                       capabilities flagged unavailable and 62 installed into
                       ACTION_MAP anyway. With `morpheus_security` absent (the
                       shipped default) `gate_action` returns
                       `observe, blocked=False`. So a remote unauthenticated
                       `POST {"action":"liquid_stake_lido","params":{"amount":1e30}}`
                       set the ETH value of a transaction signed by the
                       platform paymaster against the platform's own treasury.
                       The `available` flag's platform-wide semantics are a
                       REGISTER item; this gate is the domain-scoped refusal
                       that does not wait for it.

19-B  WHO BENEFITS     `receiver = params.get("receiver") or
                       get_account().address` went into arg 2 of ERC-4626
                       `Vault.deposit(assets, receiver)`. The paymaster signs
                       and PLATFORM collateral is spent; the shares — the claim
                       on those assets — mint to whatever address the caller
                       named. Platform pays, caller owns.

                       The response then asserted the literal
                       `acts_on: "platform_account"`, which is true of the
                       funds' SOURCE and false of their DESTINATION. Three
                       census lenses reached this independently.

                       §AH, and the reason it survived reading: the module's
                       NON-CUSTODIAL NOTE is prominent, truthful, and answers
                       *whose money leaves*. It is silent on *whose money
                       arrives*, and the defect is entirely on the second
                       question. "The service NEVER moves a user wallet's
                       balance" is true and irrelevant — it is the platform's
                       balance that moves.

19-C  WHAT HAPPENED    `status: "submitted"` meant only that a node accepted a
                       raw transaction. No receipt was ever awaited, so a
                       transaction that REVERTED was indistinguishable from one
                       that worked — and `submitted` is in
                       `_REAL_OUTCOME_STATUSES`, so the dispatcher EAS-attested
                       it and published it to the public feed as an action that
                       happened.

                       And the same field carried the opposite error: when the
                       node ACCEPTED the transaction and the failure came after
                       (timeout, reset, malformed response), the service
                       returned `status: "error"`, which `_outcome_is_real`
                       reads as NOT an outcome — so the audit trail recorded
                       "the platform declined" for a value-moving transaction
                       that was broadcast and may be mined.

                       §AC's completed form: **a status field carrying two
                       opposite errors simultaneously proves the field cannot
                       be the evidence.** Second independent arrival at
                       16-N/16-O's conclusion.

                       BOTH HALVES ARE FIXED HERE, TOGETHER (17-D's standard).
                       Fixing the over-claim alone would leave the audit trail
                       recording refusals for mined transactions — the worse
                       half, because **an over-claim is visible to the
                       claimant and an under-claim is visible to nobody.**

                       The fix is not a better label. `wait_for_receipt` has
                       existed on `Web3Manager` the whole time: the evidence
                       was collectable and was not being collected.
"""

from __future__ import annotations

import logging
from typing import Any

from runtime.blockchain.web3_manager import not_deployed_response

logger = logging.getLogger(__name__)

__all__ = ["require_restaking_enabled", "settle_transaction", "resolve_receiver"]

#: How long to wait for a receipt before reporting the outcome as UNKNOWN.
#: A timeout is not a failure and must not be recorded as one.
_RECEIPT_TIMEOUT_S = 120


def require_restaking_enabled(service_name: str, config: dict, method: str) -> dict | None:
    """Return a refusal unless `services.<name>.enabled` is explicitly true.

    19-A. FAILS CLOSED. The key defaults to absent, and absent means refuse —
    because the alternative is what shipped: a config key the example sets,
    nothing reads, and which therefore cannot turn anything off.
    """
    svc_cfg = (config.get("services", {}) or {}).get(service_name, {}) or {}
    if svc_cfg.get("enabled") is True:
        return None
    return not_deployed_response(service_name, extra={
        "method": method,
        "missing": f"services.{service_name}.enabled must be set to true",
        "reason": (
            "This service moves the platform's own treasury and is disabled by "
            "default. Setting `enabled: true` is an explicit, auditable opt-in "
            "by an operator — it is not implied by populating contract "
            "addresses."
        ),
    })


def resolve_receiver(params: dict, platform_address: str) -> str:
    """The beneficiary of a platform-funded deposit is the platform. 19-B.

    A caller-supplied `receiver` is REFUSED rather than ignored. Silently
    overriding it would let a caller believe they had named a beneficiary and
    leave them to discover otherwise; refusing says which party the platform
    will underwrite.
    """
    requested = params.get("receiver")
    if requested and str(requested).lower() != str(platform_address).lower():
        raise PermissionError(
            f"receiver {requested!r} is not the platform account. This deposit "
            f"is funded by the platform paymaster and spends platform "
            f"collateral, so the vault shares — the claim on those assets — "
            f"must mint to the platform. A caller-named beneficiary would make "
            f"the platform pay for a position the caller owns."
        )
    return platform_address


async def settle_transaction(
    web3: Any,
    tx_hash: str,
    method: str,
    service_name: str,
    base: dict[str, Any],
) -> dict[str, Any]:
    """Turn a broadcast into a settled, honest outcome. 19-C, both halves.

    The status vocabulary is the dispatcher's own, used for what it means:

        receipt.status == 1  -> "submitted"  REAL outcome, settled, value moved
        receipt.status == 0  -> "failed"     NON-outcome. The chain REVERTED it;
                                             attesting it would assert a thing
                                             that did not happen.
        no receipt in time   -> "pending"    NON-outcome, and correct: attesting
                                             now would assert the future. Carries
                                             `broadcast: True` + the hash, so it
                                             is distinguishable from a refusal
                                             that never touched the chain — which
                                             is the under-claim half.

    `settled` and `value_moved` are emitted on every path. The restaking service
    emitted NEITHER while 10+ sibling services do, so `_outcome_is_real`'s
    highest-priority override — built precisely to catch "a transaction was
    broadcast but nothing moved" — was not wired here at all (§AP at the
    predicate layer: a control whose strongest clause never fires because the
    field it reads is absent).
    """
    out = {**base, "tx_hash": tx_hash, "broadcast": True}
    try:
        receipt = await web3.wait_for_receipt(tx_hash, timeout=_RECEIPT_TIMEOUT_S)
    except Exception as exc:  # noqa: BLE001 — any wait fault is UNKNOWN, not failure
        logger.warning("%s.%s: no receipt for %s: %s", service_name, method,
                       tx_hash, exc)
        return {
            **out,
            "status": "pending",
            "settled": False,
            "value_moved": None,
            "disclosure": (
                "The transaction was BROADCAST and no receipt was obtained "
                "within the wait window. This is NOT a refusal and NOT a "
                "failure — the transaction may be mined. Check the hash."
            ),
        }

    on_chain_ok = int(getattr(receipt, "status", 0) or 0) == 1
    if not on_chain_ok:
        return {
            **out,
            "status": "failed",
            "settled": True,
            "value_moved": False,
            "block_number": getattr(receipt, "blockNumber", None),
            "disclosure": (
                "The transaction was mined and REVERTED on-chain. Nothing "
                "moved. Gas was still spent."
            ),
        }

    return {
        **out,
        "status": "submitted",
        "settled": True,
        "value_moved": True,
        "block_number": getattr(receipt, "blockNumber", None),
        "gas_used": getattr(receipt, "gasUsed", None),
    }
