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
    """Lifecycle states of an x402 payment RECORD.

    NEW-55: the terminal state was `COMPLETED = "completed"`. Nothing in this
    service moves value — no ledger, no web3 call, no external payment API
    anywhere in it — so "completed" asserted a settlement that never happened.
    Renamed rather than re-documented: fixing the docstring while leaving the
    enum would be a differently-worded version of the same claim, and a status
    that half-changes is a coherent-looking lie, worse than an obvious one.

    RECORDED_UNSETTLED is deliberately ugly. "recorded" alone could be read as
    "recorded on-chain"; this cannot be misread as money having moved.
    """

    PENDING = "pending"
    AUTHORIZED = "authorized"
    RECORDED_UNSETTLED = "recorded_unsettled"
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
        before its record can be closed. Spend limits are checked at creation.

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
            # NEW-55: was `completed_at`, renamed with the terminal status it
            # belongs to. A field named completed_at on an unsettled record is
            # the same claim in a different place.
            "recorded_at": None,
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

        # NEW-56: was `"status": "created"`, OVERWRITING the record's real
        # lifecycle status ("pending"). The caller got a status describing the
        # API call rather than the payment, so a client could never see the
        # state it needed. Real status returned; "created" moves to its own key.
        return {**payment, "created": True}

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

        # NEW-56: was `"status": "found"`, clobbering the real lifecycle status
        # on EVERY lookup of EVERY payment — a client polling for settlement
        # state could never observe pending / authorized / recorded_unsettled /
        # expired / refunded. "found" is a fact about the LOOKUP, not the
        # payment, so it moves to its own key.
        return {**payment, "found": True}

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
        """Close an authorised payment RECORD. Moves no value (NEW-55).

        This docstring used to read "(on-chain settlement done)". It was not:
        the method's entire former action was a single status assignment. No
        web3 call, no external payment API, no ledger debit or credit — this
        service has no ledger at all. The payer's balance was untouched and the
        recipient received nothing.

        Classified real-local-defective rather than fabrication: the state
        guards ARE real (unknown id and wrong-state are genuinely rejected).
        The work is real; the settlement guarantee was fiction.

        REAL SETTLEMENT EXISTS ELSEWHERE and is deliberately NOT wired here.
        runtime/blockchain/payments.py `_send_eth` / `_send_token` build, sign
        and broadcast genuine transactions. Delegating means live chain
        transactions, which is out of remediation scope — so this tells the
        truth about being a record-keeper instead of quietly becoming a mover.
        Logged on the deferred register as a real-build project (wiring this
        record-keeper to the payments.py transaction path).
        """
        payment = self._payments.get(payment_id)
        if payment is None:
            return {"status": "error", "error": f"Payment not found: {payment_id}"}

        if payment["status"] != PaymentStatus.AUTHORIZED.value:
            return {
                "status": "error",
                "error": (
                    "Only authorised payments can be recorded as closed. "
                    f"Current: {payment['status']}"
                ),
            }

        payment["status"] = PaymentStatus.RECORDED_UNSETTLED.value
        payment["recorded_at"] = int(time.time())

        logger.info(
            "Payment record closed (NOT settled — no value moved): id=%s", payment_id
        )

        return {
            "status": PaymentStatus.RECORDED_UNSETTLED.value,
            "payment_id": payment_id,
            "recorded_at": payment["recorded_at"],
            "settled": False,
            "value_moved": False,
            "disclosure": (
                "NOT SETTLED. This closes the payment RECORD only. No value was "
                "transferred: this service holds no ledger and makes no on-chain "
                "or payment-provider call. The payer has not been debited and "
                "the recipient has not been credited."
            ),
        }

    async def refund_payment(self, payment_id: str) -> dict[str, Any]:
        """Refund an authorised or recorded payment RECORD.

        NEW-53: DISABLED at ACTION_MAP — it took only a payment_id, with no
        caller identity. NEW-55: it reverses a spend COUNTER, not money; no
        value ever left anyone.
        """
        payment = self._payments.get(payment_id)
        if payment is None:
            return {"status": "error", "error": f"Payment not found: {payment_id}"}

        if payment["status"] not in (
            PaymentStatus.AUTHORIZED.value,
            PaymentStatus.RECORDED_UNSETTLED.value,
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

    # ── REMOVED: the six "expanded" payment operations (NEW-57) ──────────
    #
    # create_stream, create_recurring, create_milestone_escrow, split_payment,
    # factor_invoice, run_payroll. All six were fabrication-live — reachable
    # through ACTION_MAP — and every one moved NOTHING.
    #
    #   split_payment     never read the per-recipient amounts at all, only
    #                     len(recipients), so the split arithmetic did not even
    #                     happen. Returned "status": "completed".
    #   run_payroll       summed the caller's own input and returned
    #                     "status": "processed". Not one employee was paid.
    #   factor_invoice    computed an advance_amount and returned "factored".
    #                     Invoice factoring IS the advancing of cash; there was
    #                     no funder, no counterparty, no transfer.
    #   create_stream     no Sablier/Superfluid contract, no stream.
    #   create_recurring  no scheduler exists; no first payment, and none ever.
    #   create_milestone_escrow  claimed to hold funds in escrow, held nothing,
    #                     and bypassed the SpendEnforcer that gates every other
    #                     payment path.
    #
    # TWIN CHECK, per method — none of the six has one.
    # runtime/blockchain/payments.py is REAL (_send_eth / _send_token build,
    # sign and broadcast genuine transactions), which is why complete_payment's
    # settlement gap is a wiring question. But it is a SINGLE-TRANSFER
    # primitive. split_payment and run_payroll are batch disbursement: N
    # transfers with partial-failure, atomicity and gas semantics that exist
    # nowhere in this repo. A loop over a real primitive is a DESIGN, not a
    # twin — calling it one would repeat the publish_mirror_post error
    # (NEW-48), where a name-adjacent neighbour was mistaken for the same
    # operation. Batch disbursement is logged on the deferred register.
    #
    # Removed rather than gated: a credential-gated stub would imply a real
    # implementation waits behind a key. None does.
