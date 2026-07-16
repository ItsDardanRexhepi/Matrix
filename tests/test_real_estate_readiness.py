"""RE-4: transaction-readiness engine — exhaustive tests.

The honest-failure law, executable: readiness is NEVER faked, every blocker is
named specifically, and there is no code path where ready=True with a blocker
present. Covers: every document type missing, every one stale by exactly one
day, freshness boundaries (the expiry instant itself), clock edge cases
(future-dated uploads), attestation gating, buyer proof-of-funds, and the
structural ready==not(blockers) invariant.
"""

import pytest

from runtime.blockchain.services.real_estate.readiness import (
    DEFAULT_FRESHNESS_DAYS,
    DEFAULT_REQUIRED_DOCUMENTS,
    Blocker,
    days_stale,
    evaluate_readiness,
    expires_at_for,
    is_fresh,
)

NOW = 2_000_000_000.0
DAY = 86400.0


def _fresh_doc(now=NOW, days_left=10.0, attestation="attested"):
    return {"expires_at": now + days_left * DAY, "attestation_status": attestation}


def _all_green_docs(now=NOW):
    return {t: _fresh_doc(now) for t in DEFAULT_REQUIRED_DOCUMENTS}


def _verified_buyer(now=NOW, days_left=10.0):
    return {"expires_at": now + days_left * DAY, "status": "verified"}


# ── The all-green case (the ONLY way to ready=True) ─────────────────────────

def test_all_green_is_ready_with_zero_blockers():
    r = evaluate_readiness(_all_green_docs(), _verified_buyer(), now=NOW)
    assert r.ready is True
    assert r.blockers == ()
    assert r.checked_at == NOW


def test_ready_is_structurally_derived_from_blockers():
    # ready must equal (blockers == empty) in every combination we can build.
    for missing in DEFAULT_REQUIRED_DOCUMENTS:
        docs = _all_green_docs()
        del docs[missing]
        r = evaluate_readiness(docs, _verified_buyer(), now=NOW)
        assert r.ready == (len(r.blockers) == 0)
        assert r.ready is False


# ── Every document type missing, individually named ─────────────────────────

@pytest.mark.parametrize("doc_type", DEFAULT_REQUIRED_DOCUMENTS)
def test_each_document_missing_is_a_named_blocker(doc_type):
    docs = _all_green_docs()
    del docs[doc_type]
    r = evaluate_readiness(docs, _verified_buyer(), now=NOW)
    assert r.ready is False
    assert len(r.blockers) == 1
    b = r.blockers[0]
    assert b.item == doc_type and b.reason == "missing"


@pytest.mark.parametrize("doc_type", DEFAULT_REQUIRED_DOCUMENTS)
def test_none_valued_document_counts_as_missing(doc_type):
    docs = _all_green_docs()
    docs[doc_type] = None
    r = evaluate_readiness(docs, _verified_buyer(), now=NOW)
    assert r.ready is False
    assert r.blockers[0].item == doc_type
    assert r.blockers[0].reason == "missing"


def test_everything_missing_names_every_blocker():
    r = evaluate_readiness({}, None, now=NOW)
    assert r.ready is False
    named = {b.item for b in r.blockers}
    assert named == set(DEFAULT_REQUIRED_DOCUMENTS) | {"proof_of_funds"}


# ── Every document type stale by exactly one day ────────────────────────────

@pytest.mark.parametrize("doc_type", DEFAULT_REQUIRED_DOCUMENTS)
def test_each_document_stale_by_one_day_is_named_with_days(doc_type):
    docs = _all_green_docs()
    docs[doc_type] = {"expires_at": NOW - 1 * DAY, "attestation_status": "attested"}
    r = evaluate_readiness(docs, _verified_buyer(), now=NOW)
    assert r.ready is False
    assert len(r.blockers) == 1
    b = r.blockers[0]
    assert b.item == doc_type and b.reason == "stale" and b.days_stale == 1


def test_stale_days_round_up_never_zero():
    # 1 second past expiry is 1 day stale, never a misleading 0.
    assert days_stale(NOW - 1, NOW) == 1
    assert days_stale(NOW - DAY, NOW) == 1
    assert days_stale(NOW - DAY - 1, NOW) == 2
    assert days_stale(NOW - 30 * DAY, NOW) == 30


