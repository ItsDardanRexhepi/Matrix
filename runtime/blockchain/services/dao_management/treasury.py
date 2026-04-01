"""
TreasuryManager — manages DAO treasury funds with tiered fees.

Fee schedule on treasury operations:
- < 10,000   : 1.00 %
- 10,000-100,000 : 0.50 %
- > 100,000  : 0.25 %

Fees are routed to the ``platform_wallet`` defined in config.
"""

import logging
import time
import uuid
from typing import Any

logger = logging.getLogger(__name__)

# Tiered fee brackets: (upper_bound_exclusive, fee_pct)
_FEE_TIERS: list[tuple[float, float]] = [
    (10_000.0, 1.0),
    (100_000.0, 0.5),
    (float("inf"), 0.25),
]


class SpendProposalStatus:
    PENDING = "pending"
    APPROVED = "approved"
    EXECUTED = "executed"
    REJECTED = "rejected"


class TreasuryManager:
    """Manages deposits, spend proposals, and balances for DAO treasuries.

    Parameters
    ----------
    config : dict
        Platform configuration.  Reads:

        - ``blockchain.platform_wallet`` — fee recipient address
        - ``dao.treasury`` sub-key for optional overrides
    """

    def __init__(self, config: dict) -> None:
        self._config = config
        self._platform_wallet: str = (
            config.get("blockchain", {}).get("platform_wallet", "0xplatform")
        )
        treasury_cfg = config.get("dao", {}).get("treasury", {})
        self._approval_threshold_pct: float = treasury_cfg.get(
            "approval_threshold_pct", 50.0
        )

        # dao_id -> {token -> balance}
        self._balances: dict[str, dict[str, float]] = {}
        # dao_id -> list of deposit records
        self._deposits: dict[str, list[dict]] = {}
        # proposal_id -> spend proposal
        self._proposals: dict[str, dict[str, Any]] = {}
        # Total fees collected
        self._fees_collected: float = 0.0

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    async def deposit(
        self, dao_id: str, depositor: str, token: str, amount: float
    ) -> dict:
        """Deposit funds into a DAO treasury.

        A tiered fee is deducted and sent to the platform wallet.
        """
        if amount <= 0:
            raise ValueError("Deposit amount must be positive")
        if not depositor:
            raise ValueError("Depositor address is required")
        if not token:
            raise ValueError("Token identifier is required")

        fee = self._calculate_fee(amount)
        net = round(amount - fee, 8)

        balances = self._balances.setdefault(dao_id, {})
        balances[token] = round(balances.get(token, 0.0) + net, 8)
        self._fees_collected = round(self._fees_collected + fee, 8)

        deposit_record = {
            "deposit_id": f"dep_{uuid.uuid4().hex[:10]}",
            "dao_id": dao_id,
            "depositor": depositor,
            "token": token,
            "gross_amount": amount,
            "fee": fee,
            "net_amount": net,
            "fee_recipient": self._platform_wallet,
            "timestamp": time.time(),
        }
        self._deposits.setdefault(dao_id, []).append(deposit_record)

        logger.info(
            "Deposit to DAO %s: %.4f %s (fee=%.4f, net=%.4f) by %s",
            dao_id, amount, token, fee, net, depositor,
        )
        return deposit_record

    async def propose_spend(
        self,
        dao_id: str,
        proposer: str,
        recipient: str,
        amount: float,
        reason: str,
    ) -> dict:
        """Create a spend proposal for DAO treasury funds.

        The proposal must be voted on (externally via DAO governance)
        before it can be executed.
        """
        if amount <= 0:
            raise ValueError("Spend amount must be positive")
        if not proposer:
            raise ValueError("Proposer address is required")
        if not recipient:
            raise ValueError("Recipient address is required")
        if not reason:
            raise ValueError("Reason is required for spend proposals")

        proposal_id = f"spend_{uuid.uuid4().hex[:12]}"
        now = time.time()

        proposal = {
            "proposal_id": proposal_id,
            "dao_id": dao_id,
            "proposer": proposer,
            "recipient": recipient,
            "amount": amount,
            "fee": self._calculate_fee(amount),
            "reason": reason,
            "status": SpendProposalStatus.PENDING,
            "votes_for": 0.0,
            "votes_against": 0.0,
            "voters": [],
            "created_at": now,
            "updated_at": now,
        }
        self._proposals[proposal_id] = proposal

        logger.info(
            "Spend proposal %s for DAO %s: %.4f to %s — '%s'",
            proposal_id, dao_id, amount, recipient, reason,
        )
        return proposal

    async def execute_spend(self, dao_id: str, proposal_id: str) -> dict:
        """Execute an approved spend proposal.

        Deducts funds from the DAO treasury and applies the tiered fee.
        The proposal must have ``status == 'approved'`` or have sufficient
        votes-for to auto-approve.
        """
        proposal = self._proposals.get(proposal_id)
        if proposal is None:
            raise KeyError(f"Proposal {proposal_id} not found")
        if proposal["dao_id"] != dao_id:
            raise ValueError(
                f"Proposal {proposal_id} belongs to DAO {proposal['dao_id']}, "
                f"not {dao_id}"
            )
        if proposal["status"] == SpendProposalStatus.EXECUTED:
            raise ValueError(f"Proposal {proposal_id} has already been executed")
        if proposal["status"] == SpendProposalStatus.REJECTED:
            raise ValueError(f"Proposal {proposal_id} was rejected")

        # Auto-approve if enough votes
        total_votes = proposal["votes_for"] + proposal["votes_against"]
        if total_votes > 0:
            approval_pct = (proposal["votes_for"] / total_votes) * 100
            if approval_pct >= self._approval_threshold_pct:
                proposal["status"] = SpendProposalStatus.APPROVED

        if proposal["status"] != SpendProposalStatus.APPROVED:
            raise ValueError(
                f"Proposal {proposal_id} is not approved (status={proposal['status']})"
            )

        amount = proposal["amount"]
        fee = self._calculate_fee(amount)
        total_debit = round(amount + fee, 8)

        # Check balance (default token assumed if not specified)
        balances = self._balances.get(dao_id, {})
        # Try the native token first, then any token with sufficient balance
        debit_token: str | None = None
        for tkn, bal in balances.items():
            if bal >= total_debit:
                debit_token = tkn
                break

        if debit_token is None:
            available = sum(balances.values())
            raise ValueError(
                f"Insufficient treasury funds for DAO {dao_id}: "
                f"need {total_debit:.4f}, available {available:.4f}"
            )

        balances[debit_token] = round(balances[debit_token] - total_debit, 8)
        self._fees_collected = round(self._fees_collected + fee, 8)

        now = time.time()
        proposal["status"] = SpendProposalStatus.EXECUTED
        proposal["executed_at"] = now
        proposal["updated_at"] = now
        proposal["execution_details"] = {
            "amount_sent": amount,
            "fee_deducted": fee,
            "total_debited": total_debit,
            "debit_token": debit_token,
            "fee_recipient": self._platform_wallet,
        }

        logger.info(
            "Spend executed: %s — %.4f to %s (fee=%.4f) from DAO %s",
            proposal_id, amount, proposal["recipient"], fee, dao_id,
        )
        return proposal

    async def get_balance(self, dao_id: str) -> dict:
        """Return the current treasury balances for a DAO."""
        balances = self._balances.get(dao_id, {})
        total = sum(balances.values())
        return {
            "dao_id": dao_id,
            "balances": dict(balances),
            "total": round(total, 8),
            "pending_proposals": len([
                p for p in self._proposals.values()
                if p["dao_id"] == dao_id
                and p["status"] in (SpendProposalStatus.PENDING, SpendProposalStatus.APPROVED)
            ]),
        }

    # ------------------------------------------------------------------
    # Fee calculation
    # ------------------------------------------------------------------

    @staticmethod
    def _calculate_fee(amount: float) -> float:
        """Calculate the tiered fee for a given amount.

        Fee tiers:
        - < 10,000   : 1.00 %
        - 10,000-100,000 : 0.50 %
        - > 100,000  : 0.25 %
        """
        for upper_bound, pct in _FEE_TIERS:
            if amount < upper_bound:
                return round(amount * pct / 100.0, 8)
        # Fallback (should not reach here due to inf)
        return round(amount * 0.25 / 100.0, 8)
