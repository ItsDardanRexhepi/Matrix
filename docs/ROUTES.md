# Gateway route table

> **Generated** by `scripts/generate_route_table.py` — do not edit by hand.
> Run `python scripts/generate_route_table.py` after adding a route;
> CI runs it with `--check` and fails if this file is stale.

**211 routes.** A **public** route requires no API key (its own auth applies — e.g. a signed JWS, SIWE, or per-IP caps).

| Method | Path | Handler | Source | Public |
|---|---|---|---|---|
| GET | `/` | `handle_landing` | server.py:2317 | ✅ |
| POST | `/a2a/jobs` | `handle_a2a_submit_job` | server.py:2351 |  |
| GET | `/a2a/jobs/{job_id}` | `handle_a2a_get_job` | server.py:2352 |  |
| GET | `/a2a/services` | `handle_a2a_services` | server.py:2350 | ✅ |
| POST | `/api/v1/agent/register` | `_handle_agent_register` | service_routes.py:276 |  |
| POST | `/api/v1/ai/agent/register` | `_handle_ai_agent_register` | service_routes.py:371 |  |
| POST | `/api/v1/ai/model/trade` | `_handle_ai_model_trade` | service_routes.py:372 |  |
| GET | `/api/v1/attestation/verify/{uid}` | `_handle_attestation_verify` | service_routes.py:288 |  |
| DELETE | `/api/v1/auth/account` | `handle_account_delete` | server.py:2305 | ✅ |
| POST | `/api/v1/auth/apple` | `handle_apple_auth` | server.py:2304 | ✅ |
| POST | `/api/v1/batch` | `_handle_batch` | service_routes.py:392 |  |
| POST | `/api/v1/brand/campaign/create` | `_handle_brand_campaign_create` | service_routes.py:255 |  |
| GET | `/api/v1/capabilities` | `_handle_capabilities_list` | service_routes.py:386 |  |
| GET | `/api/v1/capabilities/categories` | `_handle_capabilities_categories` | service_routes.py:387 |  |
| GET | `/api/v1/capabilities/{capability_id}` | `_handle_capability_detail` | service_routes.py:388 |  |
| POST | `/api/v1/capabilities/{capability_id}/invoke` | `_handle_capability_invoke` | service_routes.py:389 |  |
| POST | `/api/v1/cashback/track` | `_handle_cashback_track` | service_routes.py:252 |  |
| POST | `/api/v1/compute/arweave/store` | `_handle_arweave_store` | service_routes.py:333 |  |
| POST | `/api/v1/compute/ipfs/pin` | `_handle_ipfs_pin` | service_routes.py:332 |  |
| POST | `/api/v1/compute/store` | `_handle_decentralized_store` | service_routes.py:331 |  |
| POST | `/api/v1/contracts/convert` | `_handle_contract_convert` | service_routes.py:179 |  |
| POST | `/api/v1/contracts/deploy` | `_handle_contract_deploy` | service_routes.py:180 |  |
| POST | `/api/v1/crossborder/send` | `_handle_crossborder_send` | service_routes.py:261 |  |
| POST | `/api/v1/dao/create` | `_handle_dao_create` | service_routes.py:206 |  |
| GET | `/api/v1/dashboard/{address}` | `_handle_dashboard` | service_routes.py:282 |  |
| POST | `/api/v1/defi/bridge/execute` | `_handle_bridge_execute` | service_routes.py:295 |  |
| POST | `/api/v1/defi/bridge/quote` | `_handle_bridge_quote` | service_routes.py:294 |  |
| POST | `/api/v1/defi/collateral/manage` | `_handle_collateral_manage` | service_routes.py:300 |  |
| POST | `/api/v1/defi/flash-loan/execute` | `_handle_flash_loan` | service_routes.py:296 |  |
| POST | `/api/v1/defi/liquidity/provide` | `_handle_liquidity_provide` | service_routes.py:298 |  |
| POST | `/api/v1/defi/loan/create` | `_handle_defi_loan_create` | service_routes.py:183 |  |
| POST | `/api/v1/defi/loan/repay` | `_handle_defi_loan_repay` | service_routes.py:184 |  |
| POST | `/api/v1/defi/perp/trade` | `_handle_perp_trade` | service_routes.py:299 |  |
| POST | `/api/v1/defi/swap/execute` | `_handle_swap_execute` | service_routes.py:293 |  |
| POST | `/api/v1/defi/swap/route` | `_handle_swap_route` | service_routes.py:292 |  |
| POST | `/api/v1/defi/vault/deposit` | `_handle_vault_deposit` | service_routes.py:297 |  |
| POST | `/api/v1/defi/yield/optimize` | `_handle_yield_optimize` | service_routes.py:291 |  |
| POST | `/api/v1/dex/liquidity/add` | `_handle_dex_add_liquidity` | service_routes.py:217 |  |
| POST | `/api/v1/dex/swap` | `_handle_dex_swap` | service_routes.py:216 |  |
| POST | `/api/v1/dispute/claim` | `_handle_dispute_claim` | service_routes.py:234 |  |
| POST | `/api/v1/dispute/file` | `_handle_dispute_file` | service_routes.py:232 |  |
| POST | `/api/v1/dispute/vote` | `_handle_dispute_vote` | service_routes.py:233 |  |
| POST | `/api/v1/energy/carbon/buy` | `_handle_carbon_buy` | service_routes.py:345 |  |
| GET | `/api/v1/energy/carbon/prices` | `_handle_carbon_prices` | service_routes.py:347 |  |
| POST | `/api/v1/energy/carbon/retire` | `_handle_carbon_retire` | service_routes.py:346 |  |
| GET | `/api/v1/events/stream` | `_handle_event_stream` | service_routes.py:393 | ✅ |
| POST | `/api/v1/fundraising/campaign/create` | `_handle_fundraising_create` | service_routes.py:241 |  |
| POST | `/api/v1/fundraising/contribute` | `_handle_fundraising_contribute` | service_routes.py:242 |  |
| POST | `/api/v1/gaming/register` | `_handle_gaming_register` | service_routes.py:270 |  |
| GET | `/api/v1/governance/daos/{daoId}/proposals` | `_handle_dao_proposals` | service_routes.py:2372 |  |
| POST | `/api/v1/governance/multisig/approve` | `_handle_multisig_approve` | service_routes.py:351 |  |
| POST | `/api/v1/governance/multisig/propose` | `_handle_multisig_propose` | service_routes.py:350 |  |
| POST | `/api/v1/governance/proposal/create` | `_handle_governance_create` | service_routes.py:228 |  |
| POST | `/api/v1/governance/snapshot/vote` | `_handle_snapshot_vote` | service_routes.py:352 |  |
| POST | `/api/v1/governance/treasury/transfer` | `_handle_treasury_transfer` | service_routes.py:353 |  |
| POST | `/api/v1/governance/vote` | `_handle_governance_vote` | service_routes.py:229 |  |
| POST | `/api/v1/groups` | `_handle_groups_create` | service_routes.py:2362 |  |
| POST | `/api/v1/iap/asn` | `handle_iap_asn` | server.py:2307 | ✅ |
| POST | `/api/v1/iap/verify` | `handle_iap_verify` | server.py:2306 | ✅ |
| POST | `/api/v1/identity/create` | `_handle_did_create` | service_routes.py:203 |  |
| POST | `/api/v1/identity/credential/issue` | `_handle_credential_issue` | service_routes.py:311 |  |
| POST | `/api/v1/identity/credential/verify` | `_handle_credential_verify` | service_routes.py:312 |  |
| POST | `/api/v1/identity/did/create` | `_handle_identity_did_create` | service_routes.py:310 |  |
| POST | `/api/v1/identity/soulbound/mint` | `_handle_soulbound_mint` | service_routes.py:314 |  |
| POST | `/api/v1/identity/zk-proof/generate` | `_handle_zk_proof` | service_routes.py:313 |  |
| POST | `/api/v1/insurance/claim` | `_handle_insurance_claim` | service_routes.py:221 |  |
| POST | `/api/v1/insurance/claim/settle` | `_handle_claim_settle` | service_routes.py:381 |  |
| POST | `/api/v1/insurance/parametric/create` | `_handle_parametric_policy` | service_routes.py:380 |  |
| POST | `/api/v1/insurance/policy/create` | `_handle_insurance_create` | service_routes.py:220 |  |
| POST | `/api/v1/intent/execute` | `_handle_intent_execute` | service_routes.py:362 |  |
| POST | `/api/v1/intent/resolve` | `_handle_intent_resolve` | service_routes.py:361 |  |
| GET | `/api/v1/intent/summary/{plan_id}` | `_handle_intent_summary` | service_routes.py:363 |  |
| POST | `/api/v1/ip/register` | `_handle_ip_register` | service_routes.py:273 |  |
| POST | `/api/v1/legal/agreement/execute` | `_handle_agreement_execute` | service_routes.py:367 |  |
| POST | `/api/v1/legal/dispute/file` | `_handle_legal_dispute_file` | service_routes.py:368 |  |
| POST | `/api/v1/legal/license/grant` | `_handle_license_grant` | service_routes.py:366 |  |
| POST | `/api/v1/licensing/ip` | `_handle_licensing_register_ip` | service_routes.py:2366 |  |
| POST | `/api/v1/licensing/licenses` | `_handle_licensing_create_license` | service_routes.py:2368 |  |
| POST | `/api/v1/loyalty/earn` | `_handle_loyalty_earn` | service_routes.py:248 |  |
| POST | `/api/v1/loyalty/redeem` | `_handle_loyalty_redeem` | service_routes.py:249 |  |
| POST | `/api/v1/marketplace/buy` | `_handle_marketplace_buy` | service_routes.py:225 |  |
| POST | `/api/v1/marketplace/list` | `_handle_marketplace_list` | service_routes.py:224 |  |
| GET | `/api/v1/messaging/conversations` | `_handle_messaging_conversations` | service_routes.py:2352 |  |
| GET | `/api/v1/messaging/conversations/{conversationId}/messages` | `_handle_messaging_messages` | service_routes.py:2353 |  |
| POST | `/api/v1/nft/batch-mint` | `_handle_nft_batch_mint` | service_routes.py:305 |  |
| POST | `/api/v1/nft/bridge` | `_handle_nft_bridge` | service_routes.py:307 |  |
| POST | `/api/v1/nft/collection/create` | `_handle_nft_collection_create` | service_routes.py:197 |  |
| POST | `/api/v1/nft/fractionalize` | `_handle_nft_fractionalize` | service_routes.py:303 |  |
| POST | `/api/v1/nft/mint` | `_handle_nft_mint` | service_routes.py:196 |  |
| POST | `/api/v1/nft/rent` | `_handle_nft_rent` | service_routes.py:304 |  |
| POST | `/api/v1/nft/royalty/claim` | `_handle_nft_royalty_claim` | service_routes.py:306 |  |
| GET | `/api/v1/oracle/price/{pair}` | `_handle_oracle_price` | service_routes.py:285 |  |
| POST | `/api/v1/paymaster/sign` | `_handle_paymaster_sign` | service_routes.py:190 |  |
| POST | `/api/v1/payments/create` | `_handle_payment_create` | service_routes.py:279 |  |
| POST | `/api/v1/payments/escrow/milestone` | `_handle_escrow_milestone` | service_routes.py:326 |  |
| POST | `/api/v1/payments/payroll` | `_handle_payroll_run` | service_routes.py:328 |  |
| POST | `/api/v1/payments/recurring/create` | `_handle_recurring_create` | service_routes.py:325 |  |
| POST | `/api/v1/payments/split` | `_handle_payment_split` | service_routes.py:327 |  |
| POST | `/api/v1/payments/stream/create` | `_handle_stream_create` | service_routes.py:324 |  |
| GET | `/api/v1/portfolio/complete/{wallet}` | `_handle_portfolio_complete` | service_routes.py:356 |  |
| GET | `/api/v1/portfolio/history/{wallet}` | `_handle_portfolio_history` | service_routes.py:358 |  |
| GET | `/api/v1/portfolio/positions/{wallet}` | `_handle_portfolio_positions` | service_routes.py:357 |  |
| POST | `/api/v1/prediction/market/bet` | `_handle_market_bet` | service_routes.py:341 |  |
| POST | `/api/v1/prediction/market/create` | `_handle_market_create` | service_routes.py:340 |  |
| GET | `/api/v1/prediction/market/list` | `_handle_market_list` | service_routes.py:342 |  |
| GET | `/api/v1/price/eth-usd` | `_handle_eth_usd_price` | service_routes.py:193 |  |
| POST | `/api/v1/privacy/delete` | `_handle_privacy_delete` | service_routes.py:258 |  |
| POST | `/api/v1/realestate/buyers/verify` | `_handle_re_buyer_verify` | service_routes.py:406 |  |
| GET | `/api/v1/realestate/buyers/{wallet}/verification` | `_handle_re_buyer_verification_get` | service_routes.py:407 |  |
| GET | `/api/v1/realestate/documents/expiring` | `_handle_re_docs_expiring` | service_routes.py:405 |  |
| GET | `/api/v1/realestate/escrow/{id}` | `_handle_re_escrow_get` | service_routes.py:412 |  |
| POST | `/api/v1/realestate/escrow/{id}/confirm` | `_handle_re_escrow_confirm` | service_routes.py:409 |  |
| POST | `/api/v1/realestate/escrow/{id}/recording-complete` | `_handle_re_recording_complete` | service_routes.py:410 |  |
| POST | `/api/v1/realestate/escrow/{id}/refund` | `_handle_re_escrow_refund` | service_routes.py:411 |  |
| GET | `/api/v1/realestate/properties` | `_handle_re_property_list` | service_routes.py:399 |  |
| POST | `/api/v1/realestate/properties` | `_handle_re_property_create` | service_routes.py:398 |  |
| GET | `/api/v1/realestate/properties/{id}` | `_handle_re_property_get` | service_routes.py:400 |  |
| GET | `/api/v1/realestate/properties/{id}/documents` | `_handle_re_documents_get` | service_routes.py:403 |  |
| POST | `/api/v1/realestate/properties/{id}/documents` | `_handle_re_document_upload` | service_routes.py:402 |  |
| GET | `/api/v1/realestate/properties/{id}/readiness` | `_handle_re_readiness` | service_routes.py:404 |  |
| POST | `/api/v1/realestate/properties/{id}/status` | `_handle_re_property_status` | service_routes.py:401 |  |
| POST | `/api/v1/realestate/purchase` | `_handle_re_purchase` | service_routes.py:408 |  |
| POST | `/api/v1/rwa/fractional/buy` | `_handle_rwa_fractional_buy` | service_routes.py:336 |  |
| GET | `/api/v1/rwa/listings` | `_handle_rwa_listings` | service_routes.py:337 |  |
| POST | `/api/v1/rwa/tokenize` | `_handle_rwa_tokenize` | service_routes.py:200 |  |
| POST | `/api/v1/securities/create` | `_handle_securities_create` | service_routes.py:264 |  |
| POST | `/api/v1/security/preflight` | `_handle_security_preflight` | service_routes.py:187 |  |
| POST | `/api/v1/social/community/create` | `_handle_community_create` | service_routes.py:320 |  |
| GET | `/api/v1/social/feed/{wallet}` | `_handle_social_feed` | service_routes.py:321 |  |
| POST | `/api/v1/social/gate/create` | `_handle_social_gate` | service_routes.py:319 |  |
| POST | `/api/v1/social/message` | `_handle_social_message` | service_routes.py:237 |  |
| POST | `/api/v1/social/message/send` | `_handle_social_message_send` | service_routes.py:318 |  |
| POST | `/api/v1/social/post` | `_handle_social_post` | service_routes.py:317 |  |
| POST | `/api/v1/social/profile` | `_handle_social_profile` | service_routes.py:238 |  |
| POST | `/api/v1/stablecoin/transfer` | `_handle_stablecoin_transfer` | service_routes.py:209 |  |
| POST | `/api/v1/staking/stake` | `_handle_staking_stake` | service_routes.py:212 |  |
| POST | `/api/v1/staking/unstake` | `_handle_staking_unstake` | service_routes.py:213 |  |
| POST | `/api/v1/subscriptions/subscribe` | `_handle_subscribe` | service_routes.py:245 |  |
| POST | `/api/v1/supply-chain/custody/transfer` | `_handle_custody_transfer` | service_routes.py:377 |  |
| POST | `/api/v1/supply-chain/provenance/log` | `_handle_provenance_log` | service_routes.py:375 |  |
| POST | `/api/v1/supply-chain/register` | `_handle_supply_chain_register` | service_routes.py:267 |  |
| POST | `/api/v1/supply-chain/verify` | `_handle_authenticity_verify` | service_routes.py:376 |  |
| GET | `/audit` | `handle_audit_page` | server.py:2319 | ✅ |
| POST | `/audit/request` | `handle_audit_request` | server.py:2330 |  |
| GET | `/audit/{audit_id}` | `handle_audit_report` | server.py:2331 |  |
| POST | `/auth/nonce` | `handle_auth_nonce` | server.py:2302 | ✅ |
| POST | `/auth/verify` | `handle_auth_verify` | server.py:2303 | ✅ |
| POST | `/badge/issue` | `handle_badge_issue` | server.py:2371 |  |
| GET | `/badge/widget.js` | `handle_badge_widget_js` | server.py:2366 |  |
| GET | `/badge/{badge_id}` | `handle_badge_page` | server.py:2367 |  |
| GET | `/badge/{badge_id}/embed` | `handle_badge_embed` | server.py:2369 |  |
| GET | `/badge/{badge_id}/status` | `handle_badge_status` | server.py:2368 |  |
| GET | `/badges` | `handle_badges_list` | server.py:2370 | ✅ |
| POST | `/bridge/v1/action` | `execute_action` | bridge.py:571 |  |
| POST | `/bridge/v1/chat` | `chat` | bridge.py:568 | ✅ |
| GET | `/bridge/v1/components` | `get_components` | bridge.py:588 |  |
| GET | `/bridge/v1/components/manifest` | `get_components_manifest` | bridge.py:589 |  |
| GET | `/bridge/v1/components/{component_id}` | `get_component` | bridge.py:590 |  |
| GET | `/bridge/v1/config` | `get_config` | bridge.py:581 |  |
| GET | `/bridge/v1/dashboard` | `get_dashboard` | bridge.py:585 |  |
| POST | `/bridge/v1/push/register` | `register_push` | bridge.py:578 |  |
| GET | `/bridge/v1/services` | `get_services` | bridge.py:582 |  |
| POST | `/bridge/v1/session/create` | `create_session` | bridge.py:564 |  |
| POST | `/bridge/v1/session/resume` | `resume_session` | bridge.py:565 |  |
| POST | `/bridge/v1/wallet/link` | `link_wallet` | bridge.py:574 |  |
| GET | `/bridge/v1/wallet/status` | `wallet_status` | bridge.py:575 |  |
| POST | `/certification/start` | `handle_cert_start` | server.py:2376 |  |
| POST | `/certification/submit` | `handle_cert_submit` | server.py:2377 |  |
| GET | `/certification/tracks` | `handle_cert_tracks` | server.py:2375 |  |
| GET | `/certification/{cert_id}` | `handle_cert_verify` | server.py:2378 |  |
| GET | `/chat` | `handle_chat_page` | server.py:2318 | ✅ |
| POST | `/chat` | `handle_chat` | server.py:2294 | ✅ |
| POST | `/chat/stream` | `handle_chat_stream` | server.py:2295 |  |
| GET | `/extensions/registry` | `handle_extensions_registry` | server.py:2326 | ✅ |
| GET | `/extensions/registry/{component_id}` | `handle_extensions_component` | server.py:2327 |  |
| GET | `/glasswing` | `handle_glasswing_page` | server.py:2365 | ✅ |
| GET | `/health` | `handle_health` | server.py:2297 | ✅ |
| GET | `/learn` | `handle_learn_page` | server.py:2374 | ✅ |
| GET | `/marketplace` | `handle_marketplace_page` | server.py:2320 | ✅ |
| GET | `/marketplace/plugins` | `handle_marketplace_list` | server.py:2355 |  |
| POST | `/marketplace/plugins/submit` | `handle_marketplace_submit` | server.py:2358 |  |
| GET | `/marketplace/plugins/{plugin_id}` | `handle_marketplace_plugin` | server.py:2356 |  |
| POST | `/marketplace/plugins/{plugin_id}/purchase` | `handle_marketplace_purchase` | server.py:2357 |  |
| GET | `/marketplace/purchased` | `handle_marketplace_purchased` | server.py:2359 |  |
| POST | `/memory/read` | `handle_memory_read` | server.py:2300 |  |
| POST | `/memory/write` | `handle_memory_write` | server.py:2301 |  |
| GET | `/metrics` | `handle_metrics` | server.py:2313 |  |
| GET | `/metrics/prom` | `handle_metrics_prometheus` | server.py:2314 |  |
| GET | `/privacy` | `handle_privacy_page` | server.py:2322 | ✅ |
| GET | `/ready` | `handle_ready` | server.py:2298 | ✅ |
| POST | `/security/appattest/attest` | `handle_appattest_attest` | server.py:2312 | ✅ |
| GET | `/security/appattest/challenge` | `handle_appattest_challenge` | server.py:2311 | ✅ |
| POST | `/security/owner/request` | `handle_owner_otp_request` | server.py:2310 |  |
| POST | `/security/phone/request` | `handle_otp_request` | server.py:2308 | ✅ |
| POST | `/security/phone/verify` | `handle_otp_verify` | server.py:2309 | ✅ |
| GET | `/services/conversion` | `handle_conversion_page` | server.py:2321 | ✅ |
| GET | `/social` | `handle_social_feed_page` | server.py:2337 | ✅ |
| GET | `/social/actor/{wallet}` | `handle_social_actor` | server.py:2341 |  |
| GET | `/social/feed` | `handle_social_feed` | server.py:2338 | ✅ |
| GET | `/social/feed/stream` | `handle_social_feed_stream` | server.py:2339 | ✅ |
| POST | `/social/follow` | `handle_social_follow` | server.py:2344 |  |
| POST | `/social/post` | `handle_social_post` | server.py:2334 |  |
| GET | `/social/stats` | `handle_social_stats` | server.py:2342 | ✅ |
| GET | `/social/trending` | `handle_social_trending` | server.py:2340 | ✅ |
| POST | `/social/unfollow` | `handle_social_unfollow` | server.py:2345 |  |
| GET | `/social/{address}/followers` | `handle_social_followers` | server.py:2346 |  |
| GET | `/social/{address}/following` | `handle_social_following` | server.py:2347 |  |
| GET | `/sponsor` | `handle_sponsor_redirect` | server.py:2362 | ✅ |
| GET | `/status` | `handle_status` | server.py:2299 |  |
| GET | `/terms` | `handle_terms_page` | server.py:2323 | ✅ |
| GET | `/ws` | `handle_websocket` | server.py:2296 | ✅ |
