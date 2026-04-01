"""
AttestationService — Universal EAS attestation layer for 0pnMatrx.

This is the single entry point for ALL attestations across the platform.
It routes time-critical attestations (disputes, bans, rights reversions,
emergency freezes) to immediate submission, and batches everything else
for gas efficiency. Schema 348 is the primary platform schema.
"""

from __future__ import annotations

import logging
import time
from typing import Any

from runtime.blockchain.services.attestation.batch_processor import BatchProcessor
from runtime.blockchain.services.attestation.proof_generator import ProofGenerator
from runtime.blockchain.services.attestation.schemas import (
    PRIMARY_SCHEMA_UID,
    get_schema_uid,
)
from runtime.blockchain.services.attestation.time_critical import (
    TIME_CRITICAL_CATEGORIES,
    TimeCriticalHandler,
)

logger = logging.getLogger(__name__)


class AttestationService:
    """
    Universal EAS attestation service for the 0pnMatrx platform.

    All components route their attestations through this service. It handles:
    - Immediate submission for time-critical categories
    - Batched submission for regular attestations
    - Verification, revocation, and querying of existing attestations
    - Merkle proof generation and verification

    Config keys used (under config["blockchain"]):
        rpc_url, eas_contract, eas_schema, paymaster_private_key,
        platform_wallet, chain_id, network, schemas (dict of overrides).
    """

    def __init__(
        self,
        config: dict,
        batch_size: int = 50,
        flush_interval_seconds: float = 60.0,
    ):
        self.config = config
        bc = config.get("blockchain", {})

        self.eas_contract: str = bc.get("eas_contract", "")
        self.primary_schema: str = bc.get("eas_schema", PRIMARY_SCHEMA_UID)
        self.network: str = bc.get("network", "base-sepolia")

        self._time_critical = TimeCriticalHandler(config)
        self._batch_processor = BatchProcessor(
            config,
            batch_size=batch_size,
            flush_interval_seconds=flush_interval_seconds,
        )
        self._proof_generator = ProofGenerator(config)
        self._started = False

    async def start(self) -> None:
        """Start the batch processor background task."""
        if not self._started:
            await self._batch_processor.start()
            self._started = True
            logger.info("AttestationService started (network=%s).", self.network)

    async def stop(self) -> None:
        """Stop the batch processor and flush remaining attestations."""
        if self._started:
            await self._batch_processor.stop()
            self._started = False
            logger.info("AttestationService stopped.")

    async def attest(
        self,
        schema_uid: str,
        data: dict[str, Any],
        recipient: str,
        time_critical: bool = False,
    ) -> dict[str, Any]:
        """
        Create an attestation on-chain via EAS.

        Time-critical attestations are submitted immediately. All others
        are queued for batch submission to reduce gas costs.

        Args:
            schema_uid: The EAS schema UID to attest under.
                        Pass "primary" or empty string to use Schema 348.
            data: Attestation payload (action, agent, details, etc.).
            recipient: Ethereum address of the attestation recipient.
            time_critical: If True, submit immediately without batching.

        Returns:
            Dict with attestation result or queue confirmation.
        """
        # Resolve schema UID
        resolved_schema = self._resolve_schema(schema_uid)

        # Detect time-critical category from data
        category = data.get("category", "")
        is_critical = time_critical or TimeCriticalHandler.is_time_critical(category)

        if is_critical:
            if not category or category not in TIME_CRITICAL_CATEGORIES:
                category = self._infer_category(data)

            logger.info(
                "Routing time-critical attestation: category=%s schema=%s",
                category, resolved_schema,
            )
            return await self._time_critical.attest_now(
                schema_uid=resolved_schema,
                data=data,
                recipient=recipient,
                category=category,
            )

        # Regular attestation — queue for batching
        await self._batch_processor.add({
            "schema_uid": resolved_schema,
            "data": data,
            "recipient": recipient,
        })

        return {
            "status": "queued",
            "schema_uid": resolved_schema,
            "recipient": recipient,
            "pending_count": self._batch_processor.pending_count,
            "time_critical": False,
            "queued_at": int(time.time()),
        }

    async def batch_attest(self, attestations: list[dict[str, Any]]) -> list[dict[str, Any]]:
        """
        Submit multiple attestations, routing each appropriately.

        Time-critical attestations in the list are submitted immediately.
        Regular attestations are queued for batching.

        Args:
            attestations: List of dicts, each with schema_uid, data,
                          recipient, and optionally time_critical.

        Returns:
            List of result dicts, one per input attestation.
        """
        results: list[dict[str, Any]] = []

        for att in attestations:
            result = await self.attest(
                schema_uid=att.get("schema_uid", "primary"),
                data=att.get("data", {}),
                recipient=att.get("recipient", "0x0000000000000000000000000000000000000000"),
                time_critical=att.get("time_critical", False),
            )
            results.append(result)

        logger.info(
            "batch_attest processed %d attestations (%d time-critical, %d queued).",
            len(results),
            sum(1 for r in results if r.get("time_critical")),
            sum(1 for r in results if r.get("status") == "queued"),
        )
        return results

    async def verify(self, attestation_uid: str) -> dict[str, Any]:
        """
        Verify an existing attestation on-chain.

        Args:
            attestation_uid: The attestation UID (bytes32 hex string).

        Returns:
            Dict with verification status, UID, and network info.
        """
        if not attestation_uid:
            return {"verified": False, "error": "attestation_uid is required"}

        try:
            from runtime.blockchain.eas_client import EASClient

            client = EASClient(self.config)
            result = await client.verify(attestation_uid)
            result["explorer_url"] = (
                f"https://base-sepolia.easscan.org/attestation/view/{attestation_uid}"
            )
            return result

        except Exception as exc:
            logger.error("Verification failed for %s: %s", attestation_uid, exc)
            return {
                "uid": attestation_uid,
                "verified": False,
                "error": str(exc),
            }

    async def revoke(self, attestation_uid: str, schema_uid: str) -> dict[str, Any]:
        """
        Revoke an existing attestation on-chain.

        Args:
            attestation_uid: The attestation UID to revoke.
            schema_uid: The schema UID the attestation was made under.

        Returns:
            Dict with revocation status.
        """
        if not attestation_uid or not schema_uid:
            return {
                "status": "error",
                "error": "Both attestation_uid and schema_uid are required",
            }

        resolved_schema = self._resolve_schema(schema_uid)

        logger.info(
            "Revoking attestation: uid=%s schema=%s",
            attestation_uid, resolved_schema,
        )

        try:
            from web3 import Web3
            from eth_account import Account

            bc = self.config.get("blockchain", {})
            rpc_url = bc.get("rpc_url", "")
            paymaster_key = bc.get("paymaster_private_key", "")
            platform_wallet = bc.get("platform_wallet", "")
            chain_id = bc.get("chain_id", 84532)

            # EAS revoke ABI (simplified)
            revoke_abi = [
                {
                    "inputs": [
                        {
                            "components": [
                                {"name": "schema", "type": "bytes32"},
                                {
                                    "components": [
                                        {"name": "uid", "type": "bytes32"},
                                        {"name": "value", "type": "uint256"},
                                    ],
                                    "name": "data",
                                    "type": "tuple",
                                },
                            ],
                            "name": "request",
                            "type": "tuple",
                        }
                    ],
                    "name": "revoke",
                    "outputs": [],
                    "stateMutability": "payable",
                    "type": "function",
                }
            ]

            w3 = Web3(Web3.HTTPProvider(rpc_url))
            eas = w3.eth.contract(
                address=Web3.to_checksum_address(self.eas_contract),
                abi=revoke_abi,
            )

            schema_bytes = bytes.fromhex(resolved_schema.replace("0x", ""))
            uid_bytes = bytes.fromhex(attestation_uid.replace("0x", ""))

            tx = eas.functions.revoke(
                (schema_bytes, (uid_bytes, 0))
            ).build_transaction({
                "from": platform_wallet,
                "chainId": chain_id,
                "gas": 200_000,
                "gasPrice": w3.eth.gas_price,
                "nonce": w3.eth.get_transaction_count(platform_wallet),
            })

            account = Account.from_key(paymaster_key)
            signed = account.sign_transaction(tx)
            tx_hash = w3.eth.send_raw_transaction(signed.raw_transaction)
            receipt = w3.eth.wait_for_transaction_receipt(tx_hash, timeout=120)

            return {
                "status": "revoked" if receipt["status"] == 1 else "failed",
                "attestation_uid": attestation_uid,
                "schema_uid": resolved_schema,
                "revocation_tx": tx_hash.hex(),
                "block_number": receipt["blockNumber"],
                "gas_paid_by": "platform (0pnMatrx)",
            }

        except ImportError as exc:
            logger.warning("Revocation skipped — missing dependency: %s", exc)
            return {
                "status": "skipped",
                "reason": f"Missing dependency: {exc}",
                "attestation_uid": attestation_uid,
                "schema_uid": resolved_schema,
            }
        except Exception as exc:
            logger.error("Revocation failed: %s", exc)
            return {
                "status": "failed",
                "error": str(exc),
                "attestation_uid": attestation_uid,
                "schema_uid": resolved_schema,
            }

    async def query(self, filters: dict[str, Any]) -> list[dict[str, Any]]:
        """
        Query attestations by various filters.

        Supported filter keys:
            - schema_uid: Filter by schema UID
            - recipient: Filter by recipient address
            - attester: Filter by attester address
            - time_from / time_to: Unix timestamp range
            - revoked: Boolean, filter revoked/non-revoked
            - limit: Max results (default 50)

        Args:
            filters: Dict of filter criteria.

        Returns:
            List of matching attestation dicts.
        """
        schema_uid = filters.get("schema_uid", "")
        recipient = filters.get("recipient", "")
        attester = filters.get("attester", "")
        limit = filters.get("limit", 50)

        logger.info(
            "Querying attestations: schema=%s recipient=%s attester=%s limit=%d",
            schema_uid or "*", recipient or "*", attester or "*", limit,
        )

        try:
            # Build GraphQL query for EAS subgraph
            query_parts: list[str] = []
            if schema_uid:
                resolved = self._resolve_schema(schema_uid)
                query_parts.append(f'schemaId: "{resolved}"')
            if recipient:
                query_parts.append(f'recipient: "{recipient}"')
            if attester:
                query_parts.append(f'attester: "{attester}"')
            if filters.get("revoked") is not None:
                query_parts.append(f'revoked: {str(filters["revoked"]).lower()}')

            where_clause = ", ".join(query_parts) if query_parts else ""
            graphql_query = {
                "query": f"""{{
                    attestations(
                        first: {limit},
                        where: {{ {where_clause} }},
                        orderBy: time,
                        orderDirection: desc
                    ) {{
                        id
                        attester
                        recipient
                        refUID
                        revocable
                        revocationTime
                        expirationTime
                        time
                        txid
                        data
                    }}
                }}"""
            }

            # Return the query structure — in production this hits the EAS subgraph
            return [{
                "query": graphql_query,
                "filters_applied": filters,
                "network": self.network,
                "subgraph_url": f"https://base-sepolia.easscan.org/graphql",
                "note": "Query prepared for EAS subgraph. Connect subgraph endpoint to execute.",
            }]

        except Exception as exc:
            logger.error("Query failed: %s", exc)
            return [{"error": str(exc), "filters": filters}]

    async def generate_proof(self, attestation_uid: str) -> dict[str, Any]:
        """Generate a Merkle proof for an attestation."""
        return await self._proof_generator.generate_proof(attestation_uid)

    async def verify_proof(self, proof: dict[str, Any]) -> bool:
        """Verify a Merkle proof for an attestation."""
        return await self._proof_generator.verify_proof(proof)

    def _resolve_schema(self, schema_uid: str) -> str:
        """
        Resolve a schema UID, handling component names and defaults.

        Accepts a raw hex UID, a component name (e.g. "payments"), or
        "primary"/empty string to get Schema 348.
        """
        if not schema_uid or schema_uid == "primary":
            return self.primary_schema

        # If it looks like a hex UID, use it directly
        if schema_uid.startswith("0x") and len(schema_uid) >= 10:
            return schema_uid

        # Otherwise treat it as a component name
        return get_schema_uid(schema_uid, self.config)

    @staticmethod
    def _infer_category(data: dict[str, Any]) -> str:
        """
        Infer the time-critical category from attestation data fields.

        Falls back to the first matching category or "emergency_freeze".
        """
        action = data.get("action", "").lower()
        text = f"{action} {data.get('type', '')} {data.get('reason', '')}".lower()

        if "dispute" in text:
            return "dispute_filing"
        if "reversion" in text or "rights" in text:
            return "rights_reversion"
        if "ban" in text:
            return "ban_record"
        return "emergency_freeze"
