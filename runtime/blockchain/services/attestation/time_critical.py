"""
Time-Critical Attestation Handler for 0pnMatrx.

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
            from eth_abi import encode

            from runtime.blockchain.eas_client import EAS_ATTEST_ABI

            # Encode the attestation data
            encoded_data = encode(
                ["string", "string", "string", "uint256"],
                [
                    "0pnMatrx",
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
            account = Account.from_key(self.paymaster_key)
            signed = account.sign_transaction(tx)
            tx_hash = w3.eth.send_raw_transaction(signed.raw_transaction)
            receipt = w3.eth.wait_for_transaction_receipt(tx_hash, timeout=60)

            confirmed_at = time.time()
            latency_ms = round((confirmed_at - submitted_at) * 1000, 2)

            logger.info(
                "Time-critical attestation confirmed: tx=%s category=%s latency=%sms",
                tx_hash.hex(), category, latency_ms,
            )

            return {
                "status": "attested" if receipt["status"] == 1 else "failed",
                "attestation_tx": tx_hash.hex(),
                "schema_uid": schema_uid,
                "category": category,
                "recipient": recipient,
                "block_number": receipt["blockNumber"],
                "latency_ms": latency_ms,
                "time_critical": True,
                "gas_paid_by": "platform (0pnMatrx)",
                "data": data,
            }

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
