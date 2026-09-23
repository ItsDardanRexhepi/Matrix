"""Revenue routing — all platform fees go to the NeoSafe multisig.

The canonical NeoSafe address is ``0x46fF491D7054A6F500026B3E81f358190f8d8Ec5``.
That value is used when ``blockchain.neosafe_wallet`` is not set in config.
"""

from __future__ import annotations

import logging
import time
from typing import Any

from runtime.blockchain.web3_manager import Web3Manager, settle_transaction
from runtime.protocols.outcome_truth import SUCCESS, report_of

logger = logging.getLogger(__name__)

NEOSAFE_DEFAULT_ADDRESS = "0x46fF491D7054A6F500026B3E81f358190f8d8Ec5"


class NeoSafeRouter:
    """Record platform fees against the NeoSafe wallet, and send revenue to it.

    :meth:`route_fee` records a fee in this process's in-memory ledger and
    attests it through EAS; it moves no funds. :meth:`route_revenue` sends
    ETH to the NeoSafe wallet and attests it once the transfer is mined.
    Nothing in the gateway calls either yet: no platform action maps to this
    router, and examples/07_revenue_to_neosafe.py calls it directly.

    Config keys used:
        - ``blockchain.platform_wallet`` — the NeoSafe wallet address
        - ``blockchain.chain_id`` — target chain (default ``8453`` = Base)
    """

    def __init__(self, config: dict) -> None:
        blockchain_cfg = config.get("blockchain", {})
        self._neosafe_wallet: str = (
            blockchain_cfg.get("neosafe_wallet")
            or blockchain_cfg.get("platform_wallet")
            or NEOSAFE_DEFAULT_ADDRESS
        )
        # Backwards-compatible alias used by existing callers
        self._platform_wallet: str = self._neosafe_wallet
        self._chain_id: int = blockchain_cfg.get("chain_id", 8453)
        self._config = config
        self._web3 = Web3Manager.get_shared(config)

        # In-memory ledger for this process lifetime
        self._ledger: list[dict[str, Any]] = []
        self._total_by_token: dict[str, float] = {}

        # Lazy attestation reference
        self._attestation_svc = None

        if not self._platform_wallet:
            logger.warning(
                "NeoSafeRouter: no platform_wallet configured — "
                "fees will be logged but not routed on-chain."
            )
        else:
            logger.info(
                "NeoSafeRouter initialised. Fees route to %s on chain %d.",
                self._platform_wallet,
                self._chain_id,
            )

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    async def route_fee(
        self,
        amount: float,
        token: str,
        source: str,
        description: str,
    ) -> dict[str, Any]:
        """Record and attest a platform fee payment.

        Parameters
        ----------
        amount:
            Fee amount in *token* units.
        token:
            Token symbol (e.g. ``USDC``, ``ETH``).
        source:
            Identifier of the service or action that generated the fee.
        description:
            Human-readable description of the fee.

        Returns
        -------
        dict
            Receipt containing the fee details and attestation UID (if available).
        """
        if amount <= 0:
            return {"status": "skipped", "reason": "non-positive amount"}

        entry: dict[str, Any] = {
            "amount": amount,
            "token": token,
            "source": source,
            "description": description,
            "recipient": self._platform_wallet,
            "chain_id": self._chain_id,
            "timestamp": int(time.time()),
        }

        self._ledger.append(entry)
        self._total_by_token[token] = self._total_by_token.get(token, 0.0) + amount

        logger.info(
            "Fee routed: %.6f %s from %s -> %s (%s)",
            amount, token, source, self._platform_wallet, description,
        )

        # Attest on-chain
        attestation_uid = await self._attest_fee(entry)
        entry["attestation_uid"] = attestation_uid

        return {
            "status": "ok",
            "fee": entry,
        }

    async def route_revenue(
        self, amount_eth: float, source_action: str
    ) -> dict[str, Any]:
        """Send *amount_eth* ETH to the NeoSafe multisig and attest the routing.

        Reports what the CHAIN did, not what the node accepted:

            mined, status 1   -> "routed", settled, value moved, and only then
                                 is the EAS attestation written
            mined, status 0   -> "failed" — it REVERTED; nothing moved and gas
                                 was still spent
            no receipt in time-> "pending", carrying the hash: not a refusal and
                                 not a failure, and not attested

        When the platform is not configured for live execution the routing is
        queued in-memory and ``status='queued'`` is returned.
        """
        if amount_eth <= 0:
            return {"status": "skipped", "reason": "non-positive amount"}

        if not self._web3.available:
            logger.info(
                "Revenue routing queued: %.6f ETH from %s "
                "(blockchain not configured)",
                amount_eth, source_action,
            )
            self._ledger.append({
                "amount": amount_eth,
                "token": "ETH",
                "source": source_action,
                "recipient": self._neosafe_wallet,
                "timestamp": int(time.time()),
                "queued": True,
            })
            return {
                "status": "queued",
                "message": (
                    "Revenue routing queued — will execute when blockchain "
                    "is configured"
                ),
                "amount_eth": amount_eth,
                "source": source_action,
                "recipient": self._neosafe_wallet,
            }

        try:
            w3 = self._web3.w3
            amount_wei = w3.to_wei(amount_eth, "ether")
            tx_hash_hex = await self._web3.send_transaction({
                "to": w3.to_checksum_address(self._neosafe_wallet),
                "value": amount_wei,
                "gas": 21000,
            })
        except Exception as exc:
            logger.error("Revenue routing failed: %s", exc)
            return {
                "status": "error",
                "error": str(exc),
                "amount_eth": amount_eth,
                "source": source_action,
            }

        # A BROADCAST IS NOT A SETTLEMENT. `send_transaction` returns when a
        # NODE ACCEPTED the raw bytes. `"routed"` was returned from that, and
        # `routed` reads as a real outcome, so the dispatcher EAS-attested it and
        # the public feed announced platform revenue that may have reverted.
        # 19-C established the fix in restaking and 21-C wrote it again in
        # creator_platforms; this is the same helper, next to `wait_for_receipt`.
        outcome = await settle_transaction(
            self._web3, tx_hash_hex, "route_revenue", "neosafe",
            {
                "amount_eth": amount_eth,
                "source": source_action,
                "recipient": self._neosafe_wallet,
                "explorer": self._web3.explorer_url(tx_hash_hex),
            },
            settled_status="routed",
        )

        # THE ATTESTATION FOLLOWS THE RECEIPT, NOT THE BROADCAST. It was written
        # from the same unconfirmed hash — a claim about platform revenue put on
        # a public chain, for third parties, before anything was mined. An
        # attestation of a transfer that reverted cannot be taken back.
        outcome["attestation_uid"] = None
        if outcome.get("settled") and outcome.get("value_moved"):
            logger.info(
                "Revenue routed: %s ETH from %s, tx=%s",
                amount_eth, source_action, tx_hash_hex,
            )
            try:
                from runtime.blockchain.eas_client import EASClient
                eas = EASClient(self._config)
                attest_result = await eas.attest(
                    action="revenue_routing",
                    agent="neosafe_router",
                    details={
                        "amount_eth": amount_eth,
                        "source": source_action,
                        "tx_hash": tx_hash_hex,
                    },
                )
                outcome["attestation_uid"] = (
                    attest_result.get("attestation_tx")
                    if isinstance(attest_result, dict) else None
                )
                # The client reports a refusal by RETURNING one, so "we attested
                # it" is read from the attestation, not from reaching this line.
                outcome["attested"] = report_of(attest_result) is SUCCESS
            except Exception as exc:
                logger.warning("NeoSafe attestation skipped: %s", exc)
                outcome["attested"] = False
        else:
            outcome["attested"] = False

        return outcome

    async def get_total_revenue(self) -> dict[str, Any]:
        """Return accumulated revenue totals by token.

        Returns
        -------
        dict
            ``platform_wallet``, per-token totals, and total fee count.
        """
        return {
            "platform_wallet": self._platform_wallet,
            "totals_by_token": dict(self._total_by_token),
            "total_fee_count": len(self._ledger),
            "chain_id": self._chain_id,
        }

    # ------------------------------------------------------------------
    # Internal
    # ------------------------------------------------------------------

    def _get_attestation_svc(self):
        """Lazily obtain the AttestationService from the registry."""
        if self._attestation_svc is None:
            try:
                from runtime.blockchain.services.registry import ServiceRegistry
                registry = ServiceRegistry(self._config)
                self._attestation_svc = registry.get("attestation")
            except Exception:
                logger.debug("AttestationService not available for NeoSafe fee attestation.")
        return self._attestation_svc

    async def _attest_fee(self, entry: dict[str, Any]) -> str | None:
        """Create an EAS attestation for a fee payment.

        Returns the attestation TRANSACTION HASH when the attestation was
        actually submitted on-chain, else ``None``.

        NEW-42: this previously documented "the attestation UID", which no
        code path has ever produced — `AttestationService.attest` returns
        `attestation_tx` on the time-critical branch and a queue disclosure on
        the batch branch. Deriving a real EAS uid means reading the receipt
        logs, which nothing here does. The docstring described the imagined
        return shape the caller was written against.
        """
        svc = self._get_attestation_svc()
        if svc is None:
            return None
        try:
            # NEW-42 (instance 2 of 2): same `schema_name=` drift as
            # service_dispatcher._attest_action — TypeError on every call,
            # swallowed by the `except` below, so no platform fee has ever
            # been attested.
            result = await svc.attest(
                schema_uid="",
                data={
                    "amount": entry["amount"],
                    "token": entry["token"],
                    "source": entry["source"],
                    "recipient": entry["recipient"],
                    "timestamp": entry["timestamp"],
                },
                recipient=self._platform_wallet,
            )
            # NEW-42, second half: this read `result.get("uid")` — a key
            # `attest` NEVER returns on ANY branch. Read from the source
            # rather than assumed:
            #   time-critical success -> {"status": "attested",
            #                             "attestation_tx": <tx hash>, ...}
            #   time-critical failure -> {"status": "failed"|"skipped", ...}
            #   batch path            -> the NEW-51 queue disclosure
            # There is no attestation UID anywhere. The EAS uid is derivable
            # only by reading the receipt logs, which nothing here does.
            #
            # So even once the TypeError above was fixed, this would have
            # returned None forever — the caller was written against an
            # IMAGINED return shape. (I first "fixed" it to
            # `result.get("attestation_uid")`, which is equally invented;
            # checking time_critical.py's actual returns is what caught it.)
            if not isinstance(result, dict):
                return None
            tx_hash = result.get("attestation_tx")
            if result.get("status") == "attested" and tx_hash:
                logger.debug("Fee attestation submitted: tx=%s", tx_hash)
                return tx_hash
            logger.debug(
                "Fee attestation NOT submitted (%s)",
                result.get("disclosure") or result.get("error") or result.get("status"),
            )
            return None
        except Exception:
            logger.warning("Fee attestation failed", exc_info=True)
            return None
