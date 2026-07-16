"""Real-Estate Escrow Engine — Component 46.

Compresses the escrow document pipeline from weeks to seconds: every closing
document is pre-uploaded, content-hashed, attested on-chain, and freshness-
tracked per property. When ALL documents are fresh + verified and the buyer's
proof-of-funds is current, the property is transaction-ready and a one-tap
purchase settles atomically (funds lock + deed transfer in one transaction)
against the PropertyEscrow contract.

Honesty invariants (absolute):
  • Readiness is never faked — evaluate on read via the pure readiness engine;
    a purchase re-evaluates server-side at execution time (never trusts a
    cached green) and refuses with the full named blocker list.
  • Non-custodial — the platform NEVER moves buyer funds. The buyer signs the
    lock/settle transaction from their own account; the server's role is to
    gate readiness, prepare the atomic calldata, sponsor gas via the existing
    paymaster path, verify the on-chain receipt, and attest the trail.
  • Every external dependency fails closed + named: unregistered EAS schema →
    document recorded as unattested (a readiness blocker, never invisible);
    uncredentialed storage → honest not_stored (hash still real); undeployed
    contracts → not_deployed_response naming the exact config keys; disabled
    feature flag → honest refusal.
  • County recording + notarization are real-world steps this system does not
    control — modelled as the explicit offchain_recording_pending state with
    an operator endpoint to mark completion, never pretended away.

Feature-gated: services.real_estate.enabled (default false) — the mvpMode-
style server-side flag; routes 403 and methods refuse honestly while off.
"""
from __future__ import annotations

import hashlib
import json
import logging
import time
from typing import Any

from runtime.blockchain.web3_manager import (
    Web3Manager,
    is_placeholder_value,
    not_deployed_response,
)
from runtime.db.database import Database

from .readiness import (
    DEFAULT_FRESHNESS_DAYS,
    DEFAULT_PROOF_OF_FUNDS_DAYS,
    DEFAULT_REQUIRED_DOCUMENTS,
    evaluate_readiness,
    expires_at_for,
)
from .store import RealEstateStore

logger = logging.getLogger(__name__)

DEFAULT_CONFIG: dict[str, Any] = {
    "enabled": False,                      # regulated feature — off by default
    "db_path": "data/real_estate.db",
    "freshness_days": dict(DEFAULT_FRESHNESS_DAYS),
    "required_documents": list(DEFAULT_REQUIRED_DOCUMENTS),
    "proof_of_funds_days": DEFAULT_PROOF_OF_FUNDS_DAYS,
    # Post-deploy wiring (testnet deploy is a separate, explicitly-triggered
    # human step; mainnet is lawyer-gated). Placeholders → honest not_deployed.
    "escrow_contract": "",
    "deed_contract": "",
}

# Escrow state machine — the ONLY legal transitions. Everything else raises.
VALID_TRANSITIONS: dict[str, frozenset[str]] = {
    "initiated": frozenset({"funds_locked", "refunded"}),
    "funds_locked": frozenset({"settled", "refunded"}),
    "settled": frozenset({"offchain_recording_pending"}),
    "offchain_recording_pending": frozenset({"complete"}),
    "complete": frozenset(),
    "refunded": frozenset(),
}

_PROPERTY_STATUSES = ("draft", "listed", "under_escrow", "sold", "delisted")

# Keep in lockstep with contracts/src/PropertyEscrow.sol — the settlement
# calldata the client's account executes. bytes32 escrowId, address seller,
# address deed contract, uint256 deed token id, bytes32 readiness attestation.
_LOCK_AND_SETTLE_SIG = "lockAndSettle(bytes32,address,address,uint256,bytes32)"


