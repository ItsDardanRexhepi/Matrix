# Gateway route table

> **Generated** by `scripts/generate_route_table.py` — do not edit by hand.
> Run `python scripts/generate_route_table.py` after adding a route;
> CI runs it with `--check` and fails if this file is stale.

**183 routes.** A **public** route requires no API key (its own auth applies — e.g. a signed JWS, SIWE, or per-IP caps).

| Method | Path | Handler | Source | Public |
|---|---|---|---|---|
| GET | `/` | `handle_landing` | server.py:2905 | ✅ |
| POST | `/a2a/jobs` | `handle_a2a_submit_job` | server.py:2939 |  |
| GET | `/a2a/jobs/{job_id}` | `handle_a2a_get_job` | server.py:2940 |  |
| GET | `/a2a/services` | `handle_a2a_services` | server.py:2938 | ✅ |
| POST | `/api/v1/agent/register` | `_handle_agent_register` | service_routes.py:309 |  |
| GET | `/api/v1/attestation/verify/{uid}` | `_handle_attestation_verify` | service_routes.py:321 |  |
| DELETE | `/api/v1/auth/account` | `handle_account_delete` | server.py:2893 | ✅ |
| POST | `/api/v1/auth/apple` | `handle_apple_auth` | server.py:2892 | ✅ |
| POST | `/api/v1/batch` | `_handle_batch` | service_routes.py:422 |  |
| POST | `/api/v1/brand/campaign/create` | `_handle_brand_campaign_create` | service_routes.py:288 |  |
| GET | `/api/v1/capabilities` | `_handle_capabilities_list` | service_routes.py:416 |  |
| GET | `/api/v1/capabilities/categories` | `_handle_capabilities_categories` | service_routes.py:417 |  |
| GET | `/api/v1/capabilities/{capability_id}` | `_handle_capability_detail` | service_routes.py:418 |  |
| POST | `/api/v1/capabilities/{capability_id}/invoke` | `_handle_capability_invoke` | service_routes.py:419 |  |
| POST | `/api/v1/cashback/track` | `_handle_cashback_track` | service_routes.py:285 |  |
| POST | `/api/v1/compute/arweave/store` | `_handle_arweave_store` | service_routes.py:361 |  |
| POST | `/api/v1/compute/ipfs/pin` | `_handle_ipfs_pin` | service_routes.py:360 |  |
| POST | `/api/v1/compute/store` | `_handle_decentralized_store` | service_routes.py:359 |  |
| POST | `/api/v1/contracts/convert` | `_handle_contract_convert` | service_routes.py:212 |  |
| POST | `/api/v1/contracts/deploy` | `_handle_contract_deploy` | service_routes.py:213 |  |
| POST | `/api/v1/crossborder/send` | `_handle_crossborder_send` | service_routes.py:294 |  |
| POST | `/api/v1/dao/create` | `_handle_dao_create` | service_routes.py:239 |  |
| GET | `/api/v1/dashboard/{address}` | `_handle_dashboard` | service_routes.py:315 |  |
| POST | `/api/v1/defi/bridge/execute` | `_handle_bridge_execute` | service_routes.py:327 |  |
| POST | `/api/v1/defi/bridge/quote` | `_handle_bridge_quote` | service_routes.py:326 |  |
| POST | `/api/v1/defi/loan/create` | `_handle_defi_loan_create` | service_routes.py:216 |  |
| POST | `/api/v1/defi/loan/repay` | `_handle_defi_loan_repay` | service_routes.py:217 |  |
| POST | `/api/v1/defi/swap/execute` | `_handle_swap_execute` | service_routes.py:325 |  |
| POST | `/api/v1/defi/swap/route` | `_handle_swap_route` | service_routes.py:324 |  |
| POST | `/api/v1/dex/liquidity/add` | `_handle_dex_add_liquidity` | service_routes.py:250 |  |
| POST | `/api/v1/dex/swap` | `_handle_dex_swap` | service_routes.py:249 |  |
| POST | `/api/v1/dispute/claim` | `_handle_dispute_claim` | service_routes.py:267 |  |
| POST | `/api/v1/dispute/file` | `_handle_dispute_file` | service_routes.py:265 |  |
| POST | `/api/v1/dispute/vote` | `_handle_dispute_vote` | service_routes.py:266 |  |
| GET | `/api/v1/events/stream` | `_handle_event_stream` | service_routes.py:423 | ✅ |
| POST | `/api/v1/fundraising/campaign/create` | `_handle_fundraising_create` | service_routes.py:274 |  |
| POST | `/api/v1/fundraising/contribute` | `_handle_fundraising_contribute` | service_routes.py:275 |  |
| POST | `/api/v1/gaming/register` | `_handle_gaming_register` | service_routes.py:303 |  |
| GET | `/api/v1/governance/daos/{daoId}/proposals` | `_handle_dao_proposals` | service_routes.py:2883 |  |
| POST | `/api/v1/governance/multisig/approve` | `_handle_multisig_approve` | service_routes.py:371 |  |
| POST | `/api/v1/governance/proposal/create` | `_handle_governance_create` | service_routes.py:261 |  |
| POST | `/api/v1/governance/snapshot/vote` | `_handle_snapshot_vote` | service_routes.py:372 |  |
| POST | `/api/v1/governance/vote` | `_handle_governance_vote` | service_routes.py:262 |  |
| POST | `/api/v1/groups` | `_handle_groups_create` | service_routes.py:2873 |  |
| POST | `/api/v1/iap/asn` | `handle_iap_asn` | server.py:2895 | ✅ |
| POST | `/api/v1/iap/verify` | `handle_iap_verify` | server.py:2894 | ✅ |
| POST | `/api/v1/identity/create` | `_handle_did_create` | service_routes.py:236 |  |
| POST | `/api/v1/identity/credential/issue` | `_handle_credential_issue` | service_routes.py:345 |  |
| POST | `/api/v1/identity/credential/verify` | `_handle_credential_verify` | service_routes.py:346 |  |
| POST | `/api/v1/identity/did/create` | `_handle_identity_did_create` | service_routes.py:344 |  |
| POST | `/api/v1/identity/zk-proof/generate` | `_handle_zk_proof` | service_routes.py:347 |  |
| POST | `/api/v1/insurance/claim` | `_handle_insurance_claim` | service_routes.py:254 |  |
| POST | `/api/v1/insurance/parametric/create` | `_handle_parametric_policy` | service_routes.py:394 |  |
| POST | `/api/v1/insurance/policy/create` | `_handle_insurance_create` | service_routes.py:253 |  |
| POST | `/api/v1/intent/execute` | `_handle_intent_execute` | service_routes.py:381 |  |
| POST | `/api/v1/intent/resolve` | `_handle_intent_resolve` | service_routes.py:380 |  |
| GET | `/api/v1/intent/summary/{plan_id}` | `_handle_intent_summary` | service_routes.py:382 |  |
| POST | `/api/v1/ip/register` | `_handle_ip_register` | service_routes.py:306 |  |
| POST | `/api/v1/licensing/ip` | `_handle_licensing_register_ip` | service_routes.py:2877 |  |
| POST | `/api/v1/licensing/licenses` | `_handle_licensing_create_license` | service_routes.py:2879 |  |
| POST | `/api/v1/loyalty/earn` | `_handle_loyalty_earn` | service_routes.py:281 |  |
| POST | `/api/v1/loyalty/redeem` | `_handle_loyalty_redeem` | service_routes.py:282 |  |
| POST | `/api/v1/marketplace/buy` | `_handle_marketplace_buy` | service_routes.py:258 |  |
| POST | `/api/v1/marketplace/list` | `_handle_marketplace_list` | service_routes.py:257 |  |
| GET | `/api/v1/messaging/conversations` | `_handle_messaging_conversations` | service_routes.py:2863 |  |
| GET | `/api/v1/messaging/conversations/{conversationId}/messages` | `_handle_messaging_messages` | service_routes.py:2864 |  |
| POST | `/api/v1/nft/batch-mint` | `_handle_nft_batch_mint` | service_routes.py:339 |  |
| POST | `/api/v1/nft/bridge` | `_handle_nft_bridge` | service_routes.py:341 |  |
| POST | `/api/v1/nft/collection/create` | `_handle_nft_collection_create` | service_routes.py:230 |  |
| POST | `/api/v1/nft/fractionalize` | `_handle_nft_fractionalize` | service_routes.py:337 |  |
| POST | `/api/v1/nft/mint` | `_handle_nft_mint` | service_routes.py:229 |  |
| POST | `/api/v1/nft/rent` | `_handle_nft_rent` | service_routes.py:338 |  |
| POST | `/api/v1/nft/royalty/claim` | `_handle_nft_royalty_claim` | service_routes.py:340 |  |
| GET | `/api/v1/oracle/price/{pair}` | `_handle_oracle_price` | service_routes.py:318 |  |
| POST | `/api/v1/paymaster/sign` | `_handle_paymaster_sign` | service_routes.py:223 |  |
| POST | `/api/v1/payments/create` | `_handle_payment_create` | service_routes.py:312 |  |
| GET | `/api/v1/portfolio/complete/{wallet}` | `_handle_portfolio_complete` | service_routes.py:375 |  |
| GET | `/api/v1/portfolio/history/{wallet}` | `_handle_portfolio_history` | service_routes.py:377 |  |
| GET | `/api/v1/portfolio/positions/{wallet}` | `_handle_portfolio_positions` | service_routes.py:376 |  |
| GET | `/api/v1/price/eth-usd` | `_handle_eth_usd_price` | service_routes.py:226 |  |
| POST | `/api/v1/privacy/delete` | `_handle_privacy_delete` | service_routes.py:291 |  |
| POST | `/api/v1/realestate/buyers/verify` | `_handle_re_buyer_verify` | service_routes.py:436 |  |
| GET | `/api/v1/realestate/buyers/{wallet}/verification` | `_handle_re_buyer_verification_get` | service_routes.py:437 |  |
| GET | `/api/v1/realestate/documents/expiring` | `_handle_re_docs_expiring` | service_routes.py:435 |  |
| GET | `/api/v1/realestate/escrow/{id}` | `_handle_re_escrow_get` | service_routes.py:442 |  |
| POST | `/api/v1/realestate/escrow/{id}/confirm` | `_handle_re_escrow_confirm` | service_routes.py:439 |  |
| POST | `/api/v1/realestate/escrow/{id}/recording-complete` | `_handle_re_recording_complete` | service_routes.py:440 |  |
| POST | `/api/v1/realestate/escrow/{id}/refund` | `_handle_re_escrow_refund` | service_routes.py:441 |  |
| GET | `/api/v1/realestate/properties` | `_handle_re_property_list` | service_routes.py:429 |  |
| POST | `/api/v1/realestate/properties` | `_handle_re_property_create` | service_routes.py:428 |  |
| GET | `/api/v1/realestate/properties/{id}` | `_handle_re_property_get` | service_routes.py:430 |  |
| GET | `/api/v1/realestate/properties/{id}/documents` | `_handle_re_documents_get` | service_routes.py:433 |  |
| POST | `/api/v1/realestate/properties/{id}/documents` | `_handle_re_document_upload` | service_routes.py:432 |  |
| GET | `/api/v1/realestate/properties/{id}/readiness` | `_handle_re_readiness` | service_routes.py:434 |  |
| POST | `/api/v1/realestate/properties/{id}/status` | `_handle_re_property_status` | service_routes.py:431 |  |
| POST | `/api/v1/realestate/purchase` | `_handle_re_purchase` | service_routes.py:438 |  |
| GET | `/api/v1/rwa/listings` | `_handle_rwa_listings` | service_routes.py:364 |  |
| POST | `/api/v1/rwa/tokenize` | `_handle_rwa_tokenize` | service_routes.py:233 |  |
| POST | `/api/v1/securities/create` | `_handle_securities_create` | service_routes.py:297 |  |
| POST | `/api/v1/security/preflight` | `_handle_security_preflight` | service_routes.py:220 |  |
| POST | `/api/v1/social/community/create` | `_handle_community_create` | service_routes.py:353 |  |
| GET | `/api/v1/social/feed/{wallet}` | `_handle_social_feed` | service_routes.py:354 |  |
| POST | `/api/v1/social/gate/create` | `_handle_social_gate` | service_routes.py:352 |  |
| POST | `/api/v1/social/message` | `_handle_social_message` | service_routes.py:270 |  |
| POST | `/api/v1/social/message/send` | `_handle_social_message_send` | service_routes.py:351 |  |
| POST | `/api/v1/social/post` | `_handle_social_post` | service_routes.py:350 |  |
| POST | `/api/v1/social/profile` | `_handle_social_profile` | service_routes.py:271 |  |
| POST | `/api/v1/stablecoin/transfer` | `_handle_stablecoin_transfer` | service_routes.py:242 |  |
| POST | `/api/v1/staking/stake` | `_handle_staking_stake` | service_routes.py:245 |  |
| POST | `/api/v1/staking/unstake` | `_handle_staking_unstake` | service_routes.py:246 |  |
| POST | `/api/v1/subscriptions/subscribe` | `_handle_subscribe` | service_routes.py:278 |  |
| POST | `/api/v1/supply-chain/custody/transfer` | `_handle_custody_transfer` | service_routes.py:391 |  |
| POST | `/api/v1/supply-chain/provenance/log` | `_handle_provenance_log` | service_routes.py:389 |  |
| POST | `/api/v1/supply-chain/register` | `_handle_supply_chain_register` | service_routes.py:300 |  |
| POST | `/api/v1/supply-chain/verify` | `_handle_authenticity_verify` | service_routes.py:390 |  |
| GET | `/audit` | `handle_audit_page` | server.py:2907 | ✅ |
| POST | `/audit/request` | `handle_audit_request` | server.py:2918 |  |
| GET | `/audit/{audit_id}` | `handle_audit_report` | server.py:2919 |  |
| POST | `/auth/nonce` | `handle_auth_nonce` | server.py:2890 | ✅ |
| POST | `/auth/verify` | `handle_auth_verify` | server.py:2891 | ✅ |
| POST | `/badge/issue` | `handle_badge_issue` | server.py:2956 |  |
| GET | `/badge/widget.js` | `handle_badge_widget_js` | server.py:2951 |  |
| GET | `/badge/{badge_id}` | `handle_badge_page` | server.py:2952 |  |
| GET | `/badge/{badge_id}/embed` | `handle_badge_embed` | server.py:2954 |  |
| GET | `/badge/{badge_id}/status` | `handle_badge_status` | server.py:2953 |  |
| GET | `/badges` | `handle_badges_list` | server.py:2955 | ✅ |
| POST | `/bridge/v1/action` | `execute_action` | bridge.py:670 |  |
| POST | `/bridge/v1/chat` | `chat` | bridge.py:668 | ✅ |
| GET | `/bridge/v1/components` | `get_components` | bridge.py:682 |  |
| GET | `/bridge/v1/components/manifest` | `get_components_manifest` | bridge.py:683 |  |
| GET | `/bridge/v1/components/{component_id}` | `get_component` | bridge.py:684 |  |
| GET | `/bridge/v1/config` | `get_config` | bridge.py:677 |  |
| GET | `/bridge/v1/dashboard` | `get_dashboard` | bridge.py:680 |  |
| POST | `/bridge/v1/push/register` | `register_push` | bridge.py:675 |  |
| GET | `/bridge/v1/services` | `get_services` | bridge.py:678 |  |
| POST | `/bridge/v1/session/create` | `create_session` | bridge.py:665 |  |
| POST | `/bridge/v1/session/resume` | `resume_session` | bridge.py:666 |  |
| POST | `/bridge/v1/wallet/link` | `link_wallet` | bridge.py:672 |  |
| GET | `/bridge/v1/wallet/status` | `wallet_status` | bridge.py:673 |  |
| POST | `/certification/start` | `handle_cert_start` | server.py:2961 |  |
| POST | `/certification/submit` | `handle_cert_submit` | server.py:2962 |  |
| GET | `/certification/tracks` | `handle_cert_tracks` | server.py:2960 |  |
| GET | `/certification/{cert_id}` | `handle_cert_verify` | server.py:2963 |  |
| GET | `/chat` | `handle_chat_page` | server.py:2906 | ✅ |
| POST | `/chat` | `handle_chat` | server.py:2882 | ✅ |
| POST | `/chat/stream` | `handle_chat_stream` | server.py:2883 | ✅ |
| GET | `/extensions/registry` | `handle_extensions_registry` | server.py:2914 | ✅ |
| GET | `/extensions/registry/{component_id}` | `handle_extensions_component` | server.py:2915 |  |
| GET | `/glasswing` | `handle_glasswing_page` | server.py:2950 | ✅ |
| GET | `/health` | `handle_health` | server.py:2885 | ✅ |
| GET | `/learn` | `handle_learn_page` | server.py:2959 | ✅ |
| GET | `/marketplace` | `handle_marketplace_page` | server.py:2908 | ✅ |
| GET | `/marketplace/plugins` | `handle_marketplace_list` | server.py:2943 |  |
| POST | `/marketplace/plugins/submit` | `handle_marketplace_submit` | server.py:2946 |  |
| GET | `/marketplace/plugins/{plugin_id}` | `handle_marketplace_plugin` | server.py:2944 |  |
| POST | `/marketplace/plugins/{plugin_id}/purchase` | `handle_marketplace_purchase` | server.py:2945 |  |
| GET | `/marketplace/purchased` | `handle_marketplace_purchased` | server.py:2947 |  |
| POST | `/memory/read` | `handle_memory_read` | server.py:2888 |  |
| POST | `/memory/write` | `handle_memory_write` | server.py:2889 |  |
| GET | `/metrics` | `handle_metrics` | server.py:2901 |  |
| GET | `/metrics/prom` | `handle_metrics_prometheus` | server.py:2902 |  |
| GET | `/privacy` | `handle_privacy_page` | server.py:2910 | ✅ |
| GET | `/ready` | `handle_ready` | server.py:2886 | ✅ |
| POST | `/security/appattest/attest` | `handle_appattest_attest` | server.py:2900 | ✅ |
| GET | `/security/appattest/challenge` | `handle_appattest_challenge` | server.py:2899 | ✅ |
| POST | `/security/owner/request` | `handle_owner_otp_request` | server.py:2898 |  |
| POST | `/security/phone/request` | `handle_otp_request` | server.py:2896 | ✅ |
| POST | `/security/phone/verify` | `handle_otp_verify` | server.py:2897 | ✅ |
| GET | `/services/conversion` | `handle_conversion_page` | server.py:2909 | ✅ |
| GET | `/social` | `handle_social_feed_page` | server.py:2925 | ✅ |
| GET | `/social/actor/{wallet}` | `handle_social_actor` | server.py:2929 |  |
| GET | `/social/feed` | `handle_social_feed` | server.py:2926 | ✅ |
| GET | `/social/feed/stream` | `handle_social_feed_stream` | server.py:2927 | ✅ |
| POST | `/social/follow` | `handle_social_follow` | server.py:2932 |  |
| POST | `/social/post` | `handle_social_post` | server.py:2922 |  |
| GET | `/social/stats` | `handle_social_stats` | server.py:2930 | ✅ |
| GET | `/social/trending` | `handle_social_trending` | server.py:2928 | ✅ |
| POST | `/social/unfollow` | `handle_social_unfollow` | server.py:2933 |  |
| GET | `/social/{address}/followers` | `handle_social_followers` | server.py:2934 |  |
| GET | `/social/{address}/following` | `handle_social_following` | server.py:2935 |  |
| GET | `/status` | `handle_status` | server.py:2887 |  |
| GET | `/terms` | `handle_terms_page` | server.py:2911 | ✅ |
| GET | `/ws` | `handle_websocket` | server.py:2884 | ✅ |
