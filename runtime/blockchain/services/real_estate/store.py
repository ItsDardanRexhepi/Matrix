"""Durable SQLite store for the real-estate service.

Follows the platform's canonical durable pattern (runtime/social/follows.py
FollowStore): a store class over runtime.db.database.Database with lazy
CREATE TABLE IF NOT EXISTS and parameterised SQL. The service owns its own
Database instance (path from services.real_estate.db_path) so real-estate
state survives restarts — escrow records and document history must never
evaporate with the process.

Supersession model: a re-uploaded document INSERTS a new row and stamps the
prior current row's superseded_by — full history retained, the "current"
document per type is the single row with superseded_by IS NULL.
"""
from __future__ import annotations

import json
import time
import uuid

from runtime.db.database import Database

_CREATE_PROPERTIES = """
CREATE TABLE IF NOT EXISTS re_properties (
    id            TEXT PRIMARY KEY,
    address_json  TEXT NOT NULL,
    price_wei     TEXT NOT NULL,
    seller_wallet TEXT NOT NULL,
    status        TEXT NOT NULL,
    deed_token_id TEXT,
    created_at    REAL NOT NULL,
    updated_at    REAL NOT NULL
)
"""

_CREATE_DOCUMENTS = """
CREATE TABLE IF NOT EXISTS re_documents (
    id                 TEXT PRIMARY KEY,
    property_id        TEXT NOT NULL,
    doc_type           TEXT NOT NULL,
    content_hash       TEXT NOT NULL,
    storage_ref        TEXT,
    storage_status     TEXT NOT NULL,
    attestation_ref    TEXT,
    attestation_status TEXT NOT NULL,
    uploaded_at        REAL NOT NULL,
    expires_at         REAL NOT NULL,
    superseded_by      TEXT
)
"""

_CREATE_ESCROWS = """
CREATE TABLE IF NOT EXISTS re_escrows (
    id                      TEXT PRIMARY KEY,
    property_id             TEXT NOT NULL,
    buyer_wallet            TEXT NOT NULL,
    amount_wei              TEXT NOT NULL,
    state                   TEXT NOT NULL,
    readiness_snapshot_json TEXT,
    attestation_refs_json   TEXT NOT NULL,
    tx_hashes_json          TEXT NOT NULL,
    history_json            TEXT NOT NULL,
    created_at              REAL NOT NULL,
    updated_at              REAL NOT NULL
)
"""

_CREATE_VERIFICATIONS = """
CREATE TABLE IF NOT EXISTS re_buyer_verifications (
    id                 TEXT PRIMARY KEY,
    buyer_wallet       TEXT NOT NULL,
    method             TEXT NOT NULL,
    status             TEXT NOT NULL,
    threshold_wei      TEXT,
    details_json       TEXT NOT NULL,
    attestation_ref    TEXT,
    attestation_status TEXT NOT NULL,
    verified_at        REAL NOT NULL,
    expires_at         REAL NOT NULL,
    superseded_by      TEXT
)
"""

_INDEXES = (
    "CREATE INDEX IF NOT EXISTS idx_re_docs_property ON re_documents(property_id, doc_type)",
    "CREATE INDEX IF NOT EXISTS idx_re_docs_expiry ON re_documents(expires_at) ",
    "CREATE INDEX IF NOT EXISTS idx_re_escrows_property ON re_escrows(property_id)",
    "CREATE INDEX IF NOT EXISTS idx_re_verif_buyer ON re_buyer_verifications(buyer_wallet)",
)


def _row_to_dict(row) -> dict:
    return dict(row) if row is not None else None


