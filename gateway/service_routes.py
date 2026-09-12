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
import math
import re
import time
from typing import Any, Awaitable, Callable, Dict, List, Optional, Tuple

from aiohttp import web

from gateway.error_contract import client_error

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
        #: Cached P2 route-completion table (built once, shared by the live
        #: router and the batch dispatcher). See :meth:`_p2_route_specs`.
        self._p2_specs_cache: Optional[list] = None

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

        # Security preflight (the send-path gate consult; P1-5)
        app.router.add_post("/api/v1/security/preflight", self._handle_security_preflight)

        # Verifying-paymaster gas-sponsorship signature (P4)
        app.router.add_post("/api/v1/paymaster/sign", self._handle_paymaster_sign)

        # ETH/USD price (P4) — Chainlink primary, Coinbase fallback, honest 503
        app.router.add_get("/api/v1/price/eth-usd", self._handle_eth_usd_price)

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
        app.router.add_post("/api/v1/dispute/vote", self._handle_dispute_vote)
        app.router.add_post("/api/v1/dispute/claim", self._handle_dispute_claim)

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
        app.router.add_post("/api/v1/defi/swap/route", self._handle_swap_route)
        app.router.add_post("/api/v1/defi/swap/execute", self._handle_swap_execute)
        app.router.add_post("/api/v1/defi/bridge/quote", self._handle_bridge_quote)
        app.router.add_post("/api/v1/defi/bridge/execute", self._handle_bridge_execute)
        # NEW-61: five defi routes unregistered with their fabrications
        # (flash-loan/execute, vault/deposit, liquidity/provide, perp/trade,
        # collateral/manage). flash-loan/execute was ALSO permanently dead: it
        # dispatched to "flash_loan_execute", a method that never existed.
        # Real liquidity lives on the dex routes; real collateral management is
        # now reachable through the deposit_collateral / withdraw_collateral
        # actions.

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

        # ── Social ───────────────────────────────────────────────────
        app.router.add_post("/api/v1/social/post", self._handle_social_post)
        app.router.add_post("/api/v1/social/message/send", self._handle_social_message_send)
        app.router.add_post("/api/v1/social/gate/create", self._handle_social_gate)
        app.router.add_post("/api/v1/social/community/create", self._handle_community_create)
        app.router.add_get("/api/v1/social/feed/{wallet}", self._handle_social_feed)

        # ── Payments Expanded ────────────────────────────────────────

        # ── Compute & Storage ────────────────────────────────────────
        app.router.add_post("/api/v1/compute/store", self._handle_decentralized_store)
        app.router.add_post("/api/v1/compute/ipfs/pin", self._handle_ipfs_pin)
        app.router.add_post("/api/v1/compute/arweave/store", self._handle_arweave_store)

        # ── RWA ──────────────────────────────────────────────────────
        app.router.add_get("/api/v1/rwa/listings", self._handle_rwa_listings)

        # ── Prediction Markets ──────────────────────────────────────

        # ── Energy ───────────────────────────────────────────────────

        # ── Governance Expanded ──────────────────────────────────────
        app.router.add_post("/api/v1/governance/multisig/approve", self._handle_multisig_approve)
        app.router.add_post("/api/v1/governance/snapshot/vote", self._handle_snapshot_vote)

        # ── Portfolio ────────────────────────────────────────────────
        app.router.add_get("/api/v1/portfolio/complete/{wallet}", self._handle_portfolio_complete)
        app.router.add_get("/api/v1/portfolio/positions/{wallet}", self._handle_portfolio_positions)
        app.router.add_get("/api/v1/portfolio/history/{wallet}", self._handle_portfolio_history)

        # ── Intent Resolution ────────────────────────────────────────
        app.router.add_post("/api/v1/intent/resolve", self._handle_intent_resolve)
        app.router.add_post("/api/v1/intent/execute", self._handle_intent_execute)
        app.router.add_get("/api/v1/intent/summary/{plan_id}", self._handle_intent_summary)

        # ── Legal ────────────────────────────────────────────────────

        # ── AI ───────────────────────────────────────────────────────

        # ── Supply Chain Expanded ────────────────────────────────────
        app.router.add_post("/api/v1/supply-chain/provenance/log", self._handle_provenance_log)
        app.router.add_post("/api/v1/supply-chain/verify", self._handle_authenticity_verify)
        app.router.add_post("/api/v1/supply-chain/custody/transfer", self._handle_custody_transfer)

        # ── Insurance Expanded ───────────────────────────────────────
        app.router.add_post("/api/v1/insurance/parametric/create", self._handle_parametric_policy)
        # NEW-81: /api/v1/insurance/claim/settle removed from BOTH tables.
        # Its handler called insurance.settle_claim — a method that has never
        # existed (the real one is auto_settle_claim) — so the route returned
        # 404 on every request since it was written. Its params were wrong
        # twice over (claim_id/settlement_amount vs policy_id), and settlement
        # now requires an owner and oracle verification it never supplied.

        # ── Privacy ──────────────────────────────────────────────────

        # ── Capability Registry (data-driven Web3 capability surface) ──
        app.router.add_get("/api/v1/capabilities",                    self._handle_capabilities_list)
        app.router.add_get("/api/v1/capabilities/categories",         self._handle_capabilities_categories)
        app.router.add_get("/api/v1/capabilities/{capability_id}",    self._handle_capability_detail)
        app.router.add_post("/api/v1/capabilities/{capability_id}/invoke", self._handle_capability_invoke)

        # Batch dispatch and live event stream (used by MTRXPackager)
        app.router.add_post("/api/v1/batch", self._handle_batch)
        app.router.add_get("/api/v1/events/stream", self._handle_event_stream)

        # ── Real-Estate Escrow Engine (Component 46; feature-gated) ──
        # Every route crosses the _call → gate_action seam; the whole group
        # additionally 403s honestly while services.real_estate.enabled=false.
        app.router.add_post("/api/v1/realestate/properties", self._handle_re_property_create)
        app.router.add_get("/api/v1/realestate/properties", self._handle_re_property_list)
        app.router.add_get("/api/v1/realestate/properties/{id}", self._handle_re_property_get)
        app.router.add_post("/api/v1/realestate/properties/{id}/status", self._handle_re_property_status)
        app.router.add_post("/api/v1/realestate/properties/{id}/documents", self._handle_re_document_upload)
        app.router.add_get("/api/v1/realestate/properties/{id}/documents", self._handle_re_documents_get)
        app.router.add_get("/api/v1/realestate/properties/{id}/readiness", self._handle_re_readiness)
        app.router.add_get("/api/v1/realestate/documents/expiring", self._handle_re_docs_expiring)
        app.router.add_post("/api/v1/realestate/buyers/verify", self._handle_re_buyer_verify)
        app.router.add_get("/api/v1/realestate/buyers/{wallet}/verification", self._handle_re_buyer_verification_get)
        app.router.add_post("/api/v1/realestate/purchase", self._handle_re_purchase)
        app.router.add_post("/api/v1/realestate/escrow/{id}/confirm", self._handle_re_escrow_confirm)
        app.router.add_post("/api/v1/realestate/escrow/{id}/recording-complete", self._handle_re_recording_complete)
        app.router.add_post("/api/v1/realestate/escrow/{id}/refund", self._handle_re_escrow_refund)
        app.router.add_get("/api/v1/realestate/escrow/{id}", self._handle_re_escrow_get)

        # ── P2: route completion ─────────────────────────────────────
        # storage / messaging / groups / licensing / events / indexer /
        # oracle-feeds / compute-jobs / portfolio-performance. Each is a real
        # leg of the client skeleton: WIRE routes run through the _call() seam;
        # the rest return an honest 501 (never a fabricated 200).
        for method, path, handler in self._p2_route_specs():
            app.router.add_route(method, path, handler)

        self._build_batch_route_map()
        logger.info("ServiceRoutes: registered %d endpoints", 122 + len(self._p2_route_specs()))

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
            ("POST", "/api/v1/dispute/vote", self._handle_dispute_vote),
            ("POST", "/api/v1/dispute/claim", self._handle_dispute_claim),
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
            ("POST", "/api/v1/defi/swap/route", self._handle_swap_route),
            ("POST", "/api/v1/defi/swap/execute", self._handle_swap_execute),
            ("POST", "/api/v1/defi/bridge/quote", self._handle_bridge_quote),
            ("POST", "/api/v1/defi/bridge/execute", self._handle_bridge_execute),
            # NEW-61: same five removed from the SECOND registration table.
            ("POST", "/api/v1/nft/fractionalize", self._handle_nft_fractionalize),
            ("POST", "/api/v1/nft/rent", self._handle_nft_rent),
            ("POST", "/api/v1/nft/batch-mint", self._handle_nft_batch_mint),
            ("POST", "/api/v1/nft/royalty/claim", self._handle_nft_royalty_claim),
            ("POST", "/api/v1/nft/bridge", self._handle_nft_bridge),
            ("POST", "/api/v1/identity/did/create", self._handle_identity_did_create),
            ("POST", "/api/v1/identity/credential/issue", self._handle_credential_issue),
            ("POST", "/api/v1/identity/credential/verify", self._handle_credential_verify),
            ("POST", "/api/v1/identity/zk-proof/generate", self._handle_zk_proof),
            ("POST", "/api/v1/social/post", self._handle_social_post),
            ("POST", "/api/v1/social/message/send", self._handle_social_message_send),
            ("POST", "/api/v1/social/gate/create", self._handle_social_gate),
            ("POST", "/api/v1/social/community/create", self._handle_community_create),
            ("GET",  "/api/v1/social/feed/{wallet}", self._handle_social_feed),
            ("POST", "/api/v1/compute/store", self._handle_decentralized_store),
            ("POST", "/api/v1/compute/ipfs/pin", self._handle_ipfs_pin),
            ("POST", "/api/v1/compute/arweave/store", self._handle_arweave_store),
            ("GET",  "/api/v1/rwa/listings", self._handle_rwa_listings),
            ("POST", "/api/v1/governance/multisig/approve", self._handle_multisig_approve),
            ("POST", "/api/v1/governance/snapshot/vote", self._handle_snapshot_vote),
            ("GET",  "/api/v1/portfolio/complete/{wallet}", self._handle_portfolio_complete),
            ("GET",  "/api/v1/portfolio/positions/{wallet}", self._handle_portfolio_positions),
            ("GET",  "/api/v1/portfolio/history/{wallet}", self._handle_portfolio_history),
            ("POST", "/api/v1/intent/resolve", self._handle_intent_resolve),
            ("POST", "/api/v1/intent/execute", self._handle_intent_execute),
            ("GET",  "/api/v1/intent/summary/{plan_id}", self._handle_intent_summary),
            ("POST", "/api/v1/supply-chain/provenance/log", self._handle_provenance_log),
            ("POST", "/api/v1/supply-chain/verify", self._handle_authenticity_verify),
            ("POST", "/api/v1/supply-chain/custody/transfer", self._handle_custody_transfer),
            ("POST", "/api/v1/insurance/parametric/create", self._handle_parametric_policy),
            # NEW-81: claim/settle route removed (see note above).
            ("POST", "/api/v1/realestate/properties", self._handle_re_property_create),
            ("GET",  "/api/v1/realestate/properties", self._handle_re_property_list),
            ("GET",  "/api/v1/realestate/properties/{id}", self._handle_re_property_get),
            ("POST", "/api/v1/realestate/properties/{id}/status", self._handle_re_property_status),
            ("POST", "/api/v1/realestate/properties/{id}/documents", self._handle_re_document_upload),
            ("GET",  "/api/v1/realestate/properties/{id}/documents", self._handle_re_documents_get),
            ("GET",  "/api/v1/realestate/properties/{id}/readiness", self._handle_re_readiness),
            ("GET",  "/api/v1/realestate/documents/expiring", self._handle_re_docs_expiring),
            ("POST", "/api/v1/realestate/buyers/verify", self._handle_re_buyer_verify),
            ("GET",  "/api/v1/realestate/buyers/{wallet}/verification", self._handle_re_buyer_verification_get),
            ("POST", "/api/v1/realestate/purchase", self._handle_re_purchase),
            ("POST", "/api/v1/realestate/escrow/{id}/confirm", self._handle_re_escrow_confirm),
            ("POST", "/api/v1/realestate/escrow/{id}/recording-complete", self._handle_re_recording_complete),
            ("POST", "/api/v1/realestate/escrow/{id}/refund", self._handle_re_escrow_refund),
            ("GET",  "/api/v1/realestate/escrow/{id}", self._handle_re_escrow_get),
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
                ("GET",  "/bridge/v1/dashboard", br.get_dashboard),
                ("GET",  "/bridge/v1/components", br.get_components),
                ("GET",  "/bridge/v1/components/manifest", br.get_components_manifest),
                ("GET",  "/bridge/v1/components/{component_id}", br.get_component),
            ]
            specs.extend(bridge_specs)

        # P2 completion routes participate in batch dispatch too, so
        # /api/v1/batch sub-calls resolve them identically to the live router.
        specs.extend(self._p2_route_specs())

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

    # RUN-4: inner status -> HTTP status. Only the two values that mean "the
    # operation did not happen" are failures.
    #
    # Deliberately NOT in this set: submitted, active, pending, completed,
    # verified, registered, updated, rejected, failed. Those are legitimate
    # DOMAIN outcomes the caller asked about — a rejected claim or a failed
    # transaction is a real answer, not a transport error. Treating them as
    # HTTP failures would break working flows and is the opposite mistake to
    # the one RUN-4 fixes.
    _FAILURE_STATUSES = frozenset({"error", "unavailable"})

    # When the service says WHY, honour it; otherwise 422 — the request was
    # well-formed but the operation could not be completed.
    _ERROR_CATEGORY_HTTP = {
        "validation": 400,
        "bad_request": 400,
        "not_found": 404,
        "forbidden": 403,
        "not_implemented": 501,
        "service_unavailable": 503,
        "service_error": 502,
        "timeout": 504,
    }

    # client_error's statuses, as the aiohttp exceptions `_call` raises.
    _HTTP_ERROR_FOR_STATUS = {
        400: web.HTTPBadRequest,
        404: web.HTTPNotFound,
        500: web.HTTPInternalServerError,
        503: web.HTTPServiceUnavailable,
        504: web.HTTPGatewayTimeout,
    }

    def _ok(self, data: Any) -> web.Response:
        """Wrap a service result — but never dress a failure as a success.

        RUN-4: this used to return HTTP 200 with {"status":"ok","data":...}
        unconditionally, including when `data` itself said
        {"status":"error"}. The transport claimed success while the payload
        reported failure, and every SDK believes the transport: the Python
        client checks only `resp.status != 200`, the Swift client decodes the
        outer envelope and discards its status, and 9 sdk-js methods check
        nothing at all. A caller therefore received an error dictionary and
        proceeded as though the call had worked — which on the iOS side meant
        a failed transfer closed the send sheet and cleared the form (NEW-21).

        A failing payload now gets a real HTTP status so the failure is
        impossible to miss, and the body keeps the service's own detail so
        callers lose nothing they had before.
        """
        status = data.get("status") if isinstance(data, dict) else None
        if isinstance(status, str) and status in self._FAILURE_STATUSES:
            category = data.get("error_category")
            if status == "unavailable":
                http_status = 503
            else:
                http_status = self._ERROR_CATEGORY_HTTP.get(category, 422)
            return web.json_response(
                {"status": status, "data": data}, status=http_status
            )
        return web.json_response({"status": "ok", "data": data})

    async def _call(self, service_name: str, method_name: str, **kwargs) -> Any:
        """Resolve a service and call its method.

        Security gate (boundary call): every service invocation that reaches this
        funnel — direct ``/api/v1/*`` endpoints AND batch sub-calls — is routed
        through the Morpheus contract first, with the per-request identity + App
        Attest context bound at the HTTP entry. A blocked action returns a GENERIC
        denial; the internal reason stays server-side. Inert (allows) when the
        private security package isn't installed.
        """
        from gateway.security_gate import (
            action_type_for, current_request_security, gate_action,
            generic_denial, is_blocked,
        )
        decision = await gate_action(
            action_type_for(service_name, method_name), kwargs, current_request_security()
        )
        if is_blocked(decision):
            raise web.HTTPForbidden(
                text=json.dumps({"error": generic_denial(decision)}),
                content_type="application/json",
            )

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
            result = await method(**kwargs)
        except TypeError as exc:
            # RUN-5b: was `f"Invalid parameters: {exc}"`. A TypeError from
            # `method(**kwargs)` quotes the INTERNAL Python signature back at
            # the caller ("...got an unexpected keyword argument 'x'",
            # "missing 1 required positional argument: 'user_id'"), which maps
            # the service layer for anyone probing the seam. Still a 400 — it
            # genuinely is a caller error — but the signature stays server-side
            # against the ref.
            logger.error("Bad params for %s.%s: %s", service_name, method_name, exc)
            _st, _err = client_error(
                exc, None, what=f"{service_name}.{method_name}", code="invalid_request")
            raise web.HTTPBadRequest(
                text=json.dumps(_err),
                content_type="application/json",
            )
        except ValueError as exc:
            # Invalid parameter *value* (e.g. an unsupported oracle pair) is an
            # honest client error, not a server fault — surface a 400, never a 500.
            logger.info("Rejected %s.%s: %s", service_name, method_name, exc)
            raise web.HTTPBadRequest(
                text=json.dumps({"error": str(exc)}),
                content_type="application/json",
            )
        except NotImplementedError as exc:
            # A DELIBERATE REFUSAL — the capability does not exist and never
            # will until it is built. Without this clause it fell to the generic
            # handler below as HTTP 500 + an ERROR-level stack trace: a
            # permanently-unavailable capability reported as the server
            # malfunctioning, which retry layers treat as transient.
            #
            # THIS CLAUSE IS HALF OF A PAIR. The dispatcher maps
            # NotImplementedError -> "not_implemented"/501 and everything else
            # to "service_error"/502; this gateway maps ValueError -> 400 and
            # everything else to 500. The two ladders disagree, so changing a
            # refusal's exception type improves one surface and regresses the
            # other unless both move together. Converting the governance
            # refusals to NotImplementedError took the dispatcher 502 -> 501 and
            # this route 400 -> 500; adding the clause here is what makes the
            # change a net improvement rather than a traded defect.
            # tests/test_refusal_classification.py asserts BOTH surfaces agree.
            logger.info(
                "Refused %s.%s (capability unavailable): %s",
                service_name, method_name, exc,
            )
            raise web.HTTPNotImplemented(
                text=json.dumps({
                    "error": str(exc),
                    "error_category": "not_implemented",
                }),
                content_type="application/json",
            )
        except Exception as exc:
            # This was `HTTPInternalServerError({"error": str(exc)})`: whatever a
            # service raised — an RPC URL with credentials in it, a provider's
            # quota text — became the body of every direct route and batch
            # sub-call that funnels through here. RUN-5 built client_error for
            # exactly this and applied it to 13 sites; the funnel they all share
            # was not one of them. It also said 500 for a dependency that was
            # merely unreachable. client_error logs the full exception against
            # a ref and decides both the status (500/503/504) and what the
            # client may see.
            _st, _err = client_error(
                exc, None, what=f"{service_name}.{method_name}")
            raise self._HTTP_ERROR_FOR_STATUS.get(
                _st, web.HTTPInternalServerError)(
                text=json.dumps(_err),
                content_type="application/json",
            )

        # Step 13 of the loop — ripple out. A successfully executed action
        # publishes to the live feed. Reached ONLY after a real result, so an
        # honest failure (which raised above) never ripples.
        self._maybe_ripple(service_name, method_name, kwargs, result)
        return result

    # Only UNAMBIGUOUS read verbs skip the ripple. Prefixes like request_ /
    # resolve_ / verify_ / snapshot_ are deliberately NOT here: each also names a
    # consequential write (request_arbitration, resolve, resolve_market,
    # verify_milestone, snapshot_vote) that MUST ripple. Read-shaped calls that
    # slip past these prefixes are caught by the list-result guard below.
    _READ_PREFIXES: Tuple[str, ...] = (
        "get_", "list_", "fetch_", "iter_", "is_", "has_", "read_", "query_", "query",
    )

    def _maybe_ripple(self, service_name: str, method_name: str, kwargs: dict, result: Any) -> None:
        """Publish a ``feed.ripple`` event for an executed consequential action.

        Privacy actions NEVER ripple (private_transfer / stealth / private_vote /
        confidential_compute and the privacy-backed storage legs all live on the
        ``privacy`` service). Reads never ripple. A publish failure can never
        break the action itself.
        """
        if service_name == "privacy":
            return
        # A collection result is a read/lookup, never a single consequential action.
        if isinstance(result, list):
            return
        m = method_name.lower()
        if any(m == p or m.startswith(p) for p in self._READ_PREFIXES):
            return
        # create_post already emits a richer ``social.post`` event — don't double.
        if service_name == "social" and method_name == "create_post":
            return
        actor = ""
        for k in ("owner", "creator", "author", "sender", "from_", "from",
                  "uploader", "requester", "employer", "holder", "minter",
                  "user", "voter", "address", "delegator"):
            v = kwargs.get(k)
            if isinstance(v, str) and v:
                actor = v
                break
        from gateway.security_gate import action_type_for
        payload: Dict[str, Any] = {
            "action": action_type_for(service_name, method_name),
            "service": service_name,
            "method": method_name,
            "actor": actor,
        }
        if isinstance(result, dict):
            ref = result.get("id") or result.get("tx_hash") or result.get("hash")
            if ref:
                payload["ref"] = str(ref)
            status = result.get("status")
            if isinstance(status, str):
                payload["status"] = status
        try:
            self._broadcaster.publish_dict("feed.ripple", payload)
        except Exception:  # pragma: no cover — a ripple failure must not break the action
            logger.debug("ripple publish failed for %s.%s", service_name, method_name)

    # ------------------------------------------------------------------
    # Endpoint handlers
    # ------------------------------------------------------------------

    # -- ETH/USD price (P4) --

    def _price_feed(self):
        from runtime.blockchain.price_feed import PriceFeed
        if getattr(self, "_price_feed_inst", None) is None:
            self._price_feed_inst = PriceFeed(getattr(self, "_config", {}) or {})
        return self._price_feed_inst

    async def _handle_eth_usd_price(self, request: web.Request) -> web.Response:
        """GET /api/v1/price/eth-usd -> {pair, price, source, decimals, updated_at}.
        Chainlink primary, Coinbase fallback, 30s cache. If no source is reachable
        -> 503 (never a stale/invented number)."""
        from runtime.blockchain.price_feed import PriceUnavailable
        try:
            data = await self._price_feed().eth_usd()
        except PriceUnavailable as exc:
            # The documented outcome: no source reachable is a dependency
            # failure (503), not an internal error. Without the explicit code,
            # client_error() classified PriceUnavailable as internal_error (500)
            # and the one branch written for this case broke the contract.
            _st, _err = client_error(exc, request.get("request_id"), what="Service",
                                     code="upstream_unavailable")
            return web.json_response(_err, status=_st)
        except Exception as exc:
            logger.exception("eth-usd price failed")
            return web.json_response({"error": "price unavailable"}, status=503)
        return web.json_response(data)

    # -- Verifying paymaster sign (P4) --

    @staticmethod
    def _sponsorship_identity(request: "web.Request") -> str:
        """The wallet the security middleware bound for this request.

        Bound, not authenticated: it is the session's identity when a session is
        presented, and otherwise the caller-written X-Wallet-Address header or a
        body wallet/from/sender/account field (gateway/server.py
        _security_context_middleware). Empty when none of those is present; the
        handler then meters the body `sender`, and the policy denies only when
        that is empty too and a cap is configured.
        """
        from gateway.security_gate import current_request_security
        from runtime.blockchain.sponsorship import canonical_identity
        return canonical_identity((current_request_security() or {}).get("wallet"))

    async def _estimate_sponsorship_usd(self, cfg: dict, body: dict) -> float:
        """Worst-case USD cost of the gas this userOp asks the platform to cover.

        max_fee_per_gas x (callGasLimit + verificationGasLimit +
        preVerificationGas) is the ceiling the EntryPoint can charge the
        paymaster for this operation, so metering the ceiling is the reading
        that cannot under-count. Priced with the same PriceFeed the /price route
        uses; it raises rather than return a stale number, and this method lets
        that raise through to the caller's 503.
        """
        def _int(key: str) -> int:
            try:
                return int(body.get(key, 0) or 0)
            except (TypeError, ValueError):
                return 0

        total_gas = (_int("call_gas_limit") + _int("verification_gas_limit")
                     + _int("pre_verification_gas"))
        wei = total_gas * _int("max_fee_per_gas")
        if wei <= 0:
            return 0.0
        quote = await self._price_feed().eth_usd()
        return (wei / 1e18) * float(quote["price"])


    async def _handle_paymaster_sign(self, request: web.Request) -> web.Response:
        """POST /api/v1/paymaster/sign — sign a gas-sponsorship approval for a
        UserOperation. Returns {"paymasterAndData": "0x..."} the client splices
        into the userOp. Non-custodial: signs ONLY a gas-sponsorship digest with a
        platform key; never the account's own signature, never moves user funds.

        Sponsorship policy (allowlisted actions + per-identity daily USD cap)
        is checked before signing; unconfigured signer/paymaster -> 503; a denied
        policy -> 403 with an honest reason; call_data/init_code that is not hex
        -> 400.

        §EE: the allowlist is checked against what the userOp's own call_data
        and init_code DO (runtime.blockchain.sponsorship.classify_user_operation)
        — the bytes the digest commits to. It used to be checked against the
        body's `action_type`, defaulting to "transfer", so any request satisfied
        it by saying so; the MTRX client hardcodes "transfer" for every send, so
        the label was never information even from an honest caller. The field is
        still accepted and a disagreement is logged, but it decides nothing.
        The labels name ABI functions, not behaviour: the target, a value
        recipient and the sender account are not verified (sponsorship.py, WHAT
        IT CANNOT KNOW). With no allowlist configured the call data is not
        decoded at all.

        D-045: the cap in that sentence had no reader anywhere in the tree — the
        handler checked `allowed_actions` and nothing else, so one holder of the
        single static API key could request unlimited sponsorship, for any
        account, until the EntryPoint deposit was empty. Three things changed:

          * the sponsored account is bound to the identity the security
            middleware bound for THIS request. A body `sender` that disagrees is
            refused rather than honoured. That identity is a session's when one
            is presented; without a session it is the X-Wallet-Address header or
            body field the caller writes;
          * the request is priced from its own gas fields against a live ETH/USD
            quote and metered against the configured per-identity daily cap.
            Per identity means per address: a caller who writes a new address
            gets a fresh cap, so the cap bounds spend per address, not per
            caller;
          * the budget is reserved before signing and committed only once a
            signature actually exists, so a signing failure does not charge
            anyone for gas that was never sponsored.

        An operator with no `daily_cap_usd` configured sees the previous
        behaviour exactly.
        """
        from gateway.paymaster import (
            compute_paymaster_digest, sign_digest, build_paymaster_and_data,
            paymaster_config, signer_configured,
        )
        from runtime.blockchain import sponsorship
        from runtime.blockchain.sponsorship import SponsorshipPolicy, summarize_labels
        body = await self._parse_body(request)
        cfg = getattr(self, "_config", {}) or {}
        pcfg = paymaster_config(cfg)

        if not signer_configured(cfg) or not pcfg.get("address"):
            return web.json_response(
                {"error": "paymaster not configured"}, status=503)

        policy = SponsorshipPolicy.from_config(cfg)

        # Bind the sponsored account to the identity bound for this request
        # (a session's, else the caller-written header or body field). Same
        # idiom as _handle_governance_vote: a bound identity always wins, and a
        # body value that contradicts it is refused, not preferred.
        identity = self._sponsorship_identity(request)
        body_sender = str(body.get("sender", "") or "").strip()
        if identity and body_sender and body_sender.lower() != identity.lower():
            logger.warning(
                "paymaster sign refused: body sender does not match the "
                "authenticated caller")
            return web.json_response(
                {"error": "sender does not match the authenticated caller"},
                status=403)
        sender = identity or body_sender

        def _bytes(key):
            v = str(body.get(key, "") or "")
            return bytes.fromhex(v[2:] if v.startswith("0x") else v) if v else b""

        # The bytes are parsed once, here, and the SAME bytes are both classified
        # for the allowlist and hashed into the digest below — so what the
        # policy judged is what gets signed. Not-hex is the caller's malformed
        # input (400), with or without a policy, exactly as it was when the
        # digest step was the first thing to read these fields.
        try:
            call_data = _bytes("call_data")
            init_code = _bytes("init_code")
        except (TypeError, ValueError) as exc:
            logger.info("paymaster sign: call_data/init_code is not hex")
            _st, _err = client_error(
                exc, None, what="Paymaster sign", code="invalid_request")
            return web.json_response(_err, status=_st)

        # §EE: derive the action from what is being sponsored. The body's
        # `action_type` is logged when it disagrees and is otherwise ignored.
        #
        # Only an allowlist reads the labels, so with none configured the
        # caller's bytes are not decoded at all — hex-decoded and hashed, as
        # before this policy read them. The classifier is linear in its input
        # either way (sponsorship.py, HOW IT DECODES); not running it where
        # nothing depends on it keeps an unconfigured deployment's sign path
        # exactly what it was.
        if policy.allowed_actions is None:
            actions = ["unclassified"]
        else:
            actions = sponsorship.classify_user_operation(
                call_data, init_code, account_factory=pcfg.get("account_factory"))
            declared = body.get("action_type")
            if declared is not None and [str(declared)] != actions:
                logger.info(
                    "paymaster sign: declared action_type %r; the call data "
                    "performs %s, and the call data decides",
                    str(declared)[:64], summarize_labels(actions))

        # Price this request before metering it. A cap denominated in dollars
        # cannot be enforced against an unknown dollar amount, so an unavailable
        # quote is a 503 — never an unmetered signature.
        est_usd = 0.0
        if policy.enforces_a_cap:
            try:
                est_usd = await self._estimate_sponsorship_usd(cfg, body)
            except Exception:
                logger.exception("sponsorship pricing unavailable — refusing to "
                                 "sign an unmeterable request")
                return web.json_response(
                    {"error": "gas price unavailable; sponsorship cannot be "
                              "metered against the configured daily cap"},
                    status=503)

        decision = policy.authorize_and_reserve(
            actions, identity=sender, est_usd=est_usd)
        if not decision.allowed:
            logger.info("paymaster sponsorship denied: %s", decision.code)
            return web.json_response(
                {"error": decision.reason, "code": decision.code,
                 "policy": decision.to_dict()},
                status=403)

        def _int(key, default=0):
            try:
                return int(body.get(key, default) or default)
            except (TypeError, ValueError):
                return default

        # RUN-5b: this was ONE `try` around both halves, ending in
        # `{"error": f"sign failed: {exc}"}` at 400. Two separate defects.
        #
        # (a) The exception text was the response body, and the second half
        #     calls `sign_digest(digest, str(pcfg.get("signer_key")))` — a
        #     malformed key raises with THE KEY VALUE in its message. That is
        #     signing-key material on a client-visible money path.
        #
        # (b) The blanket 400 told the caller their request was bad when the
        #     real fault was our own signer configuration, which both misleads
        #     the client and hides an operational problem behind a 4xx.
        #
        # Split: caller-supplied input is a 400, our signing is a 5xx, and
        # neither returns the exception.
        try:
            digest = compute_paymaster_digest(
                sender=sender,
                nonce=_int("nonce"),
                init_code=init_code,
                call_data=call_data,
                call_gas_limit=_int("call_gas_limit"),
                verification_gas_limit=_int("verification_gas_limit"),
                pre_verification_gas=_int("pre_verification_gas"),
                max_fee_per_gas=_int("max_fee_per_gas"),
                max_priority_fee_per_gas=_int("max_priority_fee_per_gas"),
                chain_id=_int("chain_id", int(cfg.get("blockchain", {}).get("chain_id", 84532))),
                paymaster=str(pcfg.get("address")),
                valid_until=_int("valid_until"),
                valid_after=_int("valid_after"),
            )
        except Exception as exc:
            policy.release(decision.reservation_id)
            logger.exception("paymaster digest rejected caller input")
            _st, _err = client_error(
                exc, None, what="Paymaster sign", code="invalid_request")
            return web.json_response(_err, status=_st)

        try:
            sig = sign_digest(digest, str(pcfg.get("signer_key")))
            pnd = build_paymaster_and_data(
                str(pcfg.get("address")), _int("valid_until"), _int("valid_after"), sig)
        except Exception as exc:
            policy.release(decision.reservation_id)
            logger.exception("paymaster signing failed — check the configured signer key")
            _st, _err = client_error(
                exc, None, what="Paymaster sign", code="internal_error")
            return web.json_response(_err, status=_st)

        # The signature exists — only now is the budget actually spent.
        policy.commit(decision.reservation_id)
        return web.json_response({"paymasterAndData": pnd})

    # -- Security preflight (P1-5) --

    async def _handle_security_preflight(self, request: web.Request) -> web.Response:
        """POST /api/v1/security/preflight — consult the Morpheus gate for a
        fund-moving transfer WITHOUT executing anything. Returns the exact
        status/shape the iOS client maps to .securityBlocked so a deny can
        finally be delivered (before this route, the 404 always fail-opened).

          allowed  -> 200 {"allow": true, "mode": "<gate mode>"}
          blocked  -> 403 {"error": "<generic denial>"}  (mirrors _call)

        Under the noop backend the gate allows, so the route still returns
        {"allow": true} — never 404 — so the client's deny path becomes
        reachable the moment a real backend is deployed.
        """
        body = await self._parse_body(request)
        from gateway.security_gate import (
            current_request_security, gate_action, generic_denial, is_blocked,
        )
        to = str(body.get("to", ""))
        try:
            value_usd = float(body.get("value_usd", 0) or 0)
        except (TypeError, ValueError):
            value_usd = 0.0
        try:
            chain_id = int(body.get("chain_id", 0) or 0)
        except (TypeError, ValueError):
            chain_id = 0
        decision = await gate_action(
            "transfer",
            {"to": to, "value_usd": value_usd, "chain_id": chain_id,
             "app_attest": body.get("app_attest")},
            current_request_security(),
        )
        if is_blocked(decision):
            raise web.HTTPForbidden(
                text=json.dumps({"error": generic_denial(decision)}),
                content_type="application/json",
            )
        return web.json_response({"allow": True, "mode": decision.get("mode", "observe")})

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
        """RUN-2: deployment is not implemented. Say so, in the status line.

        This handler used to be byte-identical to _handle_contract_convert and
        dispatched to the same contract_conversion.convert. The service has no
        deploy method at all — nothing in the path touched a chain, a wallet or
        a signer. A client POSTing here got HTTP 200 with status ok and
        concluded a contract had been deployed. That was wrong 100% of the time.

        501 is the honest answer: the route is recognised, the capability is not
        built. Implementing real deployment is a feature with real risk (key
        custody, gas, chain selection, failure semantics) and needs its own
        design pass — deliberately NOT smuggled in behind a bug fix.
        """
        return web.json_response(
            {
                "status": "not_implemented",
                "error": "Contract deployment is not implemented.",
                "detail": (
                    "This endpoint previously returned a converted contract and "
                    "reported success, which read as a completed deployment. It "
                    "never deployed anything. Use POST /api/v1/contracts/convert "
                    "to generate Solidity; deploying it is a separate step you "
                    "currently perform with your own tooling and signer."
                ),
                "see": "/api/v1/contracts/convert",
            },
            status=501,
        )

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
        # NEW-89 CONTRACT-GAP + DROPPED-INTENT: `collection_type` is required
        # by the service and was never collected; `metadata` was collected and
        # is not accepted. Neither substitutes for the other.
        self._require(body, "creator", "name", "symbol", "collection_type")
        result = await self._call(
            "nft_services", "create_collection",
            creator=body["creator"],
            name=body["name"],
            symbol=body["symbol"],
            collection_type=body["collection_type"],
            royalty_bps=int(body.get("royalty_bps", 500)),
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
        # NEW-78: `trigger_data` is gone — it was the claimant's own "proof"
        # of the covered event, and the claim decision now comes from oracle
        # data instead. The caller is bound to the wallet the security
        # middleware bound for THIS request (a session's identity when one is
        # presented, otherwise the caller-written X-Wallet-Address header or a
        # body field), following the same idiom as _handle_governance_vote:
        # a bound identity always wins, a body-supplied holder is a dev
        # fallback only, and an absent caller is refused by assert_owner rather
        # than silently skipped.
        body = await self._parse_body(request)
        self._require(body, "policy_id")
        from gateway.security_gate import current_request_security
        authed = str((current_request_security() or {}).get("wallet") or "")
        caller = authed or str(body.get("holder") or "")
        result = await self._call(
            "insurance", "file_claim",
            policy_id=body["policy_id"],
            caller=caller,
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
        self._require(body, "proposal_id", "support")
        # P5-1: bind the vote to the wallet the security middleware bound for
        # THIS request. That is a session's identity when a session is
        # presented; without one it is the caller-written X-Wallet-Address
        # header (or a body wallet/from field), so the binding is only as strong
        # as the session. A bound identity always wins, so a mismatched body
        # ``voter`` is ignored (the vote is recorded under the bound wallet). The
        # body voter is a testnet/dev fallback only, used when no identity was
        # bound. The 400 for a
        # fully-absent voter just mirrors the prior _require("voter") — no gate
        # stricter than before, and the Morpheus OBSERVE gate itself is untouched.
        from gateway.security_gate import current_request_security
        authed = str((current_request_security() or {}).get("wallet") or "")
        voter = authed or str(body.get("voter") or "")
        if not voter:
            raise web.HTTPBadRequest(
                text=json.dumps({"error": "voter identity required"}),
                content_type="application/json",
            )
        # governance.vote's parameter is `choice`, not `support` — passing
        # support= raised TypeError (500) on every live vote. Map it here.
        result = await self._call(
            "governance", "vote",
            proposal_id=body["proposal_id"],
            voter=voter,
            choice=body["support"],
        )
        return self._ok(result)

    # -- Dispute Resolution --

    async def _handle_dispute_file(self, request: web.Request) -> web.Response:
        body = await self._parse_body(request)
        self._require(body, "complainant", "respondent", "dispute_type", "description")
        # Kwargs must match DisputeResolution.file_dispute(claimant, respondent,
        # category, evidence, stake_amount) — the old complainant/dispute_type/
        # description kwargs made every call a TypeError 500.
        result = await self._call(
            "dispute_resolution", "file_dispute",
            claimant=body["complainant"],
            respondent=body["respondent"],
            category=body["dispute_type"],
            evidence={"description": body["description"], **(body.get("evidence") or {})},
            stake_amount=float(body.get("stake_amount", 0) or 0),
        )
        return self._ok(result)

    async def _handle_dispute_vote(self, request: web.Request) -> web.Response:
        """Juror vote commitment — panel-membership enforced by the service."""
        body = await self._parse_body(request)
        self._require(body, "dispute_id", "juror", "vote")
        result = await self._call(
            "dispute_resolution", "vote",
            dispute_id=body["dispute_id"],
            juror=body["juror"],
            vote=body["vote"],
            justification=body.get("justification", ""),
        )
        return self._ok(result)

    async def _handle_dispute_claim(self, request: web.Request) -> web.Response:
        """Post-resolution entitlement claim — idempotent, no funds held here."""
        body = await self._parse_body(request)
        self._require(body, "dispute_id", "claimant")
        result = await self._call(
            "dispute_resolution", "claim",
            dispute_id=body["dispute_id"],
            claimant=body["claimant"],
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
        """POST /api/v1/privacy/delete — answers 501, queues nothing (NEW-38).

        The route is deliberately KEPT rather than unregistered. An erasure
        endpoint that 404s reads as "wrong URL"; this one states plainly that
        the platform cannot delete data. `request_deletion` now refuses, and
        its {"status": "error", "error_category": "not_implemented"} maps to
        HTTP 501 through `_ok`'s RUN-4 failure branch — the same code
        /api/v1/contracts/deploy returns.
        """
        body = await self._parse_body(request)
        # `_require(body, "user", "data_types")` is dropped: it answered 400
        # "missing field" — a claim about the request — when the truth is a
        # fact about the platform, and it made the honest 501 conditional on
        # the caller correctly filling in a form for an operation that cannot
        # run. Defaults keep the call bindable so this cannot become a 500.
        #
        # Still routed through `_call` rather than short-circuited here, so the
        # security seam continues to observe the attempt.
        result = await self._call(
            "privacy", "request_deletion",
            user=body.get("user", ""),
            data_types=body.get("data_types") or [],
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
            # NEW-89 RENAME: the service spells these from_/to_currency.
            from_currency=body["source_currency"],
            to_currency=body["destination_currency"],
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
        """POST /api/v1/payments/create — reconciled to the method (NEW-58).

        This route was PERMANENTLY DEAD. It sent payer/payee/amount/token to
        `create_payment(agent_id, recipient, amount, token, purpose)`, so every
        call raised TypeError on the unexpected `payer`/`payee` and the
        required `purpose` was never supplied. The x402 payment-creation
        endpoint has never worked over HTTP; only the ACTION_MAP path did.

        The body keys stay payer/payee for wire compatibility (nothing that
        works today is broken by keeping them) and are mapped to the method's
        real parameter names here.
        """
        body = await self._parse_body(request)
        self._require(body, "payer", "payee", "amount", "token")
        result = await self._call(
            "x402_payments", "create_payment",
            agent_id=body["payer"],
            recipient=body["payee"],
            amount=float(body["amount"]),
            token=body["token"],
            purpose=body.get("purpose", ""),
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
        # ETH/USD is backed by the real price feed (P4); other pairs keep the
        # existing oracle_gateway path.
        if pair.lower().replace("_", "-") in ("eth-usd", "ethusd"):
            from runtime.blockchain.price_feed import PriceUnavailable
            try:
                return web.json_response(await self._price_feed().eth_usd())
            except PriceUnavailable as exc:
                _st, _err = client_error(
                    exc, request.get("request_id"), what="PriceFeed"
                )
                return web.json_response(_err, status=_st)
            except Exception as exc:
                _st, _err = client_error(
                    exc, request.get("request_id"), what="PriceFeed"
                )
                return web.json_response(_err, status=_st)
        try:
            result = await self._call(
                "oracle_gateway", "request",
                oracle_type="price_feed",
                params={"pair": pair},
            )
        except web.HTTPException as exc:
            # An unsupported pair is an honest 400 (raised by _call from the
            # service's ValueError); a security denial is a 403. Any 5xx here
            # means the price-feed backend is unreachable (e.g. no RPC / web3)
            # — surface that honestly as 503, never a bare 500 masquerade.
            if exc.status >= 500:
                return web.json_response({"error": "price unavailable"}, status=503)
            raise
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

    # NEW-61: five handler bodies removed with their routes
    # (_handle_flash_loan, _handle_vault_deposit, _handle_liquidity_provide,
    # _handle_perp_trade, _handle_collateral_manage). An unregistered handler
    # is still a callable path, so the bodies go with the registrations.
    #
    # ALL FIVE WERE PERMANENTLY DEAD, independently of the fabrications behind
    # them — every one forwarded parameter names its target could not accept:
    #   flash_loan        -> "flash_loan_execute" (no such method) with
    #                        token/operations vs the method's asset/strategy
    #   vault_deposit     -> wallet, vault_id     vs vault, asset
    #   liquidity_provide -> wallet, pool_id, token_a_amount, token_b_amount
    #                        vs token_a, token_b, amount_a, amount_b
    #   perp_trade        -> wallet, market, side vs asset, direction
    #   collateral_manage -> wallet, token        vs asset, position_id
    # so every HTTP call raised TypeError at dispatch. Not one of these
    # endpoints has ever completed a request. (Domain 4 found one dead route
    # of this shape; this is five in a row, in one block.)

    # -- NFT Expanded --

    async def _handle_nft_fractionalize(self, request: web.Request) -> web.Response:
        body = await self._parse_body(request)
        # NEW-89 CONTRACT-GAP: `collection` was never collected. `owner` is
        # NOT the collection — binding it there would fix the TypeError and
        # fractionalise a token in whatever collection is named by an address.
        self._require(body, "owner", "token_id", "fractions", "collection")
        # §CD sibling pass: `owner` was required and then never forwarded — the
        # route advertised an authorization input that governed nothing. It is
        # bound the way every other identity on this funnel is: the wallet the
        # middleware authenticated wins, the body field is the dev fallback.
        from gateway.security_gate import current_request_security
        authed = str((current_request_security() or {}).get("wallet") or "")
        result = await self._call(
            "nft_services", "fractionalize",
            collection=body["collection"],
            token_id=body["token_id"],
            fractions=int(body["fractions"]),
            price_per_fraction=body.get("price_per_fraction"),
            owner=authed or str(body.get("owner") or ""),
        )
        return self._ok(result)

    async def _handle_nft_rent(self, request: web.Request) -> web.Response:
        body = await self._parse_body(request)
        # NEW-89 CONTRACT-GAP: `collection` was never collected.
        self._require(body, "renter", "token_id", "duration", "collection")
        result = await self._call(
            "nft_services", "rent",
            collection=body["collection"],
            token_id=body["token_id"],
            renter=body["renter"],
            duration_days=body["duration"],
            price=body.get("price"),
        )
        return self._ok(result)

    async def _handle_nft_batch_mint(self, request: web.Request) -> web.Response:
        body = await self._parse_body(request)
        # NEW-89 DROPPED-INTENT: the route took a per-item list; the service
        # mints `count` copies of one `metadata_template`. Collapsing a list of
        # distinct items into a count would mint the WRONG TOKENS — every one
        # carrying the first item's metadata. The contract changes rather than
        # the data being mangled to fit.
        self._require(body, "creator", "collection_id", "count", "metadata_template")
        if body.get("items"):
            return web.json_response(status=501, data={
                "error": "not_implemented",
                "capability": "per-item batch mint",
                "detail": (
                    "nft_services.batch_mint mints `count` copies of a single "
                    "`metadata_template`. It cannot mint a list of distinct "
                    "items; sending `items` would silently mint duplicates."
                ),
            })
        result = await self._call(
            "nft_services", "batch_mint",
            collection=body["collection_id"],
            creator=body["creator"],
            count=int(body["count"]),
            metadata_template=body["metadata_template"],
        )
        return self._ok(result)

    async def _handle_nft_royalty_claim(self, request: web.Request) -> web.Response:
        body = await self._parse_body(request)
        # NEW-89 CONTRACT-GAP: `collection` was never collected. `creator`
        # maps to `claimer` — the party claiming, which the service checks.
        self._require(body, "creator", "token_id", "collection")
        result = await self._call(
            "nft_services", "royalty_claim",
            collection=body["collection"],
            token_id=body["token_id"],
            claimer=body["creator"],
        )
        return self._ok(result)

    async def _handle_nft_bridge(self, request: web.Request) -> web.Response:
        body = await self._parse_body(request)
        # NEW-89 CONTRACT-GAP: `collection` was never collected. An NFT is
        # identified by (collection, token_id); a token_id alone is ambiguous
        # across collections. Adding it is a public-contract change, taken
        # deliberately rather than binding `owner` into the collection slot.
        self._require(body, "owner", "token_id", "dest_chain", "collection")
        result = await self._call(
            "nft_services", "bridge_nft",
            collection=body["collection"],
            token_id=body["token_id"],
            destination_chain=body["dest_chain"],
            owner=body["owner"],
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
            # NEW-89 RENAME: the service spells these *_did.
            issuer_did=body["issuer"],
            subject_did=body["subject"],
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
        # Live-feed push: SSE subscribers (Phase 6 realtime client) receive
        # new posts without polling. Mirrors the batch.completed pattern —
        # a publish failure can never break the post itself.
        try:
            self._broadcaster.publish_dict(
                "social.post",
                {
                    "author": str(body["author"]),
                    "content": str(body["content"]),
                    "post": result if isinstance(result, dict) else {},
                },
            )
        except Exception:  # pragma: no cover — telemetry must not break posts
            logger.debug("social.post SSE publish failed", exc_info=True)
        return self._ok(result)

    async def _handle_social_message_send(self, request: web.Request) -> web.Response:
        body = await self._parse_body(request)
        # NEW-89 HONEST-501: social.send_message does not exist. The only
        # near-twin, send_encrypted_message, is a D7 FAKE-DELIVERY instance —
        # it returns "sent" with a uuid content_hash and contacts no XMTP
        # client. Repointing would turn a 404 into a convincing fake.
        self._require(body, "sender", "recipient", "content")
        return web.json_response(status=501, data={
            "error": "not_implemented",
            "capability": "direct messaging",
            "detail": (
                "No message-sending implementation exists. The route is "
                "answered honestly rather than pointed at a method that "
                "reports delivery without delivering."
            ),
        })

    async def _handle_social_gate(self, request: web.Request) -> web.Response:
        body = await self._parse_body(request)
        # NEW-89 HONEST-501: social.create_gate does not exist. The real
        # method, create_token_gate(creator, token_address, min_balance,
        # resource), is TOKEN-BALANCE-ONLY — it cannot express an arbitrary
        # gate_type/criteria pair, so a repoint would silently narrow every
        # gate to a token-balance check.
        self._require(body, "owner", "gate_type", "criteria")
        return web.json_response(status=501, data={
            "error": "not_implemented",
            "capability": "general-purpose social gates",
            "detail": (
                "Only token-balance gating exists "
                "(social.create_token_gate). Arbitrary gate_type/criteria "
                "gating is unbuilt."
            ),
        })

    async def _handle_community_create(self, request: web.Request) -> web.Response:
        body = await self._parse_body(request)
        refusal = self._community_create_refusal(body)
        if refusal is not None:
            return refusal
        result = await self._call(
            "social", "create_community",
            creator=body["creator"],
            name=body["name"],
            description=body.get("description", ""),
            token_gate=self._first(body, "token_gate", "tokenGate"),
        )
        return self._ok(result)

    def _community_create_refusal(self, body: dict) -> Optional[web.Response]:
        """The ONE body contract for social.create_community — refusal half.

        Two routes create a community — POST /api/v1/social/community/create
        and POST /api/v1/groups ("group" and "community" are one entity under
        two product names). NEW-89's refusal below was written into only one of
        the two handlers: /groups kept answering 200 with a caller's `rules`
        silently dropped, and so did /batch reaching it. Both handlers now ask
        this, so a guard cannot exist on one twin and not the other. Both read
        the token gate in either spelling; the community route used to read only
        `token_gate` and dropped a camelCase `tokenGate`.

        Each handler still writes out `self._call("social", "create_community",
        creator=..., ...)` itself, deliberately, for two readers of that call:
        scripts/generate_session_routes.py finds the service method a route
        reaches by reading the call in the handler body (moving it into a shared
        helper made community_create silently drop out of
        CAPABILITIES_OFF_ALLOWLIST), and tests/test_route_binding_detector.py
        can only check keyword names it can see (a **kwargs splat is its blind
        spot). tests/test_community_twins_share_one_contract.py drives the same
        bodies at both routes, which is what keeps the two field lists equal.
        """
        # NEW-89 DROPPED-INTENT: `rules` was REQUIRED here and the service has
        # no rules concept at all — create_community stores creator/name/
        # description/token_gate and nothing enforces anything. Mapping rules ->
        # description would return 200 with the caller's rules sitting in a
        # descriptive field that governs nothing. Refuse instead of pretending.
        self._require(body, "creator", "name")
        if body.get("rules"):
            return web.json_response(status=501, data={
                "error": "not_implemented",
                "capability": "community rules",
                "detail": (
                    "social.create_community records a community; it does not "
                    "store or enforce rules. Omit `rules` to create the "
                    "community, or the rules would be silently unenforced."
                ),
            })
        return None

    async def _handle_social_feed(self, request: web.Request) -> web.Response:
        # NOTE: SocialService.get_feed takes `address` (this route historically
        # passed `wallet=`, which the method never accepted → 400). Fixed here.
        wallet = request.match_info["wallet"]
        mode = request.query.get("mode", "latest")
        kwargs: dict = {"address": wallet, "mode": mode}
        limit_raw = request.query.get("limit")
        if limit_raw:
            try:
                limit = int(limit_raw)
            except ValueError:
                raise web.HTTPBadRequest(
                    text=json.dumps({"error": "limit must be an integer"}),
                    content_type="application/json",
                )
            if limit <= 0:
                raise web.HTTPBadRequest(
                    text=json.dumps({"error": "limit must be a positive integer"}),
                    content_type="application/json",
                )
            kwargs["limit"] = limit
        # get_feed_view wraps get_feed (same privacy + ranking) and returns the
        # {"posts": [...]} shape the iOS FeedResponse decodes.
        result = await self._call("social", "get_feed_view", **kwargs)
        return self._ok(result)

    # -- Real-Estate Escrow Engine (Component 46; feature-gated) --

    def _re_guard(self) -> None:
        """Honest 403 while services.real_estate.enabled=false (the server-side
        mvpMode analogue for this regulated feature). The service ALSO refuses
        internally, so non-HTTP paths (batch, dispatcher) stay gated too."""
        cfg = (self._config.get("services", {}) or {}).get("real_estate", {}) or {}
        if not cfg.get("enabled", False):
            raise web.HTTPForbidden(
                text=json.dumps({
                    "error": "real_estate is disabled",
                    "detail": "services.real_estate.enabled=false — this"
                              " regulated feature ships dark until explicitly"
                              " enabled server-side.",
                }),
                content_type="application/json",
            )

    async def _handle_re_property_create(self, request: web.Request) -> web.Response:
        self._re_guard()
        body = await self._parse_body(request)
        self._require(body, "seller", "address", "price_wei")
        result = await self._call(
            "real_estate", "create_property",
            seller=body["seller"], address=body["address"],
            price_wei=str(body["price_wei"]),
        )
        return self._ok(result)

    async def _handle_re_property_list(self, request: web.Request) -> web.Response:
        self._re_guard()
        result = await self._call(
            "real_estate", "list_properties",
            status=request.query.get("status"),
        )
        return self._ok(result)

    async def _handle_re_property_get(self, request: web.Request) -> web.Response:
        self._re_guard()
        result = await self._call(
            "real_estate", "get_property", property_id=request.match_info["id"])
        return self._ok(result)

    async def _handle_re_property_status(self, request: web.Request) -> web.Response:
        self._re_guard()
        body = await self._parse_body(request)
        self._require(body, "status")
        result = await self._call(
            "real_estate", "update_listing_status",
            property_id=request.match_info["id"], status=body["status"])
        return self._ok(result)

    async def _handle_re_document_upload(self, request: web.Request) -> web.Response:
        self._re_guard()
        body = await self._parse_body(request)
        self._require(body, "doc_type")
        result = await self._call(
            "real_estate", "upload_document",
            property_id=request.match_info["id"],
            doc_type=body["doc_type"],
            content_b64=body.get("content_b64"),
            content_hash=body.get("content_hash"),
            filename=body.get("filename", ""),
        )
        return self._ok(result)

    async def _handle_re_documents_get(self, request: web.Request) -> web.Response:
        self._re_guard()
        result = await self._call(
            "real_estate", "get_documents",
            property_id=request.match_info["id"],
            include_history=request.query.get("history", "") in ("1", "true"),
        )
        return self._ok(result)

    async def _handle_re_readiness(self, request: web.Request) -> web.Response:
        self._re_guard()
        result = await self._call(
            "real_estate", "get_readiness",
            property_id=request.match_info["id"],
            buyer=request.query.get("buyer", ""),
        )
        return self._ok(result)

    async def _handle_re_docs_expiring(self, request: web.Request) -> web.Response:
        self._re_guard()
        try:
            days = int(request.query.get("days", "14"))
        except ValueError:
            raise web.HTTPBadRequest(
                text=json.dumps({"error": "days must be an integer"}),
                content_type="application/json")
        result = await self._call(
            "real_estate", "query_expiring_documents", days=days)
        return self._ok(result)

    async def _handle_re_buyer_verify(self, request: web.Request) -> web.Response:
        self._re_guard()
        body = await self._parse_body(request)
        self._require(body, "buyer")
        method = body.get("method", "wallet_balance")
        if method == "external":
            # Honest 501 — the bank-integration path does not exist yet and is
            # never faked (the service ALSO raises NotImplementedError).
            return web.json_response(
                {"error": "external proof-of-funds verification is not"
                          " implemented yet", "status": "not_implemented"},
                status=501)
        result = await self._call(
            "real_estate", "verify_buyer",
            buyer=body["buyer"], method=method,
            threshold_wei=body.get("threshold_wei"),
        )
        return self._ok(result)

    async def _handle_re_buyer_verification_get(self, request: web.Request) -> web.Response:
        self._re_guard()
        result = await self._call(
            "real_estate", "get_buyer_verification",
            buyer=request.match_info["wallet"])
        return self._ok(result)

    async def _handle_re_purchase(self, request: web.Request) -> web.Response:
        self._re_guard()
        body = await self._parse_body(request)
        self._require(body, "buyer", "property_id")
        result = await self._call(
            "real_estate", "execute_purchase",
            buyer=body["buyer"], property_id=body["property_id"])
        return self._ok(result)

    async def _handle_re_escrow_confirm(self, request: web.Request) -> web.Response:
        self._re_guard()
        body = await self._parse_body(request)
        self._require(body, "tx_hash")
        result = await self._call(
            "real_estate", "confirm_settlement",
            escrow_id=request.match_info["id"], tx_hash=body["tx_hash"])
        return self._ok(result)

    async def _handle_re_recording_complete(self, request: web.Request) -> web.Response:
        self._re_guard()
        body = await self._parse_body(request)
        result = await self._call(
            "real_estate", "mark_recording_complete",
            escrow_id=request.match_info["id"],
            recording_reference=body.get("recording_reference", ""))
        return self._ok(result)

    async def _handle_re_escrow_refund(self, request: web.Request) -> web.Response:
        self._re_guard()
        body = await self._parse_body(request)
        result = await self._call(
            "real_estate", "refund_escrow",
            escrow_id=request.match_info["id"],
            reason=body.get("reason", ""))
        return self._ok(result)

    async def _handle_re_escrow_get(self, request: web.Request) -> web.Response:
        self._re_guard()
        result = await self._call(
            "real_estate", "get_escrow", escrow_id=request.match_info["id"])
        return self._ok(result)

    # -- Payments Expanded --






    # -- Compute & Storage --

    async def _handle_decentralized_store(self, request: web.Request) -> web.Response:
        """POST /api/v1/compute/store — now reaches the real Filecoin client.

        NEW-48: `content` is forwarded. The service method delegates to
        `storage.store_filecoin`, which uploads BYTES; forwarding only
        `data_hash` (as this handler used to) would make the delegation
        permanently unsatisfiable from HTTP — a route wired to a real client it
        can never feed is half a fix.
        """
        body = await self._parse_body(request)
        self._require(body, "owner", "data", "storage_type")
        result = await self._call(
            "privacy", "decentralized_store",
            uploader=body["owner"],
            data_hash=body["data"],
            storage_provider=body["storage_type"],
            content=body.get("content"),
            filename=body.get("filename", "upload.bin"),
        )
        return self._ok(result)

    async def _handle_ipfs_pin(self, request: web.Request) -> web.Response:
        """POST /api/v1/compute/ipfs/pin — now reaches the real pinning client."""
        body = await self._parse_body(request)
        self._require(body, "cid")
        result = await self._call(
            "privacy", "pin_to_ipfs",
            uploader=body.get("owner", ""),
            data_hash=body["cid"],
            pin_name=body.get("name", ""),
            content=body.get("content"),
        )
        return self._ok(result)

    async def _handle_arweave_store(self, request: web.Request) -> web.Response:
        """POST /api/v1/compute/arweave/store — 501, uploads nothing (NEW-48).

        The backing method minted `arweave_tx = f"ar_{uuid4().hex}"` for data
        it never uploaded. No real Arweave blob-storage client exists anywhere
        in the platform — `creator_platforms.publish_mirror_post` writes to
        Arweave but publishes a titled Mirror ENTRY, which is a different act
        with different visibility, so it is not a valid delegation target.

        The route is kept and answers honestly rather than 404-ing, so a
        caller learns the capability is absent instead of guessing the URL.
        """
        return web.json_response(
            {
                "status": "error",
                "data": {
                    "status": "error",
                    "error_category": "not_implemented",
                    "error": "arweave_storage_not_implemented",
                    "message": (
                        "Arweave storage is not available. The platform has no "
                        "Arweave upload client; the previous implementation "
                        "returned a random string as a transaction id for data "
                        "it never uploaded. Nothing was stored by this call."
                    ),
                },
            },
            status=501,
        )

    # ------------------------------------------------------------------
    # P2 — Route completion
    #
    # Register every leg the client skeleton expects so it reaches a real
    # gateway endpoint instead of a 404. Routes with a genuine backing service
    # method run through the universal _call() seam (gate_action first); the
    # rest return an HONEST 501 not-implemented — never a fabricated 200.
    # ------------------------------------------------------------------

    def _not_impl(self, feature: str) -> Callable[..., Awaitable[web.Response]]:
        """Build a handler that honestly reports a not-yet-implemented route."""
        async def handler(request: web.Request) -> web.Response:
            return web.json_response(
                {"error": f"{feature} is not implemented yet",
                 "status": "not_implemented"},
                status=501,
            )
        return handler

    # -- WIRE handlers (real service, through _call) --

    async def _handle_messaging_conversations(self, request: web.Request) -> web.Response:
        address = request.query.get("address", "")
        result = await self._call("social", "get_conversations", address=address)
        return self._ok(result)

    async def _handle_messaging_messages(self, request: web.Request) -> web.Response:
        conversation_id = request.match_info["conversationId"]
        try:
            limit = int(request.query.get("limit", 50))
        except (TypeError, ValueError):
            limit = 50
        result = await self._call(
            "social", "get_messages", conversation_id=conversation_id, limit=limit
        )
        return self._ok(result)

    async def _handle_groups_create(self, request: web.Request) -> web.Response:
        # Same entity, same service call, same contract — see
        # _community_create_refusal for why the call stays written out here.
        body = await self._parse_body(request)
        refusal = self._community_create_refusal(body)
        if refusal is not None:
            return refusal
        result = await self._call(
            "social", "create_community",
            creator=body["creator"],
            name=body["name"],
            description=body.get("description", ""),
            token_gate=self._first(body, "token_gate", "tokenGate"),
        )
        return self._ok(result)

    @staticmethod
    def _first(body: dict, *keys: str):
        """First present, non-empty value among *keys*.

        The iOS client encodes every body to snake_case, so a client-supplied
        camelCase key (``ipId``) arrives as ``ip_id``. Accept both forms.
        """
        for k in keys:
            v = body.get(k)
            if v not in (None, ""):
                return v
        return None

    async def _handle_licensing_register_ip(self, request: web.Request) -> web.Response:
        body = await self._parse_body(request)
        owner = self._first(body, "owner")
        ip_type = self._first(body, "type", "ip_type")
        name = self._first(body, "name")
        if not owner or not ip_type or not name:
            raise web.HTTPBadRequest(
                text=json.dumps({"error": "owner, type and name are required"}),
                content_type="application/json",
            )
        result = await self._call(
            "ip_royalties", "register_ip",
            owner=owner,
            ip_type=ip_type,
            metadata={
                "title": name,
                "description": self._first(body, "description") or "",
                "content_hash": self._first(body, "evidenceHash", "evidence_hash") or "",
            },
        )
        return self._ok(result)

    async def _handle_licensing_create_license(self, request: web.Request) -> web.Response:
        body = await self._parse_body(request)
        ip_id = self._first(body, "ipId", "ip_id")
        recipient = self._first(body, "recipient")
        terms = self._first(body, "terms")
        if not ip_id or not recipient or terms is None:
            raise web.HTTPBadRequest(
                text=json.dumps({"error": "ipId, recipient and terms are required"}),
                content_type="application/json",
            )
        result = await self._call(
            "ip_royalties", "license_ip",
            ip_id=ip_id,
            licensee=recipient,
            terms=terms,
        )
        return self._ok(result)

    async def _handle_dao_proposals(self, request: web.Request) -> web.Response:
        # DAO proposals live-read (was blocked: no route emitted the client's
        # Proposal shape). list_proposals_detailed returns exactly the client's
        # DAO tab shape (proposal_id/title/description/status/votes_for/
        # votes_against/quorum/end_time) through the _call seam.
        dao_id = request.match_info.get("daoId", "")
        result = await self._call("governance", "list_proposals_detailed", dao_id=dao_id)
        return self._ok(result)

    def _p2_route_specs(self) -> List[Tuple[str, str, Callable[..., Awaitable[web.Response]]]]:
        """The P2 route-completion table (built once, shared by both routers).

        WIRE routes point at a real ``_handle_*`` above; every other route is an
        honest 501. Routes that already exist elsewhere (oracle/price,
        portfolio/complete·positions·history, compute/store·ipfs·arweave,
        events/stream) are deliberately NOT included here.
        """
        if self._p2_specs_cache is not None:
            return self._p2_specs_cache
        NI = self._not_impl
        specs: List[Tuple[str, str, Callable[..., Awaitable[web.Response]]]] = [
            # ── storage ──
            ("GET",  "/api/v1/storage/files", NI("storage.list_files")),
            ("POST", "/api/v1/storage/files", NI("storage.upload_file")),
            ("GET",  "/api/v1/storage/files/{cid}", NI("storage.get_file")),
            ("POST", "/api/v1/storage/files/{cid}/pin", NI("storage.pin_file")),
            ("POST", "/api/v1/storage/files/{cid}/unpin", NI("storage.unpin_file")),
            # ── messaging (reads WIRE to social; writes honest 501) ──
            ("GET",  "/api/v1/messaging/conversations", self._handle_messaging_conversations),
            ("GET",  "/api/v1/messaging/conversations/{conversationId}/messages", self._handle_messaging_messages),
            ("POST", "/api/v1/messaging/conversations/{conversationId}/messages", NI("messaging.send_message")),
            ("POST", "/api/v1/messaging/conversations", NI("messaging.start_conversation")),
            # ── groups (create WIRE to social.create_community; rest 501) ──
            ("GET",  "/api/v1/groups", NI("groups.list_user_groups")),
            ("GET",  "/api/v1/groups/discover", NI("groups.discover")),
            ("GET",  "/api/v1/groups/{groupId}/feed", NI("groups.feed")),
            ("POST", "/api/v1/groups/{groupId}/join", NI("groups.join")),
            ("POST", "/api/v1/groups/{groupId}/leave", NI("groups.leave")),
            ("POST", "/api/v1/groups", self._handle_groups_create),
            ("POST", "/api/v1/groups/{groupId}/posts", NI("groups.post")),
            # ── licensing (register/license WIRE to ip_royalties; rest 501) ──
            ("GET",  "/api/v1/licensing/ip", NI("licensing.list_ip")),
            ("POST", "/api/v1/licensing/ip", self._handle_licensing_register_ip),
            ("GET",  "/api/v1/licensing/licenses", NI("licensing.list_licenses")),
            ("POST", "/api/v1/licensing/licenses", self._handle_licensing_create_license),
            ("POST", "/api/v1/licensing/licenses/purchase", NI("licensing.purchase_license")),
            ("GET",  "/api/v1/licensing/marketplace", NI("licensing.marketplace")),
            # ── DAO proposals live-read (WIRE → governance.list_proposals_detailed) ──
            ("GET",  "/api/v1/governance/daos/{daoId}/proposals", self._handle_dao_proposals),
            # ── events (no backing service yet → honest 501) ──
            ("GET",  "/api/v1/events", NI("events.list")),
            ("GET",  "/api/v1/events/tickets", NI("events.user_tickets")),
            ("POST", "/api/v1/events", NI("events.create")),
            ("POST", "/api/v1/events/{eventId}/purchase", NI("events.purchase_ticket")),
            ("GET",  "/api/v1/events/tickets/{ticketId}/verify", NI("events.verify_ticket")),
            # ── indexer (no backing service yet → honest 501) ──
            ("GET",  "/api/v1/indexer/subgraphs", NI("indexer.list_subgraphs")),
            ("POST", "/api/v1/indexer/subgraphs/{subgraphId}/query", NI("indexer.query")),
            ("POST", "/api/v1/indexer/subgraphs/{subgraphId}/translate", NI("indexer.translate")),
            ("GET",  "/api/v1/indexer/queries", NI("indexer.saved_queries")),
            ("POST", "/api/v1/indexer/queries", NI("indexer.save_query")),
            # ── oracle feeds (catalog/subscription; /oracle/price already exists) ──
            ("GET",  "/api/v1/oracle/feeds", NI("oracle.list_feeds")),
            ("POST", "/api/v1/oracle/feeds/{feedId}/subscribe", NI("oracle.subscribe_feed")),
            ("POST", "/api/v1/oracle/feeds/{feedId}/unsubscribe", NI("oracle.unsubscribe_feed")),
            ("GET",  "/api/v1/oracle/feeds/{feedId}/history", NI("oracle.feed_history")),
            # ── compute jobs (/compute/store·ipfs·arweave already exist) ──
            ("GET",  "/api/v1/compute/providers", NI("compute.providers")),
            ("POST", "/api/v1/compute/jobs", NI("compute.submit_job")),
            ("GET",  "/api/v1/compute/jobs", NI("compute.list_jobs")),
            ("GET",  "/api/v1/compute/jobs/{jobId}", NI("compute.job_status")),
            ("GET",  "/api/v1/compute/jobs/{jobId}/result", NI("compute.job_result")),
            # ── portfolio performance (complete/positions/history already exist) ──
            ("GET",  "/api/v1/portfolio/performance/{wallet}", NI("portfolio.performance")),
        ]
        self._p2_specs_cache = specs
        return specs

    # -- RWA Expanded --


    async def _handle_rwa_listings(self, request: web.Request) -> web.Response:
        result = await self._call(
            "rwa_tokenization", "list_assets",
        )
        return self._ok(result)

    # -- Prediction Markets --




    # -- Energy --




    # -- Governance Expanded --


    async def _handle_multisig_approve(self, request: web.Request) -> web.Response:
        body = await self._parse_body(request)
        # NEW-89 HONEST-501: multisig_approve does not exist. The nearest real
        # method, approve_multisig(multisig_id, signer), approves a MULTISIG —
        # it has no proposal parameter, so this route's `proposal_id` would be
        # discarded and the approval recorded against the wrong subject.
        self._require(body, "approver", "multisig_address", "proposal_id")
        return web.json_response(status=501, data={
            "error": "not_implemented",
            "capability": "multisig proposal approval",
            "detail": (
                "governance.approve_multisig approves a multisig, not a "
                "proposal within one. Approving per-proposal is unbuilt."
            ),
        })

    async def _handle_snapshot_vote(self, request: web.Request) -> web.Response:
        body = await self._parse_body(request)
        # NEW-89 DROPPED-INTENT: `space` (the Snapshot namespace) has no
        # parameter on the service. Its only free parameter, `block_number`, is
        # a voting-power snapshot block — not a namespace — so space ->
        # block_number is rejected. Dropping `space` silently would record the
        # vote against a proposal id in NO named space.
        self._require(body, "voter", "proposal_id", "choice")
        if body.get("space"):
            return web.json_response(status=501, data={
                "error": "not_implemented",
                "capability": "Snapshot spaces",
                "detail": (
                    "governance.snapshot_vote records a vote against a "
                    "proposal id and has no notion of a Snapshot space. "
                    "Omit `space`; it would otherwise be discarded."
                ),
            })
        result = await self._call(
            "governance", "snapshot_vote",
            proposal_id=body["proposal_id"],
            voter=body["voter"],
            choice=body["choice"],
        )
        return self._ok(result)


    # -- Portfolio --

    async def _handle_portfolio_complete(self, request: web.Request) -> web.Response:
        """The last copy of the RUN-6 shape on the portfolio pair.

        This returned `{"wallet", "status": "unavailable", "message": str(e)}`
        — the exact body RUN-6 removed from /portfolio/positions two handlers
        below. RUN-4's `_ok` already turned that inner `unavailable` into a 503,
        so the status was honest; the body was not: the exception text (an RPC
        URL, a provider error) went to the caller. Same answer as positions now:
        the reason is logged server-side, the client gets a fixed sentence.

        That `except` was not where the real failures went, though.
        DataAggregator.get_user_portfolio caught everything itself — and
        Web3Manager.get_balance_eth turned a failed RPC read into 0.0 below it —
        so an RPC outage, a timeout, or no RPC configured at all came back as a
        200 all-zero portfolio identical to an empty wallet, and was cached.
        Both now raise (PortfolioUnavailable / BalanceUnavailable), nothing
        failed is cached, and a balance is valued only at a live ETH/USD quote,
        so every one of those reaches this 503. A 200 now means the native
        balance was actually read; `covered` / `not_covered` say that it is the
        only thing read.
        """
        wallet = request.match_info["wallet"]
        try:
            from runtime.blockchain.protocol_abstraction.data_aggregator import DataAggregator
            aggregator = DataAggregator(self._config)
            result = await aggregator.get_user_portfolio(wallet)
        except Exception as e:
            logger.warning("Portfolio aggregation failed for %s: %s", wallet, e)
            raise web.HTTPServiceUnavailable(
                text=json.dumps({
                    "status": "unavailable",
                    "error": "The portfolio is unavailable right now.",
                }),
                content_type="application/json",
            )
        return self._ok(result)

    async def _handle_portfolio_positions(self, request: web.Request) -> web.Response:
        """RUN-6: was calling DataAggregator.get_positions(), which does not exist.

        The class it reached has no such method — the call raised AttributeError
        every time and the handler returned HTTP 200 with the Python error text
        as the payload. Positions ARE genuinely derivable: get_user_portfolio()
        computes them from a real chain balance, so this is a repoint to the
        real method plus a projection of the position-bearing fields, not a
        fabricated answer.
        """
        wallet = request.match_info["wallet"]
        try:
            from runtime.blockchain.protocol_abstraction.data_aggregator import (
                DataAggregator,
            )
            aggregator = DataAggregator(self._config)
            portfolio = await aggregator.get_user_portfolio(wallet)
        except Exception as e:
            # RUN-5 shape: the reason is logged server-side, never returned.
            logger.warning("Portfolio positions failed for %s: %s", wallet, e)
            raise web.HTTPServiceUnavailable(
                text=json.dumps({
                    "status": "unavailable",
                    "error": "Portfolio positions are unavailable right now.",
                }),
                content_type="application/json",
            )

        return self._ok({
            "wallet": wallet,
            "total_value_usd": portfolio.get("total_value_usd", 0.0),
            "positions": {
                "tokens": portfolio.get("tokens", []),
                "nfts": portfolio.get("nfts", []),
                "defi": portfolio.get("defi_positions", []),
                "staking": portfolio.get("staking_positions", []),
                "streams": portfolio.get("streams", []),
                "rwa": portfolio.get("rwa_positions", []),
            },
            "covered": portfolio.get("covered", []),
            "not_covered": portfolio.get("not_covered", []),
            "cached": portfolio.get("cached", False),
        })

    async def _handle_portfolio_history(self, request: web.Request) -> web.Response:
        """RUN-6: historical portfolio data does not exist to serve.

        This called DataAggregator.get_history(), which was never implemented on
        either class of that name. Unlike positions, history cannot be derived
        from what the platform has: every aggregator method returns a CURRENT
        snapshot, and nothing records time-series. Serving it needs an indexer —
        a feature, not a bug fix — so the honest answer is 501, the same shape
        as /contracts/deploy (RUN-2).
        """
        return web.json_response(
            {
                "status": "not_implemented",
                "error": "Portfolio history is not implemented.",
                "detail": (
                    "This endpoint previously returned HTTP 200 with an internal "
                    "error as its payload. No time-series portfolio data is "
                    "recorded anywhere in the platform; serving history requires "
                    "an indexer that does not exist yet. Use "
                    "/api/v1/portfolio/positions/{wallet} for the current snapshot."
                ),
                "see": "/api/v1/portfolio/positions/{wallet}",
            },
            status=501,
        )

    # -- Intent Resolution --

    # Entity fields IntentResolver.resolve reads as text. Anything else in
    # `entities` is passed through untouched.
    _INTENT_TEXT_ENTITIES = ("asset", "from_chain", "to_chain", "token_out",
                             "collateral", "data_ref")

    @staticmethod
    def _bad_request(message: str) -> web.Response:
        return web.json_response(
            {"error": message, "code": "invalid_request"}, status=400)

    async def _handle_intent_resolve(self, request: web.Request) -> web.Response:
        """POST /api/v1/intent/resolve — an exception is not a plan.

        Both this handler and IntentResolver.resolve itself caught every
        exception and returned `{"status": "error", "message": str(exc)}`.
        RUN-4's `_ok` made that a 422 rather than a 200, but the body still
        carried the exception text, and 422 said "your request was
        unprocessable" for what was usually our own fault. It also said the same
        422 — with Python's own wording — for input that genuinely WAS the
        caller's fault (`entities.amount: "abc"`, `entities: [...]`).

        Now:
          * the caller's malformed input is a 400 checked here, before the
            resolver runs, and so is a bridge between unsupported or identical
            chains, which the resolver reports as `error_category: validation`;
          * a router the plan needs that is not configured, or that failed
            (the routers catch their own exceptions and answer
            `status: error`), is a 503 `{"status": "unavailable", "reason",
            "error"}` with a fixed sentence. resolve() used to fill the
            router's missing numbers with defaults ($3.00, "uniswap", "aave",
            "hop") and this route answered 200 ok with that plan;
          * an exception that escapes the resolver goes through client_error —
            logged in full against a ref, redacted to the client, 503/504 when
            its type or text says a dependency was unreachable or timed out,
            500 otherwise.
        `unresolved` stays a 200: it is an answer to the question asked.
        A 200 plan's figures are the routers' own `ok` answers, which are
        static per-protocol tables in defi_router.py / cross_chain_router.py,
        not live quotes; `value_usd` is None and `requires_confirmation` True
        whenever no live price exists for the asset.
        """
        body = await self._parse_body(request)
        self._require(body, "intent")
        intent = body.get("intent")
        if not isinstance(intent, str) or not intent.strip():
            return self._bad_request("intent must be a non-empty string")
        entities = body.get("entities")
        if entities is None:
            entities = {}
        if not isinstance(entities, dict):
            return self._bad_request("entities must be an object")
        if "amount" in entities:
            try:
                amount = float(entities["amount"])
            except (TypeError, ValueError):
                return self._bad_request("entities.amount must be a number")
            if not math.isfinite(amount) or amount < 0:
                return self._bad_request(
                    "entities.amount must be a finite, non-negative number")
        for key in self._INTENT_TEXT_ENTITIES:
            if key in entities and not isinstance(entities[key], str):
                return self._bad_request(f"entities.{key} must be a string")
        try:
            from runtime.blockchain.protocol_abstraction.intent_resolver import IntentResolver
            resolver = IntentResolver(self._config)
            result = await resolver.resolve(
                intent=intent,
                entities=entities,
                wallet=str(body.get("wallet", "") or ""),
                tier=str(body.get("tier", "free") or "free"),
            )
        except Exception as exc:
            _st, _err = client_error(exc, None, what="Intent resolution")
            return web.json_response(_err, status=_st)
        status = result.get("status") if isinstance(result, dict) else None
        if status == "unavailable":
            # A top-level string `error`: the Swift client's extractErrorMessage
            # reads nothing else. The resolver's message is a fixed sentence.
            return web.json_response({
                "status": "unavailable",
                "reason": result.get("reason", "dependency_failed"),
                "action": result.get("action"),
                "error": result.get("message", "Intent resolution is unavailable right now."),
            }, status=503)
        if status == "error" and result.get("error_category") == "validation":
            return self._bad_request(str(result.get("message", "invalid intent")))
        return self._ok(result)

    async def _handle_intent_execute(self, request: web.Request) -> web.Response:
        """POST /api/v1/intent/execute — executing a plan by id is not built.

        This called IntentResolver.execute(plan_id=..., wallet=...), which does
        not exist, so every well-formed request raised AttributeError and the
        handler returned it as the body (422 after RUN-4, 200 before). It
        survived the route sweep because the sweep's generic body carries no
        `plan_id`, so the sweep only ever saw the 400 for a missing field.

        Same reason as /intent/summary, and the same answer: plans are not
        persisted — resolve() mints a uuid4 plan_id and keeps nothing — so
        there is no plan to look up by id. The real method,
        execute_plan(plan: dict, wallet), takes the plan OBJECT. Repointing to it
        would mean executing a plan the caller wrote into its own request body,
        on a fund-moving path, which is not a repair. 501 until a plan store and
        a gated execution path exist.
        """
        return web.json_response(
            {
                "status": "not_implemented",
                "error": "Executing an intent plan by id is not implemented.",
                "detail": (
                    "Plans are not persisted: /api/v1/intent/resolve returns the "
                    "full plan and the resolver keeps no store, so a plan_id "
                    "cannot be looked up, and nothing executes a resolved plan "
                    "from this endpoint."
                ),
                "see": "/api/v1/intent/resolve",
            },
            status=501,
        )

    async def _handle_intent_summary(self, request: web.Request) -> web.Response:
        """RUN-6: summary-by-plan-id cannot be served, and never could.

        This called IntentResolver.get_summary(plan_id=...), which does not
        exist, so every request returned HTTP 200 carrying the AttributeError.

        Repointing it is not possible: the real method is
        get_plan_summary(plan: dict) — it takes the plan OBJECT — and
        IntentResolver is stateless. resolve() mints a plan_id with uuid4() and
        never persists the plan, so there is nothing anywhere to look a plan_id
        up in. Serving this needs a plan store, which is a feature, not a repair.

        501 rather than a repoint, because the alternative would be inventing
        persistence behind a bug fix. Callers that hold the plan from
        /intent/resolve already have everything the summary would describe.
        """
        return web.json_response(
            {
                "status": "not_implemented",
                "error": "Intent summary by plan id is not implemented.",
                "detail": (
                    "Plans are not persisted: /api/v1/intent/resolve returns the "
                    "full plan and the resolver keeps no store, so a plan_id "
                    "cannot be looked up. Keep the plan object from the resolve "
                    "response rather than re-fetching it by id."
                ),
                "see": "/api/v1/intent/resolve",
            },
            status=501,
        )

    # -- Legal --




    # -- AI --



    # -- Supply Chain Expanded --

    async def _handle_provenance_log(self, request: web.Request) -> web.Response:
        body = await self._parse_body(request)
        self._require(body, "product_id", "event_type", "data")
        result = await self._call(
            # NEW-89 REPOINT: log_provenance never existed; log_event is the
            # real method and its signature matches exactly.
            "supply_chain", "log_event",
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
            # NEW-89 RENAME: same concepts, the service spells them *_handler.
            from_handler=body["from_holder"],
            to_handler=body["to_holder"],
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

    # NEW-81: _handle_claim_settle removed with its route — an
    # unregistered handler is still a callable path.

    # -- Privacy Expanded --

    # ------------------------------------------------------------------
    # Capability Registry (data-driven Web3 capability surface)
    # ------------------------------------------------------------------

    def _capability_registry(self):
        """Lazy-load the CapabilityRegistry with the gateway's config."""
        reg = getattr(self, "_cap_registry_cache", None)
        if reg is None:
            from runtime.capabilities import CapabilityRegistry
            reg = CapabilityRegistry(self._config)
            self._cap_registry_cache = reg
        return reg

    async def _handle_capabilities_list(self, request: web.Request) -> web.Response:
        """``GET /api/v1/capabilities`` — enumerate all capabilities."""
        reg = self._capability_registry()
        category = request.query.get("category")
        min_tier = request.query.get("min_tier")
        available_only = request.query.get("available", "").lower() in {"1", "true", "yes"}
        caps = reg.list_capabilities(
            category=category,
            available_only=available_only,
            min_tier=min_tier,
        )
        return self._ok({"capabilities": caps, "count": len(caps)})

    async def _handle_capabilities_categories(self, request: web.Request) -> web.Response:
        """``GET /api/v1/capabilities/categories`` — list categories + counts."""
        reg = self._capability_registry()
        return self._ok({"categories": reg.list_categories()})

    async def _handle_capability_detail(self, request: web.Request) -> web.Response:
        """``GET /api/v1/capabilities/{id}`` — descriptor for one capability."""
        capability_id = request.match_info["capability_id"]
        reg = self._capability_registry()
        cap = reg.describe(capability_id)
        if cap is None:
            return web.json_response(
                {"ok": False, "error": "unknown_capability", "capability_id": capability_id},
                status=404,
            )
        return self._ok({"capability": cap})

    async def _handle_capability_invoke(self, request: web.Request) -> web.Response:
        """``POST /api/v1/capabilities/{id}/invoke`` — execute a capability."""
        capability_id = request.match_info["capability_id"]
        try:
            body = await request.json()
        except Exception:
            body = {}
        params = body.get("params", {}) if isinstance(body, dict) else {}
        reg = self._capability_registry()
        # 17-D. This route reaches the SAME ServiceDispatcher as gateway/bridge.py
        # — `set_nft_rights` is a catalog capability id — and it dropped the
        # caller for exactly the same reason: nobody asked for it. The identity
        # is already bound for every POST /api/v1/* by
        # `GatewayServer._security_context_middleware`, so it is read here from
        # the request-scoped context rather than from the body, following the
        # idiom `_handle_governance_vote` and `_handle_insurance_claim` already
        # use: an authenticated identity always wins, and a body-supplied
        # address is never promoted to fact. Absent identity degrades to ""
        # ("unknown"), never to a self-asserted address, and never to a refusal.
        from gateway.security_gate import (
            current_request_security, gate_action, generic_denial, is_blocked,
        )
        security = current_request_security() or {}
        authed = str(security.get("wallet") or "")
        # EA-1: this route reached the dispatcher WITHOUT the gate the
        # /api/v1 funnel (`_call`) consults — `settle_auction` and every other
        # catalog write was reachable ungated here. The capability's ACTION_MAP
        # verb is the label the gate classifies; a block is the generic denial.
        # The invoke route is on the session allowlist because the app calls it,
        # but it is a DISPATCHER into the same ServiceDispatcher the dedicated
        # /api/v1 routes use. Allowlisting the URL is not allowlisting the
        # operation: seven catalog ids reach a service method whose own route
        # answers 403 to a session. A session is refused those explicitly; the
        # operator key is unaffected.
        from gateway.session_routes import CAPABILITIES_OFF_ALLOWLIST, session_may_invoke
        # aiohttp's Request is a mapping; the suite's fake request objects are not.
        auth = (request.get("auth") if hasattr(request, "get") else None) or {}
        if auth.get("kind") == "session" and not session_may_invoke(capability_id):
            return web.json_response(
                {"error": "forbidden",
                 "message": "This capability is not available to a user session; "
                            f"its route ({CAPABILITIES_OFF_ALLOWLIST[capability_id]}) requires the operator key."},
                status=403)

        from runtime.capabilities import catalog as _catalog
        descriptor = _catalog.get_by_id(capability_id)
        action_label = str((descriptor or {}).get("action") or capability_id)
        decision = await gate_action(action_label, params if isinstance(params, dict) else {}, security)
        if is_blocked(decision):
            return web.json_response({"error": generic_denial(decision)}, status=403)
        result = await reg.invoke(capability_id, params, caller_identity=authed)
        status = 200 if result.get("status") == "ok" else 400
        return web.json_response(result, status=status)

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
            # Same contract as `_call`: the exception is logged, never returned.
            _st, _err = client_error(exc, None, what=f"Batch item {item_id}")
            return {
                "id": item_id,
                "status": _st,
                "body": None,
                "error": _err["error"],
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
