"""NEW-86/87/88 — the remittance twin, the bridge fabrication, the feed lie.

Three findings that share one operation's surface, so they ship together.

  NEW-86  `remit` DELEGATES to `send_payment`. It was the compliance-free twin
          of a compliance-bearing sibling: zero awaits, uuid + "sent", and it
          never converted currency at all — reporting net_amount in the SOURCE
          currency for corridors the conversion layer cannot price.
  NEW-87  `bridge_transfer` DISABLED. It never bridged anything and could not
          be repointed to the real CCIP implementation without inventing a
          chain-selector table and a token-address table.
  NEW-88  `cross_chain_bridge -> "bridge_completed"` REMOVED from
          ACTION_TO_FEED_EVENT. Independent of the fabrication: the method's
          own literal was "bridging" — in-progress — and the router upgraded
          it to COMPLETED and published that to the public social feed.

EACH INHERITED GUARD IS ITS OWN ASSERTION. A delegation that inherits five of
six guards is a delegation that LOOKS complete, so "it delegates" is not the
property under test — "it refuses in each of the seven ways its sibling
refuses" is.

SCENARIO COVERAGE:
    sanctioned sender        -> test_remit_inherits_sanctions_screening
    above KYC threshold      -> test_remit_inherits_the_kyc_threshold
    over the cap             -> test_remit_inherits_the_max_payment_cap
    negative / zero          -> test_remit_inherits_amount_validation
    missing counterparty     -> test_remit_inherits_counterparty_validation
    unpriceable corridor     -> test_remit_inherits_real_fx_conversion
    custody vocabulary       -> test_remit_inherits_the_honest_custody_claim
    caller-chosen corridor   -> test_a_caller_supplied_corridor_cannot_pick_its_own_thresholds
    legacy callers           -> test_the_legacy_id_key_still_resolves
"""

from __future__ import annotations

import ast
import inspect

import pytest

from runtime.blockchain.services.cross_border.service import CrossBorderService

SANCTIONED = {"cross_border": {"sanctions_list": ["0xBAD"]}}


# ── NEW-86: every guard, one assertion each ──────────────────────────────


async def test_remit_inherits_sanctions_screening():
    """SCENARIO: sanctioned sender. Pre-fix: "sent". The sanctions branch was
    not merely weak on this path — it was absent."""
    svc = CrossBorderService(SANCTIONED)
    result = await svc.remit("0xBAD", "0xB", 100.0, "USD", "EUR")

    assert result["status"] == "compliance_hold"
    assert "sanctions_hit" in result["compliance"]["flags"]


async def test_remit_inherits_the_kyc_threshold():
    """SCENARIO: $5,000 USD->EUR, above the $1,000 max_without_id."""
    svc = CrossBorderService({})
    result = await svc.remit("0xA", "0xB", 5000.0, "USD", "EUR")

    assert result["status"] == "compliance_hold"
    assert "kyc_required" in result["compliance"]["flags"]


async def test_remit_inherits_the_max_payment_cap():
    """SCENARIO: $10,000,000 against a $1,000,000 cap. Pre-fix: "sent"."""
    svc = CrossBorderService({})
    with pytest.raises(ValueError, match="exceeds maximum"):
        await svc.remit("0xA", "0xB", 10_000_000.0, "USD", "EUR")


async def test_remit_inherits_amount_validation():
    """SCENARIO: negative and zero. Pre-fix a NEGATIVE remittance returned
    "sent" — the fee arithmetic simply ran on a negative number."""
    svc = CrossBorderService({})
    for bad in (-5.0, 0.0):
        with pytest.raises(ValueError, match="must be positive"):
            await svc.remit("0xA", "0xB", bad, "USD", "EUR")


async def test_remit_inherits_counterparty_validation():
    """SCENARIO: absent sender or recipient."""
    svc = CrossBorderService({})
    for sender, recipient in (("", "0xB"), ("0xA", "")):
        with pytest.raises(ValueError, match="required"):
            await svc.remit(sender, recipient, 100.0, "USD", "EUR")


async def test_remit_inherits_real_fx_conversion():
    """SCENARIO: the defect that had no analogue in its sibling.

    `remit` never converted. It reported net_amount in the SOURCE currency
    while declaring the remittance sent — and it accepted corridors the
    conversion layer cannot price at all (USD->MXN raises inside get_quote).
    """
    svc = CrossBorderService({})
    result = await svc.remit("0xA", "0xB", 500.0, "USD", "EUR")

    assert result["converted_amount"] > 0
    assert result["exchange_rate"] > 0
    assert result["destination_currency"] == "EUR"
    assert result["converted_amount"] != result["net_source_amount"], (
        "the amount was not converted — this is the pre-fix behaviour"
    )

    # An unpriceable corridor must now raise rather than report "sent".
    with pytest.raises(Exception):
        await svc.remit("0xA", "0xB", 500.0, "USD", "MXN")


async def test_remit_inherits_the_honest_custody_claim():
    """SCENARIO: the NEW-85 vocabulary must flow through the delegation.

    This is why NEW-85 shipped first: delegating into a method that still
    said "completed" would have inherited a lie along with the guards.
    """
    svc = CrossBorderService({})
    result = await svc.remit("0xA", "0xB", 500.0, "USD", "EUR")

    assert result["status"] == "recorded_unsettled"
    assert result["value_moved"] is False
    assert result["settled"] is False
    assert "has not been debited" in result["disclosure"]


