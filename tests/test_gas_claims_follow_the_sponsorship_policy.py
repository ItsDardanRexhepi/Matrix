"""What the platform tells people about gas follows what the sponsorship policy
actually does.

Since D-045 (f797b1d) the platform signer is metered: a per-identity rolling
24-hour USD cap, an action allowlist, a refusal when the cap would be crossed,
and nothing at all when no paymaster is configured. The copy never moved. The
Trinity system prompt, the capability map, docs/blockchain.md ("No exceptions.
No conditions. Ever."), README, the intro course, and — the part a user
actually receives — the dashboard, payments and cross-border tools all returned
"All gas fees covered by platform — users never pay" as data, whatever the
deployment was configured to do. The iOS bridge config reported
`gas_sponsorship: true` unconditionally.

Two kinds of control, neither keyed on the prose it judges:

  * RESPONSES are derived: each tool's gas statement must equal
    `describe_gas_policy(config)` for three configurations (no paymaster, a
    paymaster with a $50 cap, a paymaster with no cap), so a hardcoded string
    fails two of the three whatever it says.
  * PUBLISHED TEXT is checked only after the condition is MEASURED: a policy is
    built from a capped config and asked to authorise a request above the cap.
    Only because that is refused may no public surface promise unconditional
    sponsorship.

The first describer described the cap and forgot the rest of the policy it
claimed to mirror. Under the shipped example policy (allowed_actions
["transfer", "swap"], cap $50) it told a user "The platform pays gas for your
operations up to $50.00", while the signer refuses every platform-signed
capability, because those are metered under `<capability>.<method>` names that
list does not contain. Without a cap it reported the allowlist as
`sponsored_actions`, though MeteredSigner skips the policy entirely then. It
never mentioned the identity requirement, read the platform key under one of
the two names Web3Manager accepts, and Web3Manager.send_transaction — the
signer 14 registry services use — consulted no policy at all. Each of those is
now measured against the signer and SponsorshipPolicy, not asserted.
"""

from __future__ import annotations

import json
import re
import subprocess
from pathlib import Path

import pytest

from runtime.blockchain.sponsorship import SponsorshipPolicy


def describe_gas_policy(config):
    # Imported per call so each property below reports on its own rather than
    # the whole file failing to collect where the describer does not exist.
    from runtime.blockchain.sponsorship import describe_gas_policy as describe
    return describe(config)

ROOT = Path(__file__).resolve().parent.parent
KEY = "0x" + "11" * 32
ADDR = "0x" + "22" * 20

NO_PAYMASTER: dict = {"blockchain": {"rpc_url": "http://rpc.invalid"}}
CAPPED = {"blockchain": {"rpc_url": "http://rpc.invalid", "paymaster_private_key": KEY,
                         "paymaster": {"address": ADDR,
                                       "policy": {"daily_cap_usd": 50}}}}
UNCAPPED = {"blockchain": {"rpc_url": "http://rpc.invalid", "paymaster_private_key": KEY,
                           "paymaster": {"address": ADDR}}}
# The policy the public example config ships.
EXAMPLE_POLICY = {"allowed_actions": ["transfer", "swap"], "daily_cap_usd": 50}
CAPPED_ALLOWLIST = {"blockchain": {"rpc_url": "http://rpc.invalid", "paymaster_private_key": KEY,
                                   "paymaster": {"address": ADDR, "policy": dict(EXAMPLE_POLICY)}}}
UNCAPPED_ALLOWLIST = {"blockchain": {"rpc_url": "http://rpc.invalid", "paymaster_private_key": KEY,
                                     "paymaster": {"address": ADDR,
                                                   "policy": {"allowed_actions": ["transfer", "swap"]}}}}
CONFIGS = {"no_paymaster": NO_PAYMASTER, "capped": CAPPED, "uncapped": UNCAPPED,
           "capped_allowlist": CAPPED_ALLOWLIST, "uncapped_allowlist": UNCAPPED_ALLOWLIST}


# ── the description itself ──────────────────────────────────────────────────

def test_no_paymaster_is_described_as_no_sponsorship():
    d = describe_gas_policy(NO_PAYMASTER)
    assert d["sponsored"] is False
    assert d["daily_cap_usd"] is None
    assert "not configured" in d["statement"]


def test_a_cap_is_described_with_its_amount_and_its_consequence():
    d = describe_gas_policy(CAPPED)
    assert d["sponsored"] is True
    assert d["daily_cap_usd"] == 50.0
    assert "$50.00" in d["statement"]
    assert "refused" in d["statement"]


def test_no_cap_is_described_as_no_cap():
    d = describe_gas_policy(UNCAPPED)
    assert d["sponsored"] is True
    assert d["daily_cap_usd"] is None
    assert "no daily cap" in d["statement"]


