"""Per-agent tool access policy — the PUBLIC, coarse default boundary.

This is the visible, code-enforced boundary that decides which agent may invoke
which tool/action. It is consulted by the ToolDispatcher on EVERY tool call,
keyed on the trusted ``agent_name`` from the gateway-validated request context —
NOT on anything the model can put in its tool arguments. A subverted agent
therefore cannot call another agent's tools: the dispatcher refuses based on who
the caller IS, regardless of what the prompt says.

This module is the coarse PUBLIC floor. The authoritative, finer-grained policy
(exact per-agent sets, ban/freeze integration, the closed-source nuance) lives in
the private security package and supersedes this when it is installed. The
security seam (``runtime.security.agent_access_allowed``) binds the two: private
if present, else this default. Either way the boundary holds.

Assigned tool sets (documented for review):
  - Neo     — FULL execution set: every tool, every action. The invisible engine.
  - Trinity — conversational gateway: ``web_search``, ``web``, and ``platform_action``
              restricted to NON-state-modifying actions (reads / quotes / analytics /
              conversation). NEVER bash, file_ops, raw blockchain execution tools, or
              any state-changing action. State-changing requests are escalated to Neo
              through the Morpheus security gate (she never gains Neo's tools).
  - Morpheus— security / guidance: ``security_audit``, ``web_search``, ``web``, and
              ``platform_action`` restricted to READ-ONLY security/verification
              actions. Never executes; never state-modifying; never bash/file_ops.
"""

from __future__ import annotations

import logging

logger = logging.getLogger(__name__)

# Trinity's directly-callable tools (platform_action is further action-gated below).
# request_execution is the controlled Trinity→Morpheus→Neo hand-off channel — it is
# NOT a raw execution tool; it gates through Morpheus and routes to Neo.
_TRINITY_TOOLS = frozenset({"web_search", "web", "platform_action", "request_execution"})

# Morpheus's directly-callable tools (platform_action is further action-gated below).
_MORPHEUS_TOOLS = frozenset({"security_audit", "web_search", "web", "platform_action"})

# Read-only security/verification actions Morpheus may run via platform_action.
_MORPHEUS_ACTION_KEYWORDS = (
    "audit", "verify", "verification", "attest", "attestation", "compliance",
    "security", "risk", "monitor", "check", "status", "report", "resolve",
)


def _is_state_modifying(action: str | None) -> bool:
    """True if *action* mutates on-chain/platform state. Sourced from the single
    canonical set in the service dispatcher so the boundary stays in lock-step
    with the capability catalog."""
    if not action:
        return False
    try:
        from runtime.blockchain.services.service_dispatcher import _STATE_MODIFYING_ACTIONS
        return action in _STATE_MODIFYING_ACTIONS
    except Exception:  # pragma: no cover — if the set can't load, fail safe (treat as mutating)
        logger.debug("Could not load _STATE_MODIFYING_ACTIONS; treating '%s' as state-modifying", action)
        return True


# ── Coarse fail-direction (used only when the security gate is unreachable) ──────
#
# Generic read verbs — the ONLY labels treated as safe to observe-allow when the
# security gate can't be reached / faults. EVERYTHING ELSE (anything value-moving,
# owner-gated, or simply unrecognised) FAILS CLOSED. This is a deliberately
# conservative PUBLIC default for one decision — the fail DIRECTION — and is NOT the
# authoritative classification (that lives in the private gate). It is intentionally
# independent of any value-moving list so a fund-moving action can never be *missed*
# and wrongly allowed: we allow only what is clearly a benign read, and deny the rest.
_BENIGN_READ_LABELS = frozenset({
    "get", "list", "read", "view", "info", "status", "health", "ping", "ready",
    "quote", "quotes", "balance", "balances", "price", "prices", "rate", "rates",
    "history", "feed", "search", "lookup", "metrics", "dashboard", "manifest",
    "config", "weather", "preview", "estimate", "simulate", "positions", "portfolio",
    "profile",
})
_BENIGN_READ_PREFIXES = ("get_", "list_", "read_", "fetch_", "view_", "quote_", "status_")


