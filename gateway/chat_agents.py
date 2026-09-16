"""The agent a chat names, decided once for every chat surface.

A chat body names its agent. Before this module each surface judged that name
on its own, and none of them canonicalised it. The operator-only check compared
``agent in ("neo", "morpheus")`` exactly, while the per-agent tool policy
lowercases. So on /bridge/v1/chat, which had no membership check at all, a
caller with no credential who sent ``"Neo"`` passed the operator check and was
served Neo's full toolset, bash included. /chat and /ws answered 400 only
because their membership check happened to be case-sensitive too.

One canonical form (strip, lower), then membership, then the operator check on
that canonical name. Every surface calls ``resolve_chat_agent`` and hands the
canonical name to the agent loop, so the name that is judged is the name that
runs.
"""
from __future__ import annotations

CHAT_AGENTS: frozenset[str] = frozenset({"trinity", "neo", "morpheus"})
#: Agents a chat may name only with the operator key.
OPERATOR_AGENTS: frozenset[str] = frozenset({"neo", "morpheus"})
#: The one agent a caller without the operator key is served by.
USER_AGENT = "trinity"


def canonical_agent(raw: object) -> str:
    """The agent name the policy and the loop both read: stripped, lowercased."""
    return str(raw).strip().lower()


def resolve_chat_agent(raw: object, is_operator: bool):
    """``(agent, None)`` when the caller may talk to *raw*'s agent, else
    ``(None, (status, message))``: 400 for a name that is no agent, 403 for an
    operator-only agent named without the operator key."""
    agent = canonical_agent(raw)
    if agent not in CHAT_AGENTS:
        return None, (400, "invalid agent, must be one of: " + ", ".join(sorted(CHAT_AGENTS)))
    if agent in OPERATOR_AGENTS and not is_operator:
        return None, (403, f"agent '{agent}' requires the operator key; users talk to "
                           f"Trinity (omit 'agent' or send '{USER_AGENT}')")
    return agent, None
