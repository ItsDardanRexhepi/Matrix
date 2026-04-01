"""
Service API Routes — exposes all 30 blockchain services as REST endpoints.
Each service gets its own endpoint group under /api/v1/
"""

from __future__ import annotations

import json
import logging
from typing import Any

from aiohttp import web

logger = logging.getLogger(__name__)


class ServiceRoutes:
    """Register REST endpoints for every blockchain service.

    Each endpoint parses the JSON request body, calls the corresponding
    service method via :class:`ServiceRegistry`, and returns a JSON
    response with appropriate HTTP status codes.
    """

    def __init__(self, config: dict) -> None:
        self._config = config
        self._registry = None  # lazy

    def _get_registry(self):
        if self._registry is None:
            from runtime.blockchain.services.registry import ServiceRegistry
            self._registry = ServiceRegistry(self._config)
        return self._registry

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

        logger.info("ServiceRoutes: registered %d endpoints", 41)

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
