"""Glasswing Security Badge manager backed by SQLite.

Handles the full lifecycle of security badges: issuance after a
passing audit, verification, renewal, revocation, and listing.
Badge IDs follow the format ``GLASSWING-{year}-{seq:04d}``.
"""

from __future__ import annotations

import hashlib
import json
import logging
import time
from datetime import datetime, timezone
from typing import Any

logger = logging.getLogger(__name__)

_BADGE_VALIDITY_SECONDS = 365 * 86400  # 1 year
_PASSING_STATUSES = ("passed", "pass", "clean")
_VERIFICATION_BASE = "https://openmatrix-ai.com/badge"
_API_BASE = "https://api.openmatrix-ai.com"


class BadgeManager:
    """SQLite-backed Glasswing security badge persistence.

    Provides issuance, verification, renewal, revocation, and
    listing of security badges tied to audited smart contracts.
    """

    def __init__(self, db, config: dict | None = None):
        """Initialise with a ``Database`` instance.

        Parameters
        ----------
        db : runtime.db.database.Database
            The platform's shared SQLite wrapper.
        config : dict, optional
            Optional configuration overrides.
        """
        self.db = db
        self.config = config or {}

    async def initialize(self) -> None:
        """Create the security_badges and badge_sequence tables if
        they do not already exist."""
        await self.db.execute(
            """
            CREATE TABLE IF NOT EXISTS security_badges (
                badge_id            TEXT PRIMARY KEY,
                contract_address    TEXT NOT NULL,
                contract_name       TEXT NOT NULL,
                audit_report_hash   TEXT,
                eas_uid             TEXT,
                issued_at           REAL NOT NULL,
                expires_at          REAL NOT NULL,
                renewal_count       INTEGER DEFAULT 0,
                status              TEXT DEFAULT 'valid',
                contact_email       TEXT,
                project_url         TEXT
            )
            """,
            commit=True,
        )
        await self.db.execute(
            """
            CREATE TABLE IF NOT EXISTS badge_sequence (
                year    INTEGER PRIMARY KEY,
                seq     INTEGER DEFAULT 0
            )
            """,
            commit=True,
        )

    # ── Issuance ────────────────────────────────────────────────────

    async def issue_badge(
        self,
        contract_address: str,
        contract_name: str,
        audit_report: dict,
        contact_email: str,
        project_url: str = "",
    ) -> dict:
        """Issue a new Glasswing security badge.

        Parameters
        ----------
        contract_address : str
            The audited contract's on-chain address.
        contract_name : str
            Human-readable contract name.
        audit_report : dict
            The full audit report; must have a passing ``status``.
        contact_email : str
            Contact email for the project team.
        project_url : str, optional
            URL of the project's website.

        Returns
        -------
        dict
            The complete badge record including ``badge_id``,
            ``verification_url``, and ``embed_code``.

        Raises
        ------
        ValueError
            If the audit report does not have a passing status.
        """
        status = audit_report.get("status", "")
        if status not in _PASSING_STATUSES:
            raise ValueError(
                f"Audit report status '{status}' is not passing. "
                f"Must be one of: {', '.join(_PASSING_STATUSES)}"
            )

        now = time.time()
        year = datetime.fromtimestamp(now, tz=timezone.utc).year

        badge_id = await self._next_badge_id(year)
        report_hash = hashlib.sha256(
            json.dumps(audit_report, sort_keys=True).encode()
        ).hexdigest()

        expires_at = now + _BADGE_VALIDITY_SECONDS

        await self.db.execute(
            """
            INSERT INTO security_badges
                (badge_id, contract_address, contract_name,
                 audit_report_hash, issued_at, expires_at,
                 renewal_count, status, contact_email, project_url)
            VALUES (?, ?, ?, ?, ?, ?, 0, 'valid', ?, ?)
            """,
            (
                badge_id,
                contract_address,
                contract_name,
                report_hash,
                now,
                expires_at,
                contact_email,
                project_url,
            ),
            commit=True,
        )

        verification_url = f"{_VERIFICATION_BASE}/{badge_id}"
        embed_code = self._build_embed_code(badge_id)

        logger.info("Issued badge %s for %s (%s)", badge_id, contract_name, contract_address)

        return {
            "badge_id": badge_id,
            "contract_address": contract_address,
            "contract_name": contract_name,
            "audit_report_hash": report_hash,
            "issued_at": now,
            "expires_at": expires_at,
            "renewal_count": 0,
            "status": "valid",
            "contact_email": contact_email,
            "project_url": project_url,
            "verification_url": verification_url,
            "embed_code": embed_code,
        }

    # ── Verification ────────────────────────────────────────────────

    async def verify_badge(self, badge_id: str) -> dict:
        """Verify a badge and return its current status.

        Parameters
        ----------
        badge_id : str
            The badge identifier (e.g. ``GLASSWING-2026-0001``).

        Returns
        -------
        dict
            Badge data with computed ``verified`` flag and
            ``time_until_expiry`` in seconds.

        Raises
        ------
        ValueError
            If the badge does not exist.
        """
        row = await self.db.fetchone(
            "SELECT * FROM security_badges WHERE badge_id = ?",
            (badge_id,),
        )
        if not row:
            raise ValueError(f"Badge '{badge_id}' not found")

        now = time.time()
        db_status = row["status"]
        expires_at = row["expires_at"]

        # Determine effective status
        if db_status == "revoked":
            effective_status = "revoked"
        elif now > expires_at:
            effective_status = "expired"
        else:
            effective_status = "valid"

        time_until_expiry = max(0.0, expires_at - now)
        verified = effective_status == "valid"

        return {
            "badge_id": row["badge_id"],
            "contract_address": row["contract_address"],
            "contract_name": row["contract_name"],
            "audit_report_hash": row["audit_report_hash"],
            "eas_uid": row["eas_uid"],
            "issued_at": row["issued_at"],
            "expires_at": expires_at,
            "renewal_count": row["renewal_count"],
            "status": effective_status,
            "contact_email": row["contact_email"],
            "project_url": row["project_url"],
            "verified": verified,
            "time_until_expiry": time_until_expiry,
            "verification_url": f"{_VERIFICATION_BASE}/{row['badge_id']}",
        }

    # ── Renewal ─────────────────────────────────────────────────────

    async def renew_badge(self, badge_id: str, new_audit_report: dict) -> dict:
        """Renew an existing badge with a fresh audit.

        Parameters
        ----------
        badge_id : str
            The badge to renew.
        new_audit_report : dict
            The new audit report; must have a passing status.

        Returns
        -------
        dict
            The updated badge record.

        Raises
        ------
        ValueError
            If the badge does not exist or the new audit does not pass.
        """
        status = new_audit_report.get("status", "")
        if status not in _PASSING_STATUSES:
            raise ValueError(
                f"New audit report status '{status}' is not passing. "
                f"Must be one of: {', '.join(_PASSING_STATUSES)}"
            )

        row = await self.db.fetchone(
            "SELECT * FROM security_badges WHERE badge_id = ?",
            (badge_id,),
        )
        if not row:
            raise ValueError(f"Badge '{badge_id}' not found")

        now = time.time()
        new_expires = now + _BADGE_VALIDITY_SECONDS
        new_hash = hashlib.sha256(
            json.dumps(new_audit_report, sort_keys=True).encode()
        ).hexdigest()
        new_renewal_count = row["renewal_count"] + 1

        await self.db.execute(
            """
            UPDATE security_badges SET
                expires_at = ?,
                audit_report_hash = ?,
                renewal_count = ?,
                status = 'valid'
            WHERE badge_id = ?
            """,
            (new_expires, new_hash, new_renewal_count, badge_id),
            commit=True,
        )

        logger.info(
            "Renewed badge %s (renewal #%d)", badge_id, new_renewal_count
        )

        return {
            "badge_id": badge_id,
            "contract_address": row["contract_address"],
            "contract_name": row["contract_name"],
            "audit_report_hash": new_hash,
            "issued_at": row["issued_at"],
            "expires_at": new_expires,
            "renewal_count": new_renewal_count,
            "status": "valid",
            "contact_email": row["contact_email"],
            "project_url": row["project_url"],
            "verification_url": f"{_VERIFICATION_BASE}/{badge_id}",
        }

    # ── Revocation ──────────────────────────────────────────────────

    async def revoke_badge(self, badge_id: str, reason: str) -> dict:
        """Revoke a badge without deleting it.

        Parameters
        ----------
        badge_id : str
            The badge to revoke.
        reason : str
            Human-readable reason for revocation.

        Returns
        -------
        dict
            Confirmation with badge_id and reason.

        Raises
        ------
        ValueError
            If the badge does not exist.
        """
        row = await self.db.fetchone(
            "SELECT badge_id FROM security_badges WHERE badge_id = ?",
            (badge_id,),
        )
        if not row:
            raise ValueError(f"Badge '{badge_id}' not found")

        await self.db.execute(
            "UPDATE security_badges SET status = 'revoked' WHERE badge_id = ?",
            (badge_id,),
            commit=True,
        )

        logger.warning("Revoked badge %s: %s", badge_id, reason)

        return {
            "badge_id": badge_id,
            "status": "revoked",
            "reason": reason,
        }

    # ── Listing ─────────────────────────────────────────────────────

    async def list_badges(self, status: str = "valid") -> list[dict]:
        """List all badges with the given status.

        Parameters
        ----------
        status : str
            Filter by status (``valid``, ``expired``, ``revoked``).
            Defaults to ``valid``.

        Returns
        -------
        list[dict]
            List of badge records.
        """
        rows = await self.db.fetchall(
            "SELECT * FROM security_badges WHERE status = ? ORDER BY issued_at DESC",
            (status,),
        )

        now = time.time()
        badges = []
        for row in rows:
            effective_status = status
            if status == "valid" and now > row["expires_at"]:
                effective_status = "expired"

            badges.append({
                "badge_id": row["badge_id"],
                "contract_address": row["contract_address"],
                "contract_name": row["contract_name"],
                "audit_report_hash": row["audit_report_hash"],
                "issued_at": row["issued_at"],
                "expires_at": row["expires_at"],
                "renewal_count": row["renewal_count"],
                "status": effective_status,
                "contact_email": row["contact_email"],
                "project_url": row["project_url"],
                "verification_url": f"{_VERIFICATION_BASE}/{row['badge_id']}",
            })

        return badges

    # ── Embed Code ──────────────────────────────────────────────────

    async def get_badge_embed_code(self, badge_id: str) -> str:
        """Return the HTML embed snippet for a badge.

        Parameters
        ----------
        badge_id : str
            The badge identifier.

        Returns
        -------
        str
            An HTML ``<script>`` tag that renders the badge widget.

        Raises
        ------
        ValueError
            If the badge does not exist.
        """
        row = await self.db.fetchone(
            "SELECT badge_id FROM security_badges WHERE badge_id = ?",
            (badge_id,),
        )
        if not row:
            raise ValueError(f"Badge '{badge_id}' not found")

        return self._build_embed_code(badge_id)

    # ── Private helpers ─────────────────────────────────────────────

    async def _next_badge_id(self, year: int) -> str:
        """Atomically increment the sequence counter for *year* and
        return the next badge ID."""
        row = await self.db.fetchone(
            "SELECT seq FROM badge_sequence WHERE year = ?",
            (year,),
        )
        if row:
            new_seq = row["seq"] + 1
            await self.db.execute(
                "UPDATE badge_sequence SET seq = ? WHERE year = ?",
                (new_seq, year),
                commit=True,
            )
        else:
            new_seq = 1
            await self.db.execute(
                "INSERT INTO badge_sequence (year, seq) VALUES (?, ?)",
                (year, new_seq),
                commit=True,
            )

        return f"GLASSWING-{year}-{new_seq:04d}"

    @staticmethod
    def _build_embed_code(badge_id: str) -> str:
        """Return the embeddable ``<script>`` tag for a badge."""
        return (
            f'<script src="{_API_BASE}/badge/widget.js" '
            f'data-badge="{badge_id}"></script>'
        )
