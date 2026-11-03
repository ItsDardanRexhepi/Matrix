"""
ERC-6551 token-bound accounts — every NFT can act as a smart wallet.

This service wires the ERC-6551 protocol (token-bound accounts) to the
platform. Two operations are named:

- ``create_tba`` — deploy / bind a token-bound account for an NFT via the
  canonical ERC-6551 ``Registry.createAccount(...)``. An on-chain WRITE,
  signed by the **platform paymaster account** (via
  ``Web3Manager.send_transaction``), so the platform pays gas and no user key
  is ever custodied server-side.
- ``execute_as_tba`` — REFUSED, before anything is built or signed.
  ``IERC6551Account.execute(to, value, data, operation)`` carries a call the
  request writes: its target, its calldata, a DELEGATECALL if it asks, and an
  ETH value paid from the platform's own wallet to whatever contract the
  request names as the ``account``. Signed with the platform key, that was a
  call the request composed, made in the platform's name and with its money;
  a contract at ``account`` with a payable ``execute`` kept the ETH. A
  token-bound account is executed by the NFT's holder with the holder's own
  key. (runtime/access_policy.py REFUSED_ON_REQUEST refuses it at every door
  too.)

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
        """Refused: the platform's key executes no call a request writes.

        This signed ``IERC6551Account.execute(to, value, data, operation)``
        with the platform paymaster key, from the platform wallet, with every
        argument the request's: the contract it was sent to (``account``), the
        inner call's target, calldata and operation (1 is DELEGATECALL), and an
        ETH ``value`` taken from the platform wallet. Nothing checked that
        ``account`` was a token-bound account, or one the platform may operate;
        a session reached it through the capability route and through chat.
        It now answers with a refusal before anything is built or signed. A
        token-bound account is executed by its NFT's holder, with the holder's
        own key.
        """
        from runtime.access_policy import refused_by_the_service
        return refused_by_the_service(self.service_name, "execute_as_tba")
