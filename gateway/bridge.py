from __future__ import annotations

"""
Matrix-to-0pnMatrx Bridge — connects the MTRX iOS app to the 0pnMatrx backend.

Exposes mobile-optimized endpoints under /bridge/v1/ that the MTRX iOS app
calls. Handles:
- Session management (create/resume/end)
- Agent chat with Trinity/Neo/Morpheus
- Direct platform actions (bypass chat, call services directly)
- Wallet linking and status
- Push notification registration
- App config sync (feature flags, service catalog)

The bridge translates between the iOS app's data model (Swift structs) and
the backend's internal formats. All responses are JSON with consistent
envelope: {"ok": true, "data": {...}} or {"ok": false, "error": "..."}.
"""

import json
import logging
import time
import uuid
from typing import Any

from aiohttp import web

logger = logging.getLogger(__name__)


class MobileResponse:
    """Consistent response envelope for mobile clients."""

    @staticmethod
    def ok(data: Any = None) -> web.Response:
        body = {"ok": True, "data": data or {}, "timestamp": time.time()}
        return web.json_response(body)

    @staticmethod
    def error(message: str, code: int = 400) -> web.Response:
        body = {"ok": False, "error": message, "timestamp": time.time()}
        return web.json_response(body, status=code)


# ─── Service Catalog for iOS ────────────────────────────────────────────────

SERVICE_CATALOG = [
    {
        "id": "contract_conversion",
        "name": "Smart Contracts",
        "icon": "doc.text.magnifyingglass",
        "description": "Convert any agreement into a self-executing smart contract.",
        "category": "core",
        "actions": ["convert_contract", "deploy_contract", "estimate_contract_cost", "list_templates"],
    },
    {
        "id": "defi",
        "name": "DeFi Loans",
        "icon": "banknote",
        "description": "Borrow and lend with no banks, no credit checks.",
        "category": "finance",
        "actions": ["create_loan", "repay_loan", "get_loan"],
    },
    {
        "id": "nft_services",
        "name": "NFTs & Royalties",
        "icon": "photo.artframe",
        "description": "Mint, trade, and enforce automatic royalties forever.",
        "category": "creative",
        "actions": ["mint_nft", "create_nft_collection", "list_nft_for_sale", "buy_nft", "transfer_nft"],
    },
    {
        "id": "rwa_tokenization",
        "name": "Real World Assets",
        "icon": "building.2",
        "description": "Co-own property, vehicles, and commodities through tokenization.",
        "category": "finance",
        "actions": ["tokenize_asset", "transfer_rwa_ownership", "get_rwa_asset"],
    },
    {
        "id": "did_identity",
        "name": "Digital Identity",
        "icon": "person.badge.shield.checkmark",
        "description": "Own and control your identity. Share only what you choose.",
        "category": "identity",
        "actions": ["create_did", "resolve_did", "update_did"],
    },
    {
        "id": "dao_management",
        "name": "DAOs",
        "icon": "person.3",
        "description": "Create decentralized organizations with on-chain governance.",
        "category": "governance",
        "actions": ["create_dao", "join_dao", "get_dao"],
    },
    {
        "id": "staking",
        "name": "Staking",
        "icon": "arrow.triangle.2.circlepath",
        "description": "Stake assets and earn yield at competitive rates.",
        "category": "finance",
        "actions": ["stake", "unstake", "claim_staking_rewards", "get_staking_position"],
    },
    {
        "id": "insurance",
        "name": "Insurance",
        "icon": "shield.checkered",
        "description": "Parametric insurance with automatic payouts. No claims, no waiting.",
        "category": "protection",
        "actions": ["create_insurance", "file_insurance_claim", "get_insurance_policy"],
    },
    {
        "id": "marketplace",
        "name": "Marketplace",
        "icon": "storefront",
        "description": "Buy and sell digital and real-world assets with on-chain escrow.",
        "category": "commerce",
        "actions": ["list_marketplace", "buy_marketplace", "search_marketplace"],
    },
    {
        "id": "payments",
        "name": "Payments",
        "icon": "creditcard",
        "description": "Send money anywhere instantly. Zero fees.",
        "category": "finance",
        "actions": ["send_payment", "get_payment_quote", "create_payment"],
    },
    {
        "id": "governance",
        "name": "Governance",
        "icon": "checkmark.seal",
        "description": "Tamper-proof voting and proposal management.",
        "category": "governance",
        "actions": ["create_proposal", "vote", "list_proposals"],
    },
    {
        "id": "ip_royalties",
        "name": "IP & Royalties",
        "icon": "text.badge.checkmark",
        "description": "Register and protect intellectual property on-chain.",
        "category": "creative",
        "actions": ["register_ip", "license_ip", "get_ip"],
    },
    {
        "id": "fundraising",
        "name": "Fundraising",
        "icon": "chart.line.uptrend.xyaxis",
        "description": "Milestone-based campaigns with full transparency.",
        "category": "finance",
        "actions": ["create_campaign", "contribute_to_campaign", "get_campaign"],
    },
    {
        "id": "dex",
        "name": "Token Exchange",
        "icon": "arrow.left.arrow.right",
        "description": "Swap tokens at the best rates across DEXs.",
        "category": "finance",
        "actions": ["swap_tokens", "get_swap_quote", "add_liquidity"],
    },
    {
        "id": "security_audit",
        "name": "Security Audit",
        "icon": "lock.shield",
        "description": "Glasswing-powered vulnerability scanning for every contract.",
        "category": "infrastructure",
        "actions": [],
    },
]


