"""NEW-85 — `send_payment` says what it did: recorded, not settled.

THE FINDING. It returned ``"status": "completed"`` over money that never
moved. No chain write, no signer, no tx_hash, no debit of a sender balance, no
credit of a recipient balance — this service holds no ledger at all. The record
in ``self._payments`` is a record OF a payment instruction, not the payment.

WHY THE FIX IS VOCABULARY AND NOT REMOVAL. The test that settled it: STRIP THE
OUTCOME CLAIM — IS THERE WORK LEFT? Measured on the real object:

    send_payment, minus the word "completed":
        compliance        {'approved': True, 'corridor': 'USD->EUR', ...}
        exchange_rate     0.92
        converted_amount  457.7
        fee_amount        2.5

    remit, minus the word "sent":
        compliance        None
        exchange_rate     None
        converted_amount  None      <- never converted at all

So `send_payment` is category 6 (real-local-defective) — genuine guards,
genuine arithmetic, fabricated CUSTODY — and `remit` is category 4. Removing
`send_payment` would destroy working compliance and pricing; renaming its
outcome preserves them. That difference is why these ship as two different
commits with two different dispositions.

SCENARIO COVERAGE, stated per test — the domain-7 lesson was scenario breadth:

    below the KYC threshold      -> test_a_sub_threshold_payment_is_recorded_not_settled
    above the KYC threshold      -> test_an_above_threshold_payment_still_halts
    the compliance halt is real  -> test_the_compliance_halt_is_untouched
    the arithmetic is preserved  -> test_the_real_work_survives_the_rename
    every surface, not just one  -> test_no_surface_still_says_sent
    the D7 control clears        -> test_the_d7_ratchet_can_be_tightened_for_this_method
"""

from __future__ import annotations

import ast
import inspect
import pathlib

import pytest

from runtime.blockchain.services.cross_border.service import CrossBorderService

REPO = pathlib.Path(__file__).resolve().parent.parent


# ── The custody claim ────────────────────────────────────────────────────


async def test_a_sub_threshold_payment_is_recorded_not_settled():
    """SCENARIO: $500 USD->EUR, below the $1,000 max_without_id.

    This is the band that mattered: compliance APPROVES here, so pre-fix this
    returned a clean "completed". It is also the remittance-sized band.
    """
    svc = CrossBorderService({})
    result = await svc.send_payment("0xA", "0xB", 500.0, "USD", "EUR")

    assert result["status"] == "recorded_unsettled"
    assert result["settled"] is False
    assert result["value_moved"] is False
    assert "no value was transferred" in result["disclosure"].lower()
    assert "has not been debited" in result["disclosure"]
    assert "tx_hash" not in result


async def test_an_above_threshold_payment_still_halts():
    """SCENARIO: $5,000 — the KYC branch must be untouched by the rename.

    A vocabulary fix that accidentally turned a halt into a record would be
    strictly worse than the defect it replaced.
    """
    svc = CrossBorderService({})
    result = await svc.send_payment("0xA", "0xB", 5000.0, "USD", "EUR")

    assert result["status"] == "compliance_hold"
    assert "kyc_required" in result["compliance"]["flags"]
    assert result["payment_id"] if "payment_id" in result else True


async def test_the_compliance_halt_is_untouched():
    """SCENARIO: a sanctioned sender, configured explicitly.

    The sanctions list is empty by default (a separate finding), so this
    configures one to prove the branch still refuses after the rename.
    """
    svc = CrossBorderService({"cross_border": {"sanctions_list": ["0xBAD"]}})
    result = await svc.send_payment("0xBAD", "0xB", 100.0, "USD", "EUR")

    assert result["status"] == "compliance_hold"
    assert "sanctions_hit" in result["compliance"]["flags"]


# ── The work that justified vocabulary over removal ──────────────────────


