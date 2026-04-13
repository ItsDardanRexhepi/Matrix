"""
Service API Routes — exposes the complete Web3 surface as REST endpoints.
Each service gets its own endpoint group under /api/v1/

This module also owns two cross-cutting endpoints that power the MTRX
iOS Packager:

* ``POST /api/v1/batch`` — execute multiple service calls in one round
  trip (see :meth:`ServiceRoutes._handle_batch`).
* ``GET /api/v1/events/stream`` — Server-Sent Events fan-out for live
  price updates, transaction status, and alerts (see
  :meth:`ServiceRoutes._handle_event_stream`).
"""

from __future__ import annotations

import asyncio
import json
import logging
import re
import time
from typing import Any, Awaitable, Callable, List, Optional, Tuple

from aiohttp import web

from gateway.event_broadcaster import (
    BroadcastEvent,
    BroadcasterCapacityError,
    EventBroadcaster,
)

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Batch sub-request machinery
# ---------------------------------------------------------------------------

#: Number of batch items an iOS client can ask for in one POST.
BATCH_MAX_ITEMS = 25

#: Hard ceiling on how long a batch item can spend inside a single sub
#: call before we time it out and move on. Keeps one slow service from
#: holding up the whole batch.
BATCH_ITEM_TIMEOUT_SECONDS = 20.0


class _BatchSubRequest:
    """A minimal aiohttp.web.Request look-alike used for batch dispatch.

    The real handlers only touch ``request.json()`` and
    ``request.match_info``; we re-implement that tiny surface so we can
    invoke them directly without spinning up an actual HTTP round trip.
    """

    __slots__ = ("_body", "match_info", "headers", "method", "path")

    def __init__(
        self,
        *,
        body: Any,
        match_info: dict,
        method: str,
        path: str,
        headers: Optional[dict] = None,
    ) -> None:
        self._body = body if body is not None else {}
        self.match_info = match_info
        self.headers = headers or {}
        self.method = method
        self.path = path

    async def json(self) -> Any:
        return self._body


