"""Agent hand-off — the controlled Trinity → Morpheus → Neo escalation channel.

Trinity is the conversational interface; she does NOT hold Neo's execution tools
(enforced by the per-agent boundary in the dispatcher). When a user request needs
real execution / finances, Trinity passes it through THIS channel rather than
executing it herself:

    Trinity  --request_execution(action, params)-->  AgentHandoff.escalate
        1. Morpheus security gate evaluates the request.
        2. Only on PASS does Neo execute it (via the service dispatcher, which
           runs the EAS attestation; the protocol stack's Glasswing audit applies
           on the contract path).
        3. The result is returned to Trinity to relay to the user.

Trinity never gains Neo's tools — she only ever holds this single, gated channel.
A denied request comes back as a controlled refusal, never an execution.

This is the public wiring of the hand-off; the Morpheus gate's decision logic is
the closed-source security layer (consulted through the seam). Default OBSERVE
(the gate logs/classifies but does not hard-block until human review enables
ENFORCE); the hand-off STRUCTURE — escalate, gate, route-to-Neo — is enforced
here regardless of mode.
"""

from __future__ import annotations

import json
import logging
from typing import Any

logger = logging.getLogger(__name__)


class AgentHandoff:
    """Trinity → Morpheus → Neo escalation. Constructed with the platform config
    and the ServiceDispatcher that performs Neo's execution."""

    def __init__(self, config: dict, service_dispatcher: Any) -> None:
        self._config = config
        self._dispatcher = service_dispatcher

    async def escalate(
        self,
        action: str,
        params: dict | None = None,
        context: dict | None = None,
    ) -> dict[str, Any]:
        """Escalate a single execution request from Trinity to Neo through the
        Morpheus gate. Returns a structured result describing the hand-off."""
        params = params or {}
        ctx = {**(context or {}), "via_agent_flow": True, "origin_agent": "trinity"}

        # 1. Morpheus security gate (authoritative server-side). OBSERVE by default:
        #    it logs/classifies and (in ENFORCE) can deny. We honour an explicit deny.
        decision: dict[str, Any] = {}
        try:
            from runtime.security import get_morpheus_security
            gate = get_morpheus_security(self._config)
            decision = await gate.evaluate(
                {"action_type": action, "parameters": params}, ctx
            )
        except Exception:
            logger.exception("Morpheus gate failed during hand-off; refusing (fail-closed)")
            return {
                "handoff": "trinity->morpheus->neo",
                "approved": False,
                "reason": "Security gate unavailable — request not escalated.",
            }

        if not decision.get("allow", True):
            return {
                "handoff": "trinity->morpheus->neo",
                "approved": False,
                "reason": decision.get("reason", "Blocked by the Morpheus security gate."),
                "morpheus": decision,
            }

        # 2. PASS → Neo executes. The service dispatcher attests state-modifying
        #    actions on success; the protocol stack's Glasswing audit applies to the
        #    contract path. Trinity never touches this executor directly.
        if self._dispatcher is None:
            return {
                "handoff": "trinity->morpheus->neo",
                "approved": True,
                "executed": False,
                "reason": "No executor wired (service dispatcher unavailable).",
                "morpheus": decision,
            }
        try:
            result = await self._dispatcher.execute(action, None, params)
        except Exception as exc:  # noqa: BLE001
            logger.exception("Neo execution failed during hand-off")
            return {
                "handoff": "trinity->morpheus->neo",
                "approved": True,
                "executed": False,
                "reason": f"Neo execution error: {exc}",
                "morpheus": decision,
            }

        return {
            "handoff": "trinity->morpheus->neo",
            "approved": True,
            "executed_as": "neo",
            "morpheus": decision,
            "result": result,
        }

    async def as_tool(self, action: str = "", params: dict | None = None, **extra: Any) -> str:
        """Tool-handler shape: returns a JSON string for the ReAct loop. ``params``
        may arrive as a dict or be spread across keyword args."""
        merged = dict(params or {})
        merged.update({k: v for k, v in extra.items() if k not in ("action", "params")})
        outcome = await self.escalate(action, merged)
        return json.dumps(outcome, default=str)

    @property
    def schema(self) -> dict:
        return {
            "type": "function",
            "function": {
                "name": "request_execution",
                "description": (
                    "Escalate a request that needs real on-chain execution or moves "
                    "funds. Trinity calls this to hand the request to Neo through the "
                    "Morpheus security gate; she never executes it herself. Returns the "
                    "gate decision and, on pass, Neo's execution result."
                ),
                "parameters": {
                    "type": "object",
                    "properties": {
                        "action": {"type": "string", "description": "The platform action to execute (e.g. deploy_contract, swap_tokens)."},
                        "params": {"type": "object", "description": "Parameters for the action."},
                    },
                    "required": ["action"],
                },
            },
        }
