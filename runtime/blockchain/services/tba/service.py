"""
ERC-6551 token-bound accounts — every NFT can act as a smart wallet.

This service wires the ERC-6551 protocol (token-bound accounts) to the
platform. Two operations are exposed:

- ``create_tba`` — deploy / bind a token-bound account for an NFT via the
  canonical ERC-6551 ``Registry.createAccount(...)``.
- ``execute_as_tba`` — call ``IERC6551Account.execute(...)`` on an existing
  token-bound account so the NFT-as-wallet can act on-chain.

Both are on-chain WRITES. They are signed by the **platform paymaster
account** (via ``Web3Manager.send_transaction``) so the platform pays gas
and no user key is ever custodied server-side. Deploying / executing a TBA
is a platform-level operation; this service never moves a user's wallet
funds — ``execute_as_tba`` operates the token-bound account whose
controller is the NFT, and the call is sponsored, not user-signed.

Each method gates on its required config FIRST and returns the canonical
CREDENTIAL-GATED ``not_deployed_response`` when a credential is missing or
the chain is unreachable. The real protocol call is only attempted once the
operator has populated the relevant ``services.tba`` config keys.

Config keys (read from ``services.tba``):
    - ``registry_address``       — ERC-6551 registry (defaults to the
                                   canonical 0x0000...775758 when unset)
    - ``account_implementation`` — ERC-6551 account implementation address
                                   (REQUIRED — no canonical default)
    - ``salt``                   — bytes32 salt for deterministic accounts
                                   (defaults to zero salt)
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

# Canonical ERC-6551 registry (v0.3.1) — same address across all chains.
# https://eips.ethereum.org/EIPS/eip-6551 / https://github.com/erc6551/reference
_CANONICAL_REGISTRY = "0x000000006551c19487814612e58FE06813775758"

# bytes32 zero salt — deterministic default when the operator sets none.
_DEFAULT_SALT = "0x" + "00" * 32

# Minimal ABI for the ERC-6551 registry — only the two functions we invoke.
# Verified against the canonical reference implementation (erc6551/reference).
_REGISTRY_ABI: list[dict] = [
    {
        "type": "function",
        "name": "createAccount",
        "stateMutability": "nonpayable",
        "inputs": [
            {"name": "implementation", "type": "address"},
            {"name": "salt", "type": "bytes32"},
            {"name": "chainId", "type": "uint256"},
            {"name": "tokenContract", "type": "address"},
            {"name": "tokenId", "type": "uint256"},
        ],
        "outputs": [{"name": "account", "type": "address"}],
    },
    {
        "type": "function",
        "name": "account",
        "stateMutability": "view",
        "inputs": [
            {"name": "implementation", "type": "address"},
            {"name": "salt", "type": "bytes32"},
            {"name": "chainId", "type": "uint256"},
            {"name": "tokenContract", "type": "address"},
            {"name": "tokenId", "type": "uint256"},
        ],
        "outputs": [{"name": "account", "type": "address"}],
    },
]

# Minimal ABI for IERC6551Account.execute — the canonical execution
# entrypoint of a token-bound account. operation 0 == CALL.
# Verified against the ERC-6551 reference IERC6551Executable interface.
_ACCOUNT_ABI: list[dict] = [
    {
        "type": "function",
        "name": "execute",
        "stateMutability": "payable",
        "inputs": [
            {"name": "to", "type": "address"},
            {"name": "value", "type": "uint256"},
            {"name": "data", "type": "bytes"},
            {"name": "operation", "type": "uint8"},
        ],
        "outputs": [{"name": "result", "type": "bytes"}],
    },
]


class TokenBoundAccountService:
    """ERC-6551 token-bound accounts — every NFT can act as a smart wallet."""

    service_name = "tba"

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
        """Return this service's own config sub-dict (``services.tba``)."""
        return self._config.get("services", {}).get(self.service_name, {})

    def _registry_address(self) -> str:
        """Registry address — canonical ERC-6551 registry unless overridden."""
        addr = self._cfg().get("registry_address", "")
        if is_placeholder_value(addr):
            return _CANONICAL_REGISTRY
        return addr

    def _salt(self) -> bytes:
        """bytes32 salt — operator override or the deterministic zero salt."""
        raw = self._cfg().get("salt", "")
        if is_placeholder_value(raw):
            raw = _DEFAULT_SALT
        if isinstance(raw, str):
            return bytes.fromhex(raw[2:] if raw.startswith("0x") else raw)
        if isinstance(raw, (bytes, bytearray)):
            return bytes(raw)
        return bytes.fromhex(_DEFAULT_SALT[2:])

    async def create_tba(self, **params: Any) -> dict:
        """Deploy / bind an ERC-6551 token-bound account for an NFT.

        Params: ``token_contract`` (NFT collection address), ``token_id``,
        optional ``chain_id`` (defaults to the configured chain).

        On-chain WRITE: ``Registry.createAccount(implementation, salt,
        chainId, tokenContract, tokenId)``, signed by the platform paymaster.
        """
        token_contract = params.get("token_contract") or params.get("collection")
        token_id = params.get("token_id")
        chain_id = int(params.get("chain_id") or self._web3.chain_id)

        implementation = self._cfg().get("account_implementation", "")

        # ── CREDENTIAL-GATED gate FIRST ──────────────────────────────
        if not self._web3.available:
            return not_deployed_response(self.service_name, extra={
                "method": "create_tba",
                "missing": "blockchain.rpc_url",
                "protocol": "ERC-6551 (token-bound accounts)",
            })
        if is_placeholder_value(implementation):
            return not_deployed_response(self.service_name, extra={
                "method": "create_tba",
                "missing": "services.tba.account_implementation",
                "protocol": "ERC-6551 (token-bound accounts)",
            })
        if is_placeholder_value(token_contract) or token_id is None:
            return not_deployed_response(self.service_name, extra={
                "method": "create_tba",
                "missing": "token_contract / token_id (call params)",
                "protocol": "ERC-6551 (token-bound accounts)",
            })

        # ── REAL path: registry.createAccount(...) via platform paymaster ─
        try:
            registry_addr = self._registry_address()
            registry = self._web3.load_contract(registry_addr, _REGISTRY_ABI)
            w3 = self._web3.w3

            impl_cs = w3.to_checksum_address(implementation)
            token_cs = w3.to_checksum_address(token_contract)
            salt = self._salt()

            # Deterministic account address (view call, no gas) so we can
            # return the real account even before the receipt confirms.
            predicted_account = registry.functions.account(
                impl_cs, salt, chain_id, token_cs, int(token_id)
            ).call()

            tx = registry.functions.createAccount(
                impl_cs, salt, chain_id, token_cs, int(token_id)
            ).build_transaction({
                "from": self._web3.get_account().address,
                "chainId": self._web3.chain_id,
            })

            tx_hash = await self._web3.send_transaction(tx)
            return {
                "status": "submitted",
                "service": self.service_name,
                "method": "create_tba",
                "protocol": "ERC-6551",
                "registry": registry_addr,
                "implementation": impl_cs,
                "token_contract": token_cs,
                "token_id": int(token_id),
                "chain_id": chain_id,
                "account": predicted_account,
                "tx_hash": tx_hash,
                "explorer": self._web3.explorer_url(tx_hash),
                "gas_paid_by": "platform_paymaster",
            }
        except Exception as exc:  # noqa: BLE001
            logger.error("create_tba on-chain call failed: %s", exc)
            return {
                "status": "error",
                "service": self.service_name,
                "method": "create_tba",
                "error": str(exc),
                "error_type": type(exc).__name__,
            }

    async def execute_as_tba(self, **params: Any) -> dict:
        """Execute a call from an existing ERC-6551 token-bound account.

        Params: ``account`` (the TBA address), ``to`` (call target),
        optional ``value`` (wei, default 0), optional ``data`` (hex calldata,
        default empty), optional ``operation`` (default 0 == CALL).

        On-chain WRITE: ``IERC6551Account.execute(to, value, data,
        operation)``, signed by the platform paymaster (gas-sponsored). The
        platform never custodies a user wallet key — it operates the
        token-bound account on the platform's behalf.
        """
        account = params.get("account") or params.get("tba")
        to = params.get("to") or params.get("target")
        value = int(params.get("value") or 0)
        data = params.get("data") or "0x"
        operation = int(params.get("operation") or 0)

        # ── CREDENTIAL-GATED gate FIRST ──────────────────────────────
        if not self._web3.available:
            return not_deployed_response(self.service_name, extra={
                "method": "execute_as_tba",
                "missing": "blockchain.rpc_url",
                "protocol": "ERC-6551 (IERC6551Account.execute)",
            })
        if is_placeholder_value(account) or is_placeholder_value(to):
            return not_deployed_response(self.service_name, extra={
                "method": "execute_as_tba",
                "missing": "account / to (call params)",
                "protocol": "ERC-6551 (IERC6551Account.execute)",
            })

        # ── REAL path: IERC6551Account.execute(...) via platform paymaster ─
        try:
            w3 = self._web3.w3
            tba = self._web3.load_contract(account, _ACCOUNT_ABI)
            to_cs = w3.to_checksum_address(to)

            if isinstance(data, str):
                data_bytes = bytes.fromhex(data[2:] if data.startswith("0x") else data)
            else:
                data_bytes = bytes(data)

            tx = tba.functions.execute(
                to_cs, value, data_bytes, operation
            ).build_transaction({
                "from": self._web3.get_account().address,
                "chainId": self._web3.chain_id,
                "value": value,
            })

            tx_hash = await self._web3.send_transaction(tx)
            return {
                "status": "submitted",
                "service": self.service_name,
                "method": "execute_as_tba",
                "protocol": "ERC-6551",
                "account": w3.to_checksum_address(account),
                "to": to_cs,
                "value": value,
                "operation": operation,
                "tx_hash": tx_hash,
                "explorer": self._web3.explorer_url(tx_hash),
                "gas_paid_by": "platform_paymaster",
            }
        except Exception as exc:  # noqa: BLE001
            logger.error("execute_as_tba on-chain call failed: %s", exc)
            return {
                "status": "error",
                "service": self.service_name,
                "method": "execute_as_tba",
                "error": str(exc),
                "error_type": type(exc).__name__,
            }
