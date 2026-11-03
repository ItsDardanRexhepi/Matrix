"""What a tool call DOES — the seam's classification of the twin tools.

The 20 blockchain capability classes (``runtime/blockchain/registry.py``)
register as tools named ``smart_contract``, ``defi``, ``stablecoin``, … and take
their real verb in ``arguments["action"]``. The seam used to hand the security
gate ``action_type = tool_name``, so the gate — which classifies by verb —
saw ``smart_contract`` for a contract deployment signed with the platform key
and ``stablecoin`` for an ERC-20 approve, and 18 of the 20 tools passed by
name (Matrix register entry::TWINS-CRITICAL, entry::TWINS-MORPHEUS-BYNAME,
standing rule §DL.4: never classify on a field the dangerous value is not in).

This table maps every declared (tool, action) to the canonical action type the
gate already knows for value movement where one fits, and names every other
platform-key-signed action ``send_transaction`` — which is what it is: a
transaction signed and broadcast with the platform's key. Reads keep their
own verb. The gate's vocabulary itself is not ours to change (Morpheus is
report-only in the audit); ``test_twins_seam.py`` pins that every signing
entry is a verb the gate requires evaluation for, when the package is present.
"""
from __future__ import annotations

from typing import Any

# Canonical verbs the gate treats as fund-moving (its vocabulary, read from the
# private package, not imported from it).
_TX = "send_transaction"

# tool -> action -> canonical action type. Every signing action is here; a
# read maps to READ and keeps the declared verb as its action type.
READ = "read"
SIGNING_ACTIONS: dict[str, dict[str, str]] = {
    # D-045: "deploy" is gone from the tool's action enum — the platform does
    # not deploy contracts (NEW-4 / NEW-12 / RUN-2), and the tool axis was the
    # last place that still offered it. Left out rather than kept as a dead _TX
    # entry, because tests/test_twins_seam.py treats a classification for an
    # action nobody declares as staleness to be removed, not as harmless.
    "smart_contract": {"send": _TX, "call": READ, "verify": READ, "compile": READ},
    "defi": {"supply": "deposit", "borrow": "borrow", "withdraw": "withdraw", "repay": "repay",
             "get_rates": READ, "get_positions": READ},
    "nft": {"mint": "mint", "transfer": "transfer", "deploy_collection": _TX,
            "get_owner": READ, "get_uri": READ, "balance": READ},
    "tokenize": {"deploy": _TX, "transfer": "transfer", "approve": _TX, "mint": "mint",
                 "balance": READ, "info": READ},
    "identity": {"register": _TX, "resolve": READ, "verify": READ, "lookup": READ},
    "dao": {"create_proposal": _TX, "vote": _TX, "execute": _TX, "deploy_dao": _TX, "get_state": READ},
    "stablecoin": {"transfer": "transfer", "approve": _TX, "balance": READ, "list": READ},
    "eas": {"create_schema": _TX, "attest": _TX, "revoke": _TX, "batch_attest": _TX, "query": READ},
    "agent_identity": {"register": _TX, "attest_action": _TX, "verify": READ, "get_identity": READ},
    "payment": {"send_eth": "send", "send_token": "transfer", "get_balance": READ, "estimate_fee": READ},
    "oracle": {"get_price": READ, "list_feeds": READ, "query_custom": READ},
    "supply_chain": {"create_record": _TX, "update_status": _TX, "track": READ, "verify_provenance": READ},
    "insurance": {"create_policy": "buy", "file_claim": "claim", "get_policy": READ},
    "gaming": {"mint_item": "mint", "transfer_item": "transfer", "record_achievement": _TX,
               "get_inventory": READ},
    "ip_royalties": {"register_ip": _TX, "set_royalties": _TX, "distribute": "transfer", "get_ip": READ},
    "stake": {"stake": "stake", "unstake": "unstake", "claim_rewards": "claim",
              "get_staked": READ, "get_rewards": READ},
    "crossborder_payment": {"send": "send", "estimate": READ, "track": READ, "compliance_check": READ},
    "securities": {"create_token": _TX, "whitelist_investor": _TX, "transfer": "transfer", "freeze": _TX,
                   "get_info": READ},
    "governance": {"schedule_operation": _TX, "execute_operation": _TX, "grant_role": _TX,
                   "revoke_role": _TX, "get_delay": READ},
    "dashboard": {"wallet_overview": READ, "tx_history": READ, "gas_price": READ, "block_info": READ,
                  "platform_stats": READ},
}

