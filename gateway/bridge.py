from __future__ import annotations

"""
Matrix-to-The Matrix Bridge — connects the MTRX iOS app to the Matrix backend.

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

import asyncio
import hashlib
import json
import logging
import time
import uuid
from typing import Any

from aiohttp import web

from gateway.error_contract import client_error, dispatcher_failure

logger = logging.getLogger(__name__)


class MobileResponse:
    """Consistent response envelope for mobile clients."""

    @staticmethod
    def ok(data: Any = None) -> web.Response:
        body = {"ok": True, "data": data or {}, "timestamp": time.time()}
        return web.json_response(body)

    @staticmethod
    def error(
        message: str,
        code: int = 400,
        *,
        error_code: str | None = None,
        ref: str | None = None,
    ) -> web.Response:
        body = {"ok": False, "error": message, "timestamp": time.time()}
        # RUN-5: `code` and `ref` are part of the error contract. Passing only
        # the sentence made the bridge agree on STATUS while diverging on
        # SHAPE — a client could not read a machine code or a correlation id
        # here, though it could on every other channel.
        if error_code:
            body["code"] = error_code
        if ref:
            body["ref"] = ref
        return web.json_response(body, status=code)

    @staticmethod
    def from_exception(exc: BaseException, *, what: str = "Bridge") -> web.Response:
        """The one way this channel turns an exception into a response.

        Every bridge failure goes through `client_error`, so classification,
        redaction and the correlation id are decided in exactly one place
        rather than re-derived per call site.
        """
        status, err = client_error(exc, None, what=what)
        return MobileResponse.error(
            err["error"], status, error_code=err["code"], ref=err["ref"]
        )


# ─── Service Catalog for iOS ────────────────────────────────────────────────

SERVICE_CATALOG = [
    {
        "id": "contract_conversion",
        "name": "Smart Contracts",
        "icon": "doc.text.magnifyingglass",
        "description": "Convert any agreement into a self-executing smart contract.",
        "category": "core",
        # NEW-12: deploy_contract removed — the platform does not deploy.
        "actions": ["convert_contract", "estimate_contract_cost", "list_templates"],
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


# ─── Component Registry — dynamic UI schemas for iOS ──────────────────────

COMPONENT_REGISTRY: dict[str, dict[str, Any]] = {
    "contract_conversion": {
        "version": "1.0.0",
        "min_app_version": "1.0.0",
        "capabilities": ["wallet_connected", "network_base"],
        "ui_flow": {
            "screens": [
                {
                    "id": "convert_contract",
                    "title": "Convert to Smart Contract",
                    "fields": [
                        {"name": "contract_text", "type": "text", "label": "Agreement Text", "required": True, "placeholder": "Paste your agreement or contract text here..."},
                        {"name": "contract_type", "type": "select", "label": "Contract Type", "required": True, "placeholder": "Select type", "options": ["Escrow", "Vesting", "Revenue Share", "Service Agreement", "Custom"]},
                        {"name": "parties", "type": "text", "label": "Counterparty Address", "required": True, "placeholder": "0x..."},
                        {"name": "auto_deploy", "type": "toggle", "label": "Deploy Immediately", "required": False, "placeholder": ""},
                    ],
                },
            ],
        },
    },
    "defi": {
        "version": "1.0.0",
        "min_app_version": "1.0.0",
        "capabilities": ["wallet_connected", "network_base"],
        "ui_flow": {
            "screens": [
                {
                    "id": "create_loan",
                    "title": "Create DeFi Loan",
                    "fields": [
                        {"name": "collateral_token", "type": "select", "label": "Collateral Token", "required": True, "placeholder": "Select token", "options": ["ETH", "WETH", "USDC", "DAI"]},
                        {"name": "collateral_amount", "type": "decimal", "label": "Collateral Amount", "required": True, "placeholder": "0.00"},
                        {"name": "borrow_token", "type": "select", "label": "Borrow Token", "required": True, "placeholder": "Select token", "options": ["USDC", "DAI", "ETH"]},
                        {"name": "borrow_amount", "type": "decimal", "label": "Borrow Amount", "required": True, "placeholder": "0.00"},
                    ],
                },
            ],
        },
    },
    "nft_services": {
        "version": "1.0.0",
        "min_app_version": "1.0.0",
        "capabilities": ["wallet_connected", "network_base"],
        "ui_flow": {
            "screens": [
                {
                    "id": "mint_nft",
                    "title": "Mint NFT",
                    "fields": [
                        {"name": "name", "type": "text", "label": "NFT Name", "required": True, "placeholder": "My NFT"},
                        {"name": "description", "type": "text", "label": "Description", "required": False, "placeholder": "Describe your NFT..."},
                        {"name": "image_uri", "type": "text", "label": "Image URI", "required": True, "placeholder": "ipfs:// or https://..."},
                        {"name": "royalty_percent", "type": "decimal", "label": "Royalty %", "required": False, "placeholder": "2.5"},
                        {"name": "collection", "type": "select", "label": "Collection", "required": False, "placeholder": "Select collection", "options": ["New Collection", "Existing"]},
                    ],
                },
            ],
        },
    },
    "rwa_tokenization": {
        "version": "1.0.0",
        "min_app_version": "1.0.0",
        "capabilities": ["wallet_connected", "network_base", "kyc_verified"],
        "ui_flow": {
            "screens": [
                {
                    "id": "tokenize_asset",
                    "title": "Tokenize Real World Asset",
                    "fields": [
                        {"name": "asset_type", "type": "select", "label": "Asset Type", "required": True, "placeholder": "Select type", "options": ["Real Estate", "Vehicle", "Commodity", "Equipment", "Other"]},
                        {"name": "asset_name", "type": "text", "label": "Asset Name", "required": True, "placeholder": "e.g. 123 Main St Apt 4B"},
                        {"name": "valuation", "type": "decimal", "label": "Valuation (USD)", "required": True, "placeholder": "0.00"},
                        {"name": "total_shares", "type": "decimal", "label": "Total Shares", "required": True, "placeholder": "1000"},
                        {"name": "document_uri", "type": "text", "label": "Supporting Document URI", "required": False, "placeholder": "ipfs:// or https://..."},
                    ],
                },
            ],
        },
    },
    "did_identity": {
        "version": "1.0.0",
        "min_app_version": "1.0.0",
        "capabilities": ["wallet_connected"],
        "ui_flow": {
            "screens": [
                {
                    "id": "create_did",
                    "title": "Create Digital Identity",
                    "fields": [
                        {"name": "display_name", "type": "text", "label": "Display Name", "required": True, "placeholder": "Your public name"},
                        {"name": "method", "type": "select", "label": "DID Method", "required": True, "placeholder": "Select method", "options": ["did:ethr", "did:web", "did:key"]},
                        {"name": "public_profile", "type": "toggle", "label": "Public Profile", "required": False, "placeholder": ""},
                    ],
                },
            ],
        },
    },
    "dao_management": {
        "version": "1.0.0",
        "min_app_version": "1.0.0",
        "capabilities": ["wallet_connected", "network_base"],
        "ui_flow": {
            "screens": [
                {
                    "id": "create_dao",
                    "title": "Create DAO",
                    "fields": [
                        {"name": "dao_name", "type": "text", "label": "DAO Name", "required": True, "placeholder": "My Organization"},
                        {"name": "description", "type": "text", "label": "Description", "required": True, "placeholder": "What is this DAO for?"},
                        {"name": "governance_model", "type": "select", "label": "Governance Model", "required": True, "placeholder": "Select model", "options": ["Token Voting", "Multisig", "Quadratic Voting", "Conviction Voting"]},
                        {"name": "quorum_percent", "type": "decimal", "label": "Quorum %", "required": True, "placeholder": "51"},
                        {"name": "token_symbol", "type": "text", "label": "Governance Token Symbol", "required": True, "placeholder": "e.g. GOV"},
                    ],
                },
            ],
        },
    },
    "staking": {
        "version": "1.0.0",
        "min_app_version": "1.0.0",
        "capabilities": ["wallet_connected", "network_base"],
        "ui_flow": {
            "screens": [
                {
                    "id": "stake",
                    "title": "Stake Assets",
                    "fields": [
                        {"name": "token", "type": "select", "label": "Token", "required": True, "placeholder": "Select token", "options": ["ETH", "USDC", "DAI", "WETH"]},
                        {"name": "amount", "type": "decimal", "label": "Amount", "required": True, "placeholder": "0.00"},
                        {"name": "lock_period", "type": "select", "label": "Lock Period", "required": True, "placeholder": "Select period", "options": ["30 days", "90 days", "180 days", "365 days"]},
                        {"name": "auto_compound", "type": "toggle", "label": "Auto-Compound Rewards", "required": False, "placeholder": ""},
                    ],
                },
            ],
        },
    },
    "insurance": {
        "version": "1.0.0",
        "min_app_version": "1.0.0",
        "capabilities": ["wallet_connected", "network_base"],
        "ui_flow": {
            "screens": [
                {
                    "id": "create_insurance",
                    "title": "Create Insurance Policy",
                    "fields": [
                        {"name": "policy_type", "type": "select", "label": "Policy Type", "required": True, "placeholder": "Select type", "options": ["Smart Contract Cover", "Stablecoin Depeg", "Oracle Failure", "Slashing Protection"]},
                        {"name": "coverage_amount", "type": "decimal", "label": "Coverage Amount (USD)", "required": True, "placeholder": "0.00"},
                        {"name": "duration_days", "type": "decimal", "label": "Duration (days)", "required": True, "placeholder": "30"},
                        {"name": "beneficiary", "type": "address", "label": "Beneficiary Address", "required": False, "placeholder": "0x... (defaults to your wallet)"},
                    ],
                },
            ],
        },
    },
    "marketplace": {
        "version": "1.0.0",
        "min_app_version": "1.0.0",
        "capabilities": ["wallet_connected", "network_base"],
        "ui_flow": {
            "screens": [
                {
                    "id": "list_marketplace",
                    "title": "List Item for Sale",
                    "fields": [
                        {"name": "item_name", "type": "text", "label": "Item Name", "required": True, "placeholder": "What are you selling?"},
                        {"name": "description", "type": "text", "label": "Description", "required": True, "placeholder": "Describe the item..."},
                        {"name": "price", "type": "decimal", "label": "Price (USDC)", "required": True, "placeholder": "0.00"},
                        {"name": "category", "type": "select", "label": "Category", "required": True, "placeholder": "Select category", "options": ["Digital Good", "Physical Good", "Service", "NFT", "Other"]},
                        {"name": "escrow_enabled", "type": "toggle", "label": "Enable Escrow", "required": False, "placeholder": ""},
                    ],
                },
            ],
        },
    },
    "payments": {
        "version": "1.0.0",
        "min_app_version": "1.0.0",
        "capabilities": ["wallet_connected", "network_base"],
        "ui_flow": {
            "screens": [
                {
                    "id": "send_payment",
                    "title": "Send Payment",
                    "fields": [
                        {"name": "recipient", "type": "address", "label": "Recipient Address", "required": True, "placeholder": "0x..."},
                        {"name": "amount", "type": "decimal", "label": "Amount", "required": True, "placeholder": "0.00"},
                        {"name": "token", "type": "select", "label": "Token", "required": True, "placeholder": "Select token", "options": ["ETH", "USDC", "DAI", "WETH"]},
                        {"name": "memo", "type": "text", "label": "Memo", "required": False, "placeholder": "What is this payment for?"},
                    ],
                },
            ],
        },
    },
    "governance": {
        "version": "1.0.0",
        "min_app_version": "1.0.0",
        "capabilities": ["wallet_connected", "network_base"],
        "ui_flow": {
            "screens": [
                {
                    "id": "create_proposal",
                    "title": "Create Proposal",
                    "fields": [
                        {"name": "dao_address", "type": "address", "label": "DAO Address", "required": True, "placeholder": "0x..."},
                        {"name": "title", "type": "text", "label": "Proposal Title", "required": True, "placeholder": "Title of your proposal"},
                        {"name": "description", "type": "text", "label": "Description", "required": True, "placeholder": "Describe your proposal in detail..."},
                        {"name": "voting_period", "type": "select", "label": "Voting Period", "required": True, "placeholder": "Select period", "options": ["3 days", "5 days", "7 days", "14 days"]},
                    ],
                },
            ],
        },
    },
    "ip_royalties": {
        "version": "1.0.0",
        "min_app_version": "1.0.0",
        "capabilities": ["wallet_connected", "network_base"],
        "ui_flow": {
            "screens": [
                {
                    "id": "register_ip",
                    "title": "Register Intellectual Property",
                    "fields": [
                        {"name": "ip_title", "type": "text", "label": "Title", "required": True, "placeholder": "Name of your work"},
                        {"name": "ip_type", "type": "select", "label": "IP Type", "required": True, "placeholder": "Select type", "options": ["Music", "Art", "Software", "Literature", "Patent", "Other"]},
                        {"name": "content_hash", "type": "text", "label": "Content Hash / URI", "required": True, "placeholder": "ipfs:// or sha256:..."},
                        {"name": "royalty_percent", "type": "decimal", "label": "Royalty %", "required": True, "placeholder": "5.0"},
                    ],
                },
            ],
        },
    },
    "fundraising": {
        "version": "1.0.0",
        "min_app_version": "1.0.0",
        "capabilities": ["wallet_connected", "network_base"],
        "ui_flow": {
            "screens": [
                {
                    "id": "create_campaign",
                    "title": "Create Fundraising Campaign",
                    "fields": [
                        {"name": "campaign_name", "type": "text", "label": "Campaign Name", "required": True, "placeholder": "Name your campaign"},
                        {"name": "goal_amount", "type": "decimal", "label": "Goal (USDC)", "required": True, "placeholder": "0.00"},
                        {"name": "description", "type": "text", "label": "Description", "required": True, "placeholder": "What are you raising funds for?"},
                        {"name": "duration_days", "type": "decimal", "label": "Duration (days)", "required": True, "placeholder": "30"},
                        {"name": "milestone_based", "type": "toggle", "label": "Milestone-Based Release", "required": False, "placeholder": ""},
                    ],
                },
            ],
        },
    },
    "dex": {
        "version": "1.0.0",
        "min_app_version": "1.0.0",
        "capabilities": ["wallet_connected", "network_base"],
        "ui_flow": {
            "screens": [
                {
                    "id": "swap_tokens",
                    "title": "Swap Tokens",
                    "fields": [
                        {"name": "token_in", "type": "select", "label": "From Token", "required": True, "placeholder": "Select token", "options": ["ETH", "USDC", "DAI", "WETH"]},
                        {"name": "amount_in", "type": "decimal", "label": "Amount", "required": True, "placeholder": "0.00"},
                        {"name": "token_out", "type": "select", "label": "To Token", "required": True, "placeholder": "Select token", "options": ["ETH", "USDC", "DAI", "WETH"]},
                        {"name": "slippage", "type": "decimal", "label": "Max Slippage %", "required": False, "placeholder": "0.5"},
                    ],
                },
            ],
        },
    },
    "security_audit": {
        "version": "1.0.0",
        "min_app_version": "1.0.0",
        "capabilities": ["wallet_connected"],
        "ui_flow": {
            "screens": [
                {
                    "id": "audit_contract",
                    "title": "Audit Smart Contract",
                    "fields": [
                        {"name": "contract_address", "type": "address", "label": "Contract Address", "required": True, "placeholder": "0x..."},
                        {"name": "source_code", "type": "text", "label": "Source Code (optional)", "required": False, "placeholder": "Paste Solidity source or leave blank for bytecode analysis"},
                        {"name": "audit_depth", "type": "select", "label": "Audit Depth", "required": True, "placeholder": "Select depth", "options": ["Quick Scan", "Standard", "Deep Analysis"]},
                    ],
                },
            ],
        },
    },
}


def _build_component_list() -> list[dict[str, Any]]:
    """Merge SERVICE_CATALOG entries with their COMPONENT_REGISTRY schemas."""
    components: list[dict[str, Any]] = []
    for svc in SERVICE_CATALOG:
        entry: dict[str, Any] = {**svc}
        registry = COMPONENT_REGISTRY.get(svc["id"])
        if registry:
            entry.update(registry)
        components.append(entry)
    return components


def _component_checksum(component_id: str) -> str:
    """Deterministic checksum for a single component's registry data."""
    data = COMPONENT_REGISTRY.get(component_id, {})
    raw = json.dumps(data, sort_keys=True).encode()
    return hashlib.sha256(raw).hexdigest()[:16]


