"""D-045 — the daily sponsorship cap the repo documents is actually enforced.

THE CLAIM, made in three places and read by no code:

  gateway/paymaster.py:15        "Sponsorship policy (action allowlist +
                                  per-identity daily USD cap) is enforced
                                  before signing"
  gateway/service_routes.py      the handler docstring repeats it
  openmatrix.config.json.example `"policy": {"allowed_actions": [...],
                                  "daily_cap_usd": 50}`

At 9819e06 the only policy key any code read was `allowed_actions`, in one
handler. `daily_cap_usd` appeared exactly once in the tree — in the example
config — with no reader. A grep across runtime/blockchain/ for a caller
identity, a cap, or an allowlist returned nothing, while 32 call sites in 13
files signed transactions with `bc["paymaster_private_key"]`.

So the platform's signer would approve sponsorship until the deposit was empty,
and the tool axis would sign whatever the model composed. This file is the
control set; each test below failed before the build.

(f) is the §CD test: it is not about any one site but about the class. A new
capability that constructs its own signer fails here rather than shipping
unmetered.
"""

from __future__ import annotations

import json
import os
import subprocess
import sys
import tempfile
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent


def _policy(tmp_path, **overrides):
    from runtime.blockchain.sponsorship import SponsorshipPolicy
    cfg = {
        "blockchain": {
            "paymaster": {
                "policy": {"allowed_actions": ["transfer", "swap"],
                           "daily_cap_usd": 50},
            },
        },
        "database": {"path": str(tmp_path / "spend.db")},
    }
    cfg["blockchain"]["paymaster"]["policy"].update(overrides)
    return SponsorshipPolicy.from_config(cfg)


# ── (a) a configured cap is enforced ──────────────────────────────────────

def test_a_a_request_crossing_the_daily_cap_is_denied(tmp_path):
    p = _policy(tmp_path)
    for _ in range(4):
        d = p.authorize_and_reserve("transfer", identity="0xabc", est_usd=12.0)
        assert d.allowed, d.reason
        p.commit(d.reservation_id)
    # 48 spent, cap 50 — a 12 dollar request crosses it.
    d = p.authorize_and_reserve("transfer", identity="0xabc", est_usd=12.0)
    assert not d.allowed, "the cap did not stop a request that crosses it"
    assert d.code == "daily_cap_exceeded"
    assert "50" in d.reason, f"the denial should name the cap: {d.reason!r}"


# ── (b) the cap is PER IDENTITY ───────────────────────────────────────────

def test_b_one_identity_exhausting_the_cap_does_not_deny_another(tmp_path):
    p = _policy(tmp_path)
    d = p.authorize_and_reserve("transfer", identity="0xabc", est_usd=50.0)
    assert d.allowed
    p.commit(d.reservation_id)
    assert not p.authorize_and_reserve(
        "transfer", identity="0xabc", est_usd=1.0).allowed
    other = p.authorize_and_reserve("transfer", identity="0xdef", est_usd=1.0)
    assert other.allowed, (
        "a shared bucket: one identity's spend denied a different identity")


# ── (c) the ledger is DURABLE — proven across a real process boundary ─────

def test_c_a_restart_does_not_refill_the_bucket(tmp_path):
    """§EB: an in-process assertion cannot prove durability — the object under
    test would be its own witness. Two separate interpreters share only the
    file, so only the file can carry the spend."""
    db = tmp_path / "spend.db"
    script = (
        "import sys, json;"
        "sys.path.insert(0, %r);"
        "from runtime.blockchain.sponsorship import SponsorshipPolicy;"
        "cfg={'blockchain':{'paymaster':{'policy':{'daily_cap_usd':50}}},"
        "'database':{'path':%r}};"
        "p=SponsorshipPolicy.from_config(cfg);"
        "d=p.authorize_and_reserve('transfer', identity='0xabc', est_usd=%s);"
        "print(json.dumps({'allowed': d.allowed, 'code': d.code}));"
        "p.commit(d.reservation_id) if d.allowed else None"
    ) % (str(ROOT), str(db), "%s")

    env = {**os.environ, "PYTHONPATH": str(ROOT), "PYTHONDONTWRITEBYTECODE": "1"}
    first = subprocess.run([sys.executable, "-c", script % "45.0"],
                           capture_output=True, text=True, env=env, cwd=str(ROOT))
    assert first.returncode == 0, first.stderr
    assert json.loads(first.stdout.strip().splitlines()[-1])["allowed"] is True

    second = subprocess.run([sys.executable, "-c", script % "10.0"],
                            capture_output=True, text=True, env=env, cwd=str(ROOT))
    assert second.returncode == 0, second.stderr
    out = json.loads(second.stdout.strip().splitlines()[-1])
    assert out["allowed"] is False, (
        "a fresh process got a fresh budget — the ledger is in memory, so a "
        "restart (or a second worker) refills the cap")
    assert out["code"] == "daily_cap_exceeded"