class ServiceRoutes:
    """Register REST endpoints for every blockchain service.

    Each endpoint parses the JSON request body, calls the corresponding
    service method via :class:`ServiceRegistry`, and returns a JSON
    response with appropriate HTTP status codes.
    """

    def __init__(
        self,
        config: dict,
        broadcaster: Optional[EventBroadcaster] = None,
        metrics: Optional[Any] = None,
        bridge_routes: Optional[Any] = None,
    ) -> None:
        self._config = config
        self._registry = None  # lazy
        self._broadcaster = broadcaster or EventBroadcaster()
        self._metrics = metrics
        #: Reference to the ``BridgeRoutes`` instance so the batch
        #: dispatcher can forward ``/bridge/v1/*`` items through the same
        #: in-process fast path used for ``/api/v1/*``. Set by the
        #: gateway server right after both ServiceRoutes and BridgeRoutes
        #: exist — see :meth:`attach_bridge_routes`.
        self._bridge_routes = bridge_routes
        if metrics is not None:
            self._broadcaster.attach_metrics(metrics)
        #: (method, compiled_regex, param_names, handler, literal_path)
        self._batch_routes: List[
            Tuple[str, re.Pattern, List[str], Callable[..., Awaitable[web.Response]], str]
        ] = []

    # -- post-construction wiring --------------------------------------

    def attach_metrics(self, metrics: Any) -> None:
        """Attach a metrics collector after the fact.

        Used by :class:`GatewayServer` when it constructs the service
        routes inside ``create_app`` but only finishes wiring metrics a
        few lines later.
        """

        self._metrics = metrics
        self._broadcaster.attach_metrics(metrics)

    def attach_bridge_routes(self, bridge_routes: Any) -> None:
        """Give the batch dispatcher access to the bridge handlers.

        The gateway server creates the ``ServiceRoutes`` first, then
        constructs ``BridgeRoutes`` (which takes the server as a
        dependency), then calls this hook so ``/api/v1/batch`` can
        transparently dispatch ``/bridge/v1/*`` sub-requests without a
        second HTTP round trip.
        """

        self._bridge_routes = bridge_routes
        # Rebuild the route map so the bridge entries get compiled in.
        self._build_batch_route_map()

    def _metric_incr(self, name: str, value: int = 1) -> None:
        if self._metrics is None:
            return
        try:
            self._metrics.incr(name, value)
        except Exception:  # pragma: no cover — telemetry must never raise
            pass

    def _metric_observe(self, name: str, value: float) -> None:
        if self._metrics is None:
            return
        try:
            observer = getattr(self._metrics, "observe", None)
            if callable(observer):
                observer(name, value)
        except Exception:  # pragma: no cover
            pass

    def _get_registry(self):
        if self._registry is None:
            from runtime.blockchain.services.registry import ServiceRegistry
            self._registry = ServiceRegistry(self._config)
        return self._registry

    # -- broadcaster accessor ------------------------------------------

    @property
    def broadcaster(self) -> EventBroadcaster:
        return self._broadcaster

    # ------------------------------------------------------------------
    # Route registration
    # ------------------------------------------------------------------

    def register_routes(self, app: web.Application) -> None:
        """Add all service routes to *app*."""

        # Contracts (Component 1)
        app.router.add_post("/api/v1/contracts/convert", self._handle_contract_convert)
        app.router.add_post("/api/v1/contracts/deploy", self._handle_contract_deploy)

        # DeFi (Component 2)
        app.router.add_post("/api/v1/defi/loan/create", self._handle_defi_loan_create)
        app.router.add_post("/api/v1/defi/loan/repay", self._handle_defi_loan_repay)

        # NFT (Component 3)
        app.router.add_post("/api/v1/nft/mint", self._handle_nft_mint)
        app.router.add_post("/api/v1/nft/collection/create", self._handle_nft_collection_create)

        # RWA (Component 4)
        app.router.add_post("/api/v1/rwa/tokenize", self._handle_rwa_tokenize)

        # Identity / DID (Component 5)
        app.router.add_post("/api/v1/identity/create", self._handle_did_create)

        # DAO (Component 6)
        app.router.add_post("/api/v1/dao/create", self._handle_dao_create)

        # Stablecoin (Component 7)
        app.router.add_post("/api/v1/stablecoin/transfer", self._handle_stablecoin_transfer)

        # Staking (Component 16)
        app.router.add_post("/api/v1/staking/stake", self._handle_staking_stake)
        app.router.add_post("/api/v1/staking/unstake", self._handle_staking_unstake)

        # DEX (Component 21)
        app.router.add_post("/api/v1/dex/swap", self._handle_dex_swap)
        app.router.add_post("/api/v1/dex/liquidity/add", self._handle_dex_add_liquidity)

        # Insurance (Component 13)
        app.router.add_post("/api/v1/insurance/policy/create", self._handle_insurance_create)
        app.router.add_post("/api/v1/insurance/claim", self._handle_insurance_claim)

        # Marketplace (Component 24)
        app.router.add_post("/api/v1/marketplace/list", self._handle_marketplace_list)
        app.router.add_post("/api/v1/marketplace/buy", self._handle_marketplace_buy)

        # Governance (Component 19)
        app.router.add_post("/api/v1/governance/proposal/create", self._handle_governance_create)
        app.router.add_post("/api/v1/governance/vote", self._handle_governance_vote)

        # Dispute Resolution (Component 30)
        app.router.add_post("/api/v1/dispute/file", self._handle_dispute_file)

        # Social (Component 28)
        app.router.add_post("/api/v1/social/message", self._handle_social_message)
        app.router.add_post("/api/v1/social/profile", self._handle_social_profile)

        # Fundraising (Component 22)
        app.router.add_post("/api/v1/fundraising/campaign/create", self._handle_fundraising_create)
        app.router.add_post("/api/v1/fundraising/contribute", self._handle_fundraising_contribute)

        # Subscriptions (Component 27)
        app.router.add_post("/api/v1/subscriptions/subscribe", self._handle_subscribe)

        # Loyalty (Component 23)
        app.router.add_post("/api/v1/loyalty/earn", self._handle_loyalty_earn)
        app.router.add_post("/api/v1/loyalty/redeem", self._handle_loyalty_redeem)

        # Cashback (Component 25)
        app.router.add_post("/api/v1/cashback/track", self._handle_cashback_track)

        # Brand Rewards (Component 26)
        app.router.add_post("/api/v1/brand/campaign/create", self._handle_brand_campaign_create)

        # Privacy (Component 29)
        app.router.add_post("/api/v1/privacy/delete", self._handle_privacy_delete)

        # Cross-Border (Component 17)
        app.router.add_post("/api/v1/crossborder/send", self._handle_crossborder_send)

        # Securities (Component 18)
        app.router.add_post("/api/v1/securities/create", self._handle_securities_create)

        # Supply Chain (Component 12)
        app.router.add_post("/api/v1/supply-chain/register", self._handle_supply_chain_register)

        # Gaming (Component 14)
        app.router.add_post("/api/v1/gaming/register", self._handle_gaming_register)

        # IP & Royalties (Component 15)
        app.router.add_post("/api/v1/ip/register", self._handle_ip_register)

        # Agent Identity (Component 9)
        app.router.add_post("/api/v1/agent/register", self._handle_agent_register)

        # x402 Payments (Component 10)
        app.router.add_post("/api/v1/payments/create", self._handle_payment_create)

        # Dashboard (Component 20) — GET
        app.router.add_get("/api/v1/dashboard/{address}", self._handle_dashboard)

        # Oracle (Component 11) — GET
        app.router.add_get("/api/v1/oracle/price/{pair}", self._handle_oracle_price)

        # Attestation (Component 8) — GET
        app.router.add_get("/api/v1/attestation/verify/{uid}", self._handle_attestation_verify)

        # ── DeFi Expanded ────────────────────────────────────────────
        app.router.add_post("/api/v1/defi/yield/optimize", self._handle_yield_optimize)
        app.router.add_post("/api/v1/defi/swap/route", self._handle_swap_route)
        app.router.add_post("/api/v1/defi/swap/execute", self._handle_swap_execute)
        app.router.add_post("/api/v1/defi/bridge/quote", self._handle_bridge_quote)
        app.router.add_post("/api/v1/defi/bridge/execute", self._handle_bridge_execute)
        app.router.add_post("/api/v1/defi/flash-loan/execute", self._handle_flash_loan)
        app.router.add_post("/api/v1/defi/vault/deposit", self._handle_vault_deposit)
        app.router.add_post("/api/v1/defi/liquidity/provide", self._handle_liquidity_provide)
        app.router.add_post("/api/v1/defi/perp/trade", self._handle_perp_trade)
        app.router.add_post("/api/v1/defi/collateral/manage", self._handle_collateral_manage)

        # ── NFT Expanded ─────────────────────────────────────────────
        app.router.add_post("/api/v1/nft/fractionalize", self._handle_nft_fractionalize)
        app.router.add_post("/api/v1/nft/rent", self._handle_nft_rent)
        app.router.add_post("/api/v1/nft/batch-mint", self._handle_nft_batch_mint)
        app.router.add_post("/api/v1/nft/royalty/claim", self._handle_nft_royalty_claim)
        app.router.add_post("/api/v1/nft/bridge", self._handle_nft_bridge)

        # ── Identity ─────────────────────────────────────────────────
        app.router.add_post("/api/v1/identity/did/create", self._handle_identity_did_create)
        app.router.add_post("/api/v1/identity/credential/issue", self._handle_credential_issue)
        app.router.add_post("/api/v1/identity/credential/verify", self._handle_credential_verify)
        app.router.add_post("/api/v1/identity/zk-proof/generate", self._handle_zk_proof)
        app.router.add_post("/api/v1/identity/soulbound/mint", self._handle_soulbound_mint)

        # ── Social ───────────────────────────────────────────────────
        app.router.add_post("/api/v1/social/post", self._handle_social_post)
        app.router.add_post("/api/v1/social/message/send", self._handle_social_message_send)
        app.router.add_post("/api/v1/social/gate/create", self._handle_social_gate)
        app.router.add_post("/api/v1/social/community/create", self._handle_community_create)
        app.router.add_get("/api/v1/social/feed/{wallet}", self._handle_social_feed)

        # ── Payments Expanded ────────────────────────────────────────
        app.router.add_post("/api/v1/payments/stream/create", self._handle_stream_create)
        app.router.add_post("/api/v1/payments/recurring/create", self._handle_recurring_create)
        app.router.add_post("/api/v1/payments/escrow/milestone", self._handle_escrow_milestone)
        app.router.add_post("/api/v1/payments/split", self._handle_payment_split)
        app.router.add_post("/api/v1/payments/payroll", self._handle_payroll_run)

        # ── Compute & Storage ────────────────────────────────────────
        app.router.add_post("/api/v1/compute/store", self._handle_decentralized_store)
        app.router.add_post("/api/v1/compute/ipfs/pin", self._handle_ipfs_pin)
        app.router.add_post("/api/v1/compute/arweave/store", self._handle_arweave_store)

        # ── RWA ──────────────────────────────────────────────────────
        app.router.add_post("/api/v1/rwa/fractional/buy", self._handle_rwa_fractional_buy)
        app.router.add_get("/api/v1/rwa/listings", self._handle_rwa_listings)

        # ── Prediction Markets ──────────────────────────────────────
        app.router.add_post("/api/v1/prediction/market/create", self._handle_market_create)
        app.router.add_post("/api/v1/prediction/market/bet", self._handle_market_bet)
        app.router.add_get("/api/v1/prediction/market/list", self._handle_market_list)

        # ── Energy ───────────────────────────────────────────────────
        app.router.add_post("/api/v1/energy/carbon/buy", self._handle_carbon_buy)
        app.router.add_post("/api/v1/energy/carbon/retire", self._handle_carbon_retire)
        app.router.add_get("/api/v1/energy/carbon/prices", self._handle_carbon_prices)

        # ── Governance Expanded ──────────────────────────────────────
        app.router.add_post("/api/v1/governance/multisig/propose", self._handle_multisig_propose)
        app.router.add_post("/api/v1/governance/multisig/approve", self._handle_multisig_approve)
        app.router.add_post("/api/v1/governance/snapshot/vote", self._handle_snapshot_vote)
        app.router.add_post("/api/v1/governance/treasury/transfer", self._handle_treasury_transfer)

        # ── Portfolio ────────────────────────────────────────────────
        app.router.add_get("/api/v1/portfolio/complete/{wallet}", self._handle_portfolio_complete)
        app.router.add_get("/api/v1/portfolio/positions/{wallet}", self._handle_portfolio_positions)
        app.router.add_get("/api/v1/portfolio/history/{wallet}", self._handle_portfolio_history)

        # ── Intent Resolution ────────────────────────────────────────
        app.router.add_post("/api/v1/intent/resolve", self._handle_intent_resolve)
        app.router.add_post("/api/v1/intent/execute", self._handle_intent_execute)
        app.router.add_get("/api/v1/intent/summary/{plan_id}", self._handle_intent_summary)

        # ── Legal ────────────────────────────────────────────────────
        app.router.add_post("/api/v1/legal/license/grant", self._handle_license_grant)
        app.router.add_post("/api/v1/legal/agreement/execute", self._handle_agreement_execute)
        app.router.add_post("/api/v1/legal/dispute/file", self._handle_legal_dispute_file)

        # ── AI ───────────────────────────────────────────────────────
        app.router.add_post("/api/v1/ai/agent/register", self._handle_ai_agent_register)
        app.router.add_post("/api/v1/ai/model/trade", self._handle_ai_model_trade)

        # ── Supply Chain Expanded ────────────────────────────────────
        app.router.add_post("/api/v1/supply-chain/provenance/log", self._handle_provenance_log)
        app.router.add_post("/api/v1/supply-chain/verify", self._handle_authenticity_verify)
        app.router.add_post("/api/v1/supply-chain/custody/transfer", self._handle_custody_transfer)

        # ── Insurance Expanded ───────────────────────────────────────
        app.router.add_post("/api/v1/insurance/parametric/create", self._handle_parametric_policy)
        app.router.add_post("/api/v1/insurance/claim/settle", self._handle_claim_settle)

        # ── Privacy ──────────────────────────────────────────────────
        app.router.add_post("/api/v1/privacy/transfer", self._handle_private_transfer)
        app.router.add_post("/api/v1/privacy/stealth-address", self._handle_stealth_address)

        # Batch dispatch and live event stream (used by MTRXPackager)
        app.router.add_post("/api/v1/batch", self._handle_batch)
        app.router.add_get("/api/v1/events/stream", self._handle_event_stream)

        self._build_batch_route_map()
        logger.info("ServiceRoutes: registered %d endpoints", 118)

    # ------------------------------------------------------------------
    # Batch route map — mirrors every non-batch route above so we can
    # resolve ``{method, path}`` tuples coming in from /api/v1/batch
    # without touching aiohttp's live dispatcher.
    # ------------------------------------------------------------------

    def _build_batch_route_map(self) -> None:
        """Build the ``(method, path) -> handler`` map used by batch dispatch."""

        def _compile(path: str) -> Tuple[re.Pattern, List[str]]:
            param_names: List[str] = []
            pattern = "^"
            i = 0
            while i < len(path):
                ch = path[i]
                if ch == "{":
                    end = path.index("}", i)
                    name = path[i + 1:end]
                    param_names.append(name)
                    pattern += r"([^/]+)"
                    i = end + 1
                else:
                    pattern += re.escape(ch)
                    i += 1
            pattern += "$"
            return re.compile(pattern), param_names

        specs: List[Tuple[str, str, Callable[..., Awaitable[web.Response]]]] = [
            ("POST", "/api/v1/contracts/convert", self._handle_contract_convert),
            ("POST", "/api/v1/contracts/deploy", self._handle_contract_deploy),
            ("POST", "/api/v1/defi/loan/create", self._handle_defi_loan_create),
            ("POST", "/api/v1/defi/loan/repay", self._handle_defi_loan_repay),
            ("POST", "/api/v1/nft/mint", self._handle_nft_mint),
            ("POST", "/api/v1/nft/collection/create", self._handle_nft_collection_create),
            ("POST", "/api/v1/rwa/tokenize", self._handle_rwa_tokenize),
            ("POST", "/api/v1/identity/create", self._handle_did_create),
            ("POST", "/api/v1/dao/create", self._handle_dao_create),
            ("POST", "/api/v1/stablecoin/transfer", self._handle_stablecoin_transfer),
            ("POST", "/api/v1/staking/stake", self._handle_staking_stake),
            ("POST", "/api/v1/staking/unstake", self._handle_staking_unstake),
            ("POST", "/api/v1/dex/swap", self._handle_dex_swap),
            ("POST", "/api/v1/dex/liquidity/add", self._handle_dex_add_liquidity),
            ("POST", "/api/v1/insurance/policy/create", self._handle_insurance_create),
            ("POST", "/api/v1/insurance/claim", self._handle_insurance_claim),
            ("POST", "/api/v1/marketplace/list", self._handle_marketplace_list),
            ("POST", "/api/v1/marketplace/buy", self._handle_marketplace_buy),
            ("POST", "/api/v1/governance/proposal/create", self._handle_governance_create),
            ("POST", "/api/v1/governance/vote", self._handle_governance_vote),
            ("POST", "/api/v1/dispute/file", self._handle_dispute_file),
            ("POST", "/api/v1/social/message", self._handle_social_message),
            ("POST", "/api/v1/social/profile", self._handle_social_profile),
            ("POST", "/api/v1/fundraising/campaign/create", self._handle_fundraising_create),
            ("POST", "/api/v1/fundraising/contribute", self._handle_fundraising_contribute),
            ("POST", "/api/v1/subscriptions/subscribe", self._handle_subscribe),
            ("POST", "/api/v1/loyalty/earn", self._handle_loyalty_earn),
            ("POST", "/api/v1/loyalty/redeem", self._handle_loyalty_redeem),
            ("POST", "/api/v1/cashback/track", self._handle_cashback_track),
            ("POST", "/api/v1/brand/campaign/create", self._handle_brand_campaign_create),
            ("POST", "/api/v1/privacy/delete", self._handle_privacy_delete),
            ("POST", "/api/v1/crossborder/send", self._handle_crossborder_send),
            ("POST", "/api/v1/securities/create", self._handle_securities_create),
            ("POST", "/api/v1/supply-chain/register", self._handle_supply_chain_register),
            ("POST", "/api/v1/gaming/register", self._handle_gaming_register),
            ("POST", "/api/v1/ip/register", self._handle_ip_register),
            ("POST", "/api/v1/agent/register", self._handle_agent_register),
            ("POST", "/api/v1/payments/create", self._handle_payment_create),
            ("GET",  "/api/v1/dashboard/{address}", self._handle_dashboard),
            ("GET",  "/api/v1/oracle/price/{pair}", self._handle_oracle_price),
            ("GET",  "/api/v1/attestation/verify/{uid}", self._handle_attestation_verify),
            # ── Expanded routes ──────────────────────────────────────
            ("POST", "/api/v1/defi/yield/optimize", self._handle_yield_optimize),
            ("POST", "/api/v1/defi/swap/route", self._handle_swap_route),
            ("POST", "/api/v1/defi/swap/execute", self._handle_swap_execute),
            ("POST", "/api/v1/defi/bridge/quote", self._handle_bridge_quote),
            ("POST", "/api/v1/defi/bridge/execute", self._handle_bridge_execute),
            ("POST", "/api/v1/defi/flash-loan/execute", self._handle_flash_loan),
            ("POST", "/api/v1/defi/vault/deposit", self._handle_vault_deposit),
            ("POST", "/api/v1/defi/liquidity/provide", self._handle_liquidity_provide),
            ("POST", "/api/v1/defi/perp/trade", self._handle_perp_trade),
            ("POST", "/api/v1/defi/collateral/manage", self._handle_collateral_manage),
            ("POST", "/api/v1/nft/fractionalize", self._handle_nft_fractionalize),
            ("POST", "/api/v1/nft/rent", self._handle_nft_rent),
            ("POST", "/api/v1/nft/batch-mint", self._handle_nft_batch_mint),
            ("POST", "/api/v1/nft/royalty/claim", self._handle_nft_royalty_claim),
            ("POST", "/api/v1/nft/bridge", self._handle_nft_bridge),
            ("POST", "/api/v1/identity/did/create", self._handle_identity_did_create),
            ("POST", "/api/v1/identity/credential/issue", self._handle_credential_issue),
            ("POST", "/api/v1/identity/credential/verify", self._handle_credential_verify),
            ("POST", "/api/v1/identity/zk-proof/generate", self._handle_zk_proof),
            ("POST", "/api/v1/identity/soulbound/mint", self._handle_soulbound_mint),
            ("POST", "/api/v1/social/post", self._handle_social_post),
            ("POST", "/api/v1/social/message/send", self._handle_social_message_send),
            ("POST", "/api/v1/social/gate/create", self._handle_social_gate),
            ("POST", "/api/v1/social/community/create", self._handle_community_create),
            ("GET",  "/api/v1/social/feed/{wallet}", self._handle_social_feed),
            ("POST", "/api/v1/payments/stream/create", self._handle_stream_create),
            ("POST", "/api/v1/payments/recurring/create", self._handle_recurring_create),
            ("POST", "/api/v1/payments/escrow/milestone", self._handle_escrow_milestone),
            ("POST", "/api/v1/payments/split", self._handle_payment_split),
            ("POST", "/api/v1/payments/payroll", self._handle_payroll_run),
            ("POST", "/api/v1/compute/store", self._handle_decentralized_store),
            ("POST", "/api/v1/compute/ipfs/pin", self._handle_ipfs_pin),
            ("POST", "/api/v1/compute/arweave/store", self._handle_arweave_store),
            ("POST", "/api/v1/rwa/fractional/buy", self._handle_rwa_fractional_buy),
            ("GET",  "/api/v1/rwa/listings", self._handle_rwa_listings),
            ("POST", "/api/v1/prediction/market/create", self._handle_market_create),
            ("POST", "/api/v1/prediction/market/bet", self._handle_market_bet),
            ("GET",  "/api/v1/prediction/market/list", self._handle_market_list),
            ("POST", "/api/v1/energy/carbon/buy", self._handle_carbon_buy),
            ("POST", "/api/v1/energy/carbon/retire", self._handle_carbon_retire),
            ("GET",  "/api/v1/energy/carbon/prices", self._handle_carbon_prices),
            ("POST", "/api/v1/governance/multisig/propose", self._handle_multisig_propose),
            ("POST", "/api/v1/governance/multisig/approve", self._handle_multisig_approve),
            ("POST", "/api/v1/governance/snapshot/vote", self._handle_snapshot_vote),
            ("POST", "/api/v1/governance/treasury/transfer", self._handle_treasury_transfer),
            ("GET",  "/api/v1/portfolio/complete/{wallet}", self._handle_portfolio_complete),
            ("GET",  "/api/v1/portfolio/positions/{wallet}", self._handle_portfolio_positions),
            ("GET",  "/api/v1/portfolio/history/{wallet}", self._handle_portfolio_history),
            ("POST", "/api/v1/intent/resolve", self._handle_intent_resolve),
            ("POST", "/api/v1/intent/execute", self._handle_intent_execute),
            ("GET",  "/api/v1/intent/summary/{plan_id}", self._handle_intent_summary),
            ("POST", "/api/v1/legal/license/grant", self._handle_license_grant),
            ("POST", "/api/v1/legal/agreement/execute", self._handle_agreement_execute),
            ("POST", "/api/v1/legal/dispute/file", self._handle_legal_dispute_file),
            ("POST", "/api/v1/ai/agent/register", self._handle_ai_agent_register),
            ("POST", "/api/v1/ai/model/trade", self._handle_ai_model_trade),
            ("POST", "/api/v1/supply-chain/provenance/log", self._handle_provenance_log),
            ("POST", "/api/v1/supply-chain/verify", self._handle_authenticity_verify),
            ("POST", "/api/v1/supply-chain/custody/transfer", self._handle_custody_transfer),
            ("POST", "/api/v1/insurance/parametric/create", self._handle_parametric_policy),
            ("POST", "/api/v1/insurance/claim/settle", self._handle_claim_settle),
            ("POST", "/api/v1/privacy/transfer", self._handle_private_transfer),
            ("POST", "/api/v1/privacy/stealth-address", self._handle_stealth_address),
        ]

        # Bridge endpoints — only registered if the gateway server has
        # wired a BridgeRoutes instance via :meth:`attach_bridge_routes`.
        # Without the bridge available we simply skip them so a bare
        # ``ServiceRoutes`` (as used in unit tests) still builds cleanly.
        if self._bridge_routes is not None:
            br = self._bridge_routes
            bridge_specs: List[Tuple[str, str, Callable[..., Awaitable[web.Response]]]] = [
                ("POST", "/bridge/v1/session/create", br.create_session),
                ("POST", "/bridge/v1/session/resume", br.resume_session),
                ("POST", "/bridge/v1/chat", br.chat),
                ("POST", "/bridge/v1/action", br.execute_action),
                ("POST", "/bridge/v1/wallet/link", br.link_wallet),
                ("GET",  "/bridge/v1/wallet/status", br.wallet_status),
                ("GET",  "/bridge/v1/config", br.get_config),
                ("GET",  "/bridge/v1/services", br.get_services),
                ("POST", "/bridge/v1/push/register", br.register_push),
                ("GET",  "/bridge/v1/dashboard", br.get_dashboard),
                ("GET",  "/bridge/v1/components", br.get_components),
                ("GET",  "/bridge/v1/components/manifest", br.get_components_manifest),
                ("GET",  "/bridge/v1/components/{component_id}", br.get_component),
            ]
            specs.extend(bridge_specs)

        routes = []
        for method, path, handler in specs:
            pattern, param_names = _compile(path)
            routes.append((method.upper(), pattern, param_names, handler, path))
        self._batch_routes = routes

    def _resolve_batch_route(
        self,
        method: str,
        path: str,
    ) -> Optional[Tuple[Callable[..., Awaitable[web.Response]], dict, str]]:
        """Return ``(handler, match_info, literal_path)`` for a batch item."""

        method = method.upper()
        for route_method, pattern, param_names, handler, literal_path in self._batch_routes:
            if route_method != method:
                continue
            match = pattern.match(path)
            if match is None:
                continue
            match_info = {name: value for name, value in zip(param_names, match.groups())}
            return handler, match_info, literal_path
        return None

    # ------------------------------------------------------------------
    # Helpers
    # ------------------------------------------------------------------

    async def _parse_body(self, request: web.Request) -> dict:
        """Parse and return the JSON body, raising on failure."""
        try:
            return await request.json()
        except (json.JSONDecodeError, Exception):
            raise web.HTTPBadRequest(
                text=json.dumps({"error": "Invalid JSON body"}),
                content_type="application/json",
            )

    def _require(self, body: dict, *keys: str) -> None:
        """Raise 400 if any required key is missing from *body*."""
        missing = [k for k in keys if k not in body]
        if missing:
            raise web.HTTPBadRequest(
                text=json.dumps({"error": f"Missing required fields: {', '.join(missing)}"}),
                content_type="application/json",
            )

    def _ok(self, data: Any) -> web.Response:
        return web.json_response({"status": "ok", "data": data})

    async def _call(self, service_name: str, method_name: str, **kwargs) -> Any:
        """Resolve a service and call its method."""
        try:
            svc = self._get_registry().get(service_name)
        except KeyError:
            raise web.HTTPNotFound(
                text=json.dumps({"error": f"Service '{service_name}' not found"}),
                content_type="application/json",
            )
        method = getattr(svc, method_name, None)
        if method is None:
            raise web.HTTPNotFound(
                text=json.dumps({"error": f"Method '{method_name}' not found on '{service_name}'"}),
                content_type="application/json",
            )
        try:
            return await method(**kwargs)
        except TypeError as exc:
            logger.error("Bad params for %s.%s: %s", service_name, method_name, exc)
            raise web.HTTPBadRequest(
                text=json.dumps({"error": f"Invalid parameters: {exc}"}),
                content_type="application/json",
            )
        except Exception as exc:
            logger.exception("Error in %s.%s", service_name, method_name)
            raise web.HTTPInternalServerError(
                text=json.dumps({"error": str(exc)}),
                content_type="application/json",
            )

    # ------------------------------------------------------------------
    # Endpoint handlers
    # ------------------------------------------------------------------

    # -- Contracts --

    async def _handle_contract_convert(self, request: web.Request) -> web.Response:
        body = await self._parse_body(request)
        self._require(body, "source_code", "source_lang")
        result = await self._call(
            "contract_conversion", "convert",
            source_code=body["source_code"],
            source_lang=body["source_lang"],
            target_chain=body.get("target_chain", "base"),
        )
        return self._ok(result)

    async def _handle_contract_deploy(self, request: web.Request) -> web.Response:
        body = await self._parse_body(request)
        self._require(body, "source_code", "source_lang")
        result = await self._call(
            "contract_conversion", "convert",
            source_code=body["source_code"],
            source_lang=body["source_lang"],
            target_chain=body.get("target_chain", "base"),
        )
        return self._ok(result)

    # -- DeFi --

    async def _handle_defi_loan_create(self, request: web.Request) -> web.Response:
        body = await self._parse_body(request)
        self._require(body, "borrower", "collateral_token", "collateral_amount",
                       "borrow_token", "borrow_amount")
        result = await self._call(
            "defi", "create_loan",
            borrower=body["borrower"],
            collateral_token=body["collateral_token"],
            collateral_amount=float(body["collateral_amount"]),
            borrow_token=body["borrow_token"],
            borrow_amount=float(body["borrow_amount"]),
        )
        return self._ok(result)

    async def _handle_defi_loan_repay(self, request: web.Request) -> web.Response:
        body = await self._parse_body(request)
        self._require(body, "loan_id", "amount")
        result = await self._call(
            "defi", "repay_loan",
            loan_id=body["loan_id"],
            amount=float(body["amount"]),
        )
        return self._ok(result)

    # -- NFT --

    async def _handle_nft_mint(self, request: web.Request) -> web.Response:
        body = await self._parse_body(request)
        self._require(body, "collection_id", "creator", "metadata")
        result = await self._call(
            "nft_services", "mint",
            collection_id=body["collection_id"],
            creator=body["creator"],
            metadata=body["metadata"],
        )
        return self._ok(result)

    async def _handle_nft_collection_create(self, request: web.Request) -> web.Response:
        body = await self._parse_body(request)
        self._require(body, "creator", "name", "symbol")
        result = await self._call(
            "nft_services", "create_collection",
            creator=body["creator"],
            name=body["name"],
            symbol=body["symbol"],
            metadata=body.get("metadata", {}),
        )
        return self._ok(result)

    # -- RWA --

    async def _handle_rwa_tokenize(self, request: web.Request) -> web.Response:
        body = await self._parse_body(request)
        self._require(body, "owner", "asset_type", "asset_data")
        result = await self._call(
            "rwa_tokenization", "tokenize_asset",
            owner=body["owner"],
            asset_type=body["asset_type"],
            asset_data=body["asset_data"],
        )
        return self._ok(result)

    # -- DID / Identity --

    async def _handle_did_create(self, request: web.Request) -> web.Response:
        body = await self._parse_body(request)
        self._require(body, "owner")
        result = await self._call(
            "did_identity", "create_did",
            owner=body["owner"],
            method=body.get("method", "openmatrix"),
        )
        return self._ok(result)

    # -- DAO --

    async def _handle_dao_create(self, request: web.Request) -> web.Response:
        body = await self._parse_body(request)
        self._require(body, "creator", "name", "config")
        result = await self._call(
            "dao_management", "create_dao",
            creator=body["creator"],
            name=body["name"],
            config=body["config"],
        )
        return self._ok(result)

    # -- Stablecoin --

    async def _handle_stablecoin_transfer(self, request: web.Request) -> web.Response:
        body = await self._parse_body(request)
        self._require(body, "sender", "recipient", "amount", "token")
        result = await self._call(
            "stablecoin", "transfer",
            sender=body["sender"],
            recipient=body["recipient"],
            amount=float(body["amount"]),
            token=body["token"],
        )
        return self._ok(result)

    # -- Staking --

    async def _handle_staking_stake(self, request: web.Request) -> web.Response:
        body = await self._parse_body(request)
        self._require(body, "staker", "token", "amount")
        result = await self._call(
            "staking", "stake",
            staker=body["staker"],
            token=body["token"],
            amount=float(body["amount"]),
        )
        return self._ok(result)

    async def _handle_staking_unstake(self, request: web.Request) -> web.Response:
        body = await self._parse_body(request)
        self._require(body, "staker", "token", "amount")
        result = await self._call(
            "staking", "unstake",
            staker=body["staker"],
            token=body["token"],
            amount=float(body["amount"]),
        )
        return self._ok(result)

    # -- DEX --

    async def _handle_dex_swap(self, request: web.Request) -> web.Response:
        body = await self._parse_body(request)
        self._require(body, "trader", "token_in", "token_out", "amount_in")
        result = await self._call(
            "dex", "swap",
            trader=body["trader"],
            token_in=body["token_in"],
            token_out=body["token_out"],
            amount_in=float(body["amount_in"]),
        )
        return self._ok(result)

    async def _handle_dex_add_liquidity(self, request: web.Request) -> web.Response:
        body = await self._parse_body(request)
        self._require(body, "provider", "token_a", "token_b", "amount_a", "amount_b")
        result = await self._call(
            "dex", "add_liquidity",
            provider=body["provider"],
            token_a=body["token_a"],
            token_b=body["token_b"],
            amount_a=float(body["amount_a"]),
            amount_b=float(body["amount_b"]),
        )
        return self._ok(result)

    # -- Insurance --

    async def _handle_insurance_create(self, request: web.Request) -> web.Response:
        body = await self._parse_body(request)
        self._require(body, "holder", "policy_type", "coverage_amount", "premium")
        result = await self._call(
            "insurance", "create_policy",
            holder=body["holder"],
            policy_type=body["policy_type"],
            coverage_amount=float(body["coverage_amount"]),
            premium=float(body["premium"]),
        )
        return self._ok(result)

    async def _handle_insurance_claim(self, request: web.Request) -> web.Response:
        body = await self._parse_body(request)
        self._require(body, "policy_id", "trigger_data")
        result = await self._call(
            "insurance", "file_claim",
            policy_id=body["policy_id"],
            trigger_data=body["trigger_data"],
        )
        return self._ok(result)

    # -- Marketplace --

    async def _handle_marketplace_list(self, request: web.Request) -> web.Response:
        body = await self._parse_body(request)
        self._require(body, "seller", "item_type", "metadata", "price")
        result = await self._call(
            "marketplace", "list_item",
            seller=body["seller"],
            item_type=body["item_type"],
            metadata=body["metadata"],
            price=float(body["price"]),
        )
        return self._ok(result)

    async def _handle_marketplace_buy(self, request: web.Request) -> web.Response:
        body = await self._parse_body(request)
        self._require(body, "listing_id", "buyer")
        result = await self._call(
            "marketplace", "buy_item",
            listing_id=body["listing_id"],
            buyer=body["buyer"],
        )
        return self._ok(result)

    # -- Governance --

    async def _handle_governance_create(self, request: web.Request) -> web.Response:
        body = await self._parse_body(request)
        self._require(body, "proposer", "title", "description")
        result = await self._call(
            "governance", "create_proposal",
            proposer=body["proposer"],
            title=body["title"],
            description=body["description"],
            actions=body.get("actions", []),
        )
        return self._ok(result)

    async def _handle_governance_vote(self, request: web.Request) -> web.Response:
        body = await self._parse_body(request)
        self._require(body, "proposal_id", "voter", "support")
        result = await self._call(
            "governance", "vote",
            proposal_id=body["proposal_id"],
            voter=body["voter"],
            support=body["support"],
        )
        return self._ok(result)

    # -- Dispute Resolution --

    async def _handle_dispute_file(self, request: web.Request) -> web.Response:
        body = await self._parse_body(request)
        self._require(body, "complainant", "respondent", "dispute_type", "description")
        result = await self._call(
            "dispute_resolution", "file_dispute",
            complainant=body["complainant"],
            respondent=body["respondent"],
            dispute_type=body["dispute_type"],
            description=body["description"],
        )
        return self._ok(result)

    # -- Social --

    async def _handle_social_message(self, request: web.Request) -> web.Response:
        body = await self._parse_body(request)
        self._require(body, "sharer", "proof_type", "proof_data")
        result = await self._call(
            "social", "share_proof",
            sharer=body["sharer"],
            proof_type=body["proof_type"],
            proof_data=body["proof_data"],
        )
        return self._ok(result)

    async def _handle_social_profile(self, request: web.Request) -> web.Response:
        body = await self._parse_body(request)
        self._require(body, "address", "display_name", "bio")
        result = await self._call(
            "social", "create_profile",
            address=body["address"],
            display_name=body["display_name"],
            bio=body["bio"],
        )
        return self._ok(result)

    # -- Fundraising --

    async def _handle_fundraising_create(self, request: web.Request) -> web.Response:
        body = await self._parse_body(request)
        self._require(body, "creator", "title", "goal")
        result = await self._call(
            "fundraising", "create_campaign",
            creator=body["creator"],
            title=body["title"],
            goal=float(body["goal"]),
            description=body.get("description", ""),
            milestones=body.get("milestones", []),
        )
        return self._ok(result)

    async def _handle_fundraising_contribute(self, request: web.Request) -> web.Response:
        body = await self._parse_body(request)
        self._require(body, "campaign_id", "contributor", "amount")
        result = await self._call(
            "fundraising", "contribute",
            campaign_id=body["campaign_id"],
            contributor=body["contributor"],
            amount=float(body["amount"]),
        )
        return self._ok(result)

    # -- Subscriptions --

    async def _handle_subscribe(self, request: web.Request) -> web.Response:
        body = await self._parse_body(request)
        self._require(body, "user", "plan_id", "payment_token")
        result = await self._call(
            "subscriptions", "subscribe",
            user=body["user"],
            plan_id=body["plan_id"],
            payment_token=body["payment_token"],
        )
        return self._ok(result)

    # -- Loyalty --

    async def _handle_loyalty_earn(self, request: web.Request) -> web.Response:
        body = await self._parse_body(request)
        self._require(body, "user", "action", "amount")
        result = await self._call(
            "loyalty", "earn_points",
            user=body["user"],
            action=body["action"],
            amount=float(body["amount"]),
            program_id=body.get("program_id", "platform"),
        )
        return self._ok(result)

    async def _handle_loyalty_redeem(self, request: web.Request) -> web.Response:
        body = await self._parse_body(request)
        self._require(body, "user", "points", "reward_type")
        result = await self._call(
            "loyalty", "redeem_points",
            user=body["user"],
            points=int(body["points"]),
            reward_type=body["reward_type"],
            program_id=body.get("program_id", "platform"),
        )
        return self._ok(result)

    # -- Cashback --

    async def _handle_cashback_track(self, request: web.Request) -> web.Response:
        body = await self._parse_body(request)
        self._require(body, "user", "amount", "category")
        result = await self._call(
            "cashback", "track_spending",
            user=body["user"],
            amount=float(body["amount"]),
            category=body["category"],
        )
        return self._ok(result)

    # -- Brand Rewards --

    async def _handle_brand_campaign_create(self, request: web.Request) -> web.Response:
        body = await self._parse_body(request)
        self._require(body, "brand", "reward_type", "budget", "criteria")
        result = await self._call(
            "brand_rewards", "create_campaign",
            brand=body["brand"],
            reward_type=body["reward_type"],
            budget=float(body["budget"]),
            criteria=body["criteria"],
        )
        return self._ok(result)

    # -- Privacy --

    async def _handle_privacy_delete(self, request: web.Request) -> web.Response:
        body = await self._parse_body(request)
        self._require(body, "user", "data_types")
        result = await self._call(
            "privacy", "request_deletion",
            user=body["user"],
            data_types=body["data_types"],
        )
        return self._ok(result)

    # -- Cross-Border --

    async def _handle_crossborder_send(self, request: web.Request) -> web.Response:
        body = await self._parse_body(request)
        self._require(body, "sender", "recipient", "amount", "source_currency",
                       "destination_currency")
        result = await self._call(
            "cross_border", "send_payment",
            sender=body["sender"],
            recipient=body["recipient"],
            amount=float(body["amount"]),
            source_currency=body["source_currency"],
            destination_currency=body["destination_currency"],
        )
        return self._ok(result)

    # -- Securities --

    async def _handle_securities_create(self, request: web.Request) -> web.Response:
        body = await self._parse_body(request)
        self._require(body, "issuer", "security_type", "name", "total_supply")
        result = await self._call(
            "securities_exchange", "create_security",
            issuer=body["issuer"],
            security_type=body["security_type"],
            name=body["name"],
            total_supply=int(body["total_supply"]),
        )
        return self._ok(result)

    # -- Supply Chain --

    async def _handle_supply_chain_register(self, request: web.Request) -> web.Response:
        body = await self._parse_body(request)
        self._require(body, "manufacturer", "product_data")
        result = await self._call(
            "supply_chain", "register_product",
            manufacturer=body["manufacturer"],
            product_data=body["product_data"],
        )
        return self._ok(result)

    # -- Gaming --

    async def _handle_gaming_register(self, request: web.Request) -> web.Response:
        body = await self._parse_body(request)
        self._require(body, "developer", "game_data")
        result = await self._call(
            "gaming", "register_game",
            developer=body["developer"],
            game_data=body["game_data"],
        )
        return self._ok(result)

    # -- IP & Royalties --

    async def _handle_ip_register(self, request: web.Request) -> web.Response:
        body = await self._parse_body(request)
        self._require(body, "creator", "ip_type", "metadata")
        result = await self._call(
            "ip_royalties", "register_ip",
            creator=body["creator"],
            ip_type=body["ip_type"],
            metadata=body["metadata"],
        )
        return self._ok(result)

    # -- Agent Identity --

    async def _handle_agent_register(self, request: web.Request) -> web.Response:
        body = await self._parse_body(request)
        self._require(body, "owner", "agent_type", "capabilities")
        result = await self._call(
            "agent_identity", "register_agent",
            owner=body["owner"],
            agent_type=body["agent_type"],
            capabilities=body["capabilities"],
        )
        return self._ok(result)

    # -- x402 Payments --

    async def _handle_payment_create(self, request: web.Request) -> web.Response:
        body = await self._parse_body(request)
        self._require(body, "payer", "payee", "amount", "token")
        result = await self._call(
            "x402_payments", "create_payment",
            payer=body["payer"],
            payee=body["payee"],
            amount=float(body["amount"]),
            token=body["token"],
        )
        return self._ok(result)

    # -- Dashboard (GET) --

    async def _handle_dashboard(self, request: web.Request) -> web.Response:
        address = request.match_info["address"]
        result = await self._call(
            "dashboard", "get_overview",
            user_address=address,
        )
        return self._ok(result)

    # -- Oracle (GET) --

    async def _handle_oracle_price(self, request: web.Request) -> web.Response:
        pair = request.match_info["pair"]
        result = await self._call(
            "oracle_gateway", "request",
            oracle_type="price",
            params={"pair": pair},
        )
        return self._ok(result)

    # -- Attestation (GET) --

    async def _handle_attestation_verify(self, request: web.Request) -> web.Response:
        uid = request.match_info["uid"]
        result = await self._call(
            "attestation", "verify",
            attestation_uid=uid,
        )
        return self._ok(result)

    # -- DeFi Expanded --

    async def _handle_yield_optimize(self, request: web.Request) -> web.Response:
        body = await self._parse_body(request)
        self._require(body, "asset", "amount")
        result = await self._call(
            "defi", "yield_optimize",
            asset=body["asset"],
            amount=body["amount"],
            risk_tolerance=body.get("risk_tolerance", "medium"),
        )
        return self._ok(result)

    async def _handle_swap_route(self, request: web.Request) -> web.Response:
        body = await self._parse_body(request)
        self._require(body, "token_in", "token_out", "amount")
        result = await self._call(
            "defi", "swap_route",
            token_in=body["token_in"],
            token_out=body["token_out"],
            amount=body["amount"],
            slippage=body.get("slippage", 0.5),
        )
        return self._ok(result)

    async def _handle_swap_execute(self, request: web.Request) -> web.Response:
        body = await self._parse_body(request)
        self._require(body, "wallet", "route_id")
        result = await self._call(
            "defi", "swap_execute",
            wallet=body["wallet"],
            route_id=body["route_id"],
            slippage=body.get("slippage", 0.5),
        )
        return self._ok(result)

    async def _handle_bridge_quote(self, request: web.Request) -> web.Response:
        body = await self._parse_body(request)
        self._require(body, "token", "amount", "source_chain", "dest_chain")
        result = await self._call(
            "defi", "bridge_quote",
            token=body["token"],
            amount=body["amount"],
            source_chain=body["source_chain"],
            dest_chain=body["dest_chain"],
        )
        return self._ok(result)

    async def _handle_bridge_execute(self, request: web.Request) -> web.Response:
        body = await self._parse_body(request)
        self._require(body, "wallet", "quote_id")
        result = await self._call(
            "defi", "bridge_execute",
            wallet=body["wallet"],
            quote_id=body["quote_id"],
        )
        return self._ok(result)

    async def _handle_flash_loan(self, request: web.Request) -> web.Response:
        body = await self._parse_body(request)
        self._require(body, "token", "amount", "operations")
        result = await self._call(
            "defi", "flash_loan_execute",
            token=body["token"],
            amount=body["amount"],
            operations=body["operations"],
            wallet=body.get("wallet", ""),
        )
        return self._ok(result)

    async def _handle_vault_deposit(self, request: web.Request) -> web.Response:
        body = await self._parse_body(request)
        self._require(body, "wallet", "vault_id", "amount")
        result = await self._call(
            "defi", "vault_deposit",
            wallet=body["wallet"],
            vault_id=body["vault_id"],
            amount=body["amount"],
        )
        return self._ok(result)

    async def _handle_liquidity_provide(self, request: web.Request) -> web.Response:
        body = await self._parse_body(request)
        self._require(body, "wallet", "pool_id", "token_a_amount", "token_b_amount")
        result = await self._call(
            "defi", "liquidity_provide",
            wallet=body["wallet"],
            pool_id=body["pool_id"],
            token_a_amount=body["token_a_amount"],
            token_b_amount=body["token_b_amount"],
        )
        return self._ok(result)

    async def _handle_perp_trade(self, request: web.Request) -> web.Response:
        body = await self._parse_body(request)
        self._require(body, "wallet", "market", "side", "size")
        result = await self._call(
            "defi", "perp_trade",
            wallet=body["wallet"],
            market=body["market"],
            side=body["side"],
            size=body["size"],
            leverage=body.get("leverage", 1),
        )
        return self._ok(result)

    async def _handle_collateral_manage(self, request: web.Request) -> web.Response:
        body = await self._parse_body(request)
        self._require(body, "wallet", "action", "token", "amount")
        result = await self._call(
            "defi", "collateral_manage",
            wallet=body["wallet"],
            action=body["action"],
            token=body["token"],
            amount=body["amount"],
        )
        return self._ok(result)

    # -- NFT Expanded --

    async def _handle_nft_fractionalize(self, request: web.Request) -> web.Response:
        body = await self._parse_body(request)
        self._require(body, "owner", "token_id", "fractions")
        result = await self._call(
            "nft_services", "fractionalize",
            owner=body["owner"],
            token_id=body["token_id"],
            fractions=int(body["fractions"]),
            price_per_fraction=body.get("price_per_fraction"),
        )
        return self._ok(result)

    async def _handle_nft_rent(self, request: web.Request) -> web.Response:
        body = await self._parse_body(request)
        self._require(body, "renter", "token_id", "duration")
        result = await self._call(
            "nft_services", "rent",
            renter=body["renter"],
            token_id=body["token_id"],
            duration=body["duration"],
            price=body.get("price"),
        )
        return self._ok(result)

    async def _handle_nft_batch_mint(self, request: web.Request) -> web.Response:
        body = await self._parse_body(request)
        self._require(body, "creator", "collection_id", "items")
        result = await self._call(
            "nft_services", "batch_mint",
            creator=body["creator"],
            collection_id=body["collection_id"],
            items=body["items"],
        )
        return self._ok(result)

    async def _handle_nft_royalty_claim(self, request: web.Request) -> web.Response:
        body = await self._parse_body(request)
        self._require(body, "creator", "token_id")
        result = await self._call(
            "nft_services", "royalty_claim",
            creator=body["creator"],
            token_id=body["token_id"],
        )
        return self._ok(result)

    async def _handle_nft_bridge(self, request: web.Request) -> web.Response:
        body = await self._parse_body(request)
        self._require(body, "owner", "token_id", "dest_chain")
        result = await self._call(
            "nft_services", "bridge_nft",
            owner=body["owner"],
            token_id=body["token_id"],
            dest_chain=body["dest_chain"],
        )
        return self._ok(result)

    # -- Identity Expanded --

    async def _handle_identity_did_create(self, request: web.Request) -> web.Response:
        body = await self._parse_body(request)
        self._require(body, "owner")
        result = await self._call(
            "did_identity", "create_did",
            owner=body["owner"],
            method=body.get("method", "openmatrix"),
        )
        return self._ok(result)

    async def _handle_credential_issue(self, request: web.Request) -> web.Response:
        body = await self._parse_body(request)
        self._require(body, "issuer", "subject", "credential_type", "claims")
        result = await self._call(
            "did_identity", "issue_credential",
            issuer=body["issuer"],
            subject=body["subject"],
            credential_type=body["credential_type"],
            claims=body["claims"],
        )
        return self._ok(result)

    async def _handle_credential_verify(self, request: web.Request) -> web.Response:
        body = await self._parse_body(request)
        self._require(body, "credential_id")
        result = await self._call(
            "did_identity", "verify_credential",
            credential_id=body["credential_id"],
        )
        return self._ok(result)

    async def _handle_zk_proof(self, request: web.Request) -> web.Response:
        body = await self._parse_body(request)
        self._require(body, "prover", "claim", "proof_type")
        result = await self._call(
            "did_identity", "generate_zk_proof",
            prover=body["prover"],
            claim=body["claim"],
            proof_type=body["proof_type"],
        )
        return self._ok(result)

    async def _handle_soulbound_mint(self, request: web.Request) -> web.Response:
        body = await self._parse_body(request)
        self._require(body, "issuer", "recipient", "metadata")
        result = await self._call(
            "did_identity", "mint_soulbound",
            issuer=body["issuer"],
            recipient=body["recipient"],
            metadata=body["metadata"],
        )
        return self._ok(result)

    # -- Social Expanded --

    async def _handle_social_post(self, request: web.Request) -> web.Response:
        body = await self._parse_body(request)
        self._require(body, "author", "content")
        result = await self._call(
            "social", "create_post",
            author=body["author"],
            content=body["content"],
            media=body.get("media", []),
        )
        return self._ok(result)

    async def _handle_social_message_send(self, request: web.Request) -> web.Response:
        body = await self._parse_body(request)
        self._require(body, "sender", "recipient", "content")
        result = await self._call(
            "social", "send_message",
            sender=body["sender"],
            recipient=body["recipient"],
            content=body["content"],
            encrypted=body.get("encrypted", True),
        )
        return self._ok(result)

    async def _handle_social_gate(self, request: web.Request) -> web.Response:
        body = await self._parse_body(request)
        self._require(body, "owner", "gate_type", "criteria")
        result = await self._call(
            "social", "create_gate",
            owner=body["owner"],
            gate_type=body["gate_type"],
            criteria=body["criteria"],
        )
        return self._ok(result)

    async def _handle_community_create(self, request: web.Request) -> web.Response:
        body = await self._parse_body(request)
        self._require(body, "creator", "name", "rules")
        result = await self._call(
            "social", "create_community",
            creator=body["creator"],
            name=body["name"],
            rules=body["rules"],
            token_gate=body.get("token_gate"),
        )
        return self._ok(result)

    async def _handle_social_feed(self, request: web.Request) -> web.Response:
        wallet = request.match_info["wallet"]
        result = await self._call(
            "social", "get_feed",
            wallet=wallet,
        )
        return self._ok(result)

    # -- Payments Expanded --

    async def _handle_stream_create(self, request: web.Request) -> web.Response:
        body = await self._parse_body(request)
        self._require(body, "sender", "recipient", "token", "total_amount", "duration")
        result = await self._call(
            "x402_payments", "create_stream",
            sender=body["sender"],
            recipient=body["recipient"],
            token=body["token"],
            total_amount=float(body["total_amount"]),
            duration=body["duration"],
        )
        return self._ok(result)

    async def _handle_recurring_create(self, request: web.Request) -> web.Response:
        body = await self._parse_body(request)
        self._require(body, "payer", "payee", "token", "amount", "interval")
        result = await self._call(
            "x402_payments", "create_recurring",
            payer=body["payer"],
            payee=body["payee"],
            token=body["token"],
            amount=float(body["amount"]),
            interval=body["interval"],
        )
        return self._ok(result)

    async def _handle_escrow_milestone(self, request: web.Request) -> web.Response:
        body = await self._parse_body(request)
        self._require(body, "escrow_id", "milestone_id", "action")
        result = await self._call(
            "x402_payments", "escrow_milestone",
            escrow_id=body["escrow_id"],
            milestone_id=body["milestone_id"],
            action=body["action"],
        )
        return self._ok(result)

    async def _handle_payment_split(self, request: web.Request) -> web.Response:
        body = await self._parse_body(request)
        self._require(body, "payer", "recipients", "token", "total_amount")
        result = await self._call(
            "x402_payments", "split_payment",
            payer=body["payer"],
            recipients=body["recipients"],
            token=body["token"],
            total_amount=float(body["total_amount"]),
        )
        return self._ok(result)

    async def _handle_payroll_run(self, request: web.Request) -> web.Response:
        body = await self._parse_body(request)
        self._require(body, "employer", "employees", "token")
        result = await self._call(
            "x402_payments", "run_payroll",
            employer=body["employer"],
            employees=body["employees"],
            token=body["token"],
        )
        return self._ok(result)

    # -- Compute & Storage --

    async def _handle_decentralized_store(self, request: web.Request) -> web.Response:
        body = await self._parse_body(request)
        self._require(body, "owner", "data", "storage_type")
        result = await self._call(
            "compute", "store",
            owner=body["owner"],
            data=body["data"],
            storage_type=body["storage_type"],
        )
        return self._ok(result)

    async def _handle_ipfs_pin(self, request: web.Request) -> web.Response:
        body = await self._parse_body(request)
        self._require(body, "cid")
        result = await self._call(
            "compute", "ipfs_pin",
            cid=body["cid"],
            name=body.get("name", ""),
        )
        return self._ok(result)

    async def _handle_arweave_store(self, request: web.Request) -> web.Response:
        body = await self._parse_body(request)
        self._require(body, "owner", "data")
        result = await self._call(
            "compute", "arweave_store",
            owner=body["owner"],
            data=body["data"],
            content_type=body.get("content_type", "application/octet-stream"),
        )
        return self._ok(result)

    # -- RWA Expanded --

    async def _handle_rwa_fractional_buy(self, request: web.Request) -> web.Response:
        body = await self._parse_body(request)
        self._require(body, "buyer", "asset_id", "fractions")
        result = await self._call(
            "rwa_tokenization", "buy_fractions",
            buyer=body["buyer"],
            asset_id=body["asset_id"],
            fractions=int(body["fractions"]),
        )
        return self._ok(result)

    async def _handle_rwa_listings(self, request: web.Request) -> web.Response:
        result = await self._call(
            "rwa_tokenization", "list_assets",
        )
        return self._ok(result)

    # -- Prediction Markets --

    async def _handle_market_create(self, request: web.Request) -> web.Response:
        body = await self._parse_body(request)
        self._require(body, "creator", "question", "outcomes", "resolution_date")
        result = await self._call(
            "prediction", "create_market",
            creator=body["creator"],
            question=body["question"],
            outcomes=body["outcomes"],
            resolution_date=body["resolution_date"],
        )
        return self._ok(result)

    async def _handle_market_bet(self, request: web.Request) -> web.Response:
        body = await self._parse_body(request)
        self._require(body, "bettor", "market_id", "outcome", "amount")
        result = await self._call(
            "prediction", "place_bet",
            bettor=body["bettor"],
            market_id=body["market_id"],
            outcome=body["outcome"],
            amount=float(body["amount"]),
        )
        return self._ok(result)

    async def _handle_market_list(self, request: web.Request) -> web.Response:
        result = await self._call(
            "prediction", "list_markets",
        )
        return self._ok(result)

    # -- Energy --

    async def _handle_carbon_buy(self, request: web.Request) -> web.Response:
        body = await self._parse_body(request)
        self._require(body, "buyer", "tonnes", "project_id")
        result = await self._call(
            "energy", "buy_carbon_credits",
            buyer=body["buyer"],
            tonnes=float(body["tonnes"]),
            project_id=body["project_id"],
        )
        return self._ok(result)

    async def _handle_carbon_retire(self, request: web.Request) -> web.Response:
        body = await self._parse_body(request)
        self._require(body, "owner", "credit_ids")
        result = await self._call(
            "energy", "retire_carbon",
            owner=body["owner"],
            credit_ids=body["credit_ids"],
        )
        return self._ok(result)

    async def _handle_carbon_prices(self, request: web.Request) -> web.Response:
        result = await self._call(
            "energy", "get_carbon_prices",
        )
        return self._ok(result)

    # -- Governance Expanded --

    async def _handle_multisig_propose(self, request: web.Request) -> web.Response:
        body = await self._parse_body(request)
        self._require(body, "proposer", "multisig_address", "action", "params")
        result = await self._call(
            "governance", "multisig_propose",
            proposer=body["proposer"],
            multisig_address=body["multisig_address"],
            action=body["action"],
            params=body["params"],
        )
        return self._ok(result)

    async def _handle_multisig_approve(self, request: web.Request) -> web.Response:
        body = await self._parse_body(request)
        self._require(body, "approver", "multisig_address", "proposal_id")
        result = await self._call(
            "governance", "multisig_approve",
            approver=body["approver"],
            multisig_address=body["multisig_address"],
            proposal_id=body["proposal_id"],
        )
        return self._ok(result)

    async def _handle_snapshot_vote(self, request: web.Request) -> web.Response:
        body = await self._parse_body(request)
        self._require(body, "voter", "space", "proposal_id", "choice")
        result = await self._call(
            "governance", "snapshot_vote",
            voter=body["voter"],
            space=body["space"],
            proposal_id=body["proposal_id"],
            choice=body["choice"],
        )
        return self._ok(result)

    async def _handle_treasury_transfer(self, request: web.Request) -> web.Response:
        body = await self._parse_body(request)
        self._require(body, "dao_address", "recipient", "token", "amount")
        result = await self._call(
            "governance", "treasury_transfer",
            dao_address=body["dao_address"],
            recipient=body["recipient"],
            token=body["token"],
            amount=float(body["amount"]),
        )
        return self._ok(result)

    # -- Portfolio --

    async def _handle_portfolio_complete(self, request: web.Request) -> web.Response:
        wallet = request.match_info["wallet"]
        try:
            from runtime.blockchain.protocol_abstraction.data_aggregator import DataAggregator
            aggregator = DataAggregator(self._config)
            result = await aggregator.get_user_portfolio(wallet)
        except Exception as e:
            logger.warning("Portfolio aggregation failed: %s", e)
            result = {"wallet": wallet, "status": "unavailable", "message": str(e)}
        return self._ok(result)

    async def _handle_portfolio_positions(self, request: web.Request) -> web.Response:
        wallet = request.match_info["wallet"]
        try:
            from runtime.blockchain.protocol_abstraction.data_aggregator import DataAggregator
            aggregator = DataAggregator(self._config)
            result = await aggregator.get_positions(wallet)
        except Exception as e:
            logger.warning("Portfolio positions failed: %s", e)
            result = {"wallet": wallet, "status": "unavailable", "message": str(e)}
        return self._ok(result)

    async def _handle_portfolio_history(self, request: web.Request) -> web.Response:
        wallet = request.match_info["wallet"]
        try:
            from runtime.blockchain.protocol_abstraction.data_aggregator import DataAggregator
            aggregator = DataAggregator(self._config)
            result = await aggregator.get_history(wallet)
        except Exception as e:
            logger.warning("Portfolio history failed: %s", e)
            result = {"wallet": wallet, "status": "unavailable", "message": str(e)}
        return self._ok(result)

    # -- Intent Resolution --

    async def _handle_intent_resolve(self, request: web.Request) -> web.Response:
        body = await self._parse_body(request)
        self._require(body, "intent")
        try:
            from runtime.blockchain.protocol_abstraction.intent_resolver import IntentResolver
            resolver = IntentResolver(self._config)
            result = await resolver.resolve(
                intent=body["intent"],
                entities=body.get("entities", {}),
                wallet=body.get("wallet", ""),
                tier=body.get("tier", "free"),
            )
        except Exception as e:
            logger.warning("Intent resolution failed: %s", e)
            result = {"status": "error", "message": str(e)}
        return self._ok(result)

    async def _handle_intent_execute(self, request: web.Request) -> web.Response:
        body = await self._parse_body(request)
        self._require(body, "plan_id", "wallet")
        try:
            from runtime.blockchain.protocol_abstraction.intent_resolver import IntentResolver
            resolver = IntentResolver(self._config)
            result = await resolver.execute(
                plan_id=body["plan_id"],
                wallet=body["wallet"],
            )
        except Exception as e:
            logger.warning("Intent execution failed: %s", e)
            result = {"status": "error", "message": str(e)}
        return self._ok(result)

    async def _handle_intent_summary(self, request: web.Request) -> web.Response:
        plan_id = request.match_info["plan_id"]
        try:
            from runtime.blockchain.protocol_abstraction.intent_resolver import IntentResolver
            resolver = IntentResolver(self._config)
            result = await resolver.get_summary(plan_id=plan_id)
        except Exception as e:
            logger.warning("Intent summary failed: %s", e)
            result = {"plan_id": plan_id, "status": "unavailable", "message": str(e)}
        return self._ok(result)

    # -- Legal --

    async def _handle_license_grant(self, request: web.Request) -> web.Response:
        body = await self._parse_body(request)
        self._require(body, "licensor", "licensee", "ip_id", "terms")
        result = await self._call(
            "legal", "grant_license",
            licensor=body["licensor"],
            licensee=body["licensee"],
            ip_id=body["ip_id"],
            terms=body["terms"],
        )
        return self._ok(result)

    async def _handle_agreement_execute(self, request: web.Request) -> web.Response:
        body = await self._parse_body(request)
        self._require(body, "parties", "agreement_type", "terms")
        result = await self._call(
            "legal", "execute_agreement",
            parties=body["parties"],
            agreement_type=body["agreement_type"],
            terms=body["terms"],
        )
        return self._ok(result)

    async def _handle_legal_dispute_file(self, request: web.Request) -> web.Response:
        body = await self._parse_body(request)
        self._require(body, "complainant", "respondent", "dispute_type", "description")
        result = await self._call(
            "legal", "file_dispute",
            complainant=body["complainant"],
            respondent=body["respondent"],
            dispute_type=body["dispute_type"],
            description=body["description"],
        )
        return self._ok(result)

    # -- AI --

    async def _handle_ai_agent_register(self, request: web.Request) -> web.Response:
        body = await self._parse_body(request)
        self._require(body, "owner", "agent_name", "capabilities")
        result = await self._call(
            "ai", "register_agent",
            owner=body["owner"],
            agent_name=body["agent_name"],
            capabilities=body["capabilities"],
            model=body.get("model", ""),
        )
        return self._ok(result)

    async def _handle_ai_model_trade(self, request: web.Request) -> web.Response:
        body = await self._parse_body(request)
        self._require(body, "seller", "buyer", "model_id", "price")
        result = await self._call(
            "ai", "trade_model",
            seller=body["seller"],
            buyer=body["buyer"],
            model_id=body["model_id"],
            price=float(body["price"]),
        )
        return self._ok(result)

    # -- Supply Chain Expanded --

    async def _handle_provenance_log(self, request: web.Request) -> web.Response:
        body = await self._parse_body(request)
        self._require(body, "product_id", "event_type", "data")
        result = await self._call(
            "supply_chain", "log_provenance",
            product_id=body["product_id"],
            event_type=body["event_type"],
            data=body["data"],
        )
        return self._ok(result)

    async def _handle_authenticity_verify(self, request: web.Request) -> web.Response:
        body = await self._parse_body(request)
        self._require(body, "product_id")
        result = await self._call(
            "supply_chain", "verify_authenticity",
            product_id=body["product_id"],
        )
        return self._ok(result)

    async def _handle_custody_transfer(self, request: web.Request) -> web.Response:
        body = await self._parse_body(request)
        self._require(body, "product_id", "from_holder", "to_holder")
        result = await self._call(
            "supply_chain", "transfer_custody",
            product_id=body["product_id"],
            from_holder=body["from_holder"],
            to_holder=body["to_holder"],
        )
        return self._ok(result)

    # -- Insurance Expanded --

    async def _handle_parametric_policy(self, request: web.Request) -> web.Response:
        body = await self._parse_body(request)
        self._require(body, "holder", "trigger_type", "trigger_params", "coverage_amount", "premium")
        result = await self._call(
            "insurance", "create_parametric_policy",
            holder=body["holder"],
            trigger_type=body["trigger_type"],
            trigger_params=body["trigger_params"],
            coverage_amount=float(body["coverage_amount"]),
            premium=float(body["premium"]),
        )
        return self._ok(result)

    async def _handle_claim_settle(self, request: web.Request) -> web.Response:
        body = await self._parse_body(request)
        self._require(body, "claim_id", "settlement_amount")
        result = await self._call(
            "insurance", "settle_claim",
            claim_id=body["claim_id"],
            settlement_amount=float(body["settlement_amount"]),
        )
        return self._ok(result)

    # -- Privacy Expanded --

    async def _handle_private_transfer(self, request: web.Request) -> web.Response:
        body = await self._parse_body(request)
        self._require(body, "sender", "recipient", "amount", "token")
        result = await self._call(
            "privacy", "private_transfer",
            sender=body["sender"],
            recipient=body["recipient"],
            amount=float(body["amount"]),
            token=body["token"],
        )
        return self._ok(result)

    async def _handle_stealth_address(self, request: web.Request) -> web.Response:
        body = await self._parse_body(request)
        self._require(body, "owner")
        result = await self._call(
            "privacy", "generate_stealth_address",
            owner=body["owner"],
        )
        return self._ok(result)

    # ------------------------------------------------------------------
    # Batch dispatch
    # ------------------------------------------------------------------

    async def _handle_batch(self, request: web.Request) -> web.Response:
        """``POST /api/v1/batch`` — run multiple calls in one round trip.

        Expected body (sent by the MTRX iOS ``MTRXPackager.batchPackage``
        helper, with camelCase → snake_case on the wire)::

            {
              "requests": [
                {"id": "<uuid>", "method": "POST",
                 "path": "/api/v1/nfts/mint",
                 "body": {...}},
                ...
              ],
              "sequential": false,
              "abort_on_failure": false
            }

        The response mirrors
        ``BatchResponseEnvelope`` on the Swift side::

            {
              "results": [
                {"id": "...", "status": 200, "body": {...}, "error": null},
                ...
              ],
              "total_duration_ms": 42
            }
        """

        start_wall = time.monotonic()
        self._metric_incr("batch.requests")
        body = await self._parse_body(request)
        self._require(body, "requests")

        items = body["requests"]
        if not isinstance(items, list):
            self._metric_incr("batch.errors.bad_shape")
            raise web.HTTPBadRequest(
                text=json.dumps({"error": "'requests' must be a list"}),
                content_type="application/json",
            )
        if len(items) == 0:
            self._metric_observe("batch.items.count", 0)
            return web.json_response({
                "results": [],
                "total_duration_ms": 0,
            })
        if len(items) > BATCH_MAX_ITEMS:
            self._metric_incr("batch.errors.too_large")
            raise web.HTTPBadRequest(
                text=json.dumps({
                    "error": f"Batch exceeds maximum of {BATCH_MAX_ITEMS} items",
                }),
                content_type="application/json",
            )

        self._metric_observe("batch.items.count", float(len(items)))

        sequential = bool(body.get("sequential", False))
        abort_on_failure = bool(body.get("abort_on_failure", False))

        if sequential:
            self._metric_incr("batch.mode.sequential")
            results = await self._run_batch_sequential(items, abort_on_failure)
        else:
            self._metric_incr("batch.mode.parallel")
            results = await self._run_batch_parallel(items, abort_on_failure)

        total_ms = int((time.monotonic() - start_wall) * 1000)
        self._metric_observe("batch.duration_ms", float(total_ms))

        success_count = sum(1 for r in results if 200 <= r["status"] < 300)
        failure_count = len(results) - success_count
        if success_count:
            self._metric_incr("batch.item.success", success_count)
        if failure_count:
            self._metric_incr("batch.item.failure", failure_count)
        timeout_count = sum(1 for r in results if r.get("status") == 504)
        if timeout_count:
            self._metric_incr("batch.items.timeout", timeout_count)

        # Broadcast a batch-completed event so any SSE subscribers can
        # refresh their UI without polling.
        try:
            self._broadcaster.publish_dict(
                "batch.completed",
                {
                    "item_count": len(items),
                    "success_count": success_count,
                    "total_duration_ms": total_ms,
                },
            )
        except Exception:  # pragma: no cover — never let telemetry break a response
            logger.debug("batch SSE publish failed", exc_info=True)

        return web.json_response({
            "results": results,
            "total_duration_ms": total_ms,
        })

    async def _run_batch_sequential(
        self,
        items: list,
        abort_on_failure: bool,
    ) -> List[dict]:
        results: List[dict] = []
        for item in items:
            result = await self._dispatch_batch_item(item)
            results.append(result)
            if abort_on_failure and not (200 <= result["status"] < 300):
                # Pad remaining items so the response shape stays aligned
                # with the request order.
                for remaining in items[len(results):]:
                    item_id = remaining.get("id") if isinstance(remaining, dict) else None
                    results.append({
                        "id": item_id or "",
                        "status": 0,
                        "body": None,
                        "error": "aborted",
                    })
                break
        return results

    async def _run_batch_parallel(
        self,
        items: list,
        abort_on_failure: bool,
    ) -> List[dict]:
        tasks = [self._dispatch_batch_item(item) for item in items]
        results = await asyncio.gather(*tasks)
        if abort_on_failure:
            # For parallel mode abort_on_failure is a no-op by design —
            # everything already fired — but we preserve the flag so
            # clients can log it if they need to.
            pass
        return results

    async def _dispatch_batch_item(self, item: Any) -> dict:
        """Run one batch item and return a ``BatchItemResult`` dict."""

        if not isinstance(item, dict):
            return {
                "id": "",
                "status": 400,
                "body": None,
                "error": "Batch item must be an object",
            }

        item_id = item.get("id") or ""
        method = (item.get("method") or "POST").upper()
        path = item.get("path") or ""
        body = item.get("body")

        if not path:
            return {
                "id": item_id,
                "status": 400,
                "body": None,
                "error": "Batch item missing 'path'",
            }

        resolved = self._resolve_batch_route(method, path)
        if resolved is None:
            return {
                "id": item_id,
                "status": 404,
                "body": None,
                "error": f"No route for {method} {path}",
            }

        handler, match_info, literal_path = resolved
        sub_request = _BatchSubRequest(
            body=body,
            match_info=match_info,
            method=method,
            path=path,
        )

        try:
            response = await asyncio.wait_for(
                handler(sub_request),
                timeout=BATCH_ITEM_TIMEOUT_SECONDS,
            )
        except asyncio.TimeoutError:
            return {
                "id": item_id,
                "status": 504,
                "body": None,
                "error": (
                    f"Batch item exceeded {BATCH_ITEM_TIMEOUT_SECONDS:.0f}s timeout"
                ),
            }
        except web.HTTPException as exc:
            return {
                "id": item_id,
                "status": exc.status,
                "body": None,
                "error": self._extract_http_error(exc),
            }
        except Exception as exc:  # pragma: no cover — defence in depth
            logger.exception("Batch item %s crashed (%s %s)", item_id, method, literal_path)
            return {
                "id": item_id,
                "status": 500,
                "body": None,
                "error": str(exc),
            }

        return {
            "id": item_id,
            "status": response.status,
            "body": self._extract_response_body(response),
            "error": None,
        }

    @staticmethod
    def _extract_http_error(exc: web.HTTPException) -> str:
        text = exc.text or ""
        try:
            parsed = json.loads(text)
            if isinstance(parsed, dict) and "error" in parsed:
                return str(parsed["error"])
        except Exception:
            pass
        return text or exc.reason or "HTTP error"

    @staticmethod
    def _extract_response_body(response: web.Response) -> Any:
        text = response.text if hasattr(response, "text") else None
        if text is None and hasattr(response, "body"):
            try:
                text = response.body.decode("utf-8")  # type: ignore[assignment]
            except Exception:
                text = None
        if text is None:
            return None
        try:
            return json.loads(text)
        except Exception:
            return text

    # ------------------------------------------------------------------
    # Server-Sent Events stream
    # ------------------------------------------------------------------

    async def _handle_event_stream(self, request: web.Request) -> web.StreamResponse:
        """``GET /api/v1/events/stream`` — live SSE feed for the iOS app.

        Query parameters:

        * ``components`` — comma-separated component IDs (e.g.
          ``3,13,24``). Limits the stream to those components.
        * ``session`` — scope the feed to a single session id.
        * ``types`` — comma-separated event types
          (e.g. ``price.update,transaction.confirmed``).

        The response is an endless ``text/event-stream`` that ends when
        the client disconnects. A keep-alive comment is sent every 15s
        so NAT / LB idle timers don't kill the connection.
        """

        components = _parse_int_csv(request.query.get("components"))
        types = _parse_str_csv(request.query.get("types"))
        session_id = request.query.get("session") or None
        remote_ip = request.remote or None
        last_event_id = (
            request.headers.get("Last-Event-ID")
            or request.query.get("last_event_id")
            or None
        )

        self._metric_incr("sse.connect.attempt")

        # Try to register the subscriber *before* sending any bytes so
        # we can return a clean HTTP error on capacity rejection.
        try:
            sub = await self._broadcaster.register(
                components=components,
                session_id=session_id,
                types=types,
                remote_ip=remote_ip,
            )
        except BroadcasterCapacityError as exc:
            if exc.scope == "per_ip":
                raise web.HTTPTooManyRequests(
                    text=json.dumps({"error": str(exc), "scope": exc.scope}),
                    content_type="application/json",
                    headers={"Retry-After": "30"},
                )
            raise web.HTTPServiceUnavailable(
                text=json.dumps({"error": str(exc), "scope": exc.scope}),
                content_type="application/json",
                headers={"Retry-After": "5"},
            )

        response = web.StreamResponse(
            status=200,
            headers={
                "Content-Type": "text/event-stream",
                "Cache-Control": "no-cache, no-transform",
                "Connection": "keep-alive",
                "X-Accel-Buffering": "no",  # disable nginx/Caddy buffering
            },
        )
        await response.prepare(request)

        # Replay any events the client missed during the reconnect window.
        if last_event_id:
            try:
                missed = self._broadcaster.replay_since(last_event_id, matcher=sub)
            except Exception:  # pragma: no cover — replay must never break a stream
                missed = []
            for event in missed:
                try:
                    await response.write(
                        _format_sse(
                            event_type=event.type,
                            data=event.to_dict(),
                            event_id=event.event_id,
                        )
                    )
                except (ConnectionResetError, asyncio.CancelledError):
                    await self._broadcaster.unregister(sub)
                    return response

        # Send an initial hello event so the client knows the stream is
        # live even before the first real event arrives.
        try:
            await response.write(
                _format_sse(
                    event_type="stream.opened",
                    data={
                        "components": components or [],
                        "session_id": session_id,
                        "types": types or [],
                        "resumed_from": last_event_id,
                    },
                )
            )
        except (ConnectionResetError, asyncio.CancelledError):
            await self._broadcaster.unregister(sub)
            return response

        try:
            async for event in self._broadcaster.iter_events(sub):
                if event is None:
                    # Keep-alive comment line. Browsers/curl ignore it.
                    try:
                        await response.write(b": keepalive\n\n")
                    except (ConnectionResetError, asyncio.CancelledError):
                        break
                    continue
                try:
                    await response.write(
                        _format_sse(
                            event_type=event.type,
                            data=event.to_dict(),
                            event_id=event.event_id,
                        )
                    )
                except (ConnectionResetError, asyncio.CancelledError):
                    break
        finally:
            await self._broadcaster.unregister(sub)

        return response


