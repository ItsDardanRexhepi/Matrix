"""The sponsorship cap must meter what the EntryPoint can actually charge.

THE DEFECT. `_estimate_sponsorship_usd` priced a UserOperation as

    max_fee_per_gas * (callGasLimit + verificationGasLimit + preVerificationGas)

and its docstring called that "the ceiling the EntryPoint can charge the
paymaster". It is not. EntryPoint v0.6 — the revision this repo pins at
`contracts/lib/account-abstraction` — computes the prefund it takes from the
PAYMASTER as::

    uint256 mul = mUserOp.paymaster != address(0) ? 3 : 1;
    uint256 requiredGas = mUserOp.callGasLimit
                        + mUserOp.verificationGasLimit * mul
                        + mUserOp.preVerificationGas;
    requiredPrefund = requiredGas * mUserOp.maxFeePerGas;

(`contracts/core/EntryPoint.sol::_getRequiredPrefund`; the multiplier exists
because the verification limit also bounds the paymaster's postOp call, which
the security model may run twice.)

`/api/v1/paymaster/sign` only ever signs WITH a paymaster — it returns 503
before it reaches the estimate when no paymaster address is configured — so the
multiplier is always 3 on this path and the cap was metering a number that can
be less than half of the real reservable spend. The cap therefore authorised
more real spend than the operator configured: with the gas fields used below, a
$1.00/day cap let through an operation the EntryPoint can charge $1.44 for.

MEASURED on the tree before the fix — 6 failed, 2 passed:
  test_the_cap_denies_what_the_entrypoint_can_actually_charge   FAILED
      "the route signed a sponsorship worth $1.44 of reservable gas against a
       $1.00 cap (HTTP 200) — the cap was metering $0.64"
  test_the_estimate_is_the_v06_prefund_not_the_naive_sum        FAILED
  test_without_a_paymaster_the_multiplier_is_one                FAILED
  test_overflowing_and_missing_fields_do_not_crash_the_meter    FAILED
  test_pricing_is_rounded_the_same_way_the_route_prices_it      FAILED
  test_the_formula_matches_the_pinned_entrypoint_source         FAILED
      (the last five: gateway.paymaster had no required_prefund_wei)
  test_a_request_under_the_real_prefund_still_signs             passed
  test_an_unconfigured_cap_still_prices_nothing                 passed
The two that passed before are scope pins, and they are counted here as such:
they guard the shape of the fix, not the defect. After the fix all eight pass,
and the source-pinned one reads the multiplier out of the upstream contract
rather than out of anything this change wrote.

One existing test moved with the arithmetic:
test_paymaster_sponsors_what_it_signs.py::test_the_daily_cap_is_per_address...
priced a request at 321,000 gas and set its cap at $0.50. The request is 721,000
gas. Its cap is now $1.00 and the property it pins — one address crosses, a
fresh address does not — is unchanged.
"""

from __future__ import annotations

import re
import subprocess
from pathlib import Path

import pytest

pytest.importorskip("eth_account")

from tests.test_gateway import _build_mock_server

SIGNER_KEY = "0x" + hex(0xA11CE)[2:].rjust(64, "0")
PAYMASTER = "0x00000000000000000000000000000000caFe0001"
SENDER = "0x000000000000000000000000000000000000dEaD"

# The gas fields every test in this file uses, and the two prices they produce.
CALL_GAS = 100_000
VERIFICATION_GAS = 200_000
PRE_VERIFICATION_GAS = 21_000
MAX_FEE_WEI = 1_000_000_000          # 1 gwei
ETH_USD = 2_000.0

# What the old arithmetic charged the cap:  321_000 gas -> $0.642
NAIVE_USD = (CALL_GAS + VERIFICATION_GAS + PRE_VERIFICATION_GAS) * MAX_FEE_WEI / 1e18 * ETH_USD
# What EntryPoint v0.6 reserves from the paymaster: 721_000 gas -> $1.442
TRUE_USD = (CALL_GAS + 3 * VERIFICATION_GAS + PRE_VERIFICATION_GAS) * MAX_FEE_WEI / 1e18 * ETH_USD

# A cap that sits between them: the old estimate is under it, the real one is over.
CAP_USD = 1.00

_BODY = {
    "sender": SENDER, "nonce": 7, "init_code": "", "call_data": "0x010203",
    "call_gas_limit": CALL_GAS, "verification_gas_limit": VERIFICATION_GAS,
    "pre_verification_gas": PRE_VERIFICATION_GAS,
    "max_fee_per_gas": MAX_FEE_WEI, "max_priority_fee_per_gas": MAX_FEE_WEI,
    "chain_id": 84532, "valid_until": 2000000000, "valid_after": 1000000000,
}


