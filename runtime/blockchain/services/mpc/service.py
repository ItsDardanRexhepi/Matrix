"""
Multi-party computation, threshold signatures, social recovery, session keys.

Real protocol integration. Each method gates on the specific credential it
needs (CREDENTIAL-GATED, testable) and otherwise performs the real protocol
operation (UNVERIFIED — requires the MPC node account / a deployed recovery
or session-key module on testnet to prove).

Two integration surfaces, selected per-method by which config key is present:

* On-chain modules (``recover_wallet``, ``create_session_key``) — a smart-account
  recovery / session-key module the USER has already authorized on their
  account abstraction wallet (e.g. a guardian/recovery module, or an ERC-4337
  session-key validator). The platform paymaster only SPONSORS the gas of the
  module call; the authorization to act on the user account comes from the
  user-installed module, never from the server holding user keys.

* Off-chain MPC node API (``mpc_sign``) — a threshold-signature node cluster
  (``cfg.endpoint`` + ``cfg.api_key``). The server coordinates a signing
  request against the user's MPC key shares held by the node cluster; the
  server never possesses a full private key.

NON-CUSTODIAL: the server NEVER holds or moves a user's wallet funds. The only
key the server signs with is the platform paymaster account, used solely to pay
gas for module calls that the user's own on-chain module authorizes.

Config keys (under ``services.mpc``):
    endpoint            — MPC node cluster base URL (off-chain threshold signing)
    api_key             — MPC node API key
    module_address      — generic module address fallback
    recovery_module     — social-recovery module contract address
    session_key_module  — session-key validator/module contract address
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


# ── Minimal ABIs (only the single function each method invokes) ───────────────
# UNVERIFIED: these signatures follow common social-recovery / session-key
# module conventions (Safe-style modules, ERC-4337 session-key validators) but
# the exact module deployed by the operator must match. Confirm against the
# configured module before relying on the write path.

# Social-recovery module: kick off recovery of `account` to `newOwner`.
RECOVERY_MODULE_ABI = [
    {
        "name": "initiateRecovery",
        "type": "function",
        "stateMutability": "nonpayable",
        "inputs": [
            {"name": "account", "type": "address"},
            {"name": "newOwner", "type": "address"},
        ],
        "outputs": [{"name": "recoveryId", "type": "bytes32"}],
    }
]

# Session-key module: register a scoped session key on `account`.
SESSION_KEY_MODULE_ABI = [
    {
        "name": "registerSessionKey",
        "type": "function",
        "stateMutability": "nonpayable",
        "inputs": [
            {"name": "account", "type": "address"},
            {"name": "sessionKey", "type": "address"},
            {"name": "validUntil", "type": "uint48"},
        ],
        "outputs": [],
    }
]


class MPCService:
    """Multi-party computation, threshold signatures, social recovery, session keys."""

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

    # ── Social recovery (on-chain user-authorized module) ────────────────────

    async def recover_wallet(self, **params: Any) -> dict:
        """Initiate social recovery of a user smart account via its recovery module.

        The platform paymaster only SPONSORS the gas of the module call. The
        authority to recover the account comes from the recovery module the user
        installed on their own smart account — the server never holds user keys
        and never moves user funds.

        Params: ``account`` (user smart account), ``new_owner`` (recovered owner).
        """
        cfg = self._cfg()
        module = cfg.get("recovery_module") or cfg.get("module_address") or ""

        if not self._web3.available:
            return not_deployed_response(self.service_name, extra={
                "method": "recover_wallet",
                "missing": "blockchain.rpc_url (RPC unreachable)",
                "protocol": "on-chain social-recovery module",
            })
        if is_placeholder_value(module):
            return not_deployed_response(self.service_name, extra={
                "method": "recover_wallet",
                "missing": "services.mpc.recovery_module",
                "protocol": "on-chain social-recovery module",
            })

        account = params.get("account") or params.get("wallet")
        new_owner = params.get("new_owner") or params.get("owner")
        if is_placeholder_value(account) or is_placeholder_value(new_owner):
            return not_deployed_response(self.service_name, extra={
                "method": "recover_wallet",
                "missing": "params.account and params.new_owner",
                "protocol": "on-chain social-recovery module",
            })

        try:
            contract = self._web3.load_contract(module, RECOVERY_MODULE_ABI)
            acct = self._web3.w3.to_checksum_address(account)
            owner = self._web3.w3.to_checksum_address(new_owner)
            tx = contract.functions.initiateRecovery(acct, owner).build_transaction({
                "from": self._web3.get_account().address,
                "chainId": self._web3.chain_id,
            })
            tx_hash = await self._web3.send_transaction(tx)
            return {
                "status": "submitted",
                "service": self.service_name,
                "method": "recover_wallet",
                "account": account,
                "new_owner": new_owner,
                "module": module,
                "tx_hash": tx_hash,
                "explorer_url": self._web3.explorer_url(tx_hash),
                "custody": "non-custodial: recovery authorized by user-installed module; platform only sponsors gas",
            }
        except Exception as exc:  # noqa: BLE001
            logger.error("recover_wallet failed: %s", exc)
            return {
                "status": "error",
                "service": self.service_name,
                "method": "recover_wallet",
                "error": str(exc),
                "protocol": "on-chain social-recovery module",
            }

    # ── Session keys (on-chain user-authorized module) ───────────────────────

    async def create_session_key(self, **params: Any) -> dict:
        """Register a scoped, time-bounded session key on a user smart account.

        Registers ``session_key`` on the user's account via the session-key
        validator/module the user installed. The platform paymaster only
        SPONSORS the gas; the server never holds the user's root key and the
        session key's scope/expiry are enforced on-chain by the module.

        Params: ``account`` (user smart account), ``session_key`` (the key to
        authorize), optional ``valid_until`` (unix ts; default now+1h).
        """
        cfg = self._cfg()
        module = cfg.get("session_key_module") or cfg.get("module_address") or ""

        if not self._web3.available:
            return not_deployed_response(self.service_name, extra={
                "method": "create_session_key",
                "missing": "blockchain.rpc_url (RPC unreachable)",
                "protocol": "on-chain session-key module (ERC-4337 validator)",
            })
        if is_placeholder_value(module):
            return not_deployed_response(self.service_name, extra={
                "method": "create_session_key",
                "missing": "services.mpc.session_key_module",
                "protocol": "on-chain session-key module (ERC-4337 validator)",
            })

        account = params.get("account") or params.get("wallet")
        session_key = params.get("session_key") or params.get("key")
        if is_placeholder_value(account) or is_placeholder_value(session_key):
            return not_deployed_response(self.service_name, extra={
                "method": "create_session_key",
                "missing": "params.account and params.session_key",
                "protocol": "on-chain session-key module (ERC-4337 validator)",
            })

        import time
        valid_until = int(params.get("valid_until") or (time.time() + 3600))

        try:
            contract = self._web3.load_contract(module, SESSION_KEY_MODULE_ABI)
            acct = self._web3.w3.to_checksum_address(account)
            skey = self._web3.w3.to_checksum_address(session_key)
            tx = contract.functions.registerSessionKey(
                acct, skey, valid_until
            ).build_transaction({
                "from": self._web3.get_account().address,
                "chainId": self._web3.chain_id,
            })
            tx_hash = await self._web3.send_transaction(tx)
            return {
                "status": "submitted",
                "service": self.service_name,
                "method": "create_session_key",
                "account": account,
                "session_key": session_key,
                "valid_until": valid_until,
                "module": module,
                "tx_hash": tx_hash,
                "explorer_url": self._web3.explorer_url(tx_hash),
                "custody": "non-custodial: session key scoped on-chain by user-installed module; platform only sponsors gas",
            }
        except Exception as exc:  # noqa: BLE001
            logger.error("create_session_key failed: %s", exc)
            return {
                "status": "error",
                "service": self.service_name,
                "method": "create_session_key",
                "error": str(exc),
                "protocol": "on-chain session-key module (ERC-4337 validator)",
            }
