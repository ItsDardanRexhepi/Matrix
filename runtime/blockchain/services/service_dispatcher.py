"""
Service Dispatcher — routes Trinity's natural language intents to the correct
blockchain service. This is what makes all 30 components user-facing.

Trinity's ReAct loop calls tools. This dispatcher registers one mega-tool
'platform_action' that can invoke any of the 30 services based on the action name.
"""

from __future__ import annotations

import asyncio
import json
import logging
import time
from typing import Any

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Action -> (service_name, method_name) mapping
# ---------------------------------------------------------------------------

ACTION_MAP: dict[str, tuple[str, str]] = {
    # --- Contract Conversion (Component 1) ---
    "deploy_contract": ("contract_conversion", "convert"),
    "convert_contract": ("contract_conversion", "convert"),
    "estimate_contract_cost": ("contract_conversion", "estimate_cost"),
    "list_templates": ("contract_conversion", "get_available_templates"),

    # --- DeFi (Component 2) ---
    "create_loan": ("defi", "create_loan"),
    "repay_loan": ("defi", "repay_loan"),
    "get_loan": ("defi", "get_loan"),

    # --- NFT (Component 3) ---
    "mint_nft": ("nft_services", "mint"),
    "create_nft_collection": ("nft_services", "create_collection"),
    "transfer_nft": ("nft_services", "transfer"),
    "list_nft_for_sale": ("nft_services", "list_for_sale"),
    "buy_nft": ("nft_services", "process_sale"),
    "estimate_nft_value": ("nft_services", "estimate_value"),
    "get_nft_rarity": ("nft_services", "get_rarity_score"),
    "set_nft_rights": ("nft_services", "set_rights"),
    "check_nft_rights": ("nft_services", "check_rights"),
    "configure_nft_royalty": ("nft_services", "configure_royalty"),

    # --- RWA Tokenization (Component 4) ---
    "tokenize_asset": ("rwa_tokenization", "tokenize_asset"),
    "transfer_rwa_ownership": ("rwa_tokenization", "transfer_ownership"),
    "get_rwa_asset": ("rwa_tokenization", "get_asset"),

    # --- DID Identity (Component 5) ---
    "create_did": ("did_identity", "create_did"),
    "resolve_did": ("did_identity", "resolve_did"),
    "update_did": ("did_identity", "update_did"),
    "deactivate_did": ("did_identity", "deactivate_did"),

    # --- DAO Management (Component 6) ---
    "create_dao": ("dao_management", "create_dao"),
    "get_dao": ("dao_management", "get_dao"),
    "join_dao": ("dao_management", "join_dao"),
    "leave_dao": ("dao_management", "leave_dao"),

    # --- Stablecoin (Component 7) ---
    "transfer_stablecoin": ("stablecoin", "transfer"),
    "get_stablecoin_balance": ("stablecoin", "get_balance"),
    "get_stablecoin_fee": ("stablecoin", "get_fee"),

    # --- Attestation (Component 8) ---
    "create_attestation": ("attestation", "attest"),
    "verify_attestation": ("attestation", "verify"),
    "revoke_attestation": ("attestation", "revoke"),
    "query_attestations": ("attestation", "query"),
    "batch_attest": ("attestation", "batch_attest"),

    # --- Agent Identity (Component 9) ---
    "register_agent": ("agent_identity", "register_agent"),
    "get_agent": ("agent_identity", "get_agent"),
    "update_agent": ("agent_identity", "update_agent"),
    "deregister_agent": ("agent_identity", "deregister_agent"),
    "list_agents": ("agent_identity", "list_agents"),

    # --- x402 Payments (Component 10) ---
    "create_payment": ("x402_payments", "create_payment"),
    "authorize_payment": ("x402_payments", "authorize_payment"),
    "complete_payment": ("x402_payments", "complete_payment"),
    "refund_payment": ("x402_payments", "refund_payment"),
    "get_payment": ("x402_payments", "get_payment"),
    "list_payments": ("x402_payments", "list_payments"),

    # --- Oracle Gateway (Component 11) ---
    "oracle_request": ("oracle_gateway", "request"),
    "get_price": ("oracle_gateway", "request"),

    # --- Supply Chain (Component 12) ---
    "register_product": ("supply_chain", "register_product"),
    "update_product_status": ("supply_chain", "update_status"),
    "track_product": ("supply_chain", "track"),
    "verify_product": ("supply_chain", "verify"),
    "transfer_custody": ("supply_chain", "transfer_custody"),

    # --- Insurance (Component 13) ---
    "create_insurance": ("insurance", "create_policy"),
    "file_insurance_claim": ("insurance", "file_claim"),
    "get_insurance_policy": ("insurance", "get_policy"),
    "cancel_insurance": ("insurance", "cancel_policy"),

    # --- Gaming (Component 14) ---
    "register_game": ("gaming", "register_game"),
    "get_game": ("gaming", "get_game"),
    "mint_game_asset": ("gaming", "mint_game_asset"),
    "transfer_game_asset": ("gaming", "transfer_asset"),
    "approve_game": ("gaming", "approve_game"),

    # --- IP & Royalties (Component 15) ---
    "register_ip": ("ip_royalties", "register_ip"),
    "get_ip": ("ip_royalties", "get_ip"),
    "transfer_ip": ("ip_royalties", "transfer_ip"),
    "license_ip": ("ip_royalties", "license_ip"),

    # --- Staking (Component 16) ---
    "stake": ("staking", "stake"),
    "unstake": ("staking", "unstake"),
    "claim_staking_rewards": ("staking", "claim_rewards"),
    "get_staking_position": ("staking", "get_position"),

    # --- Cross-Border Payments (Component 17) ---
    "send_payment": ("cross_border", "send_payment"),
    "get_payment_quote": ("cross_border", "get_quote"),
    "get_cross_border_payment": ("cross_border", "get_payment"),
    "list_cross_border_payments": ("cross_border", "list_payments"),

    # --- Securities Exchange (Component 18) ---
    "create_security": ("securities_exchange", "create_security"),
    "list_security": ("securities_exchange", "list_security"),
    "buy_security": ("securities_exchange", "buy"),
    "sell_security": ("securities_exchange", "sell"),
    "get_security": ("securities_exchange", "get_security"),

    # --- Governance (Component 19) ---
    "create_proposal": ("governance", "create_proposal"),
    "vote": ("governance", "vote"),
    "get_proposal": ("governance", "get_proposal"),
    "finalize_proposal": ("governance", "finalize"),
    "list_proposals": ("governance", "list_proposals"),

    # --- Dashboard (Component 20) ---
    "get_dashboard": ("dashboard", "get_overview"),
    "get_activity": ("dashboard", "get_activity"),
    "get_component_status": ("dashboard", "get_component_status"),
    "get_platform_stats": ("dashboard", "get_platform_stats"),

    # --- DEX (Component 21) ---
    "swap_tokens": ("dex", "swap"),
    "get_swap_quote": ("dex", "get_quote"),
    "add_liquidity": ("dex", "add_liquidity"),
    "remove_liquidity": ("dex", "remove_liquidity"),
    "get_dex_positions": ("dex", "get_positions"),

    # --- Fundraising (Component 22) ---
    "create_campaign": ("fundraising", "create_campaign"),
    "contribute_to_campaign": ("fundraising", "contribute"),
    "get_campaign": ("fundraising", "get_campaign"),
    "list_campaigns": ("fundraising", "list_campaigns"),
    "release_milestone_funds": ("fundraising", "release_milestone_funds"),
    "trigger_refunds": ("fundraising", "trigger_refunds"),

    # --- Loyalty (Component 23) ---
    "earn_loyalty": ("loyalty", "earn_points"),
    "redeem_loyalty": ("loyalty", "redeem_points"),
    "get_loyalty_balance": ("loyalty", "get_balance"),
    "get_loyalty_tier": ("loyalty", "get_tier"),

    # --- Marketplace (Component 24) ---
    "list_marketplace": ("marketplace", "list_item"),
    "buy_marketplace": ("marketplace", "buy_item"),
    "cancel_listing": ("marketplace", "cancel_listing"),
    "search_marketplace": ("marketplace", "search"),
    "get_listing": ("marketplace", "get_listing"),

    # --- Cashback (Component 25) ---
    "track_spending": ("cashback", "track_spending"),
    "get_cashback_balance": ("cashback", "get_cashback_balance"),
    "claim_cashback": ("cashback", "claim_cashback"),
    "get_spending_summary": ("cashback", "get_spending_summary"),

    # --- Brand Rewards (Component 26) ---
    "create_brand_campaign": ("brand_rewards", "create_campaign"),
    "distribute_brand_reward": ("brand_rewards", "distribute_reward"),
    "get_brand_campaign": ("brand_rewards", "get_campaign"),
    "list_brand_campaigns": ("brand_rewards", "list_campaigns"),

    # --- Subscriptions (Component 27) ---
    "create_subscription_plan": ("subscriptions", "create_plan"),
    "subscribe": ("subscriptions", "subscribe"),
    "cancel_subscription": ("subscriptions", "cancel"),
    "get_subscription": ("subscriptions", "get_subscription"),

    # --- Social (Component 28) ---
    "create_social_profile": ("social", "create_profile"),
    "update_social_profile": ("social", "update_profile"),
    "get_social_profile": ("social", "get_profile"),
    "send_message": ("social", "share_proof"),
    "get_social_feed": ("social", "get_feed"),

    # --- Privacy (Component 29) ---
    "request_deletion": ("privacy", "request_deletion"),
    "get_privacy_commitment": ("privacy", "get_privacy_commitment"),
    "check_privacy_dependencies": ("privacy", "check_dependencies"),
    "get_deletion_status": ("privacy", "get_deletion_status"),
    "execute_deletion": ("privacy", "execute_pending_deletion"),

    # --- Dispute Resolution (Component 30) ---
    "file_dispute": ("dispute_resolution", "file_dispute"),
    "submit_dispute_evidence": ("dispute_resolution", "submit_evidence"),
    "get_dispute": ("dispute_resolution", "get_dispute"),
    "resolve_dispute": ("dispute_resolution", "resolve"),
    "appeal_dispute": ("dispute_resolution", "appeal"),

    # ── DeFi Expanded ────────────────────────────────────────────
    "flash_loan": ("defi", "flash_loan"),
    "yield_optimize": ("defi", "yield_optimize"),
    "liquidity_provide": ("defi", "liquidity_provide"),
    "liquidity_remove": ("defi", "liquidity_remove"),
    "perp_trade": ("defi", "perp_trade"),
    "options_trade": ("defi", "options_trade"),
    "synthetic_asset": ("defi", "synthetic_asset"),
    "vault_deposit": ("defi", "vault_deposit"),
    "cross_chain_bridge": ("cross_border", "bridge_transfer"),
    "leverage_position": ("defi", "leverage_position"),
    "collateral_manage": ("defi", "collateral_manage"),
    # ── NFT Expanded ─────────────────────────────────────────────
    "nft_fractionalize": ("nft_services", "fractionalize"),
    "nft_rent": ("nft_services", "rent"),
    "nft_dynamic_update": ("nft_services", "dynamic_update"),
    "nft_batch_mint": ("nft_services", "batch_mint"),
    "nft_royalty_claim": ("nft_services", "royalty_claim"),
    "nft_bridge": ("nft_services", "bridge_nft"),
    # ── Identity Expanded ────────────────────────────────────────
    "did_create": ("did_identity", "create_did"),
    "credential_issue": ("did_identity", "issue_credential"),
    "credential_verify": ("did_identity", "verify_credential"),
    "selective_disclose": ("did_identity", "selective_disclose"),
    "reputation_query": ("did_identity", "query_reputation"),
    "soulbound_mint": ("nft_services", "mint_soulbound"),
    # ── Governance Expanded ──────────────────────────────────────
    "timelock_queue": ("governance", "queue_timelock"),
    "multisig_propose": ("governance", "propose_multisig"),
    "multisig_approve": ("governance", "approve_multisig"),
    "snapshot_vote": ("governance", "snapshot_vote"),
    "treasury_transfer": ("dao_management", "treasury_transfer"),
    "parameter_change": ("governance", "parameter_change"),
    # ── RWA Expanded ─────────────────────────────────────────────
    "rwa_tokenize": ("rwa_tokenization", "tokenize_asset"),
    "rwa_fractional_buy": ("rwa_tokenization", "fractional_buy"),
    "rwa_income_claim": ("rwa_tokenization", "claim_income"),
    "rwa_verify": ("rwa_tokenization", "verify_provenance"),
    # ── Payments Expanded ────────────────────────────────────────
    "stream_payment": ("x402_payments", "create_stream"),
    "recurring_create": ("x402_payments", "create_recurring"),
    "escrow_milestone": ("x402_payments", "create_milestone_escrow"),
    "payment_split": ("x402_payments", "split_payment"),
    "cross_border_remit": ("cross_border", "remit"),
    "invoice_factor": ("x402_payments", "factor_invoice"),
    "payroll_run": ("x402_payments", "run_payroll"),
    # ── Privacy ──────────────────────────────────────────────────
    "private_transfer": ("privacy", "private_transfer"),
    "stealth_address": ("privacy", "generate_stealth_address"),
    "zk_proof_generate": ("privacy", "generate_zk_proof"),
    "private_vote": ("privacy", "private_vote"),
    "confidential_compute": ("privacy", "confidential_compute"),
    # ── Social Expanded ──────────────────────────────────────────
    "social_post": ("social", "publish_post"),
    "social_follow": ("social", "follow_wallet"),
    "social_gate": ("social", "create_token_gate"),
    "creator_monetize": ("social", "setup_monetization"),
    "community_create": ("social", "create_community"),
    "message_encrypt": ("social", "send_encrypted_message"),
    # ── Gaming Expanded ──────────────────────────────────────────
    "game_asset_mint": ("gaming", "mint_game_asset"),
    "tournament_enter": ("gaming", "enter_tournament"),
    "game_item_trade": ("gaming", "trade_item"),
    "achievement_attest": ("gaming", "attest_achievement"),
    # ── Prediction Markets ───────────────────────────────────────
    "market_create": ("gaming", "create_prediction_market"),
    "market_bet": ("gaming", "place_prediction_bet"),
    "market_resolve": ("gaming", "resolve_market"),
    "market_query": ("gaming", "query_market"),
    # ── Supply Chain Expanded ────────────────────────────────────
    "provenance_log": ("supply_chain", "log_event"),
    "batch_track": ("supply_chain", "track_batch"),
    "authenticity_verify": ("supply_chain", "verify_authenticity"),
    "custody_transfer": ("supply_chain", "transfer_custody"),
    # ── Insurance Expanded ───────────────────────────────────────
    "parametric_policy": ("insurance", "create_parametric_policy"),
    "claim_auto_settle": ("insurance", "auto_settle_claim"),
    "cover_renew": ("insurance", "renew_coverage"),
    "risk_assess": ("insurance", "assess_risk"),
    # ── Compute and Storage ──────────────────────────────────────
    "decentralized_store": ("privacy", "decentralized_store"),
    "compute_job_submit": ("privacy", "submit_compute_job"),
    "ipfs_pin": ("privacy", "pin_to_ipfs"),
    "arweave_store": ("privacy", "store_on_arweave"),
    # ── AI Capabilities ──────────────────────────────────────────
    "ai_agent_register": ("agent_identity", "register_agent"),
    "ai_model_trade": ("agent_identity", "trade_model_access"),
    "ai_inference_verify": ("agent_identity", "verify_inference"),
    "training_data_sell": ("agent_identity", "sell_training_data"),
    # ── Energy and Sustainability ────────────────────────────────
    "carbon_credit_buy": ("fundraising", "buy_carbon_credit"),
    "carbon_credit_retire": ("fundraising", "retire_carbon_credit"),
    "renewable_cert_buy": ("fundraising", "buy_renewable_cert"),
    "green_bond_invest": ("fundraising", "invest_green_bond"),
    # ── Legal ────────────────────────────────────────────────────
    "ip_license_grant": ("ip_royalties", "grant_license"),
    "ip_license_verify": ("ip_royalties", "verify_license"),
    "agreement_execute": ("ip_royalties", "execute_agreement"),
    "dispute_file": ("dispute_resolution", "file_dispute"),
    "arbitration_request": ("dispute_resolution", "request_arbitration"),
}