# ── (d) unattributable spend is denied, not waved through ─────────────────

def test_d_a_request_with_no_identity_is_denied_when_a_cap_is_configured(tmp_path):
    p = _policy(tmp_path)
    d = p.authorize_and_reserve("transfer", identity="", est_usd=1.0)
    assert not d.allowed, (
        "an anonymous request was sponsored — a per-identity cap cannot meter "
        "spend it cannot attribute, so this is an unbounded hole in the cap")
    assert d.code == "identity_required"


def test_d_no_cap_configured_preserves_todays_behaviour(tmp_path):
    """HR2 rollback: an operator who configured no cap sees no new denial."""
    from runtime.blockchain.sponsorship import SponsorshipPolicy
    p = SponsorshipPolicy.from_config(
        {"blockchain": {"paymaster": {"policy": {}}},
         "database": {"path": str(tmp_path / "spend.db")}})
    assert p.authorize_and_reserve("anything", identity="", est_usd=10_000).allowed


def test_d_an_action_outside_the_allowlist_is_denied(tmp_path):
    p = _policy(tmp_path)
    d = p.authorize_and_reserve("drain", identity="0xabc", est_usd=1.0)
    assert not d.allowed and d.code == "action_not_allowed"


# ── (e) the route binds sender to the caller, not to the body ─────────────

def test_e_paymaster_sign_does_not_take_the_sponsored_account_from_the_body():
    """One static key holder could request sponsorship for ANY account: the
    handler read `sender` straight out of the request body and never compared
    it to whoever was authenticated."""
    import inspect
    from gateway.service_routes import ServiceRoutes

    src = inspect.getsource(ServiceRoutes._handle_paymaster_sign)
    assert "_sponsorship_identity" in src, (
        "the handler does not resolve a caller identity at all")
    assert "authorize_and_reserve" in src, (
        "the handler does not consult the sponsorship policy")


# ── (f) the CLASS: no capability may build its own platform signer ────────

def test_f_no_blockchain_capability_constructs_a_platform_signer_directly():
    """§CD — the sweep found one site; the class was 32. A signer built outside
    `_platform_signer` is a signature no policy ever saw."""
    offenders: list[str] = []
    allowed = {"interface.py", "sponsorship.py"}
    for path in sorted((ROOT / "runtime" / "blockchain").rglob("*.py")):
        if path.name in allowed:
            continue
        for n, line in enumerate(path.read_text().splitlines(), 1):
            stripped = line.strip()
            if stripped.startswith("#"):
                continue
            if "Account.from_key(" in stripped:
                offenders.append(
                    f"{path.relative_to(ROOT)}:{n}: {stripped[:100]}")
    assert not offenders, (
        "platform signatures are produced outside the metered path:\n"
        + "\n".join(offenders))


# ── the OTHER branch, resolved rather than argued ─────────────────────────
#
# D-045 pre-registered this: the cap could be enforced and still be useless if
# the 32 tool-axis sites carry no identity, because a per-identity cap denies
# everything it cannot attribute. That would be correct-by-the-documents and
# destructive in practice. These two tests are how that branch is settled — by
# driving the real dispatcher and reading what the signer actually received,
# not by asserting that the wiring exists.

