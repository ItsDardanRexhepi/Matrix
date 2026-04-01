"""
FiatETHConversion — currency conversion using oracle-sourced FX rates.

Supported currencies: USD, EUR, GBP, JPY, CHF, CAD, AUD + ETH, USDC, USDT, DAI.
Uses OracleGateway (Component 11) for real-time FX rates.
"""

from __future__ import annotations

import logging
import time
from typing import Any

logger = logging.getLogger(__name__)

SUPPORTED_FIAT: set[str] = {"USD", "EUR", "GBP", "JPY", "CHF", "CAD", "AUD"}
SUPPORTED_CRYPTO: set[str] = {"ETH", "USDC", "USDT", "DAI"}
SUPPORTED_CURRENCIES: set[str] = SUPPORTED_FIAT | SUPPORTED_CRYPTO

# Fallback rates (USD-based) used when oracle is unavailable
_FALLBACK_RATES_USD: dict[str, float] = {
    "USD": 1.0,
    "EUR": 0.92,
    "GBP": 0.79,
    "JPY": 149.50,
    "CHF": 0.88,
    "CAD": 1.36,
    "AUD": 1.53,
    "ETH": 0.00031,   # 1 USD = 0.00031 ETH  (~3200 USD/ETH)
    "USDC": 1.0,
    "USDT": 1.0,
    "DAI": 1.0,
}


class FiatETHConversion:
    """Converts between fiat and crypto currencies.

    Uses OracleGateway (Component 11) for live rates when available,
    falls back to built-in rates otherwise.

    Config keys (under ``config["cross_border"]``):
        fallback_rates (dict): Override fallback USD-based rates.
    """

    def __init__(self, config: dict) -> None:
        self._config = config
        cb_cfg = config.get("cross_border", {})

        self._fallback_rates: dict[str, float] = {
            **_FALLBACK_RATES_USD,
            **cb_cfg.get("fallback_rates", {}),
        }

        # Simple cache: pair -> (rate, timestamp)
        self._rate_cache: dict[str, tuple[float, int]] = {}
        self._cache_ttl: int = int(cb_cfg.get("rate_cache_ttl", 60))

    async def get_rate(
        self, from_currency: str, to_currency: str,
    ) -> dict:
        """Get the exchange rate between two currencies.

        Args:
            from_currency: Source currency code.
            to_currency: Destination currency code.

        Returns:
            Dict with ``rate``, ``from``, ``to``, ``source``, ``timestamp``.
        """
        from_currency = from_currency.upper()
        to_currency = to_currency.upper()

        self._validate_currency(from_currency)
        self._validate_currency(to_currency)

        if from_currency == to_currency:
            return {
                "rate": 1.0,
                "from": from_currency,
                "to": to_currency,
                "source": "identity",
                "timestamp": int(time.time()),
            }

        pair = f"{from_currency}/{to_currency}"

        # Check cache
        cached = self._rate_cache.get(pair)
        now = int(time.time())
        if cached and (now - cached[1]) < self._cache_ttl:
            return {
                "rate": cached[0],
                "from": from_currency,
                "to": to_currency,
                "source": "cache",
                "timestamp": cached[1],
            }

        # Try oracle
        rate, source = await self._fetch_oracle_rate(from_currency, to_currency)

        if rate is None:
            # Fallback: cross-rate via USD
            rate = self._cross_rate(from_currency, to_currency)
            source = "fallback"

        self._rate_cache[pair] = (rate, now)

        return {
            "rate": round(rate, 8),
            "from": from_currency,
            "to": to_currency,
            "source": source,
            "timestamp": now,
        }

    async def convert(
        self, amount: float, from_currency: str, to_currency: str,
    ) -> dict:
        """Convert an amount from one currency to another.

        Args:
            amount: Amount in from_currency.
            from_currency: Source currency code.
            to_currency: Destination currency code.

        Returns:
            Dict with ``converted_amount``, ``rate``, ``from``, ``to``.
        """
        if amount <= 0:
            raise ValueError("Amount must be positive")

        rate_data = await self.get_rate(from_currency, to_currency)
        rate = rate_data["rate"]
        converted = amount * rate

        return {
            "original_amount": amount,
            "from_currency": from_currency.upper(),
            "to_currency": to_currency.upper(),
            "rate": rate,
            "converted_amount": round(converted, 6),
            "source": rate_data["source"],
            "timestamp": rate_data["timestamp"],
        }

    # ------------------------------------------------------------------
    # Oracle integration
    # ------------------------------------------------------------------

    async def _fetch_oracle_rate(
        self, from_currency: str, to_currency: str,
    ) -> tuple[float | None, str]:
        """Attempt to fetch a rate from OracleGateway."""
        try:
            from runtime.blockchain.services.oracle_gateway import OracleGateway

            gw = OracleGateway(self._config)
            pair = f"{from_currency}/{to_currency}"

            result = await gw.request(
                "price_feed",
                {"pair": pair},
                caller="cross_border",
            )

            price = result.get("price") or result.get("data", {}).get("price")
            if price is not None:
                return float(price), "oracle"

        except ImportError:
            logger.debug("OracleGateway not available.")
        except Exception as exc:
            logger.warning("Oracle rate fetch failed for %s/%s: %s",
                           from_currency, to_currency, exc)

        return None, "fallback"

    # ------------------------------------------------------------------
    # Helpers
    # ------------------------------------------------------------------

    def _cross_rate(self, from_currency: str, to_currency: str) -> float:
        """Compute cross-rate via USD using fallback rates."""
        from_usd = self._fallback_rates.get(from_currency)
        to_usd = self._fallback_rates.get(to_currency)

        if from_usd is None or to_usd is None:
            raise ValueError(
                f"No fallback rate available for {from_currency}/{to_currency}"
            )

        # from_usd = how many units of from_currency per 1 USD
        # to_usd = how many units of to_currency per 1 USD
        # rate = to_usd / from_usd  (units of to per unit of from)
        return to_usd / from_usd

    @staticmethod
    def _validate_currency(currency: str) -> None:
        if currency not in SUPPORTED_CURRENCIES:
            raise ValueError(
                f"Unsupported currency '{currency}'. "
                f"Supported: {', '.join(sorted(SUPPORTED_CURRENCIES))}"
            )
