"""Per-agent tool access policy — the PUBLIC, coarse default boundary.

This is the visible, code-enforced boundary that decides which agent may invoke
which tool/action. It is consulted by the ToolDispatcher on EVERY tool call,
keyed on the trusted ``agent_name`` from the gateway-validated request context —
NOT on anything the model can put in its tool arguments. A subverted agent
therefore cannot call another agent's tools: the dispatcher refuses based on who
the caller IS, regardless of what the prompt says.

This module is the coarse PUBLIC floor. The authoritative, finer-grained policy
(exact per-agent sets, ban/freeze integration, the closed-source nuance) lives in
the private ``matrix_security.agent_access`` package and supersedes this when it
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
    sets — just generic read verbs. The authoritative classification still lives in
    the private gate; this only decides the safe direction on a gateway fault.
    """
    a = (action_type or "").strip().lower()
    if not a:
        return True  # unknown → safest direction: treat as value-moving
    if a in _BENIGN_READ_LABELS or a.startswith(_BENIGN_READ_PREFIXES):
        return False  # clearly a benign read → a transient fault may observe-allow it
    return True       # value-moving / owner-gated / unrecognised → fail closed


def default_agent_access(agent: str | None, tool: str, action: str | None = None) -> tuple[bool, str]:
    """Coarse PUBLIC per-agent access decision. Returns ``(allowed, reason)``.

    - ``agent is None`` (no agent context — internal/test path): allowed (the
      agent boundary only applies to identified agents).
    - Unknown agent name: denied (fail-closed).
    """
    a = (agent or "").strip().lower()

    if a == "":
        return (True, "")  # non-agent path; the boundary does not apply

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
