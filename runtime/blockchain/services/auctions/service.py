"""
Dutch, English, sealed-bid auctions and orderbook DEX primitives.

This service speaks to two real on-chain surfaces:

1. An **auction contract** (``services.auctions.auction_address``) — a
   Dutch / English / sealed-bid auction house. ``create_auction``,
   ``place_bid`` and ``settle_auction`` map to that contract's functions.
   The auction contract is modelled on the well-known Zora / Reservoir-style
   ``AuctionHouse`` interface:
     createAuction(address tokenContract, uint256 tokenId, uint256 duration,
                   uint256 reservePrice, address currency)
     createBid(uint256 auctionId, uint256 amount)   [payable]
     endAuction(uint256 auctionId)
   (See Zora ``AuctionHouse.sol`` — the canonical reference auction house.)

2. An **orderbook DEX** (``services.auctions.orderbook_address``) — a
   central-limit-orderbook exchange. ``place_limit_order`` and
   ``cancel_limit_order`` map to that contract's functions, modelled on the
   common on-chain CLOB interface (e.g. dYdX / Serum-style settlement and the
   0x Exchange ``cancelOrder`` selector):
     placeOrder(address baseToken, address quoteToken, bool isBuy,
                uint256 price, uint256 amount)
     cancelOrder(uint256 orderId)

GATING (CREDENTIAL-GATED, testable): every method first checks for the exact
credential it needs — ``services.auctions.auction_address`` /
``services.auctions.orderbook_address`` (non-placeholder) plus a reachable
``blockchain.rpc_url``. When the needed credential is missing it returns the
canonical ``not_deployed_response`` naming the exact missing config key, so
CREDENTIALS_NEEDED.md can map it.

NON-CUSTODIAL (hard rule):
- ``create_auction`` and ``settle_auction`` are PLATFORM-level / permissionless
  maintenance operations (listing a platform-held item, finalising an expired
  auction) and are signed with the platform paymaster account via
  ``Web3Manager.send_transaction`` (gas-sponsored).
- ``place_bid`` and ``place_limit_order`` MOVE A USER'S VALUE (a bid escrows the
  bidder's funds; a maker order locks the maker's funds). The server therefore
  NEVER signs these — it returns a PREPARED, UNSIGNED transaction (``to`` +
  ``data`` + ``value`` + ``chainId``) for the user's own wallet to sign and
  broadcast. User funds are never custodied or moved server-side.
- ``cancel_limit_order`` cancels an order owned by ``maker``; only the maker may
  cancel on-chain, so it is likewise returned as a PREPARED, UNSIGNED tx for the
  maker's wallet — unless the caller is cancelling a PLATFORM-owned order, in
  which case the platform account signs.

The real on-chain calls are UNVERIFIED: they cannot be proven without the
auction/orderbook contracts deployed to Base Sepolia and the platform paymaster
funded. The gating logic above is the testable (CREDENTIAL-GATED) part.
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


# ── Minimal real ABI fragments ────────────────────────────────────────────
# Only the functions this service invokes are declared. Modelled on the Zora
# AuctionHouse (createAuction / createBid / endAuction). UNVERIFIED against the
# operator's specific deployment — the function selectors below match the
# canonical reference interface but the deployed contract may differ; the
# operator must confirm the ABI of the contract they configure.
_AUCTION_ABI = [
    {
        "name": "createAuction",
        "type": "function",
        "stateMutability": "nonpayable",
        "inputs": [
            {"name": "tokenContract", "type": "address"},
            {"name": "tokenId", "type": "uint256"},
            {"name": "duration", "type": "uint256"},
            {"name": "reservePrice", "type": "uint256"},
            {"name": "currency", "type": "address"},
        ],
        "outputs": [{"name": "auctionId", "type": "uint256"}],
    },
    {
        # createBid is payable for native-currency auctions; for ERC-20
        # auctions `amount` is pulled via prior allowance. The PREPARED tx
        # this service returns carries `value` only when currency is native.
        "name": "createBid",
        "type": "function",
        "stateMutability": "payable",
        "inputs": [
            {"name": "auctionId", "type": "uint256"},
            {"name": "amount", "type": "uint256"},
        ],
        "outputs": [],
    },
    {
        "name": "endAuction",
        "type": "function",
        "stateMutability": "nonpayable",
        "inputs": [{"name": "auctionId", "type": "uint256"}],
        "outputs": [],
    },
]

# Orderbook DEX (central limit orderbook). placeOrder / cancelOrder modelled on
# common on-chain CLOB interfaces. UNVERIFIED against the operator's deployment.
_ORDERBOOK_ABI = [
    {
        "name": "placeOrder",
        "type": "function",
        "stateMutability": "nonpayable",
        "inputs": [
            {"name": "baseToken", "type": "address"},
            {"name": "quoteToken", "type": "address"},
            {"name": "isBuy", "type": "bool"},
            {"name": "price", "type": "uint256"},
            {"name": "amount", "type": "uint256"},
        ],
        "outputs": [{"name": "orderId", "type": "uint256"}],
    },
    {
        "name": "cancelOrder",
        "type": "function",
        "stateMutability": "nonpayable",
        "inputs": [{"name": "orderId", "type": "uint256"}],
        "outputs": [],
    },
]

# Zero address sentinel = native currency (ETH) auction.
_NATIVE_CURRENCY = "0x0000000000000000000000000000000000000000"


class AuctionService:
    """Dutch, English, sealed-bid auctions and orderbook DEX primitives."""

    service_name = "auctions"

    def __init__(self, config: dict) -> None:
        self._config = config
        self._web3 = Web3Manager.get_shared(config)
        self._gas_sponsor = None  # lazy — only instantiated when needed

    def _sponsor(self):
        if self._gas_sponsor is None:
            from runtime.blockchain.gas_sponsor import GasSponsor
            self._gas_sponsor = GasSponsor(self._config)
        return self._gas_sponsor

    # ── config helpers ────────────────────────────────────────────────
    def _cfg(self) -> dict:
        return self._config.get("services", {}).get(self.service_name, {}) or {}

    def _auction_address(self) -> str:
        return self._cfg().get("auction_address", "") or ""

    def _orderbook_address(self) -> str:
        return self._cfg().get("orderbook_address", "") or ""

    def _to_wei(self, value: Any) -> int:
        """Interpret *value* as a token base-unit integer.

        Callers pass on-chain amounts already in base units (wei / smallest
        token unit). We coerce to int and never fabricate scaling — if a caller
        passes a float, it is treated as ether and converted, otherwise the
        integer base-unit value is used verbatim.
        """
        if isinstance(value, float):
            # ether → wei, deterministic, no fabricated price.
            return int(value * 10**18)
        try:
            return int(value)
        except (TypeError, ValueError):
            return 0

    def _gate_auction(self, method: str) -> dict | None:
        """Return a CREDENTIAL-GATED dict if the auction path is not usable."""
        addr = self._auction_address()
        if not self._web3.available or is_placeholder_value(addr):
            return not_deployed_response(
                self.service_name,
                extra={
                    "method": method,
                    "missing": (
                        "services.auctions.auction_address (auction house "
                        "contract) + reachable blockchain.rpc_url"
                    ),
                    "protocol": "On-chain auction house (Dutch/English/sealed-bid)",
                },
            )
        return None

    def _gate_orderbook(self, method: str) -> dict | None:
        """Return a CREDENTIAL-GATED dict if the orderbook path is not usable."""
        addr = self._orderbook_address()
        if not self._web3.available or is_placeholder_value(addr):
            return not_deployed_response(
                self.service_name,
                extra={
                    "method": method,
                    "missing": (
                        "services.auctions.orderbook_address (orderbook DEX "
                        "contract) + reachable blockchain.rpc_url"
                    ),
                    "protocol": "On-chain central-limit-orderbook DEX",
                },
            )
        return None

    # ── create_auction (PLATFORM-level write) ─────────────────────────
    async def create_auction(self, **params: Any) -> dict:
        """Create an auction for a platform-held item.

        PLATFORM-level: listing an item the platform controls. Signed with the
        platform paymaster account (gas-sponsored). To auction a USER's asset,
        the user must list it from their own wallet — this server never moves a
        user's NFT/token, so a user-owned listing is returned as a prepared op
        (see ``prepared_only=True``).
        """
        gate = self._gate_auction("create_auction")
        if gate is not None:
            return gate

        token_contract = params.get("token_contract") or params.get("collection")
        token_id = params.get("token_id")
        duration = params.get("duration", 86400)  # seconds; caller-supplied
        reserve_price = params.get("reserve_price", params.get("reservePrice", 0))
        currency = params.get("currency") or _NATIVE_CURRENCY
        prepared_only = bool(params.get("prepared_only", False))

        if is_placeholder_value(token_contract) or token_id is None:
            return {
                "status": "error",
                "service": self.service_name,
                "method": "create_auction",
                "error": "token_contract and token_id are required",
            }

        try:
            w3 = self._web3.w3
            contract = self._web3.load_contract(
                self._auction_address(), _AUCTION_ABI
            )
            fn = contract.functions.createAuction(
                w3.to_checksum_address(token_contract),
                int(token_id),
                int(duration),
                self._to_wei(reserve_price),
                w3.to_checksum_address(currency),
            )

            if prepared_only:
                # Item belongs to a USER — return an unsigned tx for their wallet.
                data = fn.build_transaction({"gas": 0, "gasPrice": 0})["data"]
                return self._prepared_response(
                    "create_auction", self._auction_address(), data, value=0,
                    note="User-owned listing — sign and broadcast from the asset owner's wallet.",
                )

            # PLATFORM-held item: platform account signs (gas-sponsored).
            platform = self._web3.get_account().address
            tx = fn.build_transaction({"from": platform})
            tx_hash = await self._web3.send_transaction(tx)
            return {
                "status": "submitted",
                "service": self.service_name,
                "method": "create_auction",
                "protocol": "auction_house",
                "auction_contract": self._auction_address(),
                "token_contract": token_contract,
                "token_id": int(token_id),
                "duration": int(duration),
                "reserve_price": str(self._to_wei(reserve_price)),
                "currency": currency,
                "signed_by": "platform_paymaster",
                "tx_hash": tx_hash,
                "explorer_url": self._web3.explorer_url(tx_hash),
            }
        except Exception as exc:  # noqa: BLE001
            logger.error("create_auction failed: %s", exc)
            return {
                "status": "error",
                "service": self.service_name,
                "method": "create_auction",
                "error": str(exc),
            }

    # ── place_bid (USER value — PREPARED only, never server-signed) ────
    async def place_bid(self, **params: Any) -> dict:
        """Place a bid on an auction.

        NON-CUSTODIAL: a bid escrows the BIDDER's funds. The server NEVER signs
        this with the platform key — doing so would custody/move user value.
        Returns a PREPARED, UNSIGNED transaction the bidder's own wallet signs
        and broadcasts.
        """
        gate = self._gate_auction("place_bid")
        if gate is not None:
            return gate

        auction_id = params.get("auction_id", params.get("auctionId"))
        amount = params.get("amount", params.get("bid_amount", 0))
        currency = params.get("currency") or _NATIVE_CURRENCY

        if auction_id is None:
            return {
                "status": "error",
                "service": self.service_name,
                "method": "place_bid",
                "error": "auction_id is required",
            }

        try:
            contract = self._web3.load_contract(
                self._auction_address(), _AUCTION_ABI
            )
            amount_wei = self._to_wei(amount)
            fn = contract.functions.createBid(int(auction_id), amount_wei)
            data = fn.build_transaction({"gas": 0, "gasPrice": 0})["data"]
            # Native-currency auctions carry `value`; ERC-20 auctions require a
            # prior allowance (the bidder's wallet must approve separately).
            is_native = (
                str(currency).lower() == _NATIVE_CURRENCY.lower()
            )
            value = amount_wei if is_native else 0
            note = (
                "Native-currency bid — value attached."
                if is_native
                else "ERC-20 bid — approve the auction contract for `amount` first, then sign this tx."
            )
            return self._prepared_response(
                "place_bid", self._auction_address(), data, value=value,
                note="NON-CUSTODIAL: bidder signs from their own wallet. " + note,
                extra={
                    "auction_id": int(auction_id),
                    "amount": str(amount_wei),
                    "currency": currency,
                },
            )
        except Exception as exc:  # noqa: BLE001
            logger.error("place_bid prepare failed: %s", exc)
            return {
                "status": "error",
                "service": self.service_name,
                "method": "place_bid",
                "error": str(exc),
            }

    # ── settle_auction (PLATFORM-level / permissionless write) ─────────
    async def settle_auction(self, **params: Any) -> dict:
        """Settle / finalise an ended auction.

        PLATFORM-level: ``endAuction`` is a permissionless keeper-style
        finalisation that transfers the asset to the winner and proceeds to the
        seller per the contract's own logic — it moves no caller-controlled
        funds, so the platform paymaster signs it (gas-sponsored).
        """
        gate = self._gate_auction("settle_auction")
        if gate is not None:
            return gate

        auction_id = params.get("auction_id", params.get("auctionId"))
        if auction_id is None:
            return {
                "status": "error",
                "service": self.service_name,
                "method": "settle_auction",
                "error": "auction_id is required",
            }

        try:
            contract = self._web3.load_contract(
                self._auction_address(), _AUCTION_ABI
            )
            platform = self._web3.get_account().address
            tx = contract.functions.endAuction(int(auction_id)).build_transaction(
                {"from": platform}
            )
            tx_hash = await self._web3.send_transaction(tx)
            return {
                "status": "submitted",
                "service": self.service_name,
                "method": "settle_auction",
                "protocol": "auction_house",
                "auction_contract": self._auction_address(),
                "auction_id": int(auction_id),
                "signed_by": "platform_paymaster",
                "tx_hash": tx_hash,
                "explorer_url": self._web3.explorer_url(tx_hash),
            }
        except Exception as exc:  # noqa: BLE001
            logger.error("settle_auction failed: %s", exc)
            return {
                "status": "error",
                "service": self.service_name,
                "method": "settle_auction",
                "error": str(exc),
            }

    # ── place_limit_order (USER value — PREPARED only) ─────────────────
    async def place_limit_order(self, **params: Any) -> dict:
        """Place a limit order on the orderbook DEX.

        NON-CUSTODIAL: a maker order locks the MAKER's funds. The server NEVER
        signs this with the platform key. Returns a PREPARED, UNSIGNED
        transaction for the maker's own wallet.
        """
        gate = self._gate_orderbook("place_limit_order")
        if gate is not None:
            return gate

        base_token = params.get("base_token") or params.get("baseToken")
        quote_token = params.get("quote_token") or params.get("quoteToken")
        side = str(params.get("side", "buy")).lower()
        is_buy = side in ("buy", "bid", "long")
        price = params.get("price", 0)
        amount = params.get("amount", params.get("size", 0))

        if is_placeholder_value(base_token) or is_placeholder_value(quote_token):
            return {
                "status": "error",
                "service": self.service_name,
                "method": "place_limit_order",
                "error": "base_token and quote_token are required",
            }

        try:
            w3 = self._web3.w3
            contract = self._web3.load_contract(
                self._orderbook_address(), _ORDERBOOK_ABI
            )
            price_wei = self._to_wei(price)
            amount_wei = self._to_wei(amount)
            fn = contract.functions.placeOrder(
                w3.to_checksum_address(base_token),
                w3.to_checksum_address(quote_token),
                bool(is_buy),
                price_wei,
                amount_wei,
            )
            data = fn.build_transaction({"gas": 0, "gasPrice": 0})["data"]
            return self._prepared_response(
                "place_limit_order", self._orderbook_address(), data, value=0,
                note=(
                    "NON-CUSTODIAL: maker signs from their own wallet. Approve "
                    "the orderbook contract for the funding token first."
                ),
                extra={
                    "base_token": base_token,
                    "quote_token": quote_token,
                    "side": "buy" if is_buy else "sell",
                    "price": str(price_wei),
                    "amount": str(amount_wei),
                },
            )
        except Exception as exc:  # noqa: BLE001
            logger.error("place_limit_order prepare failed: %s", exc)
            return {
                "status": "error",
                "service": self.service_name,
                "method": "place_limit_order",
                "error": str(exc),
            }

    # ── cancel_limit_order ─────────────────────────────────────────────
    async def cancel_limit_order(self, **params: Any) -> dict:
        """Cancel a resting limit order.

        On-chain only the order's MAKER may cancel. NON-CUSTODIAL:
        - If ``platform_owned=True`` the order belongs to the platform account
          and the platform paymaster signs the cancel (gas-sponsored).
        - Otherwise the cancel is returned as a PREPARED, UNSIGNED tx for the
          maker's own wallet — the server never signs on a user's behalf.
        """
        gate = self._gate_orderbook("cancel_limit_order")
        if gate is not None:
            return gate

        order_id = params.get("order_id", params.get("orderId"))
        platform_owned = bool(params.get("platform_owned", False))

        if order_id is None:
            return {
                "status": "error",
                "service": self.service_name,
                "method": "cancel_limit_order",
                "error": "order_id is required",
            }

        try:
            contract = self._web3.load_contract(
                self._orderbook_address(), _ORDERBOOK_ABI
            )
            fn = contract.functions.cancelOrder(int(order_id))

            if not platform_owned:
                # User-owned order — return unsigned tx for the maker's wallet.
                data = fn.build_transaction({"gas": 0, "gasPrice": 0})["data"]
                return self._prepared_response(
                    "cancel_limit_order", self._orderbook_address(), data, value=0,
                    note="NON-CUSTODIAL: only the order maker may cancel — sign from the maker's wallet.",
                    extra={"order_id": int(order_id)},
                )

            # Platform-owned order: platform account signs (gas-sponsored).
            platform = self._web3.get_account().address
            tx = fn.build_transaction({"from": platform})
            tx_hash = await self._web3.send_transaction(tx)
            return {
                "status": "submitted",
                "service": self.service_name,
                "method": "cancel_limit_order",
                "protocol": "orderbook_dex",
                "orderbook_contract": self._orderbook_address(),
                "order_id": int(order_id),
                "signed_by": "platform_paymaster",
                "tx_hash": tx_hash,
                "explorer_url": self._web3.explorer_url(tx_hash),
            }
        except Exception as exc:  # noqa: BLE001
            logger.error("cancel_limit_order failed: %s", exc)
            return {
                "status": "error",
                "service": self.service_name,
                "method": "cancel_limit_order",
                "error": str(exc),
            }

    # ── prepared (unsigned) tx helper — non-custodial user-signed path ──
    def _prepared_response(
        self,
        method: str,
        to: str,
        data: str,
        value: int = 0,
        note: str = "",
        extra: dict | None = None,
    ) -> dict:
        """Shape a PREPARED, UNSIGNED transaction for a USER's wallet to sign.

        The server returns ``to``/``data``/``value``/``chainId`` only — it does
        NOT sign and does NOT broadcast. The user's wallet supplies ``from``,
        ``nonce`` and gas and signs locally. This keeps user-value-moving
        operations fully non-custodial.
        """
        response = {
            "status": "prepared",
            "service": self.service_name,
            "method": method,
            "custody": "non_custodial",
            "signing": "user_wallet_required",
            "note": note,
            "transaction": {
                "to": to,
                "data": data,
                "value": str(int(value)),
                "chainId": self._web3.chain_id,
            },
        }
        if extra:
            response.update(extra)
        return response
