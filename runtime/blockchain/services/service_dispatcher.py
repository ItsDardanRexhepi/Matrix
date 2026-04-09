"""
Service Dispatcher — routes Trinity's natural language intents to the correct
blockchain service. This is what makes all 30 components user-facing.

Trinity's ReAct loop calls tools. This dispatcher registers one mega-tool
'platform_action' that can invoke any of the 30 services based on the action name.
"""

from __future__ import annotations

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
})


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

    def _get_neosafe(self):
        """Lazily initialise the NeoSafe fee router."""
        if self._neosafe is None:
            from runtime.blockchain.services.neosafe import NeoSafeRouter
            self._neosafe = NeoSafeRouter(self._config)
        return self._neosafe

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
