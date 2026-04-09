"""
Morpheus Trigger System — determines when Morpheus should appear.
"""

import logging
import time
from typing import Any

logger = logging.getLogger(__name__)

# Categories that Morpheus tracks
CAPABILITY_CATEGORIES = (
    "smart_contract",
    "defi",
    "nft",
    "dao",
    "staking",
    "insurance",
    "securities",
    "identity",
    "governance",
    "marketplace",
)

# Trigger types
TRIGGER_TYPES = (
    "first_capability",
    "irreversible_action",
    "significant_event",
    "on_demand",
)

# Actions classified as irreversible
_IRREVERSIBLE_ACTIONS: set[str] = {
    "deploy_contract", "burn_nft", "transfer_ownership", "self_destruct",
    "upgrade_proxy", "set_implementation", "renounce_ownership",
    "burn_tokens", "delete_account",
}

# Action-type to category mapping
_ACTION_CATEGORY_MAP: dict[str, str] = {
    "deploy_contract": "smart_contract",
    "upgrade_proxy": "smart_contract",
    "self_destruct": "smart_contract",
    "set_implementation": "smart_contract",
    "swap": "defi",
    "borrow": "defi",
    "repay": "defi",
    "add_liquidity": "defi",
    "remove_liquidity": "defi",
    "flash_loan": "defi",
    "mint_nft": "nft",
    "burn_nft": "nft",
    "transfer_nft": "nft",
    "list_nft": "marketplace",
    "buy_nft": "marketplace",
    "create_proposal": "dao",
    "vote": "governance",
    "delegate_votes": "governance",
    "stake": "staking",
    "unstake": "staking",
    "claim_rewards": "staking",
    "buy_insurance": "insurance",
    "file_claim": "insurance",
    "issue_security": "securities",
    "transfer_security": "securities",
    "create_identity": "identity",
    "verify_identity": "identity",
    "security_audit": "smart_contract",
    "transfer_ownership": "smart_contract",
    "renounce_ownership": "smart_contract",
}


