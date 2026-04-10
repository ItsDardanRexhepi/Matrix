"""
Component Registry — central registry for all platform components and plugins.

Every built-in component and third-party plugin registers itself here with:
    - Feature flags (tier requirements, beta status)
    - Action list
    - Tier-based usage limits
    - Trinity skill keywords

The bridge/packager queries this registry to determine which components
are available for a given user's subscription tier.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass, field
from typing import Any

from plugins.manifest_schema import PluginManifest

logger = logging.getLogger(__name__)


@dataclass
class UsageLimits:
    """Per-tier usage limits for a component."""
    free: dict[str, int | float | None] = field(default_factory=dict)
    pro: dict[str, int | float | None] = field(default_factory=dict)
    enterprise: dict[str, int | float | None] = field(default_factory=dict)

    def get_limits(self, tier: str) -> dict[str, int | float | None]:
        return getattr(self, tier, self.free)


@dataclass
class RegisteredComponent:
    """A component registered in the platform."""
    name: str
    display_name: str
    description: str
    category: str
    actions: list[str]
    requires_tier: str = "free"
    feature_flags: dict[str, bool] = field(default_factory=dict)
    usage_limits: UsageLimits | None = None
    trinity_keywords: list[str] = field(default_factory=list)
    is_plugin: bool = False
    plugin_author: str = ""

    def to_dict(self) -> dict[str, Any]:
        result = {
            "name": self.name,
            "display_name": self.display_name,
            "description": self.description,
            "category": self.category,
            "actions": self.actions,
            "requires_tier": self.requires_tier,
            "feature_flags": self.feature_flags,
            "is_plugin": self.is_plugin,
        }
        if self.usage_limits:
            result["usage_limits"] = {
                "free": self.usage_limits.free,
                "pro": self.usage_limits.pro,
                "enterprise": self.usage_limits.enterprise,
            }
        return result


class ComponentRegistry:
    """Central registry for all platform components and third-party plugins.

    Usage::

        registry = ComponentRegistry()
        # Built-in components are auto-registered on init

        # Register a third-party plugin
        registry.register_plugin(plugin_manifest)

        # Query available components for a user's tier
        available = registry.get_available_components("pro")

        # Check if a specific action is allowed
        allowed = registry.is_action_allowed("mint_nft", "free")
    """

    def __init__(self):
        self._components: dict[str, RegisteredComponent] = {}
        self._register_builtins()

    def _register_builtins(self) -> None:
        """Register all 30 built-in components with their tier limits."""

        builtins = [
            RegisteredComponent(
                name="contract_conversion",
                display_name="Smart Contracts",
                description="Convert and deploy smart contracts across chains",
                category="core_infrastructure",
                actions=["deploy_contract", "convert_contract", "estimate_contract_cost", "list_templates"],
                requires_tier="free",
                usage_limits=UsageLimits(
                    free={"conversions_per_month": 5, "deployments_per_month": 3},
                    pro={"conversions_per_month": 100, "deployments_per_month": 50},
                    enterprise={"conversions_per_month": None, "deployments_per_month": None},
                ),
                trinity_keywords=["convert contract", "deploy contract", "smart contract"],
            ),
            RegisteredComponent(
                name="defi",
                display_name="DeFi Lending",
                description="Decentralized lending and borrowing",
                category="defi",
                actions=["create_loan", "repay_loan", "get_loan"],
                requires_tier="free",
                usage_limits=UsageLimits(
                    free={"monthly_volume_usd": 5000, "active_loans": 3},
                    pro={"monthly_volume_usd": 500000, "active_loans": 50},
                    enterprise={"monthly_volume_usd": None, "active_loans": None},
                ),
                trinity_keywords=["loan", "borrow", "lending", "DeFi"],
            ),
            RegisteredComponent(
                name="nft_services",
                display_name="NFTs",
                description="Mint, trade, and manage NFTs",
                category="nft_digital_assets",
                actions=["mint_nft", "create_nft_collection", "transfer_nft", "list_nft_for_sale",
                         "buy_nft", "estimate_nft_value", "get_nft_rarity", "set_nft_rights",
                         "check_nft_rights", "configure_nft_royalty"],
                requires_tier="free",
                usage_limits=UsageLimits(
                    free={"mints_per_month": 3, "collections_per_month": 1},
                    pro={"mints_per_month": 100, "collections_per_month": 20},
                    enterprise={"mints_per_month": None, "collections_per_month": None},
                ),
                trinity_keywords=["NFT", "mint", "collection", "royalty"],
            ),
            RegisteredComponent(
                name="rwa_tokenization",
                display_name="Real World Assets",
                description="Tokenize real-world assets on-chain",
                category="defi",
                actions=["tokenize_asset", "transfer_rwa_ownership", "get_rwa_asset"],
                requires_tier="free",
                usage_limits=UsageLimits(
                    free={"assets_per_month": 2},
                    pro={"assets_per_month": 25},
                    enterprise={"assets_per_month": None},
                ),
                trinity_keywords=["tokenize", "real world asset", "RWA", "property"],
            ),
            RegisteredComponent(
                name="did_identity",
                display_name="Digital Identity",
                description="Decentralized identity management",
                category="core_infrastructure",
                actions=["create_did", "resolve_did", "update_did", "deactivate_did"],
                requires_tier="free",
                trinity_keywords=["identity", "DID", "decentralized identity"],
            ),
            RegisteredComponent(
                name="dao_management",
                display_name="DAOs",
                description="Create and manage DAOs",
                category="governance_social",
                actions=["create_dao", "get_dao", "join_dao", "leave_dao"],
                requires_tier="free",
                usage_limits=UsageLimits(
                    free={"daos_created": 1},
                    pro={"daos_created": 10},
                    enterprise={"daos_created": None},
                ),
                trinity_keywords=["DAO", "organization", "community"],
            ),
            RegisteredComponent(
                name="stablecoin",
                display_name="Stablecoin",
                description="Stablecoin transfers and management",
                category="defi",
                actions=["transfer_stablecoin", "get_stablecoin_balance", "get_stablecoin_fee"],
                requires_tier="free",
                trinity_keywords=["stablecoin", "USDC", "USDT", "DAI"],
            ),
            RegisteredComponent(
                name="attestation",
                display_name="Attestations",
                description="On-chain attestations via EAS",
                category="core_infrastructure",
                actions=["create_attestation", "verify_attestation", "revoke_attestation",
                         "query_attestations", "batch_attest"],
                requires_tier="free",
                usage_limits=UsageLimits(
                    free={"attestations_per_month": 10},
                    pro={"attestations_per_month": 500},
                    enterprise={"attestations_per_month": None},
                ),
                trinity_keywords=["attest", "attestation", "verify", "EAS"],
            ),
            RegisteredComponent(
                name="agent_identity",
                display_name="Agent Identity",
                description="Register and manage AI agent identities",
                category="core_infrastructure",
                actions=["register_agent", "get_agent", "update_agent", "deregister_agent", "list_agents"],
                requires_tier="free",
                usage_limits=UsageLimits(
                    free={"agents_registered": 2},
                    pro={"agents_registered": 20},
                    enterprise={"agents_registered": None},
                ),
                trinity_keywords=["agent", "AI agent", "register agent"],
            ),
            RegisteredComponent(
                name="x402_payments",
                display_name="x402 Payments",
                description="HTTP 402-based micropayments",
                category="defi",
                actions=["create_payment", "authorize_payment", "complete_payment",
                         "refund_payment", "get_payment", "list_payments"],
                requires_tier="free",
                trinity_keywords=["x402", "micropayment", "pay-per-request"],
            ),
            RegisteredComponent(
                name="oracle_gateway",
                display_name="Oracle Gateway",
                description="Real-time price feeds and external data",
                category="core_infrastructure",
                actions=["oracle_request", "get_price"],
                requires_tier="free",
                trinity_keywords=["oracle", "price feed", "price", "data feed"],
            ),
            RegisteredComponent(
                name="supply_chain",
                display_name="Supply Chain",
                description="Track products through supply chains",
                category="core_infrastructure",
                actions=["register_product", "update_product_status", "track_product",
                         "verify_product", "transfer_custody"],
                requires_tier="free",
                trinity_keywords=["supply chain", "track product", "logistics"],
            ),
            RegisteredComponent(
                name="insurance",
                display_name="Insurance",
                description="On-chain insurance policies and claims",
                category="defi",
                actions=["create_insurance", "file_insurance_claim", "get_insurance_policy", "cancel_insurance"],
                requires_tier="free",
                usage_limits=UsageLimits(
                    free={"policies_per_month": 2, "max_coverage_usd": 50000},
                    pro={"policies_per_month": 20, "max_coverage_usd": 1000000},
                    enterprise={"policies_per_month": None, "max_coverage_usd": None},
                ),
                trinity_keywords=["insurance", "insure", "coverage", "claim"],
            ),
            RegisteredComponent(
                name="gaming",
                display_name="Gaming",
                description="On-chain gaming assets and economies",
                category="nft_digital_assets",
                actions=["register_game", "get_game", "mint_game_asset",
                         "transfer_game_asset", "approve_game"],
                requires_tier="free",
                trinity_keywords=["game", "gaming", "game asset"],
            ),
            RegisteredComponent(
                name="ip_royalties",
                display_name="IP & Royalties",
                description="Intellectual property registration and royalty management",
                category="nft_digital_assets",
                actions=["register_ip", "get_ip", "transfer_ip", "license_ip"],
                requires_tier="free",
                trinity_keywords=["IP", "intellectual property", "royalty", "license", "copyright"],
            ),
            RegisteredComponent(
                name="staking",
                display_name="Staking",
                description="Stake tokens and earn rewards",
                category="defi",
                actions=["stake", "unstake", "claim_staking_rewards", "get_staking_position"],
                requires_tier="free",
                trinity_keywords=["stake", "staking", "rewards", "yield"],
            ),
            RegisteredComponent(
                name="cross_border",
                display_name="Cross-Border Payments",
                description="International payment transfers",
                category="defi",
                actions=["send_payment", "get_payment_quote", "get_cross_border_payment",
                         "list_cross_border_payments"],
                requires_tier="free",
                trinity_keywords=["cross-border", "international", "wire", "transfer"],
            ),
            RegisteredComponent(
                name="securities_exchange",
                display_name="Securities Exchange",
                description="Tokenized securities trading",
                category="derivatives_advanced",
                actions=["create_security", "list_security", "buy_security",
                         "sell_security", "get_security"],
                requires_tier="free",
                usage_limits=UsageLimits(
                    free={"trades_per_month": 10},
                    pro={"trades_per_month": 500},
                    enterprise={"trades_per_month": None},
                ),
                trinity_keywords=["security", "securities", "stock", "bond", "trade"],
            ),
            RegisteredComponent(
                name="governance",
                display_name="Governance",
                description="On-chain governance and voting",
                category="governance_social",
                actions=["create_proposal", "vote", "get_proposal",
                         "finalize_proposal", "list_proposals"],
                requires_tier="free",
                usage_limits=UsageLimits(
                    free={"votes_per_month": 10, "proposals_per_month": 2},
                    pro={"votes_per_month": 500, "proposals_per_month": 50},
                    enterprise={"votes_per_month": None, "proposals_per_month": None},
                ),
                feature_flags={"advanced_governance_tools": False},
                trinity_keywords=["vote", "proposal", "governance"],
            ),
            RegisteredComponent(
                name="dashboard",
                display_name="Dashboard",
                description="Portfolio overview and analytics",
                category="core_infrastructure",
                actions=["get_dashboard", "get_activity", "get_component_status", "get_platform_stats"],
                requires_tier="free",
                feature_flags={"advanced_exports": False, "enterprise_analytics": False},
                trinity_keywords=["dashboard", "portfolio", "balance", "overview"],
            ),
            RegisteredComponent(
                name="dex",
                display_name="Token Exchange",
                description="Decentralized token swaps and liquidity",
                category="defi",
                actions=["swap_tokens", "get_swap_quote", "add_liquidity",
                         "remove_liquidity", "get_dex_positions"],
                requires_tier="free",
                trinity_keywords=["swap", "exchange", "DEX", "liquidity"],
            ),
            RegisteredComponent(
                name="fundraising",
                display_name="Fundraising",
                description="Create and manage fundraising campaigns",
                category="governance_social",
                actions=["create_campaign", "contribute_to_campaign", "get_campaign",
                         "list_campaigns", "release_milestone_funds", "trigger_refunds"],
                requires_tier="free",
                usage_limits=UsageLimits(
                    free={"campaigns_per_month": 1},
                    pro={"campaigns_per_month": 10},
                    enterprise={"campaigns_per_month": None},
                ),
                trinity_keywords=["fundraise", "campaign", "crowdfund"],
            ),
            RegisteredComponent(
                name="loyalty",
                display_name="Loyalty Rewards",
                description="Earn and redeem loyalty points",
                category="governance_social",
                actions=["earn_loyalty", "redeem_loyalty", "get_loyalty_balance", "get_loyalty_tier"],
                requires_tier="free",
                trinity_keywords=["loyalty", "points", "rewards", "tier"],
            ),
            RegisteredComponent(
                name="marketplace",
                display_name="Marketplace",
                description="Buy and sell items on the marketplace",
                category="nft_digital_assets",
                actions=["list_marketplace", "buy_marketplace", "cancel_listing",
                         "search_marketplace", "get_listing"],
                requires_tier="free",
                usage_limits=UsageLimits(
                    free={"listings_per_month": 2},
                    pro={"listings_per_month": 100},
                    enterprise={"listings_per_month": None},
                ),
                trinity_keywords=["marketplace", "buy", "sell", "listing"],
            ),
            RegisteredComponent(
                name="cashback",
                display_name="Cashback",
                description="Earn cashback on transactions",
                category="defi",
                actions=["track_spending", "get_cashback_balance", "claim_cashback", "get_spending_summary"],
                requires_tier="free",
                trinity_keywords=["cashback", "spending", "earn back"],
            ),
            RegisteredComponent(
                name="brand_rewards",
                display_name="Brand Rewards",
                description="Brand-sponsored reward campaigns",
                category="governance_social",
                actions=["create_brand_campaign", "distribute_brand_reward",
                         "get_brand_campaign", "list_brand_campaigns"],
                requires_tier="free",
                trinity_keywords=["brand", "brand rewards", "campaign", "sponsor"],
            ),
            RegisteredComponent(
                name="subscriptions",
                display_name="Subscriptions",
                description="On-chain subscription management",
                category="defi",
                actions=["create_subscription_plan", "subscribe", "cancel_subscription", "get_subscription"],
                requires_tier="free",
                trinity_keywords=["subscribe", "subscription", "plan", "membership"],
            ),
            RegisteredComponent(
                name="social",
                display_name="Social",
                description="Social profiles and messaging",
                category="governance_social",
                actions=["create_social_profile", "update_social_profile",
                         "get_social_profile", "send_message", "get_social_feed"],
                requires_tier="free",
                trinity_keywords=["social", "profile", "message", "feed"],
            ),
            RegisteredComponent(
                name="privacy",
                display_name="Privacy",
                description="Data deletion and privacy management",
                category="compliance_privacy",
                actions=["request_deletion", "get_privacy_commitment",
                         "check_privacy_dependencies", "get_deletion_status", "execute_deletion"],
                requires_tier="free",
                trinity_keywords=["privacy", "delete", "data deletion", "GDPR"],
            ),
            RegisteredComponent(
                name="dispute_resolution",
                display_name="Dispute Resolution",
                description="On-chain dispute filing and arbitration",
                category="compliance_privacy",
                actions=["file_dispute", "submit_dispute_evidence", "get_dispute",
                         "resolve_dispute", "appeal_dispute"],
                requires_tier="free",
                trinity_keywords=["dispute", "arbitration", "conflict", "appeal"],
            ),
        ]

        for comp in builtins:
            self._components[comp.name] = comp

        logger.info("Registered %d built-in components", len(builtins))

    def register_plugin(self, manifest: PluginManifest) -> list[str]:
        """Register a third-party plugin's components.

        Returns:
            List of registered component names.
        """
        registered = []
        for comp_decl in manifest.components:
            tier = manifest.requires_tier
            if comp_decl.requires_enterprise:
                tier = "enterprise"
            elif comp_decl.requires_pro:
                tier = "pro"

            component = RegisteredComponent(
                name=comp_decl.name,
                display_name=manifest.display_name,
                description=manifest.description,
                category="plugin",
                actions=comp_decl.actions,
                requires_tier=tier,
                feature_flags=comp_decl.feature_flags,
                trinity_keywords=manifest.trinity_skills,
                is_plugin=True,
                plugin_author=manifest.author,
            )
            self._components[comp_decl.name] = component
            registered.append(comp_decl.name)

        logger.info(
            "Registered plugin '%s' with %d components",
            manifest.name, len(registered),
        )
        return registered

    def get_component(self, name: str) -> RegisteredComponent | None:
        """Get a registered component by name."""
        return self._components.get(name)

    def get_available_components(self, user_tier: str) -> list[RegisteredComponent]:
        """Return all components available for a given tier."""
        tier_level = {"free": 0, "pro": 1, "enterprise": 2}
        user_level = tier_level.get(user_tier, 0)

        available = []
        for comp in self._components.values():
            required_level = tier_level.get(comp.requires_tier, 0)
            if user_level >= required_level:
                available.append(comp)

        return available

    def is_action_allowed(self, action: str, user_tier: str) -> bool:
        """Check if a specific action is allowed for a given tier."""
        for comp in self._components.values():
            if action in comp.actions:
                tier_level = {"free": 0, "pro": 1, "enterprise": 2}
                return tier_level.get(user_tier, 0) >= tier_level.get(comp.requires_tier, 0)
        return False

    def get_limits_for_action(self, action: str, user_tier: str) -> dict[str, Any]:
        """Get usage limits for an action at a given tier."""
        for comp in self._components.values():
            if action in comp.actions and comp.usage_limits:
                return comp.usage_limits.get_limits(user_tier)
        return {}

    def get_all_actions(self, user_tier: str = "enterprise") -> list[str]:
        """Return all action names available for a tier."""
        actions = []
        for comp in self.get_available_components(user_tier):
            actions.extend(comp.actions)
        return actions

    def get_registry_summary(self) -> dict[str, Any]:
        """Return a summary of all registered components."""
        total = len(self._components)
        builtins = sum(1 for c in self._components.values() if not c.is_plugin)
        plugins = sum(1 for c in self._components.values() if c.is_plugin)
        total_actions = sum(len(c.actions) for c in self._components.values())

        return {
            "total_components": total,
            "builtin_components": builtins,
            "plugin_components": plugins,
            "total_actions": total_actions,
        }
