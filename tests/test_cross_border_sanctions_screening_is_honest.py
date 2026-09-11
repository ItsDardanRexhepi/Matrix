"""A sanctions screen that cannot match must not report itself as a screen.

FINDING 14-C. Every corridor in `_CORRIDOR_REQUIREMENTS` declares
`sanctions_check: True`. The branch in `check_compliance` is REAL logic — it
returns `approved: False` with "Sender address is sanctioned" on a hit. But
`_sanctions_list` is fed from config `cross_border.sanctions_list`, which is
**empty in the shipped deployment** (measured: len 0), so the branch executes and
**can never match**.

NOT UNREACHABLE — UNFED. The distinction is the finding. The inert-fix pattern is
code that never runs; this code runs, on every payment, and is starved of the data
that would let it decide anything.

AND THE PRECISION MATTERS. The sibling controls in the same method genuinely
enforce — a 50,000 transfer is refused on the reporting threshold, driven. So the
honest statement is "one control is unfed", not "compliance is broken". Those are
materially different claims to put in front of counsel.

A CONTROL THAT REPORTS ENABLED AND CANNOT MATCH IS WORSE THAN ONE THAT REPORTS
DISABLED. It produces the paperwork of screening without the screening: a reviewer
reading `requirements: {"sanctions_check": True}` in the result reasonably
concludes the corridor was screened.

WHY NOT JUST POPULATE A LIST. Writing sanctioned addresses from memory would
fabricate the exact class of data this audit exists to remove — and a WRONG entry
on a sanctions list blocks a legitimate party, which is its own serious harm. The
list must come from a real source. Until it does, the result says so.
"""

from __future__ import annotations

import pytest

from runtime.blockchain.services.cross_border.service import CrossBorderService

WITH_LIST = {"cross_border": {"sanctions_list": ["0xBAD"]}}


async def _check(config, sender="0xA", recipient="0xB", amount=100.0):
    service = CrossBorderService(config)
    return await service._compliance.check_compliance(
        sender, recipient, amount, "USD->EUR"
    )


async def test_an_unfed_screen_reports_that_it_did_not_screen():
    """THE LOAD-BEARING ASSERTION, on the shipped config."""
    result = await _check({})

    assert result["sanctions_screened"] is False
    assert "sanctions_screening_unavailable" in result["flags"]
    assert "NOT SCREENED" in result["sanctions_disclosure"]
    assert "cross_border.sanctions_list" in result["sanctions_disclosure"], (
        "the disclosure must name the config key, or an operator cannot act on it"
    )


async def test_the_payment_is_not_silently_blocked_by_the_disclosure():
    """SCOPE PIN. Disclosing a missing screen must not become a refusal — that
    would take a labelling fix and turn it into an outage. The approval decision
    is unchanged; only the reporting is honest."""
    result = await _check({})

    assert result["approved"] is True


async def test_a_configured_screen_reports_itself_as_screened():
    """CONTROL IN THE OTHER DIRECTION. With a real list the disclosure must be
    ABSENT — an always-on warning trains readers to ignore it, the same failure
    as an over-firing detector."""
    result = await _check(WITH_LIST)

    assert result["sanctions_screened"] is True
    assert result["sanctions_disclosure"] is None
    assert "sanctions_screening_unavailable" not in result["flags"]


async def test_a_real_sanctions_hit_still_refuses():
    """THE CONTROL ITSELF, asserted intact. The disclosure work must not have
    weakened the enforcement it describes."""
    result = await _check(WITH_LIST, sender="0xBAD")

    assert result["approved"] is False
    assert "sanctioned" in result["reason"].lower()


async def test_a_sanctioned_recipient_is_refused_too():
    """Both directions of the screen — fixing one side and not its twin is how a
    correct fix reads as effective while half of it is missing."""
    result = await _check(WITH_LIST, recipient="0xBAD")

    assert result["approved"] is False
    assert "sanctioned" in result["reason"].lower()


async def test_the_sibling_controls_still_enforce():
    """THE PRECISION OF THE FINDING, pinned. If these ever stop firing, the
    claim changes from 'one control is unfed' to 'compliance is broken' — and the
    report says the former."""
    result = await _check({}, amount=50_000.0)

    assert result["approved"] is False
    assert "verification" in str(result.get("reason", "")).lower()


async def test_the_shipped_deployment_configures_no_sanctions_list():
    """THE MEASUREMENT BEHIND THE FINDING, pinned. If a list is ever configured
    by default, the disclosure stops firing on the main path and this file should
    be revisited rather than silently describing a deployment that changed."""
    service = CrossBorderService({})

    assert len(service._compliance._sanctions_list) == 0
