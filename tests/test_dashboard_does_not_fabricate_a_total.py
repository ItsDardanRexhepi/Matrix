"""The dashboard must not print a portfolio total nobody computed.

SECOND INSTANCE OF THE FABRICATED-ZERO CLASS. `total_value_usd` was initialised
to `0.0` in `aggregate_portfolio` and **never assigned again** — the only two
references in the package are that initialiser and the formatter that renders it.
So the summary read "Your portfolio is worth approximately $0.00." over real
holdings, for every user, always.

The first instance was the APY field in the SAME FILE. Its fix (NEW-96) left a
comment that reads, in part: *"0.0 WAS NEVER A SAFE DEFAULT … Defaulting to 0.0
forced it to print 'Your current annual yield is 0.0%', a fabricated yield claim …
None restores it."* That reasoning applied verbatim to `total_value_usd`, one
field over in the same dict, and was not extended to it. The surface rule —
when a finding names a field, check every field that renders to the same surface —
would have caught it at the time.

WHY `None` AND NOT A SUM. `_services` is empty under the shipped config (the
NEW-59 gap, on the register), so computing a total would produce an equally-wrong
0.0 that is HARDER to spot — a real computation over no data. The fabricated zero
and the empty aggregator are the same defect from two ends. The honest display is
correct because the data is not there, and stays correct once it is.

ASSERTIONS ARE ON RENDERED TEXT, not on the field. The deliverable is a sentence
a user reads; a field-level check would pass while the formatter still printed
something false.
"""

from __future__ import annotations

import pytest

from runtime.blockchain.services.dashboard.formatters import PlainEnglishFormatter


@pytest.fixture
def formatter() -> PlainEnglishFormatter:
    return PlainEnglishFormatter()


def test_an_uncomputed_total_is_not_rendered_as_a_dollar_figure(formatter):
    """THE LOAD-BEARING ASSERTION. `None` means nobody computed it, so the
    sentence must not appear at all."""
    text = formatter.format_portfolio_summary({
        "total_value_usd": None,
        "tokens": [{"symbol": "ETH"}],
        "nfts": [],
        "staking_positions": [],
        "defi_positions": [],
    })

    assert "$" not in text, f"a dollar figure was rendered from no data: {text!r}"
    assert "worth approximately" not in text
    assert "1 token" in text, "the holdings the platform DOES know were dropped"


def test_the_empty_portfolio_says_something_true_rather_than_nothing(formatter):
    """With no total and no holdings, `". ".join([]) + "."` would render a bare
    "." — a summary that says nothing while looking like it said something."""
    text = formatter.format_portfolio_summary({
        "total_value_usd": None,
        "tokens": [], "nfts": [], "staking_positions": [], "defi_positions": [],
    })

    assert text == "No holdings found for this account."
    assert text != "."


def test_a_real_total_is_still_rendered(formatter):
    """SCOPE PIN. Only the FABRICATED total is suppressed. Once something
    actually computes a value, it must display — otherwise this fix trades a
    false number for a missing one."""
    # Value kept UNDER 1000 deliberately: `_format_amount` switches to "1.23K"
    # at >= 1000, and the first version of this test asserted "$1,234.50" and
    # failed against BOTH the fixed and unfixed code — a test bug, not a
    # behaviour change. Caught because it failed after the fix as well as before.
    text = formatter.format_portfolio_summary({
        "total_value_usd": 123.45,
        "tokens": [], "nfts": [], "staking_positions": [], "defi_positions": [],
    })

    assert "worth approximately $123.45" in text


def test_a_genuine_zero_still_renders(formatter):
    """THE DISTINCTION THAT MAKES `None` THE RIGHT SENTINEL. A computed 0.0 is a
    FACT — the account really is worth nothing — and must display. Only the
    uncomputed case is silent. Using 0.0 as the sentinel would have made these
    two indistinguishable, which is what caused the defect."""
    text = formatter.format_portfolio_summary({
        "total_value_usd": 0.0,
        "tokens": [], "nfts": [], "staking_positions": [], "defi_positions": [],
    })

    assert "worth approximately $0.00" in text


async def test_the_shipped_dashboard_does_not_quote_a_total():
    """END TO END, through the real service under the shipped config — the layer
    the field-level check cannot see. Before the fix this rendered
    'Your portfolio is worth approximately $0.00.'"""
    from runtime.blockchain.services.registry import ServiceRegistry

    result = await ServiceRegistry({}).get("dashboard").get_overview("0xTEST")

    assert result["portfolio"]["total_value_usd"] is None
    assert "$" not in result["summary"], (
        f"the shipped dashboard quotes a figure it never computed: "
        f"{result['summary']!r}"
    )


def test_the_aggregator_still_never_computes_a_total():
    """THE FINDING BEHIND THE FINDING, pinned so it cannot be silently 'fixed'
    by assigning a wrong value.

    Nothing sums `total_value_usd`. That is a REAL GAP, tracked on the register
    with the NEW-59 aggregator wiring, not something to paper over with a
    computation that would run over an empty `_services`. If a real summation
    ever lands, this test fails and should be replaced by one that checks the
    arithmetic.
    """
    import pathlib

    source = (
        pathlib.Path(__file__).resolve().parent.parent
        / "runtime" / "blockchain" / "services" / "dashboard" / "aggregator.py"
    ).read_text()

    # DICT LITERALS BIND WITH ':', NOT '='. The first version of this scan
    # required "=" in the line and therefore matched NOTHING — it reported zero
    # assignments and failed identically before and after the fix. A scan whose
    # pattern cannot match the syntax it targets reports "clean" for the same
    # reason it reports "broken": it never looked.
    bindings = [
        line.strip() for line in source.splitlines()
        if '"total_value_usd"' in line and not line.strip().startswith("#")
    ]

    assert len(bindings) == 1, (
        "total_value_usd is bound in more than one place — if a real summation "
        f"landed, replace this test with an arithmetic check: {bindings}"
    )
    assert "None" in bindings[0], (
        f"the initialiser no longer binds None: {bindings[0]}"
    )
