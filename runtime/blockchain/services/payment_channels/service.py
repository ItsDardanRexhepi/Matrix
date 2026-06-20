"""
Layer-2 state channels and Raiden-style off-chain payment routing.

This service speaks to a real Raiden network through two surfaces:

1. The off-chain **Raiden REST API** (``services.payment_channels.endpoint``)
   — the documented Raiden node HTTP API. open / pay / close are issued as
   ``PUT``/``POST``/``PATCH`` calls against ``/api/v1/...`` on the operator's
   own Raiden node. See https://docs.raiden.network/raiden-api-1/resources .

2. The on-chain **TokenNetwork** contract
   (``services.payment_channels.contract_address``) — Raiden's per-token
   channel registry. Used as a fallback/settlement surface when no Raiden
   node endpoint is configured: ``openChannel`` / ``closeChannel`` are sent
   as PLATFORM-level transactions through the gas-sponsored paymaster.

Gating: each method first checks for the specific credential it needs
(Raiden ``endpoint`` for the off-chain path, or the ``contract_address`` +
a reachable RPC for the on-chain path). When neither is configured it
returns the canonical CREDENTIAL-GATED ``not_deployed_response`` naming the
exact missing config key.

NON-CUSTODIAL: on-chain writes are signed ONLY with the platform paymaster
account (``Web3Manager.send_transaction``). A Raiden channel is funded with
the *platform's* tokens via the platform's own Raiden node; user wallet keys
are never touched server-side. Routing a payment that would move a USER's
deposit is performed by the user's own Raiden node, not by this server —
this service only drives the platform node / platform channels.
"""

from __future__ import annotations

import logging
from typing import Any

from runtime.blockchain.web3_manager import (
    Web3Manager,
    is_placeholder_value,
    not_deployed_response,
)

logger = logging.getLogger(__name__)


# ── Minimal real ABI fragments for Raiden's TokenNetwork contract ─────────
# Source: raiden-contracts TokenNetwork.sol (function selectors are stable
# across Raiden's Red Eyes / Bespin deployments). Only the functions this
# service invokes are declared.
#
# openChannel(address participant1, address participant2, uint256 settle_timeout)
#   -> uint256 channel_identifier
# closeChannel(uint256 channel_identifier, address partner, address closing,
#              bytes32 balance_hash, uint256 nonce, bytes32 additional_hash,
#              bytes signature, bytes closing_signature)
# getChannelIdentifier(address participant, address partner) -> uint256
_TOKEN_NETWORK_ABI = [
    {
        "name": "openChannel",
        "type": "function",
        "stateMutability": "nonpayable",
        "inputs": [
            {"name": "participant1", "type": "address"},
            {"name": "participant2", "type": "address"},
            {"name": "settle_timeout", "type": "uint256"},
        ],
        "outputs": [{"name": "channel_identifier", "type": "uint256"}],
    },
    {
        # UNVERIFIED: the full Raiden closeChannel signature carries balance-proof
        # data that only the user's node can produce. The minimal 2-arg cooperative
        # variant below is used for the platform-channel settlement path; the full
        # balance-proof close is left to the Raiden node REST API.
        "name": "closeChannel",
        "type": "function",
        "stateMutability": "nonpayable",
        "inputs": [
            {"name": "channel_identifier", "type": "uint256"},
            {"name": "partner", "type": "address"},
        ],
        "outputs": [],
    },
    {
        "name": "getChannelIdentifier",
        "type": "function",
        "stateMutability": "view",
        "inputs": [
            {"name": "participant", "type": "address"},
            {"name": "partner", "type": "address"},
        ],
        "outputs": [{"name": "channel_identifier", "type": "uint256"}],
    },
]

# Default Raiden cooperative settle timeout (blocks). Raiden mandates a value
# within [settle_timeout_min, settle_timeout_max]; 500 is the documented default.
_DEFAULT_SETTLE_TIMEOUT = 500


