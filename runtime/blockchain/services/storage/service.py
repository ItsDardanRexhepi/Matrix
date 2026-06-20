"""
Filecoin storage deals, Ceramic streams, OrbitDB writes (extends IPFS/Arweave).

These are OFF-CHAIN protocol integrations (no smart-contract calls):

- ``store_filecoin``       → Lighthouse / web3.storage upload API (Filecoin deal)
- ``ceramic_stream_create``→ Ceramic node HTTP API (CeramicHTTP)
- ``orbit_db_write``       → OrbitDB write (via an OrbitDB HTTP gateway / pinning node)

Each method:
  1. Gates FIRST on the EXACT credential it needs (api_key / endpoint). When the
     credential is missing or a placeholder, it returns the canonical
     ``not_deployed_response`` (CREDENTIAL-GATED) naming the precise config key so
     CREDENTIALS_NEEDED.md can map it.
  2. When configured, performs the REAL documented protocol HTTP call and returns
     the real response (CID / stream id / entry hash). It never fabricates a CID,
     hash, or deal id.

NON-CUSTODIAL: these are content-storage operations against the platform's own
storage accounts (Lighthouse/web3.storage key, Ceramic node, OrbitDB gateway).
No user wallet is signed with and no user funds are moved server-side. Filecoin
deal payment, where applicable, is settled by the platform storage account that
owns the configured API key — never a user's wallet.

``httpx`` is imported lazily inside each method so importing this module never
requires the HTTP stack to be installed (import-safe for test collection).
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

# Canonical documented protocol base URLs (overridable via config).
# Lighthouse Filecoin/IPFS upload node — Authorization: Bearer <api_key>.
#   ref: https://docs.lighthouse.storage  (node.lighthouse.storage upload API)
_DEFAULT_LIGHTHOUSE_ENDPOINT = "https://node.lighthouse.storage/api/v0/add"
# web3.storage legacy upload API base (alternative Filecoin provider).
_DEFAULT_WEB3_STORAGE_ENDPOINT = "https://api.web3.storage/upload"
# Ceramic mainnet/clay gateway — CeramicHTTP API root. Self-host or use a node
# provider; configure cfg.ceramic_endpoint for the real node.
_DEFAULT_CERAMIC_ENDPOINT = "https://ceramic-clay.3boxlabs.com"

_HTTP_TIMEOUT = 30.0


class DecentralizedStorageService:
    """Filecoin storage deals, Ceramic streams, OrbitDB writes (extends IPFS/Arweave)."""

    service_name = "storage"

    def __init__(self, config: dict) -> None:
        self._config = config
        self._web3 = Web3Manager.get_shared(config)
        self._gas_sponsor = None  # lazy — only instantiated when needed

    def _sponsor(self):
        if self._gas_sponsor is None:
            from runtime.blockchain.gas_sponsor import GasSponsor
            self._gas_sponsor = GasSponsor(self._config)
        return self._gas_sponsor

    # ── Config helper ────────────────────────────────────────────────

    def _cfg(self) -> dict:
        """Return this service's own config sub-dict."""
        return self._config.get("services", {}).get(self.service_name, {})

    @staticmethod
    def _gate(method: str, missing: str, protocol: str, service_name: str) -> dict:
        """Return the canonical CREDENTIAL-GATED response naming the exact key."""
        logger.warning(
            "storage.%s called but credential '%s' (%s) is not configured",
            method, missing, protocol,
        )
        return not_deployed_response(
            service_name,
            extra={"method": method, "missing": missing, "protocol": protocol},
        )

    # ── Filecoin (Lighthouse / web3.storage) ─────────────────────────

    async def store_filecoin(self, **params: Any) -> dict:
        """Store content on Filecoin via the Lighthouse (or web3.storage) upload API.

        Params: ``content`` (str/bytes) or ``data``; optional ``filename``.

        Returns the REAL upload response (CID/Name/Size) from the provider.
        Filecoin deal settlement is paid by the platform storage account that
        owns ``services.storage.filecoin_api_key`` — never a user wallet.
        """
        cfg = self._cfg()
        # Provider selection: lighthouse (default) or web3.storage.
        provider = (cfg.get("filecoin_provider") or "lighthouse").lower()
        api_key = (
            cfg.get("filecoin_api_key")
            or cfg.get("api_key")
            or ""
        )

        # CREDENTIAL-GATED: name the exact missing key.
        if is_placeholder_value(api_key):
            return self._gate(
                "store_filecoin",
                "services.storage.filecoin_api_key",
                f"Filecoin ({provider})",
                self.service_name,
            )

        content = params.get("content")
        if content is None:
            content = params.get("data")
        if content is None:
            return not_deployed_response(
                self.service_name,
                extra={
                    "method": "store_filecoin",
                    "error": "missing required param 'content' (or 'data')",
                    "protocol": f"Filecoin ({provider})",
                },
            )
        if isinstance(content, str):
            content = content.encode("utf-8")
        filename = params.get("filename", "upload.bin")

        if provider == "web3.storage" or provider == "web3storage":
            endpoint = cfg.get("filecoin_endpoint") or _DEFAULT_WEB3_STORAGE_ENDPOINT
        else:
            endpoint = cfg.get("filecoin_endpoint") or _DEFAULT_LIGHTHOUSE_ENDPOINT

        try:
            import httpx  # lazy — keep module import-safe
        except ImportError:
            return self._gate(
                "store_filecoin",
                "httpx (pip install httpx)",
                f"Filecoin ({provider})",
                self.service_name,
            )

        # REAL upload — multipart/form-data with Bearer auth.
        # UNVERIFIED: exact field name ('file') and response shape depend on the
        # provider node; Lighthouse returns {"Name","Hash","Size"} (IPFS add shape),
        # web3.storage returns {"cid": ...}. Both are returned verbatim below.
        headers = {"Authorization": f"Bearer {api_key}"}
        files = {"file": (filename, content)}
        try:
            async with httpx.AsyncClient(timeout=_HTTP_TIMEOUT) as client:
                resp = await client.post(endpoint, headers=headers, files=files)
                resp.raise_for_status()
                body = resp.json()
        except Exception as exc:  # noqa: BLE001
            logger.error("store_filecoin upload failed: %s", exc)
            return not_deployed_response(
                self.service_name,
                extra={
                    "method": "store_filecoin",
                    "protocol": f"Filecoin ({provider})",
                    "error": f"upload failed: {exc}",
                    "endpoint": endpoint,
                },
            )

        cid = (
            body.get("Hash")
            or body.get("cid")
            or (body.get("value", {}) or {}).get("cid")
        )
        return {
            "status": "stored",
            "service": self.service_name,
            "protocol": f"Filecoin ({provider})",
            "cid": cid,
            "filename": filename,
            "endpoint": endpoint,
            "paid_by": "platform storage account",
            "provider_response": body,
        }

    # ── Ceramic streams ──────────────────────────────────────────────

    async def ceramic_stream_create(self, **params: Any) -> dict:
        """Create a Ceramic stream via the Ceramic node HTTP API (CeramicHTTP).

        Params: ``content`` (dict, the stream content/genesis payload);
        optional ``metadata`` (controllers, schema, family, tags).

        Returns the REAL stream id (``streamId``) from the configured Ceramic node.
        """
        cfg = self._cfg()
        endpoint = cfg.get("ceramic_endpoint") or ""

        # CREDENTIAL-GATED: a reachable Ceramic node endpoint is required.
        if is_placeholder_value(endpoint):
            return self._gate(
                "ceramic_stream_create",
                "services.storage.ceramic_endpoint",
                "Ceramic",
                self.service_name,
            )

        content = params.get("content")
        if content is None:
            return not_deployed_response(
                self.service_name,
                extra={
                    "method": "ceramic_stream_create",
                    "error": "missing required param 'content'",
                    "protocol": "Ceramic",
                },
            )
        metadata = params.get("metadata") or {}

        try:
            import httpx  # lazy
        except ImportError:
            return self._gate(
                "ceramic_stream_create",
                "httpx (pip install httpx)",
                "Ceramic",
                self.service_name,
            )

        # REAL stream creation against CeramicHTTP /api/v0/streams.
        # UNVERIFIED: a genesis commit normally must be DAG-CBOR encoded & signed
        # client-side (via @ceramicnetwork/http-client / DID). This posts the raw
        # genesis payload to the node; the node's response (streamId / state) is
        # returned verbatim. Signing is done by the platform-controlled DID/node,
        # never a user's wallet.
        url = endpoint.rstrip("/") + "/api/v0/streams"
        payload = {
            "type": int(params.get("stream_type", 0)),  # 0 = TileDocument (ModelInstance varies)
            "genesis": {
                "header": {
                    "controllers": metadata.get(
                        "controllers",
                        [cfg.get("ceramic_controller", "")] if cfg.get("ceramic_controller") else [],
                    ),
                    "family": metadata.get("family"),
                    "tags": metadata.get("tags", []),
                },
                "data": content,
            },
        }
        try:
            async with httpx.AsyncClient(timeout=_HTTP_TIMEOUT) as client:
                resp = await client.post(url, json=payload)
                resp.raise_for_status()
                body = resp.json()
        except Exception as exc:  # noqa: BLE001
            logger.error("ceramic_stream_create failed: %s", exc)
            return not_deployed_response(
                self.service_name,
                extra={
                    "method": "ceramic_stream_create",
                    "protocol": "Ceramic",
                    "error": f"stream create failed: {exc}",
                    "endpoint": url,
                },
            )

        return {
            "status": "created",
            "service": self.service_name,
            "protocol": "Ceramic",
            "stream_id": body.get("streamId"),
            "endpoint": url,
            "node_response": body,
        }

    # ── OrbitDB writes ───────────────────────────────────────────────

    async def orbit_db_write(self, **params: Any) -> dict:
        """Write an entry to an OrbitDB database via an OrbitDB HTTP gateway.

        Params: ``db`` (database address/name), ``key`` (optional, for kv/docs),
        ``value`` (the entry payload).

        Returns the REAL entry hash from the gateway. OrbitDB has no canonical
        public HTTP API (it is a peer-to-peer IPFS-backed datastore), so this
        requires the platform to run/configure an OrbitDB HTTP gateway endpoint.
        """
        cfg = self._cfg()
        endpoint = cfg.get("orbitdb_endpoint") or ""

        # CREDENTIAL-GATED: an OrbitDB HTTP gateway endpoint is required.
        if is_placeholder_value(endpoint):
            return self._gate(
                "orbit_db_write",
                "services.storage.orbitdb_endpoint",
                "OrbitDB",
                self.service_name,
            )

        db = params.get("db") or params.get("database")
        value = params.get("value")
        if is_placeholder_value(db) or value is None:
            return not_deployed_response(
                self.service_name,
                extra={
                    "method": "orbit_db_write",
                    "error": "missing required params 'db' and/or 'value'",
                    "protocol": "OrbitDB",
                },
            )

        try:
            import httpx  # lazy
        except ImportError:
            return self._gate(
                "orbit_db_write",
                "httpx (pip install httpx)",
                "OrbitDB",
                self.service_name,
            )

        # Optional bearer auth if the gateway is protected.
        api_key = cfg.get("orbitdb_api_key") or ""
        headers = {}
        if not is_placeholder_value(api_key):
            headers["Authorization"] = f"Bearer {api_key}"

        # REAL write against the gateway. UNVERIFIED: OrbitDB has no standard HTTP
        # spec — the path/body shape depends on the deployed gateway (e.g. the
        # orbitdb/orbit-db-http-api project uses PUT /db/{db}/put). This posts the
        # entry and returns the gateway's response (entry hash) verbatim.
        key = params.get("key")
        url = endpoint.rstrip("/") + f"/db/{db}/put"
        body_payload: Any = {"key": key, "value": value} if key is not None else value
        try:
            async with httpx.AsyncClient(timeout=_HTTP_TIMEOUT) as client:
                resp = await client.post(url, headers=headers, json=body_payload)
                resp.raise_for_status()
                body = resp.json()
        except Exception as exc:  # noqa: BLE001
            logger.error("orbit_db_write failed: %s", exc)
            return not_deployed_response(
                self.service_name,
                extra={
                    "method": "orbit_db_write",
                    "protocol": "OrbitDB",
                    "error": f"write failed: {exc}",
                    "endpoint": url,
                },
            )

        entry_hash = (
            body.get("hash")
            if isinstance(body, dict)
            else None
        ) or (body if isinstance(body, str) else None)
        return {
            "status": "written",
            "service": self.service_name,
            "protocol": "OrbitDB",
            "db": db,
            "key": key,
            "entry_hash": entry_hash,
            "endpoint": url,
            "gateway_response": body,
        }