class RealEstateService:
    """Property escrow platform service (registered like the other 45)."""

    service_name = "real_estate"

    def __init__(self, config: dict[str, Any] | None = None, *,
                 db: Database | None = None,
                 attestation_service: Any | None = None,
                 storage_service: Any | None = None,
                 web3_manager: Any | None = None) -> None:
        self._config = config or {}
        svc_cfg = (self._config.get("services", {}) or {}).get("real_estate", {}) or {}
        self.config = {**DEFAULT_CONFIG, **svc_cfg}
        self._store = RealEstateStore(
            db or Database({"database": {"path": self.config["db_path"]}}))
        # Injectable for tests; lazily constructed from platform config otherwise.
        self._attestation = attestation_service
        self._storage = storage_service
        self._web3 = web3_manager
        # Escrow ids with a settlement confirmation in flight — the check+add is
        # atomic under asyncio (no await between), so two concurrent confirms
        # for one escrow can't both walk the state machine.
        self._settling: set[str] = set()
        logger.info("RealEstateService initialised (enabled=%s)",
                    self.config["enabled"])

    # ── Gating ──────────────────────────────────────────────────────────

    def _require_enabled(self) -> None:
        """Honest refusal while the feature flag is off (server-side default:
        disabled). The HTTP layer also 403s before reaching here — this guard
        covers every non-HTTP path (dispatcher, batch, direct callers)."""
        if not self.config.get("enabled", False):
            raise ValueError(
                "real_estate is disabled (services.real_estate.enabled=false)."
                " This regulated feature ships dark until explicitly enabled.")

    def _attestation_svc(self):
        if self._attestation is None:
            from runtime.blockchain.services.attestation.service import (
                AttestationService,
            )
            self._attestation = AttestationService(self._config)
        return self._attestation

    def _storage_svc(self):
        if self._storage is None:
            from runtime.blockchain.services.storage.service import (
                DecentralizedStorageService,
            )
            self._storage = DecentralizedStorageService(self._config)
        return self._storage

    def _web3_mgr(self):
        if self._web3 is None:
            self._web3 = Web3Manager.get_shared(self._config)
        return self._web3

    def _web3_live(self):
        """Return a genuinely-connected web3, or None. Reads REAL connectivity —
        Web3Manager exposes `available` (+ `w3.is_connected()`), NOT an
        `is_connected` attribute on the manager — so this can't false-negative
        a live RPC (nor false-positive a dead one). Fail-closed: unknown → None."""
        mgr = self._web3_mgr()
        w3 = getattr(mgr, "w3", None)
        if w3 is None:
            return None
        connected = bool(getattr(mgr, "available", False))
        if not connected:
            probe = getattr(w3, "is_connected", None)
            try:
                connected = bool(probe()) if callable(probe) else False
            except Exception:
                connected = False
        return w3 if connected else None

    # ── Properties (RE-1) ───────────────────────────────────────────────

    async def create_property(self, seller: str, address: dict,
                              price_wei: str) -> dict:
        self._require_enabled()
        if not seller:
            raise ValueError("seller is required")
        if not isinstance(address, dict) or not address.get("line1"):
            raise ValueError("address must be an object with at least line1")
        if int(price_wei) <= 0:
            raise ValueError("price_wei must be a positive integer string")
        return await self._store.create_property(
            address=address, price_wei=price_wei, seller_wallet=seller)

    async def get_property(self, property_id: str) -> dict:
        self._require_enabled()
        prop = await self._store.get_property(property_id)
        if prop is None:
            raise ValueError(f"property not found: {property_id}")
        return prop

    async def list_properties(self, status: str | None = None) -> list[dict]:
        self._require_enabled()
        if status and status not in _PROPERTY_STATUSES:
            raise ValueError(f"unknown status '{status}'")
        return await self._store.list_properties(status)

    async def update_listing_status(self, property_id: str, status: str) -> dict:
        self._require_enabled()
        if status not in _PROPERTY_STATUSES:
            raise ValueError(f"unknown status '{status}'")
        await self.get_property(property_id)  # 404-equivalent if absent
        updated = await self._store.update_property(property_id, status=status)
        return updated

    # ── Document pipeline (RE-2) ────────────────────────────────────────

    async def upload_document(self, property_id: str, doc_type: str,
                              content_b64: str | None = None,
                              content_hash: str | None = None,
                              filename: str = "") -> dict:
        """file → (real) storage where credentialed → sha256 content hash →
        EAS attestation (document_verification schema, fail-closed).

        Every leg records its HONEST outcome: storage_status ∈ stored/
        not_stored/hash_only; attestation_status ∈ attested/queued/skipped/
        unattested. Only 'attested' satisfies readiness. A re-upload
        supersedes the prior version; history is retained.
        """
        self._require_enabled()
        prop = await self.get_property(property_id)
        windows = self.config["freshness_days"]
        if doc_type not in windows:
            raise ValueError(
                f"unknown document type '{doc_type}' — expected one of: "
                f"{sorted(windows)}")
        if not content_b64 and not content_hash:
            raise ValueError("either content_b64 or content_hash is required")

        # 1. Content hash — always real, always computed server-side when the
        #    content is present (a caller-supplied hash is accepted only when
        #    the blob itself isn't uploaded; marked hash_only, never 'stored').
        if content_b64:
            import base64
            try:
                blob = base64.b64decode(content_b64, validate=True)
            except Exception as exc:
                raise ValueError(f"content_b64 is not valid base64: {exc}")
            digest = hashlib.sha256(blob).hexdigest()
        else:
            if not isinstance(content_hash, str) or len(content_hash) != 64:
                raise ValueError("content_hash must be a 64-char sha256 hex digest")
            digest = content_hash.lower()

        # 2. Storage — real Filecoin/Lighthouse upload when credentialed,
        #    honest not_stored otherwise. NEVER a fabricated CID.
        storage_ref = None
        storage_status = "hash_only"
        if content_b64:
            try:
                stored = await self._storage_svc().store_filecoin(
                    content=content_b64, filename=filename or f"{doc_type}.bin")
                if stored.get("status") == "stored" and stored.get("cid"):
                    storage_ref = stored["cid"]
                    storage_status = "stored"
                else:
                    storage_status = "not_stored"
            except Exception:
                logger.warning("document storage failed honestly", exc_info=True)
                storage_status = "not_stored"

        # 3. Attestation — document_verification schema; fail-closed until the
        #    schema UID is registered (a human step). Outcome recorded honestly.
        uploaded_at = time.time()
        attestation_ref, attestation_status = await self._attest(
            schema="document_verification",
            data={
                "subject": prop["seller_wallet"],
                "documentHash": digest,
                "docType": doc_type,
                "propertyId": property_id,
                "category": "real_estate_document",
            },
            recipient=prop["seller_wallet"],
        )

        expires_at = expires_at_for(doc_type, uploaded_at, windows)
        doc = await self._store.add_document(
            property_id=property_id, doc_type=doc_type, content_hash=digest,
            storage_ref=storage_ref, storage_status=storage_status,
            attestation_ref=attestation_ref,
            attestation_status=attestation_status,
            uploaded_at=uploaded_at, expires_at=expires_at,
        )
        return doc

    async def get_documents(self, property_id: str,
                            include_history: bool = False) -> dict:
        self._require_enabled()
        await self.get_property(property_id)
        current = await self._store.current_documents(property_id)
        out: dict = {"current": current}
        if include_history:
            out["history"] = await self._store.document_history(property_id)
        return out

    async def query_expiring_documents(self, days: int = 14) -> list[dict]:
        """Current documents expiring within N days (already-expired excluded —
        those are readiness blockers, not reminders). Notification feed."""
        self._require_enabled()
        if days <= 0:
            raise ValueError("days must be a positive integer")
        return await self._store.documents_expiring_within(
            now=time.time(), days=days)

    async def _attest(self, *, schema: str, data: dict,
                      recipient: str) -> tuple[str | None, str]:
        """Attempt an EAS attestation; map the outcome honestly. Only a result
        carrying a real transaction reference counts as 'attested'."""
        try:
            result = await self._attestation_svc().attest(
                schema_uid=schema, data=data, recipient=recipient)
        except ValueError:
            # fail-closed schema resolution (UID unregistered) — honest.
            return None, "unattested"
        except Exception:
            logger.warning("attestation attempt failed honestly", exc_info=True)
            return None, "unattested"
        status = str(result.get("status", ""))
        tx = result.get("attestation_tx")
        if tx and status not in ("skipped", "error", "failed"):
            return str(tx), "attested"
        if status == "queued":
            return None, "queued"
        if status == "skipped":
            return None, "skipped"
        return None, "unattested"

    # ── Buyer verification (RE-6) ───────────────────────────────────────

    async def verify_buyer(self, buyer: str, method: str = "wallet_balance",
                           threshold_wei: str | None = None) -> dict:
        """Proof-of-funds. v1:
        (a) wallet_balance — REAL: reads the buyer's on-chain balance via the
            shared Web3Manager and compares against the threshold; and
        (b) external — honest 501 stub for future bank integration (raises
            NotImplementedError; the HTTP layer surfaces 501, the dispatcher
            surfaces its degraded-honest error). 30-day expiry."""
        self._require_enabled()
        if not buyer:
            raise ValueError("buyer is required")
        if method == "external":
            raise NotImplementedError(
                "external proof-of-funds verification (bank integration) is"
                " not yet available — no fabricated verification is issued.")
        if method != "wallet_balance":
            raise ValueError(f"unknown verification method '{method}'")
        if not threshold_wei or int(threshold_wei) <= 0:
            raise ValueError("threshold_wei (positive integer string) is required")

        w3 = self._web3_live()
        if w3 is None:
            return not_deployed_response(self.service_name, extra={
                "missing": ["blockchain.rpc_url (web3 connection)"],
                "message": "wallet-balance verification needs a live RPC —"
                           " no verification is fabricated without one.",
            })
        balance = int(w3.eth.get_balance(w3.to_checksum_address(buyer)))
        verified = balance >= int(threshold_wei)
        status = "verified" if verified else "insufficient_funds"
        now = time.time()
        expires_at = now + self.config["proof_of_funds_days"] * 86400.0

        attestation_ref, attestation_status = (None, "not_attempted")
        if verified:
            attestation_ref, attestation_status = await self._attest(
                schema="document_verification",
                data={
                    "subject": buyer,
                    "documentHash": hashlib.sha256(
                        f"{buyer}:{threshold_wei}:{now}".encode()).hexdigest(),
                    "docType": "proof_of_funds",
                    "propertyId": "",
                    "category": "real_estate_document",
                },
                recipient=buyer,
            )

        record = await self._store.add_verification(
            buyer_wallet=buyer, method=method, status=status,
            threshold_wei=threshold_wei,
            # The PROVEN amount is the real on-chain balance — readiness compares
            # THIS against the property price, so a low self-chosen threshold
            # can't buy a green readiness on an unfundable purchase.
            details={"balance_wei": str(balance), "verified_amount_wei": str(balance)},
            attestation_ref=attestation_ref,
            attestation_status=attestation_status,
            verified_at=now, expires_at=expires_at,
        )
        return record

    async def get_buyer_verification(self, buyer: str) -> dict:
        self._require_enabled()
        record = await self._store.current_verification(buyer)
        if record is None:
            return {"status": "none", "buyer": buyer,
                    "message": "no proof-of-funds verification on file"}
        return record

    # ── Readiness (RE-4 wiring — evaluation itself is the pure module) ──

    async def get_readiness(self, property_id: str, buyer: str = "") -> dict:
        """Transaction-readiness verdict, computed NOW on current records.
        The buyer's proof-of-funds is checked against THIS property's price, so
        readiness is honest about affordability, not just verification freshness."""
        self._require_enabled()
        prop = await self.get_property(property_id)
        docs = await self._store.current_documents(property_id)
        verification = (await self._store.current_verification(buyer)
                        if buyer else None)
        result = evaluate_readiness(
            docs, verification, now=time.time(),
            required_documents=tuple(self.config["required_documents"]),
            required_amount=int(prop["price_wei"]),
        )
        return result.to_dict()

    # ── One-tap purchase (RE-5) ─────────────────────────────────────────

    async def execute_purchase(self, buyer: str, property_id: str) -> dict:
        """The one-tap endpoint. Re-verifies readiness server-side AT
        EXECUTION TIME (a cached green is never trusted), then prepares the
        atomic lockAndSettle calldata the buyer's own account executes —
        funds lock + deed transfer + settlement all-or-nothing in ONE
        transaction, gas-sponsorable via the existing /api/v1/paymaster/sign
        path. The platform never touches buyer funds.

        Refuses honestly when: not ready (full named blocker list), property
        not listed, or contracts not deployed (exact config keys named)."""
        self._require_enabled()
        if not buyer:
            raise ValueError("buyer is required")
        prop = await self.get_property(property_id)
        if prop["status"] != "listed":
            raise ValueError(
                f"property is not listed for sale (status: {prop['status']})")

        # 1. Fresh readiness — never a cached verdict.
        readiness = await self.get_readiness(property_id, buyer=buyer)
        if not readiness["ready"]:
            return {
                "status": "not_ready",
                "message": "purchase refused — the property is not"
                           " transaction-ready; every blocker is named below.",
                "readiness": readiness,
            }

        # 2. Contract wiring — placeholders → honest not_deployed, no state.
        escrow_addr = self.config.get("escrow_contract", "")
        deed_addr = self.config.get("deed_contract", "")
        missing = [k for k, v in (("services.real_estate.escrow_contract", escrow_addr),
                                  ("services.real_estate.deed_contract", deed_addr))
                   if is_placeholder_value(v)]
        if missing:
            return not_deployed_response(self.service_name, extra={
                "missing": missing,
                "message": "PropertyEscrow/PropertyDeed are written + tested"
                           " but not yet deployed (testnet deploy is an"
                           " explicit, separately-triggered step).",
            })
        if prop.get("deed_token_id") in (None, ""):
            return not_deployed_response(self.service_name, extra={
                "missing": ["property.deed_token_id"],
                "message": "no deed token has been minted for this property"
                           " yet — mint via the operator deed flow first.",
            })

        # 3. Create the escrow record + prepare the atomic settlement.
        escrow = await self._store.create_escrow(
            property_id=property_id, buyer_wallet=buyer,
            amount_wei=prop["price_wei"], state="initiated",
            readiness_snapshot=readiness,
        )
        # Bind the exact readiness snapshot into the on-chain condition: the
        # bytes32 the contract requires (non-zero) is the readiness digest, so
        # the settlement is cryptographically tied to THIS verdict and the
        # contract's "no readiness attestation" guard passes only for a real
        # one. The EAS attestation of the same snapshot is recorded off-chain.
        readiness_digest = hashlib.sha256(
            json.dumps(readiness, sort_keys=True).encode()).digest()
        snapshot_ref, snapshot_status = await self._attest(
            schema="document_verification",
            data={
                "subject": buyer,
                "documentHash": readiness_digest.hex(),
                "docType": "readiness_snapshot",
                "propertyId": property_id,
                "category": "real_estate_document",
            },
            recipient=buyer,
        )
        calldata = self._encode_lock_and_settle(
            escrow_id=escrow["id"], seller=prop["seller_wallet"],
            deed_contract=deed_addr, deed_token_id=int(prop["deed_token_id"]),
            readiness_attestation=readiness_digest,  # non-zero: the contract
            # accepts it; it commits the settlement to this exact snapshot.
        )
        # Record the snapshot attestation outcome on the escrow (honest even
        # when unattested — the ref field carries the status string).
        await self._store.transition_escrow(
            escrow["id"], new_state="initiated",
            attestation_refs={"readiness_snapshot": snapshot_ref or snapshot_status})

        await self._store.update_property(property_id, status="under_escrow")
        return {
            "status": "prepared",
            "escrow": await self._store.get_escrow(escrow["id"]),
            "settlement": {
                "to": escrow_addr,
                "value_wei": prop["price_wei"],
                "data": calldata,
                "description": "atomic lockAndSettle — funds lock + deed"
                               " transfer + settlement, all-or-nothing in one"
                               " transaction signed by the BUYER's account",
                "gas_sponsorship": "/api/v1/paymaster/sign",
            },
            "next": "submit the settlement from the buyer's account, then"
                    " POST /api/v1/realestate/escrow/{id}/confirm with the"
                    " transaction hash",
        }

    def _encode_lock_and_settle(self, *, escrow_id: str, seller: str,
                                deed_contract: str, deed_token_id: int,
                                readiness_attestation: bytes) -> str:
        """ABI-encode the PropertyEscrow.lockAndSettle call (kept in lockstep
        with contracts/src/PropertyEscrow.sol)."""
        from eth_abi import encode as abi_encode
        from web3 import Web3

        selector = Web3.keccak(text=_LOCK_AND_SETTLE_SIG)[:4]
        escrow_id_b32 = hashlib.sha256(escrow_id.encode()).digest()
        args = abi_encode(
            ["bytes32", "address", "address", "uint256", "bytes32"],
            [escrow_id_b32, Web3.to_checksum_address(seller),
             Web3.to_checksum_address(deed_contract), deed_token_id,
             readiness_attestation],
        )
        return "0x" + (selector + args).hex()

    async def confirm_settlement(self, escrow_id: str, tx_hash: str) -> dict:
        """Verify the buyer-submitted settlement ON-CHAIN and only then advance
        the state machine. "Verify" means the receipt genuinely settled THIS
        escrow: status success AND emitted from OUR PropertyEscrow contract AND
        carrying a Settled(escrowId=…) log whose id matches this escrow. An
        arbitrary successful tx (e.g. a 1-wei self-transfer) is NOT accepted —
        that would fabricate a sale. A failed / unmined / unrelated receipt
        changes nothing and says so."""
        self._require_enabled()
        # Atomic concurrency claim (no await between check and add) — two
        # simultaneous confirms for one escrow can't both walk the machine.
        if escrow_id in self._settling:
            return {"status": "in_progress", "message":
                    "a settlement confirmation for this escrow is already"
                    " underway — state unchanged"}
        self._settling.add(escrow_id)
        try:
            escrow = await self._store.get_escrow(escrow_id)
            if escrow is None:
                raise ValueError(f"escrow not found: {escrow_id}")
            if escrow["state"] != "initiated":
                raise ValueError(
                    f"escrow is in state '{escrow['state']}' — settlement can"
                    " only be confirmed from 'initiated'")

            w3 = self._web3_live()
            if w3 is None:
                return not_deployed_response(self.service_name, extra={
                    "missing": ["blockchain.rpc_url (web3 connection)"],
                    "message": "cannot verify the settlement receipt without a"
                               " live RPC — the escrow state is unchanged.",
                })
            escrow_addr = self.config.get("escrow_contract", "")

            try:
                receipt = w3.eth.get_transaction_receipt(tx_hash)
            except Exception as exc:  # web3 raises TransactionNotFound for unknown/unmined
                if "not found" in str(exc).lower() or type(exc).__name__ == "TransactionNotFound":
                    return {"status": "pending", "message":
                            "transaction not yet mined — state unchanged"}
                raise
            if receipt is None:
                return {"status": "pending", "message":
                        "transaction not yet mined — state unchanged"}
            if int(receipt.get("status", 0)) != 1:
                return {"status": "failed", "message":
                        "settlement transaction REVERTED on-chain — escrow"
                        " state unchanged; funds did not move.",
                        "tx_hash": tx_hash}

            # THE ANTI-FAKE CHECK: the receipt must prove THIS escrow settled on
            # OUR contract — a successful-but-unrelated tx is rejected.
            if not self._receipt_settles_escrow(receipt, escrow, escrow_addr, w3):
                return {"status": "not_settlement", "message":
                        "the transaction succeeded but is NOT a settlement of"
                        " this escrow on the PropertyEscrow contract (no"
                        " matching Settled event) — escrow state unchanged.",
                        "tx_hash": tx_hash}

            # Genuinely settled: the atomic contract op means lock + settle both
            # happened in this one tx — walk the machine truthfully.
            await self._store.transition_escrow(
                escrow_id, new_state="funds_locked", tx_hashes={"lock": tx_hash})
            settlement_ref, settlement_status = await self._attest(
                schema="document_verification",
                data={
                    "subject": escrow["buyer_wallet"],
                    "documentHash": hashlib.sha256(tx_hash.encode()).hexdigest(),
                    "docType": "settlement",
                    "propertyId": escrow["property_id"],
                    "category": "real_estate_document",
                },
                recipient=escrow["buyer_wallet"],
            )
            await self._store.transition_escrow(
                escrow_id, new_state="settled",
                tx_hashes={"settle": tx_hash},
                attestation_refs={"settlement": settlement_ref or settlement_status})
            final = await self._store.transition_escrow(
                escrow_id, new_state="offchain_recording_pending")
            await self._store.update_property(escrow["property_id"], status="sold")
            return {
                "status": "settled",
                "escrow": final,
                "honest_note": "on-chain settlement complete (funds settled,"
                               " deed token transferred, trail attested). County"
                               " recording + notarization are REAL-WORLD steps"
                               " still pending — tracked, never pretended away.",
            }
        finally:
            self._settling.discard(escrow_id)

    def _receipt_settles_escrow(self, receipt, escrow: dict, escrow_addr: str,
                                w3) -> bool:
        """True IFF the receipt carries a Settled event from OUR PropertyEscrow
        contract whose indexed escrowId matches this escrow. This is what makes
        confirm_settlement impossible to fool with an unrelated successful tx.

        Settled(bytes32 indexed escrowId, address indexed buyer,
                address indexed seller, uint256 amount, uint256 deedTokenId,
                bytes32 readinessAttestation)
        → topic0 = keccak(signature); topic1 = escrowId (the bytes32 itself).
        The escrowId is sha256(escrow['id']) — the exact value the settlement
        calldata was built with in execute_purchase.
        """
        if is_placeholder_value(escrow_addr):
            return False
        try:
            from web3 import Web3
            want_addr = Web3.to_checksum_address(escrow_addr)
            settled_topic0 = Web3.keccak(
                text="Settled(bytes32,address,address,uint256,uint256,bytes32)")
            want_escrow_id = hashlib.sha256(escrow["id"].encode()).digest()
            want_buyer_topic = bytes(12) + Web3.to_bytes(
                hexstr=Web3.to_checksum_address(escrow["buyer_wallet"]))
            for log in receipt.get("logs", []):
                log_addr = log.get("address")
                if log_addr is None or Web3.to_checksum_address(log_addr) != want_addr:
                    continue
                topics = [bytes(t) for t in log.get("topics", [])]
                if len(topics) < 3:
                    continue
                if topics[0] != bytes(settled_topic0):
                    continue
                if topics[1] != want_escrow_id:
                    continue
                # buyer is indexed (topic2) — must be the escrow's buyer
                if topics[2] != want_buyer_topic:
                    continue
                return True
            return False
        except Exception:
            # Any decoding failure is fail-closed: we do NOT settle on doubt.
            logger.warning("settlement receipt verification failed closed",
                           exc_info=True)
            return False

    # ── Off-chain bridge + refund (RE-5) ────────────────────────────────

    async def mark_recording_complete(self, escrow_id: str,
                                      recording_reference: str = "") -> dict:
        """Operator endpoint: the county recording genuinely completed."""
        self._require_enabled()
        escrow = await self._store.get_escrow(escrow_id)
        if escrow is None:
            raise ValueError(f"escrow not found: {escrow_id}")
        self._assert_transition(escrow["state"], "complete")
        updated = await self._store.transition_escrow(
            escrow_id, new_state="complete",
            attestation_refs={"recording_reference": recording_reference or "unreferenced"})
        return updated

    async def refund_escrow(self, escrow_id: str, reason: str = "") -> dict:
        """Record-side refund transition. The FUNDS refund is enforced by the
        PropertyEscrow contract's refund path (buyer-only, post-deadline) —
        the platform cannot move buyer funds; this endpoint only tracks it."""
        self._require_enabled()
        escrow = await self._store.get_escrow(escrow_id)
        if escrow is None:
            raise ValueError(f"escrow not found: {escrow_id}")
        self._assert_transition(escrow["state"], "refunded")
        updated = await self._store.transition_escrow(
            escrow_id, new_state="refunded",
            attestation_refs={"refund_reason": reason or "unspecified"})
        await self._store.update_property(escrow["property_id"], status="listed")
        return updated

    async def get_escrow(self, escrow_id: str) -> dict:
        self._require_enabled()
        escrow = await self._store.get_escrow(escrow_id)
        if escrow is None:
            raise ValueError(f"escrow not found: {escrow_id}")
        return escrow

    def _assert_transition(self, current: str, target: str) -> None:
        allowed = VALID_TRANSITIONS.get(current, frozenset())
        if target not in allowed:
            raise ValueError(
                f"illegal escrow transition {current} → {target};"
                f" allowed from '{current}': {sorted(allowed) or 'none'}")
