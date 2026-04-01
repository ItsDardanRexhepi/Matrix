"""
StablecoinService -- core stablecoin operations for 0pnMatrx.

Handles transfers with tiered fees, balance queries, and integrates
with the BalanceTracker and TransferRateLimiter for lifetime tracking
and abuse prevention.
"""

from __future__ import annotations

import hashlib
import logging
import time
import uuid
from typing import Any

from runtime.blockchain.services.stablecoin.balance_tracker import LifetimeBalanceTracker
from runtime.blockchain.services.stablecoin.rate_limiter import TransferRateLimiter

logger = logging.getLogger(__name__)

# Tiered fee schedule: (threshold_upper, rate)
# Amount < 1K  -> 0.1%
# 1K - 10K     -> 0.05%
# 10K - 100K   -> 0.025%
# > 100K       -> 0.01%
DEFAULT_FEE_TIERS: list[tuple[float, float]] = [
    (1_000.0, 0.001),
    (10_000.0, 0.0005),
    (100_000.0, 0.00025),
    (float("inf"), 0.0001),
]

SUPPORTED_TOKENS: set[str] = {"USDC", "USDT", "DAI", "FRAX", "PYUSD"}


class StablecoinService:
    """
    Main stablecoin service for the 0pnMatrx platform.

    Config keys used (under config["stablecoin"] or config["blockchain"]):
        platform_wallet     -- address that collects fees
        supported_tokens    -- optional override of accepted token symbols
        fee_tiers           -- optional override of tiered fee schedule
        rate_limits         -- optional per-tier rate limit overrides
    """

    def __init__(self, config: dict[str, Any]) -> None:
        self.config = config
        sc = config.get("stablecoin", {})
        bc = config.get("blockchain", {})

        self.platform_wallet: str = sc.get(
            "platform_wallet", bc.get("platform_wallet", "0x0000000000000000000000000000000000000001")
        )
        self.supported_tokens: set[str] = set(
            sc.get("supported_tokens", SUPPORTED_TOKENS)
        )
        self.fee_tiers: list[tuple[float, float]] = sc.get("fee_tiers", DEFAULT_FEE_TIERS)

        # Sub-components
        self._balance_tracker = LifetimeBalanceTracker(config)
        self._rate_limiter = TransferRateLimiter(config)

        # In-memory ledger: address -> token -> balance
        self._balances: dict[str, dict[str, float]] = {}
        # Transfer log
        self._transfers: list[dict[str, Any]] = []

        logger.info(
            "StablecoinService initialised: platform_wallet=%s tokens=%s",
            self.platform_wallet,
            self.supported_tokens,
        )

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    async def transfer(
        self,
        token: str,
        from_addr: str,
        to_addr: str,
        amount: float,
    ) -> dict[str, Any]:
        """
        Execute a stablecoin transfer with tiered fees.

        The fee is deducted from the transfer amount and sent to the
        platform wallet. The recipient receives (amount - fee).

        Args:
            token: Token symbol (e.g. "USDC").
            from_addr: Sender address.
            to_addr: Recipient address.
            amount: Transfer amount in token units.

        Returns:
            Dict with transfer details including fee, net amount, and tx id.
        """
        token = token.upper()

        # Validation
        if token not in self.supported_tokens:
            return {
                "status": "error",
                "error": f"Unsupported token: {token}. Supported: {sorted(self.supported_tokens)}",
            }

        if amount <= 0:
            return {"status": "error", "error": "Amount must be positive"}

        if from_addr == to_addr:
            return {"status": "error", "error": "Sender and recipient must differ"}

        # Check sender balance
        sender_balance = self._balances.get(from_addr, {}).get(token, 0.0)
        if sender_balance < amount:
            return {
                "status": "error",
                "error": f"Insufficient balance: {sender_balance:.6f} {token} < {amount:.6f} {token}",
            }

        # Rate limit check
        rate_check = await self._rate_limiter.check_limit(from_addr, amount)
        if not rate_check["allowed"]:
            logger.warning(
                "Transfer blocked by rate limiter: address=%s amount=%.2f reason=%s",
                from_addr, amount, rate_check.get("reason", "limit exceeded"),
            )
            return {
                "status": "blocked",
                "error": "Rate limit exceeded",
                "details": rate_check,
            }

        # Calculate fee
        fee_info = await self.get_fee(amount)
        fee = fee_info["fee"]
        net_amount = amount - fee

        # Execute the transfer
        transfer_id = self._generate_transfer_id(from_addr, to_addr, amount, token)

        # Debit sender
        self._balances.setdefault(from_addr, {})[token] = sender_balance - amount

        # Credit recipient
        recipient_balance = self._balances.get(to_addr, {}).get(token, 0.0)
        self._balances.setdefault(to_addr, {})[token] = recipient_balance + net_amount

        # Credit fee to platform wallet
        platform_balance = self._balances.get(self.platform_wallet, {}).get(token, 0.0)
        self._balances.setdefault(self.platform_wallet, {})[token] = platform_balance + fee

        timestamp = int(time.time())

        # Record in balance tracker
        await self._balance_tracker.record_transfer(from_addr, token, amount, "outflow")
        await self._balance_tracker.record_transfer(to_addr, token, net_amount, "inflow")
        if fee > 0:
            await self._balance_tracker.record_transfer(
                self.platform_wallet, token, fee, "inflow"
            )

        # Record in rate limiter
        await self._rate_limiter.record_transfer(from_addr, amount)

        transfer_record = {
            "transfer_id": transfer_id,
            "status": "completed",
            "token": token,
            "from": from_addr,
            "to": to_addr,
            "amount": round(amount, 6),
            "fee": round(fee, 6),
            "fee_rate": fee_info["rate"],
            "fee_tier": fee_info["tier"],
            "net_amount": round(net_amount, 6),
            "fee_recipient": self.platform_wallet,
            "timestamp": timestamp,
        }
        self._transfers.append(transfer_record)

        logger.info(
            "Transfer completed: id=%s %s %.6f %s -> %s (fee=%.6f, net=%.6f)",
            transfer_id, token, amount, from_addr, to_addr, fee, net_amount,
        )
        return transfer_record

    async def get_balance(
        self,
        address: str,
        token: str | None = None,
    ) -> dict[str, Any]:
        """
        Get balance for an address, optionally filtered by token.

        Args:
            address: Wallet address.
            token: Optional token symbol. If None, returns all token balances.

        Returns:
            Dict with address and balance information.
        """
        all_balances = self._balances.get(address, {})

        if token is not None:
            token = token.upper()
            balance = all_balances.get(token, 0.0)
            return {
                "address": address,
                "token": token,
                "balance": round(balance, 6),
            }

        return {
            "address": address,
            "balances": {t: round(b, 6) for t, b in all_balances.items()},
            "token_count": len(all_balances),
        }

    async def get_fee(self, amount: float) -> dict[str, Any]:
        """
        Calculate the transfer fee for a given amount using tiered schedule.

        Args:
            amount: Transfer amount.

        Returns:
            Dict with fee amount, rate, and tier description.
        """
        if amount <= 0:
            return {"fee": 0.0, "rate": 0.0, "tier": "invalid", "amount": amount}

        for threshold, rate in self.fee_tiers:
            if amount < threshold:
                fee = amount * rate
                tier = self._tier_label(threshold)
                return {
                    "amount": round(amount, 6),
                    "fee": round(fee, 6),
                    "rate": rate,
                    "rate_pct": f"{rate * 100:.4f}%",
                    "tier": tier,
                }

        # Fallback to lowest tier
        rate = self.fee_tiers[-1][1]
        return {
            "amount": round(amount, 6),
            "fee": round(amount * rate, 6),
            "rate": rate,
            "rate_pct": f"{rate * 100:.4f}%",
            "tier": "maximum",
        }

    def set_balance(self, address: str, token: str, amount: float) -> None:
        """Set a balance directly (for funding/testing)."""
        token = token.upper()
        self._balances.setdefault(address, {})[token] = amount
        logger.debug("Balance set: %s %s = %.6f", address, token, amount)

    # ------------------------------------------------------------------
    # Internals
    # ------------------------------------------------------------------

    @staticmethod
    def _generate_transfer_id(
        from_addr: str, to_addr: str, amount: float, token: str
    ) -> str:
        raw = f"{from_addr}:{to_addr}:{amount}:{token}:{time.time()}:{uuid.uuid4().hex}"
        return "tx_" + hashlib.sha256(raw.encode()).hexdigest()[:24]

    @staticmethod
    def _tier_label(threshold: float) -> str:
        if threshold <= 1_000:
            return "micro (<1K)"
        if threshold <= 10_000:
            return "small (1K-10K)"
        if threshold <= 100_000:
            return "medium (10K-100K)"
        return "large (>100K)"