async def test_the_real_work_survives_the_rename():
    """The whole argument for not deleting this method, asserted.

    If a later edit strips the compliance/FX/fee work, the disposition that
    justified keeping it no longer holds and this fails.
    """
    svc = CrossBorderService({})
    r = await svc.send_payment("0xA", "0xB", 500.0, "USD", "EUR")

    assert r["compliance"]["approved"] is True
    assert r["exchange_rate"] > 0
    assert r["converted_amount"] > 0
    assert r["fee_amount"] > 0
    assert r["net_source_amount"] == pytest.approx(500.0 - r["fee_amount"])
    assert r["converted_amount"] == pytest.approx(
        r["net_source_amount"] * r["exchange_rate"], rel=1e-6
    )


# ── Every surface (standing rule 9: inert means inert on all surfaces) ────


def test_no_surface_still_says_sent():
    """SCENARIO: the three surfaces that carry the claim.

    Pre-fix all three said the payment went out: the returned status, the
    operator log line, and — loudest — the PUBLIC FEED event.
    """
    # Asserted against EXECUTING code. The docstring deliberately QUOTES the
    # removed literal so a reader knows what was there — a grep-based control
    # cannot tell a quotation of dead code from a use of it, and would either
    # fail on honest documentation or be silenced by deleting it. Comments
    # never enter the AST; the docstring is dropped explicitly.
    fn = ast.parse(inspect.getsource(CrossBorderService.send_payment).strip()).body[0]
    if (
        fn.body
        and isinstance(fn.body[0], ast.Expr)
        and isinstance(fn.body[0].value, ast.Constant)
        and isinstance(fn.body[0].value.value, str)
    ):
        fn.body = fn.body[1:]
    live = ast.unparse(fn)

    assert "'completed'" not in live and '"completed"' not in live
    assert "Payment sent:" not in live
    assert "NOT settled" in live, "the log line no longer discloses"

    catalog_src = (REPO / "runtime/capabilities/catalog.py").read_text()
    live_cat = "\n".join(
        ln for ln in catalog_src.splitlines() if not ln.strip().startswith("#")
    )
    assert 'feed_event="payment_sent"' not in live_cat, (
        "the public feed still announces payment_sent"
    )


async def test_the_disclosure_survives_the_dispatcher_seam():
    """The clients read the dispatcher envelope, not the return dict."""
    import json

    from runtime.blockchain.services.service_dispatcher import ServiceDispatcher

    raw = await ServiceDispatcher({}).execute("send_payment", params={
        "sender": "0xA", "recipient": "0xB", "amount": 500.0,
        "from_currency": "USD", "to_currency": "EUR",
    })
    payload = json.loads(raw)
    inner = payload.get("result", payload)

    assert inner["status"] == "recorded_unsettled"
    assert inner["value_moved"] is False
    assert "disclosure" in inner


# ── The control ──────────────────────────────────────────────────────────


def test_the_d7_ratchet_can_be_tightened_for_this_method():
    """D7 must now CLEAR send_payment, or the fix did not take.

    This is the positive half of the ratchet: a fix has to make the detector
    stop matching, otherwise the inventory can never shrink and the control
    is decorative.
    """
    from tests.test_fake_delivery_detector import find_fake_delivery

    target = "services/cross_border/service.py::CrossBorderService.send_payment"
    assert target not in find_fake_delivery(), (
        "D7 still matches send_payment — the disclosure is not being seen"
    )


def test_the_scope_boundary_was_crossed_deliberately_and_not_by_accident():
    """THE RETIRED SCOPE PIN, kept as a record rather than deleted.

    NEW-85 shipped with a pin asserting that `remit` and `bridge_transfer`
    were STILL flagged by D7 — so that commit could not silently do
    undisclosed work while claiming to fix only `send_payment`.

    NEW-86/87 is the commit licensed to cross that boundary, and it did: both
    are now cleared, by two DIFFERENT dispositions (delegation, and disable).
    Inverting the assertion rather than deleting it keeps the record that the
    boundary existed and was crossed on purpose — a deleted pin looks
    identical to a pin that was never written.
    """
    from tests.test_fake_delivery_detector import find_fake_delivery

    current = find_fake_delivery()
    for name in ("remit", "bridge_transfer", "send_payment"):
        assert f"services/cross_border/service.py::CrossBorderService.{name}" \
            not in current
    assert current, "D7 matches nothing at all — it has stopped detecting"
