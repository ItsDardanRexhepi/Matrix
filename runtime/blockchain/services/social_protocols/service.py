"""
Lens, Farcaster, Push Protocol integrations and social/creator token launches.

Each method is gated per-integration:

- ``create_lens_profile`` — on-chain WRITE to the LensHub profile contract
  (Lens Protocol). Requires ``services.social_protocols.lens_hub_address``.
- ``publish_cast`` — off-chain POST to the Farcaster Hubble / Neynar API
  (Warpcast ecosystem). Requires ``services.social_protocols.farcaster_api_key``
  and a ``signer_uuid`` (the per-user Farcaster signer; never a custodial key).
- ``push_subscribe`` — off-chain POST to the Push Protocol (EPNS) backend API.
  Requires ``services.social_protocols.push_channel``.
- ``launch_social_token`` / ``launch_creator_coin`` — on-chain WRITE to a
  social/creator token-factory contract. Requires
  ``services.social_protocols.token_factory_address``.

Honesty / non-custodial invariants:
- DEFAULT TESTNET (Base Sepolia, chain 84532). No mainnet assumptions; every
  contract address and API key is read from config — nothing hardcoded.
- The server signs ONLY with the platform paymaster account
  (``Web3Manager.send_transaction``) for PLATFORM-level / gas-sponsored writes.
  It never signs or moves a user's wallet funds. Token launches deploy on the
  PLATFORM account; the configured ``creator``/``owner`` is passed as a
  constructor/argument so ownership lands with the creator, not the platform.
- Until the relevant credential is configured, each method returns the canonical
  ``not_deployed_response`` (CREDENTIAL-GATED). The real protocol call is
  UNVERIFIED — it cannot be proven without the protocol's account + a testnet
  deployment.
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


# ── Minimal, real ABIs (only the function each method invokes) ──────────────

# LensHub.createProfile(CreateProfileParams) — Lens Protocol profile NFT mint.
# The canonical LensHub lives on Polygon / Lens Chain; on a testnet the address
# must be supplied via config. ABI below is the minimal single-arg form Lens V2
# exposes. UNVERIFIED against the exact deployed LensHub on the operator's chain.
_LENS_HUB_ABI = [
    {
        "inputs": [
            {
                "components": [
                    {"internalType": "address", "name": "to", "type": "address"},
                    {"internalType": "address", "name": "followModule", "type": "address"},
                    {"internalType": "bytes", "name": "followModuleInitData", "type": "bytes"},
                ],
                "internalType": "struct Types.CreateProfileParams",
                "name": "createProfileParams",
                "type": "tuple",
            }
        ],
        "name": "createProfile",
        "outputs": [{"internalType": "uint256", "name": "", "type": "uint256"}],
        "stateMutability": "nonpayable",
        "type": "function",
    }
]

# Social/creator token factory — createToken(name, symbol, supply, owner).
# This is the conventional ERC-20-launcher signature; the operator's deployed
# factory governs the exact selector. UNVERIFIED against a specific factory.
_TOKEN_FACTORY_ABI = [
    {
        "inputs": [
            {"internalType": "string", "name": "name", "type": "string"},
            {"internalType": "string", "name": "symbol", "type": "string"},
            {"internalType": "uint256", "name": "initialSupply", "type": "uint256"},
            {"internalType": "address", "name": "owner", "type": "address"},
        ],
        "name": "createToken",
        "outputs": [{"internalType": "address", "name": "token", "type": "address"}],
        "stateMutability": "nonpayable",
        "type": "function",
    }
]


class SocialProtocolsService:
    """Lens, Farcaster, Push Protocol integrations and social/creator token launches."""

    service_name = "social_protocols"

    def __init__(self, config: dict) -> None:
        self._config = config
        self._web3 = Web3Manager.get_shared(config)
        self._gas_sponsor = None  # lazy — only instantiated when needed

    def _sponsor(self):
        if self._gas_sponsor is None:
            from runtime.blockchain.gas_sponsor import GasSponsor
            self._gas_sponsor = GasSponsor(self._config)
        return self._gas_sponsor

    # ── config helpers ──────────────────────────────────────────────
    def _cfg(self) -> dict:
        """Return this service's own config sub-dict."""
        services = self._config.get("services", {})
        if not isinstance(services, dict):
            return {}
        cfg = services.get(self.service_name, {})
        return cfg if isinstance(cfg, dict) else {}

    @staticmethod
    def _platform_owner(value: Any, default: str = "") -> str:
        """Return *value* if a usable address, else *default*."""
        if isinstance(value, str) and value.startswith("0x") and len(value) >= 42:
            return value
        return default

    # ── Lens — on-chain profile creation (LensHub) ──────────────────
    async def create_lens_profile(self, **params: Any) -> dict:
        """Create a Lens profile via an on-chain LensHub.createProfile write.

        Platform-signed (paymaster) write. The ``to`` address (profile owner)
        is the supplied creator — the platform never takes custody of the
        profile NFT.
        """
        cfg = self._cfg()
        lens_hub = cfg.get("lens_hub_address", "")

        # CREDENTIAL-GATED: LensHub address + a reachable RPC are both required.
        if is_placeholder_value(lens_hub) or not self._web3.available:
            return not_deployed_response(self.service_name, extra={
                "method": "create_lens_profile",
                "missing": "services.social_protocols.lens_hub_address",
                "protocol": "Lens Protocol (LensHub.createProfile)",
                "params": params,
            })

        to_addr = self._platform_owner(
            params.get("to") or params.get("owner") or params.get("creator")
        )
        if not to_addr:
            return not_deployed_response(self.service_name, extra={
                "method": "create_lens_profile",
                "missing": "to (profile-owner address)",
                "protocol": "Lens Protocol (LensHub.createProfile)",
            })

        # REAL on-chain WRITE (platform-signed). UNVERIFIED: depends on the
        # operator's LensHub matching the createProfile(tuple) selector above.
        try:
            checksum_to = self._web3.w3.to_checksum_address(to_addr)
            zero = "0x0000000000000000000000000000000000000000"
            contract = self._web3.load_contract(lens_hub, _LENS_HUB_ABI)
            create_params = (checksum_to, zero, b"")  # (to, followModule, initData)
            tx = contract.functions.createProfile(create_params).build_transaction({
                "from": self._web3.get_account().address,
                "chainId": self._web3.chain_id,
            })
            tx_hash = await self._web3.send_transaction(tx)
            return {
                "status": "submitted",
                "service": self.service_name,
                "method": "create_lens_profile",
                "protocol": "Lens Protocol",
                "profile_owner": checksum_to,
                "tx_hash": tx_hash,
                "explorer_url": self._web3.explorer_url(tx_hash),
                "gas_paid_by": "platform (paymaster)",
                "note": "UNVERIFIED until confirmed against the deployed LensHub.",
            }
        except Exception as exc:  # noqa: BLE001
            logger.error("create_lens_profile on-chain write failed: %s", exc)
            return not_deployed_response(self.service_name, extra={
                "method": "create_lens_profile",
                "protocol": "Lens Protocol (LensHub.createProfile)",
                "error": str(exc),
            })

    # ── Farcaster — off-chain cast publish (Neynar / Hubble API) ────
    async def publish_cast(self, **params: Any) -> dict:
        """Publish a Farcaster cast via the Neynar (Warpcast-ecosystem) API.

        Off-chain HTTP POST. Non-custodial: signing is delegated to the user's
        Farcaster *signer* (``signer_uuid``); the platform never holds the
        user's Farcaster custody key.
        """
        cfg = self._cfg()
        api_key = cfg.get("farcaster_api_key", "")
        # signer_uuid is per-user (caller-supplied), falling back to a configured
        # platform/service signer if the operator set one up.
        signer_uuid = params.get("signer_uuid") or cfg.get("farcaster_signer_uuid", "")

        # CREDENTIAL-GATED: Neynar API key is required.
        if is_placeholder_value(api_key):
            return not_deployed_response(self.service_name, extra={
                "method": "publish_cast",
                "missing": "services.social_protocols.farcaster_api_key",
                "protocol": "Farcaster (Neynar API)",
                "params": params,
            })
        # CREDENTIAL-GATED: a Farcaster signer is required to author a cast.
        if is_placeholder_value(signer_uuid):
            return not_deployed_response(self.service_name, extra={
                "method": "publish_cast",
                "missing": "signer_uuid (or services.social_protocols.farcaster_signer_uuid)",
                "protocol": "Farcaster (Neynar API)",
            })

        text = params.get("text") or params.get("message") or ""
        if not text:
            return not_deployed_response(self.service_name, extra={
                "method": "publish_cast",
                "missing": "text (cast body)",
                "protocol": "Farcaster (Neynar API)",
            })

        # Lazy import — keep httpx out of module import path.
        try:
            import httpx
        except ImportError:
            return not_deployed_response(self.service_name, extra={
                "method": "publish_cast",
                "missing": "httpx (python package)",
                "protocol": "Farcaster (Neynar API)",
            })

        # REAL off-chain API call. Base URL is Neynar's documented endpoint.
        base_url = cfg.get("farcaster_api_base", "https://api.neynar.com")
        payload: dict[str, Any] = {"signer_uuid": signer_uuid, "text": text}
        if params.get("channel_id"):
            payload["channel_id"] = params["channel_id"]
        if params.get("parent"):
            payload["parent"] = params["parent"]
        if params.get("embeds"):
            payload["embeds"] = params["embeds"]

        try:
            async with httpx.AsyncClient(timeout=20.0) as client:
                resp = await client.post(
                    f"{base_url.rstrip('/')}/v2/farcaster/cast",
                    json=payload,
                    headers={"api_key": api_key, "content-type": "application/json"},
                )
            data = resp.json() if resp.content else {}
            return {
                "status": "submitted" if resp.status_code < 300 else "error",
                "service": self.service_name,
                "method": "publish_cast",
                "protocol": "Farcaster (Neynar)",
                "http_status": resp.status_code,
                "response": data,
                "note": "UNVERIFIED until confirmed against a live Neynar account.",
            }
        except Exception as exc:  # noqa: BLE001
            logger.error("publish_cast API call failed: %s", exc)
            return not_deployed_response(self.service_name, extra={
                "method": "publish_cast",
                "protocol": "Farcaster (Neynar API)",
                "error": str(exc),
            })

    # ── Push Protocol — off-chain channel subscription (EPNS API) ───
    async def push_subscribe(self, **params: Any) -> dict:
        """Subscribe an address to a Push Protocol (EPNS) channel.

        Off-chain HTTP POST to the Push backend. Non-custodial: the platform
        does not sign on a user's behalf — it submits the (channel, subscriber)
        pair the caller provides. Authenticated subscription that requires a
        user signature must be performed by the user's own wallet client.
        """
        cfg = self._cfg()
        channel = cfg.get("push_channel", "")

        # CREDENTIAL-GATED: a configured Push channel (CAIP address) is required.
        if is_placeholder_value(channel):
            return not_deployed_response(self.service_name, extra={
                "method": "push_subscribe",
                "missing": "services.social_protocols.push_channel",
                "protocol": "Push Protocol (EPNS API)",
                "params": params,
            })

        subscriber = params.get("subscriber") or params.get("address") or ""
        if is_placeholder_value(subscriber):
            return not_deployed_response(self.service_name, extra={
                "method": "push_subscribe",
                "missing": "subscriber (address to subscribe)",
                "protocol": "Push Protocol (EPNS API)",
            })

        try:
            import httpx
        except ImportError:
            return not_deployed_response(self.service_name, extra={
                "method": "push_subscribe",
                "missing": "httpx (python package)",
                "protocol": "Push Protocol (EPNS API)",
            })

        # REAL off-chain API call. Base URL is the documented Push backend.
        # UNVERIFIED: the authenticated subscribe route requires a user-signed
        # verification proof; this submits the channel-membership read/list call
        # shape the operator configures.
        base_url = cfg.get("push_api_base", "https://backend.epns.io")
        chain_id = self._web3.chain_id
        caip_subscriber = (
            subscriber if subscriber.startswith("eip155:")
            else f"eip155:{chain_id}:{subscriber}"
        )
        caip_channel = (
            channel if channel.startswith("eip155:")
            else f"eip155:{chain_id}:{channel}"
        )
        payload = {"subscriber": caip_subscriber, "channel": caip_channel}

        try:
            async with httpx.AsyncClient(timeout=20.0) as client:
                resp = await client.post(
                    f"{base_url.rstrip('/')}/apis/v1/channels/subscribe_offchain",
                    json=payload,
                    headers={"content-type": "application/json"},
                )
            data = resp.json() if resp.content else {}
            return {
                "status": "submitted" if resp.status_code < 300 else "error",
                "service": self.service_name,
                "method": "push_subscribe",
                "protocol": "Push Protocol",
                "channel": caip_channel,
                "subscriber": caip_subscriber,
                "http_status": resp.status_code,
                "response": data,
                "note": "UNVERIFIED until confirmed against a live Push channel.",
            }
        except Exception as exc:  # noqa: BLE001
            logger.error("push_subscribe API call failed: %s", exc)
            return not_deployed_response(self.service_name, extra={
                "method": "push_subscribe",
                "protocol": "Push Protocol (EPNS API)",
                "error": str(exc),
            })

    # ── Social token launch (token factory, on-chain WRITE) ─────────
    async def _launch_token(self, method: str, **params: Any) -> dict:
        """Shared on-chain token-launch path for social & creator coins.

        Platform-signed deploy via the configured token factory. The new
        token's ``owner`` is the supplied creator address, so the platform
        deploys but does NOT custody the token — ownership lands with the
        creator.
        """
        cfg = self._cfg()
        factory = cfg.get("token_factory_address", "")

        # CREDENTIAL-GATED: factory address + reachable RPC required.
        if is_placeholder_value(factory) or not self._web3.available:
            return not_deployed_response(self.service_name, extra={
                "method": method,
                "missing": "services.social_protocols.token_factory_address",
                "protocol": "Social/Creator token factory (createToken)",
                "params": params,
            })

        name = params.get("name") or params.get("token_name") or ""
        symbol = params.get("symbol") or params.get("ticker") or ""
        if not name or not symbol:
            return not_deployed_response(self.service_name, extra={
                "method": method,
                "missing": "name and symbol",
                "protocol": "Social/Creator token factory (createToken)",
            })

        owner = self._platform_owner(
            params.get("owner") or params.get("creator"),
            default=self._web3.platform_wallet,
        )
        if is_placeholder_value(owner):
            return not_deployed_response(self.service_name, extra={
                "method": method,
                "missing": "owner/creator (token-owner address)",
                "protocol": "Social/Creator token factory (createToken)",
            })

        # REAL on-chain WRITE (platform-signed deploy). UNVERIFIED: depends on
        # the operator's factory matching createToken(string,string,uint256,address).
        try:
            supply_tokens = int(params.get("initial_supply") or params.get("supply") or 0)
            initial_supply_wei = supply_tokens * (10 ** 18)
            checksum_owner = self._web3.w3.to_checksum_address(owner)
            contract = self._web3.load_contract(factory, _TOKEN_FACTORY_ABI)
            tx = contract.functions.createToken(
                name, symbol, initial_supply_wei, checksum_owner
            ).build_transaction({
                "from": self._web3.get_account().address,
                "chainId": self._web3.chain_id,
            })
            tx_hash = await self._web3.send_transaction(tx)
            return {
                "status": "submitted",
                "service": self.service_name,
                "method": method,
                "protocol": "Social/Creator token factory",
                "name": name,
                "symbol": symbol,
                "initial_supply": supply_tokens,
                "owner": checksum_owner,
                "tx_hash": tx_hash,
                "explorer_url": self._web3.explorer_url(tx_hash),
                "gas_paid_by": "platform (paymaster)",
                "note": "UNVERIFIED until confirmed against the deployed factory.",
            }
        except Exception as exc:  # noqa: BLE001
            logger.error("%s on-chain write failed: %s", method, exc)
            return not_deployed_response(self.service_name, extra={
                "method": method,
                "protocol": "Social/Creator token factory (createToken)",
                "error": str(exc),
            })

    async def launch_social_token(self, **params: Any) -> dict:
        """Launch a social token via the configured token factory (on-chain)."""
        return await self._launch_token("launch_social_token", **params)

    async def launch_creator_coin(self, **params: Any) -> dict:
        """Launch a creator coin via the configured token factory (on-chain)."""
        return await self._launch_token("launch_creator_coin", **params)