def could_move_value(action_type: str | None) -> bool:
    """Coarse PUBLIC fail-direction guess: could this action move value or change
    security/owner state?

    Used for ONE purpose only — choosing which way to fail when the security gate is
    unreachable: ``True`` → fail CLOSED (deny), ``False`` → safe to observe-allow.
    Anything that is not CLEARLY a benign read (incl. unknown/empty labels) is treated
    as value-moving and fails closed. No thresholds, no allowlists, no private action
    sets — generic read verbs, overridden by the dispatcher's PUBLIC state-modifying
    set (a state change is never a read, however it is spelled). The authoritative classification still lives in
    the private gate; this only decides the safe direction on a gateway fault.
    """
    a = (action_type or "").strip().lower()
    if not a:
        return True  # unknown → safest direction: treat as value-moving
    # A read VERB is a guess from the label's spelling, and the spelling can lie:
    # `list_nft_for_sale`, `list_marketplace` and `list_security` start with
    # `list_` and each one CHANGES state (lists an item for sale / on an
    # exchange). The dispatcher's own state-modifying set is the table dispatch
    # attests by, so an action in it is never a benign read, whatever its prefix.
    # Checked BEFORE the verb heuristic; if the set cannot load, the heuristic is
    # not trusted either (fail closed).
    if _is_state_modifying(a):
        return True
    if a in _BENIGN_READ_LABELS or a.startswith(_BENIGN_READ_PREFIXES):
        return False  # clearly a benign read → a transient fault may observe-allow it
    return True       # value-moving / owner-gated / unrecognised → fail closed


# ── The same direction keyed on what RUNS, not on what it is called ──────────
#
# A label is whatever the caller had to hand. ServiceRoutes._call passes the
# METHOD name (`list_item` for marketplace.list_item, which the state-modifying
# set knows as `list_marketplace`), and platform_action takes a `service`
# override that moves an action name onto another service's method. Both are
# the same operation the dispatcher's state-modifying set describes, under a
# spelling the set does not contain. The pair is what dispatch executes.


def is_state_modifying_pair(service: str | None, method: str | None) -> bool:
    """True when ``(service, method)`` is what a state-modifying ACTION_MAP
    action dispatches to. If the tables cannot load, True (fail closed)."""
    try:
        from runtime.blockchain.services.service_dispatcher import (
            ACTION_MAP, _STATE_MODIFYING_ACTIONS,
        )
        pair = (str(service or ""), str(method or ""))
        return any(ACTION_MAP.get(a) == pair for a in _STATE_MODIFYING_ACTIONS)
    except Exception:  # pragma: no cover — tables unavailable: treat as mutating
        logger.debug("Could not load ACTION_MAP; treating %s.%s as state-modifying", service, method)
        return True


def dispatch_pair(action: object, service: object = None) -> tuple[str, str] | None:
    """The ``(service, method)`` ServiceDispatcher.execute runs for *action*,
    resolved the way it resolves it: ACTION_MAP, then a truthy ``service``
    override replaces the service. None for an unknown or non-string action."""
    if not isinstance(action, str):
        return None
    from runtime.blockchain.services.service_dispatcher import ACTION_MAP
    pair = ACTION_MAP.get(action)
    if pair is None:
        return None
    return (str(service) if service else pair[0], pair[1])


# Operations no request may have dispatched, whoever sends it: the operator key,
# a session, an anonymous chat, a caller with no HTTP request behind it. Keyed
# on the pair a dispatch RUNS (dispatch_pair), so a new action name or a
# platform_action ``service`` override onto the same method is the same answer.
#
# The attestation service signs with the platform's key (a time-critical
# category and a revocation through the unmetered signer), and these three take
# what it signs from the request: the schema, the data — its action, its agent,
# its category — and the recipient; or the uid of any attestation the platform
# ever made, to void it. The platform attests what it EXECUTES: the
# dispatcher's own record of an action it ran, each service's record of an
# operation it performed. Those are called in process and never come through a
# door, so they are untouched. The twin ``eas`` tool refuses the same three
# (runtime/blockchain/eas_manager.py); tests/test_no_request_makes_the_
# attestation_service_sign.py drives every door that reaches the dispatcher.
_PLATFORM_KEY_STATEMENT = (
    "The platform's key signs no attestation a request composes and revokes none "
    "a request names; the platform attests an action when it executes it. "
    "Nothing was signed.")
