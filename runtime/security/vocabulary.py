"""What each dispatchable action DOES, as one verb — the vocabulary bridge.

An action is named three ways today and the three do not agree. The ReAct seam
(and with it the mobile bridge, the hand-off and the capability-invoke route)
hands the security gate the ``ACTION_MAP`` name itself (``transfer_stablecoin``,
``buy_marketplace``); the ``/api/v1`` funnel hands it the service METHOD name
after five aliases (``gateway/security_gate.py`` ``action_type_for``); the twin
tools hand it the canonical verb from ``runtime/security/action_map.py``. This
table is the first half of making them one: every name ``ServiceDispatcher``
dispatches, mapped to the verb that says what the call does.

Names come from the dispatcher's ``ACTION_MAP`` as it stands after the
capability catalog is installed into it at import — the literal in
``service_dispatcher.py`` plus the rows ``runtime/capabilities/catalog.py``
adds — because that is the set the ``platform_action`` tool offers the model.
An action outside the dispatcher's ``_STATE_MODIFYING_ACTIONS`` maps to
``READ``; every other action maps to a verb describing its effect, shared by
every name that has the same effect (``transfer_nft``, ``transfer_stablecoin``
and ``custody_transfer`` are all ``transfer``). Where the funnel's alias table
already names an action — ``create_payment``, ``send_payment``,
``add_liquidity``, ``remove_liquidity`` — the verb here is the alias's, so the
two tables cannot give one call two names.

This module says what an action does. It does not say what that permits: which
verbs carry which privileges is decided by the separately installed security
core, and by nothing in this repository.

NOTHING CONSULTS THIS TABLE YET. No module outside ``tests/`` imports it, and
``tests/test_privileged_vocabulary_coverage.py`` holds that in two halves: by
reading the source — every ``import`` and ``from`` form, relative ones
resolved; ``import_module``, ``__import__`` or ``pkgutil.resolve_name`` with a
literal name, under an alias too; an attribute or a literal ``getattr``
reached from an imported package, or from a name a plain assignment re-bound
to one; and a string that is ``vocabulary``, ``.vocabulary`` or
``:vocabulary`` alone or contains ``security.vocabulary`` (or ``/`` or ``:``
for the dot), as an import split in two would spell it — and by booting a
gateway and finding the module never loaded. The first half does not see the
module reached through an imported package handed to a call or kept in a
container, or through a name built at run time in pieces that string match
does not spell; the second covers a booted gateway, not every process. The
same file holds the table to covering exactly the dispatchable names and
agreeing with the funnel's aliases. It exists now so the gap it would close
can be measured before anything is changed to close it.
"""

from __future__ import annotations

#: The verb of an action that reads and changes nothing.
READ = "read"

