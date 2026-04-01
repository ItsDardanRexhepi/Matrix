"""
CollateralManager — manage and monitor collateral deposits across the
DeFi layer.  Tracks per-user balances, computes health factors, and
uses the oracle gateway (Component 11) for real-time price checks.
"""

from __future__ import annotations

import logging
import time
from typing import Any

logger = logging.getLogger(__name__)

# Default health factor threshold
_HEALTHY_THRESHOLD = 1.5
_WARNING_THRESHOLD = 1.3
_DANGER_THRESHOLD = 1.1


class CollateralManager:
    """Manage collateral deposits and monitor health factors.

    Parameters
    ----------
    config : dict
        Platform config.  Reads ``defi.collateral_tokens`` for accepted
        tokens and their collateral factors.
    oracle_gateway : object, optional
        OracleGateway instance for price feeds.  If ``None``, price
        lookups will use fallback values from config.
    """

    def __init__(
        self,
        config: dict,
        oracle_gateway: Any = None,
    ) -> None:
        self._config = config
        self._oracle = oracle_gateway
        defi_cfg = config.get("defi", {})

        # Collateral factors per token (e.g., {"ETH": 0.8, "USDC": 0.95})
        self._collateral_factors: dict[str, float] = defi_cfg.get(
            "collateral_factors", {
                "ETH": 0.80,
                "WETH": 0.80,
                "USDC": 0.95,
                "USDT": 0.90,
                "DAI": 0.90,
                "WBTC": 0.75,
            }
        )

        # Fallback prices (used when oracle is unavailable)
        self._fallback_prices: dict[str, float] = defi_cfg.get(
            "fallback_prices", {}
        )

        # User balances: {user: {token: amount}}
        self._balances: dict[str, dict[str, float]] = {}
        # User borrow positions: {user: {token: amount}}
        self._borrows: dict[str, dict[str, float]] = {}

    async def deposit(
        self, user: str, token: str, amount: float
    ) -> dict[str, Any]:
        """Deposit collateral for a user.

        Parameters
        ----------
        user : str
            User wallet address.
        token : str
            Token symbol to deposit.
        amount : float
            Amount to deposit.

        Returns
        -------
        dict
            Updated balance and deposit confirmation.
        """
        if amount <= 0:
            raise ValueError("Deposit amount must be positive")
        if token not in self._collateral_factors:
            raise ValueError(
                f"Token '{token}' is not accepted as collateral. "
                f"Accepted: {', '.join(sorted(self._collateral_factors))}"
            )

        user_balances = self._balances.setdefault(user, {})
        user_balances[token] = user_balances.get(token, 0) + amount

        logger.info(
            "Collateral deposited: user=%s token=%s amount=%.6f new_balance=%.6f",
            user, token, amount, user_balances[token],
        )

        return {
            "status": "deposited",
            "user": user,
            "token": token,
            "amount": amount,
            "new_balance": user_balances[token],
            "timestamp": int(time.time()),
        }

    async def withdraw(
        self, user: str, token: str, amount: float
    ) -> dict[str, Any]:
        """Withdraw collateral for a user.

        Checks health factor after withdrawal to prevent unsafe positions.

        Raises
        ------
        ValueError
            If withdrawal would bring health factor below danger threshold.
        """
        if amount <= 0:
            raise ValueError("Withdrawal amount must be positive")

        user_balances = self._balances.get(user, {})
        current = user_balances.get(token, 0)
        if amount > current:
            raise ValueError(
                f"Insufficient balance. Have {current:.6f} {token}, "
                f"requested {amount:.6f}"
            )

        # Simulate withdrawal and check health
        user_balances[token] = current - amount
        try:
            health = await self._compute_health_factor(user)
            if health["health_factor"] < _DANGER_THRESHOLD and health["total_borrows_usd"] > 0:
                # Revert withdrawal
                user_balances[token] = current
                raise ValueError(
                    f"Withdrawal would drop health factor to "
                    f"{health['health_factor']:.2f}, below minimum "
                    f"{_DANGER_THRESHOLD:.2f}"
                )
        except Exception:
            if user_balances.get(token, -1) == current - amount:
                # Only revert if we haven't already
                pass
            raise

        logger.info(
            "Collateral withdrawn: user=%s token=%s amount=%.6f remaining=%.6f",
            user, token, amount, user_balances[token],
        )

        return {
            "status": "withdrawn",
            "user": user,
            "token": token,
            "amount": amount,
            "remaining_balance": user_balances[token],
            "timestamp": int(time.time()),
        }

    async def get_health_factor(self, user: str) -> dict[str, Any]:
        """Get the health factor for a user's position.

        The health factor is the ratio of risk-adjusted collateral value
        to total borrows.  Values above 1.5 are healthy, below 1.1 are
        at risk of liquidation.

        Returns
        -------
        dict
            Keys: ``health_factor``, ``status``, ``total_collateral_usd``,
            ``risk_adjusted_collateral_usd``, ``total_borrows_usd``,
            ``balances``, ``borrows``.
        """
        return await self._compute_health_factor(user)

    async def get_balances(self, user: str) -> dict[str, float]:
        """Return raw collateral balances for a user."""
        return dict(self._balances.get(user, {}))

    def record_borrow(self, user: str, token: str, amount: float) -> None:
        """Record a borrow position for health factor tracking."""
        user_borrows = self._borrows.setdefault(user, {})
        user_borrows[token] = user_borrows.get(token, 0) + amount

    def record_repayment(self, user: str, token: str, amount: float) -> None:
        """Record a repayment, reducing borrow position."""
        user_borrows = self._borrows.get(user, {})
        current = user_borrows.get(token, 0)
        user_borrows[token] = max(0, current - amount)

    # ── Internal helpers ──────────────────────────────────────────────

    async def _compute_health_factor(self, user: str) -> dict[str, Any]:
        """Compute the health factor for a user."""
        balances = self._balances.get(user, {})
        borrows = self._borrows.get(user, {})

        total_collateral_usd = 0.0
        risk_adjusted_usd = 0.0

        for token, amount in balances.items():
            price = await self._get_price(token)
            value = amount * price
            factor = self._collateral_factors.get(token, 0.5)
            total_collateral_usd += value
            risk_adjusted_usd += value * factor

        total_borrows_usd = 0.0
        for token, amount in borrows.items():
            price = await self._get_price(token)
            total_borrows_usd += amount * price

        if total_borrows_usd == 0:
            health_factor = float("inf")
            status = "no_borrows"
        else:
            health_factor = risk_adjusted_usd / total_borrows_usd
            if health_factor >= _HEALTHY_THRESHOLD:
                status = "healthy"
            elif health_factor >= _WARNING_THRESHOLD:
                status = "warning"
            elif health_factor >= _DANGER_THRESHOLD:
                status = "danger"
            else:
                status = "liquidatable"

        return {
            "user": user,
            "health_factor": round(health_factor, 4) if health_factor != float("inf") else "inf",
            "status": status,
            "total_collateral_usd": round(total_collateral_usd, 2),
            "risk_adjusted_collateral_usd": round(risk_adjusted_usd, 2),
            "total_borrows_usd": round(total_borrows_usd, 2),
            "balances": dict(balances),
            "borrows": dict(borrows),
        }

    async def _get_price(self, token: str) -> float:
        """Get token price from oracle or fallback."""
        # Try oracle gateway first
        if self._oracle is not None:
            try:
                pair = f"{token}/USD"
                result = await self._oracle.request(
                    "price_feed",
                    {"pair": pair},
                    caller="collateral_manager",
                )
                price = result.get("price", 0)
                if price > 0:
                    return float(price)
            except Exception as exc:
                logger.warning(
                    "Oracle price fetch failed for %s: %s, using fallback",
                    token, exc,
                )

        # Fallback prices
        fallback = self._fallback_prices.get(token)
        if fallback is not None:
            return float(fallback)

        # Default stablecoin assumption
        if token in ("USDC", "USDT", "DAI"):
            return 1.0

        logger.warning("No price available for %s, defaulting to 0", token)
        return 0.0
