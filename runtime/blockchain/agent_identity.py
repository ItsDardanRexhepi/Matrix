"""
Agent Identity — on-chain identity for AI agents in 0pnMatrx.

Each agent (Neo, Trinity, Morpheus) can have an on-chain identity
attested via EAS, enabling verifiable agent actions.
Gas covered by the platform.
"""

import json
import logging
import time

from runtime.blockchain.interface import BlockchainInterface

logger = logging.getLogger(__name__)


class AgentIdentity(BlockchainInterface):

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
        return f"Unknown agent identity action: {action}"

    async def _register(self, params: dict) -> str:
        """Register an agent's on-chain identity via EAS attestation."""
        agent_name = params.get("agent_name", "neo")
        from runtime.blockchain.eas_client import EASClient
        client = EASClient(self.config)
        result = await client.attest(
            action="agent_registration",
            agent=agent_name,
            details={
                "platform": "0pnMatrx",
                "agent": agent_name,
                "registered_at": int(time.time()),
                "capabilities": self._get_capabilities(agent_name),
            },
        )
        return json.dumps(result, indent=2, default=str)

    async def _verify(self, params: dict) -> str:
        """Verify an agent's on-chain identity.

        HONEST FAILURE (fail-closed): there is no per-agent attestation/registration
        lookup yet, so this CANNOT confirm a specific agent's identity. It must NOT
        report ``verified`` based on an unrelated condition — the previous version set
        ``verified = tx_count > 0`` on the SHARED platform wallet, so ANY agent name
        passed once that one wallet had a single transaction. A check that passes for
        the wrong reason is the same danger class as a fake success. Until the real
        per-agent attestation check is built, this returns ``verified: False`` with an
        honest reason. The wallet figures below are CONTEXT ONLY and are explicitly not
        the basis for verification.
        """
        agent_name = params.get("agent_name", "neo")
        try:
            balance_wei = self.web3.eth.get_balance(self.platform_wallet) if self.platform_wallet else 0
            tx_count = self.web3.eth.get_transaction_count(self.platform_wallet) if self.platform_wallet else 0
        except Exception:
            balance_wei, tx_count = 0, 0

        return json.dumps({
            "agent": agent_name,
            "platform": "0pnMatrx",
            "verified": False,
            "reason": ("Per-agent on-chain attestation verification is not available yet; "
                       "this agent's identity cannot be confirmed. (Platform-wallet "
                       "activity is shown for context only and does NOT verify any agent.)"),
            "platform_wallet": self.platform_wallet,
            "wallet_tx_count": tx_count,
            "wallet_has_balance": balance_wei > 0,
            "capabilities": self._get_capabilities(agent_name),
            "network": self.network,
        }, indent=2)

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
            "platform": "0pnMatrx",
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