def test_example_config_policy_matches_what_this_test_calls_the_example():
    example = json.loads((ROOT / "openmatrix.config.json.example").read_text(encoding="utf-8"))
    assert example["blockchain"]["paymaster"]["policy"] == EXAMPLE_POLICY


def _measured(config, tmp_path):
    """What the signer and the policy actually do for this config."""
    from runtime.blockchain.sponsorship import MeteredSigner, SponsorshipPolicy, policy_settings

    allowed, cap = policy_settings(config)
    policy = SponsorshipPolicy(allowed_actions=allowed, daily_cap_usd=cap,
                               db_path=tmp_path / "m.db")
    unlisted = policy.authorize_and_reserve("zz_capability.unlisted", identity="0xabc", est_usd=0.01)
    anonymous = policy.authorize_and_reserve((allowed or ["x"])[0], identity="", est_usd=0.01)

    class _Account:
        address = ADDR

        def sign_transaction(self, tx):
            return "signed"

    try:
        signer_skips_allowlist = MeteredSigner(
            _Account(), policy, "zz_capability.unlisted", "0xabc", 2000.0
        ).sign_transaction({"gas": 1, "gasPrice": 1}) == "signed"
    except Exception:
        signer_skips_allowlist = False
    return {
        "platform_signed_unlisted_refused": (not unlisted.allowed
                                             and unlisted.code == "action_not_allowed"
                                             and not signer_skips_allowlist),
        "anonymous_refused": (not anonymous.allowed and anonymous.code == "identity_required"),
        "allowlist": allowed,
    }


@pytest.mark.parametrize("name", sorted(CONFIGS))
def test_the_description_states_the_policy_the_signer_applies(name, tmp_path):
    config = CONFIGS[name]
    d = describe_gas_policy(config)
    if not d["sponsored"]:
        return
    facts = _measured(config, tmp_path)
    statement = d["statement"].lower()
    if facts["platform_signed_unlisted_refused"]:
        assert d["allowlist_applies_to_platform_signed"] is True, d
        assert d["allowed_actions"] == facts["allowlist"], d
        assert "only" in statement and ", ".join(facts["allowlist"]) in d["statement"], d
    else:
        assert d["allowlist_applies_to_platform_signed"] is False, d
        if facts["allowlist"] is not None:
            assert "paymaster/sign" in d["statement"], (
                "the allowlist is not applied to platform-signed operations here; the "
                "statement must say where it is applied", d)
    if facts["anonymous_refused"]:
        assert d["identity_required"] is True, d
        assert "identity" in statement, d
    else:
        assert d["identity_required"] is False, d


def test_the_platform_key_is_resolved_as_web3manager_resolves_it():
    from runtime.blockchain.web3_manager import Web3Manager
    alias_only = {"blockchain": {"rpc_url": "", "paymaster_key": KEY}}
    padded_placeholder = {"blockchain": {"rpc_url": "", "paymaster_private_key": "  YOUR_KEY "}}
    assert Web3Manager(alias_only).paymaster_key == KEY
    assert describe_gas_policy(alias_only)["sponsored"] is True
    manager = Web3Manager(padded_placeholder)
    from runtime.blockchain.web3_manager import is_placeholder_value
    assert is_placeholder_value(manager.paymaster_key)
    assert describe_gas_policy(padded_placeholder)["sponsored"] is False


async def test_web3manager_send_transaction_consults_the_policy(tmp_path, monkeypatch):
    """14 registry services sign through Web3Manager.send_transaction. With a cap
    configured and no attributable caller, it must refuse before anything is
    signed or broadcast, exactly as a tool-axis signer does."""
    from runtime.blockchain.sponsorship import SponsorshipDenied
    from runtime.blockchain.web3_manager import Web3Manager

    class _FixedPrice:
        def __init__(self, *a, **kw): pass
        async def eth_usd(self, **kw): return {"price": 2000.0}

    monkeypatch.setattr("runtime.blockchain.price_feed.PriceFeed", _FixedPrice)
    broadcast = []

    class _Eth:
        gas_price = 1_000_000_000

        def get_transaction_count(self, _a): return 0
        def estimate_gas(self, _tx): return 21_000
        def send_raw_transaction(self, raw):
            broadcast.append(raw)
            return b"\x01" * 32

    config = {"blockchain": {"rpc_url": "", "paymaster_private_key": KEY,
                             "paymaster": {"address": ADDR, "policy": {"daily_cap_usd": 50}}},
              "database": {"path": str(tmp_path / "x.db")}}
    manager = Web3Manager(config)
    manager.available = True
    manager.w3 = type("W3", (), {"eth": _Eth()})()
    with pytest.raises(SponsorshipDenied) as denied:
        await manager.send_transaction({"to": ADDR, "value": 0})
    assert denied.value.decision.code == "identity_required"
    assert broadcast == [], "a refused signature was broadcast"