# ---------------------------------------------------------------------------
# Helpers — SSE formatting and query parsing
# ---------------------------------------------------------------------------


def _format_sse(
    *,
    event_type: str,
    data: Any,
    event_id: Optional[str] = None,
) -> bytes:
    """Format one SSE frame.

    The Swift ``MTRXPackager.handleSSEMessage`` parser expects:

    * ``event: <type>``
    * ``data: <json>``
    * optional ``id: <event_id>``
    * terminating blank line
    """

    lines = [f"event: {event_type}"]
    if event_id:
        lines.append(f"id: {event_id}")
    payload = json.dumps(data, separators=(",", ":"), default=str)
    for line in payload.splitlines() or [payload]:
        lines.append(f"data: {line}")
    frame = "\n".join(lines) + "\n\n"
    return frame.encode("utf-8")


def _parse_int_csv(raw: Optional[str]) -> Optional[list]:
    if not raw:
        return None
    out = []
    for part in raw.split(","):
        part = part.strip()
        if not part:
            continue
        try:
            out.append(int(part))
        except ValueError:
            continue
    return out or None


def _parse_str_csv(raw: Optional[str]) -> Optional[list]:
    if not raw:
        return None
    out = [part.strip() for part in raw.split(",") if part.strip()]
    return out or None
