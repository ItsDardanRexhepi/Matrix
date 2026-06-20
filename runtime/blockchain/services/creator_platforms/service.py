"""
Creator platforms: Sound.xyz drops, Mirror posts, Paragraph publishing, creator coins.

These are primarily OFF-CHAIN protocol-API integrations, with an optional
ON-CHAIN path for Sound.xyz minting against a deployed SoundEdition contract:

- ``mint_sound``            → Sound.xyz. Off-chain default: Sound GraphQL/REST API
                              (api.sound.xyz) with the platform's Sound API key.
                              On-chain option: call ``mintTo`` on a configured
                              SoundEdition contract, signed by the platform paymaster.
- ``publish_mirror_post``   → Mirror (mirror.xyz). Publishes an entry; the canonical
                              storage is Arweave (the AR/Mirror API). Requires the
                              platform's Mirror/AR publishing credential.
- ``publish_paragraph_post``→ Paragraph (paragraph.xyz / paragraph.com) publishing API
                              with the platform's Paragraph API key.

Each method:
  1. Gates FIRST on the EXACT credential it needs (api_key / contract_address /
     endpoint). When the credential is missing or a placeholder it returns the
     canonical ``not_deployed_response`` (CREDENTIAL-GATED) naming the precise
     config key so CREDENTIALS_NEEDED.md can map it.
  2. When configured, performs the REAL documented protocol call (HTTP API or, for
     on-chain Sound minting, a real contract transaction) and returns the real
     response. It NEVER fabricates a tx hash, edition address, post id, or Arweave id.

NON-CUSTODIAL: these are publishing/mint operations performed with the platform's
own creator-platform accounts (Sound/Mirror/Paragraph API keys) and, for the
on-chain Sound mint, the platform paymaster account via
``Web3Manager.send_transaction``. No user wallet is signed with and no user funds
are moved server-side. The mint recipient (``to``) is an explicit parameter; the
gas/payment is settled by the platform paymaster, never a user's wallet.

``httpx`` is imported lazily inside each method so importing this module never
requires the HTTP stack to be installed (import-safe for test collection). web3 is
only touched through ``Web3Manager`` (also lazy / offline-safe).
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

# Canonical documented protocol base URLs (overridable via per-platform config).
# Sound.xyz public API (GraphQL). ref: https://docs.sound.xyz (api.sound.xyz/graphql)
_DEFAULT_SOUND_ENDPOINT = "https://api.sound.xyz/graphql"
# Mirror has no fully public write REST API; entries are stored on Arweave. The
# platform must configure its Mirror/AR publishing gateway endpoint. We default to
# the Arweave bundler gateway base used by Mirror (UNVERIFIED for direct posting).
_DEFAULT_MIRROR_ENDPOINT = "https://arweave.net"
# Paragraph publishing API base. ref: https://docs.paragraph.xyz (api.paragraph.xyz)
_DEFAULT_PARAGRAPH_ENDPOINT = "https://api.paragraph.xyz"

_HTTP_TIMEOUT = 30.0

# Minimal SoundEdition ABI — only the function we invoke for an on-chain mint.
# Sound's SoundEditionV1/V2 expose ``mint(address to, uint256 quantity)`` (payable);
# UNVERIFIED against the exact deployed edition version — supply the real address +
# confirm the selector for the configured edition before relying on the on-chain path.
_SOUND_EDITION_MINT_ABI = [
    {
        "name": "mint",
        "type": "function",
        "stateMutability": "payable",
        "inputs": [
            {"name": "to", "type": "address"},
            {"name": "quantity", "type": "uint256"},
        ],
        "outputs": [{"name": "fromTokenId", "type": "uint256"}],
    }
]


class CreatorPlatformsService:
    """Creator platforms: Sound.xyz drops, Mirror posts, Paragraph publishing, creator coins."""

    service_name = "creator_platforms"

    def __init__(self, config: dict) -> None:
        self._config = config
        self._web3 = Web3Manager.get_shared(config)
        self._gas_sponsor = None  # lazy — only instantiated when needed

    def _sponsor(self):
        if self._gas_sponsor is None:
            from runtime.blockchain.gas_sponsor import GasSponsor
            self._gas_sponsor = GasSponsor(self._config)
        return self._gas_sponsor

    # ── Helpers ──────────────────────────────────────────────────────

    def _cfg(self) -> dict:
        """Return this service's own config sub-dict."""
        return self._config.get("services", {}).get(self.service_name, {})

    def _gate(self, method: str, missing: str, protocol: str, extra: dict | None = None) -> dict:
        """Return the canonical CREDENTIAL-GATED response naming the exact key."""
        logger.warning(
            "creator_platforms.%s called but credential '%s' (%s) is not configured",
            method, missing, protocol,
        )
        payload = {"method": method, "missing": missing, "protocol": protocol}
        if extra:
            payload.update(extra)
        return not_deployed_response(self.service_name, extra=payload)

    # ── Sound.xyz ─────────────────────────────────────────────────────

    async def mint_sound(self, **params: Any) -> dict:
        """Mint a Sound.xyz drop.

        Two real paths, selected by config:

        * ON-CHAIN (default when ``services.creator_platforms.sound_edition_address``
          is configured): call ``mint(to, quantity)`` on the deployed SoundEdition
          contract. Signed and gas-paid by the platform paymaster account via
          ``Web3Manager.send_transaction`` — never a user wallet. ``to`` (mint
          recipient) is an explicit param; no user funds are custodied.
        * OFF-CHAIN API (when no edition address but a ``sound_api_key`` is set):
          query/submit via the Sound.xyz GraphQL API for the drop.

        Params: ``to`` (recipient address, on-chain path), ``quantity`` (int, default 1),
        ``edition_address`` (override), ``sound_handle`` / ``release_id`` (API path).
        """
        cfg = self._cfg()
        edition_address = params.get("edition_address") or cfg.get("sound_edition_address") or ""

        # ── ON-CHAIN path: a real SoundEdition contract is configured. ──
        if not is_placeholder_value(edition_address):
            if not self._web3.available:
                return self._gate(
                    "mint_sound",
                    "blockchain.rpc_url (web3 RPC unreachable / web3 not installed)",
                    "Sound.xyz (SoundEdition on-chain)",
                    extra={"edition_address": edition_address},
                )
            if is_placeholder_value(self._web3.paymaster_key):
                return self._gate(
                    "mint_sound",
                    "blockchain.paymaster_private_key",
                    "Sound.xyz (SoundEdition on-chain)",
                    extra={"edition_address": edition_address},
                )

            to = params.get("to") or self._web3.platform_wallet or ""
            if is_placeholder_value(to):
                return not_deployed_response(
                    self.service_name,
                    extra={
                        "method": "mint_sound",
                        "protocol": "Sound.xyz (SoundEdition on-chain)",
                        "error": "missing required param 'to' (mint recipient) and no platform_wallet configured",
                    },
                )
            quantity = int(params.get("quantity", 1) or 1)

            # REAL on-chain mint. UNVERIFIED: the exact mint selector/signature
            # varies by SoundEdition version (V1/V2 / minter modules). Confirm the
            # ABI for the configured edition before production use.
            try:
                contract = self._web3.load_contract(edition_address, _SOUND_EDITION_MINT_ABI)
                tx = contract.functions.mint(
                    self._web3.w3.to_checksum_address(to),
                    quantity,
                ).build_transaction({"from": self._web3.get_account().address})
                tx_hash = await self._web3.send_transaction(tx)
            except Exception as exc:  # noqa: BLE001
                logger.error("mint_sound on-chain mint failed: %s", exc)
                return not_deployed_response(
                    self.service_name,
                    extra={
                        "method": "mint_sound",
                        "protocol": "Sound.xyz (SoundEdition on-chain)",
                        "edition_address": edition_address,
                        "error": f"on-chain mint failed: {exc}",
                    },
                )

            return {
                "status": "minted",
                "service": self.service_name,
                "protocol": "Sound.xyz (SoundEdition on-chain)",
                "edition_address": edition_address,
                "to": to,
                "quantity": quantity,
                "tx_hash": tx_hash,
                "explorer_url": self._web3.explorer_url(tx_hash),
                "gas_paid_by": "platform paymaster",
            }

        # ── OFF-CHAIN path: Sound.xyz GraphQL API. ──
        api_key = cfg.get("sound_api_key") or ""
        if is_placeholder_value(api_key):
            return self._gate(
                "mint_sound",
                "services.creator_platforms.sound_edition_address OR services.creator_platforms.sound_api_key",
                "Sound.xyz",
            )

        release_id = params.get("release_id") or params.get("sound_handle")
        if is_placeholder_value(release_id):
            return not_deployed_response(
                self.service_name,
                extra={
                    "method": "mint_sound",
                    "protocol": "Sound.xyz",
                    "error": "missing required param 'release_id' (or 'sound_handle') for the API path",
                },
            )

        try:
            import httpx  # lazy — keep module import-safe
        except ImportError:
            return self._gate(
                "mint_sound",
                "httpx (pip install httpx)",
                "Sound.xyz",
            )

        endpoint = cfg.get("sound_endpoint") or _DEFAULT_SOUND_ENDPOINT
        # REAL Sound.xyz GraphQL query for the release. UNVERIFIED: the exact
        # GraphQL schema/field names depend on the current Sound API version and
        # whether minting is exposed via API vs. on-chain only. The provider
        # response is returned verbatim; no mint result is fabricated.
        headers = {
            "Authorization": f"Bearer {api_key}",
            "X-Sound-Client-Key": api_key,
            "Content-Type": "application/json",
        }
        gql = {
            "query": (
                "query Release($id: String!) { "
                "release(id: $id) { id title titleSlug "
                "artist { name } } }"
            ),
            "variables": {"id": str(release_id)},
        }
        try:
            async with httpx.AsyncClient(timeout=_HTTP_TIMEOUT) as client:
                resp = await client.post(endpoint, headers=headers, json=gql)
                resp.raise_for_status()
                body = resp.json()
        except Exception as exc:  # noqa: BLE001
            logger.error("mint_sound API call failed: %s", exc)
            return not_deployed_response(
                self.service_name,
                extra={
                    "method": "mint_sound",
                    "protocol": "Sound.xyz",
                    "endpoint": endpoint,
                    "error": f"Sound API call failed: {exc}",
                },
            )

        return {
            "status": "ok",
            "service": self.service_name,
            "protocol": "Sound.xyz",
            "release_id": release_id,
            "endpoint": endpoint,
            "note": (
                "Sound.xyz minting is on-chain via the SoundEdition contract. "
                "Configure services.creator_platforms.sound_edition_address to mint; "
                "this API path returns release metadata only."
            ),
            "api_response": body,
        }

    # ── Mirror (mirror.xyz / Arweave) ─────────────────────────────────

    async def publish_mirror_post(self, **params: Any) -> dict:
        """Publish a Mirror (mirror.xyz) post.

        Mirror entries are stored permanently on Arweave. Publishing requires the
        platform's Mirror/AR publishing credential (an Arweave/bundler API key or a
        configured Mirror publishing gateway). The platform's own publishing account
        is used — no user wallet is signed with and no user funds are moved.

        Params: ``title``, ``body`` (markdown/content); optional ``author``,
        ``publication`` (Mirror publication address/handle).

        Returns the REAL Arweave transaction id / entry id from the gateway.
        """
        cfg = self._cfg()
        api_key = cfg.get("mirror_api_key") or ""
        if is_placeholder_value(api_key):
            return self._gate(
                "publish_mirror_post",
                "services.creator_platforms.mirror_api_key",
                "Mirror (mirror.xyz / Arweave)",
            )

        title = params.get("title")
        content = params.get("body") or params.get("content")
        if is_placeholder_value(title) or content is None:
            return not_deployed_response(
                self.service_name,
                extra={
                    "method": "publish_mirror_post",
                    "protocol": "Mirror (mirror.xyz / Arweave)",
                    "error": "missing required params 'title' and/or 'body'",
                },
            )

        try:
            import httpx  # lazy
        except ImportError:
            return self._gate(
                "publish_mirror_post",
                "httpx (pip install httpx)",
                "Mirror (mirror.xyz / Arweave)",
            )

        endpoint = cfg.get("mirror_endpoint") or _DEFAULT_MIRROR_ENDPOINT
        # REAL publish against the configured Mirror/AR gateway. UNVERIFIED: Mirror
        # has no public documented write REST endpoint — entries are signed and
        # bundled to Arweave (typically via a bundler such as Bundlr/Irys or a
        # self-hosted publishing service). The platform must point mirror_endpoint
        # at its publishing gateway; the gateway's response (Arweave tx id) is
        # returned verbatim and never fabricated.
        headers = {
            "Authorization": f"Bearer {api_key}",
            "Content-Type": "application/json",
        }
        payload = {
            "title": title,
            "body": content,
            "author": params.get("author"),
            "publication": params.get("publication"),
        }
        url = endpoint.rstrip("/") + "/tx"
        try:
            async with httpx.AsyncClient(timeout=_HTTP_TIMEOUT) as client:
                resp = await client.post(url, headers=headers, json=payload)
                resp.raise_for_status()
                body = resp.json() if resp.content else {}
        except Exception as exc:  # noqa: BLE001
            logger.error("publish_mirror_post failed: %s", exc)
            return not_deployed_response(
                self.service_name,
                extra={
                    "method": "publish_mirror_post",
                    "protocol": "Mirror (mirror.xyz / Arweave)",
                    "endpoint": url,
                    "error": f"Mirror publish failed: {exc}",
                },
            )

        arweave_id = None
        if isinstance(body, dict):
            arweave_id = body.get("id") or body.get("transactionId") or body.get("arweaveTxId")
        return {
            "status": "published",
            "service": self.service_name,
            "protocol": "Mirror (mirror.xyz / Arweave)",
            "title": title,
            "arweave_tx_id": arweave_id,
            "endpoint": url,
            "published_by": "platform Mirror publishing account",
            "gateway_response": body,
        }

    # ── Paragraph (paragraph.xyz) ─────────────────────────────────────

    async def publish_paragraph_post(self, **params: Any) -> dict:
        """Publish a Paragraph (paragraph.xyz) post via the Paragraph publishing API.

        Uses the platform's Paragraph API key. The platform's own publishing account
        is used — no user wallet is signed with and no user funds are moved.

        Params: ``title``, ``body`` (markdown/content); optional ``publication``
        (Paragraph publication id/slug), ``subtitle``.

        Returns the REAL post id / URL from the Paragraph API.
        """
        cfg = self._cfg()
        api_key = cfg.get("paragraph_api_key") or ""
        if is_placeholder_value(api_key):
            return self._gate(
                "publish_paragraph_post",
                "services.creator_platforms.paragraph_api_key",
                "Paragraph (paragraph.xyz)",
            )

        title = params.get("title")
        content = params.get("body") or params.get("content")
        if is_placeholder_value(title) or content is None:
            return not_deployed_response(
                self.service_name,
                extra={
                    "method": "publish_paragraph_post",
                    "protocol": "Paragraph (paragraph.xyz)",
                    "error": "missing required params 'title' and/or 'body'",
                },
            )

        publication = params.get("publication") or cfg.get("paragraph_publication") or ""
        if is_placeholder_value(publication):
            return self._gate(
                "publish_paragraph_post",
                "services.creator_platforms.paragraph_publication (or 'publication' param)",
                "Paragraph (paragraph.xyz)",
            )

        try:
            import httpx  # lazy
        except ImportError:
            return self._gate(
                "publish_paragraph_post",
                "httpx (pip install httpx)",
                "Paragraph (paragraph.xyz)",
            )

        endpoint = cfg.get("paragraph_endpoint") or _DEFAULT_PARAGRAPH_ENDPOINT
        # REAL publish against the Paragraph API. UNVERIFIED: the exact path and
        # request schema depend on Paragraph's current API version (publishing is
        # partly invite/partner-gated). The API response (post id / URL) is returned
        # verbatim and never fabricated.
        headers = {
            "Authorization": f"Bearer {api_key}",
            "Content-Type": "application/json",
        }
        payload = {
            "publicationId": publication,
            "title": title,
            "subtitle": params.get("subtitle"),
            "markdown": content,
        }
        url = endpoint.rstrip("/") + "/v1/posts"
        try:
            async with httpx.AsyncClient(timeout=_HTTP_TIMEOUT) as client:
                resp = await client.post(url, headers=headers, json=payload)
                resp.raise_for_status()
                body = resp.json() if resp.content else {}
        except Exception as exc:  # noqa: BLE001
            logger.error("publish_paragraph_post failed: %s", exc)
            return not_deployed_response(
                self.service_name,
                extra={
                    "method": "publish_paragraph_post",
                    "protocol": "Paragraph (paragraph.xyz)",
                    "endpoint": url,
                    "error": f"Paragraph publish failed: {exc}",
                },
            )

        post_id = None
        post_url = None
        if isinstance(body, dict):
            post_id = body.get("id") or body.get("postId")
            post_url = body.get("url") or body.get("postUrl")
        return {
            "status": "published",
            "service": self.service_name,
            "protocol": "Paragraph (paragraph.xyz)",
            "title": title,
            "publication": publication,
            "post_id": post_id,
            "post_url": post_url,
            "endpoint": url,
            "published_by": "platform Paragraph publishing account",
            "api_response": body,
        }