def test_description_reads_config_without_touching_disk(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    describe_gas_policy(CAPPED)
    assert not any(tmp_path.rglob("*")), "describing a policy must not create its ledger"


# ── the responses a user receives ───────────────────────────────────────────

class _Eth:
    gas_price = 1_000_000_000
    block_number = 1

    def get_balance(self, _addr):
        return 0


class _Web3:
    eth = _Eth()

    @staticmethod
    def from_wei(value, unit):
        return value / (10**9 if unit == "gwei" else 10**18)


def _with_fake_chain(cls, config):
    obj = cls(config)
    obj._web3 = _Web3()
    return obj


@pytest.mark.parametrize("name", sorted(CONFIGS))
async def test_dashboard_gas_price_carries_the_configured_policy(name):
    from runtime.blockchain.dashboard import Dashboard
    out = json.loads(await _with_fake_chain(Dashboard, CONFIGS[name])._gas_price({}))
    assert out["gas_policy"] == describe_gas_policy(CONFIGS[name])


@pytest.mark.parametrize("name", sorted(CONFIGS))
async def test_dashboard_platform_stats_carries_the_configured_policy(name):
    from runtime.blockchain.dashboard import Dashboard
    out = json.loads(await _with_fake_chain(Dashboard, CONFIGS[name])._platform_stats({}))
    assert out["gas_policy"] == describe_gas_policy(CONFIGS[name])


@pytest.mark.parametrize("name", sorted(CONFIGS))
async def test_payments_fee_estimate_carries_the_configured_policy(name):
    from runtime.blockchain.payments import Payments
    out = json.loads(await _with_fake_chain(Payments, CONFIGS[name])._estimate_fee({}))
    assert out["gas_policy"] == describe_gas_policy(CONFIGS[name])


@pytest.mark.parametrize("name", sorted(CONFIGS))
async def test_crossborder_estimate_carries_the_configured_policy(name):
    from runtime.blockchain.crossborder import CrossBorderPayments
    out = json.loads(await CrossBorderPayments(CONFIGS[name])._estimate({"amount": "500"}))
    assert out["gas_policy"] == describe_gas_policy(CONFIGS[name])


def _stablecoin_tool_transfers_the_full_amount() -> bool:
    """Measured from source: the `stablecoin` tool's _transfer sends the amount it
    was given (scaled to decimals) with no fee subtracted."""
    import inspect
    from runtime.blockchain.stablecoins import Stablecoins
    src = inspect.getsource(Stablecoins._transfer)
    return ('amount = int(float(params.get("amount", "0")) * 10**decimals)' in src
            and "fee" not in src.lower()
            and re.search(r"functions\.transfer\(\s*Web3\.to_checksum_address\(params\[\"to\"\]\),\s*amount", src))


async def test_crossborder_estimate_quotes_the_fee_of_each_path():
    """The estimate quoted "$0.00 (no platform fee)"; the first correction quoted
    the transfer_stablecoin capability's tiered fee, while `_send` names the
    `stablecoin` tool, which charges nothing, and the send_payment capability
    charges the cross-border fee. Each quoted fee must come from the code that
    charges it, and the headline fee must be the path `_send` names."""
    from runtime.blockchain.crossborder import CrossBorderPayments
    from runtime.blockchain.services.cross_border.service import CrossBorderService
    from runtime.blockchain.services.stablecoin.service import StablecoinService

    assert _stablecoin_tool_transfers_the_full_amount()
    out = json.loads(await CrossBorderPayments(CAPPED)._estimate({"amount": "500"}))
    by_path = out["fees_by_path"]
    assert out["transfer_fee"] == by_path["stablecoin_tool_transfer"]
    assert by_path["stablecoin_tool_transfer"]["fee"] == 0.0
    expected = await StablecoinService(CAPPED).get_fee(500.0)
    assert by_path["transfer_stablecoin_capability"]["fee"] == expected["fee"] > 0
    cb = CrossBorderService(CAPPED).fee_for(500.0)
    assert by_path["send_payment_capability"]["fee_amount"] == cb["fee_amount"] > 0
    # _send attests on-chain before it answers, so its named next step is read
    # from source rather than by running it.
    import inspect
    assert "`stablecoin` tool" in inspect.getsource(CrossBorderPayments._send)


@pytest.mark.parametrize("name", sorted(CONFIGS))
async def test_bridge_app_config_reports_sponsorship_as_configured(name):
    from gateway.bridge import BridgeRoutes
    bridge = BridgeRoutes.__new__(BridgeRoutes)
    bridge._config = CONFIGS[name]
    resp = await bridge.get_config(None)
    body = json.loads(resp.body)
    data = body.get("data", body)
    assert data["features"]["gas_sponsorship"] is describe_gas_policy(CONFIGS[name])["sponsored"]


# ── published text, gated on a measured refusal ─────────────────────────────

_UNCONDITIONAL = [
    r"users? never pay gas",
    r"users never pay\b",
    r"users are not charged gas",
    r"pays gas for everything",
    r"all gas (?:fees )?(?:is |are )?covered by (?:the )?platform",
    r"covers all (?:blockchain )?(?:transaction|gas) (?:fees|costs)",
    r"no exceptions\. no conditions",
    r"all transactions are sponsored",
    r"(?:buyer|user)s? pays? no gas",
    r"never hold or spend native tokens",
    r"\bno gas fees\b",
    # "Gas covered by platform." in 12 model-facing tool descriptions and ~30
    # method docstrings said it with no condition. `gas_paid_by` result fields
    # are not matched: they are written after the platform signed and paid for
    # that transaction, which is what they report.
    r"gas covered by (?:the )?platform",
    r"have gas covered",
    r"platform absorbs gas",
    r"pays them within its daily sponsorship cap",
]

# Legal copy is changed only by counsel (redlines travel separately); contract
# NatSpec is part of audited source. Both are reported, not edited here.
_NOT_EDITABLE_HERE = ("web/terms.html", "web/privacy.html")


def test_the_policy_really_refuses_past_the_cap(tmp_path):
    policy = SponsorshipPolicy(daily_cap_usd=50.0, db_path=tmp_path / "s.db")
    first = policy.authorize_and_reserve("transfer", identity="0xabc", est_usd=40.0)
    assert first.allowed
    policy.commit(first.reservation_id)
    second = policy.authorize_and_reserve("transfer", identity="0xabc", est_usd=20.0)
    assert not second.allowed and second.code == "daily_cap_exceeded"


def test_no_published_surface_promises_unconditional_gas_sponsorship(tmp_path):
    test_the_policy_really_refuses_past_the_cap(tmp_path)  # the measured premise
    out = subprocess.check_output(["git", "ls-files"], cwd=ROOT, text=True)
    offenders = []
    for rel in out.splitlines():
        if (rel.startswith(("tests/", "contracts/")) or rel in _NOT_EDITABLE_HERE
                or rel == "CHANGELOG.md" or not (ROOT / rel).is_file()):
            continue
        try:
            text = (ROOT / rel).read_text(encoding="utf-8")
        except (UnicodeDecodeError, OSError):
            continue
        for lineno, line in enumerate(text.splitlines(), 1):
            low = line.lower()
            if any(re.search(p, low) for p in _UNCONDITIONAL):
                offenders.append(f"{rel}:{lineno}: {line.strip()[:110]}")
    assert not offenders, "\n".join(offenders)


def test_the_agent_prompt_describes_gas_as_the_policy_does():
    """What the model is told: agents/trinity/identity.md is the file the ReAct
    loop loads as Trinity's system prompt (runtime/react_loop.py). The prompt
    reaches the model before any tool result, so every gas rule in it must be
    conditional on gas_policy: the no-paymaster description says the platform
    pays no gas, and the no-cap description has no cap."""
    prompt = (ROOT / "agents" / "trinity" / "identity.md").read_text(encoding="utf-8").lower()
    assert "daily cap" in prompt or "daily sponsorship" in prompt
    assert describe_gas_policy(NO_PAYMASTER)["sponsored"] is False  # measured premise
    for line in prompt.splitlines():
        if "gas" in line and "platform pays" in line:
            assert "sponsored" in line and ("false" in line or "not" in line), (
                f"a gas rule says the platform pays without the no-sponsorship case: {line!r}")
    assert not re.search(r"batch transactions for savings|suggest optimal timing", prompt), (
        "the prompt offers gas-saving services no tool provides")


def test_every_registered_tool_description_states_gas_with_its_condition():
    """What the model reads before calling a tool. A description that mentions
    gas must carry the sponsorship condition, not "Gas covered by platform."."""
    from runtime.blockchain.registry import CAPABILITY_CLASSES
    offenders = []
    for cls in CAPABILITY_CLASSES:
        try:
            tool = cls(CAPPED)
        except Exception:
            continue
        text = str(tool.description)
        low = text.lower()
        if "gas" in low and "sponsorship" not in low and "no gas needed" not in low:
            offenders.append(f"{cls.__name__}: {text}")
    assert not offenders, "\n".join(offenders)