TWIN_TOOLS = frozenset(SIGNING_ACTIONS)

# Arguments through which a caller could point a platform-signed action at
# somebody else's address (register entry::B3-TWIN-SUPPLY-ONBEHALF).
BENEFICIARY_FIELDS = ("onBehalfOf", "on_behalf_of", "beneficiary")

# Twin actions that grant a spender rights over the platform's own tokens
# (register entry::B3-TWIN-APPROVE): refused unless the operator has set a cap.
ALLOWANCE_ACTIONS = frozenset({("stablecoin", "approve"), ("tokenize", "approve")})


def canonical_action(tool_name: str, arguments: Any) -> tuple[str, bool | None]:
    """``(action_type, signs)`` for a tool call.

    ``signs`` is True for a platform-key-signed twin action, False for a twin
    read, and None for tools outside the table (their name is their type, as
    before — except ``platform_action``, whose real verb is ``arguments.action``).
    An UNDECLARED twin action is treated as signing: the gate must see it.
    """
    args = arguments if isinstance(arguments, dict) else {}
    verb = str(args.get("action") or "").strip().lower()
    table = SIGNING_ACTIONS.get(tool_name)
    if table is None:
        if tool_name == "platform_action" and verb:
            return verb, None
        return tool_name, None
    mapped = table.get(verb)
    if mapped is None:
        return _TX, True           # unknown verb on a signing tool → fail closed
    if mapped == READ:
        return verb, False
    return mapped, True


def beneficiary_violation(tool_name: str, arguments: Any, identity: str) -> str | None:
    """A signing twin action naming a beneficiary other than the caller's bound
    identity — or naming one when no identity is bound — is refused."""
    _, signs = canonical_action(tool_name, arguments)
    if not signs or not isinstance(arguments, dict):
        return None
    for field in BENEFICIARY_FIELDS:
        value = str(arguments.get(field) or "").strip()
        if not value:
            continue
        if not identity:
            return (f"'{field}' names an address but no identity is bound to this request; "
                    "a platform-signed action can only act for the caller it can attribute")
        if value.lower() != identity.lower():
            return (f"'{field}' must be your own address ({identity}); a platform-signed action "
                    "cannot be pointed at somebody else")
    return None


def allowance_violation(tool_name: str, arguments: Any, config: Any) -> str | None:
    """Platform-key approve: refused unless ``security.platform_allowance_cap``
    is set and the requested amount is within it."""
    args = arguments if isinstance(arguments, dict) else {}
    verb = str(args.get("action") or "").strip().lower()
    if (tool_name, verb) not in ALLOWANCE_ACTIONS:
        return None
    security = config.get("security") if isinstance(config, dict) else None
    # `security:` with no value in YAML is None, and `.get` on it raised out of
    # pre_action — a refusal check that faulted instead of refusing. A section
    # that is not a mapping sets no cap, so the approve is refused.
    if not isinstance(security, dict):
        security = {}
    try:
        cap = float(security.get("platform_allowance_cap", 0) or 0)
    except (TypeError, ValueError):
        cap = 0.0
    if cap <= 0:
        return ("approve with the platform key is disabled: it grants a spender rights over the "
                "platform's own tokens; set security.platform_allowance_cap to allow a bounded amount")
    try:
        amount = float(args.get("amount", 0) or 0)
    except (TypeError, ValueError):
        return "approve amount is not a number"
    if amount <= 0 or amount > cap:
        return f"approve amount {amount} exceeds security.platform_allowance_cap ({cap}) or is not positive"
    return None
