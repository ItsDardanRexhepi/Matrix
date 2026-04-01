"""Revenue routing — all platform fees go to NeoSafe wallet."""

from __future__ import annotations

import logging
import time
from typing import Any

logger = logging.getLogger(__name__)


class NeoSafeRouter:
    """Route all platform fees to the NeoSafe wallet.

    Every fee-generating action across the 30 blockchain services calls
    :meth:`route_fee` to record and forward fees. An EAS attestation is
    created for each payment so there is a permanent on-chain receipt.

    Config keys used:
        - ``blockchain.platform_wallet`` — the NeoSafe wallet address
        - ``blockchain.chain_id`` — target chain (default ``8453`` = Base)
    """

    def __init__(self, config: dict) -> None:
        blockchain_cfg = config.get("blockchain", {})
        self._platform_wallet: str = blockchain_cfg.get("platform_wallet", "")
        self._chain_id: int = blockchain_cfg.get("chain_id", 8453)
        self._config = config

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
