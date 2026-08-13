"""
ExchangeContract — order book and price-time priority matching engine
for the tokenized securities exchange.

Manages bid/ask order books per security and performs continuous matching.
"""

from __future__ import annotations

import logging
import time
import uuid
from typing import Any

logger = logging.getLogger(__name__)

_VALID_SIDES = ("buy", "sell")


class ExchangeContract:
    """Order book and matching engine for tokenized securities.

    Config keys (under ``config["securities"]``):
        max_order_size (int): Maximum order size (default 1_000_000).
        min_price_increment (float): Tick size (default 0.01).
    """

    def __init__(self, config: dict) -> None:
        self._config = config
        s_cfg: dict[str, Any] = config.get("securities", {})

        self._max_order_size: int = int(s_cfg.get("max_order_size", 1_000_000))
        self._min_tick: float = float(s_cfg.get("min_price_increment", 0.01))

        # security_id -> {"bids": [...], "asks": [...]}
        self._order_books: dict[str, dict[str, list[dict]]] = {}
        # order_id -> order record
        self._orders: dict[str, dict[str, Any]] = {}
        # Executed trades
        self._trades: list[dict[str, Any]] = []

        logger.info(
            "ExchangeContract initialised (max_order=%d, tick=%.4f).",
            self._max_order_size, self._min_tick,
        )

    def _ensure_book(self, security_id: str) -> dict[str, list[dict]]:
        """Lazily create an order book for a security."""
        if security_id not in self._order_books:
            self._order_books[security_id] = {"bids": [], "asks": []}
        return self._order_books[security_id]

    async def place_order(
        self, security_id: str, side: str, price: float, amount: int, trader: str
    ) -> dict:
        """Place a limit order on the exchange.

        Args:
            security_id: Security token identifier.
            side: "buy" or "sell".
            price: Limit price (must be positive, aligned to tick).
            amount: Number of tokens.
            trader: Trader wallet address.

        Returns:
            Order record.
        """
        side = side.lower()
        if side not in _VALID_SIDES:
            raise ValueError(f"Side must be one of {_VALID_SIDES}, got '{side}'")
        if price <= 0:
            raise ValueError("Price must be positive")
        if amount <= 0:
            raise ValueError("Amount must be positive")
        if amount > self._max_order_size:
            raise ValueError(f"Amount {amount} exceeds max order size {self._max_order_size}")

        order_id = str(uuid.uuid4())
        now = int(time.time())

        order = {
            "order_id": order_id,
            "security_id": security_id,
            "side": side,
            "price": round(price, 8),
            "original_amount": amount,
            "remaining_amount": amount,
            "filled_amount": 0,
            "trader": trader,
            "status": "open",
            "created_at": now,
            "updated_at": now,
        }

        self._orders[order_id] = order

        book = self._ensure_book(security_id)
        if side == "buy":
            book["bids"].append(order)
            # Sort bids: highest price first, then earliest time
            book["bids"].sort(key=lambda o: (-o["price"], o["created_at"]))
        else:
            book["asks"].append(order)
            # Sort asks: lowest price first, then earliest time
            book["asks"].sort(key=lambda o: (o["price"], o["created_at"]))

        logger.info(
            "Order placed: id=%s security=%s side=%s price=%.4f amount=%d trader=%s",
            order_id, security_id, side, price, amount, trader,
        )
        return dict(order)

    def committed_sell_amount(self, security_id: str, trader: str) -> int:
        """Units this trader already has promised via OPEN sell orders.

        DOMAIN 13-B. `SecuritiesExchangeService.sell` validated against the raw
        balance and reserved nothing, so N orders each passed against the same
        unreduced position. This is the reservation the caller needs to subtract.
        Counts `remaining_amount` (not `original_amount`) so partially-matched
        orders only reserve what is still outstanding.
        """
        # 13-B AND 13-C CANCELLED EACH OTHER, AND THE SUITE DID NOT NOTICE.
        # The first version counted only status == "open" and summed
        # remaining_amount. 13-C — in the same commit — moved matched orders to
        # "matched_unsettled" and drove remaining_amount to 0. So MATCHING
        # RELEASED THE RESERVATION while, by 13-C's own thesis, nothing settled:
        # sell 100, match it, sell 100 again, both accepted against a balance of
        # 100. The exact over-commitment 13-B was written to close.
        #
        # Two fixes each correct alone, interacting to reopen one of them. No
        # test combined them because each had its own test.
        #
        # THE HONEST RULE WHILE NOTHING SETTLES: a sell order commits its units
        # until it is CANCELLED. Matching does not release them, because matching
        # moves nothing — the units are still in the holder's balance and still
        # promised. So count ORIGINAL_AMOUNT for every order that is neither
        # cancelled nor settled, not the remaining_amount, which tracks matching
        # progress rather than delivery.
        #
        # WHEN SETTLEMENT EXISTS THIS MUST CHANGE: at that point matched units
        # really do leave the balance, remaining_amount becomes the right
        # measure, and counting original_amount would double-reserve. Pinned by
        # test_the_matching_engine_still_cannot_reach_balances — if that fails,
        # revisit this.
        UNSETTLED = ("open", "matched_unsettled", "partially_filled")
        total = 0
        for order in self._orders.values():
            if (
                order.get("security_id") == security_id
                and order.get("trader") == trader
                and order.get("side") == "sell"
                and order.get("status") in UNSETTLED
            ):
                total += int(order.get("original_amount", 0))
        return total

    async def cancel_order(self, order_id: str) -> dict:
        """Cancel an open order.

        Returns:
            Updated order record with status='cancelled'.
        """
        order = self._orders.get(order_id)
        if not order:
            raise ValueError(f"Order {order_id} not found")
        if order["status"] != "open":
            raise ValueError(f"Order {order_id} is {order['status']}, cannot cancel")

        order["status"] = "cancelled"
        order["updated_at"] = int(time.time())

        # Remove from book
        book = self._ensure_book(order["security_id"])
        side_key = "bids" if order["side"] == "buy" else "asks"
        book[side_key] = [o for o in book[side_key] if o["order_id"] != order_id]

        logger.info("Order cancelled: id=%s", order_id)
        return dict(order)

    async def get_order_book(self, security_id: str) -> dict:
        """Get the current order book for a security.

        Returns:
            Dict with 'bids', 'asks', 'spread', and 'mid_price'.
        """
        book = self._ensure_book(security_id)

        active_bids = [
            {"price": o["price"], "amount": o["remaining_amount"], "trader": o["trader"]}
            for o in book["bids"] if o["status"] == "open" and o["remaining_amount"] > 0
        ]
        active_asks = [
            {"price": o["price"], "amount": o["remaining_amount"], "trader": o["trader"]}
            for o in book["asks"] if o["status"] == "open" and o["remaining_amount"] > 0
        ]

        best_bid = active_bids[0]["price"] if active_bids else 0.0
        best_ask = active_asks[0]["price"] if active_asks else 0.0

        spread = (best_ask - best_bid) if (best_bid > 0 and best_ask > 0) else None
        mid_price = ((best_bid + best_ask) / 2) if spread is not None else None

        return {
            "security_id": security_id,
            "bids": active_bids,
            "asks": active_asks,
            "best_bid": best_bid,
            "best_ask": best_ask,
            "spread": spread,
            "mid_price": mid_price,
        }

    async def match_orders(self, security_id: str) -> list:
        """Match buy and sell orders using price-time priority.

        A buy order matches a sell order when bid_price >= ask_price.
        Execution price is the resting (earlier) order's price.

        Returns:
            List of executed trade records.
        """
        book = self._ensure_book(security_id)
        trades: list[dict[str, Any]] = []

        while True:
            # Filter to active orders
            bids = [o for o in book["bids"] if o["status"] == "open" and o["remaining_amount"] > 0]
            asks = [o for o in book["asks"] if o["status"] == "open" and o["remaining_amount"] > 0]

            if not bids or not asks:
                break

            best_bid = bids[0]
            best_ask = asks[0]

            if best_bid["price"] < best_ask["price"]:
                break  # No match possible

            # Execute at the resting order's price (the one placed first)
            if best_bid["created_at"] <= best_ask["created_at"]:
                exec_price = best_bid["price"]
            else:
                exec_price = best_ask["price"]

            fill_qty = min(best_bid["remaining_amount"], best_ask["remaining_amount"])

            trade = {
                "trade_id": str(uuid.uuid4()),
                "security_id": security_id,
                "price": exec_price,
                "amount": fill_qty,
                "buyer": best_bid["trader"],
                "seller": best_ask["trader"],
                "buy_order_id": best_bid["order_id"],
                "sell_order_id": best_ask["order_id"],
                # DOMAIN 13-C — "matched", NOT "executed". This engine transfers
                # NOTHING: it holds no reference to the service's `_balances`
                # (see __init__ — config, order books, trades only), so it is
                # structurally incapable of settling what it matches. Measured:
                # one trade reported executed, balances unchanged, counterparty
                # holding 0 afterwards. The order-book bookkeeping below is real
                # work; the EXECUTION claim was the lie.
                "matched_at": int(time.time()),
                "settled": False,
                "settlement": (
                    "NOT SETTLED — this exchange has no settlement path. The "
                    "match is a price/quantity agreement only; no security and "
                    "no payment has moved."
                ),
            }
            trades.append(trade)
            self._trades.append(trade)

            # Update order quantities
            best_bid["remaining_amount"] -= fill_qty
            best_bid["filled_amount"] += fill_qty
            best_ask["remaining_amount"] -= fill_qty
            best_ask["filled_amount"] += fill_qty

            now = int(time.time())
            if best_bid["remaining_amount"] == 0:
                best_bid["status"] = "matched_unsettled"
                best_bid["updated_at"] = now
            else:
                best_bid["updated_at"] = now

            if best_ask["remaining_amount"] == 0:
                best_ask["status"] = "matched_unsettled"
                best_ask["updated_at"] = now
            else:
                best_ask["updated_at"] = now

            logger.info(
                "Trade MATCHED (unsettled): id=%s security=%s price=%.4f amount=%d buyer=%s seller=%s",
                trade["trade_id"], security_id, exec_price, fill_qty,
                best_bid["trader"], best_ask["trader"],
            )

        # Clean filled orders from book lists
        book["bids"] = [o for o in book["bids"] if o["status"] == "open" and o["remaining_amount"] > 0]
        book["asks"] = [o for o in book["asks"] if o["status"] == "open" and o["remaining_amount"] > 0]

        return trades

    def get_trades(self, security_id: str, limit: int = 50) -> list[dict]:
        """Return recent trades for a security."""
        filtered = [t for t in self._trades if t["security_id"] == security_id]
        # THE RENAME BROKE THIS READER, 45 LINES FROM THE WRITE. 13-C renamed the
        # trade key executed_at -> matched_at in match_orders and left this sort
        # untouched, so get_trades raised KeyError for any security that had ever
        # matched. THE SURFACE RULE, failed in the commit that invoked it: when a
        # finding renames a field, check every reader of that field — and "the
        # same file" is not a small enough scope to skip the check.
        #
        # The empty case masked it: an empty list never calls the sort key, so
        # get_trades on a security with no trades still returned []. Same masking
        # shape as the mutable-default in domain 12 — harmless on the first call.
        #
        # `.get` with the legacy key so any record written before the rename
        # still sorts rather than crashing.
        filtered.sort(
            key=lambda t: t.get("matched_at", t.get("executed_at", 0)),
            reverse=True,
        )
        return filtered[:limit]
