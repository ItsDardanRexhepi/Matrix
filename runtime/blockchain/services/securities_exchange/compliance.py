"""
ERC3643Compliance — ERC-3643 compliant transfer restrictions and investor
whitelisting for the tokenized securities exchange.

Handles accredited investor verification, jurisdiction checks, and
holding period enforcement.
"""

from __future__ import annotations

import logging
import time
import uuid
from typing import Any

logger = logging.getLogger(__name__)

# Restricted jurisdictions (OFAC-style)
_RESTRICTED_JURISDICTIONS = frozenset({"KP", "IR", "SY", "CU", "RU_CRIMEA"})

# Minimum holding period in seconds (default 12 months for Reg D)
_DEFAULT_HOLDING_PERIOD = 365 * 86400


class ERC3643Compliance:
    """ERC-3643 compliant transfer restriction engine.

    Config keys (under ``config["securities"]``):
        restricted_jurisdictions (list[str]): ISO codes to block.
        default_holding_period (int): Seconds tokens must be held.
        require_accreditation (bool): Require accredited investor status (default True).
    """

    def __init__(self, config: dict) -> None:
        self._config = config
        s_cfg: dict[str, Any] = config.get("securities", {})

        self._restricted: frozenset[str] = frozenset(
            s_cfg.get("restricted_jurisdictions", _RESTRICTED_JURISDICTIONS)
        )
        self._default_holding: int = int(
            s_cfg.get("default_holding_period", _DEFAULT_HOLDING_PERIOD)
        )
        self._require_accreditation: bool = bool(
            s_cfg.get("require_accreditation", True)
        )

        # investor_address -> investor record
        self._investors: dict[str, dict[str, Any]] = {}
        # (security_id, investor_address) -> whitelist record
        self._whitelists: dict[tuple[str, str], dict[str, Any]] = {}
        # (security_id, investor_address) -> acquisition timestamp
        self._holdings: dict[tuple[str, str], int] = {}

        logger.info(
            "ERC3643Compliance initialised (holding_period=%ds, require_accreditation=%s).",
            self._default_holding, self._require_accreditation,
        )

    async def whitelist_investor(
        self, security_id: str, investor: str, credentials: dict
    ) -> dict:
        """Whitelist an investor for a specific security.

        Args:
            security_id: The security token identifier.
            investor: Investor wallet address.
            credentials: Dict with keys like 'accredited', 'jurisdiction',
                         'kyc_verified', 'aml_verified', 'investor_type'.

        Returns:
            Whitelist record with status.
        """
        if not security_id or not investor:
            raise ValueError("security_id and investor are required")

        jurisdiction = credentials.get("jurisdiction", "")
        if jurisdiction in self._restricted:
            logger.warning(
                "Whitelist rejected: investor=%s jurisdiction=%s is restricted.",
                investor, jurisdiction,
            )
            return {
                "security_id": security_id,
                "investor": investor,
                "whitelisted": False,
                "reason": f"Jurisdiction {jurisdiction} is restricted",
            }

        if self._require_accreditation and not credentials.get("accredited", False):
            logger.warning(
                "Whitelist rejected: investor=%s not accredited.", investor,
            )
            return {
                "security_id": security_id,
                "investor": investor,
                "whitelisted": False,
                "reason": "Investor is not accredited",
            }

        if not credentials.get("kyc_verified", False):
            return {
                "security_id": security_id,
                "investor": investor,
                "whitelisted": False,
                "reason": "KYC verification required",
            }

        now = int(time.time())
        investor_record = {
            "address": investor,
            "jurisdiction": jurisdiction,
            "accredited": credentials.get("accredited", False),
            "kyc_verified": credentials.get("kyc_verified", False),
            "aml_verified": credentials.get("aml_verified", False),
            "investor_type": credentials.get("investor_type", "individual"),
            "registered_at": now,
        }
        self._investors[investor] = investor_record

        wl_record = {
            "id": str(uuid.uuid4()),
            "security_id": security_id,
            "investor": investor,
            "whitelisted": True,
            "whitelisted_at": now,
            "credentials_hash": hash(frozenset(credentials.items())),
        }
        self._whitelists[(security_id, investor)] = wl_record

        logger.info(
            "Investor whitelisted: security=%s investor=%s jurisdiction=%s",
            security_id, investor, jurisdiction,
        )
        return wl_record

    async def check_transfer(
        self, security_id: str, from_addr: str, to_addr: str, amount: int
    ) -> dict:
        """Check whether a transfer is compliant under ERC-3643 rules.

        Verifies:
        1. Both parties are whitelisted for this security.
        2. Neither party is in a restricted jurisdiction.
        3. Holding period has elapsed for the sender.
        4. Amount is positive.

        Returns:
            Dict with 'allowed' bool and 'reason' if blocked.
        """
        if amount <= 0:
            return {"allowed": False, "reason": "Transfer amount must be positive"}

        # Check sender whitelist (issuers bypass)
        sender_wl = self._whitelists.get((security_id, from_addr))
        if not sender_wl or not sender_wl.get("whitelisted"):
            return {
                "allowed": False,
                "reason": f"Sender {from_addr} is not whitelisted for {security_id}",
            }

        # Check receiver whitelist
        receiver_wl = self._whitelists.get((security_id, to_addr))
        if not receiver_wl or not receiver_wl.get("whitelisted"):
            return {
                "allowed": False,
                "reason": f"Receiver {to_addr} is not whitelisted for {security_id}",
            }

        # Jurisdiction check on both parties
        sender_info = self._investors.get(from_addr, {})
        receiver_info = self._investors.get(to_addr, {})

        for label, info in [("Sender", sender_info), ("Receiver", receiver_info)]:
            jur = info.get("jurisdiction", "")
            if jur in self._restricted:
                return {
                    "allowed": False,
                    "reason": f"{label} jurisdiction {jur} is restricted",
                }

        # Holding period enforcement
        holding_key = (security_id, from_addr)
        acquired_at = self._holdings.get(holding_key)
        if acquired_at is not None:
            elapsed = int(time.time()) - acquired_at
            if elapsed < self._default_holding:
                remaining = self._default_holding - elapsed
                return {
                    "allowed": False,
                    "reason": (
                        f"Holding period not met: {remaining}s remaining "
                        f"(required {self._default_holding}s)"
                    ),
                }

        logger.info(
            "Transfer approved: security=%s from=%s to=%s amount=%d",
            security_id, from_addr, to_addr, amount,
        )
        return {"allowed": True, "reason": "Transfer compliant"}

    async def get_investor_status(self, investor: str) -> dict:
        """Get the compliance status for an investor across all securities.

        Returns:
            Investor record with whitelisted securities list.
        """
        record = self._investors.get(investor)
        if not record:
            return {
                "investor": investor,
                "registered": False,
                "whitelisted_securities": [],
            }

        whitelisted = [
            wl["security_id"]
            for (sec_id, addr), wl in self._whitelists.items()
            if addr == investor and wl.get("whitelisted")
        ]

        return {
            "investor": investor,
            "registered": True,
            "jurisdiction": record.get("jurisdiction", ""),
            "accredited": record.get("accredited", False),
            "kyc_verified": record.get("kyc_verified", False),
            "aml_verified": record.get("aml_verified", False),
            "investor_type": record.get("investor_type", "individual"),
            "whitelisted_securities": whitelisted,
        }

    def record_acquisition(self, security_id: str, investor: str) -> None:
        """Record the timestamp when an investor acquires a security.

        Used internally to track holding periods.
        """
        self._holdings[(security_id, investor)] = int(time.time())