@pytest.mark.asyncio
async def test_the_dispatcher_binds_the_caller_all_the_way_to_the_signer(tmp_path,
                                                                         monkeypatch):
    """A real ToolDispatcher.dispatch -> a real capability -> _platform_signer.

    The capabilities take `**kwargs`, so the dispatcher's keyword injection
    cannot reach them; this is the proof the ContextVar does.
    """
    from runtime.blockchain.smart_contracts import SmartContracts
    from runtime.tools.dispatcher import ToolDispatcher

    seen: dict = {}

    class _FakeAccount:
        address = "0x" + "22" * 20

        def sign_transaction(self, tx):
            raise AssertionError("the probe never signs")

    monkeypatch.setattr("eth_account.Account.from_key",
                        staticmethod(lambda k: _FakeAccount()))

    class _FixedPrice:
        def __init__(self, *a, **kw): pass
        async def eth_usd(self, **kw): return {"price": 2000.0}

    monkeypatch.setattr("runtime.blockchain.price_feed.PriceFeed", _FixedPrice)

    cfg = {
        "blockchain": {
            "rpc_url": "https://example.invalid",
            "paymaster_private_key": "0x" + "11" * 32,
            "platform_wallet": "0x" + "22" * 20,
            "paymaster": {"policy": {"daily_cap_usd": 50}},
        },
        "database": {"path": str(tmp_path / "x.db")},
    }

    cap = SmartContracts(cfg)

    async def _probe(**kwargs):
        signer = await cap._platform_signer("smart_contracts.probe")
        seen["identity"] = signer._identity
        seen["metered"] = signer._metered
        return "ok"

    dispatcher = ToolDispatcher.__new__(ToolDispatcher)
    dispatcher.config = cfg
    dispatcher._tools = {"probe": _probe}
    dispatcher._schemas = []
    outcome = await dispatcher.dispatch(
        "probe", {}, caller_identity="0xCAFEBABE00000000000000000000000000000000")

    assert outcome.ok, getattr(outcome, "error", outcome)
    assert seen["metered"] is True
    assert seen["identity"] == "0xcafebabe00000000000000000000000000000000", (
        "the caller did not reach the signer: every tool-axis signature would "
        "be metered as anonymous, and a configured cap denies all of them")


@pytest.mark.asyncio
async def test_an_unbound_dispatch_stays_unbound(tmp_path, monkeypatch):
    """The complement: no identity in, no identity invented. A dispatch with no
    authenticated caller must not inherit one from a previous request."""
    from runtime.blockchain.sponsorship import resolve_caller_identity
    from runtime.tools.dispatcher import ToolDispatcher

    seen: list = []

    async def _probe(**kwargs):
        seen.append(resolve_caller_identity())
        return "ok"

    dispatcher = ToolDispatcher.__new__(ToolDispatcher)
    dispatcher.config = {}
    dispatcher._tools = {"probe": _probe}
    dispatcher._schemas = []
    await dispatcher.dispatch("probe", {}, caller_identity="0xabc")
    await dispatcher.dispatch("probe", {})

    assert seen == ["0xabc", ""], (
        f"identity leaked between dispatches: {seen}")


def test_changing_capitalisation_does_not_double_the_budget(tmp_path):
    """EIP-55 mixed case is a checksum, not a second identity. If the ledger
    keyed on the literal string, re-sending the same address checksummed would
    open a fresh $50."""
    p = _policy(tmp_path)
    addr_lower = "0x" + "ab" * 20
    addr_upper = "0x" + "AB" * 20
    d = p.authorize_and_reserve("transfer", identity=addr_lower, est_usd=50.0)
    assert d.allowed
    p.commit(d.reservation_id)
    again = p.authorize_and_reserve("transfer", identity=addr_upper, est_usd=1.0)
    assert not again.allowed, "capitalising the address bought a second budget"


def test_a_non_address_identity_keeps_its_case(tmp_path):
    """The complement: case-folding everything would merge two distinct user
    ids into one spender."""
    from runtime.blockchain.sponsorship import canonical_identity
    assert canonical_identity("User-A") == "User-A"
    assert canonical_identity("0x" + "AB" * 20) == "0x" + "ab" * 20


def test_an_unlisted_exemption_is_refused(tmp_path):
    """§CT — the exemption list is the control. Asking to skip metering under a
    name nobody reviewed is a denial, not a quiet pass."""
    from runtime.blockchain.sponsorship import (
        SponsorshipDenied, unmetered_platform_signer,
    )
    with pytest.raises(SponsorshipDenied):
        unmetered_platform_signer("0x" + "11" * 32, "something.invented")
