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
        self._nonce_lock = None  # lazy: created on first async use (Py3.9 has no loop in __init__)

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

    def _get_nonce_lock(self) -> asyncio.Lock:
        """Lazily create the nonce lock so __init__ doesn't need a running event
        loop (asyncio.Lock() in __init__ raises 'no current event loop' on Py 3.9)."""
        if self._nonce_lock is None:
            self._nonce_lock = asyncio.Lock()
        return self._nonce_lock

    # ── Public helpers ────────────────────────────────────────────

    @classmethod
    def get_shared(cls, config: dict | None = None) -> "Web3Manager":
        """Return the process-wide shared Web3Manager, creating it if needed.

        21-J. THE `config` ARGUMENT IS IGNORED AFTER THE FIRST CALL, and it was
        ignored SILENTLY. MEASURED with two services and two configs:

            same object returned?  True
            service A (first)      rpc=rpc-A  chain=1
            service B (asked B)    rpc=rpc-A  chain=1

        Whichever service constructs first decides the RPC, THE NETWORK and THE
        PAYMASTER KEY that every later service signs with. `creator_platforms`
        gates its mint on `self._web3.paymaster_key` — so 21-C's paymaster
        check can be reading a key that came from a different service's config,
        and a mint intended for one chain can be signed on another.

        WHAT THIS DOES AND DELIBERATELY DOES NOT DO. It does not change which
        instance is returned: making the singleton config-aware would alter
        process-wide behaviour for every service at once, which is a platform
        decision and not this domain's to make (Rule M). It makes the
        divergence LOUD. In normal operation every service is handed the same
        top-level config dict, so this is silent; it fires only when the
        configs genuinely disagree, which is exactly when someone needs to
        know.

        A silent bleed and a logged one are the same defect. Only one of them
        can be noticed.
        """
        if cls._instance is None:
            cls._instance = Web3Manager(config or {})
            return cls._instance

        if config:
            live = cls._instance
            incoming = (config.get("blockchain", {}) or {}) if isinstance(config, dict) else {}
            divergent = {
                key: (getattr(live, attr, None), incoming.get(key))
                for key, attr in (("rpc_url", "rpc_url"), ("chain_id", "chain_id"))
                if incoming.get(key) is not None
                and str(incoming.get(key)) != str(getattr(live, attr, None))
            }
            if divergent:
                logger.error(
                    "Web3Manager.get_shared IGNORED a divergent config: %s. The "
                    "process-wide instance was built by an earlier caller and "
                    "its RPC, network and PAYMASTER KEY are what every service "
                    "signs with — including this one. Fields shown as "
                    "(in-use, requested-and-ignored).",
                    divergent,
                )
        return cls._instance

    @classmethod
    def reset_shared(cls) -> None:
        """Reset the shared singleton (used by tests)."""
        cls._instance = None

    def is_placeholder(self, value: Any) -> bool:
        """Return True if *value* is empty or looks like a config placeholder."""
        return is_placeholder_value(value)

    #: chain_id -> block-explorer tx base. Only chains we can name honestly.
    _EXPLORERS: dict[int, str] = {
        1: "https://etherscan.io/tx/",
        8453: "https://basescan.org/tx/",
        84532: "https://sepolia.basescan.org/tx/",
        11155111: "https://sepolia.etherscan.io/tx/",
        137: "https://polygonscan.com/tx/",
        42161: "https://arbiscan.io/tx/",
        10: "https://optimistic.etherscan.io/tx/",
    }

    def explorer_url(self, tx_hash: str) -> str | None:
        """Return a block-explorer URL, or None when we cannot build a real one.

        21-L. THIS ALWAYS RETURNED A BASE URL, FOR EVERY CHAIN. The base was
        `sepolia.basescan.org` unless `self.network` contained "mainnet", in
        which case `basescan.org` — so a transaction on Ethereum, Polygon,
        Arbitrum or Optimism got a link to Base's explorer, where it does not
        exist. It also read `self.network`, an attribute that is not always
        set, raising AttributeError on an instance built without it.

        Combined with the unprefixed hash (register R-21.3: `.hex()` drops the
        `0x` under the installed hexbytes 1.3.1), the durable success record of
        a mint carried A LINK TO THE WRONG EXPLORER FOR A MALFORMED HASH —
        while reading as evidence that the transaction is inspectable.

        `None` is the honest answer for a chain we have no explorer for. A URL
        that does not resolve is worse than no URL: the absent field says "look
        it up yourself", and the broken one says "here is the proof" and is not.
        """
        if not tx_hash:
            return None
        h = str(tx_hash)
        if not h.startswith("0x"):
            h = "0x" + h          # R-21.3's domain consequence, fixed here
        base = self._EXPLORERS.get(int(getattr(self, "chain_id", 0) or 0))
        return f"{base}{h}" if base else None

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
        async with self._get_nonce_lock():
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
        """Wait for a transaction receipt. Returns the receipt or raises.

        21-I. THE OFFLOAD IS THE POINT. `w3.eth.wait_for_transaction_receipt`
        is SYNCHRONOUS — it polls in a loop and sleeps. This method was
        declared `async` and called it directly, with no await and no thread,
        so awaiting it BLOCKED THE ENTIRE EVENT LOOP for up to `timeout`
        seconds. An `async def` that never awaits is a function lying about
        its concurrency contract, and the signature is exactly what stops a
        caller noticing.

        THIS ENGAGEMENT INTRODUCED THE STALL. Enumerated at the time of the
        fix, `wait_for_receipt` had ZERO callers until 19-C and 21-C added the
        only two — both of them ours, both added to stop a service claiming an
        outcome it had not confirmed. The mechanism was real and orphaned; we
        called it, correctly, and in doing so activated a latent defect inside
        it.

        §AG's after-form in its sharpest version so far: not "our fix made a
        neighbour load-bearing" but "our fix ACTIVATED A LATENT DEFECT IN THE
        MECHANISM IT CALLED". A fix that reaches for an unused facility inherits
        whatever is wrong with it, and nothing about the facility's own history
        will warn you — it had no callers precisely because nobody had tested
        it.
        """
        if not self.available or self.w3 is None:
            raise RuntimeError("Web3Manager not available")
        return await asyncio.to_thread(
            self.w3.eth.wait_for_transaction_receipt, tx_hash, timeout=timeout
        )

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
