"""Transaction-readiness engine — the heart of the real-estate escrow feature.

PURE module: no I/O, no clock reads, no network. Callers supply `now` and the
current document/verification records; this module answers one question with
zero room for fabrication:

    "Can this property transact RIGHT NOW, and if not, exactly why not?"

Honest-failure law (structural, not aspirational):
  • `ready` is DERIVED as `len(blockers) == 0` — there is no code path that can
    set ready=True while any blocker exists, because ready is never assigned
    independently of the blocker list.
  • A missing document is named by type. A stale document is named with exactly
    how many days stale it is. An unattested document is named as unverified.
    Nothing is summarized away.
  • Staleness is computed on read from `now` — no cron, no cached green.

Freshness windows are config-driven per document type; the defaults below are
the documented v1 policy (see REAL_ESTATE.md).
"""
from __future__ import annotations

import math
from dataclasses import dataclass, field


# ── Document types + default freshness windows (days) ──────────────────────
# Config override: services.real_estate.freshness_days = {"title_report": 30, ...}
DEFAULT_FRESHNESS_DAYS: dict[str, int] = {
    "title_report": 30,
    "inspection": 90,
    "pest_roof_inspection": 90,
    "appraisal": 120,
    "seller_disclosures": 180,
    "hoa_documents": 90,
    "insurance_binder": 30,
}

# Buyer-side proof-of-funds freshness (days). Config: services.real_estate.
# proof_of_funds_days.
DEFAULT_PROOF_OF_FUNDS_DAYS: int = 30

# The document set a property must hold to be transaction-ready. Config
# override: services.real_estate.required_documents (list of type names).
DEFAULT_REQUIRED_DOCUMENTS: tuple[str, ...] = tuple(DEFAULT_FRESHNESS_DAYS)

_DAY_SECONDS = 86400.0

# Attestation states that count as verified. Anything else (queued, skipped,
# failed, unattested, missing field) is a named "unverified" blocker — the
# fail-closed EAS system means a document is only verified once its
# attestation genuinely went on-chain.
VERIFIED_ATTESTATION_STATUSES: frozenset[str] = frozenset({"attested"})


@dataclass(frozen=True)
class Blocker:
    """One named reason a property cannot transact. `days_stale` is present
    only for stale items (whole days, rounded up — 1 second past expiry is
    1 day stale, never 0)."""

    item: str                    # document type, or "proof_of_funds"
    reason: str                  # "missing" | "stale" | "unverified"
    days_stale: int | None = None
    detail: str = ""

    def to_dict(self) -> dict:
        out: dict = {"item": self.item, "reason": self.reason}
        if self.days_stale is not None:
            out["days_stale"] = self.days_stale
        if self.detail:
            out["detail"] = self.detail
        return out


@dataclass(frozen=True)
class TransactionReadiness:
    """The verdict. `ready` is structurally `not blockers` — see checks()."""

    ready: bool
    blockers: tuple[Blocker, ...] = field(default_factory=tuple)
    checked_at: float = 0.0

    def to_dict(self) -> dict:
        return {
            "ready": self.ready,
            "blockers": [b.to_dict() for b in self.blockers],
            "checked_at": self.checked_at,
        }


def days_stale(expires_at: float, now: float) -> int:
    """Whole days past expiry, rounded UP. Exactly at expiry (now == expires_at)
    a document is already stale (the window is [uploaded_at, expires_at)), and
    one second past is 1 day stale — never a misleading 0."""
    overdue = now - expires_at
    if overdue < 0:
        return 0
    return max(1, math.ceil(overdue / _DAY_SECONDS)) if overdue > 0 else 1


def is_fresh(expires_at: float, now: float) -> bool:
    """Fresh means strictly before expiry. `now == expires_at` is stale — the
    boundary belongs to staleness so a window can never be stretched by an
    exact-boundary read. A non-finite expiry (inf/NaN — impossible from our
    writers, but defense-in-depth) is STALE, never eternally fresh."""
    if not math.isfinite(expires_at):
        return False
    return now < expires_at


