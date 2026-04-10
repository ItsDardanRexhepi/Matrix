"""
Service API Routes — exposes all 30 blockchain services as REST endpoints.
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

from gateway.event_broadcaster import BroadcastEvent, EventBroadcaster

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
    ) -> None:
        self._config = config
        self._registry = None  # lazy
        self._broadcaster = broadcaster or EventBroadcaster()
        #: (method, compiled_regex, param_names, handler, literal_path)
        self._batch_routes: List[
            Tuple[str, re.Pattern, List[str], Callable[..., Awaitable[web.Response]], str]
        ] = []

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

        # Batch dispatch and live event stream (used by MTRXPackager)
        app.router.add_post("/api/v1/batch", self._handle_batch)
        app.router.add_get("/api/v1/events/stream", self._handle_event_stream)

        self._build_batch_route_map()
        logger.info("ServiceRoutes: registered %d endpoints", 43)

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
        ]

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
        body = await self._parse_body(request)
        self._require(body, "requests")

        items = body["requests"]
        if not isinstance(items, list):
            raise web.HTTPBadRequest(
                text=json.dumps({"error": "'requests' must be a list"}),
                content_type="application/json",
            )
        if len(items) == 0:
            return web.json_response({
                "results": [],
                "total_duration_ms": 0,
            })
        if len(items) > BATCH_MAX_ITEMS:
            raise web.HTTPBadRequest(
                text=json.dumps({
                    "error": f"Batch exceeds maximum of {BATCH_MAX_ITEMS} items",
                }),
                content_type="application/json",
            )

        sequential = bool(body.get("sequential", False))
        abort_on_failure = bool(body.get("abort_on_failure", False))

        if sequential:
            results = await self._run_batch_sequential(items, abort_on_failure)
        else:
            results = await self._run_batch_parallel(items, abort_on_failure)

        total_ms = int((time.monotonic() - start_wall) * 1000)

        # Broadcast a batch-completed event so any SSE subscribers can
        # refresh their UI without polling.
        try:
            self._broadcaster.publish_dict(
                "batch.completed",
                {
                    "item_count": len(items),
                    "success_count": sum(
                        1 for r in results if 200 <= r["status"] < 300
                    ),
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

        sub = await self._broadcaster.register(
            components=components,
            session_id=session_id,
            types=types,
        )

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
