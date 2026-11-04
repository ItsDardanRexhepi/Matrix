"""
AgentIdentityService -- ERC-8004 compliant agent identity management.

Registers autonomous agents on-chain with DIDs, manages capabilities,
and integrates reputation tracking and safe update monitoring.
"""

from __future__ import annotations

import hashlib
import logging
import time
import uuid
from typing import Any

from runtime.blockchain.services.agent_identity.reputation import AgentReputation
from runtime.blockchain.web3_manager import recorded_unsettled_response
from runtime.auth.identity import same_caller
from runtime.blockchain.services.agent_identity.update_monitor import UpdateMonitor

logger = logging.getLogger(__name__)

# Valid agent statuses
AGENT_STATUSES = {"active", "suspended", "deregistered", "pending_review"}

# Maximum capabilities per agent
MAX_CAPABILITIES = 50


class AgentIdentityService:
    """
    ERC-8004 compliant agent identity service.

    Manages the lifecycle of autonomous agent identities on-chain,
    including registration, capability management, and deregistration.
    Each agent receives a unique DID (Decentralised Identifier).

    Config keys (under config["agent_identity"]):
        did_method      -- DID method prefix (default "did:the-matrix")
        max_capabilities-- max capabilities per agent
        network         -- blockchain network
    """

    def __init__(self, config: dict[str, Any]) -> None:
        self.config = config
        ai = config.get("agent_identity", {})
        bc = config.get("blockchain", {})

        self.did_method: str = ai.get("did_method", "did:the-matrix")
        self.max_capabilities: int = ai.get("max_capabilities", MAX_CAPABILITIES)
        self.network: str = bc.get("network", "base-sepolia")

        # Sub-components
        self._reputation = AgentReputation(config)
        self._update_monitor = UpdateMonitor(config)

        # In-memory agent registry: agent_id -> agent record
        self._agents: dict[str, dict[str, Any]] = {}
        # owner -> list of agent_ids
        self._owner_agents: dict[str, list[str]] = {}

        logger.info(
            "AgentIdentityService initialised: did_method=%s network=%s",
            self.did_method, self.network,
        )

    @property
    def reputation(self) -> AgentReputation:
        """Access the reputation sub-component."""
        return self._reputation

    @property
    def update_monitor(self) -> UpdateMonitor:
        """Access the update monitor sub-component."""
        return self._update_monitor

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    async def register_agent(
        self,
        owner: str,
        agent_name: str,
        capabilities: list[str],
        metadata: dict[str, Any],
    ) -> dict[str, Any]:
        """
        Register a new agent identity on-chain (ERC-8004).

        Args:
            owner: Owner address (Ethereum address).
            agent_name: Human-readable agent name.
            capabilities: List of capability strings the agent can perform.
            metadata: Additional metadata (description, version, etc.).

        Returns:
            Dict with agent_id, DID, registration details.
        """
        if not owner:
            return {"status": "error", "error": "Owner address is required"}

        if not agent_name or not agent_name.strip():
            return {"status": "error", "error": "Agent name is required"}

        if len(capabilities) > self.max_capabilities:
            return {
                "status": "error",
                "error": f"Too many capabilities: {len(capabilities)} > {self.max_capabilities}",
            }

        # Check for duplicate agent names under same owner
        existing_ids = self._owner_agents.get(owner, [])
        for aid in existing_ids:
            if self._agents.get(aid, {}).get("agent_name") == agent_name:
                return {
                    "status": "error",
                    "error": f"Agent with name '{agent_name}' already registered by this owner",
                }

        # Generate agent ID and DID
        agent_id = self._generate_agent_id(owner, agent_name)
        did = f"{self.did_method}:{agent_id}"

        timestamp = int(time.time())

        agent_record: dict[str, Any] = {
            "agent_id": agent_id,
            "did": did,
            "owner": owner,
            "agent_name": agent_name,
            "capabilities": list(capabilities),
            "metadata": dict(metadata),
            "status": "active",
            "registered_at": timestamp,
            "updated_at": timestamp,
            "version": 1,
            "erc_standard": "ERC-8004",
            "network": self.network,
            "on_chain_hash": self._compute_identity_hash(agent_id, owner, capabilities),
        }

        self._agents[agent_id] = agent_record
        self._owner_agents.setdefault(owner, []).append(agent_id)

        # Initialise reputation
        await self._reputation.initialise(agent_id)

        logger.info(
            "Agent registered: id=%s did=%s owner=%s name=%s capabilities=%d",
            agent_id, did, owner, agent_name, len(capabilities),
        )

        return {
            **agent_record,
            "status": "registered",
        }

    async def get_agent(self, agent_id: str) -> dict[str, Any]:
        """
        Retrieve an agent identity by ID.

        Args:
            agent_id: The unique agent identifier.

        Returns:
            Dict with full agent record, or error if not found.
        """
        agent = self._agents.get(agent_id)
        if agent is None:
            return {"status": "error", "error": f"Agent not found: {agent_id}"}

        # Include current reputation
        rep = await self._reputation.get_reputation(agent_id)

        return {
            **agent,
            "status": "found",
            "reputation": rep,
        }

    @staticmethod
    def _not_the_owner(agent: dict[str, Any], caller_identity: str,
                       caller_source: str | None) -> dict[str, Any] | None:
        """The refusal a call made for someone other than the agent's owner
        gets, or None. A dispatched call carries ``caller_source`` and is held
        to the identity the entry point bound for it (``""`` when it bound
        none, which is refused, never read as the owner); a call with no caller
        behind it (``caller_source`` None: the platform's own code) is not."""
        if caller_source is None or same_caller(caller_identity, agent.get("owner")):
            return None
        return {"status": "error", "error_category": "forbidden",
                "error": "Only the agent's owner may change or deregister it"}

    async def update_agent(
        self, agent_id: str, updates: dict[str, Any],
        caller_identity: str = "", caller_source: str | None = None,
    ) -> dict[str, Any]:
        """
        Update an agent's metadata, capabilities, or name.

        Does not allow changing owner or agent_id. For capability changes,
        routes through the UpdateMonitor for safety validation. A dispatched
        call is held to the agent's owner (``_not_the_owner``).

        Args:
            agent_id: The agent identifier.
            updates: Dict of fields to update.

        Returns:
            Dict with updated agent record.
        """
        agent = self._agents.get(agent_id)
        if agent is None:
            return {"status": "error", "error": f"Agent not found: {agent_id}"}
        refused = self._not_the_owner(agent, caller_identity, caller_source)
        if refused is not None:
            return refused

        if agent["status"] == "deregistered":
            return {"status": "error", "error": "Cannot update a deregistered agent"}

        # Disallow changing immutable fields
        immutable = {"agent_id", "did", "owner", "registered_at", "erc_standard", "network"}
        blocked = set(updates.keys()) & immutable
        if blocked:
            return {
                "status": "error",
                "error": f"Cannot update immutable fields: {sorted(blocked)}",
            }

        # If capabilities are being updated, validate through update monitor
        if "capabilities" in updates:
            new_caps = updates["capabilities"]
            if len(new_caps) > self.max_capabilities:
                return {
                    "status": "error",
                    "error": f"Too many capabilities: {len(new_caps)} > {self.max_capabilities}",
                }

            # Create safety proposal for capability changes
            proposal = await self._update_monitor.propose_update(
                agent_id,
                {
                    "type": "capability_change",
                    "old_capabilities": agent["capabilities"],
                    "new_capabilities": new_caps,
                },
            )

            validation = await self._update_monitor.validate_update(
                proposal["proposal_id"]
            )

            if not validation.get("safe", False):
                return {
                    "status": "error",
                    "error": "Capability update failed safety validation",
                    "validation": validation,
                }

        # Apply updates
        for key, value in updates.items():
            if key not in immutable:
                agent[key] = value

        agent["updated_at"] = int(time.time())
        agent["version"] += 1
        agent["on_chain_hash"] = self._compute_identity_hash(
            agent_id, agent["owner"], agent.get("capabilities", [])
        )

        logger.info(
            "Agent updated: id=%s version=%d fields=%s",
            agent_id, agent["version"], sorted(updates.keys()),
        )

        return {
            **agent,
            "status": "updated",
        }

    async def deregister_agent(
        self, agent_id: str, caller_identity: str = "", caller_source: str | None = None,
    ) -> dict[str, Any]:
        """
        Deregister an agent, marking it inactive on-chain. A dispatched call
        is held to the agent's owner (``_not_the_owner``).

        Args:
            agent_id: The agent identifier.

        Returns:
            Dict with deregistration confirmation.
        """
        agent = self._agents.get(agent_id)
        if agent is None:
            return {"status": "error", "error": f"Agent not found: {agent_id}"}
        refused = self._not_the_owner(agent, caller_identity, caller_source)
        if refused is not None:
            return refused

        if agent["status"] == "deregistered":
            return {"status": "error", "error": "Agent is already deregistered"}

        agent["status"] = "deregistered"
        agent["deregistered_at"] = int(time.time())
        agent["updated_at"] = agent["deregistered_at"]

        logger.info("Agent deregistered: id=%s did=%s", agent_id, agent["did"])

        return {
            "status": "deregistered",
            "agent_id": agent_id,
            "did": agent["did"],
            "owner": agent["owner"],
            "deregistered_at": agent["deregistered_at"],
        }

    async def list_agents(
        self, owner: str | None = None, status: str | None = None
    ) -> list[dict[str, Any]]:
        """List agents, optionally filtered by owner or status."""
        agents = list(self._agents.values())

        if owner is not None:
            agent_ids = self._owner_agents.get(owner, [])
            agents = [a for a in agents if a["agent_id"] in agent_ids]

        if status is not None:
            agents = [a for a in agents if a["status"] == status]

        return agents

    # ------------------------------------------------------------------
    # Internals
    # ------------------------------------------------------------------

    @staticmethod
    def _generate_agent_id(owner: str, agent_name: str) -> str:
        raw = f"{owner}:{agent_name}:{uuid.uuid4().hex}:{time.time()}"
        return "agent_" + hashlib.sha256(raw.encode()).hexdigest()[:24]

    @staticmethod
    def _compute_identity_hash(
        agent_id: str, owner: str, capabilities: list[str]
    ) -> str:
        payload = f"{agent_id}|{owner}|{','.join(sorted(capabilities))}"
        return "0x" + hashlib.sha256(payload.encode()).hexdigest()

    # ------------------------------------------------------------------
    # Expanded AI agent operations
    # ------------------------------------------------------------------

    async def trade_model_access(
        self, seller: str, buyer: str, model_id: str, price: float, license_type: str = "inference",
    ) -> dict[str, Any]:
        """Record a trade of access to an AI model. NOTHING IS PAID OR GRANTED.

        It returned `status: "traded"` over a caller-supplied price with no
        payment taken and no access granted, and the dispatcher attested it as
        settled — the same shape as `GamingService.trade_item`, and the same
        record now.
        """
        trade_id = f"mta_{uuid.uuid4().hex[:16]}"
        now = int(time.time())
        record: dict[str, Any] = recorded_unsettled_response(
            "agent_identity", "trade_model_access", {
                "id": trade_id,
                "seller": seller,
                "buyer": buyer,
                "model_id": model_id,
                "price": price,
                "license_type": license_type,
                "recorded_at": now,
            },
            value_moved=False,
            disclosure=(
                "The trade is recorded on The Matrix and did NOT settle: no "
                "payment was taken from the buyer and no model access was "
                "granted."
            ),
        )
        self._agents[f"_trade_{trade_id}"] = record
        logger.info("Model access trade recorded (unsettled): id=%s", trade_id)
        return record

    async def verify_inference(
        self, agent_id: str, input_hash: str, output_hash: str, model_id: str = "",
    ) -> dict[str, Any]:
        """Verify an AI inference result on-chain."""
        verify_id = f"ivf_{uuid.uuid4().hex[:16]}"
        now = int(time.time())
        record: dict[str, Any] = {
            "id": verify_id,
            "status": "verified",
            "agent_id": agent_id,
            "input_hash": input_hash,
            "output_hash": output_hash,
            "model_id": model_id,
            "valid": True,
            "verified_at": now,
        }
        logger.info("Inference verified: id=%s", verify_id)
        return record

    async def sell_training_data(
        self, seller: str, buyer: str, dataset_id: str, price: float, sample_count: int = 0,
    ) -> dict[str, Any]:
        """Record a sale of access to training data. NOTHING IS PAID OR DELIVERED.

        It returned `status: "sold"` over a caller-supplied price with no
        payment taken and no data delivered, and the dispatcher attested it as
        settled. It is recorded, and the record says nothing moved.
        """
        sale_id = f"tds_{uuid.uuid4().hex[:16]}"
        now = int(time.time())
        record: dict[str, Any] = recorded_unsettled_response(
            "agent_identity", "sell_training_data", {
                "id": sale_id,
                "seller": seller,
                "buyer": buyer,
                "dataset_id": dataset_id,
                "price": price,
                "sample_count": sample_count,
                "recorded_at": now,
            },
            value_moved=False,
            disclosure=(
                "The sale is recorded on The Matrix and did NOT settle: no "
                "payment was taken from the buyer and no data was delivered."
            ),
        )
        self._agents[f"_data_{sale_id}"] = record
        logger.info("Training data sale recorded (unsettled): id=%s", sale_id)
        return record
