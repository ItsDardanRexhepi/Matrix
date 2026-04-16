"""
Capability Catalog — the single source of truth for every capability the
0pnMatrx platform can perform across Web3.

Each entry is a plain dict (not a dataclass — matches the duck-typed style
used by services) with the following shape:

    {
        "id": str,                # unique, kebab_case
        "name": str,              # human-friendly
        "category": str,          # high-level bucket
        "subcategory": str,       # finer-grain grouping
        "description": str,       # plain English, 1 line
        "service": str,           # resolves via runtime.blockchain.services.registry
        "method": str,            # method on the service instance
        "action": str,            # ACTION_MAP key (usually == id, but not always)
        "params_schema": dict,    # JSON-schema-ish snippet for input validation
        "state_modifying": bool,  # True if it writes to chain / DB
        "feed_event": str | None, # live social feed event name (or None)
        "min_tier": str,          # "free" | "pro" | "enterprise"
        "uses_paymaster": bool,   # True if platform sponsors the tx
        "protocol": str | None,   # external protocol tag (eigenlayer, pyth, ...)
        "available": bool,        # True when backend+contracts deployed
    }

The same catalog backs:
    * Trinity's platform_action tool enum (via install_action_map)
    * Gateway /api/v1/capabilities endpoints
    * iOS extensions registry
    * Documentation generation
"""

from __future__ import annotations

from typing import Any


# ---------------------------------------------------------------------------
# Helper: build an entry with sensible defaults so the list below stays terse.
# ---------------------------------------------------------------------------

def _cap(
    id: str,
    name: str,
    category: str,
    service: str,
    method: str,
    description: str = "",
    *,
    subcategory: str = "",
    action: str | None = None,
    params_schema: dict | None = None,
    state_modifying: bool = True,
    feed_event: str | None = None,
    min_tier: str = "free",
    uses_paymaster: bool = True,
    protocol: str | None = None,
    available: bool = True,
) -> dict:
    return {
        "id": id,
        "name": name,
        "category": category,
        "subcategory": subcategory or category,
        "description": description or name,
        "service": service,
        "method": method,
        "action": action or id,
        "params_schema": params_schema or {"type": "object", "properties": {}},
        "state_modifying": state_modifying,
        "feed_event": feed_event,
        "min_tier": min_tier,
        "uses_paymaster": uses_paymaster,
        "protocol": protocol,
        "available": available,
    }


# ---------------------------------------------------------------------------
# Categories: 18 high-level buckets covering every slice of Web3.
# ---------------------------------------------------------------------------

CATEGORIES: list[dict[str, str]] = [
    {"id": "contracts",      "name": "Smart Contracts",    "icon": "doc.text.fill"},
    {"id": "defi",           "name": "DeFi",               "icon": "chart.line.uptrend.xyaxis"},
    {"id": "defi_advanced",  "name": "DeFi (Advanced)",    "icon": "chart.bar.xaxis"},
    {"id": "nft",            "name": "NFTs",               "icon": "sparkles"},
    {"id": "nft_finance",    "name": "NFT Finance",        "icon": "dollarsign.square"},
    {"id": "identity",       "name": "Identity",           "icon": "person.text.rectangle"},
    {"id": "governance",     "name": "Governance",         "icon": "person.3.fill"},
    {"id": "social",         "name": "Social",             "icon": "bubble.left.and.bubble.right"},
    {"id": "creator",        "name": "Creator Economy",    "icon": "music.note"},
    {"id": "payments",       "name": "Payments",           "icon": "creditcard"},
    {"id": "bridging",       "name": "Cross-chain",        "icon": "arrow.left.arrow.right"},
    {"id": "staking",        "name": "Staking & Restake",  "icon": "lock.square.stack"},
    {"id": "privacy",        "name": "Privacy & ZK",       "icon": "lock.shield"},
    {"id": "oracles",        "name": "Oracles & Data",     "icon": "antenna.radiowaves.left.and.right"},
    {"id": "storage",        "name": "Storage",            "icon": "externaldrive"},
    {"id": "compute",        "name": "Compute & DePIN",    "icon": "cpu"},
    {"id": "real_world",     "name": "Real-world Assets",  "icon": "building.2"},
    {"id": "markets",        "name": "Markets",            "icon": "chart.xyaxis.line"},
    {"id": "security",       "name": "Security & Wallets", "icon": "key.fill"},
    {"id": "gaming",         "name": "Gaming",             "icon": "gamecontroller"},
    {"id": "infra",          "name": "Infrastructure",     "icon": "server.rack"},
]