CANONICAL: dict[str, str] = {
    # --- contract_conversion ---
    "convert_contract": "convert",
    "estimate_contract_cost": READ,
    "list_templates": READ,
    # --- defi ---
    "create_loan": "borrow",
    "repay_loan": "repay",
    "get_loan": READ,
    # --- nft_services ---
    "mint_nft": "mint",
    "create_nft_collection": "create",
    "transfer_nft": "transfer",
    "list_nft_for_sale": "list",
    "buy_nft": "buy",
    "estimate_nft_value": READ,
    "get_nft_rarity": READ,
    "set_nft_rights": "grant",
    "check_nft_rights": READ,
    "configure_nft_royalty": "configure",
    # --- rwa_tokenization ---
    "tokenize_asset": "tokenize",
    "transfer_rwa_ownership": "transfer",
    "get_rwa_asset": READ,
    # --- did_identity ---
    "create_did": "create",
    "resolve_did": READ,
    "update_did": "update",
    "deactivate_did": "deactivate",
    # --- dao_management ---
    "create_dao": "create",
    "get_dao": READ,
    "join_dao": "join",
    "leave_dao": "leave",
    # --- stablecoin ---
    "transfer_stablecoin": "transfer",
    "get_stablecoin_balance": READ,
    "get_stablecoin_fee": READ,
    # --- attestation ---
    "create_attestation": "attest",
    "verify_attestation": READ,
    "revoke_attestation": "revoke",
    "batch_attest": "attest",
    # --- agent_identity ---
    "register_agent": "register",
    "get_agent": READ,
    "update_agent": "update",
    "deregister_agent": "deregister",
    "list_agents": READ,
    # --- x402_payments ---
    "create_payment": "payment",       # the funnel's alias for create_payment
    "complete_payment": "pay",
    "get_payment": READ,
    "list_payments": READ,
    # --- oracle_gateway ---
    "oracle_request": READ,
    "get_price": READ,
    # --- supply_chain ---
    "register_product": "register",
    "update_product_status": "update",
    "track_product": READ,
    "verify_product": READ,
    "transfer_custody": "transfer",
    # --- insurance ---
    "create_insurance": "buy",
    "file_insurance_claim": "claim",
    "get_insurance_policy": READ,
    "cancel_insurance": "cancel",
    # --- gaming ---
    "register_game": "register",
    "get_game": READ,
    "mint_game_asset": "mint",
    "transfer_game_asset": "transfer",
    "approve_game": "approve",
    # --- ip_royalties ---
    "register_ip": "register",
    "get_ip": READ,
    "transfer_ip": "transfer",
    "license_ip": "license",
    # --- staking ---
    "stake": "stake",
    "unstake": "unstake",
    "claim_staking_rewards": "claim",
    "get_staking_position": READ,
    # --- cross_border ---
    "send_payment": "send",            # the funnel's alias for send_payment
    "get_payment_quote": READ,
    "get_cross_border_payment": READ,
    "list_cross_border_payments": READ,
    # --- securities_exchange ---
    "create_security": "create",
    "list_security": "list",
    "buy_security": "buy",
    "sell_security": "sell",
    "get_security": READ,
    # --- governance ---
    "create_proposal": "propose",
    "vote": "vote",
    "get_proposal": READ,
    "finalize_proposal": "finalize",
    "list_proposals": READ,
    # --- dashboard ---
    "get_dashboard": READ,
    "get_activity": READ,
    "get_component_status": READ,
    "get_platform_stats": READ,
    # --- dex ---
    "swap_tokens": "swap",
    "get_swap_quote": READ,
    "add_liquidity": "provide_liquidity",     # the funnel's alias for add_liquidity
    "remove_liquidity": "remove_liquidity",   # the funnel's alias for remove_liquidity
    "get_dex_positions": READ,
    # --- fundraising ---
    "create_campaign": "create",
    "contribute_to_campaign": "contribute",
    "get_campaign": READ,
    "list_campaigns": READ,
    "release_milestone_funds": "release",
    "trigger_refunds": "refund",
    # --- loyalty ---
    "earn_loyalty": "earn",
    "redeem_loyalty": "redeem",
    "get_loyalty_balance": READ,
    "get_loyalty_tier": READ,
    # --- marketplace ---
    "list_marketplace": "list",
    "buy_marketplace": "buy",
    "cancel_listing": "cancel",
    "search_marketplace": READ,
    "get_listing": READ,
    # --- cashback ---
    "track_spending": "track",
    "get_cashback_balance": READ,
    "claim_cashback": "claim",
    "get_spending_summary": READ,
    # --- brand_rewards ---
    "create_brand_campaign": "create",
    "distribute_brand_reward": "distribute",
    "get_brand_campaign": READ,
    "list_brand_campaigns": READ,
    # --- subscriptions ---
    "create_subscription_plan": "create",
    "subscribe": "subscribe",
    "cancel_subscription": "cancel",
    "get_subscription": READ,
    # --- social ---
    "create_social_profile": "create",
    "update_social_profile": "update",
    "get_social_profile": READ,
    "send_message": "publish",         # dispatches to social.share_proof
    "get_social_feed": READ,
    # --- privacy ---
    "request_deletion": "delete",
    "get_privacy_commitment": READ,
    "check_privacy_dependencies": READ,
    "get_deletion_status": READ,
    # --- dispute_resolution ---
    "file_dispute": "file",
    "submit_dispute_evidence": "submit",
    "get_dispute": READ,
    "resolve_dispute": "resolve",
    "appeal_dispute": "appeal",
    # --- expanded actions (same services) ---
    "cross_chain_bridge": "bridge",
    "nft_fractionalize": "fractionalize",
    "nft_rent": "rent",
    "nft_dynamic_update": "update",
    "nft_batch_mint": "mint",
    "nft_royalty_claim": "claim",
    "nft_bridge": "bridge",
    "did_create": "create",
    "credential_issue": "issue",
    "credential_verify": READ,
    "selective_disclose": "disclose",
    "reputation_query": READ,
    "soulbound_mint": "mint",
    "timelock_queue": "schedule",
    "multisig_propose": "propose",
    "multisig_approve": "approve",
    "snapshot_vote": "vote",
    "parameter_change": "configure",
    "rwa_tokenize": "tokenize",
    "rwa_fractional_buy": "buy",
    "rwa_income_claim": "claim",
    "rwa_verify": READ,
    "cross_border_remit": "send",
    "zk_proof_generate": "generate",
    "social_post": "publish",
    "social_follow": "follow",
    "social_gate": "create",
    "creator_monetize": "configure",
    "community_create": "create",
    "message_encrypt": "message",
    "game_asset_mint": "mint",
    "tournament_enter": "enter",
    "game_item_trade": "trade",
    "achievement_attest": "attest",
    "market_create": "create",
    "market_bet": "bet",
    "market_resolve": "resolve",
    "market_query": READ,
    "provenance_log": "record",
    "batch_track": "track",
    "authenticity_verify": READ,
    "custody_transfer": "transfer",
    "parametric_policy": "buy",
    "claim_auto_settle": "settle",
    "cover_renew": "renew",
    "risk_assess": READ,
    "decentralized_store": "store",
    "compute_job_submit": "submit",
    "ipfs_pin": "store",
    "ai_agent_register": "register",
    "ai_model_trade": "trade",
    "ai_inference_verify": READ,
    "training_data_sell": "sell",
    "carbon_credit_buy": "buy",
    "carbon_credit_retire": "retire",
    "renewable_cert_buy": "buy",
    "green_bond_invest": "buy",
    "ip_license_grant": "license",
    "ip_license_verify": READ,
    "agreement_execute": "execute",
    "dispute_file": "file",
    "arbitration_request": "request",
    # --- installed from the capability catalog ---
    "place_limit_order": "order",
    "cancel_limit_order": "cancel",
    "pyth_pull_price": READ,
    "restake_eigenlayer": "restake",
    "restake_symbiotic": "restake",
    "restake_karak": "restake",
    "delegate_to_operator": "delegate",
    "withdraw_restake": "withdraw",
    "liquid_stake_lido": "stake",
    "liquid_stake_rocketpool": "stake",
    "borrow_against_nft": "borrow",
    "liquidate_nft_loan": "liquidate",
    "breed_nft": "mint",
    "create_tba": "create",
    "execute_as_tba": "execute",
    "start_kyc": "request",
    "check_aml_risk": READ,
    "issue_kyc_credential": "issue",
    "vote_escrow": "lock",
    "quadratic_vote": "vote",
    "submit_retropgf": "submit",
    "place_bribe": "pay",
    "delegate_voting": "delegate",
    "create_lens_profile": "create",
    "publish_cast": "publish",
    "push_subscribe": "subscribe",
    "launch_social_token": "create",
    "launch_creator_coin": "create",
    "mint_sound": "mint",
    "publish_mirror_post": "publish",
    "publish_paragraph_post": "publish",
    "open_channel": "open",
    "route_payment": "pay",
    "close_channel": "close",
    "bridge_token_ccip": "bridge",
    "send_cross_chain_message": "message",
    "bridge_hyperlane": "bridge",
    "bridge_wormhole": "bridge",
    "bridge_axelar": "bridge",
    "bridge_stargate": "bridge",
    "query_remote_chain": READ,
    "mpc_sign": "sign",
    "recover_wallet": "recover",
    "create_session_key": "grant",
    "oracle_price_query": READ,
    "oracle_vrf_request": "request",
    "oracle_weather_query": READ,
    "pyth_pull": READ,
    "redstone_request": READ,
    "api3_query": READ,
    "register_keeper_job": "register",
    "store_filecoin": "store",
    "ceramic_stream_create": "store",
    "orbit_db_write": "store",
    "submit_compute_job": "submit",
    "rent_device": "rent",
    "claim_compute_reward": "claim",
    "create_auction": "create",
    "place_bid": "bid",
    "settle_auction": "settle",
}
