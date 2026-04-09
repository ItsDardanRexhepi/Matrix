"""
Web3Manager — shared web3 connection manager for the platform.

A single instance is shared across services. It is responsible for:

- Holding a configured ``web3.Web3`` HTTP provider connection.
- Reporting whether blockchain execution is currently available
  (RPC reachable, paymaster key configured, etc.).
- Signing and broadcasting transactions on behalf of services using
  the platform paymaster account.
- Loading contract instances from address + ABI pairs.
- Detecting placeholder values in config so services can fall back to
  honest "not_deployed" responses instead of fabricating data.

Web3Manager never raises an unhandled exception from public methods —
errors are caught, logged, and surfaced as boolean availability or
explicit ``RuntimeError`` from ``get_account``/``send_transaction``
when the caller has explicitly opted into a real on-chain operation.
"""

from __future__ import annotations

import asyncio
import logging
from typing import Any, Optional

logger = logging.getLogger(__name__)


def is_placeholder_value(value: Any) -> bool:
    """Return True if *value* is empty or looks like a config placeholder."""
    if value is None:
        return True
    if not isinstance(value, str):
        return False
    stripped = value.strip()
    if not stripped:
        return True
    return stripped.startswith("YOUR_") or stripped.upper().startswith("YOUR_")


class Web3Manager:
    """Singleton-style shared web3 connection manager.

    Parameters
    ----------
    config : dict
        Top-level platform config. Reads from the ``blockchain`` sub-dict.
    """

    _instance: Optional["Web3Manager"] = None

    def __init__(self, config: dict | None = None):
        self.config = config or {}
        bc = self.config.get("blockchain", {}) if isinstance(self.config, dict) else {}

        self.rpc_url: str = bc.get("rpc_url", "") or ""
        self.chain_id: int = int(bc.get("chain_id", 84532) or 84532)
        self.platform_wallet: str = bc.get("platform_wallet", "") or ""
        self.paymaster_key: str = (
            bc.get("paymaster_private_key")
            or bc.get("paymaster_key")
            or ""
        )
        self.eas_contract: str = bc.get("eas_contract", "") or ""
        self.eas_schema: str = bc.get("eas_schema", "") or ""
        self.network: str = bc.get("network", "base-sepolia") or "base-sepolia"

        self.w3 = None
        self.available: bool = False
        self._account = None
        self._nonce_lock = asyncio.Lock()

        if is_placeholder_value(self.rpc_url):
            logger.info("Web3Manager: rpc_url not configured — running in offline mode")
            return

        try:
            from web3 import Web3
        except ImportError:
            logger.warning("Web3Manager: web3 package not installed — offline mode")
            return

        try:
            provider = Web3.HTTPProvider(self.rpc_url, request_kwargs={"timeout": 10})
            self.w3 = Web3(provider)
            if self.w3.is_connected():
                self.available = True
                logger.info("Web3Manager: connected to %s (chain_id=%s)", self.rpc_url, self.chain_id)
            else:
                logger.warning("Web3Manager: cannot reach RPC at %s — offline mode", self.rpc_url)
        except Exception as exc:  # noqa: BLE001 — never raise from constructor
            logger.warning("Web3Manager: failed to initialise web3 (%s) — offline mode", exc)
            self.w3 = None
            self.available = False

    # ── Public helpers ────────────────────────────────────────────

    @classmethod
    def get_shared(cls, config: dict | None = None) -> "Web3Manager":
        """Return the process-wide shared Web3Manager, creating it if needed."""
        if cls._instance is None:
            cls._instance = Web3Manager(config or {})
        return cls._instance

    @classmethod
    def reset_shared(cls) -> None:
        """Reset the shared singleton (used by tests)."""
        cls._instance = None

    def is_placeholder(self, value: Any) -> bool:
        """Return True if *value* is empty or looks like a config placeholder."""
        return is_placeholder_value(value)

    def explorer_url(self, tx_hash: str) -> str:
        """Return the Base Sepolia (or matching network) block-explorer URL."""
        base = "https://sepolia.basescan.org/tx/"
        if self.network and "mainnet" in self.network.lower():
            base = "https://basescan.org/tx/"
        return f"{base}{tx_hash}"

    def get_account(self):
        """Return an ``eth_account.LocalAccount`` for the configured paymaster key."""
        if self._account is not None:
            return self._account
        if is_placeholder_value(self.paymaster_key):
            raise RuntimeError("paymaster_private_key is not configured")
        try:
            from eth_account import Account
        except ImportError as exc:
            raise RuntimeError("eth-account is not installed") from exc
        try:
            self._account = Account.from_key(self.paymaster_key)
        except Exception as exc:  # noqa: BLE001
            raise RuntimeError(f"Invalid paymaster private key: {exc}") from exc
        return self._account

    def load_contract(self, address: str, abi: list):
        """Return a web3 ``Contract`` instance for *address* with *abi*."""
        if not self.available or self.w3 is None:
            raise RuntimeError("Web3Manager not available")
        if is_placeholder_value(address):
            raise ValueError(f"Contract address looks like a placeholder: {address!r}")
        try:
            checksum = self.w3.to_checksum_address(address)
        except Exception as exc:
            raise ValueError(f"Invalid contract address {address!r}: {exc}") from exc
        return self.w3.eth.contract(address=checksum, abi=abi)

    async def send_transaction(self, tx: dict) -> str:
        """Sign *tx* with the paymaster key, broadcast, and return the tx hash hex.

        Handles nonce management automatically. Caller may pass any subset
        of standard transaction fields; missing ``nonce``, ``chainId``,
        ``from``, ``gas``, ``gasPrice`` will be filled in.
        """
        if not self.available or self.w3 is None:
            raise RuntimeError("Web3Manager not available — cannot send transaction")

        account = self.get_account()
        async with self._nonce_lock:
            try:
                tx_to_sign = dict(tx)
                tx_to_sign.setdefault("from", account.address)
                tx_to_sign.setdefault("chainId", self.chain_id)
                if "nonce" not in tx_to_sign:
                    tx_to_sign["nonce"] = self.w3.eth.get_transaction_count(account.address)
                if "gasPrice" not in tx_to_sign and "maxFeePerGas" not in tx_to_sign:
                    tx_to_sign["gasPrice"] = self.w3.eth.gas_price
                if "gas" not in tx_to_sign:
                    try:
                        tx_to_sign["gas"] = int(self.w3.eth.estimate_gas(tx_to_sign) * 1.2)
                    except Exception:
                        tx_to_sign["gas"] = 500_000

                signed = account.sign_transaction(tx_to_sign)
                raw = getattr(signed, "rawTransaction", None) or getattr(signed, "raw_transaction", None)
                tx_hash = self.w3.eth.send_raw_transaction(raw)
                return tx_hash.hex() if hasattr(tx_hash, "hex") else str(tx_hash)
            except Exception as exc:
                logger.error("Web3Manager.send_transaction failed: %s", exc)
                raise

    async def wait_for_receipt(self, tx_hash: str, timeout: int = 120):
        """Wait for a transaction receipt. Returns the receipt or raises."""
        if not self.available or self.w3 is None:
            raise RuntimeError("Web3Manager not available")
        return self.w3.eth.wait_for_transaction_receipt(tx_hash, timeout=timeout)

    def get_balance_eth(self, address: str | None = None) -> float:
        """Return the ETH balance of *address* (paymaster by default)."""
        if not self.available or self.w3 is None:
            return 0.0
        try:
            if address is None:
                address = self.get_account().address
            wei = self.w3.eth.get_balance(self.w3.to_checksum_address(address))
            return float(self.w3.from_wei(wei, "ether"))
        except Exception as exc:
            logger.warning("get_balance_eth failed: %s", exc)
            return 0.0


# Standardised "not deployed" response shape used across services.
def not_deployed_response(service_name: str, extra: dict | None = None) -> dict:
    """Return the canonical not-deployed response dict for *service_name*."""
    response = {
        "status": "not_deployed",
        "service": service_name,
        "message": "This service requires a deployed contract. See contracts/DEPLOYMENT_GUIDE.md.",
        "deployment_guide": "contracts/DEPLOYMENT_GUIDE.md",
        "action_required": "Deploy contracts and add addresses to openmatrix.config.json",
    }
    if extra:
        response.update(extra)
    return response
