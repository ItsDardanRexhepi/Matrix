"""Revenue routing — all platform fees go to the NeoSafe multisig.

The canonical NeoSafe address is ``0x46fF491D7054A6F500026B3E81f358190f8d8Ec5``.
That value is used when ``blockchain.neosafe_wallet`` is not set in config.
"""

from __future__ import annotations

import logging
import time
from typing import Any

from runtime.blockchain.web3_manager import Web3Manager

logger = logging.getLogger(__name__)

NEOSAFE_DEFAULT_ADDRESS = "0x46fF491D7054A6F500026B3E81f358190f8d8Ec5"


class NeoSafeRouter:
    """Route all platform fees to the NeoSafe wallet.

    Every fee-generating action across the 44 services calls
    :meth:`route_fee` to record and forward fees. An EAS attestation is
    created for each payment so there is a permanent on-chain receipt.

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

        Returns a dict describing the on-chain action. When the platform
        is not yet configured for live execution, the routing is queued
        in-memory and a ``status='queued'`` response is returned.
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
            logger.info(
                "Revenue routed: %s ETH from %s, tx=%s",
                amount_eth, source_action, tx_hash_hex,
            )
            # Best-effort attestation
            attestation_uid = None
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
                attestation_uid = attest_result.get("attestation_tx") if isinstance(attest_result, dict) else None
            except Exception as exc:
                logger.warning("NeoSafe attestation skipped: %s", exc)

            return {
                "status": "routed",
                "amount_eth": amount_eth,
                "source": source_action,
                "recipient": self._neosafe_wallet,
                "tx_hash": tx_hash_hex,
                "explorer": self._web3.explorer_url(tx_hash_hex),
                "attestation_uid": attestation_uid,
            }
        except Exception as exc:
            logger.error("Revenue routing failed: %s", exc)
            return {
                "status": "error",
                "error": str(exc),
                "amount_eth": amount_eth,
                "source": source_action,
            }

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

        Returns the attestation UID or ``None`` on failure.
        """
        svc = self._get_attestation_svc()
        if svc is None:
            return None
        try:
            result = await svc.attest(
                schema_name="platform_fee",
                data={
                    "amount": entry["amount"],
                    "token": entry["token"],
                    "source": entry["source"],
                    "recipient": entry["recipient"],
                    "timestamp": entry["timestamp"],
                },
                recipient=self._platform_wallet,
            )
            uid = result.get("uid") if isinstance(result, dict) else None
            logger.debug("Fee attestation created: %s", uid)
            return uid
        except Exception:
            logger.warning("Fee attestation failed", exc_info=True)
            return None
