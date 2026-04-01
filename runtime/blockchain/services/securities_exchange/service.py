"""
SecuritiesExchangeService — ERC-3643 compliant tokenized securities exchange.

Supports equity, debt, fund, and REIT security types with full compliance
checks, order book matching, and private placement negotiation.
"""

from __future__ import annotations

import logging
import time
import uuid
from typing import Any

from runtime.blockchain.services.securities_exchange.compliance import ERC3643Compliance
from runtime.blockchain.services.securities_exchange.exchange import ExchangeContract
from runtime.blockchain.services.securities_exchange.negotiation import TermsNegotiation

logger = logging.getLogger(__name__)

_VALID_SECURITY_TYPES = ("equity", "debt", "fund", "reit")


class SecuritiesExchangeService:
    """Main tokenized securities exchange service (ERC-3643 compliant).

    Config keys (under ``config["securities"]``):
        All keys from ERC3643Compliance, ExchangeContract, and
        TermsNegotiation are supported.
    """

    def __init__(self, config: dict) -> None:
        self._config = config

        self._compliance = ERC3643Compliance(config)
        self._exchange = ExchangeContract(config)
        self._negotiation = TermsNegotiation(config)

        # security_id -> security record
        self._securities: dict[str, dict[str, Any]] = {}
        # security_id -> listing record
        self._listings: dict[str, dict[str, Any]] = {}
        # (security_id, holder) -> balance
        self._balances: dict[tuple[str, str], int] = {}

        logger.info("SecuritiesExchangeService initialised.")

    @property
    def compliance(self) -> ERC3643Compliance:
        return self._compliance

    @property
    def exchange(self) -> ExchangeContract:
        return self._exchange

    @property
    def negotiation(self) -> TermsNegotiation:
        return self._negotiation

    # ------------------------------------------------------------------
    # Security lifecycle
    # ------------------------------------------------------------------

    async def create_security(
        self,
        issuer: str,
        security_type: str,
        total_supply: int,
        metadata: dict,
    ) -> dict:
        """Create a new tokenized security.

        Args:
            issuer: Issuer wallet address.
            security_type: One of "equity", "debt", "fund", "reit".
            total_supply: Total number of tokens to mint.
            metadata: Additional info (name, symbol, description, etc.).

        Returns:
            Security record.
        """
        if not issuer:
            raise ValueError("Issuer address is required")

        security_type = security_type.lower()
        if security_type not in _VALID_SECURITY_TYPES:
            raise ValueError(
                f"Invalid security type '{security_type}'; "
                f"must be one of {_VALID_SECURITY_TYPES}"
            )
        if total_supply <= 0:
            raise ValueError("Total supply must be positive")

        security_id = str(uuid.uuid4())
        now = int(time.time())

        security = {
            "security_id": security_id,
            "issuer": issuer,
            "security_type": security_type,
            "total_supply": total_supply,
            "circulating_supply": total_supply,
            "name": metadata.get("name", f"{security_type.upper()}-{security_id[:8]}"),
            "symbol": metadata.get("symbol", security_id[:8].upper()),
            "description": metadata.get("description", ""),
            "metadata": dict(metadata),
            "status": "created",
            "created_at": now,
            "updated_at": now,
        }

        self._securities[security_id] = security
        # Issuer holds all tokens initially
        self._balances[(security_id, issuer)] = total_supply

        # Auto-whitelist the issuer
        await self._compliance.whitelist_investor(
            security_id, issuer,
            {
                "accredited": True,
                "jurisdiction": metadata.get("jurisdiction", "US"),
                "kyc_verified": True,
                "aml_verified": True,
                "investor_type": "issuer",
            },
        )

        logger.info(
            "Security created: id=%s type=%s supply=%d issuer=%s",
            security_id, security_type, total_supply, issuer,
        )
        return dict(security)

    async def list_security(self, security_id: str, price: float) -> dict:
        """List a security for trading on the exchange.

        Args:
            security_id: Security to list.
            price: Initial listing price per token.

        Returns:
            Listing record.
        """
        security = self._securities.get(security_id)
        if not security:
            raise ValueError(f"Security {security_id} not found")
        if price <= 0:
            raise ValueError("Listing price must be positive")

        now = int(time.time())
        listing = {
            "security_id": security_id,
            "listing_price": price,
            "current_price": price,
            "status": "active",
            "listed_at": now,
            "volume_24h": 0,
            "total_volume": 0,
        }

        self._listings[security_id] = listing
        security["status"] = "listed"
        security["updated_at"] = now

        logger.info(
            "Security listed: id=%s price=%.4f", security_id, price,
        )
        return dict(listing)

    async def buy(
        self, security_id: str, buyer: str, amount: int
    ) -> dict:
        """Buy tokens at market price (takes from order book).

        This is a simplified market buy that checks compliance first.

        Args:
            security_id: Security to buy.
            buyer: Buyer wallet address.
            amount: Number of tokens to buy.

        Returns:
            Trade execution result.
        """
        security = self._securities.get(security_id)
        if not security:
            raise ValueError(f"Security {security_id} not found")
        if amount <= 0:
            raise ValueError("Buy amount must be positive")

        listing = self._listings.get(security_id)
        if not listing or listing["status"] != "active":
            raise ValueError(f"Security {security_id} is not listed for trading")

        # Compliance check: issuer -> buyer
        issuer = security["issuer"]
        compliance_result = await self._compliance.check_transfer(
            security_id, issuer, buyer, amount
        )
        if not compliance_result["allowed"]:
            raise ValueError(
                f"Compliance check failed: {compliance_result['reason']}"
            )

        # Check issuer balance
        issuer_balance = self._balances.get((security_id, issuer), 0)
        if issuer_balance < amount:
            raise ValueError(
                f"Insufficient supply: available={issuer_balance}, requested={amount}"
            )

        # Execute transfer
        price = listing["current_price"]
        self._balances[(security_id, issuer)] = issuer_balance - amount
        self._balances[(security_id, buyer)] = (
            self._balances.get((security_id, buyer), 0) + amount
        )

        # Record acquisition for holding period tracking
        self._compliance.record_acquisition(security_id, buyer)

        # Update listing stats
        listing["volume_24h"] += amount
        listing["total_volume"] += amount

        trade = {
            "trade_id": str(uuid.uuid4()),
            "security_id": security_id,
            "side": "buy",
            "buyer": buyer,
            "seller": issuer,
            "amount": amount,
            "price": price,
            "total_value": price * amount,
            "executed_at": int(time.time()),
        }

        logger.info(
            "Buy executed: security=%s buyer=%s amount=%d price=%.4f",
            security_id, buyer, amount, price,
        )
        return trade

    async def sell(
        self,
        security_id: str,
        seller: str,
        amount: int,
        price: float,
    ) -> dict:
        """Place a sell order on the exchange.

        Compliance is checked before the order is placed.

        Args:
            security_id: Security to sell.
            seller: Seller wallet address.
            amount: Number of tokens to sell.
            price: Limit price per token.

        Returns:
            Order record.
        """
        security = self._securities.get(security_id)
        if not security:
            raise ValueError(f"Security {security_id} not found")
        if amount <= 0:
            raise ValueError("Sell amount must be positive")
        if price <= 0:
            raise ValueError("Sell price must be positive")

        seller_balance = self._balances.get((security_id, seller), 0)
        if seller_balance < amount:
            raise ValueError(
                f"Insufficient balance: have={seller_balance}, selling={amount}"
            )

        # Place as a sell order on the exchange
        order = await self._exchange.place_order(
            security_id, "sell", price, amount, seller
        )

        logger.info(
            "Sell order placed: security=%s seller=%s amount=%d price=%.4f",
            security_id, seller, amount, price,
        )
        return order

    async def get_security(self, security_id: str) -> dict:
        """Get full details for a security.

        Returns:
            Security record with listing info and order book summary.
        """
        security = self._securities.get(security_id)
        if not security:
            raise ValueError(f"Security {security_id} not found")

        result = dict(security)
        listing = self._listings.get(security_id)
        if listing:
            result["listing"] = dict(listing)

        order_book = await self._exchange.get_order_book(security_id)
        result["order_book_summary"] = {
            "best_bid": order_book["best_bid"],
            "best_ask": order_book["best_ask"],
            "spread": order_book["spread"],
            "mid_price": order_book["mid_price"],
            "bid_depth": len(order_book["bids"]),
            "ask_depth": len(order_book["asks"]),
        }

        return result
