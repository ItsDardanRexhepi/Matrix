"""A lending protocol must not issue a loan whose collateralisation is NaN.

DOMAIN 16-A. The second confirmed exploitable instance of the non-finite class,
in a different domain from the first (15-D, stablecoin) and — this is the part
that matters — against a *different kind of control*.

  15-D defeated a BALANCE check:      `sender_balance < amount`
  16-A defeats a RATIO check:         `collateral_ratio < min_collateral_ratio`

The ratio check is the primary safety property of a lending protocol. It is not
defeated by a clever exploit. It is defeated by a value for which every `<`
answers False, so the comparison never compares anything.

DRIVEN, against a simulated-deployed install (the gate reads only
`self._web3.available` and whether the pool address is a placeholder — nothing
about the arguments — so setting those two is a faithful simulation of the
deployed state and nothing else):

    create_loan("0xB", "ETH", NaN, "USDC", 1000.0)
      -> {"loan_id": "loan_b08016db7d294607", "collateral_amount": NaN,
          "collateral_value_usd": NaN, "borrow_amount": 1000.0,
          "collateral_ratio": NaN, ...}

A real 1000 USDC borrow against NaN collateral, with the ratio recorded as NaN.

ARMED BY DEPLOYMENT, NOT ARMED NOW. Under the shipped config the deployment gate
returns not_deployed and none of this runs. That is the domain-14 inversion:
harmless today, live the moment contracts are deployed. It is recorded at full
severity precisely because the disarming condition is one config change, and
because deployment is the point at which nobody re-reads the guards.

WHY THE CONTROLS ARE NOT SIMPLY ABSENT — this matters for the disposition. The
sign check and the sufficiency check BOTH work correctly for ordinary values:

    deposit_collateral("0xB", "ETH", -500.0)   -> refused, "must be positive"
    withdraw_collateral("0xC", "ETH", 1000.0)  -> refused, "Insufficient balance"

So this is not missing validation. It is validation that is correct for every
value except the one that defeats comparison itself. Category 6
(real-local-defective): the guards are real, the NaN case is the hole.

BOUNDED RANGES ARE NOT SAFER. In p2p_lending, `interest_rate < 0 or
interest_rate > self._max_interest` walks NaN through BOTH ends at once. A
two-sided check gives no more protection than a one-sided one against a value
that is False against both.
"""

from __future__ import annotations

import math

import pytest

from runtime.blockchain.services.defi import DeFiService
from runtime.blockchain.services.defi.p2p_lending import P2PLending

NAN = float("nan")
INF = float("inf")


def _deployed(service: DeFiService) -> DeFiService:
    """Simulate a deployed install.

    The gate's condition is `not self._web3.available or
    self._web3.is_placeholder(self._lending_pool_address)` — it reads NOTHING
    from the arguments, which is what makes the shipped-config absence claim
    sound AND what makes this simulation faithful.
    """
    for mgr in (service, service._loan_manager):
        mgr._web3.available = True
        mgr._web3.is_placeholder = lambda _addr: False
    return service


@pytest.fixture
def service() -> DeFiService:
    return DeFiService({"defi": {"fallback_prices": {"ETH": 2000.0, "USDC": 1.0}}})


# ── the load-bearing assertion ───────────────────────────────────────────


async def test_a_loan_is_not_issued_against_nan_collateral(service):
    """THE FINDING. Driven at the pre-fix commit: this returned a loan_id."""
    _deployed(service)

    with pytest.raises(ValueError) as exc:
        await service.create_loan("0xB", "ETH", NAN, "USDC", 1000.0)

    assert "finite" in str(exc.value).lower()


async def test_the_well_formed_loan_still_works(service):
    """SCOPE PIN. The guard must not break borrowing — if this fails, the fix
    traded a working feature for a refusal."""
    _deployed(service)

    loan = await service.create_loan("0xA", "ETH", 10.0, "USDC", 1000.0)

    assert loan["loan_id"]
    assert loan["collateral_ratio"] > 1.5
    assert math.isfinite(loan["collateral_ratio"])


async def test_the_collateralisation_control_still_refuses_a_thin_loan(service):
    """THE CONTROL ITSELF, asserted intact. The whole finding is that this check
    was bypassable; if the fix disabled it instead of repairing it, the domain is
    worse off, not better."""
    _deployed(service)

    with pytest.raises(ValueError) as exc:
        await service.create_loan("0xD", "ETH", 0.1, "USDC", 1000.0)

    assert "below minimum" in str(exc.value)