# ---------------------------------------------------------------------------
# CAPABILITIES — the complete catalog.
# Organized by category. Each entry inherits defaults from _cap().
# ---------------------------------------------------------------------------

CAPABILITIES: list[dict[str, Any]] = [

    # ── Smart Contracts ────────────────────────────────────────────────────
    _cap("deploy_contract",        "Deploy Contract",          "contracts", "contract_conversion", "convert",
         "Convert any description into a deployed smart contract", feed_event="contract_deployed"),
    _cap("convert_contract",       "Convert to Solidity",      "contracts", "contract_conversion", "convert",
         "Convert natural language to Solidity", feed_event="contract_converted"),
    _cap("estimate_contract_cost", "Estimate Deployment Cost", "contracts", "contract_conversion", "estimate_cost",
         state_modifying=False, uses_paymaster=False),
    _cap("list_templates",         "List Contract Templates",  "contracts", "contract_conversion", "get_available_templates",
         state_modifying=False, uses_paymaster=False),

    # ── DeFi (core) ────────────────────────────────────────────────────────
    _cap("create_loan",      "Borrow Against Collateral", "defi", "defi", "create_loan",  feed_event="loan_created"),
    _cap("repay_loan",       "Repay Loan",                "defi", "defi", "repay_loan",   feed_event="loan_repaid"),
    _cap("get_loan",         "Get Loan Details",          "defi", "defi", "get_loan",     state_modifying=False, uses_paymaster=False),
    _cap("flash_loan",       "Flash Loan",                "defi", "defi", "flash_loan",   subcategory="flash"),
    _cap("yield_optimize",   "Yield Optimization",        "defi", "defi", "yield_optimize"),
    _cap("liquidity_provide","Provide Liquidity",         "defi", "dex",  "add_liquidity"),
    _cap("liquidity_remove", "Remove Liquidity",          "defi", "dex",  "remove_liquidity"),
    _cap("swap_tokens",      "Swap Tokens",               "defi", "dex",  "swap",         feed_event="tokens_swapped"),
    _cap("vault_deposit",    "Deposit to Vault",          "defi", "defi", "vault_deposit"),
    _cap("collateral_manage","Manage Collateral",         "defi", "defi", "collateral_manage"),

    # ── DeFi Advanced ──────────────────────────────────────────────────────
    _cap("perp_trade",              "Open Perpetual Position", "defi_advanced", "defi",       "perp_trade", protocol="gmx"),
    _cap("options_trade",           "Trade Options",           "defi_advanced", "defi",       "options_trade", protocol="lyra"),
    _cap("synthetic_asset",         "Mint Synthetic Asset",    "defi_advanced", "defi",       "synthetic_asset", protocol="synthetix"),
    _cap("leverage_position",       "Leverage Position",       "defi_advanced", "defi",       "leverage_position"),
    _cap("place_limit_order",       "Place Limit Order",       "defi_advanced", "auctions",   "place_limit_order", subcategory="orderbook", available=False),
    _cap("cancel_limit_order",      "Cancel Limit Order",      "defi_advanced", "auctions",   "cancel_limit_order", subcategory="orderbook", available=False),
    _cap("pyth_pull_price",         "Pull Pyth Price",         "defi_advanced", "oracles_plus","pyth_pull", protocol="pyth", state_modifying=False, uses_paymaster=False, available=False),

    # ── Restaking ──────────────────────────────────────────────────────────
    _cap("restake_eigenlayer",      "Restake on EigenLayer",   "staking", "restaking",  "restake",                 subcategory="restaking", protocol="eigenlayer",  available=False),
    _cap("restake_symbiotic",       "Restake on Symbiotic",    "staking", "restaking",  "restake_symbiotic",       subcategory="restaking", protocol="symbiotic",   available=False),
    _cap("restake_karak",           "Restake on Karak",        "staking", "restaking",  "restake_karak",           subcategory="restaking", protocol="karak",       available=False),
    _cap("delegate_to_operator",    "Delegate to Operator",    "staking", "restaking",  "delegate_to_operator",    subcategory="restaking", available=False),
    _cap("withdraw_restake",        "Withdraw Restake",        "staking", "restaking",  "withdraw_restake",        subcategory="restaking", available=False),
    _cap("liquid_stake_lido",       "Liquid Stake with Lido",  "staking", "staking",    "liquid_stake_lido",       subcategory="liquid", protocol="lido",   available=False),
    _cap("liquid_stake_rocketpool", "Liquid Stake (Rocket)",   "staking", "staking",    "liquid_stake_rocketpool", subcategory="liquid", protocol="rocketpool", available=False),

    # ── Staking (core) ─────────────────────────────────────────────────────
    _cap("stake",                   "Stake Tokens",            "staking", "staking", "stake",                 feed_event="tokens_staked"),
    _cap("unstake",                 "Unstake Tokens",          "staking", "staking", "unstake",               feed_event="tokens_unstaked"),
    _cap("claim_staking_rewards",   "Claim Staking Rewards",   "staking", "staking", "claim_staking_rewards", feed_event="rewards_claimed"),
    _cap("get_staking_position",    "Get Staking Position",    "staking", "staking", "get_position", state_modifying=False, uses_paymaster=False),

    # ── NFTs ───────────────────────────────────────────────────────────────
    _cap("mint_nft",                "Mint NFT",                "nft", "nft_services", "mint",              feed_event="nft_minted"),
    _cap("create_nft_collection",   "Create NFT Collection",   "nft", "nft_services", "create_collection", feed_event="collection_created"),
    _cap("transfer_nft",            "Transfer NFT",            "nft", "nft_services", "transfer"),
    _cap("list_nft_for_sale",       "List NFT for Sale",       "nft", "nft_services", "list_for_sale",     feed_event="nft_listed"),
    _cap("buy_nft",                 "Buy NFT",                 "nft", "nft_services", "process_sale",      feed_event="nft_purchased"),
    _cap("estimate_nft_value",      "Estimate NFT Value",      "nft", "nft_services", "estimate_value",    state_modifying=False, uses_paymaster=False),
    _cap("get_nft_rarity",          "Get NFT Rarity",          "nft", "nft_services", "get_rarity_score",  state_modifying=False, uses_paymaster=False),
    _cap("set_nft_rights",          "Set NFT Rights",          "nft", "nft_services", "set_rights"),
    _cap("check_nft_rights",        "Check NFT Rights",        "nft", "nft_services", "check_rights",      state_modifying=False, uses_paymaster=False),
    _cap("configure_nft_royalty",   "Configure NFT Royalty",   "nft", "nft_services", "configure_royalty"),
    _cap("nft_fractionalize",       "Fractionalize NFT",       "nft", "nft_services", "nft_fractionalize"),
    _cap("nft_rent",                "Rent NFT",                "nft", "nft_services", "nft_rent"),
    _cap("nft_dynamic_update",      "Update Dynamic NFT",      "nft", "nft_services", "nft_dynamic_update"),
    _cap("nft_batch_mint",          "Batch Mint NFTs",         "nft", "nft_services", "nft_batch_mint"),
    _cap("nft_royalty_claim",       "Claim NFT Royalties",     "nft", "nft_services", "nft_royalty_claim"),
    _cap("nft_bridge",              "Bridge NFT",              "nft", "nft_services", "nft_bridge"),
    _cap("soulbound_mint",          "Mint Soulbound NFT",      "nft", "nft_services", "soulbound_mint",    subcategory="soulbound"),

    # ── NFT Finance ────────────────────────────────────────────────────────
    _cap("borrow_against_nft",      "Borrow Against NFT",      "nft_finance", "nft_lending", "borrow_against_nft", protocol="benddao",  available=False),
    _cap("liquidate_nft_loan",      "Liquidate NFT Loan",      "nft_finance", "nft_lending", "liquidate_nft_loan", protocol="nftfi",    available=False),
    _cap("breed_nft",               "Breed NFT",               "nft_finance", "nft_lending", "breed_nft",          subcategory="breeding", available=False),

    # ── Token-bound accounts (ERC-6551) ───────────────────────────────────
    _cap("create_tba",              "Create Token-bound Account", "nft_finance", "tba", "create_tba",       protocol="erc6551", available=False),
    _cap("execute_as_tba",          "Execute As TBA",             "nft_finance", "tba", "execute_as_tba",   protocol="erc6551", available=False),

    # ── Identity ───────────────────────────────────────────────────────────
    _cap("create_did",              "Create DID",              "identity", "did_identity", "create",           feed_event="did_created"),
    _cap("update_did",              "Update DID",              "identity", "did_identity", "update"),
    _cap("deactivate_did",          "Deactivate DID",          "identity", "did_identity", "deactivate"),
    _cap("credential_issue",        "Issue Credential",        "identity", "did_identity", "credential_issue"),
    _cap("reputation_query",        "Query Reputation",        "identity", "agent_identity", "reputation_query", state_modifying=False, uses_paymaster=False),
    _cap("start_kyc",               "Start KYC",               "identity", "kyc", "start_kyc",         protocol="sumsub", available=False),
    _cap("check_aml_risk",          "Check AML Risk",          "identity", "kyc", "check_aml_risk",    state_modifying=False, uses_paymaster=False, available=False),
    _cap("issue_kyc_credential",    "Issue KYC Credential",    "identity", "kyc", "issue_kyc_credential", available=False),
    _cap("register_agent",          "Register AI Agent",       "identity", "agent_identity", "register"),
    _cap("update_agent",            "Update Agent",            "identity", "agent_identity", "update"),
    _cap("deregister_agent",        "Deregister Agent",        "identity", "agent_identity", "deregister"),
    _cap("create_attestation",      "Create Attestation",      "identity", "attestation", "create"),
    _cap("revoke_attestation",      "Revoke Attestation",      "identity", "attestation", "revoke"),
    _cap("batch_attest",            "Batch Attest",            "identity", "attestation", "batch_attest"),

    # ── Governance ─────────────────────────────────────────────────────────
    _cap("create_dao",              "Create DAO",              "governance", "dao_management", "create",         feed_event="dao_created"),
    _cap("join_dao",                "Join DAO",                "governance", "dao_management", "join"),
    _cap("leave_dao",               "Leave DAO",               "governance", "dao_management", "leave"),
    _cap("create_proposal",         "Create Proposal",         "governance", "governance", "create_proposal", feed_event="proposal_created"),
    _cap("vote",                    "Vote on Proposal",        "governance", "governance", "vote",            feed_event="vote_cast"),
    _cap("finalize_proposal",       "Finalize Proposal",       "governance", "governance", "finalize"),
    _cap("snapshot_vote",           "Snapshot Vote",           "governance", "governance", "snapshot_vote",   protocol="snapshot"),
    _cap("timelock_queue",          "Queue Timelock Action",   "governance", "governance", "timelock_queue"),
    _cap("multisig_propose",        "Propose Multisig Action", "governance", "governance", "multisig_propose"),
    _cap("multisig_approve",        "Approve Multisig Action", "governance", "governance", "multisig_approve"),
    _cap("treasury_transfer",       "Treasury Transfer",       "governance", "governance", "treasury_transfer"),
    _cap("parameter_change",        "Parameter Change",        "governance", "governance", "parameter_change"),
    _cap("vote_escrow",             "Vote-Escrow Lock",        "governance", "advanced_governance", "vote_escrow",          subcategory="veToken",    protocol="curve",  available=False),
    _cap("quadratic_vote",          "Quadratic Vote",          "governance", "advanced_governance", "quadratic_vote",       subcategory="quadratic",  available=False),
    _cap("submit_retropgf",         "Submit RetroPGF",         "governance", "advanced_governance", "submit_retropgf",      subcategory="retropgf",   protocol="optimism", available=False),
    _cap("place_bribe",             "Place Gauge Bribe",       "governance", "advanced_governance", "place_bribe",          subcategory="bribes",     protocol="convex", available=False),
    _cap("delegate_voting",         "Delegate Voting Power",   "governance", "advanced_governance", "delegate_voting",      available=False),

    # ── Social ─────────────────────────────────────────────────────────────
    _cap("create_social_profile",   "Create Social Profile",   "social", "social", "create_social_profile", feed_event="profile_created"),
    _cap("update_social_profile",   "Update Social Profile",   "social", "social", "update_social_profile"),
    _cap("social_post",             "Social Post",             "social", "social", "social_post"),
    _cap("social_gate",             "Gated Social Content",    "social", "social", "social_gate"),
    _cap("community_create",        "Create Community",        "social", "social", "community_create"),
    _cap("send_message",            "Send Message (XMTP)",     "social", "social", "send_message",       protocol="xmtp"),
    _cap("message_encrypt",         "Encrypted Message",       "social", "social", "message_encrypt"),
    _cap("create_lens_profile",     "Create Lens Profile",     "social", "social_protocols", "create_lens_profile",     protocol="lens",    available=False),
    _cap("publish_cast",            "Publish Farcaster Cast",  "social", "social_protocols", "publish_cast",            protocol="farcaster", available=False),
    _cap("push_subscribe",          "Subscribe to Push",       "social", "social_protocols", "push_subscribe",          protocol="push",    available=False),
    _cap("launch_social_token",     "Launch Social Token",     "social", "social_protocols", "launch_social_token",     available=False),
    _cap("launch_creator_coin",     "Launch Creator Coin",     "social", "social_protocols", "launch_creator_coin",     available=False),

    # ── Creator Economy ────────────────────────────────────────────────────
    _cap("creator_monetize",        "Monetize Content",        "creator", "social", "creator_monetize"),
    _cap("mint_sound",              "Mint Sound.xyz Drop",     "creator", "creator_platforms", "mint_sound",            protocol="sound",     available=False),
    _cap("publish_mirror_post",     "Publish Mirror Post",     "creator", "creator_platforms", "publish_mirror_post",   protocol="mirror",    available=False),
    _cap("publish_paragraph_post",  "Publish Paragraph Post",  "creator", "creator_platforms", "publish_paragraph_post",protocol="paragraph", available=False),
    _cap("register_ip",             "Register IP",             "creator", "ip_royalties", "register",    feed_event="ip_registered"),
    _cap("transfer_ip",             "Transfer IP",             "creator", "ip_royalties", "transfer"),
    _cap("license_ip",              "License IP",              "creator", "ip_royalties", "license"),
    _cap("agreement_execute",       "Execute Agreement",       "creator", "ip_royalties", "agreement_execute"),

    # ── Payments ───────────────────────────────────────────────────────────
    _cap("create_payment",          "Create Payment",          "payments", "x402_payments", "create_payment", feed_event="payment_created"),
    _cap("authorize_payment",       "Authorize Payment",       "payments", "x402_payments", "authorize"),
    _cap("complete_payment",        "Complete Payment",        "payments", "x402_payments", "complete"),
    _cap("refund_payment",          "Refund Payment",          "payments", "x402_payments", "refund"),
    _cap("send_payment",            "Send Payment",            "payments", "stablecoin",    "send_payment",  feed_event="payment_sent"),
    _cap("transfer_stablecoin",     "Transfer Stablecoin",     "payments", "stablecoin",    "transfer",      feed_event="stablecoin_sent"),
    _cap("stream_payment",          "Stream Payment",          "payments", "x402_payments", "stream_payment",   protocol="superfluid"),
    _cap("recurring_create",        "Create Recurring Payment","payments", "x402_payments", "recurring_create"),
    _cap("escrow_milestone",        "Milestone Escrow",        "payments", "x402_payments", "escrow_milestone"),
    _cap("payment_split",           "Split Payment",           "payments", "x402_payments", "payment_split"),
    _cap("invoice_factor",          "Factor Invoice",          "payments", "x402_payments", "invoice_factor"),
    _cap("payroll_run",             "Run Payroll",             "payments", "x402_payments", "payroll_run"),
    _cap("cross_border_remit",      "Cross-border Remit",      "payments", "cross_border",  "cross_border_remit"),
    _cap("open_channel",            "Open Payment Channel",    "payments", "payment_channels", "open_channel",  subcategory="state_channels", available=False),
    _cap("route_payment",           "Route via Channel",       "payments", "payment_channels", "route_payment", subcategory="state_channels", available=False),
    _cap("close_channel",           "Close Payment Channel",   "payments", "payment_channels", "close_channel", subcategory="state_channels", available=False),

    # ── Cross-chain / Bridging ─────────────────────────────────────────────
    _cap("cross_chain_bridge",      "Bridge Tokens",           "bridging", "cross_border", "cross_chain_bridge"),
    _cap("bridge_token_ccip",       "Bridge via CCIP",         "bridging", "ccip",         "bridge_token_ccip",       protocol="ccip",      available=False),
    _cap("send_cross_chain_message","Cross-chain Message",     "bridging", "ccip",         "send_cross_chain_message",protocol="ccip",      available=False),
    _cap("bridge_hyperlane",        "Bridge via Hyperlane",    "bridging", "ccip",         "bridge_hyperlane",        protocol="hyperlane", available=False),
    _cap("bridge_wormhole",         "Bridge via Wormhole",     "bridging", "ccip",         "bridge_wormhole",         protocol="wormhole",  available=False),
    _cap("bridge_axelar",           "Bridge via Axelar",       "bridging", "ccip",         "bridge_axelar",           protocol="axelar",    available=False),
    _cap("bridge_stargate",         "Bridge via Stargate",     "bridging", "ccip",         "bridge_stargate",         protocol="stargate",  available=False),
    _cap("query_remote_chain",      "Query Remote Chain",      "bridging", "ccip",         "query_remote_chain",      state_modifying=False, uses_paymaster=False, available=False),

    # ── Privacy & ZK ───────────────────────────────────────────────────────
    _cap("private_transfer",        "Private Transfer",        "privacy", "privacy", "private_transfer"),
    _cap("stealth_address",         "Stealth Address",         "privacy", "privacy", "stealth_address"),
    _cap("zk_proof_generate",       "Generate ZK Proof",       "privacy", "privacy", "zk_proof_generate"),
    _cap("private_vote",            "Private Vote",            "privacy", "privacy", "private_vote"),
    _cap("confidential_compute",    "Confidential Compute",    "privacy", "privacy", "confidential_compute"),
    _cap("mpc_sign",                "MPC Sign",                "privacy", "mpc", "mpc_sign",           subcategory="mpc", available=False),
    _cap("recover_wallet",          "Social Recovery",         "privacy", "mpc", "recover_wallet",     subcategory="recovery", available=False),
    _cap("create_session_key",      "Create Session Key",      "privacy", "mpc", "create_session_key", subcategory="session_keys", available=False),
    _cap("request_deletion",        "Request Deletion",        "privacy", "privacy", "request_deletion"),
    _cap("execute_deletion",        "Execute Deletion",        "privacy", "privacy", "execute_deletion"),

    # ── Oracles & Data ─────────────────────────────────────────────────────
    _cap("oracle_price_query",      "Query Oracle Price",      "oracles", "oracle_gateway", "query_price",  state_modifying=False, uses_paymaster=False),
    _cap("oracle_vrf_request",      "Request VRF Randomness",  "oracles", "oracle_gateway", "request_vrf",  protocol="chainlink"),
    _cap("oracle_weather_query",    "Query Weather Oracle",    "oracles", "oracle_gateway", "query_weather",state_modifying=False, uses_paymaster=False),
    _cap("pyth_pull",               "Pull Pyth Update",        "oracles", "oracles_plus",   "pyth_pull",     protocol="pyth",     state_modifying=False, uses_paymaster=False, available=False),
    _cap("redstone_request",        "Request RedStone Data",   "oracles", "oracles_plus",   "redstone_request", protocol="redstone", state_modifying=False, uses_paymaster=False, available=False),
    _cap("api3_query",              "Query API3",              "oracles", "oracles_plus",   "api3_query",    protocol="api3",     state_modifying=False, uses_paymaster=False, available=False),
    _cap("register_keeper_job",     "Register Keeper Job",     "oracles", "oracles_plus",   "register_keeper_job", protocol="chainlink_keepers", available=False),

    # ── Storage ────────────────────────────────────────────────────────────
    _cap("ipfs_pin",                "Pin to IPFS",             "storage", "privacy", "ipfs_pin"),
    _cap("arweave_store",           "Store on Arweave",        "storage", "privacy", "arweave_store"),
    _cap("store_filecoin",          "Store on Filecoin",       "storage", "storage", "store_filecoin",   protocol="filecoin", available=False),
    _cap("ceramic_stream_create",   "Create Ceramic Stream",   "storage", "storage", "ceramic_stream_create", protocol="ceramic", available=False),
    _cap("orbit_db_write",          "Write to OrbitDB",        "storage", "storage", "orbit_db_write",   protocol="orbitdb", available=False),
    _cap("decentralized_store",     "Decentralized Store",     "storage", "privacy", "decentralized_store"),

    # ── Compute & DePIN ────────────────────────────────────────────────────
    _cap("submit_compute_job",      "Submit Compute Job",      "compute", "compute", "submit_compute_job", subcategory="compute", protocol="akash", available=False),
    _cap("rent_device",             "Rent DePIN Device",       "compute", "compute", "rent_device",        subcategory="depin", available=False),
    _cap("claim_compute_reward",    "Claim Compute Reward",    "compute", "compute", "claim_compute_reward", available=False),
    _cap("compute_job_submit",      "Submit Legacy Compute",   "compute", "privacy", "compute_job_submit"),

    # ── Real-World Assets & ReFi ───────────────────────────────────────────
    _cap("tokenize_asset",          "Tokenize Asset",          "real_world", "rwa_tokenization", "tokenize_asset"),
    _cap("transfer_rwa_ownership",  "Transfer RWA Ownership",  "real_world", "rwa_tokenization", "transfer_ownership"),
    _cap("rwa_tokenize",            "RWA Tokenize",            "real_world", "rwa_tokenization", "rwa_tokenize"),
    _cap("rwa_fractional_buy",      "Buy RWA Fraction",        "real_world", "rwa_tokenization", "rwa_fractional_buy"),
    _cap("rwa_income_claim",        "Claim RWA Income",        "real_world", "rwa_tokenization", "rwa_income_claim"),
    _cap("register_product",        "Register Product",        "real_world", "supply_chain", "register_product"),
    _cap("update_product_status",   "Update Product Status",   "real_world", "supply_chain", "update_product_status"),
    _cap("transfer_custody",        "Transfer Custody",        "real_world", "supply_chain", "transfer_custody"),
    _cap("provenance_log",          "Log Provenance",          "real_world", "supply_chain", "provenance_log"),
    _cap("batch_track",             "Batch Track",             "real_world", "supply_chain", "batch_track"),
    _cap("custody_transfer",        "Custody Transfer",        "real_world", "supply_chain", "custody_transfer"),
    _cap("carbon_credit_buy",       "Buy Carbon Credit",       "real_world", "privacy", "carbon_credit_buy",    protocol="toucan"),
    _cap("carbon_credit_retire",    "Retire Carbon Credit",    "real_world", "privacy", "carbon_credit_retire", protocol="klimadao"),
    _cap("renewable_cert_buy",      "Buy Renewable Cert",      "real_world", "privacy", "renewable_cert_buy"),
    _cap("green_bond_invest",       "Invest in Green Bond",    "real_world", "privacy", "green_bond_invest"),

    # ── Markets ────────────────────────────────────────────────────────────
    _cap("market_create",           "Create Prediction Market","markets", "gaming", "market_create", protocol="polymarket"),
    _cap("market_bet",              "Place Prediction Bet",    "markets", "gaming", "market_bet"),
    _cap("market_resolve",          "Resolve Market",          "markets", "gaming", "market_resolve"),
    _cap("create_auction",          "Create Auction",          "markets", "auctions", "create_auction",  subcategory="auction", available=False),
    _cap("place_bid",               "Place Auction Bid",       "markets", "auctions", "place_bid",      subcategory="auction", available=False),
    _cap("settle_auction",          "Settle Auction",          "markets", "auctions", "settle_auction", subcategory="auction", available=False),
    _cap("create_campaign",         "Create Fundraiser",       "markets", "fundraising", "create_campaign",           feed_event="campaign_created"),
    _cap("contribute_to_campaign",  "Contribute to Campaign",  "markets", "fundraising", "contribute",                feed_event="campaign_contribution"),
    _cap("release_milestone_funds", "Release Milestone Funds", "markets", "fundraising", "release_milestone_funds"),
    _cap("trigger_refunds",         "Trigger Refunds",         "markets", "fundraising", "trigger_refunds"),
    _cap("create_security",         "Create Security Token",   "markets", "securities_exchange", "create_security"),
    _cap("list_security",           "List Security",           "markets", "securities_exchange", "list_security"),
    _cap("buy_security",            "Buy Security",            "markets", "securities_exchange", "buy_security"),
    _cap("sell_security",           "Sell Security",           "markets", "securities_exchange", "sell_security"),

    # ── Gaming ─────────────────────────────────────────────────────────────
    _cap("register_game",           "Register Game",           "gaming", "gaming", "register_game"),
    _cap("mint_game_asset",         "Mint Game Asset",         "gaming", "gaming", "mint_game_asset"),
    _cap("transfer_game_asset",     "Transfer Game Asset",     "gaming", "gaming", "transfer_game_asset"),
    _cap("approve_game",            "Approve Game",            "gaming", "gaming", "approve_game"),
    _cap("game_asset_mint",         "Mint Game Asset (Legacy)","gaming", "gaming", "game_asset_mint"),
    _cap("tournament_enter",        "Enter Tournament",        "gaming", "gaming", "tournament_enter"),
    _cap("game_item_trade",         "Trade Game Item",         "gaming", "gaming", "game_item_trade"),
    _cap("achievement_attest",      "Attest Achievement",      "gaming", "gaming", "achievement_attest"),

    # ── Insurance ──────────────────────────────────────────────────────────
    _cap("create_insurance",        "Create Policy",           "real_world", "insurance", "create_policy"),
    _cap("file_insurance_claim",    "File Claim",              "real_world", "insurance", "file_claim"),
    _cap("cancel_insurance",        "Cancel Policy",           "real_world", "insurance", "cancel_policy"),
    _cap("parametric_policy",       "Parametric Policy",       "real_world", "insurance", "parametric_policy"),
    _cap("claim_auto_settle",       "Auto-settle Claim",       "real_world", "insurance", "claim_auto_settle"),
    _cap("cover_renew",             "Renew Cover",             "real_world", "insurance", "cover_renew"),

    # ── Marketplace / Loyalty / Rewards ───────────────────────────────────
    _cap("list_marketplace",        "List Marketplace Item",   "markets", "marketplace", "list_marketplace"),
    _cap("buy_marketplace",         "Buy Marketplace Item",    "markets", "marketplace", "buy_marketplace"),
    _cap("cancel_listing",          "Cancel Listing",          "markets", "marketplace", "cancel_listing"),
    _cap("earn_loyalty",            "Earn Loyalty Points",     "markets", "loyalty", "earn_loyalty"),
    _cap("redeem_loyalty",          "Redeem Loyalty Points",   "markets", "loyalty", "redeem_loyalty"),
    _cap("track_spending",          "Track Spending",          "markets", "cashback", "track_spending"),
    _cap("claim_cashback",          "Claim Cashback",          "markets", "cashback", "claim_cashback"),
    _cap("create_brand_campaign",   "Create Brand Campaign",   "markets", "brand_rewards", "create_brand_campaign"),
    _cap("distribute_brand_reward", "Distribute Brand Reward", "markets", "brand_rewards", "distribute_brand_reward"),
    _cap("create_subscription_plan","Create Subscription Plan","markets", "subscriptions", "create_subscription_plan"),
    _cap("subscribe",               "Subscribe",               "markets", "subscriptions", "subscribe"),
    _cap("cancel_subscription",     "Cancel Subscription",     "markets", "subscriptions", "cancel_subscription"),

    # ── Disputes ───────────────────────────────────────────────────────────
    _cap("file_dispute",            "File Dispute",            "governance", "dispute_resolution", "file_dispute"),
    _cap("submit_dispute_evidence", "Submit Evidence",         "governance", "dispute_resolution", "submit_evidence"),
    _cap("resolve_dispute",         "Resolve Dispute",         "governance", "dispute_resolution", "resolve_dispute"),
    _cap("appeal_dispute",          "Appeal Dispute",          "governance", "dispute_resolution", "appeal_dispute"),
    _cap("dispute_file",            "Dispute File (Legacy)",   "governance", "dispute_resolution", "dispute_file"),
    _cap("arbitration_request",     "Request Arbitration",     "governance", "dispute_resolution", "arbitration_request"),

    # ── AI Agents / ML ─────────────────────────────────────────────────────
    _cap("ai_agent_register",       "Register AI Agent",       "infra", "agent_identity", "ai_agent_register"),
    _cap("ai_model_trade",          "Trade AI Model",          "infra", "agent_identity", "ai_model_trade"),
    _cap("training_data_sell",      "Sell Training Data",      "infra", "agent_identity", "training_data_sell"),
    _cap("ip_license_grant",        "Grant IP License",        "infra", "ip_royalties",   "ip_license_grant"),
]


