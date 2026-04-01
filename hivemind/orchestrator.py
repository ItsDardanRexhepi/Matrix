"""
Hivemind Orchestrator — coordinates the three agents of 0pnMatrx.

Trinity handles conversation. Neo handles execution. Morpheus handles guidance.
The orchestrator routes messages to the right agent at the right time,
manages agent handoffs, and enforces the Unified Rexhepi Framework.
"""

import logging
from dataclasses import dataclass
from enum import Enum

from runtime.react_loop import ReActLoop, ReActContext, Message

logger = logging.getLogger(__name__)


class AgentRole(Enum):
    CONVERSATION = "conversation"
    EXECUTION = "execution"
    GUIDANCE = "guidance"


@dataclass
class AgentState:
    name: str
    role: AgentRole
    enabled: bool
    system_prompt: str = ""


class HivemindOrchestrator:
    """
    Routes messages between Trinity, Neo, and Morpheus.

    The orchestrator determines which agent should handle each interaction:
    - Trinity handles all user-facing conversation
    - Neo executes all blockchain and tool operations (never user-facing)
    - Morpheus intervenes at pivotal moments defined by trigger conditions

    Morpheus trigger detection runs before every Trinity response. If a
    Morpheus trigger condition is met, Morpheus responds instead of Trinity,
    then control returns to Trinity.
    """

    def __init__(self, config: dict, react_loop: ReActLoop):
        self.config = config
        self.react_loop = react_loop
        self.agents: dict[str, AgentState] = {}
        self._user_firsts: dict[str, set[str]] = {}
        self._init_agents()

    def _init_agents(self):
        agents_config = self.config.get("agents", {})

        agent_defs = {
            "trinity": AgentRole.CONVERSATION,
            "neo": AgentRole.EXECUTION,
            "morpheus": AgentRole.GUIDANCE,
        }

        for name, role in agent_defs.items():
            cfg = agents_config.get(name, {})
            self.agents[name] = AgentState(
                name=name,
                role=role,
                enabled=cfg.get("enabled", True),
            )

    async def handle_message(
        self,
        user_message: str,
        session_id: str,
        conversation: list[Message],
    ) -> dict:
        """
        Process a user message through the hivemind.

        Returns a dict with:
            - response: the text to show the user
            - agent: which agent produced the response
            - morpheus_triggered: whether Morpheus intervened
        """
        morpheus_response = await self._check_morpheus_triggers(
            user_message, session_id, conversation
        )

        if morpheus_response:
            return {
                "response": morpheus_response,
                "agent": "morpheus",
                "morpheus_triggered": True,
            }

        context = ReActContext(
            agent_name="trinity",
            conversation=conversation + [Message(role="user", content=user_message)],
            system_prompt=self.agents["trinity"].system_prompt,
        )

        response = await self.react_loop.run(context)

        return {
            "response": response,
            "agent": "trinity",
            "morpheus_triggered": False,
        }

    async def execute_operation(self, operation: str, params: dict) -> dict:
        """
        Route an operation to Neo for execution.
        Never called directly by users — only by the system.
        """
        context = ReActContext(
            agent_name="neo",
            conversation=[Message(role="user", content=f"Execute: {operation}\nParams: {params}")],
            system_prompt=self.agents["neo"].system_prompt,
            tools_enabled=True,
        )

        result = await self.react_loop.run(context)
        return {"result": result, "operation": operation}

    async def _check_morpheus_triggers(
        self,
        user_message: str,
        session_id: str,
        conversation: list[Message],
    ) -> str | None:
        """
        Check if any Morpheus trigger conditions are met.

        Triggers:
        1. First significant capability use (smart contract, DeFi, NFT, DAO)
        2. Before any irreversible action
        3. When something significant happens
        4. On-demand knowledge request
        """
        if not self.agents.get("morpheus", AgentState("morpheus", AgentRole.GUIDANCE, False)).enabled:
            return None

        if self._is_on_demand_morpheus(user_message):
            return await self._invoke_morpheus(user_message, conversation)

        first_category = self._detect_first_use(user_message, session_id)
        if first_category:
            prompt = (
                f"The user is about to use {first_category} for the first time. "
                f"Explain what they are about to do before they do it. "
                f"Their message: {user_message}"
            )
            return await self._invoke_morpheus(prompt, conversation)

        if self._detect_irreversible(user_message):
            prompt = (
                f"The user is about to take an irreversible action. "
                f"State clearly what is about to happen and that it is permanent. "
                f"Their message: {user_message}"
            )
            return await self._invoke_morpheus(prompt, conversation)

        return None

    def _is_on_demand_morpheus(self, message: str) -> bool:
        triggers = ["explain", "what does this mean", "help me understand", "morpheus"]
        msg_lower = message.lower()
        return any(t in msg_lower for t in triggers)

    def _detect_first_use(self, message: str, session_id: str) -> str | None:
        categories = {
            "smart contracts": ["smart contract", "deploy contract", "solidity"],
            "DeFi": ["defi", "loan", "lending", "borrow", "yield", "liquidity"],
            "NFTs": ["nft", "mint nft", "create nft"],
            "DAOs": ["dao", "governance", "vote", "proposal"],
        }

        if session_id not in self._user_firsts:
            self._user_firsts[session_id] = set()

        msg_lower = message.lower()
        for category, keywords in categories.items():
            if category in self._user_firsts[session_id]:
                continue
            if any(kw in msg_lower for kw in keywords):
                self._user_firsts[session_id].add(category)
                return category

        return None

    def _detect_irreversible(self, message: str) -> bool:
        irreversible_keywords = [
            "deploy", "execute contract", "transfer", "send eth",
            "send token", "burn", "swap", "stake",
        ]
        msg_lower = message.lower()
        return any(kw in msg_lower for kw in irreversible_keywords)

    async def _invoke_morpheus(self, prompt: str, conversation: list[Message]) -> str:
        context = ReActContext(
            agent_name="morpheus",
            conversation=conversation + [Message(role="user", content=prompt)],
            system_prompt=self.agents["morpheus"].system_prompt,
            tools_enabled=False,
        )
        return await self.react_loop.run_without_tools(context)
