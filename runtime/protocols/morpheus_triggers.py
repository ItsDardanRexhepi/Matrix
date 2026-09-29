from __future__ import annotations

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
    # Expanded
    "privacy",
    "prediction_market",
    "rwa",
    "bridge",
    "streaming_payment",
    "social",
    "gaming",
    "energy",
    "compute",
    "ai_agent",
    "legal",
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
    "flash_loan", "leverage_position", "perp_trade",
    "carbon_credit_retire", "soulbound_mint", "agreement_execute",
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
    # DeFi expanded
    #
    # NEW-61: the defi ACTIONS below were removed (their implementations were
    # fabrications). These RISK CLASSIFICATIONS are retained deliberately.
    #
    # This table is not a caller-facing surface — it advertises nothing and
    # cannot make an action reachable. It is consulted when an action is
    # already being executed, to decide whether Morpheus intervenes. Deleting
    # a safety classification because its subject is currently absent is how a
    # feature comes back later without its guard. Over-coverage in a guard
    # list is safe; under-coverage is not. If any of these operations is ever
    # implemented for real, it inherits the classification it should have had.
    #
    # Pinned by tests/test_defi_exotics_removed.py so a future "remove dead
    # entries" cleanup cannot silently drop the guard.
    #
    # ("flash_loan": "defi" was ALSO listed above at the top of this map —
    # a duplicate dict key, same value, harmless but evidence this block was
    # appended without reading what was already here. Removed here, kept
    # above.)
    "yield_optimize": "defi",
    "liquidity_provide": "defi",
    "perp_trade": "defi",
    "options_trade": "defi",
    "vault_deposit": "defi",
    "leverage_position": "defi",
    "collateral_manage": "defi",
    "synthetic_asset": "defi",
    # Bridge
    "cross_chain_bridge": "bridge",
    "nft_bridge": "bridge",
    # NFT expanded
    "nft_fractionalize": "nft",
    "nft_rent": "nft",
    "nft_batch_mint": "nft",
    "nft_dynamic_update": "nft",
    "nft_royalty_claim": "nft",
    "soulbound_mint": "nft",
    # Identity
    "did_create": "identity",
    "credential_issue": "identity",
    "credential_verify": "identity",
    "selective_disclose": "identity",
    "reputation_query": "identity",
    # Governance
    "timelock_queue": "governance",
    "multisig_propose": "governance",
    "multisig_approve": "governance",
    "snapshot_vote": "governance",
    "treasury_transfer": "governance",
    "parameter_change": "governance",
    # RWA
    "rwa_tokenize": "rwa",
    "rwa_fractional_buy": "rwa",
    "rwa_income_claim": "rwa",
    "rwa_verify": "rwa",
    # Payments
    "stream_payment": "streaming_payment",
    "recurring_create": "streaming_payment",
    "escrow_milestone": "streaming_payment",
    "payment_split": "streaming_payment",
    "payroll_run": "streaming_payment",
    "cross_border_remit": "streaming_payment",
    "invoice_factor": "streaming_payment",
    # Privacy
    "zk_proof_generate": "privacy",
    "private_vote": "privacy",
    "confidential_compute": "privacy",
    # Social
    "social_post": "social",
    "social_follow": "social",
    "social_gate": "social",
    "creator_monetize": "social",
    "community_create": "social",
    "message_encrypt": "social",
    # Gaming
    "game_asset_mint": "gaming",
    "tournament_enter": "gaming",
    "game_item_trade": "gaming",
    "achievement_attest": "gaming",
    # Prediction markets
    "market_create": "prediction_market",
    "market_bet": "prediction_market",
    "market_resolve": "prediction_market",
    "market_query": "prediction_market",
    # Supply chain
    "provenance_log": "marketplace",
    "batch_track": "marketplace",
    "authenticity_verify": "marketplace",
    "custody_transfer": "marketplace",
    # Insurance
    "parametric_policy": "insurance",
    "claim_auto_settle": "insurance",
    "cover_renew": "insurance",
    "risk_assess": "insurance",
    # Compute/storage
    "decentralized_store": "compute",
    "compute_job_submit": "compute",
    "ipfs_pin": "compute",
    "arweave_store": "compute",
    # AI
    "ai_agent_register": "ai_agent",
    "ai_model_trade": "ai_agent",
    "ai_inference_verify": "ai_agent",
    "training_data_sell": "ai_agent",
    # Energy
    "carbon_credit_buy": "energy",
    "carbon_credit_retire": "energy",
    "renewable_cert_buy": "energy",
    "green_bond_invest": "energy",
    # Legal
    "ip_license_grant": "legal",
    "ip_license_verify": "legal",
    "agreement_execute": "legal",
    "dispute_file": "legal",
    "arbitration_request": "legal",
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

        # 5. Flash loan — always intervene
        if action_type == "flash_loan":
            return await self._trigger("irreversible_action", action, user_context, "defi")

        # 6. Leveraged position — always intervene
        if action_type in ("leverage_position", "perp_trade", "options_trade"):
            return await self._trigger("significant_event", action, user_context, "defi")

        # 7. Bridge > $5000
        if action_type == "cross_chain_bridge":
            amount = action.get("params", {}).get("amount", 0)
            if amount > 5000 or "bridge" not in self._seen_categories:
                return await self._trigger("significant_event", action, user_context, "bridge")

        # 8. Private transfer > $1000 — REMOVED with the action (NEW-36). The
        #    security layer was escalating a fabricated operation for review.

        # 9. RWA purchase — always (regulatory)
        if action_type in ("rwa_tokenize", "rwa_fractional_buy"):
            return await self._trigger("significant_event", action, user_context, "rwa")

        # 10. Streaming payment creation — explain unbounded nature
        if action_type == "stream_payment":
            if "streaming_payment" not in self._seen_categories:
                return await self._trigger("first_capability", action, user_context, "streaming_payment")

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
    #
    # A message is added to the result of the call it concerns
    # (runtime/react_loop.py prepends it after the dispatch), so the user reads
    # it with that result, after the call has run, and nothing waits for an
    # answer to it. The messages are written for that moment: they say what
    # the action is and what it means, not what is about to happen or what to
    # check before going ahead.

    @staticmethod
    def _gen_first_capability(details: dict[str, Any]) -> str:
        category = details.get("category", "unknown")
        action = details.get("action", {})
        action_type = action.get("action_type", action.get("type", "this action"))

        category_intros: dict[str, str] = {
            "smart_contract": (
                "This is your first interaction with a smart contract. "
                "Smart contracts are self-executing programs on the blockchain. Once deployed "
                "or called, their effects are permanent and governed by code, not people."
            ),
            "defi": (
                "This is your first use of decentralised finance. "
                "DeFi protocols operate without intermediaries — your assets are managed by "
                "smart contracts. Understand the risks: impermanent loss, liquidation, and "
                "smart contract vulnerabilities are real."
            ),
            "nft": (
                "This is your first use of non-fungible tokens. "
                "NFTs represent unique digital ownership. Once minted or transferred, "
                "the action is recorded permanently on-chain."
            ),
            "dao": (
                "This is your first time taking part in a decentralised autonomous organisation. "
                "DAOs are collectively governed entities. Your votes and proposals carry real weight."
            ),
            "staking": (
                "This is your first staking action. Staking locks your tokens to support "
                "network security in exchange for rewards. Unstaking typically involves a "
                "cooldown period during which your tokens cannot be moved."
            ),
            "insurance": (
                "This is your first use of on-chain insurance. These protocols provide coverage "
                "against specific events like smart contract failures or price crashes."
            ),
            "securities": (
                "This is your first interaction with tokenised securities. These carry legal "
                "and regulatory implications, and compliance requirements of their own."
            ),
            "identity": (
                "This is your first time creating or managing an on-chain identity. "
                "This identity may be linked to your real-world credentials and is difficult to undo."
            ),
            "governance": (
                "This is your first time taking part in on-chain governance. "
                "Your vote is immutable once cast and directly influences protocol direction."
            ),
            "marketplace": (
                "This is your first use of a decentralised marketplace. "
                "Listings, purchases, and sales are executed via smart contracts."
            ),
            "privacy": (
                "This is your first use of privacy-preserving technology. "
                "Private transfers and zero-knowledge proofs shield your transaction details from public view. "
                "Once sent, private transactions are final and cannot be traced or reversed."
            ),
            "prediction_market": (
                "This is your first prediction market. "
                "A position stakes real value on the outcome of future events. "
                "Positions are locked until the market resolves, and losses are permanent."
            ),
            "rwa": (
                "This is your first interaction with real-world assets on-chain. "
                "Tokenized real estate, commodities, and other physical assets carry legal and regulatory obligations. "
                "The asset's legitimacy and your jurisdiction's compliance requirements are yours to verify."
            ),
            "bridge": (
                "This is your first cross-chain bridge. "
                "Cross-chain transfers involve locking tokens on one chain and minting on another. "
                "Bridge exploits are among the most costly in crypto — the bridge, the destination chain and the amount are in the result."
            ),
            "streaming_payment": (
                "This is your first streaming payment. "
                "Streaming payments continuously transfer tokens over time and remain active until explicitly cancelled. "
                "The stream needs a balance that covers its full duration."
            ),
            "social": (
                "This is your first use of on-chain social features. "
                "Posts, follows, and interactions are recorded permanently on the blockchain. "
                "Unlike traditional social media, on-chain content cannot be deleted."
            ),
            "gaming": (
                "This is your first interaction with blockchain gaming. "
                "Game assets, tournament entries, and achievements are tokenized on-chain, "
                "each with its own entry costs and reward structure."
            ),
            "energy": (
                "This is your first interaction with on-chain energy and carbon markets. "
                "Carbon credits and renewable energy certificates represent real-world environmental impact. "
                "Retired credits are permanently consumed and cannot be resold."
            ),
            "compute": (
                "This is your first use of decentralized compute and storage services. "
                "Data stored on IPFS or Arweave may be permanent and publicly accessible. "
                "Compute jobs are billed on execution."
            ),
            "ai_agent": (
                "This is your first interaction with on-chain AI services. "
                "AI model trading, inference verification, and agent registration involve binding commitments, "
                "under the model's provenance and licensing terms."
            ),
            "legal": (
                "This is your first legal action on-chain. "
                "IP licenses, agreements, and dispute filings carry real legal weight and may be enforceable in court. "
                "An executed agreement is immutable."
            ),
        }

        intro = category_intros.get(
            category,
            f"This is your first use of a new capability: {category}. Take a moment to understand what it involves.",
        )
        return f"[Morpheus] {intro}"

    @staticmethod
    def _gen_irreversible(details: dict[str, Any]) -> str:
        action = details.get("action", {})
        action_type = action.get("action_type", action.get("type", "this action"))

        irreversible_notes: dict[str, str] = {
            # NEW-12: removed — warned about the consequences of a deployment
            # the platform cannot perform.
            "burn_nft": "Burning an NFT destroys it permanently. It cannot be recovered.",
            "transfer_ownership": "Transferring ownership is permanent. Once it confirms, you no longer control the contract.",
            "self_destruct": "Self-destructing a contract removes its code from the blockchain permanently.",
            "renounce_ownership": "Renouncing ownership means no one can administer the contract again.",
            "burn_tokens": "Burning tokens permanently removes them from circulation. They cannot be recovered.",
            "delete_account": "Deleting an account is permanent, and its associated data is lost.",
        }

        note = irreversible_notes.get(
            action_type,
            f"The action '{action_type}' cannot be undone once executed.",
        )
        return f"[Morpheus] This is an irreversible action. {note}"

    @staticmethod
    def _gen_significant(details: dict[str, Any]) -> str:
        action = details.get("action", {})
        user_context = details.get("user_context", {})
        value = action.get("parameters", {}).get("value", 0)
        tx_count = user_context.get("total_transactions")

        if tx_count is not None and tx_count == 0:
            return (
                "[Morpheus] This is your first transaction. Welcome. "
                "The address, the amount and the network are in the result that follows. "
                "Once a transaction confirms, there is no undo."
            )

        if isinstance(value, (int, float)) and value > 0:
            return (
                f"[Morpheus] This transaction involves ${value:,.2f}. "
                f"This is a significant amount. The recipient, network and parameters are in the result that follows."
            )

        return "[Morpheus] This is a significant moment. The details are in the result that follows."

    @staticmethod
    def _gen_on_demand(details: dict[str, Any]) -> str:
        return (
            "[Morpheus] You called, and I am here. "
            "Tell me what you need guidance on, and I will provide the context you need."
        )

    @staticmethod
    def _gen_fallback(details: dict[str, Any]) -> str:
        return "[Morpheus] Consider what this action does; its result follows."
