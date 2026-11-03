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

from runtime.protocols.outcome_truth import FAILURE, OUTCOME_FIELD, report_of

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
        Morpheus gate. Returns a structured result describing the hand-off.

        EVERY RETURN BELOW STATES ITS OUTCOME, and none of them did.

        This is the only channel Trinity has to anything that moves value, and
        its refusal shape — `{"handoff": ..., "approved": false, "reason": ...}`
        — carries no field the outcome classifier reads. No `ok`, no `success`,
        no `status`, and `approved` means "the gate allowed it", not "it
        happened". So a structure whose entire content is a denial fell through
        to the measured default for a report that says nothing about itself, and
        every Morpheus denial, every fail-closed gate fault and every unwired
        executor was recorded as a successful execution. Outcome learning then
        blended those into the base rates that drive future confidence: the more
        often the gate refused Trinity, the more confident the platform became.

        The relay path was no better. `{"approved": true, "executed_as": "neo",
        "result": <Neo's envelope>}` asserts nothing about itself either, so
        Neo's own refusal — already wrapped in the dispatcher's envelope —
        arrived as a success too. It is stated here rather than inferred
        downstream: this frame is the one that knows the gate's decision, knows
        whether an executor existed, and holds Neo's structured report.
        """
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
                OUTCOME_FIELD: FAILURE,
                "approved": False,
                "reason": "Security gate unavailable — request not escalated.",
            }

        if not decision.get("allow", True):
            return {
                "handoff": "trinity->morpheus->neo",
                OUTCOME_FIELD: FAILURE,
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
                # Approved and NOT executed. Nothing ran, so nothing succeeded —
                # the gate's verdict is not the call's.
                OUTCOME_FIELD: FAILURE,
                "approved": True,
                "executed": False,
                "reason": "No executor wired (service dispatcher unavailable).",
                "morpheus": decision,
            }
        try:
            # 17-J: this chain has no human caller — Trinity -> Morpheus -> Neo is
            # agent-to-agent, with no HTTP request, session or wallet anywhere in
            # the path. `caller_identity` is correctly "", and DECLARING the
            # source is what stops that "" being read as a dropped identity.
            result = await self._dispatcher.execute(
                action, None, params, caller_source="agent_handoff",
            )
        except Exception as exc:  # noqa: BLE001
            logger.exception("Neo execution failed during hand-off")
            return {
                "handoff": "trinity->morpheus->neo",
                OUTCOME_FIELD: FAILURE,
                "approved": True,
                "executed": False,
                "reason": f"Neo execution error: {exc}",
                "morpheus": decision,
            }

        # NEO'S VERDICT, RELAYED — not the hand-off's opinion of it. The
        # dispatcher's envelope already states what the service reported, so this
        # reads that field rather than re-classifying a payload it did not
        # produce; a second classification here would be a second source of
        # truth for the same fact.
        return {
            "handoff": "trinity->morpheus->neo",
            OUTCOME_FIELD: report_of(result),
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
