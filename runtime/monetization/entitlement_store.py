"""Phase 3: durable store of VERIFIED App Store transactions + entitlements.

Two tables, async sqlite (house style of ``runtime.notifications.token_store``):

* ``iap_transactions`` — one row per verified signed transaction, keyed on
  ``transaction_id``. This is the idempotency ledger: replaying the same
  signed transaction (client retry, purchase-return + updates listener, or a
  re-posted webhook) records NOTHING new. Consumables live here — accepted
  and recorded, never entitlement rows, never a tier.
* ``iap_entitlements`` — one row per subscription lineage, keyed on
  ``originalTransactionId``. ASN flips update ``status`` in place: refund
  flips the row to ``refunded``, revoke to ``revoked``, expiry to
  ``expired``; a renewal writes the fresh ``expires_date`` back to ``active``.

``refunded``/``revoked`` are TERMINAL: Apple delivers notifications with no
ordering guarantee, and after a refund the client still (correctly) reports
the next renewal JWS to /iap/verify — so the blanket upsert refuses to lift a
terminal status, and ``set_status`` refuses to leave one without an explicit
``allow_terminal_override``. Refund wins regardless of arrival order.
(A rare REFUND_REVERSED is deliberately NOT auto-reactivated — the ASN
handler logs it for manual review; fail-closed means toward less
entitlement, never more.)

This is the server-side entitlement PRIMITIVE — a queryable fact table.
Nothing here gates existing routes; adopting it as a gate is a later,
deliberate decision. Writes happen only from routes that verified the JWS
chain first; there is no unverified write path.
"""

from __future__ import annotations

import logging
import time
from typing import Any

logger = logging.getLogger(__name__)

_CREATE_TRANSACTIONS = """
CREATE TABLE IF NOT EXISTS iap_transactions (
    transaction_id          TEXT PRIMARY KEY,
    original_transaction_id TEXT,
    product_id              TEXT,
    product_type            TEXT,
    user_key                TEXT,
    quantity                INTEGER,
    purchase_date           REAL,
    environment             TEXT,
    status                  TEXT,
    recorded_at             REAL
)
"""

_CREATE_ENTITLEMENTS = """
CREATE TABLE IF NOT EXISTS iap_entitlements (
    original_transaction_id TEXT PRIMARY KEY,
    user_key                TEXT,
    product_id              TEXT,
    tier                    TEXT,
    status                  TEXT,
    purchase_date           REAL,
    expires_date            REAL,
    environment             TEXT,
    updated_at              REAL
)
"""

#: statuses an entitlement row can hold.
STATUSES = ("active", "expired", "refunded", "revoked")

#: terminal statuses — once set, only an explicit override can leave them.
TERMINAL_STATUSES = ("refunded", "revoked")


