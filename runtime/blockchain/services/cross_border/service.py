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

    def fee_for(self, amount: float) -> dict[str, float]:
        """The platform fee on a payment of ``amount``: the one computation
        send_payment, get_quote and any published estimate share, so a quoted
        fee cannot differ from the fee a payment record carries."""
        fee = amount * (self._fee_pct / 100.0)
        return {"fee_pct": self._fee_pct, "fee_amount": fee, "net_amount": amount - fee}

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
        """RECORD a cross-border payment. NO VALUE MOVES. NEW-85.

        WHAT THIS METHOD ACTUALLY DOES, AND WHY THE FIX IS VOCABULARY.

        It used to return ``"status": "completed"`` over money that never
        moved. The test that settled the disposition is: STRIP THE OUTCOME
        CLAIM — IS THERE WORK LEFT? Here there is, and a lot of it:

            compliance        real corridor/threshold/sanctions evaluation
                              that can and does halt the operation
            exchange_rate     a real rate, oracle-first with a declared
                              fallback table
            converted_amount  a real conversion of the net amount
            fee_amount        real tiered fee arithmetic
            attestation       a real EAS call

        So this is category 6 (real-local-defective), not category 4: the
        guards and the arithmetic are genuine and the CUSTODY CLAIM was the
        only fabricated part. Removing the method would destroy working
        compliance and pricing. Renaming the outcome preserves them.

        Contrast ``remit``, which has none of the above: strip its claim and
        nothing is left, which is why its disposition is delegation, not
        vocabulary.

        WHAT DOES NOT HAPPEN HERE: no chain write, no signer, no tx_hash, no
        debit of any sender balance, no credit of any recipient balance. This
        service holds no ledger. The record written to ``self._payments`` is a
        record OF a payment instruction, not the payment.

        LIFTING CONDITION — what would license ``status: "completed"`` again:
          1. a real settlement leg exists (on-chain transfer or a payment-
             provider call) AND its result is what sets the status, and
          2. that leg is credential-gated with an honest refusal when
             unconfigured, in the ``not_deployed_response`` idiom, and
          3. the recipient is verifiably credited — the status is derived from
             the settlement result, never asserted alongside it.
        Satisfying 1 without 3 reproduces this exact defect one layer down.

        Args:
            sender: Sender address.
            recipient: Recipient address.
            amount: Amount in from_currency.
            from_currency: Source currency code.
            to_currency: Destination currency code.

        Returns:
            The payment RECORD, carrying ``settled``/``value_moved``/
            ``disclosure`` so no caller can read it as a completed transfer.
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
        fee_info = self.fee_for(amount)
        fee, net_amount = fee_info["fee_amount"], fee_info["net_amount"]

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
            # NEW-85: was "completed". Borrowed verbatim from the x402 idiom —
            # "recorded" alone could be read as "recorded on-chain"; this
            # cannot be misread as money having moved.
            "status": "recorded_unsettled",
            "settled": False,
            "value_moved": False,
            "disclosure": (
                "NOT SETTLED. Compliance was evaluated, the FX rate and fee "
                "are real, and this payment instruction has been RECORDED — "
                "but no value was transferred. This service holds no ledger "
                "and makes no on-chain or payment-provider call. The sender "
                "has not been debited and the recipient has not been credited."
            ),
            "created_at": now,
        }
        self._payments[payment_id] = payment
        self._address_payments.setdefault(sender, []).append(payment_id)
        self._address_payments.setdefault(recipient, []).append(payment_id)

        # Attest via Component 8
        await self._attest_payment(payment)

        logger.info(
            # NEW-85: was "Payment sent". An operator reading logs is a
            # surface too — inert means inert on every surface.
            "Payment RECORDED (NOT settled — no value moved): "
            "id=%s %s %.6f %s -> %.6f %s",
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

        # DOMAIN 14-A — CARRY THE RATE'S PROVENANCE. `get_rate` already reports
        # where the number came from ("identity" / "cache" / an oracle /
        # "fallback"), and this method read `rate` and DISCARDED `source`, so the
        # quote presented a hardcoded cross-rate as an `exchange_rate` with
        # nothing marking it as non-market.
        #
        # AND FALLBACK IS THE SHIPPED PATH, NOT AN EDGE CASE. The oracle carries
        # NO FIAT PAIRS at all under the shipped config (measured: BTC/USD,
        # DAI/USD, ETH/USD, LINK/USD, USDC/USD, USDT/USD), so EVERY fiat corridor
        # resolves to the fallback table. USD->EUR quoted 0.92 from a constant.
        #
        # THIRD INSTANCE OF ONE CLASS: a number rendered without the qualifier
        # its own producer attached. `total_value_usd` printed $0.00 without
        # saying it summed nothing; the APY printed 0.0 without saying no data
        # backed it; this printed a rate without saying it was unsourced. Every
        # time, the honest datum was one call up.
        rate_source = rate_data.get("source", "unknown")
        rate_is_market = rate_source not in ("fallback", "unknown")

        fee_info = self.fee_for(amount)
        fee, net = fee_info["fee_amount"], fee_info["net_amount"]
        converted = net * rate

        return {
            "source_amount": amount,
            "source_currency": from_currency,
            "destination_currency": to_currency,
            "exchange_rate": rate,
            "rate_source": rate_source,
            "rate_is_market": rate_is_market,
            "rate_disclosure": (
                None if rate_is_market else
                "INDICATIVE ONLY — this rate came from a built-in fallback "
                "table, not a live market feed. No oracle covers this currency "
                "pair in this deployment. Do not rely on it as a quoted price."
            ),
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

    # ------------------------------------------------------------------
    # Expanded cross-border operations
    # ------------------------------------------------------------------

    async def bridge_transfer(
        self, sender: str, recipient: str, amount: float, source_chain: str, dest_chain: str, token: str = "USDC",
    ) -> dict:
        """DISABLED. NEW-87. This never bridged anything.

        WHAT IT USED TO DO: mint a uuid, write
        ``{"status": "bridging", ...}`` into ``self._payments``, log, return.
        Zero awaits. No chain, no signer, no bridge protocol, no router
        address, no tx_hash. It validated nothing — not the amount, not the
        sender, not the chains, not the token.

        WHY DISABLED AND NOT REPOINTED. The honest implementation already
        exists: ``CCIPService.bridge_token_ccip`` — credential-gated first,
        a real ``Router.ccipSend``, returning ``"submitted"`` with a tx_hash
        and a non-custodial note. Delegating to it was the preferred
        disposition and it is NOT POSSIBLE without inventing data:

            this method has      CCIP requires
            ---------------      -------------
            source/dest_chain    destination_chain_selector (uint64 CCIP
            as NAMES             selector — a per-network magic number)
            token as a SYMBOL    token as an ERC-20 CONTRACT ADDRESS on the
            ("USDC")             source chain
            amount as a float    amount in integer base units

        Both mappings are deployment facts. Writing a chain-name -> selector
        table or a symbol -> address table from memory would be fabricating
        the exact class of data this audit exists to remove — and a wrong
        selector or a wrong token address sends real value to the wrong
        place. So: refuse, and name what a real repoint needs.

        LIFTING CONDITION — all four, or leave it disabled:
          1. a chain-name -> CCIP chain-selector map, sourced from Chainlink's
             published selector list for the target networks, in config;
          2. a token-symbol -> ERC-20 address map PER CHAIN, in config;
          3. this method converts ``amount`` to integer base units using the
             token's real ``decimals()``, not an assumed 6 or 18; and
          4. the returned status is DERIVED from what
             ``bridge_token_ccip`` returns — never asserted alongside it.
        Satisfying 1-3 without 4 reproduces this defect one layer down.
        """
        return {
            "status": "error",
            "error": (
                "Cross-chain bridging is disabled. This path never moved "
                "value: it recorded a dict and reported 'bridging'."
            ),
            "value_moved": False,
            "settled": False,
            "disabled_by": "NEW-87",
            "requested": {
                "sender": sender, "recipient": recipient, "amount": amount,
                "source_chain": source_chain, "dest_chain": dest_chain,
                "token": token,
            },
            "honest_alternative": (
                "ccip.bridge_token_ccip — a real Router.ccipSend. It is "
                "catalogued available=False pending its own configuration."
            ),
        }

    async def remit(
        self, sender: str, recipient: str, amount: float, from_currency: str, to_currency: str, corridor: str = "",
    ) -> dict:
        """Send a remittance. DELEGATES to send_payment. NEW-86.

        WHAT THIS USED TO BE: fifteen lines that minted a uuid, computed a
        fee, and returned ``"status": "sent"``. Zero awaits. It applied NONE
        of the guards its sibling applies, and it never converted currency at
        all — it reported ``net_amount`` in the SOURCE currency while
        declaring the remittance sent, for corridors the conversion layer
        cannot even price.

        WHY DELEGATION AND NOT REMOVAL. `remit` and `send_payment` are the
        same operation: money across a corridor. Their signatures already
        agree; the only extra parameter, ``corridor``, is one `send_payment`
        derives itself. So this is the NEW-67 shape — a shadow over a real
        implementation that lives one method away.

        WHAT DELEGATION INHERITS, each of which `remit` previously skipped:
          * sanctions screening        * KYC threshold check
          * travel-rule flagging       * the _max_payment cap
          * negative/zero rejection    * real FX conversion
          * EAS attestation
        And, since NEW-85, the honest custody vocabulary: the result carries
        ``settled: False`` / ``value_moved: False`` / ``disclosure``.

        ORDERING NOTE: this delegation was deliberately NOT shipped before
        NEW-85. Delegating into a method that still claimed ``"completed"``
        would have turned "lies about sending, unguarded" into "lies about
        sending, guarded" — better gating, and not a fix.

        ``corridor`` is accepted for signature compatibility and ignored:
        `send_payment` derives the corridor from the currency pair, and
        honouring a caller-supplied one would let the caller choose which
        compliance thresholds apply to their own payment.
        """
        result = await self.send_payment(
            sender, recipient, amount, from_currency, to_currency,
        )
        # Preserve the legacy `id` key so existing callers keep working; the
        # canonical key is payment_id, as send_payment returns it.
        if "payment_id" in result:
            result.setdefault("id", result["payment_id"])
        return result

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
