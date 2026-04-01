"""
ComplianceScaffold — regulatory compliance checking for cross-border payments.

Corridors are country/currency pairs with regulatory requirements.
Flags transactions that need additional verification.  All cross-border
payments are attested via Component 8.
"""

from __future__ import annotations

import logging
import time
from typing import Any

logger = logging.getLogger(__name__)

# Corridor-specific requirements
# corridor format: "FROM_CURRENCY->TO_CURRENCY"
_CORRIDOR_REQUIREMENTS: dict[str, dict[str, Any]] = {
    "USD->EUR": {
        "kyc_required": True,
        "max_without_id": 1_000.0,
        "reporting_threshold": 10_000.0,
        "sanctions_check": True,
        "regulations": ["FinCEN", "EU-AMLD"],
    },
    "USD->GBP": {
        "kyc_required": True,
        "max_without_id": 1_000.0,
        "reporting_threshold": 10_000.0,
        "sanctions_check": True,
        "regulations": ["FinCEN", "FCA"],
    },
    "USD->JPY": {
        "kyc_required": True,
        "max_without_id": 500.0,
        "reporting_threshold": 10_000.0,
        "sanctions_check": True,
        "regulations": ["FinCEN", "FSA-Japan"],
    },
    "EUR->USD": {
        "kyc_required": True,
        "max_without_id": 1_000.0,
        "reporting_threshold": 10_000.0,
        "sanctions_check": True,
        "regulations": ["EU-AMLD", "FinCEN"],
    },
    "EUR->GBP": {
        "kyc_required": True,
        "max_without_id": 1_000.0,
        "reporting_threshold": 15_000.0,
        "sanctions_check": True,
        "regulations": ["EU-AMLD", "FCA"],
    },
    "GBP->USD": {
        "kyc_required": True,
        "max_without_id": 1_000.0,
        "reporting_threshold": 10_000.0,
        "sanctions_check": True,
        "regulations": ["FCA", "FinCEN"],
    },
    "USD->CHF": {
        "kyc_required": True,
        "max_without_id": 1_000.0,
        "reporting_threshold": 10_000.0,
        "sanctions_check": True,
        "regulations": ["FinCEN", "FINMA"],
    },
}

# Default requirements for corridors not explicitly listed
_DEFAULT_REQUIREMENTS: dict[str, Any] = {
    "kyc_required": True,
    "max_without_id": 500.0,
    "reporting_threshold": 10_000.0,
    "sanctions_check": True,
    "regulations": ["general_AML"],
}


class ComplianceScaffold:
    """Regulatory compliance checking for cross-border payments.

    Config keys (under ``config["cross_border"]``):
        corridor_overrides (dict): Override corridor requirements.
        sanctions_list (list): List of sanctioned addresses.
    """

    def __init__(self, config: dict) -> None:
        self._config = config
        cb_cfg = config.get("cross_border", {})

        self._corridor_reqs: dict[str, dict[str, Any]] = {
            **_CORRIDOR_REQUIREMENTS,
            **cb_cfg.get("corridor_overrides", {}),
        }
        self._sanctions_list: set[str] = set(
            cb_cfg.get("sanctions_list", [])
        )

        # Verification records: address -> verification status
        self._verifications: dict[str, dict[str, Any]] = {}

    async def check_compliance(
        self,
        sender: str,
        recipient: str,
        amount: float,
        corridor: str,
    ) -> dict:
        """Check whether a cross-border payment is compliant.

        Args:
            sender: Sender address.
            recipient: Recipient address.
            amount: Payment amount (in source currency).
            corridor: Currency corridor (e.g. "USD->EUR").

        Returns:
            Dict with ``approved`` bool, ``flags``, ``requirements``.
        """
        reqs = self._corridor_reqs.get(corridor, dict(_DEFAULT_REQUIREMENTS))
        flags: list[str] = []
        needs_verification = False

        # Sanctions check
        if reqs.get("sanctions_check", True):
            if sender in self._sanctions_list:
                return {
                    "approved": False,
                    "reason": "Sender address is sanctioned",
                    "flags": ["sanctions_hit"],
                    "corridor": corridor,
                }
            if recipient in self._sanctions_list:
                return {
                    "approved": False,
                    "reason": "Recipient address is sanctioned",
                    "flags": ["sanctions_hit"],
                    "corridor": corridor,
                }

        # KYC check
        if reqs.get("kyc_required", False):
            max_without_id = float(reqs.get("max_without_id", 500))
            if amount > max_without_id:
                sender_verified = self._verifications.get(sender, {}).get(
                    "verified", False,
                )
                if not sender_verified:
                    flags.append("kyc_required")
                    needs_verification = True

        # Reporting threshold
        reporting = float(reqs.get("reporting_threshold", 10_000))
        if amount >= reporting:
            flags.append("reporting_threshold_exceeded")
            # Still approved but flagged for reporting

        # Crypto-specific checks
        crypto_currencies = {"ETH", "USDC", "USDT", "DAI"}
        parts = corridor.split("->")
        if len(parts) == 2:
            from_cur, to_cur = parts
            if from_cur in crypto_currencies or to_cur in crypto_currencies:
                if amount > 3_000:
                    flags.append("travel_rule_applicable")

        approved = not needs_verification

        result: dict[str, Any] = {
            "approved": approved,
            "corridor": corridor,
            "amount": amount,
            "flags": flags,
            "requirements": reqs,
            "regulations": reqs.get("regulations", []),
            "checked_at": int(time.time()),
        }

        if needs_verification:
            result["reason"] = (
                "Additional verification required for this amount"
            )
            result["verification_instructions"] = (
                "Complete KYC verification to proceed with payments "
                f"above {reqs.get('max_without_id', 500)} {parts[0] if len(parts) == 2 else 'units'}"
            )

        logger.info(
            "Compliance check: corridor=%s amount=%.2f approved=%s flags=%s",
            corridor, amount, approved, flags,
        )
        return result

    async def get_requirements(self, corridor: str) -> dict:
        """Get regulatory requirements for a corridor.

        Args:
            corridor: Currency corridor (e.g. "USD->EUR").

        Returns:
            Dict with corridor requirements.
        """
        reqs = self._corridor_reqs.get(corridor, dict(_DEFAULT_REQUIREMENTS))
        return {
            "corridor": corridor,
            "requirements": reqs,
            "is_default": corridor not in self._corridor_reqs,
        }

    async def verify_address(self, address: str, verification: dict) -> dict:
        """Record KYC verification for an address.

        Args:
            address: The address being verified.
            verification: Dict with ``level`` ("basic", "enhanced"),
                          ``provider``, ``reference_id``.

        Returns:
            Verification record.
        """
        record: dict[str, Any] = {
            "address": address,
            "verified": True,
            "level": verification.get("level", "basic"),
            "provider": verification.get("provider", ""),
            "reference_id": verification.get("reference_id", ""),
            "verified_at": int(time.time()),
        }
        self._verifications[address] = record

        logger.info("Address verified: %s level=%s", address, record["level"])
        return record
