"""Per-agent tool access policy — the PUBLIC, coarse default boundary.

This is the visible, code-enforced boundary that decides which agent may invoke
which tool/action. It is consulted by the ToolDispatcher on EVERY tool call,
keyed on the trusted ``agent_name`` from the gateway-validated request context —
NOT on anything the model can put in its tool arguments. A subverted agent
therefore cannot call another agent's tools: the dispatcher refuses based on who
the caller IS, regardless of what the prompt says.

This module is the coarse PUBLIC floor. The authoritative, finer-grained policy
(exact per-agent sets, ban/freeze integration, the closed-source nuance) lives in
the private ``morpheus_security.agent_access`` package and supersedes this when it
is installed. The security seam (``runtime.security.agent_access_allowed``) binds
the two: private if present, else this default. Either way the boundary holds.

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
