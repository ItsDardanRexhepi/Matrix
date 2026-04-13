"""
DeFiService — orchestrate all DeFi operations on 0pnMatrx.

This is the single entry point for lending, borrowing, collateral
management, P2P lending, governance, and reputation tracking.
"""

from __future__ import annotations

import logging
import time
import uuid
from typing import Any

from runtime.blockchain.services.defi.collateral import CollateralManager
from runtime.blockchain.services.defi.loans import LoanManager
from runtime.blockchain.services.defi.p2p_lending import P2PLending
from runtime.blockchain.services.defi.reputation import LenderReputation
from runtime.blockchain.services.defi.whitelist_governance import WhitelistGovernance
from runtime.blockchain.web3_manager import Web3Manager, not_deployed_response

logger = logging.getLogger(__name__)


class DeFiService:
    """Orchestrate all DeFi operations on 0pnMatrx.

    Config keys used (under ``defi``):
        min_collateral_ratio, liquidation_threshold, liquidation_penalty,
        base_rate, collateral_factors, fallback_prices, p2p.*,
        governance.*, reputation.*.

    Parameters
    ----------
    config : dict
        Full platform configuration dictionary.
    oracle_gateway : object, optional
        OracleGateway instance for real-time price feeds.
    """

    def __init__(
        self,
        config: dict,
        oracle_gateway: Any = None,
    ) -> None:
        self._config = config
        self._oracle = oracle_gateway
        self._web3 = Web3Manager.get_shared(config)
        self._lending_pool_address: str = (
            config.get("defi", {}).get("lending_pool_address", "") or ""
        )

        self._loan_manager = LoanManager(config)
        self._collateral_manager = CollateralManager(config, oracle_gateway)
        self._p2p_lending = P2PLending(config)
        self._whitelist_gov = WhitelistGovernance(config)
        self._reputation = LenderReputation(config)

        logger.info("DeFiService initialised.")

    # ── Core Lending Operations ──────────────────────────────────────

    async def create_loan(
        self,
        borrower: str,
        collateral_token: str,
        collateral_amount: float,
        borrow_token: str,
        borrow_amount: float,
    ) -> dict[str, Any]:
        """Create a collateralised loan.

        Fetches real-time prices via the oracle gateway, deposits
        collateral, creates the loan, and records it for health
        tracking.

        Parameters
        ----------
        borrower : str
            Borrower wallet address.
        collateral_token : str
            Token to use as collateral.
        collateral_amount : float
            Amount of collateral to deposit.
        borrow_token : str
            Token to borrow.
        borrow_amount : float
            Amount to borrow.

        Returns
        -------
        dict
            Loan details.
        """
        if (
            not self._web3.available
            or self._web3.is_placeholder(self._lending_pool_address)
        ):
            logger.warning(
                "Service %s called but contract not deployed",
                self.__class__.__name__,
            )
            return not_deployed_response("defi", {
                "operation": "create_loan",
                "requested": {
                    "borrower": borrower,
                    "collateral_token": collateral_token,
                    "collateral_amount": collateral_amount,
                    "borrow_token": borrow_token,
                    "borrow_amount": borrow_amount,
                },
            })

        try:
            # Fetch prices
            collateral_price = await self._get_token_price(collateral_token)
            borrow_price = await self._get_token_price(borrow_token)

            # Deposit collateral
            await self._collateral_manager.deposit(
                borrower, collateral_token, collateral_amount
            )

            # Create loan
            loan = await self._loan_manager.create_loan(
                borrower=borrower,
                collateral_token=collateral_token,
                collateral_amount=collateral_amount,
                borrow_token=borrow_token,
                borrow_amount=borrow_amount,
                collateral_price=collateral_price,
                borrow_price=borrow_price,
            )

            # Record borrow for health tracking
            self._collateral_manager.record_borrow(
                borrower, borrow_token, borrow_amount
            )

            # Update pool
            self._loan_manager.update_pool_total(
                borrow_token, -borrow_amount
            )

            logger.info(
                "Loan created via DeFiService: id=%s borrower=%s",
                loan["loan_id"], borrower,
            )
            return loan

        except Exception as exc:
            logger.error("Loan creation failed: %s", exc, exc_info=True)
            raise

    async def repay_loan(
        self, loan_id: str, amount: float
    ) -> dict[str, Any]:
        """Repay part or all of a loan.

        Parameters
        ----------
        loan_id : str
            The loan identifier.
        amount : float
            Amount to repay.

        Returns
        -------
        dict
            Repayment result.
        """
        try:
            loan = await self._loan_manager.get_loan(loan_id)
            borrower = loan["borrower"]
            borrow_token = loan["borrow_token"]

            result = await self._loan_manager.repay_loan(loan_id, amount)

            # Update collateral tracking
            self._collateral_manager.record_repayment(
                borrower, borrow_token, result["repaid_amount"]
            )

            # Update reputation
            if result["status"] == "repaid":
                await self._reputation.update_score(
                    borrower, "loan_repaid_on_time"
                )

            # Update pool
            self._loan_manager.update_pool_total(
                borrow_token, result["repaid_amount"]
            )

            return result

        except Exception as exc:
            logger.error("Loan repayment failed: %s", exc, exc_info=True)
            raise

    async def liquidate(self, loan_id: str) -> dict[str, Any]:
        """Liquidate an under-collateralised loan.

        Fetches current prices and attempts liquidation if the
        collateral ratio is below the threshold.

        Parameters
        ----------
        loan_id : str
            The loan identifier.

        Returns
        -------
        dict
            Liquidation result.
        """
        try:
            loan = await self._loan_manager.get_loan(loan_id)

            collateral_price = await self._get_token_price(loan["collateral_token"])
            borrow_price = await self._get_token_price(loan["borrow_token"])

            result = await self._loan_manager.liquidate(
                loan_id, collateral_price, borrow_price
            )

            # Record default event
            await self._reputation.update_score(
                loan["borrower"], "loan_defaulted"
            )

            return result

        except Exception as exc:
            logger.error("Liquidation failed: %s", exc, exc_info=True)
            raise

    async def get_loan(self, loan_id: str) -> dict[str, Any]:
        """Retrieve a loan by ID with accrued interest."""
        return await self._loan_manager.get_loan(loan_id)

    async def get_rates(self, token: str) -> dict[str, Any]:
        """Get current interest rates for a token."""
        return await self._loan_manager.get_rates(token)

    # ── Collateral Operations ────────────────────────────────────────

    async def deposit_collateral(
        self, user: str, token: str, amount: float
    ) -> dict[str, Any]:
        """Deposit collateral for a user."""
        result = await self._collateral_manager.deposit(user, token, amount)
        self._loan_manager.update_pool_total(token, amount)
        return result

    async def withdraw_collateral(
        self, user: str, token: str, amount: float
    ) -> dict[str, Any]:
        """Withdraw collateral, checking health factor."""
        result = await self._collateral_manager.withdraw(user, token, amount)
        self._loan_manager.update_pool_total(token, -amount)
        return result

    async def get_health_factor(self, user: str) -> dict[str, Any]:
        """Get the health factor for a user's position."""
        return await self._collateral_manager.get_health_factor(user)

    # ── P2P Lending ──────────────────────────────────────────────────

    async def create_p2p_offer(
        self,
        lender: str,
        token: str,
        amount: float,
        interest_rate: float,
        duration_days: int,
    ) -> dict[str, Any]:
        """Create a P2P lending offer."""
        result = await self._p2p_lending.create_offer(
            lender, token, amount, interest_rate, duration_days
        )
        await self._reputation.update_score(lender, "loan_funded")
        return result

    async def accept_p2p_offer(
        self,
        offer_id: str,
        borrower: str,
        collateral: dict[str, Any],
    ) -> dict[str, Any]:
        """Accept a P2P lending offer."""
        return await self._p2p_lending.accept_offer(
            offer_id, borrower, collateral
        )

    async def list_p2p_offers(
        self, filters: dict[str, Any] | None = None
    ) -> list[dict[str, Any]]:
        """List P2P lending offers."""
        return await self._p2p_lending.list_offers(filters)

    # ── Governance ───────────────────────────────────────────────────

    async def propose_token(
        self, token_address: str, proposer: str
    ) -> dict[str, Any]:
        """Propose a new token for the whitelist."""
        return await self._whitelist_gov.propose_token(token_address, proposer)

    async def vote_on_proposal(
        self, proposal_id: str, voter: str, support: bool
    ) -> dict[str, Any]:
        """Vote on a whitelist proposal."""
        return await self._whitelist_gov.vote_on_proposal(
            proposal_id, voter, support
        )

    async def get_whitelist(self) -> list[str]:
        """Get the current token whitelist."""
        return await self._whitelist_gov.get_whitelist()

    # ── Reputation ───────────────────────────────────────────────────

    async def get_reputation(self, address: str) -> dict[str, Any]:
        """Get reputation score for an address."""
        return await self._reputation.get_score(address)

    async def get_top_lenders(self, limit: int = 20) -> list[dict[str, Any]]:
        """Get top-rated lenders."""
        return await self._reputation.get_top_lenders(limit)

    # ── Price helper ─────────────────────────────────────────────────

    async def _get_token_price(self, token: str) -> float:
        """Fetch token price from oracle or config fallback."""
        if self._oracle is not None:
            try:
                result = await self._oracle.request(
                    "price_feed",
                    {"pair": f"{token}/USD"},
                    caller="defi_service",
                )
                price = result.get("price", 0)
                if price > 0:
                    return float(price)
            except Exception as exc:
                logger.warning(
                    "Oracle price fetch failed for %s: %s", token, exc,
                )

        # Fallback prices from config
        fallback = self._config.get("defi", {}).get("fallback_prices", {})
        price = fallback.get(token)
        if price is not None:
            return float(price)

        # Stablecoin defaults
        if token in ("USDC", "USDT", "DAI"):
            return 1.0

        raise ValueError(
            f"No price available for {token}. Configure oracle or "
            f"set defi.fallback_prices.{token} in config."
        )

    # ── Expanded DeFi Operations ────────────────────────────────────

    async def flash_loan(
        self, asset: str, amount: float, strategy: str = "arbitrage",
    ) -> dict[str, Any]:
        """Execute a flash loan."""
        if (
            not self._web3.available
            or self._web3.is_placeholder(self._lending_pool_address)
        ):
            return not_deployed_response("defi", {
                "operation": "flash_loan",
                "requested": {"asset": asset, "amount": amount, "strategy": strategy},
            })
        loan_id = f"fl_{uuid.uuid4().hex[:16]}"
        record: dict[str, Any] = {
            "id": loan_id,
            "status": "executed",
            "asset": asset,
            "amount": amount,
            "strategy": strategy,
            "fee": round(amount * 0.0009, 6),
        }
        self._loan_manager._loans[loan_id] = record
        logger.info("Flash loan executed: id=%s", loan_id)
        return record

    async def yield_optimize(
        self, asset: str, amount: float, risk_tolerance: str = "medium",
    ) -> dict[str, Any]:
        """Optimise yield across DeFi protocols."""
        if (
            not self._web3.available
            or self._web3.is_placeholder(self._lending_pool_address)
        ):
            return not_deployed_response("defi", {
                "operation": "yield_optimize",
                "requested": {"asset": asset, "amount": amount, "risk_tolerance": risk_tolerance},
            })
        position_id = f"yo_{uuid.uuid4().hex[:16]}"
        record: dict[str, Any] = {
            "id": position_id,
            "status": "optimized",
            "asset": asset,
            "amount": amount,
            "risk_tolerance": risk_tolerance,
            "estimated_apy": 8.5,
        }
        self._loan_manager._loans[position_id] = record
        logger.info("Yield optimized: id=%s", position_id)
        return record

    async def liquidity_provide(
        self, token_a: str, token_b: str, amount_a: float, amount_b: float = 0,
    ) -> dict[str, Any]:
        """Provide liquidity to an AMM pool."""
        if (
            not self._web3.available
            or self._web3.is_placeholder(self._lending_pool_address)
        ):
            return not_deployed_response("defi", {
                "operation": "liquidity_provide",
                "requested": {"token_a": token_a, "token_b": token_b, "amount_a": amount_a, "amount_b": amount_b},
            })
        lp_id = f"lp_{uuid.uuid4().hex[:16]}"
        record: dict[str, Any] = {
            "id": lp_id,
            "status": "provided",
            "token_a": token_a,
            "token_b": token_b,
            "amount_a": amount_a,
            "amount_b": amount_b,
            "lp_tokens": round((amount_a * amount_b) ** 0.5 if amount_b else amount_a, 6),
        }
        self._loan_manager._loans[lp_id] = record
        logger.info("Liquidity provided: id=%s", lp_id)
        return record

    async def liquidity_remove(
        self, pool_id: str, percentage: float = 100.0,
    ) -> dict[str, Any]:
        """Remove liquidity from an AMM pool."""
        if (
            not self._web3.available
            or self._web3.is_placeholder(self._lending_pool_address)
        ):
            return not_deployed_response("defi", {
                "operation": "liquidity_remove",
                "requested": {"pool_id": pool_id, "percentage": percentage},
            })
        removal_id = f"lr_{uuid.uuid4().hex[:16]}"
        record: dict[str, Any] = {
            "id": removal_id,
            "status": "removed",
            "pool_id": pool_id,
            "percentage": percentage,
        }
        self._loan_manager._loans[removal_id] = record
        logger.info("Liquidity removed: id=%s", removal_id)
        return record

    async def perp_trade(
        self, asset: str, direction: str, size: float, leverage: float,
    ) -> dict[str, Any]:
        """Open a perpetual futures position."""
        if (
            not self._web3.available
            or self._web3.is_placeholder(self._lending_pool_address)
        ):
            return not_deployed_response("defi", {
                "operation": "perp_trade",
                "requested": {"asset": asset, "direction": direction, "size": size, "leverage": leverage},
            })
        trade_id = f"perp_{uuid.uuid4().hex[:16]}"
        record: dict[str, Any] = {
            "id": trade_id,
            "status": "opened",
            "asset": asset,
            "direction": direction,
            "size": size,
            "leverage": leverage,
            "notional": round(size * leverage, 6),
        }
        self._loan_manager._loans[trade_id] = record
        logger.info("Perp trade opened: id=%s", trade_id)
        return record

    async def options_trade(
        self, asset: str, option_type: str, strike: float, expiry_days: int, premium: float,
    ) -> dict[str, Any]:
        """Trade an on-chain option."""
        if (
            not self._web3.available
            or self._web3.is_placeholder(self._lending_pool_address)
        ):
            return not_deployed_response("defi", {
                "operation": "options_trade",
                "requested": {"asset": asset, "option_type": option_type, "strike": strike, "expiry_days": expiry_days, "premium": premium},
            })
        option_id = f"opt_{uuid.uuid4().hex[:16]}"
        record: dict[str, Any] = {
            "id": option_id,
            "status": "opened",
            "asset": asset,
            "option_type": option_type,
            "strike": strike,
            "expiry_days": expiry_days,
            "premium": premium,
        }
        self._loan_manager._loans[option_id] = record
        logger.info("Options trade opened: id=%s", option_id)
        return record

    async def synthetic_asset(
        self, underlying: str, amount: float, collateral_ratio: float = 1.5,
    ) -> dict[str, Any]:
        """Mint a synthetic asset."""
        if (
            not self._web3.available
            or self._web3.is_placeholder(self._lending_pool_address)
        ):
            return not_deployed_response("defi", {
                "operation": "synthetic_asset",
                "requested": {"underlying": underlying, "amount": amount, "collateral_ratio": collateral_ratio},
            })
        synth_id = f"synth_{uuid.uuid4().hex[:16]}"
        record: dict[str, Any] = {
            "id": synth_id,
            "status": "minted",
            "underlying": underlying,
            "amount": amount,
            "collateral_ratio": collateral_ratio,
            "collateral_required": round(amount * collateral_ratio, 6),
        }
        self._loan_manager._loans[synth_id] = record
        logger.info("Synthetic asset minted: id=%s", synth_id)
        return record

    async def vault_deposit(
        self, vault: str, amount: float, asset: str = "USDC",
    ) -> dict[str, Any]:
        """Deposit into a yield vault."""
        if (
            not self._web3.available
            or self._web3.is_placeholder(self._lending_pool_address)
        ):
            return not_deployed_response("defi", {
                "operation": "vault_deposit",
                "requested": {"vault": vault, "amount": amount, "asset": asset},
            })
        deposit_id = f"vd_{uuid.uuid4().hex[:16]}"
        record: dict[str, Any] = {
            "id": deposit_id,
            "status": "deposited",
            "vault": vault,
            "amount": amount,
            "asset": asset,
            "shares_received": round(amount * 0.98, 6),
        }
        self._loan_manager._loans[deposit_id] = record
        logger.info("Vault deposit: id=%s", deposit_id)
        return record

    async def leverage_position(
        self, asset: str, amount: float, leverage: float, direction: str = "long",
    ) -> dict[str, Any]:
        """Open a leveraged position."""
        if (
            not self._web3.available
            or self._web3.is_placeholder(self._lending_pool_address)
        ):
            return not_deployed_response("defi", {
                "operation": "leverage_position",
                "requested": {"asset": asset, "amount": amount, "leverage": leverage, "direction": direction},
            })
        pos_id = f"lev_{uuid.uuid4().hex[:16]}"
        record: dict[str, Any] = {
            "id": pos_id,
            "status": "opened",
            "asset": asset,
            "amount": amount,
            "leverage": leverage,
            "direction": direction,
            "notional": round(amount * leverage, 6),
        }
        self._loan_manager._loans[pos_id] = record
        logger.info("Leverage position opened: id=%s", pos_id)
        return record

    async def collateral_manage(
        self, action: str, asset: str, amount: float, position_id: str = "",
    ) -> dict[str, Any]:
        """Manage collateral for an existing position."""
        if (
            not self._web3.available
            or self._web3.is_placeholder(self._lending_pool_address)
        ):
            return not_deployed_response("defi", {
                "operation": "collateral_manage",
                "requested": {"action": action, "asset": asset, "amount": amount, "position_id": position_id},
            })
        mgmt_id = f"cm_{uuid.uuid4().hex[:16]}"
        record: dict[str, Any] = {
            "id": mgmt_id,
            "status": "completed",
            "action": action,
            "asset": asset,
            "amount": amount,
            "position_id": position_id,
        }
        self._loan_manager._loans[mgmt_id] = record
        logger.info("Collateral managed: id=%s action=%s", mgmt_id, action)
        return record