class BridgeRoutes:
    """
    Mobile bridge endpoints for the MTRX iOS app.

    All endpoints sit under /bridge/v1/ and return the consistent
    MobileResponse envelope. Auth is required (same API key as gateway).
    """

    def __init__(self, config: dict, gateway_server):
        self._config = config
        self._server = gateway_server
        self._linked_wallets: dict[str, dict] = {}  # session_id → wallet info
        self._push_tokens: dict[str, str] = {}  # session_id → APNs token

    def register_routes(self, app: web.Application) -> None:
        """Register all bridge endpoints."""
        # Session
        app.router.add_post("/bridge/v1/session/create", self.create_session)
        app.router.add_post("/bridge/v1/session/resume", self.resume_session)

        # Chat
        app.router.add_post("/bridge/v1/chat", self.chat)

        # Direct actions (bypass chat, call services directly)
        app.router.add_post("/bridge/v1/action", self.execute_action)

        # Wallet
        app.router.add_post("/bridge/v1/wallet/link", self.link_wallet)
        app.router.add_get("/bridge/v1/wallet/status", self.wallet_status)

        # App config
        app.router.add_get("/bridge/v1/config", self.get_config)
        app.router.add_get("/bridge/v1/services", self.get_services)

        # Push notifications
        app.router.add_post("/bridge/v1/push/register", self.register_push)

        # Dashboard (aggregated data for iOS home screen)
        app.router.add_get("/bridge/v1/dashboard", self.get_dashboard)

        logger.info("Bridge routes registered under /bridge/v1/")

    # ─── Session ──────────────────────────────────────────────────────────

    async def create_session(self, request: web.Request) -> web.Response:
        """Create a new chat session. Returns session_id and first-boot greeting."""
        try:
            body = await request.json()
        except Exception:
            body = {}

        session_id = uuid.uuid4().hex[:16]
        device_id = body.get("device_id", "")
        app_version = body.get("app_version", "")

        # Store session metadata
        self._server.conversations[session_id] = []

        return MobileResponse.ok({
            "session_id": session_id,
            "greeting": (
                "Hi, my name is Trinity\n\n"
                "Welcome to the world of 0pnMatrx, "
                "I'll be by your side the entire time if you need me"
            ),
            "agents": {
                "trinity": {"available": True, "role": "assistant"},
                "neo": {"available": True, "role": "execution"},
                "morpheus": {"available": True, "role": "guardian"},
            },
            "features": {
                "chat": True,
                "blockchain": self._config.get("blockchain", {}).get("enabled", True),
                "glasswing_audit": True,
                "services": len(SERVICE_CATALOG),
            },
        })

    async def resume_session(self, request: web.Request) -> web.Response:
        """Resume an existing session."""
        try:
            body = await request.json()
        except Exception:
            return MobileResponse.error("Invalid JSON")

        session_id = body.get("session_id", "")
        if not session_id:
            return MobileResponse.error("session_id required")

        exists = session_id in self._server.conversations
        return MobileResponse.ok({
            "session_id": session_id,
            "resumed": exists,
            "message_count": len(self._server.conversations.get(session_id, [])),
        })

    # ─── Chat ─────────────────────────────────────────────────────────────

    async def chat(self, request: web.Request) -> web.Response:
        """
        Send a message to an agent. Same as /chat but with mobile envelope.
        iOS app sends: {"message": "...", "agent": "trinity", "session_id": "..."}
        """
        try:
            body = await request.json()
        except Exception:
            return MobileResponse.error("Invalid JSON")

        message = body.get("message", "").strip()
        if not message:
            return MobileResponse.error("message required")

        agent = body.get("agent", "trinity")
        session_id = body.get("session_id", "default")

        # Delegate to the main gateway handler
        # Build a fake request for handle_chat
        from aiohttp.test_utils import make_mocked_request
        from unittest.mock import AsyncMock

        # Just call the chat logic directly
        try:
            result = await self._handle_chat_internal(message, agent, session_id, body)
            return MobileResponse.ok(result)
        except Exception as e:
            logger.error(f"Bridge chat error: {e}", exc_info=True)
            return MobileResponse.error(str(e), 500)

    async def _handle_chat_internal(
        self, message: str, agent: str, session_id: str, body: dict,
    ) -> dict:
        """Internal chat handler that reuses gateway logic."""
        from runtime.react_loop import Message

        if session_id not in self._server.conversations:
            self._server.conversations[session_id] = []

        self._server.conversations[session_id].append(
            Message(role="user", content=message)
        )

        system_prompt = self._server.react_loop.get_agent_prompt(agent)
        time_context = self._server.temporal.get_context_string()
        full_prompt = f"{system_prompt}\n\n{time_context}" if system_prompt else time_context

        from runtime.react_loop import ReActContext
        context = ReActContext(
            agent_name=agent,
            conversation=self._server.conversations[session_id].copy(),
            system_prompt=full_prompt,
        )

        context.metadata["user_context"] = {
            "session_id": session_id,
            "agent": agent,
            "wallet_connected": body.get("wallet_connected", False),
            "network": body.get("network"),
            "platform": "ios",
        }

        # Inject linked wallet if available
        wallet = self._linked_wallets.get(session_id)
        if wallet:
            context.metadata["user_context"]["wallet_address"] = wallet.get("address")
            context.metadata["user_context"]["wallet_connected"] = True

        result = await self._server.react_loop.run(context)

        self._server.conversations[session_id].append(
            Message(role="assistant", content=result.response)
        )

        # Trim history
        if len(self._server.conversations[session_id]) > 100:
            self._server.conversations[session_id] = \
                self._server.conversations[session_id][-50:]

        return {
            "response": result.response,
            "agent": agent,
            "tool_calls": result.tool_calls,
            "session_id": session_id,
            "provider": result.provider,
        }

    # ─── Direct Actions ───────────────────────────────────────────────────

    async def execute_action(self, request: web.Request) -> web.Response:
        """
        Execute a platform action directly (no chat, no ReAct loop).
        iOS app calls this for button-driven actions like "Stake", "Swap", etc.

        Body: {"action": "swap_tokens", "params": {"token_in": "ETH", ...}, "session_id": "..."}
        """
        try:
            body = await request.json()
        except Exception:
            return MobileResponse.error("Invalid JSON")

        action = body.get("action", "")
        params = body.get("params", {})
        session_id = body.get("session_id", "")

        if not action:
            return MobileResponse.error("action required")

        try:
            from runtime.blockchain.services.service_dispatcher import ServiceDispatcher
            dispatcher = ServiceDispatcher(self._config)
            result = await dispatcher.execute(action, params)
            return MobileResponse.ok(result)
        except KeyError as e:
            return MobileResponse.error(f"Unknown action: {action}", 404)
        except TypeError as e:
            return MobileResponse.error(f"Invalid parameters: {e}", 422)
        except Exception as e:
            logger.error(f"Bridge action error: {e}", exc_info=True)
            return MobileResponse.error(str(e), 500)

    # ─── Wallet ───────────────────────────────────────────────────────────

    async def link_wallet(self, request: web.Request) -> web.Response:
        """Link a wallet address to a session."""
        try:
            body = await request.json()
        except Exception:
            return MobileResponse.error("Invalid JSON")

        session_id = body.get("session_id", "")
        address = body.get("address", "")

        if not session_id or not address:
            return MobileResponse.error("session_id and address required")

        self._linked_wallets[session_id] = {
            "address": address,
            "linked_at": time.time(),
            "network": body.get("network", "base-sepolia"),
        }

        return MobileResponse.ok({
            "linked": True,
            "address": address,
        })

    async def wallet_status(self, request: web.Request) -> web.Response:
        """Get wallet status for a session."""
        session_id = request.query.get("session_id", "")
        wallet = self._linked_wallets.get(session_id)

        if not wallet:
            return MobileResponse.ok({"linked": False})

        # Try to get balance
        balance = None
        try:
            from runtime.blockchain.interface import BlockchainInterface
            blockchain = BlockchainInterface(self._config)
            balance_wei = blockchain.w3.eth.get_balance(wallet["address"])
            balance = str(blockchain.w3.from_wei(balance_wei, "ether"))
        except Exception:
            pass

        return MobileResponse.ok({
            "linked": True,
            "address": wallet["address"],
            "network": wallet.get("network", "base-sepolia"),
            "balance_eth": balance,
        })

    # ─── App Config ───────────────────────────────────────────────────────

    async def get_config(self, request: web.Request) -> web.Response:
        """Return app configuration for the iOS client."""
        return MobileResponse.ok({
            "platform": "0pnMatrx",
            "version": "1.0.0",
            "network": self._config.get("blockchain", {}).get("network", "base-sepolia"),
            "chain_id": self._config.get("blockchain", {}).get("chain_id", 84532),
            "agents": ["trinity", "neo", "morpheus"],
            "features": {
                "glasswing_audit": True,
                "eas_attestations": True,
                "gas_sponsorship": True,
                "managed_agents": True,
            },
            "endpoints": {
                "chat": "/bridge/v1/chat",
                "action": "/bridge/v1/action",
                "wallet": "/bridge/v1/wallet/link",
                "dashboard": "/bridge/v1/dashboard",
                "services": "/bridge/v1/services",
            },
        })

    async def get_services(self, request: web.Request) -> web.Response:
        """Return the full service catalog for the iOS app."""
        return MobileResponse.ok({"services": SERVICE_CATALOG})

    # ─── Push Notifications ───────────────────────────────────────────────

    async def register_push(self, request: web.Request) -> web.Response:
        """Register APNs push token for a session."""
        try:
            body = await request.json()
        except Exception:
            return MobileResponse.error("Invalid JSON")

        session_id = body.get("session_id", "")
        token = body.get("push_token", "")

        if not session_id or not token:
            return MobileResponse.error("session_id and push_token required")

        self._push_tokens[session_id] = token
        return MobileResponse.ok({"registered": True})

    # ─── Dashboard ────────────────────────────────────────────────────────

    async def get_dashboard(self, request: web.Request) -> web.Response:
        """
        Aggregated dashboard data for the iOS home screen.
        Returns wallet balance, recent activity, active positions, and suggestions.
        """
        session_id = request.query.get("session_id", "")
        wallet = self._linked_wallets.get(session_id)

        dashboard = {
            "wallet": None,
            "services_available": len(SERVICE_CATALOG),
            "active_sessions": len(self._server.conversations),
            "suggestions": [
                "Convert a contract to a smart contract",
                "Check your staking rewards",
                "Explore the marketplace",
                "Create your digital identity",
            ],
        }

        if wallet:
            try:
                from runtime.blockchain.interface import BlockchainInterface
                blockchain = BlockchainInterface(self._config)
                balance_wei = blockchain.w3.eth.get_balance(wallet["address"])
                balance = str(blockchain.w3.from_wei(balance_wei, "ether"))
                dashboard["wallet"] = {
                    "address": wallet["address"],
                    "balance_eth": balance,
                    "network": wallet.get("network"),
                }
            except Exception:
                dashboard["wallet"] = {
                    "address": wallet["address"],
                    "balance_eth": None,
                    "network": wallet.get("network"),
                }

        return MobileResponse.ok(dashboard)