class RealEstateStore:
    """All persistence for properties, documents, escrows, verifications."""

    def __init__(self, db: Database) -> None:
        self._db = db
        self._ready = False

    async def _ensure(self) -> None:
        if self._ready:
            return
        for ddl in (_CREATE_PROPERTIES, _CREATE_DOCUMENTS, _CREATE_ESCROWS,
                    _CREATE_VERIFICATIONS, *_INDEXES):
            await self._db.execute(ddl)
        self._ready = True

    # ── Properties ──────────────────────────────────────────────────────

    async def create_property(self, *, address: dict, price_wei: str,
                              seller_wallet: str, status: str = "draft") -> dict:
        await self._ensure()
        now = time.time()
        pid = f"prop_{uuid.uuid4().hex[:16]}"
        await self._db.execute(
            "INSERT INTO re_properties (id, address_json, price_wei, seller_wallet,"
            " status, deed_token_id, created_at, updated_at)"
            " VALUES (?, ?, ?, ?, ?, NULL, ?, ?)",
            (pid, json.dumps(address), str(price_wei), seller_wallet, status, now, now),
        )
        return await self.get_property(pid)

    async def get_property(self, property_id: str) -> dict | None:
        await self._ensure()
        row = await self._db.fetchone(
            "SELECT * FROM re_properties WHERE id = ?", (property_id,))
        if row is None:
            return None
        d = _row_to_dict(row)
        d["address"] = json.loads(d.pop("address_json"))
        return d

    async def list_properties(self, status: str | None = None) -> list[dict]:
        await self._ensure()
        if status:
            rows = await self._db.fetchall(
                "SELECT * FROM re_properties WHERE status = ? ORDER BY created_at DESC",
                (status,))
        else:
            rows = await self._db.fetchall(
                "SELECT * FROM re_properties ORDER BY created_at DESC")
        out = []
        for r in rows:
            d = _row_to_dict(r)
            d["address"] = json.loads(d.pop("address_json"))
            out.append(d)
        return out

    async def update_property(self, property_id: str, *, status: str | None = None,
                              deed_token_id: str | None = None) -> dict | None:
        await self._ensure()
        cur = await self.get_property(property_id)
        if cur is None:
            return None
        new_status = status if status is not None else cur["status"]
        new_deed = deed_token_id if deed_token_id is not None else cur["deed_token_id"]
        await self._db.execute(
            "UPDATE re_properties SET status = ?, deed_token_id = ?, updated_at = ?"
            " WHERE id = ?",
            (new_status, new_deed, time.time(), property_id),
        )
        return await self.get_property(property_id)

    # ── Documents (supersession retained) ───────────────────────────────

    async def add_document(self, *, property_id: str, doc_type: str,
                           content_hash: str, storage_ref: str | None,
                           storage_status: str, attestation_ref: str | None,
                           attestation_status: str, uploaded_at: float,
                           expires_at: float) -> dict:
        """Insert a new document version; the prior current version (if any)
        is stamped superseded_by = new id. History is never deleted."""
        await self._ensure()
        doc_id = f"redoc_{uuid.uuid4().hex[:16]}"
        prior = await self._db.fetchone(
            "SELECT id FROM re_documents WHERE property_id = ? AND doc_type = ?"
            " AND superseded_by IS NULL",
            (property_id, doc_type),
        )
        await self._db.execute(
            "INSERT INTO re_documents (id, property_id, doc_type, content_hash,"
            " storage_ref, storage_status, attestation_ref, attestation_status,"
            " uploaded_at, expires_at, superseded_by)"
            " VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, NULL)",
            (doc_id, property_id, doc_type, content_hash, storage_ref,
             storage_status, attestation_ref, attestation_status,
             uploaded_at, expires_at),
        )
        if prior is not None:
            await self._db.execute(
                "UPDATE re_documents SET superseded_by = ? WHERE id = ?",
                (doc_id, prior["id"]),
            )
        return _row_to_dict(await self._db.fetchone(
            "SELECT * FROM re_documents WHERE id = ?", (doc_id,)))

    async def current_documents(self, property_id: str) -> dict[str, dict]:
        """Current (non-superseded) document per type for a property."""
        await self._ensure()
        rows = await self._db.fetchall(
            "SELECT * FROM re_documents WHERE property_id = ?"
            " AND superseded_by IS NULL",
            (property_id,),
        )
        return {r["doc_type"]: _row_to_dict(r) for r in rows}

    async def document_history(self, property_id: str,
                               doc_type: str | None = None) -> list[dict]:
        await self._ensure()
        if doc_type:
            rows = await self._db.fetchall(
                "SELECT * FROM re_documents WHERE property_id = ? AND doc_type = ?"
                " ORDER BY uploaded_at DESC",
                (property_id, doc_type))
        else:
            rows = await self._db.fetchall(
                "SELECT * FROM re_documents WHERE property_id = ?"
                " ORDER BY uploaded_at DESC",
                (property_id,))
        return [_row_to_dict(r) for r in rows]

    async def documents_expiring_within(self, *, now: float,
                                        days: int) -> list[dict]:
        """Current documents whose expiry falls inside (now, now + days] —
        already-expired documents are excluded (they're blockers, not
        reminders). Feed for future re-upload notifications."""
        await self._ensure()
        horizon = now + days * 86400.0
        rows = await self._db.fetchall(
            "SELECT * FROM re_documents WHERE superseded_by IS NULL"
            " AND expires_at > ? AND expires_at <= ?"
            " ORDER BY expires_at ASC",
            (now, horizon),
        )
        return [_row_to_dict(r) for r in rows]

    async def update_document_attestation(self, doc_id: str, *,
                                          attestation_ref: str | None,
                                          attestation_status: str) -> None:
        await self._ensure()
        await self._db.execute(
            "UPDATE re_documents SET attestation_ref = ?, attestation_status = ?"
            " WHERE id = ?",
            (attestation_ref, attestation_status, doc_id),
        )

    # ── Escrow transactions ─────────────────────────────────────────────

    async def create_escrow(self, *, property_id: str, buyer_wallet: str,
                            amount_wei: str, state: str,
                            readiness_snapshot: dict | None) -> dict:
        await self._ensure()
        now = time.time()
        eid = f"resc_{uuid.uuid4().hex[:16]}"
        history = [{"state": state, "at": now}]
        await self._db.execute(
            "INSERT INTO re_escrows (id, property_id, buyer_wallet, amount_wei,"
            " state, readiness_snapshot_json, attestation_refs_json,"
            " tx_hashes_json, history_json, created_at, updated_at)"
            " VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
            (eid, property_id, buyer_wallet, str(amount_wei), state,
             json.dumps(readiness_snapshot) if readiness_snapshot else None,
             json.dumps({}), json.dumps({}), json.dumps(history), now, now),
        )
        return await self.get_escrow(eid)

    async def get_escrow(self, escrow_id: str) -> dict | None:
        await self._ensure()
        row = await self._db.fetchone(
            "SELECT * FROM re_escrows WHERE id = ?", (escrow_id,))
        if row is None:
            return None
        d = _row_to_dict(row)
        d["readiness_snapshot"] = (json.loads(d.pop("readiness_snapshot_json"))
                                   if d.get("readiness_snapshot_json") else None)
        d["attestation_refs"] = json.loads(d.pop("attestation_refs_json"))
        d["tx_hashes"] = json.loads(d.pop("tx_hashes_json"))
        d["history"] = json.loads(d.pop("history_json"))
        return d

    async def list_escrows(self, property_id: str | None = None) -> list[dict]:
        await self._ensure()
        if property_id:
            rows = await self._db.fetchall(
                "SELECT id FROM re_escrows WHERE property_id = ?"
                " ORDER BY created_at DESC", (property_id,))
        else:
            rows = await self._db.fetchall(
                "SELECT id FROM re_escrows ORDER BY created_at DESC")
        return [await self.get_escrow(r["id"]) for r in rows]

    async def transition_escrow(self, escrow_id: str, *, new_state: str,
                                attestation_refs: dict | None = None,
                                tx_hashes: dict | None = None) -> dict | None:
        """Append-only transition: history grows, refs/hashes merge in.
        The caller (service) enforces state-machine validity BEFORE calling."""
        await self._ensure()
        cur = await self.get_escrow(escrow_id)
        if cur is None:
            return None
        now = time.time()
        history = cur["history"] + [{"state": new_state, "at": now}]
        refs = {**cur["attestation_refs"], **(attestation_refs or {})}
        hashes = {**cur["tx_hashes"], **(tx_hashes or {})}
        await self._db.execute(
            "UPDATE re_escrows SET state = ?, attestation_refs_json = ?,"
            " tx_hashes_json = ?, history_json = ?, updated_at = ? WHERE id = ?",
            (new_state, json.dumps(refs), json.dumps(hashes),
             json.dumps(history), now, escrow_id),
        )
        return await self.get_escrow(escrow_id)

    # ── Buyer verifications (supersession retained) ─────────────────────

    async def add_verification(self, *, buyer_wallet: str, method: str,
                               status: str, threshold_wei: str | None,
                               details: dict, attestation_ref: str | None,
                               attestation_status: str, verified_at: float,
                               expires_at: float) -> dict:
        await self._ensure()
        vid = f"rebv_{uuid.uuid4().hex[:16]}"
        prior = await self._db.fetchone(
            "SELECT id FROM re_buyer_verifications WHERE buyer_wallet = ?"
            " AND superseded_by IS NULL",
            (buyer_wallet,),
        )
        await self._db.execute(
            "INSERT INTO re_buyer_verifications (id, buyer_wallet, method, status,"
            " threshold_wei, details_json, attestation_ref, attestation_status,"
            " verified_at, expires_at, superseded_by)"
            " VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, NULL)",
            (vid, buyer_wallet, method, status,
             str(threshold_wei) if threshold_wei is not None else None,
             json.dumps(details), attestation_ref, attestation_status,
             verified_at, expires_at),
        )
        if prior is not None:
            await self._db.execute(
                "UPDATE re_buyer_verifications SET superseded_by = ? WHERE id = ?",
                (vid, prior["id"]),
            )
        return _row_to_dict(await self._db.fetchone(
            "SELECT * FROM re_buyer_verifications WHERE id = ?", (vid,)))

    async def current_verification(self, buyer_wallet: str) -> dict | None:
        await self._ensure()
        row = await self._db.fetchone(
            "SELECT * FROM re_buyer_verifications WHERE buyer_wallet = ?"
            " AND superseded_by IS NULL",
            (buyer_wallet,),
        )
        if row is None:
            return None
        d = _row_to_dict(row)
        d["details"] = json.loads(d.pop("details_json"))
        return d
