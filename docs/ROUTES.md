# Gateway route table

> **Generated** by `scripts/generate_route_table.py` — do not edit by hand.
> Run `python scripts/generate_route_table.py` after adding a route;
> CI runs it with `--check` and fails if this file is stale.

**191 routes.** A **public** route requires no API key (its own auth applies — e.g. a signed JWS, SIWE, or per-IP caps).

| Method | Path | Handler | Source | Public |
|---|---|---|---|---|
| GET | `/` | `handle_landing` | server.py:2066 | ✅ |
| POST | `/a2a/jobs` | `handle_a2a_submit_job` | server.py:2100 |  |
| GET | `/a2a/jobs/{job_id}` | `handle_a2a_get_job` | server.py:2101 |  |
| GET | `/a2a/services` | `handle_a2a_services` | server.py:2099 | ✅ |
| POST | `/api/v1/agent/register` | `_handle_agent_register` | service_routes.py:271 |  |
| POST | `/api/v1/ai/agent/register` | `_handle_ai_agent_register` | service_routes.py:366 |  |
| POST | `/api/v1/ai/model/trade` | `_handle_ai_model_trade` | service_routes.py:367 |  |
| GET | `/api/v1/attestation/verify/{uid}` | `_handle_attestation_verify` | service_routes.py:283 |  |
| DELETE | `/api/v1/auth/account` | `handle_account_delete` | server.py:2054 | ✅ |
| POST | `/api/v1/auth/apple` | `handle_apple_auth` | server.py:2053 | ✅ |
| POST | `/api/v1/batch` | `_handle_batch` | service_routes.py:389 |  |
| POST | `/api/v1/brand/campaign/create` | `_handle_brand_campaign_create` | service_routes.py:250 |  |
| GET | `/api/v1/capabilities` | `_handle_capabilities_list` | service_routes.py:383 |  |
| GET | `/api/v1/capabilities/categories` | `_handle_capabilities_categories` | service_routes.py:384 |  |
| GET | `/api/v1/capabilities/{capability_id}` | `_handle_capability_detail` | service_routes.py:385 |  |
| POST | `/api/v1/capabilities/{capability_id}/invoke` | `_handle_capability_invoke` | service_routes.py:386 |  |
| POST | `/api/v1/cashback/track` | `_handle_cashback_track` | service_routes.py:247 |  |
| POST | `/api/v1/compute/arweave/store` | `_handle_arweave_store` | service_routes.py:328 |  |
| POST | `/api/v1/compute/ipfs/pin` | `_handle_ipfs_pin` | service_routes.py:327 |  |
| POST | `/api/v1/compute/store` | `_handle_decentralized_store` | service_routes.py:326 |  |
| POST | `/api/v1/contracts/convert` | `_handle_contract_convert` | service_routes.py:174 |  |
| POST | `/api/v1/contracts/deploy` | `_handle_contract_deploy` | service_routes.py:175 |  |
| POST | `/api/v1/crossborder/send` | `_handle_crossborder_send` | service_routes.py:256 |  |
| POST | `/api/v1/dao/create` | `_handle_dao_create` | service_routes.py:201 |  |
| GET | `/api/v1/dashboard/{address}` | `_handle_dashboard` | service_routes.py:277 |  |
| POST | `/api/v1/defi/bridge/execute` | `_handle_bridge_execute` | service_routes.py:290 |  |
| POST | `/api/v1/defi/bridge/quote` | `_handle_bridge_quote` | service_routes.py:289 |  |
| POST | `/api/v1/defi/collateral/manage` | `_handle_collateral_manage` | service_routes.py:295 |  |
| POST | `/api/v1/defi/flash-loan/execute` | `_handle_flash_loan` | service_routes.py:291 |  |
| POST | `/api/v1/defi/liquidity/provide` | `_handle_liquidity_provide` | service_routes.py:293 |  |
| POST | `/api/v1/defi/loan/create` | `_handle_defi_loan_create` | service_routes.py:178 |  |
| POST | `/api/v1/defi/loan/repay` | `_handle_defi_loan_repay` | service_routes.py:179 |  |
| POST | `/api/v1/defi/perp/trade` | `_handle_perp_trade` | service_routes.py:294 |  |
| POST | `/api/v1/defi/swap/execute` | `_handle_swap_execute` | service_routes.py:288 |  |
| POST | `/api/v1/defi/swap/route` | `_handle_swap_route` | service_routes.py:287 |  |
| POST | `/api/v1/defi/vault/deposit` | `_handle_vault_deposit` | service_routes.py:292 |  |
| POST | `/api/v1/defi/yield/optimize` | `_handle_yield_optimize` | service_routes.py:286 |  |
| POST | `/api/v1/dex/liquidity/add` | `_handle_dex_add_liquidity` | service_routes.py:212 |  |
| POST | `/api/v1/dex/swap` | `_handle_dex_swap` | service_routes.py:211 |  |
| POST | `/api/v1/dispute/claim` | `_handle_dispute_claim` | service_routes.py:229 |  |
| POST | `/api/v1/dispute/file` | `_handle_dispute_file` | service_routes.py:227 |  |
| POST | `/api/v1/dispute/vote` | `_handle_dispute_vote` | service_routes.py:228 |  |
| POST | `/api/v1/energy/carbon/buy` | `_handle_carbon_buy` | service_routes.py:340 |  |
| GET | `/api/v1/energy/carbon/prices` | `_handle_carbon_prices` | service_routes.py:342 |  |
| POST | `/api/v1/energy/carbon/retire` | `_handle_carbon_retire` | service_routes.py:341 |  |
| GET | `/api/v1/events/stream` | `_handle_event_stream` | service_routes.py:390 | ✅ |
| POST | `/api/v1/fundraising/campaign/create` | `_handle_fundraising_create` | service_routes.py:236 |  |
| POST | `/api/v1/fundraising/contribute` | `_handle_fundraising_contribute` | service_routes.py:237 |  |
| POST | `/api/v1/gaming/register` | `_handle_gaming_register` | service_routes.py:265 |  |
| POST | `/api/v1/governance/multisig/approve` | `_handle_multisig_approve` | service_routes.py:346 |  |
| POST | `/api/v1/governance/multisig/propose` | `_handle_multisig_propose` | service_routes.py:345 |  |
| POST | `/api/v1/governance/proposal/create` | `_handle_governance_create` | service_routes.py:223 |  |
| POST | `/api/v1/governance/snapshot/vote` | `_handle_snapshot_vote` | service_routes.py:347 |  |
| POST | `/api/v1/governance/treasury/transfer` | `_handle_treasury_transfer` | service_routes.py:348 |  |
| POST | `/api/v1/governance/vote` | `_handle_governance_vote` | service_routes.py:224 |  |
| POST | `/api/v1/iap/asn` | `handle_iap_asn` | server.py:2056 | ✅ |
| POST | `/api/v1/iap/verify` | `handle_iap_verify` | server.py:2055 | ✅ |
| POST | `/api/v1/identity/create` | `_handle_did_create` | service_routes.py:198 |  |
| POST | `/api/v1/identity/credential/issue` | `_handle_credential_issue` | service_routes.py:306 |  |
| POST | `/api/v1/identity/credential/verify` | `_handle_credential_verify` | service_routes.py:307 |  |
| POST | `/api/v1/identity/did/create` | `_handle_identity_did_create` | service_routes.py:305 |  |
| POST | `/api/v1/identity/soulbound/mint` | `_handle_soulbound_mint` | service_routes.py:309 |  |
| POST | `/api/v1/identity/zk-proof/generate` | `_handle_zk_proof` | service_routes.py:308 |  |
| POST | `/api/v1/insurance/claim` | `_handle_insurance_claim` | service_routes.py:216 |  |
| POST | `/api/v1/insurance/claim/settle` | `_handle_claim_settle` | service_routes.py:376 |  |
| POST | `/api/v1/insurance/parametric/create` | `_handle_parametric_policy` | service_routes.py:375 |  |
| POST | `/api/v1/insurance/policy/create` | `_handle_insurance_create` | service_routes.py:215 |  |
| POST | `/api/v1/intent/execute` | `_handle_intent_execute` | service_routes.py:357 |  |
| POST | `/api/v1/intent/resolve` | `_handle_intent_resolve` | service_routes.py:356 |  |
| GET | `/api/v1/intent/summary/{plan_id}` | `_handle_intent_summary` | service_routes.py:358 |  |
| POST | `/api/v1/ip/register` | `_handle_ip_register` | service_routes.py:268 |  |
| POST | `/api/v1/legal/agreement/execute` | `_handle_agreement_execute` | service_routes.py:362 |  |
| POST | `/api/v1/legal/dispute/file` | `_handle_legal_dispute_file` | service_routes.py:363 |  |
| POST | `/api/v1/legal/license/grant` | `_handle_license_grant` | service_routes.py:361 |  |
| POST | `/api/v1/loyalty/earn` | `_handle_loyalty_earn` | service_routes.py:243 |  |
| POST | `/api/v1/loyalty/redeem` | `_handle_loyalty_redeem` | service_routes.py:244 |  |
| POST | `/api/v1/marketplace/buy` | `_handle_marketplace_buy` | service_routes.py:220 |  |
| POST | `/api/v1/marketplace/list` | `_handle_marketplace_list` | service_routes.py:219 |  |
| POST | `/api/v1/nft/batch-mint` | `_handle_nft_batch_mint` | service_routes.py:300 |  |
| POST | `/api/v1/nft/bridge` | `_handle_nft_bridge` | service_routes.py:302 |  |
| POST | `/api/v1/nft/collection/create` | `_handle_nft_collection_create` | service_routes.py:192 |  |
| POST | `/api/v1/nft/fractionalize` | `_handle_nft_fractionalize` | service_routes.py:298 |  |
| POST | `/api/v1/nft/mint` | `_handle_nft_mint` | service_routes.py:191 |  |
| POST | `/api/v1/nft/rent` | `_handle_nft_rent` | service_routes.py:299 |  |
| POST | `/api/v1/nft/royalty/claim` | `_handle_nft_royalty_claim` | service_routes.py:301 |  |
| GET | `/api/v1/oracle/price/{pair}` | `_handle_oracle_price` | service_routes.py:280 |  |
| POST | `/api/v1/paymaster/sign` | `_handle_paymaster_sign` | service_routes.py:185 |  |
| POST | `/api/v1/payments/create` | `_handle_payment_create` | service_routes.py:274 |  |
| POST | `/api/v1/payments/escrow/milestone` | `_handle_escrow_milestone` | service_routes.py:321 |  |
| POST | `/api/v1/payments/payroll` | `_handle_payroll_run` | service_routes.py:323 |  |
| POST | `/api/v1/payments/recurring/create` | `_handle_recurring_create` | service_routes.py:320 |  |
| POST | `/api/v1/payments/split` | `_handle_payment_split` | service_routes.py:322 |  |
| POST | `/api/v1/payments/stream/create` | `_handle_stream_create` | service_routes.py:319 |  |
| GET | `/api/v1/portfolio/complete/{wallet}` | `_handle_portfolio_complete` | service_routes.py:351 |  |
| GET | `/api/v1/portfolio/history/{wallet}` | `_handle_portfolio_history` | service_routes.py:353 |  |
| GET | `/api/v1/portfolio/positions/{wallet}` | `_handle_portfolio_positions` | service_routes.py:352 |  |
| POST | `/api/v1/prediction/market/bet` | `_handle_market_bet` | service_routes.py:336 |  |
| POST | `/api/v1/prediction/market/create` | `_handle_market_create` | service_routes.py:335 |  |
| GET | `/api/v1/prediction/market/list` | `_handle_market_list` | service_routes.py:337 |  |
| GET | `/api/v1/price/eth-usd` | `_handle_eth_usd_price` | service_routes.py:188 |  |
| POST | `/api/v1/privacy/delete` | `_handle_privacy_delete` | service_routes.py:253 |  |
| POST | `/api/v1/privacy/stealth-address` | `_handle_stealth_address` | service_routes.py:380 |  |
| POST | `/api/v1/privacy/transfer` | `_handle_private_transfer` | service_routes.py:379 |  |
| POST | `/api/v1/rwa/fractional/buy` | `_handle_rwa_fractional_buy` | service_routes.py:331 |  |
| GET | `/api/v1/rwa/listings` | `_handle_rwa_listings` | service_routes.py:332 |  |
| POST | `/api/v1/rwa/tokenize` | `_handle_rwa_tokenize` | service_routes.py:195 |  |
| POST | `/api/v1/securities/create` | `_handle_securities_create` | service_routes.py:259 |  |
| POST | `/api/v1/security/preflight` | `_handle_security_preflight` | service_routes.py:182 |  |
| POST | `/api/v1/social/community/create` | `_handle_community_create` | service_routes.py:315 |  |
| GET | `/api/v1/social/feed/{wallet}` | `_handle_social_feed` | service_routes.py:316 |  |
| POST | `/api/v1/social/gate/create` | `_handle_social_gate` | service_routes.py:314 |  |
| POST | `/api/v1/social/message` | `_handle_social_message` | service_routes.py:232 |  |
| POST | `/api/v1/social/message/send` | `_handle_social_message_send` | service_routes.py:313 |  |
| POST | `/api/v1/social/post` | `_handle_social_post` | service_routes.py:312 |  |
| POST | `/api/v1/social/profile` | `_handle_social_profile` | service_routes.py:233 |  |
| POST | `/api/v1/stablecoin/transfer` | `_handle_stablecoin_transfer` | service_routes.py:204 |  |
| POST | `/api/v1/staking/stake` | `_handle_staking_stake` | service_routes.py:207 |  |
| POST | `/api/v1/staking/unstake` | `_handle_staking_unstake` | service_routes.py:208 |  |
| POST | `/api/v1/subscriptions/subscribe` | `_handle_subscribe` | service_routes.py:240 |  |
| POST | `/api/v1/supply-chain/custody/transfer` | `_handle_custody_transfer` | service_routes.py:372 |  |
| POST | `/api/v1/supply-chain/provenance/log` | `_handle_provenance_log` | service_routes.py:370 |  |
| POST | `/api/v1/supply-chain/register` | `_handle_supply_chain_register` | service_routes.py:262 |  |
| POST | `/api/v1/supply-chain/verify` | `_handle_authenticity_verify` | service_routes.py:371 |  |
| GET | `/audit` | `handle_audit_page` | server.py:2068 | ✅ |
| POST | `/audit/request` | `handle_audit_request` | server.py:2079 |  |
| GET | `/audit/{audit_id}` | `handle_audit_report` | server.py:2080 |  |
| POST | `/auth/nonce` | `handle_auth_nonce` | server.py:2051 | ✅ |
| POST | `/auth/verify` | `handle_auth_verify` | server.py:2052 | ✅ |
| POST | `/badge/issue` | `handle_badge_issue` | server.py:2120 |  |
| GET | `/badge/widget.js` | `handle_badge_widget_js` | server.py:2115 |  |
| GET | `/badge/{badge_id}` | `handle_badge_page` | server.py:2116 |  |
| GET | `/badge/{badge_id}/embed` | `handle_badge_embed` | server.py:2118 |  |
| GET | `/badge/{badge_id}/status` | `handle_badge_status` | server.py:2117 |  |
| GET | `/badges` | `handle_badges_list` | server.py:2119 | ✅ |
| POST | `/bridge/v1/action` | `execute_action` | bridge.py:540 |  |
| POST | `/bridge/v1/chat` | `chat` | bridge.py:537 |  |
| GET | `/bridge/v1/components` | `get_components` | bridge.py:557 |  |
| GET | `/bridge/v1/components/manifest` | `get_components_manifest` | bridge.py:558 |  |
| GET | `/bridge/v1/components/{component_id}` | `get_component` | bridge.py:559 |  |
| GET | `/bridge/v1/config` | `get_config` | bridge.py:550 |  |
| GET | `/bridge/v1/dashboard` | `get_dashboard` | bridge.py:554 |  |
| POST | `/bridge/v1/push/register` | `register_push` | bridge.py:547 |  |
| GET | `/bridge/v1/services` | `get_services` | bridge.py:551 |  |
| POST | `/bridge/v1/session/create` | `create_session` | bridge.py:533 |  |
| POST | `/bridge/v1/session/resume` | `resume_session` | bridge.py:534 |  |
| POST | `/bridge/v1/wallet/link` | `link_wallet` | bridge.py:543 |  |
| GET | `/bridge/v1/wallet/status` | `wallet_status` | bridge.py:544 |  |
| POST | `/certification/start` | `handle_cert_start` | server.py:2125 |  |
| POST | `/certification/submit` | `handle_cert_submit` | server.py:2126 |  |
| GET | `/certification/tracks` | `handle_cert_tracks` | server.py:2124 |  |
| GET | `/certification/{cert_id}` | `handle_cert_verify` | server.py:2127 |  |
| GET | `/chat` | `handle_chat_page` | server.py:2067 | ✅ |
| POST | `/chat` | `handle_chat` | server.py:2044 | ✅ |
| POST | `/chat/stream` | `handle_chat_stream` | server.py:2045 |  |
| GET | `/extensions/registry` | `handle_extensions_registry` | server.py:2075 | ✅ |
| GET | `/extensions/registry/{component_id}` | `handle_extensions_component` | server.py:2076 |  |
| GET | `/glasswing` | `handle_glasswing_page` | server.py:2114 | ✅ |
| GET | `/health` | `handle_health` | server.py:2047 | ✅ |
| GET | `/learn` | `handle_learn_page` | server.py:2123 | ✅ |
| GET | `/marketplace` | `handle_marketplace_page` | server.py:2069 | ✅ |
| GET | `/marketplace/plugins` | `handle_marketplace_list` | server.py:2104 |  |
| POST | `/marketplace/plugins/submit` | `handle_marketplace_submit` | server.py:2107 |  |
| GET | `/marketplace/plugins/{plugin_id}` | `handle_marketplace_plugin` | server.py:2105 |  |
| POST | `/marketplace/plugins/{plugin_id}/purchase` | `handle_marketplace_purchase` | server.py:2106 |  |
| GET | `/marketplace/purchased` | `handle_marketplace_purchased` | server.py:2108 |  |
| POST | `/memory/read` | `handle_memory_read` | server.py:2049 |  |
| POST | `/memory/write` | `handle_memory_write` | server.py:2050 |  |
| GET | `/metrics` | `handle_metrics` | server.py:2062 |  |
| GET | `/metrics/prom` | `handle_metrics_prometheus` | server.py:2063 |  |
| GET | `/privacy` | `handle_privacy_page` | server.py:2071 | ✅ |
| POST | `/security/appattest/attest` | `handle_appattest_attest` | server.py:2061 | ✅ |
| GET | `/security/appattest/challenge` | `handle_appattest_challenge` | server.py:2060 | ✅ |
| POST | `/security/owner/request` | `handle_owner_otp_request` | server.py:2059 |  |
| POST | `/security/phone/request` | `handle_otp_request` | server.py:2057 | ✅ |
| POST | `/security/phone/verify` | `handle_otp_verify` | server.py:2058 | ✅ |
| GET | `/services/conversion` | `handle_conversion_page` | server.py:2070 | ✅ |
| GET | `/social` | `handle_social_feed_page` | server.py:2086 | ✅ |
| GET | `/social/actor/{wallet}` | `handle_social_actor` | server.py:2090 |  |
| GET | `/social/feed` | `handle_social_feed` | server.py:2087 | ✅ |
| GET | `/social/feed/stream` | `handle_social_feed_stream` | server.py:2088 | ✅ |
| POST | `/social/follow` | `handle_social_follow` | server.py:2093 |  |
| POST | `/social/post` | `handle_social_post` | server.py:2083 |  |
| GET | `/social/stats` | `handle_social_stats` | server.py:2091 | ✅ |
| GET | `/social/trending` | `handle_social_trending` | server.py:2089 | ✅ |
| POST | `/social/unfollow` | `handle_social_unfollow` | server.py:2094 |  |
| GET | `/social/{address}/followers` | `handle_social_followers` | server.py:2095 |  |
| GET | `/social/{address}/following` | `handle_social_following` | server.py:2096 |  |
| GET | `/sponsor` | `handle_sponsor_redirect` | server.py:2111 | ✅ |
| GET | `/status` | `handle_status` | server.py:2048 |  |
| GET | `/terms` | `handle_terms_page` | server.py:2072 | ✅ |
| GET | `/ws` | `handle_websocket` | server.py:2046 | ✅ |