def _config(tmp_path, cap):
    return {
        "platform": "The Matrix", "memory_dir": str(tmp_path / "m"),
        "workspace": str(tmp_path), "timezone": "UTC",
        "model": {"provider": "ollama", "providers": {}},
        "agents": {"neo": {"enabled": True}},
        "gateway": {"api_key": "", "rate_limit_rpm": 60, "rate_limit_burst": 10},
        "security": {},
        "database": {"path": str(tmp_path / "matrix.db")},
        "blockchain": {"chain_id": 84532},
        "paymaster": {"address": PAYMASTER, "signer_key": SIGNER_KEY,
                      "policy": {"daily_cap_usd": cap}},
    }


@pytest.fixture
def fixed_price(monkeypatch):
    """A live quote without a network — same idiom as the sponsorship tests."""
    class _FixedPrice:
        def __init__(self, *a, **kw): pass
        async def eth_usd(self, **kw): return {"price": ETH_USD, "source": "test"}

    monkeypatch.setattr("runtime.blockchain.price_feed.PriceFeed", _FixedPrice)
    return _FixedPrice


async def _client(aiohttp_client, tmp_path, cap):
    server = _build_mock_server(_config(tmp_path, cap))
    server._app_attest = None
    server._security_backend = "noop"
    return await aiohttp_client(server.create_app())


# ── the defect, driven through the route ──────────────────────────────────

@pytest.mark.asyncio
async def test_the_cap_denies_what_the_entrypoint_can_actually_charge(
        aiohttp_client, tmp_path, fixed_price):
    """DEFECT-PROVER. One request, a $1.00 daily cap, and an operation the
    EntryPoint can charge $1.44 for. Before the fix the route signed it."""
    assert NAIVE_USD < CAP_USD < TRUE_USD, "the fixture no longer straddles the cap"

    client = await _client(aiohttp_client, tmp_path, CAP_USD)
    r = await client.post("/api/v1/paymaster/sign", json=_BODY)

    assert r.status == 403, (
        f"the route signed a sponsorship worth ${TRUE_USD:.2f} of reservable "
        f"gas against a ${CAP_USD:.2f} cap (HTTP {r.status}) — the cap was "
        f"metering ${NAIVE_USD:.2f}, the sum without the paymaster multiplier")
    body = await r.json()
    assert body["code"] == "daily_cap_exceeded", body
    assert body["policy"]["est_usd"] == pytest.approx(TRUE_USD, rel=1e-9), (
        "the denial is honest about the number it metered")


@pytest.mark.asyncio
async def test_a_request_under_the_real_prefund_still_signs(
        aiohttp_client, tmp_path, fixed_price):
    """The complement — the fix must not deny everything. A cap above the real
    prefund still signs, so the test above is measuring the arithmetic and not
    a route that stopped working."""
    client = await _client(aiohttp_client, tmp_path, TRUE_USD * 2)
    r = await client.post("/api/v1/paymaster/sign", json=_BODY)
    assert r.status == 200, await r.text()
    assert (await r.json())["paymasterAndData"].startswith("0x")


@pytest.mark.asyncio
async def test_an_unconfigured_cap_still_prices_nothing(
        aiohttp_client, tmp_path, monkeypatch):
    """SCOPE PIN. With no cap configured the route must not price the request
    at all — an operator with no policy sees exactly the previous behaviour,
    including no dependency on the price feed."""
    class _Exploding:
        def __init__(self, *a, **kw): pass
        async def eth_usd(self, **kw):
            raise AssertionError("an unconfigured cap must not consult the price feed")

    monkeypatch.setattr("runtime.blockchain.price_feed.PriceFeed", _Exploding)
    client = await _client(aiohttp_client, tmp_path, None)
    r = await client.post("/api/v1/paymaster/sign", json=_BODY)
    assert r.status == 200, await r.text()


# ── the formula itself ────────────────────────────────────────────────────

def test_the_estimate_is_the_v06_prefund_not_the_naive_sum():
    """DEFECT-PROVER, arithmetic half. Fails on the old sum by construction:
    the naive total is asserted NOT to be the answer."""
    from gateway.paymaster import required_prefund_wei

    got = required_prefund_wei(
        call_gas_limit=CALL_GAS, verification_gas_limit=VERIFICATION_GAS,
        pre_verification_gas=PRE_VERIFICATION_GAS, max_fee_per_gas=MAX_FEE_WEI)

    assert got == (CALL_GAS + 3 * VERIFICATION_GAS + PRE_VERIFICATION_GAS) * MAX_FEE_WEI
    naive = (CALL_GAS + VERIFICATION_GAS + PRE_VERIFICATION_GAS) * MAX_FEE_WEI
    assert got != naive
    assert got - naive == 2 * VERIFICATION_GAS * MAX_FEE_WEI, (
        "the whole difference is the two extra verification limits the "
        "EntryPoint reserves for the paymaster's postOp calls")