# ---------------------------------------------------------------------------
# Derived lookups (computed at module import)
# ---------------------------------------------------------------------------

def _index() -> dict[str, dict]:
    return {cap["id"]: cap for cap in CAPABILITIES}


_BY_ID: dict[str, dict] = _index()


def get_by_id(capability_id: str) -> dict | None:
    return _BY_ID.get(capability_id)


def get_by_category(category: str) -> list[dict]:
    return [cap for cap in CAPABILITIES if cap["category"] == category]


def list_categories() -> list[dict]:
    """Return categories with a count of capabilities each."""
    counts: dict[str, int] = {}
    for cap in CAPABILITIES:
        counts[cap["category"]] = counts.get(cap["category"], 0) + 1
    return [
        {**cat, "count": counts.get(cat["id"], 0)}
        for cat in CATEGORIES
    ]


def as_action_map() -> dict[str, tuple[str, str]]:
    """Return action_name -> (service, method) pairs for every capability."""
    return {cap["action"]: (cap["service"], cap["method"]) for cap in CAPABILITIES}


def state_modifying_actions() -> frozenset[str]:
    return frozenset(cap["action"] for cap in CAPABILITIES if cap["state_modifying"])


def action_to_feed_event() -> dict[str, str]:
    return {cap["action"]: cap["feed_event"] for cap in CAPABILITIES if cap["feed_event"]}


def install_action_map(
    action_map: dict[str, tuple[str, str]],
    state_set: set | None = None,
    feed_map: dict[str, str] | None = None,
) -> dict[str, str]:
    """Merge catalog entries into the existing dispatcher dicts.

    Returns a dict of {action_name: reason} for any skipped entries (e.g.
    action already present with a different (service, method) pair — we
    never silently override). Callers can log or raise on the result.
    """
    skipped: dict[str, str] = {}

    for cap in CAPABILITIES:
        action = cap["action"]
        target = (cap["service"], cap["method"])
        existing = action_map.get(action)
        if existing is None:
            action_map[action] = target
        elif existing != target:
            # Keep the original mapping; record a conflict.
            skipped[action] = f"already maps to {existing}, catalog wanted {target}"

    if state_set is not None:
        for action in state_modifying_actions():
            state_set.add(action)

    if feed_map is not None:
        for action, event in action_to_feed_event().items():
            feed_map.setdefault(action, event)

    return skipped


__all__ = [
    "CAPABILITIES",
    "CATEGORIES",
    "get_by_id",
    "get_by_category",
    "list_categories",
    "as_action_map",
    "state_modifying_actions",
    "action_to_feed_event",
    "install_action_map",
]