# ── Freshness boundaries + clock edges ───────────────────────────────────────

def test_expiry_instant_itself_is_stale():
    # The window is [uploaded_at, expires_at) — the boundary belongs to
    # staleness, so an exact-boundary read can never stretch a window.
    assert is_fresh(NOW, NOW) is False
    docs = _all_green_docs()
    docs["title_report"] = {"expires_at": NOW, "attestation_status": "attested"}
    r = evaluate_readiness(docs, _verified_buyer(), now=NOW)
    assert r.ready is False
    assert r.blockers[0].reason == "stale"


def test_one_second_before_expiry_is_fresh():
    assert is_fresh(NOW + 1, NOW) is True
    docs = _all_green_docs()
    docs["title_report"] = {"expires_at": NOW + 1, "attestation_status": "attested"}
    r = evaluate_readiness(docs, _verified_buyer(), now=NOW)
    assert r.ready is True


def test_future_dated_expiry_far_ahead_is_fresh_not_error():
    # Clock skew safety: a document expiring far in the future is simply fresh.
    docs = _all_green_docs()
    docs["appraisal"] = {"expires_at": NOW + 1000 * DAY, "attestation_status": "attested"}
    assert evaluate_readiness(docs, _verified_buyer(), now=NOW).ready is True


def test_missing_expires_at_field_is_stale_not_crash():
    # A record without expires_at coerces to 0.0 → decades stale, named.
    docs = _all_green_docs()
    docs["inspection"] = {"attestation_status": "attested"}
    r = evaluate_readiness(docs, _verified_buyer(), now=NOW)
    assert r.ready is False
    assert r.blockers[0].item == "inspection" and r.blockers[0].reason == "stale"


# ── Attestation gating (unverified is a blocker, never invisible) ────────────

@pytest.mark.parametrize("status", ["queued", "skipped", "unattested", "", None])
def test_unverified_attestation_blocks(status):
    docs = _all_green_docs()
    docs["title_report"] = {"expires_at": NOW + 10 * DAY, "attestation_status": status}
    r = evaluate_readiness(docs, _verified_buyer(), now=NOW)
    assert r.ready is False
    b = r.blockers[0]
    assert b.item == "title_report" and b.reason == "unverified"


def test_stale_takes_priority_over_unverified_in_naming():
    # A stale AND unattested doc reports stale (the actionable re-upload).
    docs = _all_green_docs()
    docs["title_report"] = {"expires_at": NOW - DAY, "attestation_status": "queued"}
    r = evaluate_readiness(docs, _verified_buyer(), now=NOW)
    assert r.blockers[0].reason == "stale"


# ── Buyer proof-of-funds ─────────────────────────────────────────────────────

def test_missing_buyer_verification_blocks():
    r = evaluate_readiness(_all_green_docs(), None, now=NOW)
    assert r.ready is False
    assert r.blockers[0].item == "proof_of_funds"
    assert r.blockers[0].reason == "missing"


def test_stale_buyer_verification_blocks_with_days():
    stale = {"expires_at": NOW - 3 * DAY, "status": "verified"}
    r = evaluate_readiness(_all_green_docs(), stale, now=NOW)
    assert r.blockers[0].reason == "stale" and r.blockers[0].days_stale == 3


@pytest.mark.parametrize("status", ["insufficient_funds", "pending", "", None])
def test_unverified_buyer_status_blocks(status):
    v = {"expires_at": NOW + 10 * DAY, "status": status}
    r = evaluate_readiness(_all_green_docs(), v, now=NOW)
    assert r.ready is False
    assert r.blockers[0].item == "proof_of_funds"
    assert r.blockers[0].reason == "unverified"


def test_buyer_expiry_boundary_is_stale():
    v = {"expires_at": NOW, "status": "verified"}
    r = evaluate_readiness(_all_green_docs(), v, now=NOW)
    assert r.blockers[0].reason == "stale"


# ── Proof-of-funds must cover the price (readiness honesty) ──────────────────

