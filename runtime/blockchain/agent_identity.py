"""
Agent Identity — on-chain identity for AI agents in The Matrix.

Each agent (Neo, Trinity, Morpheus) can have an on-chain identity
attested via EAS, enabling verifiable agent actions.
Gas is paid by the platform within its sponsorship policy.
"""

import json
import logging
import time

from runtime.blockchain.interface import BlockchainInterface
from runtime.protocols.outcome_truth import FAILURE, OUTCOME_FIELD, SUCCESS, refusal

logger = logging.getLogger(__name__)


#: The agents this platform runs. A registration signed with the platform key
#: says "this is one of ours"; it is not signed for a name the platform does
#: not run (register entry::B3-ATTEST-SIBLING, the register half).
PLATFORM_AGENTS = ("neo", "trinity", "morpheus")


def agent_key(params: dict) -> str:
    """The agent a request names, in the one form every action keys on.

    A registration is cached under this key and a verification looks it up
    under this key; if they normalised differently, registering "Neo" and then
    verifying "Neo" would find nothing. An absent name is Neo, as it always
    was; an empty one stays empty and names no agent."""
    return str(params.get("agent_name", "neo") or "").strip().lower()


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
        return ("Manage on-chain agent identities: register one of the platform's agents "
                "(neo, trinity, morpheus), verify a registration, read an identity. "
                "attest_action is refused: the platform attests an action when it executes "
                "it, never from a description. Gas is paid by the platform within its "
                "sponsorship policy.")

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
        """Register one of the platform's agents on-chain via EAS attestation.

        The name is the only thing the caller chooses in this attestation, and
        the platform key signs it: so it must be an agent the platform runs."""
        agent_name = agent_key(params)
        if agent_name not in PLATFORM_AGENTS:
            return refusal(
                f"'{params.get('agent_name')}' is not one of this platform's agents "
                f"({', '.join(PLATFORM_AGENTS)}); the platform key signs a registration "
                "only for an agent the platform runs.",
                code="denied")
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
            operation="agent_identity.register",
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
        exists + not revoked), then reads it: the platform wallet must be its
        attester, the configured schema its schema, and its data must say
        ``agent_registration`` for THIS agent. The uid can be the caller's, and
        anyone can attest anything on EAS; an attestation that merely exists
        verified any agent the caller named. ``verified`` is derived only from
        the agent's own attestation — never from unrelated platform-wallet
        activity (the previous ``tx_count > 0`` trap). Fail-closed:
          • no registration resolved   -> verified False ("no registration")
          • RPC/EAS unconfigured        -> verified False ("lookup unconfigured")
          • attestation absent/revoked  -> verified False (honest reason)
          • not the platform's registration of this agent -> verified False

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
        agent_name = agent_key(params)
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
            # Existing and unrevoked is not enough: anyone can make an
            # attestation on EAS, under any schema, saying anything, and the uid
            # here is the caller's to write. It is this agent's registration
            # only if the PLATFORM made it, under the platform's schema, and it
            # says "agent_registration" for this agent.
            mismatch = self._not_this_agents_registration(result, agent_name)
            if mismatch:
                # The check ran and answered no. The call succeeded.
                return json.dumps({**base, OUTCOME_FIELD: SUCCESS, "verified": False,
                                   "attestation_uid": uid, "attester": result.get("attester"),
                                   "reason": mismatch}, indent=2)
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

    def _not_this_agents_registration(self, found: dict, agent_name: str) -> str | None:
        """Why the attestation *found* is not the platform's registration of
        *agent_name*, or None when it is. Reads what ``_register`` writes: the
        platform wallet as attester, the configured schema, and data encoding
        (platform, "agent_registration", agent, timestamp)."""
        bc = self.config.get("blockchain", {}) if isinstance(self.config, dict) else {}

        def norm(value) -> str:
            text = str(value or "").strip().lower()
            return text[2:] if text.startswith("0x") else text

        wallet, schema = norm(bc.get("platform_wallet")), norm(bc.get("eas_schema"))
        if not wallet or norm(found.get("attester")) != wallet:
            return ("This attestation was not made by the platform, so it is not this "
                    "agent's registration.")
        if not schema or norm(found.get("schema")) != schema:
            return ("This attestation is not under the platform's registration schema, so "
                    "it is not this agent's registration.")
        try:
            from eth_abi import decode
            _platform, action, agent, _ts = decode(
                ["string", "string", "string", "uint256"], bytes.fromhex(norm(found.get("data"))))
        except Exception:
            return "This attestation's data is not a registration the platform wrote."
        if action != "agent_registration" or str(agent).strip().lower() != agent_name:
            return (f"This attestation is the platform's, but it is not a registration of "
                    f"agent '{agent_name}'.")
        return None

    async def _attest_action(self, params: dict) -> str:
        """REFUSED. This signed a public, platform-keyed statement that agent
        ``agent_name`` performed ``agent_action`` — both strings as the request
        wrote them (register entry::B3-ATTEST-SIBLING). The platform attests an
        action when it EXECUTES it (ServiceDispatcher._attest_action, from the
        executed call's own record); a statement composed by the caller is not
        one the platform key can stand behind, so there is nothing here to sign.
        """
        return refusal(
            "The platform attests an action when it executes it. It does not sign an "
            "attestation whose action and agent are whatever the request says; "
            "nothing was attested.",
            code="denied")

    async def _get_identity(self, params: dict) -> str:
        agent_name = agent_key(params)
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