class BridgeRoutes:
    """
    Mobile bridge endpoints for the MTRX iOS app.

    All endpoints sit under /bridge/v1/ and return the consistent
    MobileResponse envelope. Auth is required (same API key as gateway).
    """

    def __init__(self, config: dict, gateway_server):
        self._config = config
        self._server = gateway_server
        # session_id → wallet info, including the `subject` of the wallet
        # session that linked it. A session id is a name the caller chooses, so
        # a link is shown to, and speaks for, only the account that made it.
        self._linked_wallets: dict[str, dict] = {}
        self._web3_manager = None  # lazy; built on first balance lookup

    # ─── Whose is this session id? ────────────────────────────────────────

    def _key(self, raw) -> str:
        """The gateway's one spelling of a session id (strip, 100 characters) —
        the spelling conversations are stored under."""
        key = getattr(self._server, "_session_key", None)
        return key(raw) if key is not None else str(raw or "").strip()[:100]

    def _held_elsewhere(self, request, session_id: str):
        """Refusal message when *session_id* is a conversation another account
        owns (never claims it); None otherwise, or on a server without T3."""
        check = getattr(self._server, "_conversation_held_elsewhere", None)
        return check(request, session_id) if check is not None else None

    def _visible_link(self, request, session_id: str) -> dict:
        """The wallet linked to *session_id*, if the request may see it: the
        account whose wallet session made the link, or the operator. ``{}``
        otherwise — including when the link belongs to someone else."""
        record = self._linked_wallets.get(self._key(session_id)) or {}
        if not record:
            return {}
        subject_of = getattr(self._server, "_session_subject", None)
        is_operator = getattr(self._server, "_is_operator", None)
        if subject_of is None or is_operator is None:
            return record  # a bare server without T2 (unit-test fakes)
        subject = subject_of(request)
        if subject:
            return record if record.get("subject") == subject else {}
        return record if is_operator(request) else {}

    def _get_web3_manager(self):
        """Lazily instantiate a :class:`Web3Manager` for balance reads.

        Returns ``None`` if web3 isn't installed or the blockchain
        config is missing/placeholder — callers should treat that as
        "balance unavailable" rather than an error.
        """
        if self._web3_manager is not None:
            return self._web3_manager
        try:
            from runtime.blockchain.web3_manager import Web3Manager
            mgr = Web3Manager(self._config)
            if not mgr.available:
                return None
            self._web3_manager = mgr
            return mgr
        except Exception as exc:
            logger.debug("Web3Manager unavailable for balance lookup: %s", exc)
            return None

    def _lookup_balance_eth(self, address: str) -> float | None:
        """Return the ETH balance of *address* or ``None`` if unavailable."""
        mgr = self._get_web3_manager()
        if mgr is None or not address:
            return None
        try:
            return mgr.get_balance_eth(address)
        except Exception as exc:
            logger.warning("Balance lookup failed for %s: %s", address, exc)
            return None

    def route_specs(self) -> list[tuple[str, str, Any]]:
        """Every bridge endpoint, as ``(method, path, handler)`` — the ONE table
        both entrances read: the HTTP router (register_routes) and
        POST /api/v1/batch (ServiceRoutes._build_batch_route_map).

        They were two hand-kept lists. e1232ca removed /bridge/v1/push/register
        from the batch copy when its handler was deleted; P1-6 brought the
        handler back on the router only, so the same call succeeded direct and
        answered 404 "No route" through batch.
        """
        return [
            # Session
            ("POST", "/bridge/v1/session/create", self.create_session),
            ("POST", "/bridge/v1/session/resume", self.resume_session),
            # Chat
            ("POST", "/bridge/v1/chat", self.chat),
            # Direct actions (bypass chat, call services directly)
            ("POST", "/bridge/v1/action", self.execute_action),
            # Wallet
            ("POST", "/bridge/v1/wallet/link", self.link_wallet),
            ("GET", "/bridge/v1/wallet/status", self.wallet_status),
            # Push notification registration (P1-6)
            ("POST", "/bridge/v1/push/register", self.register_push),
            # App config
            ("GET", "/bridge/v1/config", self.get_config),
            ("GET", "/bridge/v1/services", self.get_services),
            # Dashboard (aggregated data for iOS home screen)
            ("GET", "/bridge/v1/dashboard", self.get_dashboard),
            # Component registry (dynamic UI schemas)
            ("GET", "/bridge/v1/components", self.get_components),
            ("GET", "/bridge/v1/components/manifest", self.get_components_manifest),
            ("GET", "/bridge/v1/components/{component_id}", self.get_component),
        ]

    def register_routes(self, app: web.Application) -> None:
        """Register all bridge endpoints (from route_specs)."""
        for method, path, handler in self.route_specs():
            if method == "GET":
                app.router.add_get(path, handler)   # GET also answers HEAD
            else:
                app.router.add_route(method, path, handler)
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

        # Open the (empty) conversation in the working set, through the same
        # bounded path every chat entrance uses.
        history = getattr(self._server, "_conversation_history", None)
        if history is not None:
            history(session_id)
        else:  # a bare server without the shared helper (unit-test fakes)
            self._server.conversations[session_id] = []

        return MobileResponse.ok({
            "session_id": session_id,
            "greeting": (
                "Hi, my name is Trinity\n\n"
                "Welcome to the world of The Matrix, "
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

        # Keyed as the chat entrances key it, BEFORE the ownership check: the
        # check ran on the raw id and the lookup on the normalised one, so
        # "conv-A " (nobody owns that spelling) described conv-A.
        session_id = self._key(body.get("session_id", "") if isinstance(body, dict) else "")
        if not session_id:
            return MobileResponse.error("session_id required")
        # Existence and length of someone else's conversation are theirs.
        held = self._held_elsewhere(request, session_id)
        if held:
            return MobileResponse.error(held, 403)

        # From the working set, else the store: the working set is bounded, so
        # "not in memory" does not mean "does not exist" (it never did across a
        # restart).
        cached = self._server.conversations.get(session_id)
        if cached is not None:
            exists, count = True, len(cached)
        else:
            try:
                stored = self._server.react_loop.memory.load_conversation(session_id)
            except Exception:
                stored = []
            exists, count = bool(stored), len(stored)
        return MobileResponse.ok({
            "session_id": session_id,
            "resumed": exists,
            "message_count": count,
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

        # The same input bounds as /chat, /chat/stream and /ws — this entrance
        # applied none: a message up to the 1 MiB body cap went into the shared
        # conversation store, a non-string one 500'd, any agent name ran.
        check = getattr(self._server, "_chat_turn_input", None)
        if check is not None:
            message, agent, invalid = check(body)
            if invalid:
                return MobileResponse.error(invalid, 400)
        else:  # a bare server without the shared helper (unit-test fakes)
            message = str(body.get("message", "")).strip()
            agent = body.get("agent", "trinity")
        if not message:
            return MobileResponse.error("message required")

        # The same canonical agent and the same refusal as /chat and /ws. This
        # surface had no membership check, and the operator check compared the
        # raw name, so {"agent": "Neo"} reached Neo's tools with no credential.
        # A server that cannot say whether the caller is the operator gets
        # Trinity or nothing.
        from gateway.chat_agents import resolve_chat_agent
        resolve = getattr(self._server, "_resolve_chat_agent", None)
        agent, refused = (resolve(request, body.get("agent", "trinity")) if resolve
                          else resolve_chat_agent(body.get("agent", "trinity"), False))
        if refused:
            return MobileResponse.error(refused[1], refused[0])
        # T2: the Apple user behind the presented session is the apple_id the
        # Morpheus gate sees — not a value the body asserts.
        apple_sub = getattr(self._server, "_session_apple_id", lambda _r: "")(request)
        if apple_sub:
            body = {**body, "apple_id": apple_sub}
        # T3: never the shared "default" — the body's own id, else a session
        # derived from the presented wallet session, else refused in production.
        resolve = getattr(self._server, "_resolve_session_id", None)
        if resolve is not None:
            session_id, session_error = resolve(request, body.get("session_id"))
            if session_error:
                return MobileResponse.error(session_error, 400)
            turn_claim, denied = self._server._open_turn(request, session_id)
            if denied:
                return MobileResponse.error(denied, 403)
        else:
            session_id = body.get("session_id", "default")
            turn_claim = None

        try:
            caller_kind = str(getattr(self._server, "_caller_kind", lambda _r: "")(request) or "")
            result = await self._handle_chat_internal(
                message, agent, session_id, body, request,
                claim=turn_claim, caller_kind=caller_kind)
            return MobileResponse.ok(result)
        except Exception as e:
            # NEW-8 + RUN-5: this was `MobileResponse.error(str(e), 500)` — the
            # exception text WAS the response body, so a model-provider failure
            # shipped internal hostnames, ports, and model names to the client.
            # It also answered 500 where /chat answers 503 for the identical
            # condition, so two channels disagreed on the same event.
            #
            # Now: one contract — and it must be USED, not re-derived. The first
            # version of this fix hand-rolled the classification here, which
            # reproduced three defects the contract module exists to remove:
            # it read `request.get("request_id")` (the middleware stores the id
            # in a contextvar, so the ref was always "-"); it classed timeouts
            # as unreachable via `isinstance(e, OSError)` (TimeoutError
            # subclasses OSError) so a 504 condition answered 503; and it
            # returned no machine code at all. Status agreed with /chat while
            # the SHAPE did not.
            return MobileResponse.from_exception(e, what="Bridge chat")

    async def _handle_chat_internal(
        self, message: str, agent: str, session_id: str, body: dict, request, *,
        claim=None, caller_kind: str = "",
    ) -> dict:
        """Internal chat handler that reuses gateway logic."""
        from runtime.react_loop import Message

        # The same working set, hydration and write-through as /chat, /chat/
        # stream and /ws. This entrance neither loaded the stored history nor
        # saved its turns: a conversation begun here existed only in memory,
        # and the first other entrance to touch it replaced it with the (empty)
        # stored copy.
        shared = getattr(self._server, "_turn_conversation", None)
        if shared is not None:
            conversation = shared(session_id, message)
        else:  # a bare server without the shared helpers (unit-test fakes)
            conversation = [*self._server.conversations.setdefault(session_id, []),
                            Message(role="user", content=message)]

        system_prompt = self._server.react_loop.get_agent_prompt(agent)
        time_context = self._server.temporal.get_context_string()
        full_prompt = f"{system_prompt}\n\n{time_context}" if system_prompt else time_context

        from runtime.react_loop import ReActContext
        context = ReActContext(
            agent_name=agent,
            conversation=conversation,
            system_prompt=full_prompt,
        )

        # The same builder /chat, /chat/stream and /ws use: identity from the
        # presented session, never from the body or from whatever wallet was
        # linked to the session id this caller chose to name.
        #
        # This used to inject `_linked_wallets[session_id]` as wallet_address.
        # /bridge/v1/chat is public, so ANYONE naming a session id inherited
        # the wallet a SIWE holder had linked to it — as the dispatcher's
        # caller identity. The holder who linked gets that identity anyway by
        # presenting their session: `_session_identity` derives it.
        context.metadata["user_context"] = {
            **self._server._chat_user_context(
                request, session_id=session_id, agent=agent, body=body),
            "platform": "ios",
            # app_attest is threaded from the body because it is a SIGNED
            # assertion the Morpheus gate verifies, not a claim the caller makes
            # about itself. apple_id is NOT re-read here: the builder above
            # derives it from the presented session, and letting the body spread
            # over it would hand an anonymous caller any identity it named.
            "app_attest": body.get("app_attest"),
            # Which CREDENTIAL this request carries (operator / session /
            # anonymous), computed by the gateway — never read from the body. The
            # tool dispatcher refuses a non-operator caller the operations a
            # session's own routes refuse (gateway/session_routes.py).
            "caller_kind": caller_kind,
        }
        context.metadata["client_context"] = self._server._client_turn_context(body)
        # The claim the turn was admitted under: the loop writes scoped memory,
        # and _record_turn the conversation, only while it stands.
        context.metadata["turn_claim"] = claim

        result = await self._server.react_loop.run(context)

        record = getattr(self._server, "_record_turn", None)
        if record is not None:
            await record(session_id, message, result.response, claim=claim)
        else:
            self._server.conversations[session_id].extend(
                conversation[-1:] + [Message(role="assistant", content=result.response)])

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
        if not isinstance(body, dict):
            return MobileResponse.error("request body must be a JSON object", 400)

        action = body.get("action", "")
        params = body.get("params")
        session_id = body.get("session_id", "")

        if not action:
            return MobileResponse.error("action required")
        # The caller's own mistakes, named as the caller's, before the gate or
        # the dispatcher sees them. An unvalidated dict action (NEW-9's shape,
        # from the wire) reached `action not in ACTION_MAP` and came back as a
        # TypeError the handler below reported as "Invalid parameters: unhashable
        # type"; list or string params raised AttributeError inside execute.
        if not isinstance(action, str):
            return MobileResponse.error("action must be a string", 400)
        if params is None:
            params = {}
        if not isinstance(params, dict):
            return MobileResponse.error("params must be an object", 400)
        session_id = self._key(session_id)

        # This route is on the session allowlist because the app's client has a
        # call for it, and it is a DISPATCHER: it takes any ACTION_MAP action name
        # into the same ServiceDispatcher the dedicated /api/v1 routes use. A
        # session refused `POST /api/v1/crossborder/send` (and refused the same
        # operation as a catalog capability) got HTTP 200 here for
        # `send_payment`. The refusal is keyed on the (service, method) the
        # action resolves to, so every dispatcher gives one answer; the operator
        # key is unaffected.
        caller_kind = str(getattr(self._server, "_caller_kind", lambda _r: "")(request) or "")
        if caller_kind and caller_kind != "operator":
            # One refusal for every dispatcher and every credential tier.
            from gateway.session_routes import caller_refusal_message, caller_refused_route
            refused = caller_refused_route(caller_kind, action)
            if refused:
                return MobileResponse.error(caller_refusal_message(caller_kind, refused), 403)

        # Security gate (boundary call): this direct action path skips the ReAct
        # loop, so it must consult the Morpheus contract itself before executing.
        # Identity comes from the session's linked wallet; the App Attest assertion
        # (if any) rides in the request body. Generic denial — no internal reason.
        from gateway.security_gate import (
            bind_request_security, current_request_security, gate_action,
            generic_denial, is_blocked,
        )
        # T2: the session the request presents (the app's Apple Bearer) names
        # the caller. The wallet linked to the session id in the body is the
        # fallback only for a request with no session (the operator) or when
        # the link is the caller's own — a session id is a name the caller
        # chose, not a credential.
        session_identity = getattr(self._server, "_session_identity", lambda _r: "")(request)
        linked = self._visible_link(request, session_id)
        identity = session_identity or linked.get("address", "")
        bind_request_security(
            identity=identity,
            app_attest=body.get("app_attest"),
            session_id=session_id,
        )
        from runtime.access_policy import dispatch_pair
        decision = await gate_action(action, params if isinstance(params, dict) else {},
                                     current_request_security(), operation=dispatch_pair(action))
        if is_blocked(decision):
            return MobileResponse.error(generic_denial(decision), 403)

        try:
            # Reuse the server's shared ServiceDispatcher (feed engine attached
            # at startup) so direct iOS actions publish to the social feed too.
            dispatcher = getattr(self._server, "service_dispatcher", None)
            if dispatcher is None:
                from runtime.blockchain.services.service_dispatcher import ServiceDispatcher
                dispatcher = ServiceDispatcher(self._config)   # cold fallback: works, but no feed
            # 17-D. THREAD THE WALLET WE ALREADY BOUND, TWENTY LINES UP.
            # `linked.get("address", "")` was read above and handed to
            # `bind_request_security(identity=...)` for the gate — and then
            # dropped, so the service decided who could grant an IP right
            # without ever being told who was asking, and the attestation and
            # public feed recorded the grant with actor "". The identity was
            # never missing; it was discarded at this line.
            #
            # ── ARGUMENT SLOT BUG, found while making that change ───────────
            # This line read `dispatcher.execute(action, params)`, but the
            # signature is `execute(action, service=None, params=None)` — so
            # `params` landed in the SERVICE-OVERRIDE slot and the real params
            # defaulted to {}. `if service: target_service = service` then set
            # the target service to a dict, and the registry lookup raised
            # `unhashable type: 'dict'`.
            #
            # MEASURED, not inferred. Replaying this exact call shape:
            #   execute("set_nft_rights", {"collection": ..., "rights": ...})
            #     -> {"status": "error", "error_category": "validation",
            #         "error": "Invalid parameters for set_nft_rights:
            #                   unhashable type: 'dict'"}
            #   execute("set_nft_rights", None, {...same params...})
            #     -> {"status": "ok", ... "rights_set" ...}
            # So EVERY direct bridge action carrying parameters failed, and
            # only zero-parameter actions (falsy dict -> `if service` false)
            # ever reached their service.
            #
            # It is fixed here rather than filed because 17-D is unreachable
            # without it: `set_rights` always carries params, so on this path
            # the request died before the service was called, and a caller
            # identity threaded into a call that never happens is not a fix.
            # Passing by keyword so the slot cannot be misaligned again.
            #
            # ── ONE IDENTITY, NOT TWO ───────────────────────────────────────
            # This passed `linked.get("address", "")` while the gate above was
            # bound to `session_identity or linked`. So a request presenting
            # account B's session and naming the session id account W had
            # linked a wallet to was GATED as B and EXECUTED as W: the service
            # decided ownership for the account that linked, not the one that
            # asked. The dispatcher now gets exactly the identity the gate saw.
            result = await dispatcher.execute(
                action,
                params=params,
                caller_identity=identity,
            )
        except Exception as e:
            # RUN-5: was the raw exception as the response body. And this
            # caught TypeError as "Invalid parameters" (422, the raw binding
            # message quoted back) and KeyError as "Unknown action" (404) —
            # but the dispatcher returns every caller-attributable failure as a
            # payload; an exception that escapes it is an internal defect,
            # which is what the error contract says: internal_error, a ref.
            return MobileResponse.from_exception(e, what="Bridge action")
        return self._action_response(action, result)

    @staticmethod
    def _action_response(action: str, result) -> web.Response:
        """Relay the dispatcher's payload with the status it means.

        Every payload was HTTP 200 ``ok: true`` — including
        ``{"status": "error"}`` — the RUN-4 inversion ServiceRoutes._ok fixed
        for /api/v1 and never reached here. A success is relayed exactly as
        before; a failure is decided by error_contract.dispatcher_failure."""
        failure = dispatcher_failure(result, what=f"Bridge action {action}")
        if failure is None:
            return MobileResponse.ok(result)
        status, err = failure
        return MobileResponse.error(err["error"], status, error_code=err.get("code"), ref=err.get("ref"))

    # ─── Push notifications ─────────────────────────────────────────────────

    async def register_push(self, request: web.Request) -> web.Response:
        """POST /bridge/v1/push/register — {session_id, push_token} ->
        {registered: bool}. Persists the APNs device token so iOSPushChannel can
        fan out pushes. Nothing sends one yet: no gateway event is wired to the
        NotificationDispatcher (GatewayServer.__init__), and APNs credentials
        (.p8/key_id/team_id/bundle_id) alone would not change that."""
        try:
            body = await request.json()
        except Exception:
            return MobileResponse.error("invalid JSON")
        push_token = str(body.get("push_token", "")).strip()
        session_id = self._key(body.get("session_id", ""))
        if not push_token:
            return MobileResponse.error("push_token required")
        # T3: a token registered under the shared "default" (or no) session
        # belonged to everyone; derive the session from the presented wallet
        # session, or refuse in production.
        resolve = getattr(self._server, "_resolve_session_id", None)
        if resolve is not None:
            session_id, session_error = resolve(request, session_id)
            if session_error:
                return MobileResponse.error(session_error, 400)
        # A device token attached to someone else's conversation would receive
        # what is sent for it.
        held = self._held_elsewhere(request, session_id)
        if held:
            return MobileResponse.error(held, 403)
        # The wallet the token is filed under is the caller's — derived from the
        # presented session — never the wallet linked to a session id it named.
        identity = getattr(self._server, "_session_identity", lambda _r: "")(request)
        wallet = (identity if identity and not identity.startswith("apple:")
                  else self._visible_link(request, session_id).get("address", ""))
        try:
            from runtime.notifications.token_store import PushTokenStore
            db = self._server.react_loop.memory.db
            store = PushTokenStore(db)
            await store.register(
                push_token,
                session_id=session_id,
                wallet=wallet,
                platform="ios",
                bundle_id=str(body.get("bundle_id", "")),
                # The account behind the presented session — what account
                # deletion finds this device by.
                owner=getattr(self._server, "_session_subject", lambda _r: "")(request),
            )
        except Exception as exc:
            logger.error("push token registration failed: %s", exc)
            return MobileResponse.error("registration failed", 500)
        return MobileResponse.ok({"registered": True})

    # ─── Wallet ───────────────────────────────────────────────────────────

    async def link_wallet(self, request: web.Request) -> web.Response:
        """Link a SIWE-verified wallet to a session.

        Requires the ``X-Wallet-Session`` header containing a session token
        previously issued by ``POST /auth/verify``. The verified address is
        taken from the server-side session record — any address supplied in
        the request body is ignored to prevent impersonation.
        """
        wallet_token = request.headers.get("X-Wallet-Session", "")
        if not wallet_token:
            return MobileResponse.error(
                "X-Wallet-Session header required (sign in via /auth/verify first)",
                401,
            )

        wallet_sessions = getattr(self._server, "wallet_sessions", {})
        wallet_session = wallet_sessions.get(wallet_token)
        if not wallet_session:
            return MobileResponse.error("invalid or expired wallet session", 401)

        try:
            body = await request.json()
        except Exception:
            body = {}

        session_id = self._key(body.get("session_id", "") if isinstance(body, dict) else "")
        if not session_id:
            return MobileResponse.error("session_id required")

        address = wallet_session["address"]
        # The address came from the session (above); the session id did not —
        # it is whatever the body named. Linking into a conversation another
        # account owns, or over a link another account made, is refused.
        # (The X-Wallet-Session is read first, so the request's subject here is
        # `address`.)
        held = self._held_elsewhere(request, session_id)
        if held:
            return MobileResponse.error(held, 403)
        existing = self._linked_wallets.get(session_id)
        if existing and existing.get("subject") not in (None, address):
            return MobileResponse.error("this session is linked to another account", 403)
        self._linked_wallets[session_id] = {
            "address": address,
            "subject": address,
            "linked_at": time.time(),
            "network": body.get("network", "base-sepolia"),
            "verified": True,
        }

        return MobileResponse.ok({
            "linked": True,
            "address": address,
            "verified": True,
        })

    async def wallet_status(self, request: web.Request) -> web.Response:
        """Get wallet status for a session."""
        session_id = self._key(request.query.get("session_id", ""))
        if self._linked_wallets.get(session_id) and not self._visible_link(request, session_id):
            return MobileResponse.error("this session is linked to another account", 403)
        wallet = self._visible_link(request, session_id)

        if not wallet:
            return MobileResponse.ok({"linked": False})

        return MobileResponse.ok({
            "linked": True,
            "address": wallet["address"],
            "network": wallet.get("network", "base-sepolia"),
            "balance_eth": self._lookup_balance_eth(wallet["address"]),
            "verified": wallet.get("verified", False),
        })

    # ─── App Config ───────────────────────────────────────────────────────

    async def get_config(self, request: web.Request) -> web.Response:
        """Return app configuration for the iOS client."""
        return MobileResponse.ok({
            "platform": "The Matrix",
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

    # ─── Component Registry ──────────────────────────────────────────────

    async def get_components(self, request: web.Request) -> web.Response:
        """Return the full component registry with UI schemas for all services."""
        try:
            components = _build_component_list()
            return MobileResponse.ok({"components": components})
        except Exception as e:
            logger.error(f"Bridge get_components error: {e}", exc_info=True)
            # RUN-5: was the raw exception as the response body.
            return MobileResponse.from_exception(e, what='Bridge')

    async def get_component(self, request: web.Request) -> web.Response:
        """Return a single component by ID with its full UI schema."""
        component_id = request.match_info.get("component_id", "")
        if not component_id:
            return MobileResponse.error("component_id required")

        try:
            # Find the service catalog entry
            svc_entry = None
            for svc in SERVICE_CATALOG:
                if svc["id"] == component_id:
                    svc_entry = svc
                    break

            if svc_entry is None:
                return MobileResponse.error(f"Component not found: {component_id}", 404)

            component: dict[str, Any] = {**svc_entry}
            registry = COMPONENT_REGISTRY.get(component_id)
            if registry:
                component.update(registry)

            return MobileResponse.ok({"component": component})
        except Exception as e:
            logger.error(f"Bridge get_component error: {e}", exc_info=True)
            # RUN-5: was the raw exception as the response body.
            return MobileResponse.from_exception(e, what='Bridge')

    async def get_components_manifest(self, request: web.Request) -> web.Response:
        """
        Return a lightweight manifest of component IDs, versions, and checksums.
        The iOS app uses this to detect what has changed without downloading
        the full registry.
        """
        try:
            manifest: list[dict[str, str]] = []
            for svc in SERVICE_CATALOG:
                sid = svc["id"]
                registry = COMPONENT_REGISTRY.get(sid, {})
                manifest.append({
                    "id": sid,
                    "version": registry.get("version", "0.0.0"),
                    "checksum": _component_checksum(sid),
                })
            return MobileResponse.ok({"manifest": manifest})
        except Exception as e:
            logger.error(f"Bridge get_components_manifest error: {e}", exc_info=True)
            # RUN-5: was the raw exception as the response body.
            return MobileResponse.from_exception(e, what='Bridge')

    # ─── Dashboard ────────────────────────────────────────────────────────

    async def get_dashboard(self, request: web.Request) -> web.Response:
        """
        Aggregated dashboard data for the iOS home screen.
        Returns wallet balance, recent activity, active positions, and suggestions.
        """
        session_id = self._key(request.query.get("session_id", ""))
        # The caller's own link only; another account's address and balance
        # are not part of this caller's home screen.
        wallet = self._visible_link(request, session_id)

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
            dashboard["wallet"] = {
                "address": wallet["address"],
                "balance_eth": self._lookup_balance_eth(wallet["address"]),
                "network": wallet.get("network"),
                "verified": wallet.get("verified", False),
            }

        return MobileResponse.ok(dashboard)