class EntitlementStore:
    """CRUD over verified-IAP tables. Reads are fail-safe (empty on DB
    trouble); writes raise so a verified purchase is never silently dropped."""

    def __init__(self, db: Any) -> None:
        self._db = db
        self._ready = False

    async def _ensure_tables(self) -> None:
        if self._ready:
            return
        await self._db.execute(_CREATE_TRANSACTIONS)
        await self._db.execute(_CREATE_ENTITLEMENTS)
        self._ready = True

    # ── Idempotency ledger ──────────────────────────────────────────

    async def record_transaction(
        self,
        *,
        transaction_id: str,
        original_transaction_id: str,
        product_id: str,
        product_type: str,
        user_key: str = "",
        quantity: int = 1,
        purchase_date: float = 0.0,
        environment: str = "",
    ) -> bool:
        """Record a verified transaction. Returns False when this
        ``transaction_id`` was already recorded (replay) — nothing changes."""
        await self._ensure_tables()
        if not transaction_id:
            raise ValueError("transaction_id required")
        existing = await self._db.fetchall(
            "SELECT 1 FROM iap_transactions WHERE transaction_id = ?",
            (transaction_id,))
        if existing:
            return False
        await self._db.execute(
            """
            INSERT OR IGNORE INTO iap_transactions
                (transaction_id, original_transaction_id, product_id,
                 product_type, user_key, quantity, purchase_date,
                 environment, status, recorded_at)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, 'recorded', ?)
            """,
            (transaction_id, original_transaction_id, product_id,
             product_type, user_key, quantity, purchase_date,
             environment, time.time()),
        )
        return True

    async def mark_transaction(self, transaction_id: str, status: str) -> None:
        """Flip a recorded transaction's status (e.g. consumable refund)."""
        await self._ensure_tables()
        await self._db.execute(
            "UPDATE iap_transactions SET status = ? WHERE transaction_id = ?",
            (status, transaction_id))

    async def transaction(self, transaction_id: str) -> dict[str, Any] | None:
        await self._ensure_tables()
        try:
            rows = await self._db.fetchall(
                "SELECT * FROM iap_transactions WHERE transaction_id = ?",
                (transaction_id,))
        except Exception:
            logger.exception("iap transaction read failed")
            return None
        return dict(rows[0]) if rows else None

    # ── Entitlements ────────────────────────────────────────────────

    async def upsert_entitlement(
        self,
        *,
        original_transaction_id: str,
        product_id: str,
        tier: str,
        user_key: str = "",
        status: str = "active",
        purchase_date: float = 0.0,
        expires_date: float = 0.0,
        environment: str = "",
    ) -> None:
        """Create/refresh a subscription lineage row. A blank ``user_key``
        never overwrites a known one (webhooks carry no session), and a
        TERMINAL status (refunded/revoked) is sticky: a late-arriving renewal
        or a post-refund client /verify report can update dates but can NEVER
        lift the row back to active. Refund wins regardless of order."""
        await self._ensure_tables()
        if not original_transaction_id:
            raise ValueError("original_transaction_id required")
        if status not in STATUSES:
            raise ValueError(f"invalid status {status!r}")
        await self._db.execute(
            """
            INSERT INTO iap_entitlements
                (original_transaction_id, user_key, product_id, tier, status,
                 purchase_date, expires_date, environment, updated_at)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
            ON CONFLICT(original_transaction_id) DO UPDATE SET
                user_key = CASE WHEN excluded.user_key != ''
                                THEN excluded.user_key
                                ELSE iap_entitlements.user_key END,
                product_id = excluded.product_id,
                tier = excluded.tier,
                status = CASE WHEN iap_entitlements.status IN ('refunded', 'revoked')
                              THEN iap_entitlements.status
                              ELSE excluded.status END,
                purchase_date = excluded.purchase_date,
                expires_date = excluded.expires_date,
                environment = excluded.environment,
                updated_at = excluded.updated_at
            """,
            (original_transaction_id, user_key, product_id, tier, status,
             purchase_date, expires_date, environment, time.time()),
        )

    async def set_status(self, original_transaction_id: str, status: str,
                         *, expires_date: float | None = None,
                         allow_terminal_override: bool = False) -> bool:
        """Flip an entitlement row's status (ASN: refund/revoke/expire).
        Returns False when no such lineage exists — or when the row sits in a
        TERMINAL state (refunded/revoked) and the new status would leave it;
        only an explicit ``allow_terminal_override=True`` (a deliberate,
        human-reviewed reversal) may do that."""
        await self._ensure_tables()
        if status not in STATUSES:
            raise ValueError(f"invalid status {status!r}")
        rows = await self._db.fetchall(
            "SELECT status FROM iap_entitlements WHERE original_transaction_id = ?",
            (original_transaction_id,))
        if not rows:
            return False
        current = str(rows[0]["status"] if not isinstance(rows[0], tuple)
                      else rows[0][0])
        if current in TERMINAL_STATUSES and status not in TERMINAL_STATUSES \
                and not allow_terminal_override:
            logger.warning(
                "iap: refused %s -> %s for lineage %s (terminal state is sticky)",
                current, status, original_transaction_id)
            return False
        if expires_date is None:
            await self._db.execute(
                "UPDATE iap_entitlements SET status = ?, updated_at = ? "
                "WHERE original_transaction_id = ?",
                (status, time.time(), original_transaction_id))
        else:
            await self._db.execute(
                "UPDATE iap_entitlements SET status = ?, expires_date = ?, "
                "updated_at = ? WHERE original_transaction_id = ?",
                (status, expires_date, time.time(), original_transaction_id))
        return True

    async def entitlement(self, original_transaction_id: str) -> dict[str, Any] | None:
        await self._ensure_tables()
        try:
            rows = await self._db.fetchall(
                "SELECT * FROM iap_entitlements WHERE original_transaction_id = ?",
                (original_transaction_id,))
        except Exception:
            logger.exception("iap entitlement read failed")
            return None
        return dict(rows[0]) if rows else None

    # ── The entitlement primitive ───────────────────────────────────

    async def entitlements_for(self, user_key: str) -> list[dict[str, Any]]:
        """All entitlement rows bound to a user key (fail-safe: empty)."""
        if not user_key:
            return []
        await self._ensure_tables()
        try:
            rows = await self._db.fetchall(
                "SELECT * FROM iap_entitlements WHERE user_key = ?", (user_key,))
        except Exception:
            logger.exception("iap entitlements_for read failed")
            return []
        return [dict(r) for r in rows]

    async def active_tier_for(self, user_key: str, *,
                              now: float | None = None) -> str | None:
        """Highest currently-active verified tier for a user, or None.

        Active = status 'active' AND not past expires_date. This is the
        query future server-side gates would call; nothing calls it as a
        gate yet (built, not retro-fitted)."""
        now = time.time() if now is None else now
        rank = {"enterprise": 2, "pro": 1}
        best: str | None = None
        for row in await self.entitlements_for(user_key):
            if row.get("status") != "active":
                continue
            expires = float(row.get("expires_date") or 0.0)
            if expires and expires < now:
                continue
            tier = str(row.get("tier") or "")
            if tier in rank and (best is None or rank[tier] > rank[best]):
                best = tier
        return best