#
# The same answer, for the same reason, where the services layer signs, with
# the platform's key, a call or a statement the request composed. Each of these
# is also refused inside the service itself, before anything is built, so a
# door this table does not reach still signs nothing; the KYC credential is the
# one kept callable in process (its lifting condition is in the service).
# tests/test_no_request_chooses_the_call_the_platform_key_signs.py walks every
# signing call and fails on one that carries bytes the request wrote.
_COMPOSED_CALL_STATEMENT = (
    "The platform's key makes no call a request composes: a token-bound "
    "account's execute carries the request's target, value and calldata, and "
    "would pay the platform's own ETH to the account the request names. "
    "Nothing was signed.")
_COMPOSED_MESSAGE_STATEMENT = (
    "The platform's key sends no cross-chain message a request writes: the "
    "receiving chain reads the platform's wallet as the message's sender. "
    "Nothing was signed.")
_KYC_STATEMENT = (
    "The platform's key attests no KYC credential on a request: the "
    "verification it would attest arrives in the request, and the platform "
    "holds no provider result of its own to check it against. Nothing was signed.")
# A recovery or a session key is a call on an account-abstraction module, and
# the module decides by who calls it. Sent from the platform's wallet, the
# platform's own standing with the module (as a guardian, if it lets the
# platform be one) would authorize handing the account the request names to a
# new owner or to a new key of the request's choosing, and nothing tied that
# account to the caller. Both are refused in the service as well.
_ACCOUNT_AUTHORITY_STATEMENT = (
    "The platform's key recovers no account and registers no session key on a "
    "request: the module call would be sent from the platform's wallet, so the "
    "platform's standing with the module, not the account holder's, would hand "
    "the account the request names to a new owner or a new key. Nothing was signed.")
REFUSED_ON_REQUEST: dict[tuple[str, str], str] = {
    ("attestation", "attest"): _PLATFORM_KEY_STATEMENT,
    ("attestation", "batch_attest"): _PLATFORM_KEY_STATEMENT,
    ("attestation", "revoke"): _PLATFORM_KEY_STATEMENT,
    ("advanced_governance", "submit_retropgf"): _PLATFORM_KEY_STATEMENT,
    ("kyc", "issue_kyc_credential"): _KYC_STATEMENT,
    ("tba", "execute_as_tba"): _COMPOSED_CALL_STATEMENT,
    ("ccip", "send_cross_chain_message"): _COMPOSED_MESSAGE_STATEMENT,
    ("ccip", "bridge_hyperlane"): _COMPOSED_MESSAGE_STATEMENT,
    ("ccip", "bridge_wormhole"): _COMPOSED_MESSAGE_STATEMENT,
    ("ccip", "bridge_axelar"): _COMPOSED_MESSAGE_STATEMENT,
    ("mpc", "recover_wallet"): _ACCOUNT_AUTHORITY_STATEMENT,
    ("mpc", "create_session_key"): _ACCOUNT_AUTHORITY_STATEMENT,
}


# The same answer for a TOOL call, where a tool has the platform's key sign a
# call the request composed. ``smart_contract``'s ``send`` built
# ``contract.functions[function_name](*args)`` on the contract, ABI, arguments
# and value the request wrote and signed it from the platform wallet: aimed at
# the EAS contract, an ``attest`` or a ``revoke`` of the request's making. The
# tool refuses it before anything is built (runtime/blockchain/smart_contracts
# .py); the tool dispatcher refuses it before the handler runs, whoever asks,
# so a tool that lost its own refusal still signs nothing. Keyed on the tool
# and its ``action``; the doors that dispatch an action by name cannot reach a
# tool at all. tests/test_no_door_has_the_platform_key_sign_a_call_it_composed
# .py drives every door with the EAS contract's attest and revoke.
COMPOSED_CONTRACT_CALL_STATEMENT = (
    "The platform's key signs no contract call a request composes: the "
    "contract, the function, its arguments and the value would all be the "
    "request's, sent from the platform wallet. Read with action 'call', and "
    "write with your own signer. Nothing was signed.")
REFUSED_TOOL_CALLS: dict[tuple[str, str], str] = {
    ("smart_contract", "send"): COMPOSED_CONTRACT_CALL_STATEMENT,
}


def refused_tool_call(tool_name: object, arguments: object) -> str | None:
    """Why no request may have *tool_name* run with *arguments*, or None."""
    action = arguments.get("action") if isinstance(arguments, dict) else None
    if not isinstance(tool_name, str) or not isinstance(action, str):
        return None
    return REFUSED_TOOL_CALLS.get((tool_name, action.strip().lower()))


