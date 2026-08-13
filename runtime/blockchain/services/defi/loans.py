"""
LoanManager — manage lending positions with collateralisation tracking,
variable interest rates, and auto-liquidation triggers.

Collateralisation rules:
  - Minimum ratio: 150% (loan creation)
  - Liquidation trigger: below 120%
  - Interest rate: variable, based on pool utilisation
"""

from __future__ import annotations

import logging
import math
import time
import uuid
from enum import Enum
from typing import Any

from runtime.blockchain.web3_manager import Web3Manager, not_deployed_response

logger = logging.getLogger(__name__)


class LoanStatus(str, Enum):
    ACTIVE = "active"
    REPAID = "repaid"
    LIQUIDATED = "liquidated"
    DEFAULTED = "defaulted"


# Interest rate model parameters
_BASE_RATE = 0.02         # 2% base annual rate
_SLOPE_1 = 0.04           # slope below optimal utilisation
_SLOPE_2 = 0.75           # slope above optimal utilisation
_OPTIMAL_UTILISATION = 0.8  # 80% optimal utilisation

# Collateralisation thresholds
_MIN_COLLATERAL_RATIO = 1.5    # 150%
_LIQUIDATION_THRESHOLD = 1.2   # 120%
_LIQUIDATION_PENALTY = 0.05    # 5% penalty