def _verified_with(amount_wei, now=NOW, days_left=10.0):
    return {"expires_at": now + days_left * DAY, "status": "verified",
            "verified_amount_wei": str(amount_wei)}


def test_verified_but_underfunded_is_insufficient():
    v = _verified_with(1)                       # proved 1 wei
    r = evaluate_readiness(_all_green_docs(), v, now=NOW, required_amount=10**18)
    assert r.ready is False
    assert r.blockers[0].item == "proof_of_funds"
    assert r.blockers[0].reason == "insufficient"


def test_verified_and_funded_passes():
    v = _verified_with(10**18)
    r = evaluate_readiness(_all_green_docs(), v, now=NOW, required_amount=10**18)
    assert r.ready is True                       # exactly covers → ok


def test_verified_amount_from_balance_detail_is_read():
    v = {"expires_at": NOW + 10 * DAY, "status": "verified",
         "details": {"balance_wei": str(10**18)}}
    r = evaluate_readiness(_all_green_docs(), v, now=NOW, required_amount=10**18)
    assert r.ready is True


def test_verified_with_unknown_amount_fails_closed_when_price_required():
    v = {"expires_at": NOW + 10 * DAY, "status": "verified"}   # no amount at all
    r = evaluate_readiness(_all_green_docs(), v, now=NOW, required_amount=10**18)
    assert r.ready is False
    assert r.blockers[0].reason == "insufficient"


def test_no_required_amount_skips_the_coverage_check():
    # Backwards-compatible: when no price is supplied, verified+fresh is enough.
    v = {"expires_at": NOW + 10 * DAY, "status": "verified"}
    assert evaluate_readiness(_all_green_docs(), v, now=NOW).ready is True


# ── Multiple blockers all named, nothing summarized away ─────────────────────

def test_multiple_blockers_are_all_named():
    docs = _all_green_docs()
    del docs["title_report"]                                   # missing
    docs["appraisal"] = {"expires_at": NOW - 5 * DAY,
                         "attestation_status": "attested"}      # stale 5d
    docs["inspection"] = {"expires_at": NOW + DAY,
                          "attestation_status": "queued"}       # unverified
    r = evaluate_readiness(docs, None, now=NOW)                 # + buyer missing
    assert r.ready is False
    by_item = {b.item: b for b in r.blockers}
    assert by_item["title_report"].reason == "missing"
    assert by_item["appraisal"].reason == "stale"
    assert by_item["appraisal"].days_stale == 5
    assert by_item["inspection"].reason == "unverified"
    assert by_item["proof_of_funds"].reason == "missing"
    assert len(r.blockers) == 4


# ── expires_at_for (window assignment) ───────────────────────────────────────

@pytest.mark.parametrize("doc_type,days", sorted(DEFAULT_FRESHNESS_DAYS.items()))
def test_default_windows_apply_exactly(doc_type, days):
    assert expires_at_for(doc_type, NOW) == NOW + days * DAY


def test_unknown_doc_type_gets_shortest_window_never_generous():
    shortest = min(DEFAULT_FRESHNESS_DAYS.values())
    assert expires_at_for("mystery_document", NOW) == NOW + shortest * DAY


def test_config_override_changes_window():
    assert expires_at_for("title_report", NOW, {"title_report": 7}) == NOW + 7 * DAY


# ── Config-driven required set ───────────────────────────────────────────────

def test_custom_required_set_is_honored():
    docs = {"title_report": _fresh_doc()}
    r = evaluate_readiness(docs, _verified_buyer(), now=NOW,
                           required_documents=("title_report",))
    assert r.ready is True
    r2 = evaluate_readiness({}, _verified_buyer(), now=NOW,
                            required_documents=("title_report",))
    assert r2.ready is False and r2.blockers[0].item == "title_report"


def test_serialization_shape():
    r = evaluate_readiness({}, None, now=NOW)
    d = r.to_dict()
    assert d["ready"] is False and d["checked_at"] == NOW
    assert all({"item", "reason"} <= set(b) for b in d["blockers"])
    assert isinstance(Blocker(item="x", reason="missing").to_dict(), dict)