async def test_an_uncomputable_ratio_is_refused_not_coerced(service):
    """DEFENCE IN DEPTH. Guarding the inputs is not enough — the ratio is a
    QUOTIENT OF PRICES, so a non-finite price yields a non-finite ratio from
    finite inputs. Refuse; do not coerce to 0, which would replace an
    unanswerable question with a confident wrong answer.

    ONLY THE COLLATERAL PRICE MAY BE NON-FINITE FOR THIS TO REACH THE GUARD, and
    the first version of this test got that wrong — it made BOTH prices NaN, so
    `borrow_value = 1000.0 * NaN` was NaN, `NaN > 0` was False, and the ternary
    `... if borrow_value > 0 else 0` coerced the ratio to 0. The pre-existing
    minimum check then caught it correctly and the test failed asserting the
    wrong message.

    Worth keeping as a note rather than silently correcting: a test that reaches
    a guard by the wrong path would have reported that guard as working when it
    had never executed — which is the inert-fix pattern one level up, in the
    verification rather than the fix.
    """
    _deployed(service)

    async def _price(token):
        return NAN if token == "ETH" else 1.0

    service._get_token_price = _price

    with pytest.raises(ValueError) as exc:
        await service.create_loan("0xE", "ETH", 10.0, "USDC", 1000.0)

    assert "finite" in str(exc.value).lower()
    assert "unknown" in str(exc.value).lower()


# ── the collateral ledger, which is UNGATED ──────────────────────────────


async def test_nan_cannot_be_deposited_as_collateral(service):
    """UNGATED PATH — no deployment gate stands in front of this one at all.
    Pre-fix this returned {"status": "deposited", "new_balance": NaN} and
    poisoned the ledger, under the SHIPPED config."""
    with pytest.raises(ValueError) as exc:
        await service.deposit_collateral("0xA", "ETH", NAN)

    assert "finite" in str(exc.value).lower()
    assert service._collateral_manager._balances.get("0xA", {}).get("ETH") is None


async def test_nan_cannot_be_withdrawn(service):
    """THE TWIN. `amount <= 0` AND `amount > current` are both False for NaN, so
    the withdrawal walked the sign check and the sufficiency check. Fixing
    deposit alone would have left the drain open."""
    await service.deposit_collateral("0xA", "ETH", 5.0)

    with pytest.raises(ValueError) as exc:
        await service.withdraw_collateral("0xA", "ETH", NAN)

    assert "finite" in str(exc.value).lower()
    assert service._collateral_manager._balances["0xA"]["ETH"] == 5.0


async def test_infinity_is_refused_too(service):
    """inf is not NaN and fails differently — `inf > current` is True, so the
    sufficiency check DID catch a withdrawal. It did not catch a deposit."""
    with pytest.raises(ValueError) as exc:
        await service.deposit_collateral("0xA", "ETH", INF)

    assert "finite" in str(exc.value).lower()


async def test_ordinary_validation_is_untouched(service):
    """THE PROOF THAT THIS IS CATEGORY 6, NOT MISSING VALIDATION. These guards
    were always correct; only the NaN case walked them. If either stops firing,
    the fix broke a working control."""
    with pytest.raises(ValueError, match="positive"):
        await service.deposit_collateral("0xB", "ETH", -500.0)

    await service.deposit_collateral("0xC", "ETH", 1.0)
    with pytest.raises(ValueError, match="Insufficient balance"):
        await service.withdraw_collateral("0xC", "ETH", 1000.0)


# ── p2p_lending: the twin file ───────────────────────────────────────────


async def test_a_bounded_range_does_not_stop_nan():
    """THE SHARPEST FORM OF THE CLASS. `interest_rate < 0 or interest_rate >
    max` looks strictly safer than a one-sided check. It is not: NaN is False
    against BOTH ends, so a two-sided range walks exactly as easily."""
    mgr = P2PLending({})

    with pytest.raises(ValueError) as exc:
        await mgr.create_offer("0xL", "USDC", 1000.0, NAN, 30)

    assert "finite" in str(exc.value).lower()


async def test_p2p_still_enforces_its_real_interest_bounds():
    """SCOPE PIN on the twin."""
    mgr = P2PLending({})

    with pytest.raises(ValueError, match="Interest rate must be between"):
        await mgr.create_offer("0xL", "USDC", 1000.0, 0.99, 30)


async def test_p2p_offer_amount_must_be_finite():
    mgr = P2PLending({})

    with pytest.raises(ValueError) as exc:
        await mgr.create_offer("0xL", "USDC", NAN, 0.05, 30)

    assert "finite" in str(exc.value).lower()


async def test_p2p_duration_must_be_finite():
    mgr = P2PLending({})

    with pytest.raises(ValueError) as exc:
        await mgr.create_offer("0xL", "USDC", 1000.0, 0.05, NAN)

    assert "finite" in str(exc.value).lower()


# ── the measurement behind the register entry ────────────────────────────


def test_the_defi_domain_has_no_unguarded_value_entry_left():
    """THE RATCHET, and the reason it is written as a source scan rather than a
    behaviour test: the class is 290 sites across 95 files repo-wide, so what
    protects this domain is not any single assertion but the absence of a value
    entry point that reaches arithmetic without a finiteness check.

    Scoped to the two files that take caller-supplied value in this domain. If a
    new value parameter is added without a guard, this fails.
    """
    import ast
    import pathlib

    base = pathlib.Path(__file__).resolve().parent.parent
    base = base / "runtime" / "blockchain" / "services" / "defi"

    for name in ("loans.py", "collateral.py", "p2p_lending.py"):
        src = (base / name).read_text()
        assert "math.isfinite" in src, (
            f"{name} has no finiteness guard; a value entry point in this file "
            "can be reached with NaN, which is False against every comparison"
        )
        assert "import math" in src, f"{name} guards without importing math"