def refused_by_the_service(service: str, method: str) -> dict:
    """What a service method in REFUSED_ON_REQUEST returns when it is reached
    anyway: a refusal, before anything is built or signed."""
    return {
        "status": "refused",
        "refused": True,
        "service": service,
        "method": method,
        "error": REFUSED_ON_REQUEST[(service, method)],
        "signed": False,
    }


def refused_on_request(action: object, service: object = None) -> str | None:
    """Why no request may dispatch *action* (with *service* as a platform_action
    override would set it), or None. Resolved on the pair, the way
    ServiceDispatcher.execute resolves it."""
    pair = dispatch_pair(action, service)
    return REFUSED_ON_REQUEST.get(pair) if pair is not None else None


# ── What a user session may not have the platform do for it ──────────────
#
# The platform's wallet signs, and platform credentials act, in the services
# layer. Where the request names who is paid or credited (the payee, the
# account), what is spent or bound (the asset), or what is signed or published
# (a key id, a digest, content), a session would decide how the platform's own
# standing is used: its funds, its signing cluster, its publishing account,
# its storage node, its provider account. Those actions are refused to a
# session, and to chat acting for one (request_execution and platform_action
# with the session's credential), at every door a session reaches: capability
# invoke, /bridge/v1/action and the tool dispatcher. The operator's key, and a
# dispatch with no HTTP caller behind it, keep them. Any other caller kind (an
# anonymous caller, a kind this module does not know) is refused them too.
#
# The list is not kept by hand alone. tests/test_no_session_has_the_platform_
# act_on_what_it_names.py derives it from two walks of the source: every
# address a request supplies to a call the services layer signs
# (tests/test_no_request_chooses_the_call_the_platform_key_signs.py
# SERVICE_ADDRESSES, a payee or an asset, and the two payees encoded as
# bytes), and every HTTP request a services-layer method sends. A pair either
# walk finds must be here, bound or held below, or listed there with its
# reason; the test fails on one that is none of these, and on an entry here
# that neither walk finds.
_SESSION_PLATFORM_FUNDS = (
    "A user session does not have the platform's wallet act on a payee, an "
    "account or an asset the request names: the call would be sent from the "
    "platform's wallet, and what it pays, lends, stakes, bridges, delegates, "
    "claims, auctions or creates would be the platform's. The operator's key "
    "keeps this action. Nothing was signed.")
_SESSION_PLATFORM_CREDENTIAL = (
    "A user session does not have a platform credential sign, publish, pay or "
    "authorise what the request names: the key id, the digest or the content "
    "would go out under the platform's own account with the signing cluster, "
    "the publisher, the storage node, the payment node or the provider. The "
    "operator's key keeps this action. Nothing was sent.")
REFUSED_TO_A_SESSION: dict[tuple[str, str], str] = {
    # The platform's wallet signs, with a payee or an asset the request names.
    ("advanced_governance", "delegate_voting"): _SESSION_PLATFORM_FUNDS,
    ("advanced_governance", "place_bribe"): _SESSION_PLATFORM_FUNDS,
    ("auctions", "create_auction"): _SESSION_PLATFORM_FUNDS,
    ("ccip", "bridge_stargate"): _SESSION_PLATFORM_FUNDS,
    ("ccip", "bridge_token_ccip"): _SESSION_PLATFORM_FUNDS,
    ("compute", "claim_compute_reward"): _SESSION_PLATFORM_FUNDS,
    ("creator_platforms", "mint_sound"): _SESSION_PLATFORM_FUNDS,
    ("nft_lending", "borrow_against_nft"): _SESSION_PLATFORM_FUNDS,
    ("nft_lending", "liquidate_nft_loan"): _SESSION_PLATFORM_FUNDS,
    ("oracles_plus", "register_keeper_job"): _SESSION_PLATFORM_FUNDS,
    ("payment_channels", "close_channel"): _SESSION_PLATFORM_FUNDS,
    ("payment_channels", "open_channel"): _SESSION_PLATFORM_FUNDS,
    ("restaking", "delegate_to_operator"): _SESSION_PLATFORM_FUNDS,
    ("restaking", "liquid_stake_lido"): _SESSION_PLATFORM_FUNDS,
    ("restaking", "restake"): _SESSION_PLATFORM_FUNDS,
    ("restaking", "restake_karak"): _SESSION_PLATFORM_FUNDS,
    ("restaking", "restake_symbiotic"): _SESSION_PLATFORM_FUNDS,
    ("restaking", "withdraw_restake"): _SESSION_PLATFORM_FUNDS,
    ("tba", "create_tba"): _SESSION_PLATFORM_FUNDS,
    # A platform credential signs, publishes, pays or authorises what the
    # request names, over HTTP.
    ("compute", "rent_device"): _SESSION_PLATFORM_CREDENTIAL,
    ("compute", "submit_compute_job"): _SESSION_PLATFORM_CREDENTIAL,
    ("creator_platforms", "publish_mirror_post"): _SESSION_PLATFORM_CREDENTIAL,
    ("creator_platforms", "publish_paragraph_post"): _SESSION_PLATFORM_CREDENTIAL,
    ("kyc", "check_aml_risk"): _SESSION_PLATFORM_CREDENTIAL,
    ("kyc", "start_kyc"): _SESSION_PLATFORM_CREDENTIAL,
    ("mpc", "mpc_sign"): _SESSION_PLATFORM_CREDENTIAL,
    ("payment_channels", "route_payment"): _SESSION_PLATFORM_CREDENTIAL,
    ("social_protocols", "publish_cast"): _SESSION_PLATFORM_CREDENTIAL,
    ("storage", "ceramic_stream_create"): _SESSION_PLATFORM_CREDENTIAL,
    ("storage", "orbit_db_write"): _SESSION_PLATFORM_CREDENTIAL,
    ("storage", "store_filecoin"): _SESSION_PLATFORM_CREDENTIAL,
}