class LoanManager:
    """Manage lending positions with collateral tracking.

    Parameters
    ----------
    config : dict
        Platform config.  Reads:
        - ``defi.min_collateral_ratio`` (default 1.5)
        - ``defi.liquidation_threshold`` (default 1.2)
        - ``defi.liquidation_penalty`` (default 0.05)
        - ``defi.base_rate`` (default 0.02)
    """

    def __init__(self, config: dict) -> None:
        self._config = config
        defi_cfg = config.get("defi", {})

        self._min_collateral_ratio: float = float(
            defi_cfg.get("min_collateral_ratio", _MIN_COLLATERAL_RATIO)
        )
        self._liquidation_threshold: float = float(
            defi_cfg.get("liquidation_threshold", _LIQUIDATION_THRESHOLD)
        )
        self._liquidation_penalty: float = float(
            defi_cfg.get("liquidation_penalty", _LIQUIDATION_PENALTY)
        )
        self._base_rate: float = float(
            defi_cfg.get("base_rate", _BASE_RATE)
        )
        self._lending_pool_address: str = (
            defi_cfg.get("lending_pool_address", "") or ""
        )

        self._web3 = Web3Manager.get_shared(config)

        # In-memory loan storage (used only when contracts are not deployed)
        self._loans: dict[str, dict[str, Any]] = {}
        # Pool utilisation tracking per token
        self._pool_total: dict[str, float] = {}     # total deposited
        self._pool_borrowed: dict[str, float] = {}   # total borrowed

    async def create_loan(
        self,
        borrower: str,
        collateral_token: str,
        collateral_amount: float,
        borrow_token: str,
        borrow_amount: float,
        collateral_price: float,
        borrow_price: float,
    ) -> dict[str, Any]:
        """Create a new loan position.

        Parameters
        ----------
        borrower : str
            Borrower wallet address.
        collateral_token : str
            Token used as collateral.
        collateral_amount : float
            Amount of collateral deposited.
        borrow_token : str
            Token being borrowed.
        borrow_amount : float
            Amount to borrow.
        collateral_price : float
            Current USD price of collateral token.
        borrow_price : float
            Current USD price of borrow token.

        Returns
        -------
        dict
            Loan details including ``loan_id``, ``collateral_ratio``,
            ``interest_rate``, ``status``.

        Raises
        ------
        ValueError
            If collateralisation ratio is below minimum.
        """
        # DOMAIN 16-A — ARMED BY DEPLOYMENT. Under the shipped config the gate
        # below returns not_deployed and nothing here runs; the moment contracts
        # are deployed this becomes the live borrow path, and NaN walked ALL of
        # it. Driven against a simulated-deployed install: a NaN collateral
        # amount passed this sign check, passed the deployment gate, and then
        # passed the MINIMUM-COLLATERALISATION check below — issuing a real
        # 1000 USDC loan with collateral_ratio recorded as NaN.
        #
        # THAT IS THE PRIMARY SAFETY PROPERTY OF A LENDING PROTOCOL. It is not
        # defeated by a clever exploit; it is defeated by a value for which every
        # `<` answers False.
        if not math.isfinite(collateral_amount) or not math.isfinite(borrow_amount):
            raise ValueError("Amounts must be finite numbers")

        if collateral_amount <= 0 or borrow_amount <= 0:
            raise ValueError("Amounts must be positive")

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

        collateral_value = collateral_amount * collateral_price
        borrow_value = borrow_amount * borrow_price
        collateral_ratio = collateral_value / borrow_value if borrow_value > 0 else 0

        # DOMAIN 16-A, DEFENCE IN DEPTH. Guarding the inputs is not sufficient:
        # the ratio is a QUOTIENT OF PRICES, and a non-finite price from the
        # oracle produces a non-finite ratio from finite inputs. A ratio that is
        # not a number cannot be below a minimum — `NaN < 1.5` is False — so the
        # check would pass without ever comparing anything.
        # REFUSE, do not coerce: a ratio we cannot compute is not a ratio of 0,
        # and silently substituting one would replace an unanswerable question
        # with a confident wrong answer.
        if not math.isfinite(collateral_ratio):
            raise ValueError(
                "Collateral ratio could not be computed as a finite number "
                f"(collateral_value={collateral_value}, borrow_value={borrow_value}). "
                "Refusing to issue a loan whose collateralisation is unknown."
            )

        if collateral_ratio < self._min_collateral_ratio:
            raise ValueError(
                f"Collateral ratio {collateral_ratio:.2f} is below minimum "
                f"{self._min_collateral_ratio:.2f}. Deposit more collateral."
            )

        interest_rate = self._calculate_interest_rate(borrow_token)
        loan_id = f"loan_{uuid.uuid4().hex[:16]}"
        now = int(time.time())

        loan: dict[str, Any] = {
            "loan_id": loan_id,
            "borrower": borrower,
            "collateral_token": collateral_token,
            "collateral_amount": collateral_amount,
            "collateral_value_usd": collateral_value,
            "borrow_token": borrow_token,
            "borrow_amount": borrow_amount,
            "borrow_value_usd": borrow_value,
            "collateral_ratio": round(collateral_ratio, 4),
            "interest_rate": round(interest_rate, 6),
            "accrued_interest": 0.0,
            "status": LoanStatus.ACTIVE,
            "created_at": now,
            "last_interest_update": now,
            "liquidation_threshold": self._liquidation_threshold,
        }

        self._loans[loan_id] = loan

        # Update pool utilisation
        self._pool_borrowed[borrow_token] = (
            self._pool_borrowed.get(borrow_token, 0) + borrow_amount
        )

        logger.info(
            "Loan created: id=%s borrower=%s collateral=%.4f %s "
            "borrow=%.4f %s ratio=%.2f rate=%.4f%%",
            loan_id, borrower, collateral_amount, collateral_token,
            borrow_amount, borrow_token, collateral_ratio, interest_rate * 100,
        )
        return loan

    async def get_loan(self, loan_id: str) -> dict[str, Any]:
        """Retrieve a loan by ID with updated accrued interest.

        Raises
        ------
        KeyError
            If loan_id is not found.
        """
        # DOMAIN 16-H — A READ THAT WROTE, WHILE THE CATALOG SAID IT DID NOT.
        # `get_loan` is registered `state_modifying=False` (catalog.py:138), and
        # that flag is what decides whether the dispatcher attests the action and
        # publishes it. Meanwhile the body called `_accrue_interest(loan)`, which
        # writes `accrued_interest` and re-bases `last_interest_update` on the
        # stored record. Driven: two `get_loan` calls one second apart mutated
        # both fields. It also returned `self._loans[loan_id]` BY REFERENCE, so
        # any consumer that wrote to the result edited the ledger.
        #
        # The catalog was not wrong about what a read SHOULD do — the code was
        # wrong about what this read DID. Fixed on the code side: interest is
        # computed for the response on a COPY, and nothing is persisted.
        #
        # THIS IS ALSO MORE CORRECT ARITHMETIC, not merely more honest. Accrual
        # re-based the clock on every read, so interest was compounded once per
        # observation: reading a loan ten times charged more than reading it once.
        # Computing from the un-rebased `last_interest_update` makes the answer a
        # function of the loan and the clock, not of how often anyone looked.
        if loan_id not in self._loans:
            raise KeyError(f"Loan '{loan_id}' not found")

        stored = self._loans[loan_id]
        view = dict(stored)
        if view["status"] == LoanStatus.ACTIVE:
            self._accrue_interest(view)
        return view

    async def repay_loan(
        self, loan_id: str, amount: float
    ) -> dict[str, Any]:
        """Repay part or all of a loan.

        Parameters
        ----------
        loan_id : str
            The loan identifier.
        amount : float
            Amount to repay in the borrow token.

        Returns
        -------
        dict
            Updated loan state.
        """
        if loan_id not in self._loans:
            raise KeyError(f"Loan '{loan_id}' not found")

        loan = self._loans[loan_id]
        if loan["status"] != LoanStatus.ACTIVE:
            raise ValueError(f"Loan '{loan_id}' is {loan['status']}, cannot repay")

        self._accrue_interest(loan)
        total_owed = loan["borrow_amount"] + loan["accrued_interest"]

        # DOMAIN 16-D — THE GUARD WAS AT THE WRONG LAYER, AND IT WAS MY MISS.
        # 16-C put an isfinite check on `set_borrow_position`, which correctly
        # refused a NaN repayment — but only AFTER this method had already
        # mutated the loan. Driven: a refused NaN repay left the loan carrying
        # `borrow_amount = nan`, i.e. the ledger was protected and the loan was
        # corrupted. A torn write, produced by guarding the second writer and
        # not the first.
        #
        # `min(nan, total_owed)` returns nan, and `nan <= accrued_interest` is
        # False, so the NaN flowed into the principal branch.
        #
        # THE RULE: validate at the FIRST writer of the transaction, not the
        # last. A guard downstream of a mutation converts silent corruption into
        # loud corruption — an improvement, but not a fix.
        if not math.isfinite(amount):
            raise ValueError("Repayment amount must be a finite number")

        if amount <= 0:
            raise ValueError("Repayment amount must be positive")

        repay_amount = min(amount, total_owed)

        # Apply repayment: first to interest, then principal
        if repay_amount <= loan["accrued_interest"]:
            loan["accrued_interest"] -= repay_amount
        else:
            remainder = repay_amount - loan["accrued_interest"]
            loan["accrued_interest"] = 0.0
            loan["borrow_amount"] -= remainder

        # Update pool
        self._pool_borrowed[loan["borrow_token"]] = max(
            0, self._pool_borrowed.get(loan["borrow_token"], 0) - repay_amount
        )

        # Check if fully repaid
        total_remaining = loan["borrow_amount"] + loan["accrued_interest"]
        if total_remaining <= 1e-18:  # effectively zero
            loan["status"] = LoanStatus.REPAID
            loan["borrow_amount"] = 0.0
            loan["accrued_interest"] = 0.0

        logger.info(
            "Loan repayment: id=%s amount=%.6f remaining=%.6f status=%s",
            loan_id, repay_amount, total_remaining, loan["status"],
        )
        return {
            "loan_id": loan_id,
            "repaid_amount": repay_amount,
            "remaining_principal": loan["borrow_amount"],
            "remaining_interest": loan["accrued_interest"],
            "status": loan["status"],
        }

    async def liquidate(
        self,
        loan_id: str,
        collateral_price: float,
        borrow_price: float,
    ) -> dict[str, Any]:
        """Attempt to liquidate an under-collateralised loan.

        Parameters
        ----------
        loan_id : str
            The loan identifier.
        collateral_price : float
            Current USD price of collateral token.
        borrow_price : float
            Current USD price of borrow token.

        Returns
        -------
        dict
            Liquidation result.

        Raises
        ------
        ValueError
            If loan is not eligible for liquidation.
        """
        if loan_id not in self._loans:
            raise KeyError(f"Loan '{loan_id}' not found")

        loan = self._loans[loan_id]
        if loan["status"] != LoanStatus.ACTIVE:
            raise ValueError(f"Loan '{loan_id}' is {loan['status']}, cannot liquidate")

        self._accrue_interest(loan)

        collateral_value = loan["collateral_amount"] * collateral_price
        total_owed = loan["borrow_amount"] + loan["accrued_interest"]
        borrow_value = total_owed * borrow_price
        current_ratio = collateral_value / borrow_value if borrow_value > 0 else float("inf")

        if current_ratio >= self._liquidation_threshold:
            raise ValueError(
                f"Loan ratio {current_ratio:.2f} is above liquidation threshold "
                f"{self._liquidation_threshold:.2f}. Not eligible."
            )

        # Calculate liquidation
        penalty = total_owed * self._liquidation_penalty
        collateral_seized = (total_owed + penalty) * borrow_price / collateral_price
        collateral_seized = min(collateral_seized, loan["collateral_amount"])

        collateral_remaining = loan["collateral_amount"] - collateral_seized

        # DOMAIN 16-E, AND THIS HALF WAS WORSE THAN THE RETURN VALUE. The
        # method used to mark the loan LIQUIDATED, reduce its recorded
        # collateral, and set borrow_amount and accrued_interest to 0.0 — i.e.
        # it ERASED THE DEBT while the borrower still held every unit of
        # collateral. A lender reading this record sees a closed, settled
        # position; the borrower has the asset and owes nothing on the books.
        #
        # The state must record that a liquidation is DUE, and must not pretend
        # one occurred. Debt and collateral are left exactly as they are,
        # because nothing about them changed.
        loan["status"] = LoanStatus.ACTIVE
        loan["liquidation_due"] = True
        loan["liquidation_due_at"] = int(time.time())
        loan["liquidation_ratio_at_determination"] = round(current_ratio, 4)

        # The pool figure is NOT decremented. It was reduced by `total_owed` on
        # the theory that the debt had been repaid out of seized collateral. No
        # collateral was seized and no debt was repaid, so decrementing it
        # understated outstanding borrowings by the full loan value.

        # DOMAIN 16-E — "seized" WAS A CLAIM ABOUT SOMETHING THAT NEVER HAPPENED.
        # LoanManager has no reference to CollateralManager's balances, so this
        # method CANNOT move collateral — the same structural fact domain 13
        # established for the securities exchange. Driven, on an eligible loan:
        #
        #   returned:  collateral_seized 1.0, collateral_remaining 0.0,
        #              debt_repaid 1200.0, status "liquidated"
        #   actual:    borrower's collateral ledger UNCHANGED at ETH 1.0,
        #              borrow ledger UNCHANGED at USDC 1200.0
        #
        # Nothing was seized, nothing was repaid, and the borrower kept both the
        # collateral and the debt. This is the LENDER'S ONLY REMEDY reporting
        # success over an action it is structurally unable to perform.
        #
        # DISPOSITION — the NEW-85 test, and domain 13's `match_orders` ruling
        # applied verbatim. Strip the outcome claim: is there work left? YES —
        # the eligibility determination is real (price fetch, ratio computation,
        # threshold comparison) and is the useful half. So this is category 6:
        # the method stops claiming to have EXECUTED a liquidation and starts
        # reporting what it actually did, which is DETERMINE that one is due.
        #
        # The amounts are kept as what they are — a QUOTE of what a real
        # liquidation would take — under names that cannot be misread as a
        # completed transfer.
        result = {
            "loan_id": loan_id,
            "status": "liquidation_due_unsettled",
            "seized": False,
            "value_moved": False,
            "collateral_seizable": round(collateral_seized, 8),
            "collateral_would_remain": round(collateral_remaining, 8),
            "debt_outstanding": round(total_owed, 8),
            "liquidation_penalty": round(penalty, 8),
            "ratio_at_liquidation": round(current_ratio, 4),
            "disclosure": (
                "DETERMINED, NOT EXECUTED. This loan is eligible for "
                "liquidation and the amounts above are what a liquidation "
                "WOULD take. No collateral has been seized and no debt has "
                "been repaid: LoanManager holds no reference to the collateral "
                "ledger and cannot move it. A real liquidation requires a "
                "settlement path that does not exist in this service."
            ),
        }

        # An operator reading logs is a surface too — inert means inert on every
        # surface. Was "Loan liquidated: ... seized=...".
        logger.info(
            "Liquidation DUE (NOT executed — no collateral moved): "
            "id=%s seizable=%.6f %s ratio=%.2f",
            loan_id, collateral_seized, loan["collateral_token"], current_ratio,
        )
        return result

    async def check_liquidation_eligibility(
        self,
        loan_id: str,
        collateral_price: float,
        borrow_price: float,
    ) -> dict[str, Any]:
        """Check if a loan is eligible for liquidation.

        Returns
        -------
        dict
            Keys: ``eligible``, ``current_ratio``, ``threshold``.
        """
        if loan_id not in self._loans:
            raise KeyError(f"Loan '{loan_id}' not found")

        loan = self._loans[loan_id]
        if loan["status"] != LoanStatus.ACTIVE:
            return {
                "eligible": False,
                "reason": f"Loan is {loan['status']}",
            }

        self._accrue_interest(loan)
        collateral_value = loan["collateral_amount"] * collateral_price
        total_owed = (loan["borrow_amount"] + loan["accrued_interest"]) * borrow_price
        current_ratio = collateral_value / total_owed if total_owed > 0 else float("inf")

        return {
            "eligible": current_ratio < self._liquidation_threshold,
            "current_ratio": round(current_ratio, 4),
            "threshold": self._liquidation_threshold,
            "loan_id": loan_id,
        }

    def get_all_active_loans(self) -> list[dict[str, Any]]:
        """Return all active loans."""
        return [
            loan for loan in self._loans.values()
            if loan["status"] == LoanStatus.ACTIVE
        ]

    # ── Interest rate model ───────────────────────────────────────────

    def _calculate_interest_rate(self, token: str) -> float:
        """Calculate variable interest rate based on pool utilisation.

        Uses a kinked rate model similar to Aave/Compound:
        - Below optimal utilisation: base_rate + utilisation * slope1
        - Above optimal utilisation: base_rate + optimal * slope1 +
          (utilisation - optimal) * slope2
        """
        total = self._pool_total.get(token, 1.0)
        borrowed = self._pool_borrowed.get(token, 0.0)
        utilisation = min(borrowed / total, 1.0) if total > 0 else 0.0

        if utilisation <= _OPTIMAL_UTILISATION:
            rate = self._base_rate + utilisation * _SLOPE_1
        else:
            excess = utilisation - _OPTIMAL_UTILISATION
            rate = (
                self._base_rate
                + _OPTIMAL_UTILISATION * _SLOPE_1
                + excess * _SLOPE_2
            )
        return rate

    def _accrue_interest(self, loan: dict[str, Any]) -> None:
        """Accrue interest on a loan based on elapsed time."""
        now = int(time.time())
        elapsed = now - loan["last_interest_update"]
        if elapsed <= 0:
            return

        # Continuous compounding: P * e^(r*t) - P
        annual_rate = loan["interest_rate"]
        years = elapsed / (365.25 * 24 * 3600)
        principal = loan["borrow_amount"]
        new_interest = principal * (math.exp(annual_rate * years) - 1)

        loan["accrued_interest"] += new_interest
        loan["last_interest_update"] = now

    async def get_rates(self, token: str) -> dict[str, Any]:
        """Get current interest rates for a token.

        Returns
        -------
        dict
            Keys: ``borrow_rate``, ``utilisation``, ``pool_total``,
            ``pool_borrowed``.
        """
        total = self._pool_total.get(token, 0.0)
        borrowed = self._pool_borrowed.get(token, 0.0)
        utilisation = borrowed / total if total > 0 else 0.0
        rate = self._calculate_interest_rate(token)

        return {
            "token": token,
            "borrow_rate": round(rate, 6),
            "borrow_rate_pct": f"{rate * 100:.2f}%",
            "utilisation": round(utilisation, 4),
            "pool_total": total,
            "pool_borrowed": borrowed,
        }

    def update_pool_total(self, token: str, amount: float) -> None:
        """Update the total pool size for a token (called on deposit/withdraw)."""
        self._pool_total[token] = max(0, self._pool_total.get(token, 0) + amount)
