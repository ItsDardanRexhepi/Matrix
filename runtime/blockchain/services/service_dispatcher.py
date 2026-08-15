"""
Service Dispatcher — routes Trinity's natural language intents to the correct
blockchain service. This is what makes all 221 capabilities user-facing, backed by 44 services.

Trinity's ReAct loop calls tools. This dispatcher registers one mega-tool
'platform_action' that can invoke any of the 221 capabilities (backed by 44 services) based on the action name.
"""

from __future__ import annotations

import asyncio
import functools
import inspect
import json
import logging
import time
from typing import Any

logger = logging.getLogger(__name__)

# 17-D. The parameter name a service method declares to receive the
# AUTHENTICATED caller's wallet address from the dispatcher. One constant so
# the service side and the injection side cannot drift apart.
CALLER_IDENTITY_PARAM = "caller_identity"


@functools.lru_cache(maxsize=1024)
def _func_accepts_caller_identity(func: Any) -> bool:
    try:
        sig = inspect.signature(func)
    except (TypeError, ValueError):
        return False
    param = sig.parameters.get(CALLER_IDENTITY_PARAM)
    if param is None:
        return False
    # An EXPLICITLY DECLARED parameter only. A method whose signature merely
    # ends in **kwargs has not opted in — it would swallow the identity
    # silently and forward it somewhere it was never meant to go, which is the
    # kind of invisible coupling this parameter exists to avoid.
    return param.kind in (
        inspect.Parameter.POSITIONAL_OR_KEYWORD,
        inspect.Parameter.KEYWORD_ONLY,
    )


def _method_accepts_caller_identity(method: Any) -> bool:
    """True when *method* declares a `caller_identity` parameter by name.

    Signature inspection is the opt-in mechanism (see DOMAIN 17-D in
    `ServiceDispatcher.execute`). Anything uninspectable — a builtin, a C
    callable, an exotic wrapper — is treated as NOT accepting it, so an
    unreadable signature degrades to today's behaviour instead of raising.

    Caching is keyed on the underlying FUNCTION, not on the bound method:
    `getattr(instance, name)` mints a fresh bound method on every dispatch, so
    caching those would both miss every time and pin every service instance
    the cache ever saw. `__func__` is the module-level function object, which
    is stable and already immortal.
    """
    target = getattr(method, "__func__", method)
    try:
        return _func_accepts_caller_identity(target)
    except TypeError:
        # Unhashable callable — cannot be cached; answer directly.
        try:
            sig = inspect.signature(method)
        except (TypeError, ValueError):
            return False
        param = sig.parameters.get(CALLER_IDENTITY_PARAM)
        return param is not None and param.kind in (
            inspect.Parameter.POSITIONAL_OR_KEYWORD,
            inspect.Parameter.KEYWORD_ONLY,
        )


# ---------------------------------------------------------------------------
# Action -> (service_name, method_name) mapping
# ---------------------------------------------------------------------------