def test_without_a_paymaster_the_multiplier_is_one():
    """The other branch of the same upstream line. The sign route never takes
    it — it 503s without a paymaster address — but the helper is the formula,
    and a formula that only knows one branch is a constant with a docstring."""
    from gateway.paymaster import required_prefund_wei

    assert required_prefund_wei(
        call_gas_limit=CALL_GAS, verification_gas_limit=VERIFICATION_GAS,
        pre_verification_gas=PRE_VERIFICATION_GAS, max_fee_per_gas=MAX_FEE_WEI,
        has_paymaster=False,
    ) == (CALL_GAS + VERIFICATION_GAS + PRE_VERIFICATION_GAS) * MAX_FEE_WEI


def test_overflowing_and_missing_fields_do_not_crash_the_meter():
    """A caller writes these numbers. Zero everywhere is zero, and absurd
    values price high rather than wrapping or raising — under-pricing is the
    failure mode the cap cannot tolerate."""
    from gateway.paymaster import required_prefund_wei

    assert required_prefund_wei(call_gas_limit=0, verification_gas_limit=0,
                                pre_verification_gas=0, max_fee_per_gas=0) == 0
    huge = required_prefund_wei(
        call_gas_limit=2**63, verification_gas_limit=2**63,
        pre_verification_gas=0, max_fee_per_gas=2**63)
    assert huge > 2**126, "Python ints do not wrap; the meter must see the size"


@pytest.mark.asyncio
async def test_pricing_is_rounded_the_same_way_the_route_prices_it(
        aiohttp_client, tmp_path, fixed_price):
    """§EB: the USD number the policy sees, read back out of the route's own
    denial, equals the prefund formula priced at the quote — computed here from
    the helper rather than copied from the handler."""
    from gateway.paymaster import required_prefund_wei

    wei = required_prefund_wei(
        call_gas_limit=CALL_GAS, verification_gas_limit=VERIFICATION_GAS,
        pre_verification_gas=PRE_VERIFICATION_GAS, max_fee_per_gas=MAX_FEE_WEI)
    expected = (wei / 1e18) * ETH_USD

    client = await _client(aiohttp_client, tmp_path, 0.0)   # cap 0 -> always denies
    r = await client.post("/api/v1/paymaster/sign", json=_BODY)
    assert r.status == 403
    assert (await r.json())["policy"]["est_usd"] == pytest.approx(expected, rel=1e-9)


# ── the formula, checked against the source it is derived from ────────────

_ENTRYPOINT_PATH = "contracts/core/EntryPoint.sol"


def _pinned_entrypoint_source() -> str:
    """The EntryPoint.sol this repo pins, read from the submodule if it is
    checked out and otherwise from the submodule's object store at the exact
    gitlink revision the superproject records. Returns "" when neither is
    available — the same posture as the OpenZeppelin-dependent tests here."""
    root = Path(__file__).resolve().parent.parent
    checked_out = root / "contracts/lib/account-abstraction" / _ENTRYPOINT_PATH
    if checked_out.exists():
        return checked_out.read_text()

    def _git(*args: str, cwd: Path = root) -> str:
        out = subprocess.run(("git",) + args, cwd=str(cwd),
                             capture_output=True, text=True)
        return out.stdout if out.returncode == 0 else ""

    rev = ""
    for line in _git("ls-tree", "HEAD", "contracts/lib/account-abstraction").splitlines():
        parts = line.split()
        if len(parts) >= 3 and parts[1] == "commit":
            rev = parts[2]
    if not rev:
        return ""
    common = _git("rev-parse", "--git-common-dir").strip()
    if not common:
        return ""
    module = (root / common) / "modules/contracts/lib/account-abstraction"
    if not module.exists():
        return ""
    return _git("--git-dir", str(module), "cat-file", "-p",
                f"{rev}:{_ENTRYPOINT_PATH}")


def test_the_formula_matches_the_pinned_entrypoint_source():
    """§EB — the multiplier is read out of the upstream contract this repo
    pins, not out of the module under test. If the pin ever moves to a revision
    that computes the prefund differently, this fails instead of silently
    letting the cap drift back under the real number."""
    source = _pinned_entrypoint_source()
    if not source:
        pytest.skip("the account-abstraction submodule is not available here")

    body = re.search(r"function _getRequiredPrefund\((.|\n)*?\n    \}", source)
    assert body, "upstream no longer has _getRequiredPrefund — re-derive the cap"
    text = body.group(0)

    mul = re.search(r"paymaster != address\(0\) \? (\d+) : (\d+)", text)
    assert mul, f"the paymaster multiplier is no longer a literal:\n{text}"

    from gateway.paymaster import PAYMASTER_VERIFICATION_GAS_MULTIPLIER
    assert PAYMASTER_VERIFICATION_GAS_MULTIPLIER == int(mul.group(1))
    assert int(mul.group(2)) == 1, "the no-paymaster branch is no longer 1"
    assert "verificationGasLimit * mul" in text, (
        "upstream no longer multiplies the verification limit — the estimate "
        "this repo derives from that line must be re-derived")