async def test_remit_inherits_attestation():
    """The seventh guard: the delegated path reaches the attestation call."""
    svc = CrossBorderService({})
    seen = []
    real = svc._attest_payment

    async def spy(payment):
        seen.append(payment)
        return await real(payment)

    svc._attest_payment = spy
    await svc.remit("0xA", "0xB", 500.0, "USD", "EUR")

    assert seen, "the delegated path never reached attestation"


async def test_a_caller_supplied_corridor_cannot_pick_its_own_thresholds():
    """SCENARIO: the escalation the delegation could have introduced.

    `remit` accepts a `corridor` argument. If it were honoured, a caller
    could name a corridor with a laxer max_without_id than their real
    currency pair and buy themselves a higher KYC-free ceiling. It is
    ignored: send_payment derives the corridor from the currency pair.
    """
    svc = CrossBorderService({})
    result = await svc.remit(
        "0xA", "0xB", 5000.0, "USD", "JPY", corridor="USD->EUR",
    )
    assert result["compliance"]["corridor"] == "USD->JPY", (
        "a caller-supplied corridor selected the compliance thresholds"
    )


async def test_the_legacy_id_key_still_resolves():
    """Delegation must not silently break existing callers reading `id`."""
    svc = CrossBorderService({})
    result = await svc.remit("0xA", "0xB", 500.0, "USD", "EUR")
    assert result["id"] == result["payment_id"]


def test_remit_has_no_body_of_its_own_left():
    """Proves DELEGATION, not a parallel reimplementation that happens to
    agree today and drifts tomorrow — the NEW-67 lesson."""
    fn = ast.parse(inspect.getsource(CrossBorderService.remit).strip()).body[0]
    if (
        fn.body and isinstance(fn.body[0], ast.Expr)
        and isinstance(fn.body[0].value, ast.Constant)
    ):
        fn.body = fn.body[1:]
    live = ast.unparse(fn)

    assert "self.send_payment" in live
    assert "uuid" not in live, "remit still mints its own id"
    assert "'sent'" not in live and '"sent"' not in live
    assert "_fee_pct" not in live, "remit still computes its own fee"


# ── NEW-87: the bridge ───────────────────────────────────────────────────


async def test_bridge_transfer_refuses_and_moves_nothing():
    """SCENARIO: a well-formed bridge request. Pre-fix: "bridging"."""
    svc = CrossBorderService({})
    result = await svc.bridge_transfer(
        "0xA", "0xB", 5000.0, "ethereum", "polygon", "USDC",
    )

    assert result["status"] == "error"
    assert result["value_moved"] is False
    assert result["disabled_by"] == "NEW-87"
    assert "never moved value" in result["error"]
    assert result["requested"]["amount"] == 5000.0, (
        "the refusal must echo what was asked, so a caller can see it was heard"
    )


async def test_the_bridge_no_longer_writes_to_the_payment_store():
    """Pre-fix it wrote `_payments[bridge_id]`, so `get_payment` would report
    a bridge as a real payment record."""
    svc = CrossBorderService({})
    await svc.bridge_transfer("0xA", "0xB", 5000.0, "ethereum", "polygon")
    assert svc._payments == {}


def test_the_disable_names_the_honest_alternative_and_why_repointing_failed():
    """A disable states what would license lifting it. This one must also say
    why the OBVIOUS fix — delegate to CCIP, as remit delegates to send_payment
    — was not available, or the next reader will simply try it."""
    doc = inspect.getdoc(CrossBorderService.bridge_transfer) or ""
    assert "LIFTING CONDITION" in doc
    for clause in ("chain-selector", "ERC-20", "base units", "DERIVED"):
        assert clause in doc, f"lifting condition missing clause: {clause}"
    assert "bridge_token_ccip" in doc


# ── NEW-88: the feed mapping, independent of both ────────────────────────


def test_the_bridge_feed_event_is_gone():
    """SCENARIO: the router upgrading an in-progress claim to a completed one.

    Independent of the fabrication — it survives fixing the method, since even
    an honest bridge returning "submitted" would have been announced finished.
    """
    from runtime.blockchain.services.service_dispatcher import ACTION_TO_FEED_EVENT

    assert "cross_chain_bridge" not in ACTION_TO_FEED_EVENT
    assert "bridge_completed" not in ACTION_TO_FEED_EVENT.values()


# ── The catalog inversion (NEW-88b) ──────────────────────────────────────


def test_the_fabrication_is_no_longer_the_only_advertised_bridge():
    """THE INVERSION, made load-bearing.

    Six honest CCIP/Hyperlane/Wormhole/Axelar/Stargate bridges were catalogued
    available=False while the ONE that bridged nothing was available=True — the
    fabrication was what clients and the model were offered.
    """
    from runtime.capabilities import catalog

    bridges = {
        c["id"]: c.get("available", True)
        for c in catalog.CAPABILITIES
        if c.get("category") == "bridging"
    }
    assert bridges, "the bridging category vanished"
    assert bridges.get("cross_chain_bridge") is False

    advertised = [k for k, v in bridges.items() if v]
    assert not advertised, (
        f"a bridging capability is advertised as available: {advertised}. "
        "If a real one has been configured this is correct — update this test "
        "deliberately rather than letting a fabrication back in."
    )


def test_d7_no_longer_flags_either_method():
    """Both must leave the fake-delivery shape, or the fixes did not take."""
    from tests.test_fake_delivery_detector import find_fake_delivery

    current = find_fake_delivery()
    for name in ("remit", "bridge_transfer"):
        assert f"services/cross_border/service.py::CrossBorderService.{name}" \
            not in current, f"D7 still flags {name}"
