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
    - Batched submission for regular attestations (see `attest` — the batch
      submits at the size threshold only; there is no interval timer running)
    - Verification and revocation of existing attestations

    NOT provided (NEW-48b / NEW-50, both removed as fabrications):
    - Querying attestations. There is no EAS subgraph reader in this repo.
    - Merkle proof generation/verification. There is no on-chain root to
      anchor a proof against.

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
        # NEW-50: `self._proof_generator = ProofGenerator(config)` removed.
        # See the module-level note below on why the whole proof layer went.
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

        # NEW-51(b): disclose the REAL batch mechanics, not a bare "queued".
        #
        # The batch processor has two drain paths and only one of them runs:
        #
        #   * SIZE THRESHOLD — `BatchProcessor.add()` awaits `flush()` inline
        #     the moment `len(queue) >= batch_size`. This works today, with no
        #     setup. Verified by live probe (batch_size=5): four adds left
        #     pending=4 and zero flushes; the fifth flushed all five.
        #   * INTERVAL TIMER — `_auto_flush_loop` sleeps `flush_interval` and
        #     flushes whatever is pending. It is created ONLY by
        #     `BatchProcessor.start()`, and `start()` has NO CALLER anywhere
        #     in the repo. Checked five ways: repo-wide grep for `.start()`
        #     and `.flush()`; grep for on_startup/on_cleanup/cleanup_ctx
        #     across gateway/, runtime/, cli/; and a full read of the single
        #     registered startup hook (gateway/server.py `_start_cleanup_task`
        #     — memory and wallet stores, no attestation). Live probe:
        #     `_flush_task is None`, `_running is False` after adds.
        #
        # So an attestation below the threshold has NO TIME BOUND and is lost
        # if the process exits first. Returning a bare `"queued"` implied a
        # processing guarantee that only exists once `batch_size - pending`
        # more attestations arrive in this same process.
        #
        # The fields below state the actual mechanics rather than re-wording
        # the status, because this subsystem's disease was fields with the
        # right shape over wrong content — and a misleading status is not
        # cured by a differently-worded approximate one.
        pending = self._batch_processor.pending_count
        threshold = self._batch_processor.batch_size
        return {
            "status": "queued",
            "schema_uid": resolved_schema,
            "recipient": recipient,
            "pending_count": pending,
            "time_critical": False,
            "queued_at": int(time.time()),
            # -- the disclosure, accurate to the mechanics above --
            "submitted": False,
            "batch_threshold": threshold,
            "attestations_until_submit": max(0, threshold - pending),
            "interval_timer_running": self._batch_processor.is_running,
            "guaranteed_submission": False,
            "disclosure": (
                f"NOT SUBMITTED. This attestation is held in an in-memory "
                f"queue ({pending}/{threshold}). The batch submits only when "
                f"the queue reaches {threshold}; "
                f"{max(0, threshold - pending)} more attestation(s) are needed. "
                "The periodic flush timer is NOT running (BatchProcessor."
                "start() is never called), so there is no time bound and no "
                "guarantee of submission. Queued attestations are lost if the "
                "process exits before the threshold is reached. Use "
                "time_critical=True for immediate on-chain submission."
            ),
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
            from runtime.blockchain.sponsorship import unmetered_platform_signer

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

            account = unmetered_platform_signer(paymaster_key, "eas.revoke")
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

    # ── REMOVED: query (NEW-48b) ──────────────────────────────────────
    #
    # It built a GraphQL query STRING for the EAS subgraph and then returned
    # that string, wrapped in a dict, AS the result list:
    #
    #     return [{"query": graphql_query, "filters_applied": filters,
    #              "network": ..., "subgraph_url": ...,
    #              "note": "Query prepared for EAS subgraph. Connect subgraph
    #                       endpoint to execute."}]
    #
    # The signature declared `list[dict]` of "matching attestation dicts", so
    # any caller testing truthiness or `len(results)` concluded an attestation
    # had been found. There was no HTTP client in the module and no code path
    # in ANY configuration that executed the query.
    #
    # It was LIVE, not inert: ACTION_MAP["query_attestations"] routed to it
    # (service_dispatcher.py) and intent_actions.py taught Trinity to call it.
    #
    # The honest-external-client exemption does NOT apply. That exemption is
    # for a real client whose credential is unconfigured; the EAS subgraph
    # (base-sepolia.easscan.org/graphql) is a PUBLIC endpoint needing no
    # credential. Nothing was gated — the request was simply never made.
    #
    # twin-path: NONE. Searched runtime/, gateway/ and scripts/ for
    # easscan|graphql|subgraph. The only real GraphQL client is
    # creator_platforms (Sound.xyz — a different API, a different-operation
    # neighbour, not a twin); gateway/service_routes.py registers indexer
    # subgraph routes as not-implemented stubs; eas_manager.py only formats an
    # easscan VIEW url. No EAS subgraph reader exists anywhere in the repo.
    #
    # Removed rather than gated, because a credential-gated stub would imply a
    # real implementation waits behind a key. None does.

    # ── REMOVED: generate_proof / verify_proof and the whole ProofGenerator
    #    module (NEW-50, carrying NEW-49 by subsumption) ──────────────────
    #
    # The off-chain Merkle proof layer is gone. Three defects, and the third
    # is why this is a removal rather than a repair:
    #
    # 1. `_fetch_attestation` (NEW-49) claimed in its docstring to read the
    #    EAS contract's getAttestation(). Its `try` block contained ONLY a
    #    dict literal of empty strings — schema "", recipient "", attester "",
    #    data "" — so the `except` was unreachable (a dict literal cannot
    #    throw). Every proof was a Merkle tree over placeholder fields.
    #
    # 2. `verify_proof` (NEW-50) did real Merkle math — it genuinely rebuilt
    #    the tree — but from `proof["leaves"]` and `proof["merkle_root"]`,
    #    BOTH supplied by the caller. No chain call, no `await`, no trusted
    #    anchor. `{"verifiable": True, "leaves": [...anything...],
    #    "merkle_root": <root of that anything>}` returned True. It proved
    #    only that the caller can run a hash function.
    #
    #    Note the classification, because it cost us a category: this was NOT
    #    a fabrication. It did genuine computation. It was real-local and
    #    DEFECTIVE — self-referential and vacuous. "Returns success-shaped
    #    output for work not done" (fabrication) and "does real work that
    #    proves nothing" (defective) are different diseases needing different
    #    cures, and the five-category scheme had no bucket for the second.
    #
    # 3. THERE IS NO ANCHOR. A Merkle proof verifies a leaf against a root you
    #    already trust. Repo-wide, every `merkle` mention outside this module
    #    was a docstring or vendored OpenZeppelin library code: no contract
    #    stores a root, no schema declares one, nothing publishes one (all 14
    #    production contracts checked). Verifying against a caller-supplied
    #    root is not a fixable defect — it is the wrong primitive. EAS attests
    #    a payload directly; a Merkle layer over it has nothing to anchor to.
    #
    # So the honest state is that proof verification is NOT AVAILABLE, rather
    # than a check that always passes. Both methods were unreachable
    # (fabrication-inert, proven three ways: router-table read, programmatic
    # ACTION_MAP enumeration, repo-wide grep), so nothing loses a capability.
    #
    # NEW-49 is resolved BY SUBSUMPTION, deliberately: `_fetch_attestation`
    # died with the module, and its only caller (`generate_proof`) died too.
    # Adding `EASClient.get_attestation()` to delegate to would have created a
    # method with ZERO consumers — the dead-twin pattern this audit exists to
    # remove. If a real proof capability is ever wanted, the on-chain anchor
    # gets designed first; it is not stubbed in advance.

    def _resolve_schema(self, schema_uid: str) -> str:
        """
        Resolve a schema UID, handling component names and defaults.

        Accepts a raw bytes32 UID, a component name (e.g. "payments"), or
        "primary"/empty string (the configured primary schema).

        FAILS CLOSED (P2-9): the resolved UID must be a 66-char 0x+64-hex
        bytes32; an empty/malformed value (e.g. no schema registered/configured
        for the target chain) raises ValueError rather than attesting against a
        nonexistent placeholder schema.
        """
        from runtime.blockchain.services.attestation.schemas import _UID_RE
        if not schema_uid or schema_uid == "primary":
            uid = self.primary_schema
        elif schema_uid.startswith("0x"):
            uid = schema_uid
        else:
            # Component name — get_schema_uid already validates/raises.
            uid = get_schema_uid(schema_uid, self.config)
        if not _UID_RE.match(str(uid or "")):
            raise ValueError(
                "EAS schema is not configured — set blockchain.eas_schema (or "
                "blockchain.schemas.<component>) to the registered bytes32 UID "
                "for your target chain (see scripts/register_eas_schemas.py)."
            )
        return uid

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