# Actions that modify state and should be attested via EAS
_STATE_MODIFYING_ACTIONS: frozenset[str] = frozenset({
    "deploy_contract", "convert_contract", "create_loan", "repay_loan",
    "mint_nft", "create_nft_collection", "transfer_nft", "list_nft_for_sale",
    "buy_nft", "set_nft_rights", "configure_nft_royalty",
    "tokenize_asset", "transfer_rwa_ownership",
    "create_did", "update_did", "deactivate_did",
    "create_dao", "join_dao", "leave_dao",
    "transfer_stablecoin",
    "create_attestation", "revoke_attestation", "batch_attest",
    "register_agent", "update_agent", "deregister_agent",
    "create_payment", "authorize_payment", "complete_payment", "refund_payment",
    "register_product", "update_product_status", "transfer_custody",
    "create_insurance", "file_insurance_claim", "cancel_insurance",
    "register_game", "mint_game_asset", "transfer_game_asset", "approve_game",
    "register_ip", "transfer_ip", "license_ip",
    "stake", "unstake", "claim_staking_rewards",
    "send_payment",
    "create_security", "list_security", "buy_security", "sell_security",
    "create_proposal", "vote", "finalize_proposal",
    "swap_tokens", "add_liquidity", "remove_liquidity",
    "create_campaign", "contribute_to_campaign", "release_milestone_funds",
    "trigger_refunds",
    "earn_loyalty", "redeem_loyalty",
    "list_marketplace", "buy_marketplace", "cancel_listing",
    "track_spending", "claim_cashback",
    "create_brand_campaign", "distribute_brand_reward",
    "create_subscription_plan", "subscribe", "cancel_subscription",
    "create_social_profile", "update_social_profile", "send_message",
    "request_deletion", "execute_deletion",
    "file_dispute", "submit_dispute_evidence", "resolve_dispute", "appeal_dispute",
    # ── Expanded state-modifying actions ─────────────────────────
    "flash_loan", "yield_optimize", "liquidity_provide", "liquidity_remove",
    "perp_trade", "options_trade", "synthetic_asset", "vault_deposit",
    "cross_chain_bridge", "leverage_position", "collateral_manage",
    "nft_fractionalize", "nft_rent", "nft_dynamic_update", "nft_batch_mint",
    "nft_royalty_claim", "nft_bridge", "did_create", "credential_issue",
    "soulbound_mint", "timelock_queue", "multisig_propose", "multisig_approve",
    "snapshot_vote", "treasury_transfer", "parameter_change",
    "rwa_tokenize", "rwa_fractional_buy", "rwa_income_claim",
    "stream_payment", "recurring_create", "escrow_milestone", "payment_split",
    "cross_border_remit", "invoice_factor", "payroll_run",
    "private_transfer", "stealth_address", "zk_proof_generate", "private_vote",
    "confidential_compute", "social_post", "social_gate", "creator_monetize",
    "community_create", "message_encrypt",
    "game_asset_mint", "tournament_enter", "game_item_trade", "achievement_attest",
    "market_create", "market_bet", "market_resolve",
    "provenance_log", "batch_track", "custody_transfer",
    "parametric_policy", "claim_auto_settle", "cover_renew",
    "decentralized_store", "compute_job_submit", "ipfs_pin", "arweave_store",
    "ai_agent_register", "ai_model_trade", "training_data_sell",
    "carbon_credit_buy", "carbon_credit_retire", "renewable_cert_buy", "green_bond_invest",
    "ip_license_grant", "agreement_execute", "dispute_file", "arbitration_request",
})

