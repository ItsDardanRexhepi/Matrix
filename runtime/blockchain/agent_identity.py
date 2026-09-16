"""
Agent Identity — on-chain identity for AI agents in The Matrix.

Each agent (Neo, Trinity, Morpheus) can have an on-chain identity
attested via EAS, enabling verifiable agent actions.
Gas covered by the platform.
"""

import json
import logging
import time

from runtime.blockchain.interface import BlockchainInterface
from runtime.protocols.outcome_truth import FAILURE, OUTCOME_FIELD, SUCCESS, refusal

logger = logging.getLogger(__name__)


class AgentIdentity(BlockchainInterface):

    def __init__(self, config: dict):
        super().__init__(config)
        # agent_name -> its registration attestation UID, captured on register so
        # verify can resolve it without the caller re-supplying it (best-effort
        # in-process cache; callers may also pass attestation_uid explicitly).
        self._registrations: dict[str, str] = {}

    @property
    def name(self) -> str:
        return "agent_identity"

    @property
    def description(self) -> str:
        return "Manage on-chain agent identities: register, verify, attest agent actions. Gas covered by platform."

    @property
    def parameters(self) -> dict:
        return {
            "type": "object",
            "properties": {
                "action": {"type": "string", "enum": ["register", "verify", "attest_action", "get_identity"]},
                "agent_name": {"type": "string", "description": "Agent name (neo, trinity, morpheus)"},
                "agent_action": {"type": "string", "description": "Action the agent performed"},
                "details": {"type": "object"},
            },
            "required": ["action"],
        }

    async def execute(self, **kwargs) -> str:
        action = kwargs.get("action", "")
        if action == "register":
            return await self._register(kwargs)
        elif action == "verify":
            return await self._verify(kwargs)
        elif action == "attest_action":
            return await self._attest_action(kwargs)
        elif action == "get_identity":
            return await self._get_identity(kwargs)
        return refusal(f"Unknown agent identity action: {action}", code="unknown_action")

    async def _register(self, params: dict) -> str:
        """Register an agent's on-chain identity via EAS attestation."""
        agent_name = params.get("agent_name", "neo")
        from runtime.blockchain.eas_client import EASClient
        client = EASClient(self.config)
        result = await client.attest(
            action="agent_registration",
            agent=agent_name,
            details={
                "platform": "The Matrix",
                "agent": agent_name,
                "registered_at": int(time.time()),
                "capabilities": self._get_capabilities(agent_name),
            },
        )
        # Cache the real attestation UID (only when the attest actually produced
        # one) so verify() can resolve this agent later. Never fabricate.
        uid = result.get("uid") or result.get("attestation_uid") if isinstance(result, dict) else None
        if uid and str(uid).startswith("0x") and len(str(uid)) == 66:
            self._registrations[agent_name] = uid
        return json.dumps(result, indent=2, default=str)

    async def _verify(self, params: dict) -> str:
        """Verify an agent's on-chain identity (M2, real per-agent check).

        Resolves THIS agent's own registration attestation UID (from an explicit
        ``attestation_uid`` param, else the register-time cache) and checks THAT
        attestation on-chain via ``EASClient.verify`` (EAS ``getAttestation``:
        exists + not revoked). ``verified`` is derived only from the agent's own
        attestation — never from unrelated platform-wallet activity (the previous
        ``tx_count > 0`` trap). Fail-closed:
          • no registration resolved   -> verified False ("no registration")
          • RPC/EAS unconfigured        -> verified False ("lookup unconfigured")
          • attestation absent/revoked  -> verified False (honest reason)

        AND ``verified`` IS NOT A FIELD THE OUTCOME CLASSIFIER READS. Every
        branch below returns a structure with no ``ok``, no ``status`` and no
        ``error``, so all of them — the two that could not look and the three
        that looked and answered — were read as clean successes and learned from
        as such. The refusals and the answers are not the same fact, and they are
        not labelled the same way here:

          • no registration, or the lookup unconfigured -> the verification did
            NOT RUN. The call failed to do what was asked. FAILURE.
          • absent, revoked, invalid, or verified -> the verification RAN and
            answered. The call succeeded; ``verified: False`` is its answer about
            the SUBJECT, not a report of its own failure. Labelling those as
            failed calls would teach the learner that checking a bad credential
            is a broken tool.
        """
        agent_name = params.get("agent_name", "neo")
        uid = params.get("attestation_uid") or self._registrations.get(agent_name)

        base = {"agent": agent_name, "platform": "The Matrix", "network": self.network,
                "capabilities": self._get_capabilities(agent_name)}

        if not (uid and str(uid).startswith("0x")):
            # Nothing to check against: the verification did not run.
            return json.dumps({**base, OUTCOME_FIELD: FAILURE, "verified": False,
                               "reason": f"No registration attestation found for agent '{agent_name}'. "
                                         "Register the agent first (action=register)."}, indent=2)

        from runtime.blockchain.eas_client import EASClient
        result = await EASClient(self.config).verify(str(uid))

        if result.get("error"):
            # RPC / EAS contract not configured — cannot confirm; never say true.
            # The platform could not look. That is a refusal, not an answer.
            return json.dumps({**base, OUTCOME_FIELD: FAILURE, "verified": False,
                               "attestation_uid": uid,
                               "reason": "Attestation lookup unconfigured (RPC / EAS contract "
                                         "not configured); this agent's identity cannot be confirmed."},
                              indent=2)
        if result.get("verified"):
            return json.dumps({**base, OUTCOME_FIELD: SUCCESS, "verified": True,
                               "attestation_uid": uid,
                               "attester": result.get("attester"),
                               "verified_via": "eas:getAttestation"}, indent=2)
        if not result.get("exists"):
            reason = "No such attestation exists on-chain for this agent."
        elif result.get("revoked"):
            reason = "This agent's attestation has been revoked."
        else:
            reason = "This agent's attestation is invalid."
        # The check RAN and returned a negative answer. The call succeeded.
        return json.dumps({**base, OUTCOME_FIELD: SUCCESS, "verified": False,
                           "attestation_uid": uid, "reason": reason}, indent=2)

    async def _attest_action(self, params: dict) -> str:
        """Attest an action performed by an agent."""
        from runtime.blockchain.eas_client import EASClient
        client = EASClient(self.config)
        result = await client.attest(
            action=params.get("agent_action", "unknown"),
            agent=params.get("agent_name", "neo"),
            details=params.get("details", {}),
        )
        return json.dumps(result, indent=2, default=str)

    async def _get_identity(self, params: dict) -> str:
        agent_name = params.get("agent_name", "neo")
        return json.dumps({
            "agent": agent_name,
            "role": self._get_role(agent_name),
            "capabilities": self._get_capabilities(agent_name),
            "platform": "The Matrix",
            "network": self.network,
        }, indent=2)

    def _get_capabilities(self, agent: str) -> list[str]:
        caps = {
            "neo": ["execution", "blockchain", "tools", "bash"],
            "trinity": ["conversation", "explanation", "translation"],
            "morpheus": ["guidance", "security", "risk_assessment"],
        }
        return caps.get(agent, [])

    def _get_role(self, agent: str) -> str:
        roles = {"neo": "execution", "trinity": "conversation", "morpheus": "guidance"}
        return roles.get(agent, "unknown")