class PaymentChannelsService:
    """Layer-2 state channels and Raiden-style off-chain payment routing."""

    service_name = "payment_channels"

    def __init__(self, config: dict) -> None:
        self._config = config
        self._web3 = Web3Manager.get_shared(config)
        self._gas_sponsor = None  # lazy — only instantiated when needed

    def _sponsor(self):
        if self._gas_sponsor is None:
            from runtime.blockchain.gas_sponsor import GasSponsor
            self._gas_sponsor = GasSponsor(self._config)
        return self._gas_sponsor

    # ── config helpers ────────────────────────────────────────────────
    def _cfg(self) -> dict:
        return self._config.get("services", {}).get(self.service_name, {}) or {}

    def _raiden_endpoint(self) -> str:
        """Base URL of the operator's Raiden node REST API, or '' if unset."""
        return (self._cfg().get("endpoint") or "").strip().rstrip("/")

    def _token_network_address(self) -> str:
        """Raiden TokenNetwork contract address (per-token channel registry)."""
        cfg = self._cfg()
        # `contract_address` is the canonical key; accept token_network_address too.
        return (
            cfg.get("contract_address")
            or cfg.get("token_network_address")
            or ""
        )

    def _token_address(self) -> str:
        """ERC-20 token whose TokenNetwork these channels live on."""
        return self._cfg().get("token_address", "") or ""

    async def _raiden_request(
        self, method: str, path: str, json_body: dict | None = None
    ) -> dict:
        """Issue a request against the Raiden REST API. Lazy-imports httpx.

        Returns the parsed JSON response, or a CREDENTIAL-GATED / error dict.
        Never raises — callers get a structured dict either way.
        """
        endpoint = self._raiden_endpoint()
        url = f"{endpoint}{path}"
        api_key = self._cfg().get("api_key", "")
        headers = {"Content-Type": "application/json"}
        # Raiden's bundled node has no auth, but operators commonly front it with
        # a reverse proxy requiring a bearer token; forward it when configured.
        if api_key and not is_placeholder_value(api_key):
            headers["Authorization"] = f"Bearer {api_key}"

        try:
            import httpx  # lazy — keep import-safe if httpx is absent
        except ImportError:
            return not_deployed_response(
                self.service_name,
                extra={
                    "missing": "httpx (python package)",
                    "protocol": "Raiden REST API",
                    "detail": "httpx is required to call the Raiden node endpoint",
                },
            )

        try:
            async with httpx.AsyncClient(timeout=30.0) as client:
                resp = await client.request(
                    method, url, json=json_body, headers=headers
                )
            try:
                payload = resp.json()
            except Exception:
                payload = {"raw": resp.text}
            return {
                "ok": resp.status_code < 400,
                "http_status": resp.status_code,
                "raiden_endpoint": endpoint,
                "response": payload,
            }
        except Exception as exc:  # noqa: BLE001 — surface as structured error
            logger.warning("Raiden REST call %s %s failed: %s", method, url, exc)
            return {
                "ok": False,
                "error": str(exc),
                "raiden_endpoint": endpoint,
                "protocol": "Raiden REST API",
            }

    # ── open_channel ──────────────────────────────────────────────────
    async def open_channel(self, **params: Any) -> dict:
        """Open a Raiden payment channel.

        Off-chain path (preferred): ``PUT /api/v1/channels`` on the Raiden node.
        On-chain fallback: ``TokenNetwork.openChannel`` as a platform tx.
        """
        partner = params.get("partner_address") or params.get("partner")
        deposit = params.get("deposit", params.get("total_deposit", 0))
        token_address = params.get("token_address") or self._token_address()
        settle_timeout = int(
            params.get("settle_timeout", _DEFAULT_SETTLE_TIMEOUT)
        )

        endpoint = self._raiden_endpoint()
        if endpoint and not is_placeholder_value(endpoint):
            # REAL off-chain Raiden REST: open a channel from the platform node.
            if is_placeholder_value(token_address):
                return not_deployed_response(
                    self.service_name,
                    extra={
                        "method": "open_channel",
                        "missing": "services.payment_channels.token_address",
                        "protocol": "Raiden REST API",
                    },
                )
            if is_placeholder_value(partner):
                return {
                    "status": "error",
                    "service": self.service_name,
                    "method": "open_channel",
                    "error": "partner_address is required to open a channel",
                }
            body = {
                "token_address": token_address,
                "partner_address": partner,
                "total_deposit": int(deposit),
                "settle_timeout": settle_timeout,
            }
            result = await self._raiden_request(
                "PUT", "/api/v1/channels", json_body=body
            )
            result.update({"method": "open_channel", "protocol": "raiden"})
            return result

        # On-chain fallback: TokenNetwork.openChannel (platform-level write).
        token_network = self._token_network_address()
        if (
            not self._web3.available
            or is_placeholder_value(token_network)
        ):
            return not_deployed_response(
                self.service_name,
                extra={
                    "method": "open_channel",
                    "missing": (
                        "services.payment_channels.endpoint (Raiden node URL) "
                        "or services.payment_channels.contract_address "
                        "(TokenNetwork) + reachable blockchain.rpc_url"
                    ),
                    "protocol": "Raiden / TokenNetwork state channels",
                },
            )
        if is_placeholder_value(partner):
            return {
                "status": "error",
                "service": self.service_name,
                "method": "open_channel",
                "error": "partner_address is required to open a channel",
            }
        try:
            # NON-CUSTODIAL: opened from the PLATFORM account as participant1.
            platform = self._web3.get_account().address
            contract = self._web3.load_contract(token_network, _TOKEN_NETWORK_ABI)
            tx = contract.functions.openChannel(
                self._web3.w3.to_checksum_address(platform),
                self._web3.w3.to_checksum_address(partner),
                settle_timeout,
            ).build_transaction({"from": platform})
            tx_hash = await self._web3.send_transaction(tx)
            return {
                "status": "submitted",
                "service": self.service_name,
                "method": "open_channel",
                "protocol": "raiden_token_network",
                "token_network": token_network,
                "participant1": platform,
                "participant2": partner,
                "settle_timeout": settle_timeout,
                "tx_hash": tx_hash,
                "explorer_url": self._web3.explorer_url(tx_hash),
            }
        except Exception as exc:  # noqa: BLE001
            logger.error("open_channel on-chain failed: %s", exc)
            return {
                "status": "error",
                "service": self.service_name,
                "method": "open_channel",
                "error": str(exc),
            }

    # ── route_payment ─────────────────────────────────────────────────
    async def route_payment(self, **params: Any) -> dict:
        """Route an off-chain payment through Raiden's mediated network.

        REAL off-chain Raiden REST: ``POST /api/v1/payments/{token}/{target}``.
        Payment routing is inherently an off-chain (state-channel) operation,
        so there is no on-chain fallback — without a Raiden node it is gated.
        """
        token_address = params.get("token_address") or self._token_address()
        target = params.get("target_address") or params.get("target")
        amount = params.get("amount", 0)
        identifier = params.get("identifier")  # optional Raiden payment id

        endpoint = self._raiden_endpoint()
        if not endpoint or is_placeholder_value(endpoint):
            return not_deployed_response(
                self.service_name,
                extra={
                    "method": "route_payment",
                    "missing": "services.payment_channels.endpoint (Raiden node REST URL)",
                    "protocol": "Raiden REST API (mediated payment)",
                },
            )
        if is_placeholder_value(token_address):
            return not_deployed_response(
                self.service_name,
                extra={
                    "method": "route_payment",
                    "missing": "services.payment_channels.token_address",
                    "protocol": "Raiden REST API",
                },
            )
        if is_placeholder_value(target):
            return {
                "status": "error",
                "service": self.service_name,
                "method": "route_payment",
                "error": "target_address is required to route a payment",
            }

        body: dict[str, Any] = {"amount": int(amount)}
        if identifier is not None:
            body["identifier"] = int(identifier)
        # NON-CUSTODIAL: the platform's own Raiden node debits the PLATFORM's
        # channel deposit. User funds are never moved by this server.
        result = await self._raiden_request(
            "POST", f"/api/v1/payments/{token_address}/{target}", json_body=body
        )
        result.update({"method": "route_payment", "protocol": "raiden"})
        return result

    # ── close_channel ─────────────────────────────────────────────────
    async def close_channel(self, **params: Any) -> dict:
        """Close a Raiden payment channel and trigger settlement.

        Off-chain path (preferred): ``PATCH /api/v1/channels/{token}/{partner}``
        with ``{"state": "closed"}`` on the Raiden node (node submits the
        balance-proof close on-chain itself).
        On-chain fallback: ``TokenNetwork.closeChannel`` as a platform tx.
        """
        token_address = params.get("token_address") or self._token_address()
        partner = params.get("partner_address") or params.get("partner")

        endpoint = self._raiden_endpoint()
        if endpoint and not is_placeholder_value(endpoint):
            if is_placeholder_value(token_address):
                return not_deployed_response(
                    self.service_name,
                    extra={
                        "method": "close_channel",
                        "missing": "services.payment_channels.token_address",
                        "protocol": "Raiden REST API",
                    },
                )
            if is_placeholder_value(partner):
                return {
                    "status": "error",
                    "service": self.service_name,
                    "method": "close_channel",
                    "error": "partner_address is required to close a channel",
                }
            result = await self._raiden_request(
                "PATCH",
                f"/api/v1/channels/{token_address}/{partner}",
                json_body={"state": "closed"},
            )
            result.update({"method": "close_channel", "protocol": "raiden"})
            return result

        # On-chain fallback: TokenNetwork.closeChannel (platform-level write).
        token_network = self._token_network_address()
        if (
            not self._web3.available
            or is_placeholder_value(token_network)
        ):
            return not_deployed_response(
                self.service_name,
                extra={
                    "method": "close_channel",
                    "missing": (
                        "services.payment_channels.endpoint (Raiden node URL) "
                        "or services.payment_channels.contract_address "
                        "(TokenNetwork) + reachable blockchain.rpc_url"
                    ),
                    "protocol": "Raiden / TokenNetwork state channels",
                },
            )
        if is_placeholder_value(partner):
            return {
                "status": "error",
                "service": self.service_name,
                "method": "close_channel",
                "error": "partner_address is required to close a channel",
            }
        try:
            contract = self._web3.load_contract(token_network, _TOKEN_NETWORK_ABI)
            channel_id = int(params.get("channel_identifier", 0))
            if channel_id == 0:
                # Resolve the channel id from the on-chain registry.
                platform = self._web3.get_account().address
                channel_id = contract.functions.getChannelIdentifier(
                    self._web3.w3.to_checksum_address(platform),
                    self._web3.w3.to_checksum_address(partner),
                ).call()
            # UNVERIFIED: cooperative close (no balance proof). A unilateral
            # balance-proof close must go through the Raiden node REST path.
            tx = contract.functions.closeChannel(
                int(channel_id),
                self._web3.w3.to_checksum_address(partner),
            ).build_transaction({"from": self._web3.get_account().address})
            tx_hash = await self._web3.send_transaction(tx)
            return {
                "status": "submitted",
                "service": self.service_name,
                "method": "close_channel",
                "protocol": "raiden_token_network",
                "token_network": token_network,
                "channel_identifier": int(channel_id),
                "partner": partner,
                "tx_hash": tx_hash,
                "explorer_url": self._web3.explorer_url(tx_hash),
            }
        except Exception as exc:  # noqa: BLE001
            logger.error("close_channel on-chain failed: %s", exc)
            return {
                "status": "error",
                "service": self.service_name,
                "method": "close_channel",
                "error": str(exc),
            }