ACTION_TO_FEED_EVENT: dict[str, str] = {
    # Existing actions
    "deploy_contract": "contract_deployed",
    "convert_contract": "contract_converted",
    "create_loan": "loan_created",
    "repay_loan": "loan_repaid",
    "mint_nft": "nft_minted",
    "list_nft_for_sale": "nft_listed",
    "buy_nft": "nft_purchased",
    "create_proposal": "proposal_created",
    "cast_vote": "vote_cast",
    "stake": "tokens_staked",
    "create_dao": "dao_created",
    # New expanded actions
    "yield_optimize": "yield_deposited",
    "flash_loan": "flash_loan_executed",
    "cross_chain_bridge": "bridge_completed",
    "liquidity_provide": "liquidity_added",
    "vault_deposit": "vault_deposited",
    "perp_trade": "perp_trade_executed",
    "nft_fractionalize": "nft_fractionalized",
    "nft_batch_mint": "nft_batch_minted",
    "nft_bridge": "nft_bridged",
    "rwa_tokenize": "rwa_tokenized",
    "rwa_fractional_buy": "rwa_purchased",
    "did_create": "did_created",
    "credential_issue": "credential_issued",
    "soulbound_mint": "soulbound_minted",
    "market_create": "prediction_market_created",
    "market_bet": "prediction_bet_placed",
    "market_resolve": "prediction_market_resolved",
    "carbon_credit_buy": "carbon_credit_purchased",
    "carbon_credit_retire": "carbon_credit_retired",
    "stream_payment": "payment_streamed",
    "recurring_create": "recurring_payment_created",
    "escrow_milestone": "escrow_created",
    "social_post": "social_post_published",
    "community_create": "community_created",
    "ai_agent_register": "ai_agent_registered",
    "decentralized_store": "file_stored",
    "ipfs_pin": "ipfs_content_pinned",
    "arweave_store": "arweave_content_stored",
    "game_asset_mint": "game_asset_minted",
    "tournament_enter": "tournament_entered",
    "achievement_attest": "achievement_attested",
    "provenance_log": "provenance_logged",
    "custody_transfer": "custody_transferred",
    "parametric_policy": "insurance_policy_created",
    "claim_auto_settle": "insurance_claim_settled",
    "ip_license_grant": "ip_license_granted",
    "agreement_execute": "agreement_executed",
    "green_bond_invest": "green_bond_invested",
    "renewable_cert_buy": "renewable_cert_purchased",
}