# Where the one address the request names is the one the platform acts FOR,
# and the platform spends nothing but gas on it, the action is kept for a
# session and bound: every one of these fields the request carries must be
# the address the session is bound to, and it must carry at least one. A
# session bound to no address (an Apple sign-in with no wallet linked) names
# none it can be held to, and is refused.
BOUND_TO_THE_CALLER: dict[tuple[str, str], tuple[str, ...]] = {
    # LensHub.createProfile((to, followModule, initData)): the profile NFT's owner.
    ("social_protocols", "create_lens_profile"): ("to", "owner", "creator"),
    # createToken(name, symbol, supply, owner): who owns the new token and its supply.
    ("social_protocols", "launch_creator_coin"): ("owner", "creator"),
    ("social_protocols", "launch_social_token"): ("owner", "creator"),
    # The Push subscriber the platform submits to its channel.
    ("social_protocols", "push_subscribe"): ("subscriber", "address"),
}

# Where one field of the request decides whether the platform's server acts
# on what the request writes, a session may send only the values listed. The
# oracle's ``custom`` type sends an HTTP request to the URL, with the method,
# headers and body, the request writes, from the platform's own server; its
# ``sports`` type reads the configured provider, with the platform's key, at a
# path the request writes. A price, a weather reading and a randomness
# request name no address.
HELD_FOR_A_SESSION: dict[tuple[str, str], tuple[str, frozenset]] = {
    ("oracle_gateway", "request"): (
        "oracle_type", frozenset({"price_feed", "weather", "random_vrf"})),
}
_SESSION_ORACLE = (
    "A user session asks the oracle for a price, a weather reading or "
    "randomness only: a custom request would have the platform's server send "
    "whatever the request writes to whatever address it names, and a sports "
    "request reads the provider with the platform's key at a path the request "
    "writes. The operator's key keeps them. Nothing was sent.")

def _unbound(fields: tuple[str, ...], params: object, identity: object) -> str | None:
    """Why *params* do not hold the request to the caller's own address. The
    caller and each field are compared in the one spelling the platform names
    a caller by (runtime/auth/identity.py)."""
    from runtime.auth.identity import is_wallet_address, same_caller
    own = identity
    if not is_wallet_address(own):
        return ("A user session names only its own address here, and this "
                "session is bound to no wallet address. Nothing was signed.")
    if not isinstance(params, dict):
        return "The request's parameters could not be read. Nothing was signed."
    named = [(f, params[f]) for f in fields if params.get(f) not in (None, "")]
    if not named:
        return (f"A user session names its own address as {' or '.join(fields)}; "
                "this request names none. Nothing was signed.")
    other = [f for f, v in named if not same_caller(v, own)]
    if other:
        return (f"A user session names only its own address as {', '.join(other)}: "
                "the platform acts for the address the session is bound to, not "
                "for one the request names. Nothing was signed.")
    return None


