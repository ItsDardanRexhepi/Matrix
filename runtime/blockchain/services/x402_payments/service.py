"""
X402PaymentService -- x402 protocol implementation for agentic payments.

Handles agent-to-agent payments with x402 HTTP header integration,
spend enforcement, and full payment lifecycle management.
"""

from __future__ import annotations

import hashlib
import logging
import time
import uuid
from enum import Enum
from typing import Any

from runtime.blockchain.services.x402_payments.spend_enforcer import SpendEnforcer
from runtime.blockchain.services.x402_payments.limit_updater import LimitUpdater

logger = logging.getLogger(__name__)


class PaymentStatus(str, Enum):
    PENDING = "pending"
    AUTHORIZED = "authorized"
    COMPLETED = "completed"
    REJECTED = "rejected"
    EXPIRED = "expired"
    REFUNDED = "refunded"


# x402 HTTP header name
X402_HEADER = "X-Payment-402"

# Payment expiry (seconds)
DEFAULT_PAYMENT_EXPIRY = 300  # 5 minutes


class X402PaymentService:
    """
    x402 protocol payment service for autonomous agents.

    Manages the full payment lifecycle: creation, authorisation, completion.
    Integrates with SpendEnforcer for per-agent spend limits and
    LimitUpdater for owner-controlled limit management.

    Config keys (under config["x402"]):
        payment_expiry_seconds  -- seconds before pending payment expires
        supported_tokens        -- list of accepted token symbols
        network                 -- blockchain network
    Config keys (under config["blockchain"]):
        platform_wallet         -- platform fee recipient
    """

    def __init__(self, config: dict[str, Any]) -> None:
        self.config = config
        x402 = config.get("x402", {})
        bc = config.get("blockchain", {})

        self.payment_expiry: int = x402.get("payment_expiry_seconds", DEFAULT_PAYMENT_EXPIRY)
        self.supported_tokens: set[str] = set(
            x402.get("supported_tokens", ["USDC", "USDT", "DAI", "ETH"])
        )
        self.network: str = bc.get("network", "base-sepolia")
        self.platform_wallet: str = bc.get("platform_wallet", "0x" + "0" * 40)

        # Sub-components
        self._spend_enforcer = SpendEnforcer(config)
        self._limit_updater = LimitUpdater(config)

        # payment_id -> payment record
        self._payments: dict[str, dict[str, Any]] = {}
        # agent_id -> list of payment_ids
        self._agent_payments: dict[str, list[str]] = {}

        logger.info(
            "X402PaymentService initialised: network=%s tokens=%s expiry=%ds",
            self.network, self.supported_tokens, self.payment_expiry,
        )

    @property
    def spend_enforcer(self) -> SpendEnforcer:
        return self._spend_enforcer

    @property
    def limit_updater(self) -> LimitUpdater:
        return self._limit_updater

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    async def create_payment(
        self,
        agent_id: str,
        recipient: str,
        amount: float,
        token: str,
        purpose: str,
    ) -> dict[str, Any]:
        """
        Create a new x402 payment request.

        The payment is created in PENDING status and must be authorised
        before it can be completed. Spend limits are checked at creation.

        Args:
            agent_id: The paying agent's identifier.
            recipient: Recipient address or agent ID.
            amount: Payment amount.
            token: Token symbol (e.g. "USDC").
            purpose: Human-readable purpose of payment.

        Returns:
            Dict with payment_id, x402 header, and payment details.
        """
        token = token.upper()

        # Validation
        if amount <= 0:
            return {"status": "error", "error": "Amount must be positive"}

        if token not in self.supported_tokens:
            return {
                "status": "error",
                "error": f"Unsupported token: {token}. Supported: {sorted(self.supported_tokens)}",
            }

        if not agent_id:
            return {"status": "error", "error": "Agent ID is required"}

        if not recipient:
            return {"status": "error", "error": "Recipient is required"}

        if agent_id == recipient:
            return {"status": "error", "error": "Agent cannot pay itself"}

        # Check spend limits
        spend_check = await self._spend_enforcer.check_spend(agent_id, amount)
        if not spend_check["allowed"]:
            logger.warning(
                "Payment blocked by spend enforcer: agent=%s amount=%.2f reason=%s",
                agent_id, amount, spend_check.get("reason", "limit exceeded"),
            )
            return {
                "status": "blocked",
                "error": "Spend limit exceeded",
                "details": spend_check,
            }

        # Create payment
        payment_id = self._generate_payment_id(agent_id, recipient, amount)
        timestamp = int(time.time())

        # Generate x402 header value
        x402_header_value = self._generate_x402_header(
            payment_id, agent_id, recipient, amount, token
        )

        payment: dict[str, Any] = {
            "payment_id": payment_id,
            "agent_id": agent_id,
            "recipient": recipient,
            "amount": round(amount, 6),
            "token": token,
            "purpose": purpose,
            "status": PaymentStatus.PENDING.value,
            "x402_header": {
                "name": X402_HEADER,
                "value": x402_header_value,
            },
            "created_at": timestamp,
            "expires_at": timestamp + self.payment_expiry,
            "authorized_at": None,
            "completed_at": None,
            "network": self.network,
            "on_chain_hash": self._compute_payment_hash(
                payment_id, agent_id, recipient, amount, token
            ),
        }

        self._payments[payment_id] = payment
        self._agent_payments.setdefault(agent_id, []).append(payment_id)

        logger.info(
            "Payment created: id=%s agent=%s -> %s amount=%.6f %s",
            payment_id, agent_id, recipient, amount, token,
        )

        return {
            **payment,
            "status": "created",
        }

    async def authorize_payment(self, payment_id: str) -> dict[str, Any]:
        """
        Authorise a pending payment for execution.

        Verifies the payment is still valid (not expired) and transitions
        it to AUTHORIZED status. Records the spend against the agent's limits.

        Args:
            payment_id: The payment to authorise.

        Returns:
            Dict with authorisation result.
        """
        payment = self._payments.get(payment_id)
        if payment is None:
            return {"status": "error", "error": f"Payment not found: {payment_id}"}

        if payment["status"] != PaymentStatus.PENDING.value:
            return {
                "status": "error",
                "error": f"Payment cannot be authorised in status: {payment['status']}",
            }

        # Check expiry
        now = int(time.time())
        if now > payment["expires_at"]:
            payment["status"] = PaymentStatus.EXPIRED.value
            return {
                "status": "expired",
                "payment_id": payment_id,
                "error": "Payment has expired",
                "expired_at": payment["expires_at"],
            }

        # Re-check spend limits at authorisation time
        spend_check = await self._spend_enforcer.check_spend(
            payment["agent_id"], payment["amount"]
        )
        if not spend_check["allowed"]:
            payment["status"] = PaymentStatus.REJECTED.value
            return {
                "status": "rejected",
                "payment_id": payment_id,
                "error": "Spend limit exceeded at authorisation",
                "details": spend_check,
            }

        # Authorise
        payment["status"] = PaymentStatus.AUTHORIZED.value
        payment["authorized_at"] = now

        # Record spend
        await self._spend_enforcer.record_spend(
            payment["agent_id"], payment["amount"]
        )

        logger.info(
            "Payment authorised: id=%s agent=%s amount=%.6f %s",
            payment_id, payment["agent_id"], payment["amount"], payment["token"],
        )

        return {
            "status": "authorized",
            "payment_id": payment_id,
            "agent_id": payment["agent_id"],
            "recipient": payment["recipient"],
            "amount": payment["amount"],
            "token": payment["token"],
            "authorized_at": now,
            "x402_header": payment["x402_header"],
        }

    async def get_payment(self, payment_id: str) -> dict[str, Any]:
        """
        Retrieve a payment by ID.

        Args:
            payment_id: The payment identifier.

        Returns:
            Dict with full payment record.
        """
        payment = self._payments.get(payment_id)
        if payment is None:
            return {"status": "error", "error": f"Payment not found: {payment_id}"}

        # Check and update expiry status
        if (
            payment["status"] == PaymentStatus.PENDING.value
            and int(time.time()) > payment["expires_at"]
        ):
            payment["status"] = PaymentStatus.EXPIRED.value

        return {**payment, "status": "found"}

    async def list_payments(
        self,
        agent_id: str,
        filters: dict[str, Any] | None = None,
    ) -> list[dict[str, Any]]:
        """
        List payments for an agent, optionally filtered.

        Args:
            agent_id: The agent whose payments to list.
            filters: Optional filters (status, token, min_amount, max_amount,
                     from_time, to_time).

        Returns:
            List of payment dicts.
        """
        if filters is None:
            filters = {}

        payment_ids = self._agent_payments.get(agent_id, [])
        payments = [
            self._payments[pid]
            for pid in payment_ids
            if pid in self._payments
        ]

        # Apply filters
        if "status" in filters:
            payments = [p for p in payments if p["status"] == filters["status"]]

        if "token" in filters:
            tok = filters["token"].upper()
            payments = [p for p in payments if p["token"] == tok]

        if "min_amount" in filters:
            payments = [p for p in payments if p["amount"] >= filters["min_amount"]]

        if "max_amount" in filters:
            payments = [p for p in payments if p["amount"] <= filters["max_amount"]]

        if "from_time" in filters:
            payments = [p for p in payments if p["created_at"] >= filters["from_time"]]

        if "to_time" in filters:
            payments = [p for p in payments if p["created_at"] <= filters["to_time"]]

        # Update expired statuses
        now = int(time.time())
        for p in payments:
            if p["status"] == PaymentStatus.PENDING.value and now > p["expires_at"]:
                p["status"] = PaymentStatus.EXPIRED.value

        return payments

    async def complete_payment(self, payment_id: str) -> dict[str, Any]:
        """Mark an authorised payment as completed (on-chain settlement done)."""
        payment = self._payments.get(payment_id)
        if payment is None:
            return {"status": "error", "error": f"Payment not found: {payment_id}"}

        if payment["status"] != PaymentStatus.AUTHORIZED.value:
            return {
                "status": "error",
                "error": f"Only authorised payments can be completed. Current: {payment['status']}",
            }

        payment["status"] = PaymentStatus.COMPLETED.value
        payment["completed_at"] = int(time.time())

        logger.info("Payment completed: id=%s", payment_id)

        return {
            "status": "completed",
            "payment_id": payment_id,
            "completed_at": payment["completed_at"],
        }

    async def refund_payment(self, payment_id: str) -> dict[str, Any]:
        """Refund a completed or authorised payment."""
        payment = self._payments.get(payment_id)
        if payment is None:
            return {"status": "error", "error": f"Payment not found: {payment_id}"}

        if payment["status"] not in (
            PaymentStatus.AUTHORIZED.value,
            PaymentStatus.COMPLETED.value,
        ):
            return {
                "status": "error",
                "error": f"Cannot refund payment in status: {payment['status']}",
            }

        payment["status"] = PaymentStatus.REFUNDED.value
        payment["refunded_at"] = int(time.time())

        # Reverse spend record
        await self._spend_enforcer.reverse_spend(
            payment["agent_id"], payment["amount"]
        )

        logger.info("Payment refunded: id=%s amount=%.6f", payment_id, payment["amount"])

        return {
            "status": "refunded",
            "payment_id": payment_id,
            "amount": payment["amount"],
            "refunded_at": payment["refunded_at"],
        }

    # ------------------------------------------------------------------
    # Internals
    # ------------------------------------------------------------------

    @staticmethod
    def _generate_payment_id(
        agent_id: str, recipient: str, amount: float
    ) -> str:
        raw = f"{agent_id}:{recipient}:{amount}:{uuid.uuid4().hex}:{time.time()}"
        return "pay_" + hashlib.sha256(raw.encode()).hexdigest()[:24]

    @staticmethod
    def _generate_x402_header(
        payment_id: str,
        agent_id: str,
        recipient: str,
        amount: float,
        token: str,
    ) -> str:
        """Generate x402 HTTP header value for agent-to-agent payment."""
        payload = f"{payment_id}|{agent_id}|{recipient}|{amount}|{token}"
        signature = hashlib.sha256(payload.encode()).hexdigest()[:16]
        return f"x402 {payment_id} {token} {amount} sig={signature}"

    @staticmethod
    def _compute_payment_hash(
        payment_id: str,
        agent_id: str,
        recipient: str,
        amount: float,
        token: str,
    ) -> str:
        payload = f"{payment_id}|{agent_id}|{recipient}|{amount}|{token}"
        return "0x" + hashlib.sha256(payload.encode()).hexdigest()

    # ------------------------------------------------------------------
    # Expanded payment operations
    # ------------------------------------------------------------------

    async def create_stream(
        self, sender: str, recipient: str, amount: float, token: str, duration_seconds: int,
    ) -> dict[str, Any]:
        """Create a streaming payment (Sablier/Superfluid-style)."""
        stream_id = f"stream_{uuid.uuid4().hex[:16]}"
        now = int(time.time())
        record: dict[str, Any] = {
            "id": stream_id,
            "status": "streaming",
            "sender": sender,
            "recipient": recipient,
            "total_amount": amount,
            "token": token.upper(),
            "duration_seconds": duration_seconds,
            "rate_per_second": round(amount / duration_seconds, 8) if duration_seconds else 0,
            "started_at": now,
            "ends_at": now + duration_seconds,
        }
        self._payments[stream_id] = record
        logger.info("Payment stream created: id=%s", stream_id)
        return record

    async def create_recurring(
        self, payer: str, recipient: str, amount: float, token: str, interval_days: int, count: int,
    ) -> dict[str, Any]:
        """Create a recurring payment schedule."""
        rec_id = f"rec_{uuid.uuid4().hex[:16]}"
        now = int(time.time())
        record: dict[str, Any] = {
            "id": rec_id,
            "status": "active",
            "payer": payer,
            "recipient": recipient,
            "amount": amount,
            "token": token.upper(),
            "interval_days": interval_days,
            "total_payments": count,
            "payments_made": 0,
            "next_payment_at": now + interval_days * 86400,
            "created_at": now,
        }
        self._payments[rec_id] = record
        logger.info("Recurring payment created: id=%s", rec_id)
        return record

    async def create_milestone_escrow(
        self, payer: str, recipient: str, amount: float, token: str, milestones: list[str],
    ) -> dict[str, Any]:
        """Create a milestone-based escrow payment."""
        escrow_id = f"escrow_{uuid.uuid4().hex[:16]}"
        now = int(time.time())
        record: dict[str, Any] = {
            "id": escrow_id,
            "status": "funded",
            "payer": payer,
            "recipient": recipient,
            "total_amount": amount,
            "token": token.upper(),
            "milestones": [{"name": m, "status": "pending"} for m in milestones],
            "released": 0.0,
            "created_at": now,
        }
        self._payments[escrow_id] = record
        logger.info("Milestone escrow created: id=%s", escrow_id)
        return record

    async def split_payment(
        self, sender: str, recipients: list[dict[str, Any]], total_amount: float, token: str,
    ) -> dict[str, Any]:
        """Split a payment among multiple recipients."""
        split_id = f"split_{uuid.uuid4().hex[:16]}"
        record: dict[str, Any] = {
            "id": split_id,
            "status": "completed",
            "sender": sender,
            "recipients": recipients,
            "total_amount": total_amount,
            "token": token.upper(),
            "split_count": len(recipients),
            "created_at": int(time.time()),
        }
        self._payments[split_id] = record
        logger.info("Payment split: id=%s count=%d", split_id, len(recipients))
        return record

    async def factor_invoice(
        self, seller: str, invoice_amount: float, token: str, discount_pct: float = 2.0,
    ) -> dict[str, Any]:
        """Factor an invoice for immediate liquidity."""
        factor_id = f"inv_{uuid.uuid4().hex[:16]}"
        advance = round(invoice_amount * (1 - discount_pct / 100.0), 6)
        record: dict[str, Any] = {
            "id": factor_id,
            "status": "factored",
            "seller": seller,
            "invoice_amount": invoice_amount,
            "token": token.upper(),
            "discount_pct": discount_pct,
            "advance_amount": advance,
            "created_at": int(time.time()),
        }
        self._payments[factor_id] = record
        logger.info("Invoice factored: id=%s", factor_id)
        return record

    async def run_payroll(
        self, employer: str, employees: list[dict[str, Any]], token: str, period: str = "monthly",
    ) -> dict[str, Any]:
        """Execute a payroll batch payment."""
        payroll_id = f"payroll_{uuid.uuid4().hex[:16]}"
        total = sum(e.get("amount", 0) for e in employees)
        record: dict[str, Any] = {
            "id": payroll_id,
            "status": "processed",
            "employer": employer,
            "employee_count": len(employees),
            "total_amount": round(total, 6),
            "token": token.upper(),
            "period": period,
            "created_at": int(time.time()),
        }
        self._payments[payroll_id] = record
        logger.info("Payroll processed: id=%s employees=%d", payroll_id, len(employees))
        return record