# ---------------------------------------------------------------------------
# Capability catalog install — merges the expanded Web3 capability set into
# ACTION_MAP / _STATE_MODIFYING_ACTIONS / ACTION_TO_FEED_EVENT so Trinity's
# `platform_action` tool automatically exposes every catalogued action.
# Safe: catalog.install_action_map() refuses to overwrite existing mappings.
# ---------------------------------------------------------------------------
try:
    from runtime.capabilities import catalog as _capability_catalog

    # _STATE_MODIFYING_ACTIONS is a frozenset; we must rebuild it.
    _mutable_state = set(_STATE_MODIFYING_ACTIONS)
    _skipped = _capability_catalog.install_action_map(
        ACTION_MAP,
        _mutable_state,
        ACTION_TO_FEED_EVENT,
    )
    _STATE_MODIFYING_ACTIONS = frozenset(_mutable_state)
    if _skipped:
        logger.debug(
            "Capability catalog install skipped %d entries (already mapped): %s",
            len(_skipped), list(_skipped.keys())[:5],
        )
except Exception as _cap_exc:
    logger.warning("Capability catalog merge failed (non-fatal): %s", _cap_exc)


class ServiceDispatcher:
    """Bridge between Trinity's tool calls and the 30 blockchain services.

    Registers as a single ``platform_action`` tool that the ReAct loop can
    invoke with any of the defined actions. The dispatcher resolves the target
    service via :class:`ServiceRegistry`, calls the appropriate method, and
    optionally attests state-modifying operations via EAS.
    """

    name: str = "platform_action"

    schema: dict[str, Any] = {
        "type": "function",
        "function": {
            "name": "platform_action",
            "description": (
                "Execute a blockchain platform action. Choose the right action "
                "based on what the user wants, then pass the required params.\n\n"

                "SMART CONTRACTS:\n"
                "  convert_contract — Convert a contract between chains. "
                    "params: {source_code, source_lang, target_chain}\n"
                "  deploy_contract — Deploy a contract to a blockchain. "
                    "params: {source_code, source_lang, target_chain}\n"
                "  estimate_contract_cost — Estimate deployment cost. "
                    "params: {source_code, target_chain}\n"
                "  list_templates — Browse available contract templates.\n\n"

                "DEFI & LOANS:\n"
                "  create_loan — Borrow tokens against collateral. "
                    "params: {collateral_token, collateral_amount, borrow_token, borrow_amount}\n"
                "  repay_loan — Repay an outstanding loan. "
                    "params: {loan_id, amount}\n"
                "  get_loan — Check loan details. params: {loan_id}\n\n"

                "NFTs:\n"
                "  mint_nft — Mint a new NFT. "
                    "params: {metadata: {name, description, image}, royalty_bps}\n"
                "  buy_nft — Buy an NFT. params: {token_id, collection}\n"
                "  list_nft_for_sale — List an NFT for sale. "
                    "params: {token_id, price}\n"
                "  create_nft_collection, transfer_nft, estimate_nft_value, "
                    "get_nft_rarity, set_nft_rights, check_nft_rights, "
                    "configure_nft_royalty\n\n"

                "TOKEN SWAPS & DEX:\n"
                "  swap_tokens — Swap one token for another. "
                    "params: {token_in, token_out, amount}\n"
                "  get_swap_quote — Get a swap price quote. "
                    "params: {token_in, token_out, amount}\n"
                "  add_liquidity, remove_liquidity, get_dex_positions\n\n"

                "PAYMENTS & TRANSFERS:\n"
                "  send_payment — Send tokens to someone. "
                    "params: {recipient, amount, currency}\n"
                "  get_payment_quote — Get a cross-border payment quote. "
                    "params: {amount, currency, destination_country}\n"
                "  create_payment, authorize_payment, complete_payment, "
                    "refund_payment\n\n"

                "STAKING:\n"
                "  stake — Stake tokens in a pool. params: {amount, pool_id}\n"
                "  unstake — Unstake tokens. params: {amount, pool_id}\n"
                "  claim_staking_rewards — Claim earned rewards. "
                    "params: {pool_id}\n"
                "  get_staking_position — Check staking position.\n\n"

                "DASHBOARD & PORTFOLIO:\n"
                "  get_dashboard — Show portfolio overview and balances. "
                    "No params needed.\n"
                "  get_activity — Recent transaction history.\n"
                "  get_platform_stats, get_component_status\n\n"

                "INSURANCE:\n"
                "  create_insurance — Buy insurance. "
                    "params: {policy_type, coverage, premium}\n"
                "  file_insurance_claim — File a claim. "
                    "params: {policy_id, evidence}\n"
                "  get_insurance_policy, cancel_insurance\n\n"

                "GOVERNANCE & DAOs:\n"
                "  create_dao — Create a DAO. params: {name, config}\n"
                "  create_proposal — Submit a proposal. "
                    "params: {title, description, actions}\n"
                "  vote — Vote on a proposal. "
                    "params: {proposal_id, support (bool)}\n"
                "  get_dao, join_dao, leave_dao, get_proposal, "
                    "finalize_proposal, list_proposals\n\n"

                "IDENTITY:\n"
                "  create_did — Create a decentralized identity. "
                    "params: {name, attributes}\n"
                "  resolve_did, update_did, deactivate_did\n\n"

                "IP & ROYALTIES:\n"
                "  register_ip — Register intellectual property. "
                    "params: {title, description, content_hash}\n"
                "  get_ip, transfer_ip, license_ip\n\n"

                "ASSET TOKENIZATION:\n"
                "  tokenize_asset — Tokenize a real-world asset. "
                    "params: {asset_type, details}\n"
                "  transfer_rwa_ownership, get_rwa_asset\n\n"

                "MARKETPLACE:\n"
                "  list_marketplace — List an item for sale. "
                    "params: {item, price}\n"
                "  buy_marketplace — Buy a listing. params: {listing_id}\n"
                "  cancel_listing, search_marketplace, get_listing\n\n"

                "SUPPLY CHAIN:\n"
                "  track_product — Track a product. params: {product_id}\n"
                "  register_product, update_product_status, verify_product, "
                    "transfer_custody\n\n"

                "FUNDRAISING:\n"
                "  create_campaign — Start a fundraising campaign. "
                    "params: {title, goal, milestones}\n"
                "  contribute_to_campaign, get_campaign, list_campaigns, "
                    "release_milestone_funds, trigger_refunds\n\n"

                "SUBSCRIPTIONS:\n"
                "  subscribe — Subscribe to a plan. params: {plan_id}\n"
                "  create_subscription_plan, cancel_subscription, "
                    "get_subscription\n\n"

                "OTHER SERVICES: stablecoins (transfer_stablecoin, "
                "get_stablecoin_balance), attestations (create_attestation, "
                "verify_attestation), agent identity (register_agent, "
                "get_agent), oracle (get_price), gaming (register_game, "
                "mint_game_asset), securities (create_security, buy_security, "
                "sell_security), loyalty (earn_loyalty, redeem_loyalty), "
                "cashback (track_spending, claim_cashback), brand rewards "
                "(create_brand_campaign), social (create_social_profile), "
                "privacy (request_deletion), disputes (file_dispute, "
                "resolve_dispute)."
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "action": {
                        "type": "string",
                        "enum": sorted(ACTION_MAP.keys()),
                        "description": (
                            "The platform action to execute. See the tool "
                            "description for which action matches the user's "
                            "intent and what params each action needs."
                        ),
                    },
                    "service": {
                        "type": "string",
                        "description": (
                            "Optional service name override. If omitted the "
                            "action name determines the service."
                        ),
                    },
                    "params": {
                        "type": "object",
                        "description": (
                            "Parameters for the action. Each action has its own "
                            "required and optional parameters — see the tool "
                            "description for parameter details per action."
                        ),
                    },
                },
                "required": ["action"],
            },
        },
    }

    def __init__(self, config: dict) -> None:
        self._config = config
        self._registry = None  # lazy
        self._neosafe = None   # lazy
        self._feed_engine = None  # lazy — SocialFeedEngine
        self._platform_wallet: str = (
            config.get("blockchain", {}).get("platform_wallet", "")
        )

    def _get_registry(self):
        """Lazily initialise the ServiceRegistry."""
        if self._registry is None:
            from runtime.blockchain.services.registry import ServiceRegistry
            self._registry = ServiceRegistry(self._config)
            logger.info("ServiceDispatcher: ServiceRegistry initialised.")
        return self._registry

    async def prune_caches(self, grace_seconds: float = 0.0) -> int:
        """Prune caches across every instantiated service. Returns the
        number of cache entries evicted (0 if the registry was never
        touched)."""
        if self._registry is None:
            return 0
        return await self._registry.prune_caches(grace_seconds=grace_seconds)

    def _get_neosafe(self):
        """Lazily initialise the NeoSafe fee router."""
        if self._neosafe is None:
            from runtime.blockchain.services.neosafe import NeoSafeRouter
            self._neosafe = NeoSafeRouter(self._config)
        return self._neosafe

    def attach_feed_engine(self, engine) -> None:
        """Inject the :class:`SocialFeedEngine` so successful
        state-modifying actions are published to the live feed.

        Called once during gateway startup.
        """
        self._feed_engine = engine
        logger.info("ServiceDispatcher: SocialFeedEngine attached.")

    # ------------------------------------------------------------------
    # Main execution entry point
    # ------------------------------------------------------------------

    async def execute(
        self,
        action: str,
        service: str | None = None,
        params: dict | None = None,
    ) -> str:
        """Execute a platform action and return a JSON string result.

        Parameters
        ----------
        action:
            One of the keys in :data:`ACTION_MAP`.
        service:
            Optional service-name override (normally inferred from *action*).
        params:
            Keyword arguments forwarded to the underlying service method.

        Returns
        -------
        str
            JSON-encoded result dict with ``status``, ``action``, ``result``,
            and timing information.
        """
        start = time.time()
        params = params or {}

        # Resolve action -> service + method
        if action not in ACTION_MAP:
            return json.dumps({
                "status": "error",
                "error_category": "not_found",
                "degraded": False,
                "error": f"Unknown action '{action}'",
                "available_actions": sorted(ACTION_MAP.keys()),
            })

        target_service, method_name = ACTION_MAP[action]
        if service:
            target_service = service

        logger.info(
            "Dispatching action=%s -> %s.%s  params=%s",
            action, target_service, method_name, list(params.keys()),
        )

        try:
            registry = self._get_registry()
            try:
                svc_instance = registry.get(target_service)
            except (KeyError, LookupError, AttributeError) as exc:
                # Service is unregistered or its dependencies failed to
                # initialise (e.g. RPC URL missing). Return a degraded
                # response so the caller can fall back gracefully.
                logger.warning(
                    "Service '%s' unavailable: %s — returning degraded response",
                    target_service, exc,
                )
                return json.dumps({
                    "status": "error",
                    "error_category": "service_unavailable",
                    "degraded": True,
                    "service": target_service,
                    "error": (
                        f"Service '{target_service}' is currently unavailable: {exc}"
                    ),
                })

            method = getattr(svc_instance, method_name, None)
            if method is None:
                return json.dumps({
                    "status": "error",
                    "error_category": "not_found",
                    "degraded": False,
                    "error": (
                        f"Service '{target_service}' has no method '{method_name}'"
                    ),
                })

            result = await method(**params)

            # Attest state-modifying actions
            if action in _STATE_MODIFYING_ACTIONS:
                await self._attest_action(action, target_service, params, result)

                # Fire-and-forget: publish to the social feed.
                # Never blocks the response — failures are logged and
                # swallowed inside SocialFeedEngine.ingest().
                if self._feed_engine is not None:
                    _component_id = None
                    try:
                        from extensions import registry as _reg
                        _component_id = _reg.service_to_component(target_service)
                    except Exception:
                        pass
                    _actor = params.get("wallet") or params.get("address") or ""
                    _tx = None
                    if isinstance(result, dict):
                        _tx = result.get("tx_hash") or result.get("transaction_hash")
                    _value = None
                    for _vk in ("amount", "value", "total", "price"):
                        _v = params.get(_vk)
                        if _v is not None:
                            try:
                                _value = float(_v)
                            except (ValueError, TypeError):
                                pass
                            break
                    asyncio.create_task(
                        self._feed_engine.ingest(
                            action=action,
                            actor=_actor,
                            detail={
                                "service": target_service,
                                "params": {
                                    k: v for k, v in params.items()
                                    if k not in ("private_key", "seed_phrase", "mnemonic")
                                },
                            },
                            component=_component_id,
                            tx_hash=_tx,
                            value_usd=_value,
                        )
                    )

            elapsed = round(time.time() - start, 3)
            return json.dumps({
                "status": "ok",
                "action": action,
                "service": target_service,
                "result": self._serialise(result),
                "elapsed_ms": int(elapsed * 1000),
            })

        except TypeError as exc:
            logger.error("Bad params for %s.%s: %s", target_service, method_name, exc)
            return json.dumps({
                "status": "error",
                "error_category": "validation",
                "degraded": False,
                "error": f"Invalid parameters for {action}: {exc}",
            })
        except NotImplementedError as exc:
            logger.warning("Action %s not implemented: %s", action, exc)
            return json.dumps({
                "status": "error",
                "error_category": "not_implemented",
                "degraded": True,
                "error": f"Action '{action}' is not implemented in this build: {exc}",
            })
        except Exception as exc:
            logger.exception("Action %s failed", action)
            return json.dumps({
                "status": "error",
                "error_category": "service_error",
                "degraded": True,
                "service": target_service,
                "error": f"Action '{action}' failed: {exc}",
            })

    # ------------------------------------------------------------------
    # Internal helpers
    # ------------------------------------------------------------------

    async def _attest_action(
        self,
        action: str,
        service_name: str,
        params: dict,
        result: Any,
    ) -> None:
        """Record an EAS attestation for a state-modifying action."""
        try:
            registry = self._get_registry()
            attestation_svc = registry.get("attestation")
            await attestation_svc.attest(
                schema_name="platform_action",
                data={
                    "action": action,
                    "service": service_name,
                    "params_hash": str(hash(json.dumps(params, sort_keys=True, default=str))),
                    "timestamp": int(time.time()),
                },
                recipient=self._platform_wallet or "0x0",
            )
        except Exception:
            # Attestation failure must not break the primary action
            logger.warning("Attestation failed for action=%s", action, exc_info=True)

    @staticmethod
    def _serialise(obj: Any) -> Any:
        """Best-effort JSON-safe conversion."""
        if isinstance(obj, dict):
            return {k: ServiceDispatcher._serialise(v) for k, v in obj.items()}
        if isinstance(obj, (list, tuple)):
            return [ServiceDispatcher._serialise(v) for v in obj]
        if isinstance(obj, (str, int, float, bool, type(None))):
            return obj
        return str(obj)
