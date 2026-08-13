"""
CollateralManager — manage and monitor collateral deposits across the
DeFi layer.  Tracks per-user balances, computes health factors, and
uses the oracle gateway (Component 11) for real-time price checks.
"""

from __future__ import annotations

import logging
import math
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
        # DOMAIN 16-A — NaN IS FALSE AGAINST EVERY COMPARISON, INCLUDING THIS ONE.
        # Must precede the sign check: `amount <= 0` answers False for NaN, so a
        # NaN deposit was accepted, returned status "deposited" with
        # new_balance=NaN, and poisoned the collateral ledger. Driven.
        if not math.isfinite(amount):
            raise ValueError("Deposit amount must be a finite number")
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
        # DOMAIN 16-A — the withdrawal twin. BOTH sides of the ledger need the
        # guard: `amount <= 0` AND `amount > current` are both False for NaN, so
        # a NaN withdrawal walked the sign check AND the sufficiency check.
        # Fixing deposit alone would leave the drain open.
        if not math.isfinite(amount):
            raise ValueError("Withdrawal amount must be a finite number")
        if amount <= 0:
            raise ValueError("Withdrawal amount must be positive")

        user_balances = self._balances.get(user, {})
        current = user_balances.get(token, 0)
        if amount > current:
            raise ValueError(
                f"Insufficient balance. Have {current:.6f} {token}, "
                f"requested {amount:.6f}"
            )

        # NEW-55c: compute health BEFORE mutating the balance, not after.
        #
        # The old code debited first (`user_balances[token] = current -
        # amount`) and then health-checked inside a try whose except was a
        # no-op that only LOOKED like a revert:
        #     except Exception:
        #         if user_balances.get(token, -1) == current - amount:
        #             pass          # <- does nothing
        #         raise
        # So ANY exception from the health check — the old str/float TypeError,
        # and now the fail-closed price ValueError this commit introduces —
        # left the balance debited with no withdrawal performed. My own
        # fail-closed price fix would have MOVED that destruction to a new
        # trigger rather than removing it, so both halves must land together.
        #
        # The check now runs against a SIMULATED post-withdrawal balance
        # without touching the real ledger; the real debit happens only after
        # the position is proven safe. Any exception (including an
        # unpriceable-token ValueError) propagates with the ledger untouched.
        simulated = dict(user_balances)
        simulated[token] = current - amount
        health = await self._compute_health_factor(user, balances_override={user: simulated})
        if health["health_factor"] < _DANGER_THRESHOLD and health["total_borrows_usd"] > 0:
            raise ValueError(
                f"Withdrawal would drop health factor to "
                f"{health['health_factor']:.2f}, below minimum "
                f"{_DANGER_THRESHOLD:.2f}"
            )

        # Safe: commit the debit.
        user_balances[token] = current - amount

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

    def set_borrow_position(self, user: str, token: str, principal: float) -> None:
        """Set the recorded borrow position from the AUTHORITATIVE loan state.

        DOMAIN 16-C. This replaces `record_repayment(user, token, amount)`, which
        decremented by the payment: `user_borrows[token] = max(0, current - amount)`.

        THE DEFECT WAS A DELTA BETWEEN TWO LEDGERS OF THE SAME DEBT.
        `record_borrow` recorded PRINCIPAL. The caller then decremented by
        `repaid_amount`, the PAYMENT — and `repay_loan` applies payment to
        INTEREST FIRST, so the two quantities are not the same thing. Driven:

            borrow 1000 principal, accrue 20.19 interest, repay 1000
            -> loan:      ACTIVE, 20.19 still owed   (correct)
            -> ledger:    max(0, 1000 - 1000) = 0    (wrong)
            -> health:    "no_borrows", factor Infinity, total_borrows_usd 0.0
            -> withdraw:  ALL 10 ETH released while 20.19 USDC is still owed

        No malformed input. No NaN. An ordinary partial repayment.

        WHY SET AND NOT DECREMENT: a delta can drift from its source; an
        assignment cannot. `repay_loan` already returns `remaining_principal`,
        so the authoritative number exists and there is no reason to recompute
        it here. The class of bug this closes is not "the subtraction was wrong"
        but "there were two ledgers and only one of them was right".

        RENAMED RATHER THAN ADDED. Leaving `record_repayment` beside a correct
        twin would be the `set_balance` / `migrate_members` shape — an
        unattended primitive one line from live, and the wrong one is the one
        with the friendlier name.
        """
        if not math.isfinite(principal):
            raise ValueError("Borrow position must be a finite number")
        self._borrows.setdefault(user, {})[token] = max(0.0, float(principal))

    # ── Internal helpers ──────────────────────────────────────────────

    async def _compute_health_factor(
        self,
        user: str,
        balances_override: dict[str, dict[str, float]] | None = None,
    ) -> dict[str, Any]:
        """Compute the health factor for a user.

        NEW-55c: ``balances_override`` lets a caller evaluate a HYPOTHETICAL
        position (e.g. the post-withdrawal state) without mutating the real
        ledger, so a pre-check can be done before committing any balance
        change. When omitted, the real balances are used.
        """
        source = balances_override if balances_override is not None else self._balances
        balances = source.get(user, {})
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
            # NEW-55c: was `round(hf, 4) if hf != inf else "inf"` — the
            # returned value was a STRING "inf" while the internal value was a
            # float. `withdraw` reads this dict and does
            # `health["health_factor"] < _DANGER_THRESHOLD`, so on any
            # no-borrows position it compared str < float and raised TypeError
            # BEFORE the `total_borrows_usd > 0` guard could run — and
            # withdraw debits the balance before that comparison, so the
            # TypeError left the collateral debited with no withdrawal
            # performed (demonstrated: deposit 10, withdraw 4, balance -> 6).
            #
            # The returned type now matches what the comparison expects: a
            # real float (float("inf") for the no-borrows case). A human-
            # readable label lives in a SEPARATE key so no consumer has to
            # special-case a string in a numeric field.
            "health_factor": round(health_factor, 4) if health_factor != float("inf") else float("inf"),
            "health_factor_display": "∞" if health_factor == float("inf") else f"{health_factor:.4f}",
            "status": status,
            "total_collateral_usd": round(total_collateral_usd, 2),
            "risk_adjusted_collateral_usd": round(risk_adjusted_usd, 2),
            "total_borrows_usd": round(total_borrows_usd, 2),
            "balances": dict(balances),
            "borrows": dict(borrows),
        }

    def _resolve_oracle(self) -> Any:
        """Lazily resolve the OracleGateway (NEW-59).

        DeFiService injects this in lockstep, but CollateralManager can also
        be constructed standalone, so it resolves its own if none was passed —
        the same registry-DI-gap fix, so this path is never left oracle-blind.
        """
        if self._oracle is None:
            from runtime.blockchain.services.oracle_gateway import OracleGateway
            self._oracle = OracleGateway(self._config)
        return self._oracle

    async def _get_price(self, token: str) -> float:
        """Get token price. FAILS CLOSED on a missing price (NEW-55b).

        Was the fail-OPEN half of the price root: on an unpriceable token this
        returned 0.0 (with a warning). Because this method feeds
        _compute_health_factor, a 0.0 price on the DEBT side drove
        total_borrows_usd to zero -> the "no_borrows" branch -> the "inf"
        health factor -> withdraw's collateral-destruction path. Its sibling
        DeFiService._get_token_price RAISED on the same condition; the two
        files handled the identical missing input opposite ways, and only the
        fail-open one touched a money path.

        Now it raises, matching the sibling. Stablecoins still resolve to 1.0
        (an accurate value, not a fabricated one); a genuinely configured
        fallback still applies; but an UNKNOWN price stops the calculation
        instead of silently valuing collateral or debt at zero.
        """
        oracle = self._resolve_oracle()
        if oracle is not None:
            try:
                pair = f"{token}/USD"
                result = await oracle.request(
                    "price_feed",
                    {"pair": pair},
                    caller="collateral_manager",
                )
                price = result.get("price", 0)
                if price > 0:
                    return float(price)
            except Exception as exc:
                logger.warning(
                    "Oracle price fetch failed for %s: %s, trying fallback",
                    token, exc,
                )

        # Configured fallback (a real operator-set value).
        fallback = self._fallback_prices.get(token)
        if fallback is not None:
            return float(fallback)

        # Stablecoin par is accurate, not fabricated.
        if token in ("USDC", "USDT", "DAI"):
            return 1.0

        # FAIL CLOSED: an unknown price must stop the calculation, never
        # value the position at zero on a money path.
        raise ValueError(
            f"No price available for {token}. Configure the oracle or set "
            f"defi.fallback_prices.{token} in config. Refusing to value "
            f"collateral or debt at zero."
        )