def refused_to_the_caller(caller_kind: object, action: object, service: object = None,
                          params: object = None, identity: object = "") -> str | None:
    """Why a caller of *caller_kind* may not have *action* dispatched (with
    *service* as a platform_action override would set it, and *params* as the
    service would read them), or None.

    The operator (``"operator"``) and a dispatch with no HTTP caller (``""``)
    are never refused here. Every other kind is refused REFUSED_TO_A_SESSION's
    pairs, held to its own address (*identity*) in BOUND_TO_THE_CALLER's, and
    to the listed values in HELD_FOR_A_SESSION's. Resolved on the pair, the way
    ServiceDispatcher.execute resolves it."""
    if caller_kind in ("operator", ""):
        return None
    pair = dispatch_pair(action, service)
    if pair is None:
        return None
    refused = REFUSED_TO_A_SESSION.get(pair)
    if refused:
        return refused
    fields = BOUND_TO_THE_CALLER.get(pair)
    if fields:
        return _unbound(fields, params, identity)
    held = HELD_FOR_A_SESSION.get(pair)
    if held:
        field, allowed = held
        value = params.get(field) if isinstance(params, dict) else None
        if value not in allowed:
            return _SESSION_ORACLE
    return None


def operation_could_move_value(action_type: str | None, service: str | None = None,
                               method: str | None = None) -> bool:
    """`could_move_value` for a label, AND for the pair that label runs: either
    one saying "could move value" fails closed."""
    if could_move_value(action_type):
        return True
    return service is not None and method is not None and is_state_modifying_pair(service, method)


def dispatch_could_move_value(tool_name: str, arguments: object) -> bool:
    """The fail direction for a TOOL CALL, keyed on its canonical label and, for
    the dispatching tools, on the pair the call resolves to (including a
    platform_action ``service`` override)."""
    from runtime.security.action_map import canonical_action
    action_type, _ = canonical_action(tool_name, arguments)
    args = arguments if isinstance(arguments, dict) else {}
    pair = None
    if tool_name in ("platform_action", "request_execution"):
        pair = dispatch_pair(args.get("action"),
                             args.get("service") if tool_name == "platform_action" else None)
    if pair is None:
        return could_move_value(action_type)
    return operation_could_move_value(action_type, *pair)


def default_agent_access(agent: str | None, tool: str, action: str | None = None) -> tuple[bool, str]:
    """Coarse PUBLIC per-agent access decision. Returns ``(allowed, reason)``.

    - ``agent is None`` (no agent context — internal/test path): allowed (the
      agent boundary only applies to identified agents).
    - Unknown agent name: denied (fail-closed).
    """
    if agent is None:
        return (True, "")  # internal/test path with no agent context; the boundary does not apply

    a = str(agent).strip().lower()
    if a == "":
        # A caller-supplied EMPTY name is not the internal path — it is a request
        # that names no agent so that no boundary can apply to it. Fail closed.
        return (False, "no agent named; the per-agent boundary cannot be applied — refused")

    if a == "neo":
        return (True, "")  # full execution set

    if a == "trinity":
        if tool not in _TRINITY_TOOLS:
            return (False, f"Trinity may not use '{tool}'. She is the conversational "
                           f"interface; execution tools belong to Neo. Escalate through "
                           f"the Morpheus security gate to Neo.")
        if tool == "platform_action" and _is_state_modifying(action):
            return (False, f"Trinity may not execute the state-changing action '{action}'. "
                           f"She passes the request to Neo through the Morpheus security "
                           f"gate; she never executes it herself.")
        return (True, "")

    if a == "morpheus":
        if tool not in _MORPHEUS_TOOLS:
            return (False, f"Morpheus is a security/guidance agent and may not use '{tool}'.")
        if tool == "platform_action":
            if _is_state_modifying(action):
                return (False, f"Morpheus does not execute state-changing actions "
                               f"('{action}'). He informs and gates; he never executes.")
            if action and not any(k in action.lower() for k in _MORPHEUS_ACTION_KEYWORDS):
                return (False, f"Morpheus is limited to read-only security/verification "
                               f"actions; '{action}' is out of his scope.")
        return (True, "")

    # Any other (unrecognised) agent identity → fail-closed.
    return (False, f"Unknown agent '{agent}' — denied by the access policy.")
