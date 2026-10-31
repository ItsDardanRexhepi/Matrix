"""
Multi-party computation, threshold signatures, social recovery, session keys.

* ``mpc_sign`` — an off-chain threshold-signature node cluster
  (``cfg.endpoint`` + ``cfg.api_key``). The server coordinates a signing
  request against the user's MPC key shares held by the node cluster; the
  server never possesses a full private key. It gates on the credential it
  needs (CREDENTIAL-GATED, testable) and otherwise performs the real request
  (UNVERIFIED — requires the MPC node account to prove).

* ``recover_wallet`` and ``create_session_key`` — REFUSED, before anything is
  built or signed. Each was a call on a smart-account module
  (``initiateRecovery(account, newOwner)``,
  ``registerSessionKey(account, sessionKey, validUntil)``) built from the
  request's addresses and sent from the platform's own wallet with the
  platform paymaster key. A module decides by who calls it, so the platform
  wallet was the caller whose standing authorized the call, not the account
  holder, whatever the module's name for that standing (a guardian, a
  manager); and nothing tied the account to the caller. A session reached
  both through the capability route and through chat. Recovery and a session
  key are the account's own operation, signed by its holder or its guardians;
  the paymaster can sponsor the gas of that operation, which is the only part
  of it the platform's key may sign. (runtime/access_policy.py
  REFUSED_ON_REQUEST refuses both at every door too.)

Config keys (under ``services.mpc``):
    endpoint            — MPC node cluster base URL (off-chain threshold signing)
    api_key             — MPC node API key
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


class MPCService:
    """Threshold (MPC) signing through a node cluster; recovery and session keys refused."""

    service_name = "mpc"

    def __init__(self, config: dict) -> None:
        self._config = config
        self._web3 = Web3Manager.get_shared(config)
        self._gas_sponsor = None  # lazy — only instantiated when needed

    def _sponsor(self):
        if self._gas_sponsor is None:
            from runtime.blockchain.gas_sponsor import GasSponsor
            self._gas_sponsor = GasSponsor(self._config)
        return self._gas_sponsor

    def _cfg(self) -> dict:
        return self._config.get("services", {}).get(self.service_name, {}) or {}

    # ── Threshold / MPC signing (off-chain node cluster) ─────────────────────

    async def mpc_sign(self, **params: Any) -> dict:
        """Request a threshold (MPC) signature over a message digest.

        Coordinates a signing request against the user's MPC key shares held by
        the configured node cluster. The server holds NO full key — it only
        forwards the request and returns the cluster's signature.

        Params: ``message`` / ``digest`` (hex), ``key_id`` (the user's MPC key
        identifier in the cluster), optional ``derivation_path``.
        """
        cfg = self._cfg()
        endpoint = cfg.get("endpoint", "")
        api_key = cfg.get("api_key", "")

        if is_placeholder_value(endpoint):
            return not_deployed_response(self.service_name, extra={
                "method": "mpc_sign",
                "missing": "services.mpc.endpoint",
                "protocol": "MPC threshold-signature node cluster",
            })
        if is_placeholder_value(api_key):
            return not_deployed_response(self.service_name, extra={
                "method": "mpc_sign",
                "missing": "services.mpc.api_key",
                "protocol": "MPC threshold-signature node cluster",
            })

        digest = params.get("digest") or params.get("message")
        key_id = params.get("key_id") or params.get("key_share_id")
        if not digest or not key_id:
            return not_deployed_response(self.service_name, extra={
                "method": "mpc_sign",
                "missing": "params.digest and params.key_id",
                "protocol": "MPC threshold-signature node cluster",
            })

        try:
            import httpx  # lazy — heavy/optional dependency
        except ImportError:
            return not_deployed_response(self.service_name, extra={
                "method": "mpc_sign",
                "missing": "httpx (python package)",
                "protocol": "MPC threshold-signature node cluster",
            })

        # UNVERIFIED: request shape follows a generic MPC-node signing API.
        # Confirm path/payload against the operator's node cluster docs.
        url = endpoint.rstrip("/") + "/v1/sign"
        payload = {
            "key_id": key_id,
            "digest": digest,
            "derivation_path": params.get("derivation_path"),
        }
        try:
            async with httpx.AsyncClient(timeout=30) as client:
                resp = await client.post(
                    url,
                    json={k: v for k, v in payload.items() if v is not None},
                    headers={"Authorization": f"Bearer {api_key}"},
                )
            resp.raise_for_status()
            data = resp.json()
            return {
                "status": "ok",
                "service": self.service_name,
                "method": "mpc_sign",
                "key_id": key_id,
                "signature": data.get("signature"),
                "node_response": data,
                "custody": "non-custodial: signed by MPC node cluster key shares, not the server",
            }
        except Exception as exc:  # noqa: BLE001
            logger.error("mpc_sign request failed: %s", exc)
            return {
                "status": "error",
                "service": self.service_name,
                "method": "mpc_sign",
                "error": str(exc),
                "protocol": "MPC threshold-signature node cluster",
            }

    # ── Social recovery and session keys: refused ─────────────────────────────

    async def recover_wallet(self, **params: Any) -> dict:
        """Refused: the platform's key recovers no account a request names.

        This signed ``initiateRecovery(account, newOwner)`` on the configured
        recovery module, from the platform wallet, with both addresses the
        request's. The recovery module decides by who calls it, so what
        authorized the recovery was the platform wallet's standing with the
        module, not the account holder's: any caller could name any account
        the module covers and a new owner of its choosing. It now answers
        with a refusal before anything is built or signed. Recovery is started
        by the account's own guardians, with their own keys.
        """
        from runtime.access_policy import refused_by_the_service
        return refused_by_the_service(self.service_name, "recover_wallet")

    async def create_session_key(self, **params: Any) -> dict:
        """Refused: the platform's key registers no session key on an account
        a request names.

        This signed ``registerSessionKey(account, sessionKey, validUntil)`` on
        the configured session-key module, from the platform wallet, with the
        account, the key and the expiry all the request's. The module decides
        by who calls it, so the platform wallet's standing with the module,
        not the account holder's, authorized a key of the request's choosing
        on an account of the request's choosing. It now answers with a refusal
        before anything is built or signed. A session key is registered by the
        account itself, in an operation its holder signs.
        """
        from runtime.access_policy import refused_by_the_service
        return refused_by_the_service(self.service_name, "create_session_key")
