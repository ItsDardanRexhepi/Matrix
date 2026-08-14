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

import asyncio
import logging
from typing import Any

from runtime.blockchain.services.creator_platforms._guards import (
    RECEIPT_TIMEOUT_S,
    classify_transport_fault,
    log_cancelled_dispatch,
    publish_not_sent,
    require_mint_quantity,
    require_text,
    publish_rejected,
    refusal_response,
    publish_unknown,
    require_creator_platforms_enabled,
    resolve_attributed_party,
    resolve_edition_address,
    settle_publish,
)
from runtime.blockchain.web3_manager import (
    Web3Manager,
    is_placeholder_value,
    not_deployed_response,
)

logger = logging.getLogger(__name__)

# Canonical documented protocol base URLs (overridable via per-platform config).
# Sound.xyz public API (GraphQL). ref: https://docs.sound.xyz (api.sound.xyz/graphql)
_DEFAULT_SOUND_ENDPOINT = "https://api.sound.xyz/graphql"
# 21-G. THERE IS NO DEFAULT MIRROR ENDPOINT, AND THERE MUST NOT BE.
#
# The paragraph that stood here said "The platform must configure its Mirror/AR
# publishing gateway endpoint" and the NEXT LINE supplied a default so that it
# did not have to — `_DEFAULT_MIRROR_ENDPOINT = "https://arweave.net"`. §AM.3
# in its purest form: the comment named the requirement and the code below it
# removed the requirement.
#
# The consequence is not a wrong URL. `publish_mirror_post` sends
# `Authorization: Bearer <mirror_api_key>` to whatever this resolves to.
# MEASURED with the request intercepted locally, zero-config:
#
#     mirror     -> arweave.net         credential sent: True   NOT THE ISSUER
#     paragraph  -> api.paragraph.xyz   credential sent: True   issuer
#     sound      -> api.sound.xyz       credential sent: True   issuer
#
# Only Mirror had the mismatch — the other two defaults ARE the credential's
# issuer, which is the correct shape and the reason this is a specific defect
# rather than a general one. arweave.net is a public gateway that never issued
# this credential, has no relationship to it, and does not use Bearer auth: it
# would simply receive and log it.
#
# A DEFAULT ENDPOINT FOR A CREDENTIALED REQUEST IS A DECISION ABOUT WHO
# RECEIVES THE CREDENTIAL. That decision cannot have a convenience default,
# because the failure mode is disclosure to a third party rather than an
# error the operator sees. `publish_mirror_post` now REFUSES until an operator
# names the gateway, and the refusal names the key.
_MIRROR_ENDPOINT_KEY = "services.creator_platforms.mirror_endpoint"
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
        ``sound_handle`` / ``release_id`` (API path).

        ``edition_address`` IS NO LONGER A CALLER OVERRIDE (21-B). It is read
        from ``services.creator_platforms.sound_edition_address``. It selects
        which contract the PLATFORM PAYMASTER signs against and it is also the
        on-chain/off-chain branch selector, so a caller-supplied value both
        redirected the platform's signature and switched on on-chain signing
        for an operator who had configured API access only.
        """
        refusal = require_creator_platforms_enabled(
            self.service_name, self._config, "mint_sound")
        if refusal is not None:
            return refusal
        cfg = self._cfg()
        # 21-B. Config ONLY. This value is also the branch selector below, so a
        # caller-supplied address both redirected the platform's signature and
        # switched on on-chain signing for an operator who configured API
        # access only.
        try:
            edition_address = resolve_edition_address(
                params, cfg.get("sound_edition_address") or "")
        except PermissionError as exc:   # 21-E — RETURN so the refusal is recorded
            return refusal_response(self.service_name, "mint_sound", exc)

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
            # 21-K. See require_mint_quantity: `or 1` made 0 mint one, and
            # nothing bounded a caller-directed, platform-paid spend.
            try:
                quantity = require_mint_quantity(
                    params.get("quantity", 1),
                    int(cfg.get("max_mint_quantity", 10)),
                )
            except PermissionError as exc:
                return refusal_response(self.service_name, "mint_sound", exc)

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
            except asyncio.CancelledError:
                # 21-H. `asyncio.CancelledError` inherits from
                # BaseException, NOT Exception, so every `except Exception`
                # in this file missed it. MEASURED: the request was issued,
                # cancellation propagated, and the service returned NOTHING.
                # Not a wrong record — NO RECORD. Record it, then RE-RAISE:
                # cancellation must propagate or every caller's timeout breaks.
                log_cancelled_dispatch(
                    "mint_sound", f"chain tx via {edition_address}", self.service_name)
                raise
            except Exception as exc:  # noqa: BLE001
                # 21-E / AQ::3. §AK.2 INSIDE 21-C. 21-C built the
                # dispatched-outcome-unknown shape for exactly this and wired
                # it at BOTH publishers — and not here, on the ONE action with
                # an irreversible on-chain effect.
                #
                # `Web3Manager.send_transaction` re-raises AFTER
                # `send_raw_transaction`, which is precisely where a read
                # timeout leaves the raw tx IN THE MEMPOOL. The old branch told
                # the operator "This service requires a deployed contract, see
                # DEPLOYMENT_GUIDE.md" about a mint that may already be mining
                # and already paid for by the platform paymaster. Their natural
                # response — configure and retry — MINTS A SECOND TOKEN, and
                # the pending branch below states there is no idempotency key.
                logger.error("mint_sound on-chain mint failed: %s", exc)
                if classify_transport_fault(exc) == "unknown":
                    return {
                        "service": self.service_name,
                        "method": "mint_sound",
                        "protocol": "Sound.xyz (SoundEdition on-chain)",
                        "edition_address": edition_address,
                        "to": to, "quantity": quantity,
                        "status": "pending", "settled": False,
                        "value_moved": None, "dispatched": True,
                        "error": str(exc),
                        "disclosure": (
                            "The mint may have been BROADCAST before this "
                            "fault. It is NOT a refusal and NOT a credential "
                            "problem: a token may be minting, paid for by the "
                            "platform paymaster. Check the chain before "
                            "retrying — there is no idempotency key on this "
                            "path and a retry mints again."
                        ),
                    }
                return not_deployed_response(
                    self.service_name,
                    extra={
                        "method": "mint_sound",
                        "protocol": "Sound.xyz (SoundEdition on-chain)",
                        "edition_address": edition_address,
                        "error": f"on-chain mint failed: {exc}",
                    },
                )

            # 21-C. `send_transaction` returns on BROADCAST. Returning
            # "minted" here asserted that a token exists because a node
            # accepted a raw transaction — a REVERTED mint was
            # indistinguishable from one that worked, and "minted" is in
            # _REAL_OUTCOME_STATUSES, so the dispatcher attested it and
            # published it to the public feed as a thing that happened.
            #
            # `wait_for_receipt` has existed on Web3Manager the whole time
            # (19-C's lesson, fourth instance of the orphaned-real-mechanism
            # pattern): the evidence was collectable and was not collected.
            base = {
                "service": self.service_name,
                "protocol": "Sound.xyz (SoundEdition on-chain)",
                "edition_address": edition_address,
                "to": to,
                "quantity": quantity,
                "tx_hash": tx_hash,
                "explorer_url": self._web3.explorer_url(tx_hash),
                "gas_paid_by": "platform paymaster",
                "broadcast": True,
            }
            try:
                receipt = await self._web3.wait_for_receipt(
                    tx_hash, timeout=RECEIPT_TIMEOUT_S)
            except asyncio.CancelledError:
                # 21-H, and the WORST of the five sites: cancellation here means the
                # mint was ALREADY BROADCAST — tx_hash exists — and the wait for its
                # receipt was abandoned. Without this the platform holds no record of
                # a transaction it signed and paid for.
                log_cancelled_dispatch(
                    "mint_sound", f"broadcast tx {tx_hash}", self.service_name)
                raise
            except Exception as exc:  # noqa: BLE001 — a wait fault is UNKNOWN
                logger.warning("mint_sound: no receipt for %s: %s", tx_hash, exc)
                return {
                    **base, "status": "pending", "settled": False,
                    "value_moved": None,
                    "disclosure": (
                        "The mint was BROADCAST and no receipt was obtained "
                        "within the wait window. This is NOT a refusal and NOT "
                        "a failure — the transaction may be mined. Check the "
                        "hash. Do not retry blindly: there is no idempotency "
                        "key on this path and a retry mints again."
                    ),
                }
            if int(getattr(receipt, "status", 0) or 0) != 1:
                return {
                    **base, "status": "failed", "settled": True,
                    "value_moved": False,
                    "block_number": getattr(receipt, "blockNumber", None),
                    "disclosure": (
                        "The mint transaction was mined and REVERTED on-chain. "
                        "No token was minted. Gas was still spent."
                    ),
                }
            return {
                **base,
                "status": "minted",
                "settled": True,
                "value_moved": True,
                "block_number": getattr(receipt, "blockNumber", None),
                "gas_used": getattr(receipt, "gasUsed", None),
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
        except asyncio.CancelledError:   # 21-H
            log_cancelled_dispatch(
                "mint_sound", endpoint, self.service_name)
            raise
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

        # 21-C. THIS PATH MINTS NOTHING. It runs a GraphQL READ for release
        # metadata — and it returned `status: "ok"`, which is in
        # _REAL_OUTCOME_STATUSES, under an action named `mint_sound`. Measured:
        # `_outcome_is_real` returned True, so the dispatcher EAS-attested a
        # metadata query and published it to the public feed as a mint.
        # "metadata_only" is deliberately NOT in the real-outcome vocabulary.
        return {
            "status": "metadata_only",
            "settled": False,
            "value_moved": False,
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

        Params: ``title``, ``body`` (markdown/content).

        ``author`` AND ``publication`` ARE NO LONGER CALLER PARAMS (21-B). They
        are read from ``services.creator_platforms.mirror_author`` and
        ``.mirror_publication``. A caller supplying either gets a REFUSAL, not
        an override — Mirror entries are permanent on Arweave and the byline is
        published with the PLATFORM'S credential, so who it names is an
        operator decision. This paragraph replaces one that still advertised
        both as optional caller params AFTER 21-B began refusing them: the
        docstring named exactly the thing that had changed (§AM.3).

        Returns the REAL Arweave transaction id / entry id from the gateway.
        """
        refusal = require_creator_platforms_enabled(
            self.service_name, self._config, "publish_mirror_post")
        if refusal is not None:
            return refusal
        cfg = self._cfg()
        api_key = cfg.get("mirror_api_key") or ""
        if is_placeholder_value(api_key):
            return self._gate(
                "publish_mirror_post",
                "services.creator_platforms.mirror_api_key",
                "Mirror (mirror.xyz / Arweave)",
            )

        # 21-K. `is_placeholder_value` returns False for EVERY non-string —
        # it detects unfilled config templates, which is a different question
        # than "is this publishable text" (§I.13). Non-strings reached the
        # third-party body.
        try:
            title = require_text(params.get("title"), "title")
            content = require_text(
                params.get("body") if params.get("body") is not None
                else params.get("content"), "body")
        except PermissionError as exc:
            return refusal_response(self.service_name, "publish_mirror_post", exc)
        # 21-L / AQ::8. `is_placeholder_value` refuses any string starting
        # "your_" — correct for a CONFIG value left as a template, and WRONG
        # for user content: "your_first_post" and "Your_Guide_To_Arweave" are
        # legitimate titles and were refused as unfilled config. `require_text`
        # above already asks the consumer's question, so the config-template
        # detector no longer runs against caller content (§I.13 completed:
        # the guard was answering the config question about a content field).
        try:
            import httpx  # lazy
        except ImportError:
            return self._gate(
                "publish_mirror_post",
                "httpx (pip install httpx)",
                "Mirror (mirror.xyz / Arweave)",
            )

        # 21-G ORDERING. THE AUTHORIZATION REFUSAL RUNS BEFORE THE CONFIG
        # REFUSAL, and the reason is a regression my own test caught: once the
        # endpoint gate was added it fired FIRST, so a byline-hijack attempt
        # against an operator who had not configured `mirror_endpoint` came
        # back as "your endpoint is unset" and the hijack attempt WAS NEVER
        # RECORDED AS ONE.
        #
        # A config problem is the operator's own state; an attempted hijack is
        # someone acting against them. When both are true the second is the one
        # they need to see, and a misconfiguration must never mask it. This
        # resolution is pure — it touches no network — so running it first
        # costs nothing.
        try:   # 21-E — RETURN so the hijack attempt is recorded as a refusal
            _author = resolve_attributed_party(
                params, "author", cfg.get("mirror_author"), "author")
            _publication = resolve_attributed_party(
                params, "publication", cfg.get("mirror_publication"),
                "publication")
        except PermissionError as exc:
            return refusal_response(self.service_name, "publish_mirror_post", exc)

        # 21-G. No default: see the note at _MIRROR_ENDPOINT_KEY. Refusing is
        # the only option that cannot disclose the credential.
        endpoint = cfg.get("mirror_endpoint") or ""
        if is_placeholder_value(endpoint):
            return self._gate(
                "publish_mirror_post",
                _MIRROR_ENDPOINT_KEY,
                "Mirror (mirror.xyz / Arweave)",
                extra={"reason": (
                    "There is deliberately no default Mirror endpoint. This "
                    "request would send the platform's Mirror credential as a "
                    "Bearer token to whatever host it resolved to, so the host "
                    "must be an explicit operator decision. Point this at your "
                    "Mirror/Arweave publishing gateway — the party that ISSUED "
                    "the credential in services.creator_platforms.mirror_api_key."
                )},
            )
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
        # 21-B. `author` is the BYLINE and Mirror entries are stored
        # PERMANENTLY ON ARWEAVE. Caller-supplied, it let one caller publish
        # under another party's name, irreversibly, on a third-party platform,
        # to readers who cannot see this platform's internal records.
        payload = {
            "title": title,
            "body": content,
            "author": _author, "publication": _publication,
        }
        # 21-L / regions::7. `.rstrip` sits OUTSIDE the try, so a non-string
        # `mirror_endpoint` in config raised AttributeError straight past this
        # service's own error handling and out to the dispatcher — 21-D's
        # lesson at a second site: a config we cannot read is a config that
        # did not configure this, and that is a refusal, not a crash.
        if not isinstance(endpoint, str):
            return self._gate(
                "publish_mirror_post",
                "services.creator_platforms.mirror_endpoint",
                "publish_mirror_post",
                extra={"reason": (
                    f"mirror_endpoint must be a URL string, got "
                    f"{type(endpoint).__name__} {endpoint!r}."
                )},
            )
        url = endpoint.rstrip("/") + "/tx"
        try:
            async with httpx.AsyncClient(timeout=_HTTP_TIMEOUT) as client:
                resp = await client.post(url, headers=headers, json=payload)
                resp.raise_for_status()
                body = resp.json() if resp.content else {}
        except asyncio.CancelledError:   # 21-H
            log_cancelled_dispatch(
                "publish_mirror_post", url, self.service_name)
            raise
        except Exception as exc:  # noqa: BLE001
            # 21-C, THE UNDER-CLAIM HALF. This returned the CREDENTIAL-GATED
            # refusal shape for a fault that may have occurred AFTER the POST
            # reached Mirror — telling an operator to go configure an API key
            # about a post that may be live on Arweave forever.
            logger.error("publish_mirror_post failed: %s", exc)
            # 21-E. The exception TYPE carries the answer and 21-C never read
            # it, so BOTH errors were manufactured at this one site: a proven
            # non-dispatch (connection refused, DNS failure, an unserialisable
            # caller param) was reported as "may be live", and a 4xx — the
            # strongest evidence the gateway received it and stored nothing —
            # was reported as unknown, discarding the credential diagnosis.
            _base = {
                "service": self.service_name,
                "method": "publish_mirror_post",
                "protocol": "Mirror (mirror.xyz / Arweave)",
                "title": title,
            }
            _kind = classify_transport_fault(exc)
            if _kind == "not_sent":
                return publish_not_sent(base=_base, endpoint=url, exc=exc)
            if _kind == "rejected":
                return publish_rejected(
                    base=_base, endpoint=url, exc=exc,
                    missing="services.creator_platforms.mirror_api_key")
            return publish_unknown(base=_base, endpoint=url, exc=exc)

        arweave_id = None
        if isinstance(body, dict):
            arweave_id = body.get("id") or body.get("transactionId") or body.get("arweaveTxId")
        # 21-C. "published" was asserted on ANY 2xx, without reading whether
        # the gateway named anything. A record claiming a permanent Arweave
        # entry exists, carrying `arweave_tx_id: None`, points at nothing.
        return settle_publish(
            base={
                "service": self.service_name,
                "protocol": "Mirror (mirror.xyz / Arweave)",
                "title": title,
                "endpoint": url,
                "published_by": "platform Mirror publishing account",
            },
            id_value=arweave_id, id_field="arweave_tx_id", response_body=body,
        )

    # ── Paragraph (paragraph.xyz) ─────────────────────────────────────

    async def publish_paragraph_post(self, **params: Any) -> dict:
        """Publish a Paragraph (paragraph.xyz) post via the Paragraph publishing API.

        Uses the platform's Paragraph API key. The platform's own publishing account
        is used — no user wallet is signed with and no user funds are moved.

        Params: ``title``, ``body`` (markdown/content); optional ``subtitle``.

        ``publication`` IS NO LONGER A CALLER PARAM (21-B) — it is read from
        ``services.creator_platforms.paragraph_publication``. A caller
        supplying a different value gets a REFUSAL.

        Returns the REAL post id / URL from the Paragraph API.
        """
        refusal = require_creator_platforms_enabled(
            self.service_name, self._config, "publish_paragraph_post")
        if refusal is not None:
            return refusal
        cfg = self._cfg()
        api_key = cfg.get("paragraph_api_key") or ""
        if is_placeholder_value(api_key):
            return self._gate(
                "publish_paragraph_post",
                "services.creator_platforms.paragraph_api_key",
                "Paragraph (paragraph.xyz)",
            )

        # 21-K. `is_placeholder_value` returns False for EVERY non-string —
        # it detects unfilled config templates, which is a different question
        # than "is this publishable text" (§I.13). Non-strings reached the
        # third-party body.
        try:
            title = require_text(params.get("title"), "title")
            content = require_text(
                params.get("body") if params.get("body") is not None
                else params.get("content"), "body")
        except PermissionError as exc:
            return refusal_response(self.service_name, "publish_paragraph_post", exc)
        # 21-L / AQ::8. `is_placeholder_value` refuses any string starting
        # "your_" — correct for a CONFIG value left as a template, and WRONG
        # for user content: "your_first_post" and "Your_Guide_To_Arweave" are
        # legitimate titles and were refused as unfilled config. `require_text`
        # above already asks the consumer's question, so the config-template
        # detector no longer runs against caller content (§I.13 completed:
        # the guard was answering the config question about a content field).
        # 21-B. A caller-supplied `publication` OVERRODE the operator's
        # configured one, aiming the platform's Paragraph credential at any
        # publication the caller named.
        try:   # 21-E
            publication = resolve_attributed_party(
                params, "publication", cfg.get("paragraph_publication") or "",
                "publication") or ""
        except PermissionError as exc:
            return refusal_response(
                self.service_name, "publish_paragraph_post", exc)
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
        # 21-L / regions::7. `.rstrip` sits OUTSIDE the try, so a non-string
        # `paragraph_endpoint` in config raised AttributeError straight past this
        # service's own error handling and out to the dispatcher — 21-D's
        # lesson at a second site: a config we cannot read is a config that
        # did not configure this, and that is a refusal, not a crash.
        if not isinstance(endpoint, str):
            return self._gate(
                "publish_paragraph_post",
                "services.creator_platforms.paragraph_endpoint",
                "publish_paragraph_post",
                extra={"reason": (
                    f"paragraph_endpoint must be a URL string, got "
                    f"{type(endpoint).__name__} {endpoint!r}."
                )},
            )
        url = endpoint.rstrip("/") + "/v1/posts"
        try:
            async with httpx.AsyncClient(timeout=_HTTP_TIMEOUT) as client:
                resp = await client.post(url, headers=headers, json=payload)
                resp.raise_for_status()
                body = resp.json() if resp.content else {}
        except asyncio.CancelledError:   # 21-H
            log_cancelled_dispatch(
                "publish_paragraph_post", url, self.service_name)
            raise
        except Exception as exc:  # noqa: BLE001
            logger.error("publish_paragraph_post failed: %s", exc)
            # 21-E. The exception TYPE carries the answer and 21-C never read
            # it, so BOTH errors were manufactured at this one site: a proven
            # non-dispatch (connection refused, DNS failure, an unserialisable
            # caller param) was reported as "may be live", and a 4xx — the
            # strongest evidence the gateway received it and stored nothing —
            # was reported as unknown, discarding the credential diagnosis.
            _base = {
                "service": self.service_name,
                "method": "publish_paragraph_post",
                "protocol": "Paragraph (paragraph.xyz)",
                "title": title,
            }
            _kind = classify_transport_fault(exc)
            if _kind == "not_sent":
                return publish_not_sent(base=_base, endpoint=url, exc=exc)
            if _kind == "rejected":
                return publish_rejected(
                    base=_base, endpoint=url, exc=exc,
                    missing="services.creator_platforms.paragraph_api_key")
            return publish_unknown(base=_base, endpoint=url, exc=exc)

        post_id = None
        post_url = None
        if isinstance(body, dict):
            post_id = body.get("id") or body.get("postId")
            post_url = body.get("url") or body.get("postUrl")
        return settle_publish(   # 21-C
            base={
                "service": self.service_name,
                "protocol": "Paragraph (paragraph.xyz)",
                "title": title,
                "publication": publication,
                "post_url": post_url,
                "endpoint": url,
                "published_by": "platform Paragraph publishing account",
            },
            id_value=post_id, id_field="post_id", response_body=body,
        )
