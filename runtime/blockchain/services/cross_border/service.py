"""
CrossBorderService — cross-border payments with FX conversion for 0pnMatrx.

All cross-border payments are attested via Component 8
(AttestationService).
"""

from __future__ import annotations

import logging
import time
import uuid
from typing import Any

from runtime.blockchain.services.cross_border.conversion import FiatETHConversion
from runtime.blockchain.services.cross_border.compliance import ComplianceScaffold

logger = logging.getLogger(__name__)


class CrossBorderService:
    """Main cross-border payment service.

    Config keys (under ``config["cross_border"]``):
        fee_pct (float): Transaction fee percentage (default 0.5).
        max_payment (float): Maximum single payment (default 1_000_000).
    """

    def __init__(self, config: dict) -> None:
        self._config = config
        cb_cfg: dict[str, Any] = config.get("cross_border", {})

        self._fee_pct: float = float(cb_cfg.get("fee_pct", 0.5))
        self._max_payment: float = float(
            cb_cfg.get("max_payment", 1_000_000.0)
        )

        self._conversion = FiatETHConversion(config)
        self._compliance = ComplianceScaffold(config)

        # payment_id -> payment record
        self._payments: dict[str, dict[str, Any]] = {}
        # address -> list of payment_ids
        self._address_payments: dict[str, list[str]] = {}

        logger.info(
            "CrossBorderService initialised (fee=%.2f%%, max=%.2f).",
            self._fee_pct, self._max_payment,
        )

    @property
    def conversion(self) -> FiatETHConversion:
        return self._conversion

    @property
    def compliance(self) -> ComplianceScaffold:
        return self._compliance

    # ------------------------------------------------------------------
    # Payment operations
    # ------------------------------------------------------------------

    async def send_payment(
        self,
        sender: str,
        recipient: str,
        amount: float,
        from_currency: str,
        to_currency: str,
    ) -> dict:
        """Send a cross-border payment with automatic FX conversion.

        Args:
            sender: Sender address.
            recipient: Recipient address.
            amount: Amount in from_currency.
            from_currency: Source currency code.
            to_currency: Destination currency code.

        Returns:
            Payment record.
        """
        if amount <= 0:
            raise ValueError("Amount must be positive")
        if amount > self._max_payment:
            raise ValueError(
                f"Amount {amount} exceeds maximum {self._max_payment}"
            )
        if not sender or not recipient:
            raise ValueError("Both sender and recipient are required")

        from_currency = from_currency.upper()
        to_currency = to_currency.upper()

        # Compliance check
        corridor = f"{from_currency}->{to_currency}"
        compliance_result = await self._compliance.check_compliance(
            sender, recipient, amount, corridor,
        )

        if not compliance_result.get("approved", False):
            return {
                "status": "compliance_hold",
                "reason": compliance_result.get("reason", "Compliance check failed"),
                "compliance": compliance_result,
            }

        # Get conversion quote
        quote = await self.get_quote(amount, from_currency, to_currency)

        # Calculate fees
        fee = amount * (self._fee_pct / 100.0)
        net_amount = amount - fee

        # Convert
        conversion_result = await self._conversion.convert(
            net_amount, from_currency, to_currency,
        )

        payment_id = f"pay_{uuid.uuid4().hex[:16]}"
        now = int(time.time())

        payment: dict[str, Any] = {
            "payment_id": payment_id,
            "sender": sender,
            "recipient": recipient,
            "source_amount": amount,
            "source_currency": from_currency,
            "fee_amount": round(fee, 6),
            "fee_pct": self._fee_pct,
            "net_source_amount": round(net_amount, 6),
            "converted_amount": conversion_result["converted_amount"],
            "destination_currency": to_currency,
            "exchange_rate": conversion_result["rate"],
            "corridor": corridor,
            "compliance": compliance_result,
            "status": "completed",
            "created_at": now,
        }
        self._payments[payment_id] = payment
        self._address_payments.setdefault(sender, []).append(payment_id)
        self._address_payments.setdefault(recipient, []).append(payment_id)

        # Attest via Component 8
        await self._attest_payment(payment)

        logger.info(
            "Payment sent: id=%s %s %.6f %s -> %.6f %s",
            payment_id, sender, amount, from_currency,
            conversion_result["converted_amount"], to_currency,
        )
        return payment

    async def get_quote(
        self, amount: float, from_currency: str, to_currency: str,
    ) -> dict:
        """Get a conversion quote without executing.

        Args:
            amount: Amount in from_currency.
            from_currency: Source currency code.
            to_currency: Destination currency code.

        Returns:
            Quote with rate, converted amount, fees.
        """
        from_currency = from_currency.upper()
        to_currency = to_currency.upper()

        rate_data = await self._conversion.get_rate(from_currency, to_currency)
        rate = rate_data["rate"]

        fee = amount * (self._fee_pct / 100.0)
        net = amount - fee
        converted = net * rate

        return {
            "source_amount": amount,
            "source_currency": from_currency,
            "destination_currency": to_currency,
            "exchange_rate": rate,
            "fee_amount": round(fee, 6),
            "fee_pct": self._fee_pct,
            "net_source_amount": round(net, 6),
            "converted_amount": round(converted, 6),
            "quote_valid_seconds": 30,
            "quoted_at": int(time.time()),
        }

    async def get_payment(self, payment_id: str) -> dict:
        """Retrieve a payment by ID."""
        payment = self._payments.get(payment_id)
        if not payment:
            raise ValueError(f"Payment {payment_id} not found")
        return payment

    async def list_payments(self, address: str) -> list:
        """List all payments for an address (as sender or recipient).

        Args:
            address: Address to query.

        Returns:
            List of payment records.
        """
        payment_ids = self._address_payments.get(address, [])
        # Deduplicate (address appears as both sender and recipient)
        seen: set[str] = set()
        results: list[dict[str, Any]] = []
        for pid in payment_ids:
            if pid not in seen:
                seen.add(pid)
                payment = self._payments.get(pid)
                if payment:
                    results.append(payment)
        return results

    # ------------------------------------------------------------------
    # Attestation
    # ------------------------------------------------------------------

    async def _attest_payment(self, payment: dict) -> None:
        """Attest cross-border payment via Component 8."""
        try:
            from runtime.blockchain.services.attestation import AttestationService

            svc = AttestationService(self._config)
            await svc.attest(
                schema_uid="primary",
                data={
                    "action": "cross_border_payment",
                    "category": "cross_border",
                    "payment_id": payment["payment_id"],
                    "sender": payment["sender"],
                    "recipient": payment["recipient"],
                    "source_amount": payment["source_amount"],
                    "source_currency": payment["source_currency"],
                    "destination_currency": payment["destination_currency"],
                    "converted_amount": payment["converted_amount"],
                },
                recipient=payment["recipient"],
            )
        except ImportError:
            logger.debug("AttestationService not available; skipping.")
        except Exception as exc:
            logger.warning("Payment attestation failed: %s", exc)