def _document_blocker(doc_type: str, doc: dict | None, now: float) -> Blocker | None:
    """Blocker for one required document type, or None if it clears all checks.
    `doc` is the CURRENT (non-superseded) record for that type, a dict with at
    least: expires_at (float), attestation_status (str)."""
    if doc is None:
        return Blocker(item=doc_type, reason="missing",
                       detail="document has never been uploaded")

    expires_at = float(doc.get("expires_at") or 0.0)
    if not is_fresh(expires_at, now):
        return Blocker(
            item=doc_type, reason="stale",
            days_stale=days_stale(expires_at, now),
            detail="re-upload required — freshness window elapsed",
        )

    status = str(doc.get("attestation_status") or "unattested")
    if status not in VERIFIED_ATTESTATION_STATUSES:
        return Blocker(
            item=doc_type, reason="unverified",
            detail=f"on-chain attestation not confirmed (status: {status})",
        )
    return None


def _verified_amount(verification: dict) -> int | None:
    """The proven funds amount, in wei, if the verification carries one.
    Reads a top-level `verified_amount_wei` first, else the wallet-balance
    detail. None means "amount unknown" — which, when a required amount is in
    play, is a FAIL-CLOSED blocker, never a pass."""
    amt = verification.get("verified_amount_wei")
    if amt is None:
        amt = (verification.get("details") or {}).get("balance_wei")
    if amt is None:
        return None
    try:
        return int(amt)
    except (TypeError, ValueError):
        return None


def _buyer_blocker(verification: dict | None, now: float,
                   required_amount: int | None = None) -> Blocker | None:
    """Blocker for the buyer's proof-of-funds, or None if verified, fresh, AND
    (when `required_amount` is given) proven to cover it. A verification that
    does not demonstrably cover the purchase price is `insufficient` — a stale
    threshold trick (verify $1 against a $1M property) can never pass."""
    if verification is None:
        return Blocker(item="proof_of_funds", reason="missing",
                       detail="buyer has no proof-of-funds verification")

    expires_at = float(verification.get("expires_at") or 0.0)
    if not is_fresh(expires_at, now):
        return Blocker(
            item="proof_of_funds", reason="stale",
            days_stale=days_stale(expires_at, now),
            detail="re-verification required — proof-of-funds window elapsed",
        )

    status = str(verification.get("status") or "unverified")
    if status != "verified":
        return Blocker(
            item="proof_of_funds", reason="unverified",
            detail=f"verification not confirmed (status: {status})",
        )

    if required_amount is not None:
        proven = _verified_amount(verification)
        if proven is None or proven < int(required_amount):
            return Blocker(
                item="proof_of_funds", reason="insufficient",
                detail=(f"proven funds {proven if proven is not None else 'unknown'}"
                        f" wei do not cover the purchase price {int(required_amount)}"
                        " wei — re-verify against the full amount"),
            )
    return None


def evaluate_readiness(
    documents_by_type: dict[str, dict | None],
    buyer_verification: dict | None,
    *,
    now: float,
    required_documents: tuple[str, ...] | list[str] = DEFAULT_REQUIRED_DOCUMENTS,
    required_amount: int | None = None,
) -> TransactionReadiness:
    """The single readiness verdict.

    `documents_by_type`: current (non-superseded) document record per type —
    absent keys and None values both mean "missing".
    `buyer_verification`: the buyer's current proof-of-funds record, or None.
    `required_amount`: the purchase price in wei — when given, the buyer's
    proven funds must cover it or proof-of-funds is an `insufficient` blocker.

    Every required document must be present, fresh (strictly before its
    expires_at), and attestation-verified; the buyer's proof-of-funds must be
    present, fresh, verified, and cover the price. Each failure is one named
    Blocker. `ready` is DERIVED from the blocker list — never set independently.
    """
    blockers: list[Blocker] = []

    for doc_type in required_documents:
        b = _document_blocker(doc_type, documents_by_type.get(doc_type), now)
        if b is not None:
            blockers.append(b)

    bb = _buyer_blocker(buyer_verification, now, required_amount)
    if bb is not None:
        blockers.append(bb)

    return TransactionReadiness(
        ready=(len(blockers) == 0),   # the ONLY assignment of ready — derived
        blockers=tuple(blockers),
        checked_at=now,
    )


def expires_at_for(doc_type: str, uploaded_at: float,
                   freshness_days: dict[str, int] | None = None) -> float:
    """Expiry timestamp for a newly uploaded document of `doc_type`.
    Unknown types get the SHORTEST default window (fail conservative, never
    generous) so a mistyped document type can't buy extra freshness."""
    windows = {**DEFAULT_FRESHNESS_DAYS, **(freshness_days or {})}
    days = windows.get(doc_type, min(windows.values()))
    return uploaded_at + days * _DAY_SECONDS
