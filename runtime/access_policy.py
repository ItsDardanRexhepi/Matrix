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
_TRINITY_TOOLS = frozenset({"web_search", "web", "platform_action"})

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
