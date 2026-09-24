"""
Time-Critical Attestation Handler for The Matrix.

Certain attestations must NEVER be batched — they must be submitted
immediately to the chain. This includes dispute filings, rights reversions,
ban records, and emergency freezes. These are the actions where delay
could cause legal or financial harm.
"""

from __future__ import annotations

import logging
import time
from typing import Any

logger = logging.getLogger(__name__)

# Categories that require immediate attestation — never batched
TIME_CRITICAL_CATEGORIES: frozenset[str] = frozenset({
    "dispute_filing",
    "rights_reversion",
    "ban_record",
    "emergency_freeze",
})


class TimeCriticalHandler:
    """
    Immediately submits attestations without batching.

    Time-critical attestations bypass the batch processor entirely and are
    sent directly to the EAS contract. Gas is covered by the platform.
    """

    def __init__(self, config: dict):
        self.config = config
        bc = config.get("blockchain", {})
        self.rpc_url: str = bc.get("rpc_url", "")
        self.eas_contract: str = bc.get("eas_contract", "")
        self.paymaster_key: str = bc.get("paymaster_private_key", "")
        self.platform_wallet: str = bc.get("platform_wallet", "")
        self.chain_id: int = bc.get("chain_id", 84532)
        self._web3 = None

    @property
    def web3(self):
        """Lazy-load Web3 connection."""
        if self._web3 is None:
            from web3 import Web3
            self._web3 = Web3(Web3.HTTPProvider(self.rpc_url))
        return self._web3

    @staticmethod
    def is_time_critical(category: str) -> bool:
        """Check whether a category requires immediate attestation."""
        return category in TIME_CRITICAL_CATEGORIES

    async def attest_now(
        self,
        schema_uid: str,
        data: dict[str, Any],
        recipient: str,
        category: str,
    ) -> dict[str, Any]:
        """
        Immediately submit an attestation without batching.

        The platform pays the gas. It is signed through
        "eas.attest_time_critical", an exemption listed in
        UNMETERED_PLATFORM_OPERATIONS, so no sponsorship allowlist or daily
        cap is checked.

        Args:
            schema_uid: The EAS schema UID to attest under.
            data: Attestation payload.
            recipient: Ethereum address of the attestation recipient.
            category: Time-critical category (must be in TIME_CRITICAL_CATEGORIES).

        Returns:
            Dict with attestation result including tx hash, status, and timing.

        Raises:
            ValueError: If the category is not recognized as time-critical.
        """
        if category not in TIME_CRITICAL_CATEGORIES:
            raise ValueError(
                f"Unknown time-critical category '{category}'. "
                f"Valid categories: {', '.join(sorted(TIME_CRITICAL_CATEGORIES))}"
            )

        submitted_at = time.time()
        logger.info(
            "Submitting time-critical attestation: category=%s recipient=%s",
            category, recipient,
        )

        try:
            from web3 import Web3
            from eth_account import Account
            from runtime.blockchain.sponsorship import unmetered_platform_signer
            from eth_abi import encode

            from runtime.blockchain.eas_client import EAS_ATTEST_ABI

            # Encode the attestation data
            encoded_data = encode(
                ["string", "string", "string", "uint256"],
                [
                    "The Matrix",
                    category,
                    data.get("agent", "system"),
                    int(submitted_at),
                ],
            )

            # Build the EAS attest transaction
            w3 = self.web3
            eas = w3.eth.contract(
                address=Web3.to_checksum_address(self.eas_contract),
                abi=EAS_ATTEST_ABI,
            )

            schema_bytes = bytes.fromhex(schema_uid.replace("0x", ""))
            tx = eas.functions.attest(
                (
                    schema_bytes,
                    (
                        Web3.to_checksum_address(recipient),
                        0,       # no expiration
                        True,    # revocable
                        b"\x00" * 32,  # no reference UID
                        encoded_data,
                        0,       # no value
                    ),
                )
            ).build_transaction({
                "from": self.platform_wallet,
                "chainId": self.chain_id,
                "gas": 500_000,  # higher gas for time-critical
                "gasPrice": w3.eth.gas_price,
                "nonce": w3.eth.get_transaction_count(self.platform_wallet),
            })

            # Sign and send immediately
            account = unmetered_platform_signer(self.paymaster_key, "eas.attest_time_critical")
            signed = account.sign_transaction(tx)
            tx_hash = w3.eth.send_raw_transaction(signed.raw_transaction)

        except ImportError as exc:
            logger.warning("Time-critical attestation skipped — missing dependency: %s", exc)
            return {
                "status": "skipped",
                "reason": f"Missing dependency: {exc}",
                "category": category,
                "recipient": recipient,
                "time_critical": True,
                "data": data,
            }
        except Exception as exc:
            logger.error(
                "Time-critical attestation FAILED: category=%s error=%s",
                category, exc, exc_info=True,
            )
            return {
                "status": "failed",
                "error": str(exc),
                "category": category,
                "recipient": recipient,
                "time_critical": True,
                "data": data,
            }

        # A SENT ATTESTATION IS NOT DECIDED BY AN `except`. The receipt wait sat
        # inside the `try` above, so a wait that ran out came back "failed" with
        # no hash, and an emergency freeze, a ban record, a dispute filing or a
        # rights reversion the platform had signed and sent was filed "ACTION
        # DECLINED". Once the hash exists the transaction is out: confirmed ->
        # "attested", reverted -> "failed", no receipt in time -> "pending" with
        # the hash and `broadcast: True`. Off the event loop, too.
        from runtime.blockchain.web3_manager import RawWeb3Receipts, settle_transaction

        attestation_tx = tx_hash.hex() if hasattr(tx_hash, "hex") else str(tx_hash)
        outcome = await settle_transaction(
            RawWeb3Receipts(w3), attestation_tx, "attest_now", "attestation",
            {
                "attestation_tx": attestation_tx,
                "schema_uid": schema_uid,
                "category": category,
                "recipient": recipient,
                "time_critical": True,
                "gas_paid_by": "platform (The Matrix)",
                "data": data,
            },
            settled_status="attested",
            timeout=60,
        )
        if outcome.get("value_moved") is True:
            # The helper speaks for transfers. An attestation moves no value.
            outcome["value_moved"] = None
        if outcome.get("settled") is True:
            outcome["latency_ms"] = round((time.time() - submitted_at) * 1000, 2)
            logger.info(
                "Time-critical attestation %s: tx=%s category=%s latency=%sms",
                outcome["status"], attestation_tx, category, outcome["latency_ms"],
            )
        return outcome
