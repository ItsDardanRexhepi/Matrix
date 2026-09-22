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
when the caller has explicitly opted into a real on-chain operation, and
``BalanceUnavailable`` (a ``RuntimeError``) from ``get_balance_eth`` when no
balance was read, because a 0.0 there is indistinguishable from an empty wallet.
"""

from __future__ import annotations

import asyncio
import re
import time
import logging
from collections.abc import Mapping
from typing import Any, Optional

#: 21-S. How long a single blocking receipt poll may occupy a worker thread.
#: Bounds the thread orphaned by a cancellation; it does not shorten the wait.
_RECEIPT_POLL_SLICE_S = 5

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

    #: The sponsorship action a transaction sent through this manager is metered
    #: under when its caller names none. A deployment that configures
    #: ``paymaster.policy.allowed_actions`` must list it.
    DEFAULT_SIGNING_ACTION = "web3.send_transaction"

    def get_account(self):
        """The platform account as a HANDLE — its address, not a signer.

        This returned ``unmetered_platform_signer(key, "web3.platform_account")``,
        and that exemption's stated justification was that "every USE of it is a
        call site metered on its own". None was. `send_transaction` below signed
        with it, and `send_transaction` is the only signing path the 45 services
        in `services/**` have, so every platform signature they produce was
        exempt from the D-045 cap the repo documents as enforced. The
        exemption's claim was the whole of its argument and nothing checked it.

        35 call sites want `.address` for a transaction's `from`, and those are
        unchanged. A signature now comes from `signer()`, which is metered.
        """
        if self._account is not None:
            return self._account
        if is_placeholder_value(self.paymaster_key):
            raise RuntimeError("paymaster_private_key is not configured")
        try:
            from runtime.blockchain.sponsorship import platform_address
        except ImportError as exc:
            raise RuntimeError("eth-account is not installed") from exc
        try:
            self._account = platform_address(self.paymaster_key)
        except Exception as exc:  # noqa: BLE001
            raise RuntimeError(f"Invalid paymaster private key: {exc}") from exc
        return self._account

    async def signer(self, action: str | None = None):
        """A METERED signer for one platform operation.

        The same door `runtime/blockchain/*.py` already went through
        (`_platform_signer`), now open to `services/**` as well. `action` is
        `<capability>.<method>` and is what the allowlist and the per-identity
        ledger record; the caller identity comes from the ContextVar the tool
        dispatcher and the HTTP entry bind.

        With no `daily_cap_usd` configured this behaves exactly as before —
        `MeteredSigner` signs straight through. With one configured it prices
        the transaction and refuses rather than sign what it cannot meter.
        """
        if is_placeholder_value(self.paymaster_key):
            raise RuntimeError("paymaster_private_key is not configured")
        from runtime.blockchain.sponsorship import platform_signer
        return await platform_signer(
            self.config, action or self.DEFAULT_SIGNING_ACTION,
            key=self.paymaster_key)

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

    async def send_transaction(self, tx: dict, *, action: str | None = None) -> str:
        """Sign *tx* with the paymaster key, broadcast, and return the tx hash hex.

        Handles nonce management automatically. Caller may pass any subset
        of standard transaction fields; missing ``nonce``, ``chainId``,
        ``from``, ``gas``, ``gasPrice`` will be filled in.

        THE SIGNATURE IS METERED. This signed with `get_account()`, which was an
        UNMETERED exemption, so the D-045 daily cap saw none of the 35 service
        call sites that reach this method. `action` names the operation for the
        allowlist and the ledger; it defaults to `DEFAULT_SIGNING_ACTION` so a
        call site that has nothing more specific to say is still metered rather
        than exempt. The signer is built BEFORE the nonce lock — its price quote
        is a network round trip that has no business serialising every sender,
        and a cap denial that happens out here never takes a nonce at all. The
        reservation itself is taken at `sign_transaction`, inside the lock,
        where the transaction's real gas numbers exist.
        """
        if not self.available or self.w3 is None:
            raise RuntimeError("Web3Manager not available — cannot send transaction")

        account = await self.signer(action)
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
        # The loop itself is `wait_for_receipt_on`, below, so the services that
        # build their own `Web3` wait the same way this does.
        return await wait_for_receipt_on(self.w3, tx_hash, timeout)

    def get_balance_eth(self, address: str | None = None) -> float:
        """Return the ETH balance of *address* (paymaster by default).

        Raises BalanceUnavailable when no balance was read. This returned 0.0
        both when the chain was not configured and when the RPC read failed, so
        "unreachable" and "empty wallet" were the same float: DataAggregator
        served that zero as a portfolio, and gateway/bridge.py's
        `_lookup_balance_eth`, documented as "None if unavailable", could never
        see None for a failed read. A balance is a statement about money; one
        nobody read is not zero.

        Raises InvalidAddress, before any read and whether or not a chain is
        configured, when *address* is not a 20-byte hex address. That is the
        caller's input, not an outage: web3 used to reject it inside the try
        below, and it came out as BalanceUnavailable.
        """
        if address is not None:
            require_hex_address(address)
        if not self.available or self.w3 is None:
            raise BalanceUnavailable("blockchain not configured")
        try:
            if address is None:
                address = self.get_account().address
            wei = self.w3.eth.get_balance(self.w3.to_checksum_address(address))
            return float(self.w3.from_wei(wei, "ether"))
        except Exception as exc:
            logger.warning("get_balance_eth failed: %s", exc)
            raise BalanceUnavailable("balance read failed") from exc


async def wait_for_receipt_on(w3: Any, tx_hash: Any, timeout: int = 120):
    """Wait for *tx_hash*'s receipt on a web3 instance, off the event loop.

    `Web3Manager.wait_for_receipt` is this over its own `w3`. It is a module
    function so that a service holding a bare `Web3` — the attestation service
    and its time-critical handler build their own — waits the same way, instead
    of calling `w3.eth.wait_for_transaction_receipt` inline, which blocks the
    event loop for the whole timeout (21-I) and leaves the caller to decide what
    a wait that ran out means. Raises when no receipt arrives by the deadline.
    """
    # 21-S. THE WAIT IS SLICED BECAUSE `asyncio.to_thread` WORK IS NOT
    # CANCELLABLE. Cancelling the awaiting task frees the caller and leaves
    # the worker thread polling to completion — MEASURED: cancelled at
    # 0.4s, the thread was still running afterwards and exited only on its
    # own schedule.
    #
    # With the default 120s and the platform's own 20s batch-route ceiling,
    # every cancelled batch mint orphaned a pool thread for up to 100s.
    # Enough of them exhaust the default executor and stall every other
    # `to_thread` caller in the process — a availability failure introduced
    # by 21-I, which is itself the fix that stopped this call blocking the
    # event loop. Both facts are true: the offload was right, and it moved
    # the cost rather than removing it.
    #
    # Slicing bounds the orphan to one slice instead of the full timeout.
    # It does NOT make the thread cancellable — nothing can — so the
    # docstring says what it actually achieves.
    deadline = time.monotonic() + max(0, int(timeout or 0))
    slice_s = min(_RECEIPT_POLL_SLICE_S, max(1, int(timeout or 1)))
    last_exc: Exception | None = None
    while True:
        remaining = deadline - time.monotonic()
        if remaining <= 0:
            break
        try:
            return await asyncio.to_thread(
                w3.eth.wait_for_transaction_receipt,
                tx_hash,
                timeout=min(slice_s, remaining),
            )
        except asyncio.CancelledError:
            raise
        except Exception as exc:  # noqa: BLE001
            # A slice expiring is expected; anything else is not, but we
            # cannot reliably name web3's timeout type across versions, so
            # the DEADLINE decides and the last error is re-raised at it.
            last_exc = exc
    if last_exc is not None:
        raise last_exc
    raise TimeoutError(
        f"no receipt for {tx_hash} within {timeout}s"
    )


class RawWeb3Receipts:
    """What `settle_transaction` waits through, for a bare `Web3` instance.

    `settle_transaction` asks its first argument for `wait_for_receipt`, which a
    `Web3Manager` has and a `Web3` does not. This is the one method, over
    `wait_for_receipt_on`.
    """

    def __init__(self, w3: Any) -> None:
        self._w3 = w3

    async def wait_for_receipt(self, tx_hash: Any, timeout: int = 120):
        return await wait_for_receipt_on(self._w3, tx_hash, timeout)


class BalanceUnavailable(RuntimeError):
    """No balance was read — the chain is not configured or the RPC failed.
    The message is fixed; the underlying exception is chained, not embedded."""


class InvalidAddress(ValueError):
    """The value is not a 20-byte hex address. The caller's input (a 400), not
    a dependency failure. The message is fixed and does not repeat the value."""


# What web3's to_checksum_address accepts: 40 hex digits, optionally 0x/0X
# prefixed, in any letter case (the checksum is not verified by the read).
_HEX_ADDRESS = re.compile(r"(0[xX])?[0-9a-fA-F]{40}")


def require_hex_address(value: Any) -> str:
    """Return *value* if it is a 20-byte hex address, else raise InvalidAddress."""
    if not isinstance(value, str) or not _HEX_ADDRESS.fullmatch(value):
        raise InvalidAddress("not a 20-byte hex address")
    return value


# Standardised "not deployed" response shape used across services.
def not_deployed_response(service_name: str, extra: dict | None = None) -> dict:
    """Return the canonical not-deployed response dict for *service_name*."""
    response = {
        "status": "not_deployed",
        "service": service_name,
        "message": "This service requires a deployed contract. See contracts/DEPLOYMENT_GUIDE.md.",
        "deployment_guide": "contracts/DEPLOYMENT_GUIDE.md",
        "action_required": "Deploy contracts and add addresses to matrix.config.json",
    }
    if extra:
        response.update(extra)
    return response


# ── what a record is allowed to claim ────────────────────────────────────
#
# CLUSTER attest-money. `not_deployed_response` above is the platform's answer
# to "we cannot act at all". The two helpers here are its answers to the two
# weaker cases that were being written as successes:
#
#   recorded_unsettled_response  the platform wrote a LOCAL record and touched
#                                no contract, moved no token and took no
#                                payment. The record is real; the action is not.
#
#   settle_transaction           a node ACCEPTED a raw transaction. That is a
#                                broadcast, not a settlement, and the two are
#                                only distinguishable by a receipt.
#
# Both emit the disclosure flags `settled` / `value_moved`, which are the
# highest-priority clause in `_outcome_is_real` and in `report_of`. A service
# that omits them gets graded on its status string alone, which is how a record
# saying "purchased" over a transfer that never happened reached an EAS
# attestation and the public feed (§AP: a control whose strongest clause never
# fires because the field it reads is absent).

def recorded_unsettled_response(
    service_name: str,
    operation: str,
    extra: dict | None = None,
    *,
    disclosure: str = "",
    value_moved: bool | None = False,
) -> dict:
    """A local record exists and nothing settled on-chain.

    `recorded_unsettled` is already in the dispatcher's `_NON_OUTCOME_STATUSES`
    and in `outcome_truth._INDETERMINATE`, so this is not a new vocabulary: it
    is the word this codebase already uses for exactly this, used by the methods
    that were claiming `purchased`, `claimed` and `attested` instead.

    `value_moved` is None where the question does not arise (an attestation
    moves no value and never claimed to), False where a caller could reasonably
    have read the record as a payment.
    """
    response = {
        "status": "recorded_unsettled",
        "service": service_name,
        "operation": operation,
        "settled": False,
        "value_moved": value_moved,
        "disclosure": disclosure or (
            f"'{operation}' wrote a record on this platform and performed no "
            f"on-chain action: no contract was called, nothing was transferred "
            f"and no payment was taken. The record is not evidence that the "
            f"action occurred."
        ),
    }
    if extra:
        response.update(extra)
    return response


def unconfirmed_broadcast(tx_hash: Any, base: dict | None = None, *, note: str = "") -> dict:
    """A transaction that was SENT and that no receipt has answered for.

    The one shape for it, wherever the platform signs: `settle_transaction`
    returns it when its wait runs out, and so does every blockchain capability
    and helper that waits for its receipt through `receipt_within`. It carries
    the hash, which is what makes it checkable, and `broadcast: True` with
    `settled: False`: the dispatcher records it as a broadcast, and
    `outcome_truth.report_of` answers UNKNOWN, so outcome learning does not
    learn it in either direction.

    Before this existed a wait that ran out was an exception inside the same
    `try` as the send, and every one of those `except` clauses said the call
    failed — "Stake failed: no receipt", `{"status": "failed"}` — about a
    transaction that may be mined, and dropped the hash a caller would need to
    find out. A retry on the strength of that sends it again.
    """
    tx_hash_text = tx_hash.hex() if hasattr(tx_hash, "hex") else str(tx_hash)
    return {
        **(base or {}),
        "tx_hash": tx_hash_text,
        "broadcast": True,
        "status": "pending",
        "settled": False,
        "value_moved": None,
        "disclosure": (
            "The transaction was BROADCAST and no receipt was obtained "
            "within the wait window. This is NOT a refusal and NOT a "
            "failure — it may be mined. Check the hash before retrying."
            + (f" {note}" if note else "")
        ),
    }


async def receipt_within(w3: Any, tx_hash: Any, timeout: int = 120, *, what: str = "") -> Any:
    """The receipt of a transaction already sent, or None if none arrived.

    For code that reads more of the receipt than `settle_transaction` returns
    and answers in its own shape. Any fault in the wait is None — once the
    transaction is out, a wait that fails establishes nothing about it — and a
    caller answers None with `unconfirmed_broadcast`. Cancellation propagates.
    """
    try:
        return await wait_for_receipt_on(w3, tx_hash, timeout)
    except asyncio.CancelledError:
        raise
    except Exception as exc:  # noqa: BLE001 — a wait fault is UNKNOWN, not failure
        tx_hash_text = tx_hash.hex() if hasattr(tx_hash, "hex") else str(tx_hash)
        logger.warning("%s: no receipt for %s: %s", what or "transaction", tx_hash_text, exc)
        return None


def _receipt_field(receipt: Any, name: str) -> Any:
    """A field of a receipt, however the receipt carries it.

    web3 returns an `AttributeDict`, which answers both `receipt["status"]` and
    `receipt.status`; a plain dict answers only the first, and reading it by
    attribute gave `None` for every field — a confirmed transaction read as
    reverted. A mapping is read by key, anything else by attribute.
    """
    if isinstance(receipt, Mapping):
        return receipt.get(name)
    return getattr(receipt, name, None)


async def settle_transaction(
    web3: Any,
    tx_hash: str,
    method: str,
    service_name: str,
    base: dict | None = None,
    *,
    settled_status: str = "submitted",
    timeout: int = 120,
    note: str = "",
) -> dict:
    """Turn a broadcast into a settled, honest outcome.

    19-C established this in `services/restaking/_guards.py` and 21-C wrote it
    again inline in `services/creator_platforms/service.py`; this is the shared
    form, next to the `wait_for_receipt` it depends on. *web3* is anything with
    an async `wait_for_receipt`: a `Web3Manager`, or `RawWeb3Receipts` over a
    bare `Web3`.

        receipt.status == 1  -> *settled_status*  settled, value moved
        receipt.status == 0  -> "failed"          mined and REVERTED; nothing
                                                  moved, gas was still spent
        no receipt in time   -> "pending"         NOT a refusal and NOT a
                                                  failure. Carries the hash and
                                                  `broadcast: True`, so it stays
                                                  distinguishable from a call
                                                  that never touched the chain.

    The timeout branch is the under-claim half and it is the one that has to be
    got right: an over-claim is visible to the claimant, an under-claim is
    visible to nobody.

    A receipt that names a `contractAddress` — a deployment — adds it as
    `contract_address`. *note* is appended to the unconfirmed disclosure, for
    what a caller knows about retrying that this function does not.
    """
    out = {**(base or {}), "tx_hash": tx_hash, "broadcast": True}
    try:
        receipt = await web3.wait_for_receipt(tx_hash, timeout=timeout)
    except asyncio.CancelledError:
        logger.warning(
            "%s.%s: cancelled while waiting for the receipt of broadcast tx %s",
            service_name, method, tx_hash,
        )
        raise
    except Exception as exc:  # noqa: BLE001 — a wait fault is UNKNOWN, not failure
        logger.warning("%s.%s: no receipt for %s: %s", service_name, method, tx_hash, exc)
        return unconfirmed_broadcast(tx_hash, base, note=note)

    contract_address = _receipt_field(receipt, "contractAddress")
    if contract_address:
        out["contract_address"] = contract_address

    if int(_receipt_field(receipt, "status") or 0) != 1:
        return {
            **out,
            "status": "failed",
            "settled": True,
            "value_moved": False,
            "block_number": _receipt_field(receipt, "blockNumber"),
            "disclosure": (
                "The transaction was mined and REVERTED on-chain. Nothing "
                "moved. Gas was still spent."
            ),
        }

    return {
        **out,
        "status": settled_status,
        "settled": True,
        "value_moved": True,
        "block_number": _receipt_field(receipt, "blockNumber"),
        "gas_used": _receipt_field(receipt, "gasUsed"),
    }