class MorpheusTriggerSystem:
    """Decides when Morpheus should intervene and generates his
    contextual messages for the user."""

    def __init__(self, config: dict[str, Any]) -> None:
        self.config = config
        # Track which categories the user has already encountered Morpheus for
        self._seen_categories: set[str] = set(
            config.get("seen_categories", [])
        )
        self._intervention_log: list[dict[str, Any]] = []
        self._enabled = config.get("morpheus_enabled", True)
        logger.info(
            "MorpheusTriggerSystem initialised (seen %d categories)",
            len(self._seen_categories),
        )

    # ── Public API ────────────────────────────────────────────────────

    async def should_intervene(
        self, action: dict[str, Any], user_context: dict[str, Any]
    ) -> dict[str, Any]:
        """Determine whether Morpheus should appear.

        Returns:
            should_intervene: bool
            trigger_type: str | None
            message: str (empty if no intervention)
            category: str | None
        """
        if not self._enabled:
            return self._no_intervention()

        action_type = str(action.get("action_type", action.get("type", ""))).lower()
        category = self._resolve_category(action_type, action)

        # 1. On-demand (user explicitly asked for Morpheus)
        if action.get("request_morpheus") or user_context.get("request_morpheus"):
            return await self._trigger(
                "on_demand", action, user_context, category
            )

        # 2. First time using a capability category
        if category and category not in self._seen_categories:
            return await self._trigger(
                "first_capability", action, user_context, category
            )

        # 3. Irreversible action
        if action_type in _IRREVERSIBLE_ACTIONS:
            return await self._trigger(
                "irreversible_action", action, user_context, category
            )

        # 4. Significant event (value-based)
        if self._is_significant(action, user_context):
            return await self._trigger(
                "significant_event", action, user_context, category
            )

        return self._no_intervention()

    async def generate_intervention(
        self, trigger_type: str, action_details: dict[str, Any]
    ) -> str:
        """Create Morpheus's intervention message based on *trigger_type*."""
        generators = {
            "first_capability": self._gen_first_capability,
            "irreversible_action": self._gen_irreversible,
            "significant_event": self._gen_significant,
            "on_demand": self._gen_on_demand,
        }
        generator = generators.get(trigger_type, self._gen_fallback)
        message = generator(action_details)
        return message

    # ── Configuration ─────────────────────────────────────────────────

    def mark_category_seen(self, category: str) -> None:
        """Record that the user has encountered Morpheus for *category*."""
        self._seen_categories.add(category)

    def get_seen_categories(self) -> set[str]:
        return set(self._seen_categories)

    def get_unseen_categories(self) -> set[str]:
        return set(CAPABILITY_CATEGORIES) - self._seen_categories

    # ── Private ───────────────────────────────────────────────────────

    async def _trigger(
        self,
        trigger_type: str,
        action: dict[str, Any],
        user_context: dict[str, Any],
        category: str | None,
    ) -> dict[str, Any]:
        message = await self.generate_intervention(trigger_type, {
            "action": action,
            "user_context": user_context,
            "category": category,
        })

        # Mark category as seen for first_capability triggers
        if trigger_type == "first_capability" and category:
            self.mark_category_seen(category)

        entry = {
            "trigger_type": trigger_type,
            "category": category,
            "timestamp": time.time(),
            "action_type": action.get("action_type", action.get("type")),
        }
        self._intervention_log.append(entry)

        logger.info(
            "Morpheus intervention: type=%s category=%s", trigger_type, category
        )
        return {
            "should_intervene": True,
            "trigger_type": trigger_type,
            "message": message,
            "category": category,
        }

    @staticmethod
    def _no_intervention() -> dict[str, Any]:
        return {
            "should_intervene": False,
            "trigger_type": None,
            "message": "",
            "category": None,
        }

    def _resolve_category(
        self, action_type: str, action: dict[str, Any]
    ) -> str | None:
        """Map an action to its capability category."""
        # Explicit category override
        explicit = action.get("category")
        if explicit and explicit in CAPABILITY_CATEGORIES:
            return explicit
        return _ACTION_CATEGORY_MAP.get(action_type)

    def _is_significant(
        self, action: dict[str, Any], user_context: dict[str, Any]
    ) -> bool:
        """Determine if an action is significant enough for Morpheus."""
        value = action.get("parameters", {}).get("value", 0)
        if not isinstance(value, (int, float)):
            return False

        threshold = self.config.get("significant_value_threshold", 5000)
        if value >= threshold:
            return True

        # First transaction ever
        tx_count = user_context.get("total_transactions", None)
        if tx_count is not None and tx_count == 0:
            return True

        # Milestone transaction counts
        milestones = self.config.get("milestone_tx_counts", [1, 10, 100, 1000])
        if tx_count in milestones:
            return True

        return False

    # ── Message generators ────────────────────────────────────────────

    @staticmethod
    def _gen_first_capability(details: dict[str, Any]) -> str:
        category = details.get("category", "unknown")
        action = details.get("action", {})
        action_type = action.get("action_type", action.get("type", "this action"))

        category_intros: dict[str, str] = {
            "smart_contract": (
                "You are about to interact with a smart contract for the first time. "
                "Smart contracts are self-executing programs on the blockchain. Once deployed "
                "or called, their effects are permanent and governed by code, not people."
            ),
            "defi": (
                "You are entering the world of decentralised finance. "
                "DeFi protocols operate without intermediaries — your assets are managed by "
                "smart contracts. Understand the risks: impermanent loss, liquidation, and "
                "smart contract vulnerabilities are real."
            ),
            "nft": (
                "You are about to interact with non-fungible tokens. "
                "NFTs represent unique digital ownership. Once minted or transferred, "
                "the action is recorded permanently on-chain."
            ),
            "dao": (
                "You are about to participate in a decentralised autonomous organisation. "
                "DAOs are collectively governed entities. Your votes and proposals carry real weight."
            ),
            "staking": (
                "You are about to stake tokens. Staking locks your tokens to support "
                "network security in exchange for rewards. Unstaking typically involves a "
                "cooldown period during which your tokens cannot be moved."
            ),
            "insurance": (
                "You are about to use on-chain insurance. These protocols provide coverage "
                "against specific events like smart contract failures or price crashes."
            ),
            "securities": (
                "You are about to interact with tokenised securities. These carry legal "
                "and regulatory implications. Ensure you understand the compliance requirements."
            ),
            "identity": (
                "You are about to create or manage an on-chain identity. "
                "This identity may be linked to your real-world credentials and is difficult to undo."
            ),
            "governance": (
                "You are about to participate in on-chain governance. "
                "Your vote is immutable once cast and directly influences protocol direction."
            ),
            "marketplace": (
                "You are about to use a decentralised marketplace. "
                "Listings, purchases, and sales are executed via smart contracts."
            ),
        }

        intro = category_intros.get(
            category,
            f"You are about to use a new capability: {category}. Take a moment to understand what this involves.",
        )
        return f"[Morpheus] {intro}"

    @staticmethod
    def _gen_irreversible(details: dict[str, Any]) -> str:
        action = details.get("action", {})
        action_type = action.get("action_type", action.get("type", "this action"))

        irreversible_notes: dict[str, str] = {
            "deploy_contract": "Once deployed, this contract will exist on-chain permanently. It cannot be deleted (only disabled if designed to be).",
            "burn_nft": "Burning this NFT will destroy it permanently. It cannot be recovered.",
            "transfer_ownership": "Transferring ownership is permanent. You will lose control of this contract.",
            "self_destruct": "Self-destructing this contract will remove its code from the blockchain permanently.",
            "renounce_ownership": "Renouncing ownership means no one will ever be able to administer this contract again.",
            "burn_tokens": "Burning tokens permanently removes them from circulation. They cannot be recovered.",
            "delete_account": "Deleting this account is permanent and all associated data will be lost.",
        }

        note = irreversible_notes.get(
            action_type,
            f"The action '{action_type}' cannot be undone once executed.",
        )
        return f"[Morpheus] This is an irreversible action. {note} Proceed only if you are certain."

    @staticmethod
    def _gen_significant(details: dict[str, Any]) -> str:
        action = details.get("action", {})
        user_context = details.get("user_context", {})
        value = action.get("parameters", {}).get("value", 0)
        tx_count = user_context.get("total_transactions")

        if tx_count is not None and tx_count == 0:
            return (
                "[Morpheus] This is your first transaction. Welcome. "
                "Take a moment to verify every detail — the address, the amount, the network. "
                "Once confirmed, there is no undo."
            )

        if isinstance(value, (int, float)) and value > 0:
            return (
                f"[Morpheus] This transaction involves ${value:,.2f}. "
                f"This is a significant amount. Verify the recipient, network, and parameters carefully."
            )

        return "[Morpheus] This is a significant moment. Review all details before proceeding."

    @staticmethod
    def _gen_on_demand(details: dict[str, Any]) -> str:
        return (
            "[Morpheus] You called, and I am here. "
            "Tell me what you need guidance on, and I will provide the context you need."
        )

    @staticmethod
    def _gen_fallback(details: dict[str, Any]) -> str:
        return "[Morpheus] Pause and consider before proceeding."