ACTION_MAP: dict[str, tuple[str, str]] = {
    # --- Contract Conversion (Component 1) ---
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
    # NEW-48b: "query_attestations" REMOVED — attestation.query returned the
    # GraphQL query text as if it were results. No EAS subgraph reader exists.
    "batch_attest": ("attestation", "batch_attest"),

    # --- Agent Identity (Component 9) ---
    "register_agent": ("agent_identity", "register_agent"),
    "get_agent": ("agent_identity", "get_agent"),
    "update_agent": ("agent_identity", "update_agent"),
    "deregister_agent": ("agent_identity", "deregister_agent"),
    "list_agents": ("agent_identity", "list_agents"),

    # --- x402 Payments (Component 10) ---
    "create_payment": ("x402_payments", "create_payment"),
    # ── NEW-53: authorize_payment and refund_payment DISABLED ─────────────
    #
    # INTERIM DISABLE on an authorization vulnerability, not an honesty fix.
    #
    # Both methods take ONLY a payment_id:
    #     async def authorize_payment(self, payment_id: str)
    #     async def refund_payment(self, payment_id: str)
    # No owner, no signature, no caller identity of any kind. The paying agent
    # is read FROM THE STORED PAYMENT, not from the caller — so the caller is
    # never compared against anything.
    #
    # Payment ids are handed out by create_payment, get_payment and
    # list_payments. Anyone who reaches the dispatcher with an id could
    # authorize a spend against ANOTHER agent's budget, or refund another
    # agent's payment (which also silently restores that agent's spend
    # headroom — a free budget-reset primitive).
    #
    # WHY THE SECURITY GATE DOES NOT COVER THIS — two independent reasons:
    #
    #   1. `ServiceDispatcher.execute` never calls `gate_action` at all. Of the
    #      four entry points that reach it, only gateway/bridge.py:789 gates;
    #      capabilities/registry.py, agents/handoff.py and tools/dispatcher.py
    #      reach the dispatcher with no gate call (verified: 0 occurrences of
    #      `gate_action` in each).
    #   2. Even the gated path would not help. `gate_action(action_type,
    #      parameters, context)` is an action-TYPE policy check. It asks "is
    #      this kind of action allowed for this identity", never "does this
    #      caller own payment X".
    #
    #      Ownership verification is not absent from the codebase — that claim
    #      was too strong and a test caught it. It exists PER-SERVICE and
    #      AD-HOC: ip_royalties.verify_ownership compares
    #      `record["owner"] == claimant`, rwa_tokenization has _find_owner.
    #      What does not exist is a SHARED primitive or any enforcement at the
    #      seam, so whether an object is protected depends on whether that
    #      service's author happened to write a check. x402_payments did not.
    #      See NEW-54, the systemic finding.
    #
    # The real fix is a signature change + an ownership check + plumbing
    # identity through ServiceDispatcher.execute into three currently-ungated
    # call sites. That is not one commit, and an unauthenticated money-state
    # transition does not stay live while it is built — the same reasoning
    # that took execute_deletion offline (NEW-38).
    #
    # Disabling here rather than in the service body is deliberate: ACTION_MAP
    # is the single choke point all four dispatch entry points share, and
    # NEITHER method has an HTTP route (verified by router-table read — no
    # `_call("x402_payments", "authorize_payment"|"refund_payment")` exists in
    # gateway/service_routes.py). So removing the actions removes every live
    # path, with no HTTP surface lost.
    #
    # The methods themselves are LEFT IN PLACE, unreachable. They are not
    # fabrications — their expiry checks, state guards and spend accounting are
    # real work (real-local-defective). They are the starting point for the
    # authenticated versions, not something to delete.
    "complete_payment": ("x402_payments", "complete_payment"),
    "get_payment": ("x402_payments", "get_payment"),
    "list_payments": ("x402_payments", "list_payments"),

    # --- Oracle Gateway (Component 11) ---
    "oracle_request": ("oracle_gateway", "request"),
    # NEW-10 bug 1 (RUN-2 class): `get_price` pointed at the GENERIC
    # `request(oracle_type, params, ...)`, which requires an oracle_type a
    # price-lookup caller has no reason to send — so every `get_price` call
    # returned a validation error. `oracle_price_query` already used the
    # dedicated `query_price` correctly; `get_price` now does too, making the
    # two a genuine alias rather than a collapse that broke one of them.
    "get_price": ("oracle_gateway", "query_price"),

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
    # NEW-38: `execute_deletion` -> privacy.execute_pending_deletion is REMOVED.
    # It was the trigger for a deletion executor that deleted nothing and
    # reported success=True with total_deleted=9 for users whose data it never
    # looked for, then minted a random hex string as an EAS "attestation" of
    # the deletion. No HTTP route pointed here, which is why it read as inert
    # — but four call sites reach ACTION_MAP (gateway/bridge.py's tool surface,
    # capabilities/registry.invoke, agents/handoff, tools/dispatcher), so the
    # action WAS live and reproducibly returned status=ok.
    #
    # `request_deletion` below is deliberately KEPT: the ruling is that it
    # answers "not available" rather than accepting-and-queuing, so it has to
    # stay reachable to give that answer. The service method now refuses.

    # --- Dispute Resolution (Component 30) ---
    "file_dispute": ("dispute_resolution", "file_dispute"),
    "submit_dispute_evidence": ("dispute_resolution", "submit_evidence"),
    "get_dispute": ("dispute_resolution", "get_dispute"),
    "resolve_dispute": ("dispute_resolution", "resolve"),
    "appeal_dispute": ("dispute_resolution", "appeal"),

    # ── DeFi Expanded ────────────────────────────────────────────
    # NEW-61: ten fabricated defi actions removed here. Each pointed at a
    # method that minted a uuid, set a success status and stored the dict —
    # no chain call, no real arithmetic. Removed: flash_loan, yield_optimize,
    # perp_trade, options_trade, synthetic_asset, vault_deposit,
    # leverage_position (twin-path: NONE for all seven), plus
    # liquidity_provide / liquidity_remove, which were DUPLICATE names
    # shadowing the real AMM already registered above as add_liquidity /
    # remove_liquidity -> ("dex", ...). The real capability is unaffected.
    #
    # collateral_manage was NOT simply dropped. Its twin is real
    # (CollateralManager.deposit / withdraw) but was exposed on no surface at
    # all, so NEW-61 registered deposit_collateral / withdraw_collateral /
    # get_health_factor here in its place.
    #
    # NEW-64: THAT REGISTRATION IS REVERSED. It was wrong, and this is the
    # correction.
    #
    # The twin is real AS COMPUTATION and false AS CUSTODY. CollateralManager
    # increments a Python dict: no escrow, no chain interaction, no
    # persistence across a restart. Every other lending entry point on this
    # service is deployment-gated (create_loan at service.py:94 and its sole
    # writer LoanManager.create_loan at loans.py:128); these three carried NO
    # gate, so they were the only live lending surface in the service.
    #
    # The aggravating factor: deposit_collateral / withdraw_collateral were
    # placed in _STATE_MODIFYING_ACTIONS below, and membership in that set is
    # exactly what triggers _attest_action() plus a fire-and-forget publish to
    # the public social feed. So a dict increment minted an attestation and
    # announced custody publicly — strictly worse than the fabrication it
    # replaced, because the fabrication did not attest.
    #
    # LIFTING CONDITION — do not re-register any of these until BOTH hold:
    #   1. the operation actually holds value (real escrow or a real on-chain
    #      position), or the response discloses that it does not, in the
    #      RECORDED_UNSETTLED idiom (settled=False / value_moved=False); AND
    #   2. [SATISFIED by 16-C, 2026-08-12] NEW-62 is fixed. As written this read:
    #      "service.py passes repaid_amount (principal plus interest) into a
    #      principal-only ledger, collateral.py clamps the overshoot with
    #      max(0, ...), and a zero ledger makes withdraw's
    #      `total_borrows_usd > 0` conjunct False, disabling the health check
    #      entirely. Reproduced: repay $10,000 of a $10,202 debt, loan stays
    #      ACTIVE owing $202, guard reports no_borrows, all collateral
    #      withdraws."
    #      16-C replaced `CollateralManager.record_repayment(user, token,
    #      amount)` — a SUBTRACT fed the wrong quantity — with
    #      `set_borrow_position(user, token, principal)`, and service.py:196 now
    #      passes `result["remaining_principal"]`, the loan's own figure, so the
    #      two ledgers cannot disagree. `record_repayment` no longer exists;
    #      tests/test_defi_borrow_ledger_matches_the_loan.py pins its absence.
    #
    #      16-U. THE STALE CONDITION IS CORRECTED IN PLACE RATHER THAN DELETED,
    #      because this is a LIFTING CONDITION — it gates future work, and a
    #      condition naming an already-fixed defect is worse than no condition:
    #      a reader either leaves the gate shut for a reason that has gone away,
    #      or goes looking for `record_repayment`, fails to find it, and learns
    #      to distrust the annotation. This audit's own later fixes invalidate
    #      this audit's own earlier annotations; §AB's sibling.
    #
    #      CLAUSE 1 IS STILL OPEN AND IS ON ITS OWN SUFFICIENT: the operation
    #      still increments a Python dict with no escrow and no chain position,
    #      and does not disclose it. Do not re-register on the strength of
    #      clause 2 alone.
    # Pinned by tests/test_collateral_actions_unexposed.py.
    "cross_chain_bridge": ("cross_border", "bridge_transfer"),
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
    # CLUSTER B: "treasury_transfer" REMOVED. Its gateway route was deleted in
    # Tier 2 as too dangerous to advertise, and this entry kept it reachable
    # through POST /api/v1/capabilities/{id}/invoke, which bypasses `_call`.
    # Deleting a route removes one door of three; the others are here and in
    # the capability catalog. Lifting condition in dao_management/service.py.
    "parameter_change": ("governance", "parameter_change"),
    # ── RWA Expanded ─────────────────────────────────────────────
    "rwa_tokenize": ("rwa_tokenization", "tokenize_asset"),
    "rwa_fractional_buy": ("rwa_tokenization", "fractional_buy"),
    "rwa_income_claim": ("rwa_tokenization", "claim_income"),
    "rwa_verify": ("rwa_tokenization", "verify_provenance"),
    # ── Payments Expanded ────────────────────────────────────────
    "cross_border_remit": ("cross_border", "remit"),
    # ── Privacy ──────────────────────────────────────────────────
    "zk_proof_generate": ("privacy", "generate_zk_proof"),
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
    # NEW-48: private_vote / confidential_compute / arweave_store REMOVED —
    # their methods are gone (no twin to delegate to; see privacy/service.py).
    # The three below are KEPT and now delegate to real external clients.
    # NEW-57: stream_payment / recurring_create / escrow_milestone /
    # payment_split / invoice_factor / payroll_run REMOVED — all six were
    # fabrication-live and moved nothing. No twin: payments.py is a
    # single-transfer primitive, not a batch-disbursement engine.
    "decentralized_store": ("privacy", "decentralized_store"),
    "compute_job_submit": ("privacy", "submit_compute_job"),
    "ipfs_pin": ("privacy", "pin_to_ipfs"),
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
#: DOMAIN 16-K — statuses that mean NOTHING HAPPENED.
#: Every one is an idiom this audit either found or shipped:
#:   not_deployed          the deployment gate refused (NEW-57 family)
#:   error / failed        the service reported a failure
#:   blocked / rejected    a control refused (rate limiter, compliance)
#:   unavailable           the capability is not available in this deployment
#:   recorded_unsettled    15-A — a local record, NO value moved
#:   liquidation_due_unsettled   16-E — a determination, NOT an execution
#:   pending / queued      not yet done; attesting now would assert the future
#: 16-N. A DENY-LIST WAS A CLOSED-WORLD GUESS ABOUT AN OPEN VOCABULARY.
#: The first version of this predicate ended `status not in _NON_OUTCOME_STATUSES`,
#: so any status the list had not anticipated read as a real outcome. On the
#: status axis it FAILED OPEN — the exact inversion of the docstring above it.
#: The vocabulary is not open, though: it is finite and it can be counted. An AST
#: census of every status literal in the 50 packages reachable from
#: `_STATE_MODIFYING_ACTIONS` returns 115 distinct strings. Both sets below are
#: that census, classified. `test_refusals_are_not_attested.py` re-derives it and
#: fails if any status is unclassified, so "unanticipated" is no longer a state
#: this predicate can be in without the suite saying so.
_NON_OUTCOME_STATUSES: frozenset[str] = frozenset({
    # 23-A. `issue_kyc_credential` refuses to attest that a person passed KYC
    # without a screened verification result. Classified explicitly — this test
    # exists precisely to stop a new string acquiring a meaning by accident,
    # and a credential refusal must never read as a credential.
    "not_verified",
    # 21-C. `mint_sound`'s off-chain path runs a GraphQL READ for release
    # metadata and mints nothing. It previously returned "ok" — a REAL-outcome
    # status — so the dispatcher attested a metadata query and published it to
    # the public feed under an action named `mint_sound`. Classified
    # explicitly, not left to the unrecognised-status default, because this
    # test exists precisely to stop a new string from acquiring a meaning by
    # accident.
    "metadata_only",
    # the platform refused, failed, or had nothing to do
    "not_deployed", "error", "failed", "failure", "blocked", "rejected",
    "refused", "declined", "unavailable", "not_available", "unsupported",
    "chain_error", "provider_error", "invalid", "invalid_request",
    "compliance_hold", "denied", "needs_changes", "expired", "grace_period",
    "no_rewards", "no_position", "no_submission", "nothing_to_claim",
    "not_found", "not_started", "none", "already_released", "unknown",
    # not yet done — attesting now would assert the future
    "pending", "queued", "skipped", "noop", "no_op", "pending_verification",
    # this audit's own unsettled idiom: a record was written, no value moved
    "recorded_unsettled", "liquidation_due_unsettled", "calculated_unpaid",
    "recorded_unqueued", "matched_unsettled",
    # PREPARED, UNSIGNED transactions. `auctions._prepared_response`: "The server
    # returns to/data/value/chainId only — it does NOT sign and does NOT
    # broadcast." Identical in kind to `recorded_unsettled`, which was already
    # here; these were missed because the naming convention differs.
    "prepared", "prepared_unsigned",
    # reads and checks. A lookup is not a state change, and attesting one would
    # record an action that no caller performed.
    "found", "known", "queried", "reviewed", "checked", "valid", "suspicious",
    # preconditions unmet / not this deployment's job
    "not_configured", "not_ready", "not_registered", "not_qualified",
    "no_rights_supplied",   # 17-E: a request that set nothing
    "not_settlement", "unresolved", "in_progress", "degraded",
})

#: The other half of the same census: statuses that report a real state change or
#: a broadcast transaction, where "this action happened" is a true claim.
_REAL_OUTCOME_STATUSES: frozenset[str] = frozenset({
    "submitted", "claim_submitted", "confirmed", "deployed", "executed",
    "active", "open", "created", "registered", "proposed", "requested",
    "reserved", "filed", "appealed", "responded", "escalated", "countered",
    "finalized", "processed", "processing", "pending_review", "flagged",
    "accepted", "approved", "completed", "resolved", "resolved_paid",
    "resolved_cancelled", "triggered", "attested", "verified", "assessed",
    "minted", "listed", "published", "purchased", "invested", "funded",
    "released", "refunding", "refunded", "retired", "granted", "issued",
    "sold", "traded", "transferred", "claimed", "deposited", "withdrawn",
    "repaid", "filled", "passed", "entered", "placed", "rented", "bridged",
    "fractionalized", "rights_set", "configured", "generated", "stored",
    "written", "logged", "manufactured", "tracked", "recorded", "sent",
    "following", "updated", "converted", "cancelled", "deactivated",
    "deregistered", "renewed", "authorized", "applied", "rolled_back",
    "reset", "ok", "success", "succeeded", "done",
    # `runtime/blockchain/*.py` — the shared helpers services return through.
    # A first scoping of this census covered `services/<pkg>/` only and could not
    # see them, which is how "success" itself came to be missing from a set whose
    # whole job is naming successes.
    "compiled", "verification_submitted", "source_generated", "payment_attested",
    "routed", "scheduled", "settled", "staked", "unstaked", "supplied",
    "borrowed", "voted", "revoked", "frozen", "started", "qualified",
    "validated", "under_escrow",
})


def _normalise_status(status: Any) -> str:
    """Reduce a status value to the string the classification sets are keyed on.

    `str(LoanStatus.ACTIVE)` is ``"LoanStatus.ACTIVE"``, NOT ``"active"`` — a
    ``(str, Enum)`` member does not stringify to its value. Seven attested
    services return enum members directly (`defi/loans.py`, `defi/p2p_lending.py`,
    `dao_management/treasury.py`, …), so without this every one of them missed
    both sets. Harmless today because those members happen to be successes; a
    single failure member on the same pattern would have been attested as real.
    """
    return str(getattr(status, "value", status)).strip().lower()


def _outcome_is_real(result: Any) -> bool:
    """Did the action actually happen? DOMAIN 16-K's single predicate.

    Governs BOTH the attestation and the feed publish, so the two cannot drift
    apart — domain 8 established the feed is keyed on action name rather than
    result, and gating one without the other is the half-fix this engagement
    keeps catching.

    REFUSALS ANNOUNCE THEMSELVES; SUCCESSES OFTEN DO NOT. That asymmetry is a
    measured property of this codebase, not an assumption, and it decides the
    default.

    MEASURED over the 182 attested actions: 72 carry `status` on every literal
    return; **17 return a SUCCESS with no `status` key at all** —
    `dex.add_liquidity` -> {amount_a, amount_b, pool_id, provider, shares_minted},
    `loyalty.earn_points` -> {points_earned, balance, program_id, ...},
    `dao_management.join_dao` -> {dao_id, member, member_count}. Meanwhile every
    refusal idiom this audit found or shipped is EXPLICIT: `not_deployed`,
    `status: "error"`, `recorded_unsettled`, `liquidation_due_unsettled`.

    So absence of a status field is evidence of SUCCESS, not of refusal.

    A FIRST VERSION OF THIS PREDICATE GOT THAT BACKWARDS, and the mistake is
    worth keeping. It treated a missing `status` as "cannot tell -> do not
    attest", reasoning that an unrecorded truth is recoverable while a recorded
    falsehood is not. That principle is right; it was applied to the wrong axis.
    Measuring rather than reasoning showed it would have silently stopped
    attesting 17 genuine actions — inventing an evidence GAP across a sixth of
    the surface in the name of preventing a false record. "Fail closed" is only
    safe when you have correctly identified which direction "closed" is.

    THAT ASYMMETRY DECIDES ONE AXIS ONLY, AND A LATER PASS FOUND IT APPLIED TO
    TWO. Absence of a status is evidence of success. A status that is PRESENT but
    unrecognised is not evidence of anything, and the first version of this
    predicate — `status not in _NON_OUTCOME_STATUSES` — read it as success. The
    deny-list held 18 strings; the services emit 115. So the two axes now have
    two different defaults, each measured rather than reasoned:

      * no `status` key                -> REAL   (17 of 182 actions; measured)
      * `status` present, unrecognised -> NOT REAL

    WHY THIS PREDICATE CANNOT BE STRING-BASED AT ALL — the argument, stated here
    rather than left for a reader to reconstruct. `"pending"` is returned by
    `insurance.process_claim` to mean "reserve insufficient, the claim was NOT
    paid", and by `x402.create_payment` to mean "the payment record was created
    and persisted". **Both are honest. Their meanings are opposite. No
    classification of the STRING is correct for both**, so the string cannot be
    the only evidence consulted, and any predicate that tries will be wrong for
    one of them no matter which way it is set. Only the service can break the
    tie, by stating positively that it acted — which is what `created: True` is.

    and the classification itself is a census rather than a guess, held in place
    by a test that re-derives it. 15-A's disclosure flags still outrank both,
    because they are the field that was added to be honest.

    Non-dicts and None still return False: they are not this codebase's success
    idiom, they carry no refusal vocabulary to check, and no attested action
    returns one on its success path.
    """
    if not isinstance(result, dict):
        return False

    # 15-A's disclosure flags outrank the status string: a record that says
    # settled=False is telling you plainly that nothing moved, even if some
    # other field reads optimistically.
    if result.get("settled") is False or result.get("value_moved") is False:
        return False

    # 16-O. POSITIVE EVIDENCE OUTRANKS A LIFECYCLE STATUS.
    # A record-creating action reports the NEW RECORD's status, not its own
    # disposition. `x402.create_payment` mints a payment id, signs the header and
    # persists the record, then returns the payment's real lifecycle state,
    # "pending" — because NEW-56, an earlier fix in this same audit, stopped it
    # overwriting that field with "created". Without this branch, that honesty fix
    # reads as a refusal and a genuine, durable action loses its record. The two
    # meanings are not separable from the string: `insurance` returns
    # "pending" for "reserve insufficient, claim NOT paid" — a true refusal — and
    # both are correct. Only the service can break the tie, and `created: True` is
    # it saying so. It does not outrank 15-A's flags: those report that no value
    # moved, which is a different and stronger claim than "a record now exists".
    if result.get("created") is True:
        return True

    status = result.get("status")
    if status is None:
        return True  # no refusal vocabulary present -> a plain success shape

    s = _normalise_status(status)
    if s in _NON_OUTCOME_STATUSES:
        return False
    if s in _REAL_OUTCOME_STATUSES:
        return True

    # PRESENT BUT UNRECOGNISED -> NOT AN OUTCOME. The measured asymmetry that
    # decides the `status is None` case above does NOT extend to here: a service
    # that bothered to name a status is precisely the case where absence of
    # evidence is not evidence. Falling through to True is what let
    # `compliance_hold` be attested and published to the public feed as a
    # completed $5,000 payment that compliance had in fact refused.
    return False


_STATE_MODIFYING_ACTIONS: frozenset[str] = frozenset({
    "convert_contract", "create_loan", "repay_loan",
    "mint_nft", "create_nft_collection", "transfer_nft", "list_nft_for_sale",
    "buy_nft", "set_nft_rights", "configure_nft_royalty",
    "tokenize_asset", "transfer_rwa_ownership",
    "create_did", "update_did", "deactivate_did",
    "create_dao", "join_dao", "leave_dao",
    "transfer_stablecoin",
    "create_attestation", "revoke_attestation", "batch_attest",
    "register_agent", "update_agent", "deregister_agent",
    # NEW-53: authorize_payment / refund_payment removed — disabled at
    # ACTION_MAP pending identity + ownership verification.
    "create_payment", "complete_payment",
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
    # NEW-38: "execute_deletion" removed — no longer an action. "request_deletion"
    # stays in the state-modifying set even though it now modifies nothing:
    # over-classifying is the safe direction here, and if a real erasure path is
    # ever built this is the entry that must already be gated.
    "request_deletion",
    "file_dispute", "submit_dispute_evidence", "resolve_dispute", "appeal_dispute",
    # ── Expanded state-modifying actions ─────────────────────────
    # NEW-61: the ten removed defi fabrications are gone from here too.
    #
    # NEW-64: deposit_collateral / withdraw_collateral removed from this set
    # as well, not only from ACTION_MAP. Membership here is what makes
    # execute() call _attest_action() and publish to the social feed, so an
    # unremoved entry would keep minting attestations for a dict increment
    # even after the action itself was unregistered. Removing an action from
    # one table and leaving it in the table that grants it authority is the
    # same half-removal that left dangling handlers in domain 4.
    "cross_chain_bridge",
    "nft_fractionalize", "nft_rent", "nft_dynamic_update", "nft_batch_mint",
    "nft_royalty_claim", "nft_bridge", "did_create", "credential_issue",
    "soulbound_mint", "timelock_queue", "multisig_propose", "multisig_approve",
    "snapshot_vote", "parameter_change",   # CLUSTER B: treasury_transfer removed
    "rwa_tokenize", "rwa_fractional_buy", "rwa_income_claim",
    "cross_border_remit",
    "zk_proof_generate",  # NEW-48: private_vote + confidential_compute removed
    "social_post", "social_gate", "creator_monetize",
    "community_create", "message_encrypt",
    "game_asset_mint", "tournament_enter", "game_item_trade", "achievement_attest",
    "market_create", "market_bet", "market_resolve",
    "provenance_log", "batch_track", "custody_transfer",
    "parametric_policy", "claim_auto_settle", "cover_renew",
    "decentralized_store", "compute_job_submit", "ipfs_pin",  # NEW-48: arweave_store removed
    "ai_agent_register", "ai_model_trade", "training_data_sell",
    "carbon_credit_buy", "carbon_credit_retire", "renewable_cert_buy", "green_bond_invest",
    "ip_license_grant", "agreement_execute", "dispute_file", "arbitration_request",
})

ACTION_TO_FEED_EVENT: dict[str, str] = {
    # Existing actions
    # NEW-4: `deploy_contract` mapped to a `contract_deployed` feed event
    # while dispatching to contract_conversion.convert, which deploys
    # nothing. A conversion was announced to the social feed as a
    # deployment. Removed with the capability itself.
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
    # NEW-61: yield_optimize / flash_loan / liquidity_provide / vault_deposit
    # / perp_trade feed events removed with their fabrications. A feed event
    # is a public claim that something happened; these announced events for
    # operations that never occurred.
    # NEW-88: `cross_chain_bridge` -> "bridge_completed" REMOVED. This is an
    # independent defect from the fabrication behind it and it survives fixing
    # that method, so it is fixed on its own terms: the method's own literal
    # was "bridging" — an IN-PROGRESS claim — and this table upgraded it to
    # COMPLETED and published that upgrade to the public social feed. Even a
    # perfectly honest bridge that returned "submitted" would have been
    # announced here as finished.
    #
    # LIFTING CONDITION: a feed event for bridging may be restored only when
    # it is DERIVED from a settlement result (a confirmed destination-chain
    # receipt), never from the fact that a request was accepted. Same rule as
    # the NEW-61 removals above.
    "nft_fractionalize": "nft_fractionalized",
    "nft_batch_mint": "nft_batch_minted",
    "nft_bridge": "nft_bridged",
    "rwa_tokenize": "rwa_tokenized",
    # NEW-10: `tokenize_asset` routes to the SAME service method as
    # `rwa_tokenize` but published nothing, so whether this state change
    # was recorded depended on which name the caller happened to use.
    "tokenize_asset": "rwa_tokenized",
    "rwa_fractional_buy": "rwa_purchased",
    "did_create": "did_created",
    "credential_issue": "credential_issued",
    "soulbound_mint": "soulbound_minted",
    "market_create": "prediction_market_created",
    "market_bet": "prediction_bet_placed",
    "market_resolve": "prediction_market_resolved",
    "carbon_credit_buy": "carbon_credit_purchased",
    "carbon_credit_retire": "carbon_credit_retired",
    "social_post": "social_post_published",
    "community_create": "community_created",
    "ai_agent_register": "ai_agent_registered",
    # NEW-10: `register_agent` routes to the SAME service method as
    # `ai_agent_register` but published nothing, so whether this state change
    # was recorded depended on which name the caller happened to use.
    "register_agent": "ai_agent_registered",
    "decentralized_store": "file_stored",
    "ipfs_pin": "ipfs_content_pinned",
    "game_asset_mint": "game_asset_minted",
    # NEW-10: `mint_game_asset` routes to the SAME service method as
    # `game_asset_mint` but published nothing, so whether this state change
    # was recorded depended on which name the caller happened to use.
    "mint_game_asset": "game_asset_minted",
    "tournament_enter": "tournament_entered",
    "achievement_attest": "achievement_attested",
    "provenance_log": "provenance_logged",
    "custody_transfer": "custody_transferred",
    # NEW-10: `transfer_custody` routes to the SAME service method as
    # `custody_transfer` but published nothing, so whether this state change
    # was recorded depended on which name the caller happened to use.
    "transfer_custody": "custody_transferred",
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
    """Bridge between Trinity's tool calls and the 221 capabilities (44 backing services).

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
                "  create_payment, complete_payment\n\n"

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
                # NEW-38: "privacy (request_deletion)" removed from what the
                # model is told it can do. The action still exists and still
                # answers, but the answer is "not available" — advertising it
                # here would have the agent offer erasure and then dead-end.
                "disputes (file_dispute, resolve_dispute)."
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
        *,
        caller_identity: str = "",
        caller_source: str = "",
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
        caller_identity:
            The AUTHENTICATED wallet address of the caller, or "" when the
            entry point has none. See DOMAIN 17-D below. Keyword-only and
            defaulting to "" so every existing call site — including the
            positional ``execute(action, None, params)`` in
            ``runtime/agents/handoff.py`` — keeps working unchanged.

        Returns
        -------
        str
            JSON-encoded result dict with ``status``, ``action``, ``result``,
            and timing information.
        """
        # ── DOMAIN 17-D ────────────────────────────────────────────────────
        # THE CALLER'S IDENTITY WAS KNOWN AND THEN THROWN AWAY.
        #
        # `gateway/bridge.py` reads the session's linked wallet and binds it
        # into the security context (`bind_request_security(identity=...)`)
        # BEFORE calling this method — and then called `execute(action, params)`
        # with no identity at all. So the wallet existed, one frame up, and the
        # service decided without it. Two surfaces went blind at once:
        #
        #   AUTHORITY — the service is asked to move an IP right and cannot see
        #     who asked. `set_rights` grants `commercial` on any token to any
        #     holder for anyone who can reach the dispatcher.
        #   EVIDENCE — the actor written to the attestation and to the PUBLIC
        #     social feed fell back to `""`. The platform's own record said a
        #     right moved and could not say who moved it.
        #
        # Both are fixed here, in one change, because a fix that lands one and
        # not the other leaves the trail lying about a grant it can still not
        # attribute.
        #
        # WHAT THIS IS NOT. This does not check OWNERSHIP, and must not be read
        # as doing so. This platform holds NO ownership record — see the NFT
        # GATING CONDITION in nft_services/service.py: `NFTFactory._collections`
        # is a cache with a declaration, two reads and ZERO writers (verified
        # again for this change). Checking a caller against a store that does
        # not exist would fabricate a control, which is worse than the gap it
        # covers. This change supplies the IDENTITY an ownership check would
        # need; the ownership half is deployment-gate-plus-honest-refusal and is
        # tracked separately.
        start = time.time()
        params = params or {}

        # 17-J. AN EMPTY ACTOR WAS THREE FACTS WEARING ONE VALUE: no human
        # initiated this (agent hand-off — "" is CORRECT); a human initiated it
        # and the identity was DROPPED (17-D's defect); a human initiated it and
        # was anonymous. The first two rendered identically, so THE 17-D FIX
        # COULD NOT DEMONSTRATE ITS OWN SUCCESS FROM THE TRAIL.
        #
        # DERIVED FROM `caller_identity` ALONE, never from `_actor`. `_actor`
        # falls back to `params["wallet"]`, which is SELF-ASSERTED on the bridge
        # path — labelling that "authenticated" would be exactly the fabrication
        # this field exists to prevent. The source describes the CHANNEL the
        # identity arrived through, not whether some address is present.
        _actor_source = (
            "authenticated" if caller_identity
            else (caller_source or "unauthenticated")
        )

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
            "Dispatching action=%s -> %s.%s  params=%s  caller=%s",
            action, target_service, method_name, list(params.keys()),
            caller_identity or "<unauthenticated>",
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

            # 17-D. HAND THE IDENTITY TO THE SERVICE — ONLY WHERE IT ASKED.
            #
            # Injection is gated on the target method's own signature: the
            # parameter is passed if and only if the method declares a
            # parameter literally named `caller_identity`. A method that has
            # not opted in is called exactly as before, so none of the ~219
            # existing actions can break on this.
            #
            # WHY SIGNATURE INJECTION AND NOT A ContextVar. A ContextVar (the
            # shape `gateway/security_gate.py` uses for the security context)
            # would be less code, but it is bound at ONE of the four entry
            # points that reach this dispatcher — the other three
            # (capabilities/registry.py, agents/handoff.py, tools/dispatcher.py)
            # never bind it, so a service reading it would silently see the
            # PREVIOUS request's identity or nothing, with no signature to say
            # so. Declaring the parameter makes the dependency visible in the
            # service's own API, works identically from all four entry points,
            # and is checkable by `inspect`.
            #
            # THE AUTHENTICATED VALUE OVERWRITES, IT DOES NOT DEFAULT. `params`
            # is attacker-controlled — it is the request body on the bridge
            # path. If a client-supplied `params["caller_identity"]` were left
            # to stand when the real identity is unknown, this fix would ship a
            # brand-new spoofing primitive: assert any address, have the
            # platform record it. So the threaded value ALWAYS wins, including
            # when it is "" — an unauthenticated call records "unknown", never
            # a self-asserted address.
            if _method_accepts_caller_identity(method):
                params = {**params, "caller_identity": caller_identity or "",
                          "caller_source": _actor_source}

            result = await method(**params)

            # 17-D (evidence half). WHO the record says acted.
            #
            # This was computed inside the feed block as
            #     params.get("wallet") or params.get("address") or ""
            # so `set_nft_rights` — whose params are collection/token_id/rights
            # and contain neither key — was attested and published with
            # actor "". Hoisted out of the feed block so the ATTESTATION and
            # the FEED are attributed from one value: attributing the public
            # feed and leaving the audit record anonymous is the half-fix.
            #
            # Order is deliberate and conservative: the existing params-derived
            # actor keeps precedence so no currently-attributed action changes
            # who it names, and the authenticated identity is the FALLBACK that
            # fills the "" hole. Note the residual — a client-supplied `wallet`
            # param still outranks the authenticated caller on this surface.
            # That is a pre-existing attribution weakness, wider than 17-D
            # (it touches every state-modifying action), and is not narrowed
            # here.
            _actor = (
                params.get("wallet")
                or params.get("address")
                or caller_identity
                or ""
            )


            # ── DOMAIN 16-K ────────────────────────────────────────────────
            # THE ATTESTATION LAYER DID NOT CHECK WHETHER ANYTHING HAPPENED.
            # Membership in _STATE_MODIFYING_ACTIONS was the ENTIRE condition;
            # `result` was read only to pull tx_hash into the feed payload,
            # never to decide whether to record. So every refusal — every
            # `not_deployed`, every `status: "error"`, every honest decline this
            # audit shipped — was attested and published AS AN ACTION TAKEN.
            #
            # Measured: 182 attested actions, of which 62 return an honest
            # refusal. The system's mechanism for recording that something
            # happened did not check whether it happened.
            #
            # KEYED ON THE RESULT, NOT ON DISPOSITION STYLE. A raised refusal
            # never reached this block (the exception unwinds past it) while a
            # returned one always did — so the clean subset was clean only
            # because raise-vs-return was picked on local ergonomics, sixteen
            # domains deep, never once on attestation behaviour. A style-keyed
            # rule can be got wrong by accident by a future fix. This one cannot.
            #
            # BOTH SURFACES, ONE PREDICATE. Domain 8 established the feed is
            # keyed on ACTION NAME rather than result, so gating the attestation
            # alone would leave the feed announcing refusals — the half-fix this
            # engagement keeps catching (15-A's log line, 16-I's third entry
            # point). `_outcome_is_real` governs both.
            #
            # THE REFUSAL IS STILL RECORDED, AS A REFUSAL. Suppressing it would
            # trade a false record for no record, which is the same defect facing
            # the other way: an audit trail must show that the system DECLINED,
            # not that nothing occurred.
            if action in _STATE_MODIFYING_ACTIONS:
                _happened = _outcome_is_real(result)

                if _happened:
                    await self._attest_action(
                        action, target_service, params, result, actor=_actor,
                        actor_source=_actor_source,
                    )
                else:
                    await self._attest_refusal(
                        action, target_service, params, result, actor=_actor,
                        actor_source=_actor_source,
                    )

                # Fire-and-forget: publish to the social feed.
                # Never blocks the response — failures are logged and
                # swallowed inside SocialFeedEngine.ingest().
                # A REFUSAL IS NOT AN ACTIVITY: nothing happened, so nothing is
                # announced. The refusal is still recorded above, where an audit
                # trail belongs; the public feed is a different surface with a
                # different contract.
                if _happened and self._feed_engine is not None:
                    _component_id = None
                    try:
                        from extensions import registry as _reg
                        _component_id = _reg.service_to_component(target_service)
                    except Exception:
                        pass
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

    async def _attest_refusal(
        self,
        action: str,
        service_name: str,
        params: dict,
        result: Any,
        *,
        actor: str = "",
        actor_source: str = "",
    ) -> None:
        """Record that the platform DECLINED to act — as a decline.

        DOMAIN 16-K. The counterpart to `_attest_action`. A refusal that leaves
        no trace is not an improvement over a refusal recorded as a success: an
        auditor reading the trail must be able to tell "the system declined" from
        "nothing was ever asked". Both are answers; only one of them is silence.

        Deliberately a LOG record rather than an EAS attestation. An on-chain
        attestation costs gas and asserts a fact to third parties; "we declined
        because contracts are not deployed" is an operational event, not a
        counterparty-facing claim. If a deployment ever needs refusals on-chain
        that is a product decision, and this is the seam it would hang from.
        """
        # 16-N. REPORT WHAT WAS OBSERVED, NOT THE NEGATIVE FACT IT IMPLIES.
        # This line used to end "— the platform did not perform this action",
        # which is an unqualified assertion derived entirely from the predicate.
        # 16-N found two cases where the predicate was wrong in each direction,
        # and in the create_payment direction this log was the ONLY output: a
        # genuine, persisted payment recorded as something that did not happen.
        # A wrong predicate should leave a gap in the trail, not a falsehood in
        # it — the same principle the attestation path is built on, applied to
        # the path that runs when the attestation path declines.
        _status = result.get("status") if isinstance(result, dict) else None
        # 17-D. A refusal names WHO was refused. "The system declined" is only
        # half an audit record if it cannot say who it declined.
        logger.info(
            "ACTION DECLINED (not attested, not published): action=%s service=%s "
            "actor=%s status=%s — no outcome evidence in the service result",
            action, service_name, actor or "<unknown>", _status,
        )

    async def _attest_action(
        self,
        action: str,
        service_name: str,
        params: dict,
        result: Any,
        *,
        actor: str = "",
        actor_source: str = "",
    ) -> None:
        """Record an EAS attestation for a state-modifying action."""
        try:
            registry = self._get_registry()
            attestation_svc = registry.get("attestation")
            # NEW-42 (instance 1 of 2): this passed `schema_name=`, but
            # AttestationService.attest takes `schema_uid`. EVERY call raised
            # TypeError and was swallowed by the `except` below as a WARNING,
            # so NO state-modifying action on the platform has ever been
            # attested. Signature drift plus a silent swallow — the NEW-9
            # shape. "" resolves to the primary platform schema via
            # `_resolve_schema`, which is what this call always meant.
            # 17-D. THE ATTESTATION NOW NAMES THE ACTOR.
            #
            # This payload recorded action, service, a params hash and a
            # timestamp — everything except WHO. An attestation that a right
            # was granted, with the grantor unrecoverable (a hash is not a
            # name), is the evidence half of the same defect the authority half
            # fixes upstream. Empty string is written when the entry point had
            # no authenticated identity: the record says "unknown", which is a
            # fact, rather than omitting the field, which reads as "not
            # applicable".
            #
            # `recipient` is deliberately UNCHANGED. In EAS the recipient is the
            # SUBJECT of the attestation, not its author; repointing it at the
            # caller would silently redefine what all ~182 attested actions
            # assert to third parties, which is a product decision and a
            # separate change. The actor is carried in the payload, where the
            # authorship claim belongs.
            await attestation_svc.attest(
                schema_uid="",
                data={
                    "action": action,
                    "service": service_name,
                    "actor": actor or "",
                    "actor_source": actor_source or "unauthenticated",
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
