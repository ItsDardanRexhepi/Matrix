"""What the platform tells people about gas follows what the sponsorship policy
actually does.

Since the commit "D-045: enforce the sponsorship cap the repo already
documents, and close the deploy offer the 501 never reached" the platform
signer is metered: a per-identity rolling
24-hour USD cap, an action allowlist, a refusal when the cap would be crossed,
and nothing at all when no paymaster is configured. The copy never moved. The
Trinity system prompt, the capability map, docs/blockchain.md ("No exceptions.
No conditions. Ever."), README, the differentiators page, the tool modules'
descriptions and docstrings, the SDK, and — the part a user actually receives —
the dashboard, payments and cross-border tools all said or returned "All gas
fees covered by platform — users never pay" whatever the deployment was
configured to do. The iOS bridge config reported `gas_sponsorship: true`
unconditionally.

Two kinds of control, neither keyed on the prose it judges:

  * RESPONSES are derived: each tool's gas statement must equal
    `describe_gas_policy(config)` for five configurations (no paymaster, a
    paymaster with a $50 cap, one with no cap, and each of those with the
    example config's allowlist), so a hardcoded string fails whatever it says.
  * PUBLISHED TEXT is checked only after the condition is MEASURED: a policy is
    built from a capped config and asked to authorise a request above the cap.
    Only because that is refused may no public surface promise unconditional
    sponsorship.

The description itself is measured against the signer: with no cap,
MeteredSigner does not consult the policy, so the allowlist binds only
/api/v1/paymaster/sign; with a cap, the allowlist binds platform-signed
operations by their `<capability>.<method>` names (which the example config's
["transfer", "swap"] does not contain), and an unattributable request is
refused. The platform key is read under both names Web3Manager accepts.
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
    example = json.loads((ROOT / "matrix.config.json.example").read_text(encoding="utf-8"))
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
    r"all gas (?:fees )?(?:is |are |were )?covered by (?:the )?platform",
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
    # Found after the first sweep: a module docstring split this phrase across a
    # line break (the scan was line by line), a method docstring said it with
    # no subject, and the API reference said it for "every capability".
    r"cost is covered by (?:the )?platform",
    r"attestation gas is covered",
    r"sponsors gas (?:via paymaster )?for every capability",
]

# Legal copy is changed only by counsel; contract NatSpec is part of audited
# source. Neither is edited here. The unconditional lines they hold are
# web/terms.html ("Users are not charged gas fees"),
# contracts/MatrixPaymaster.sol ("users never pay gas") and
# contracts/MatrixAttestation.sol ("Gas covered by the platform"); they are
# left for counsel and for the next contract revision.
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
        offenders.extend(f"{rel}:{lineno}: {line[:110]}"
                         for lineno, line in _joined_line_hits(text, _UNCONDITIONAL))
    assert not offenders, "\n".join(offenders)


_CONTINUATION = re.compile(r"^\s*(?:#+|//|\*|>)?\s*")


def _joined_line_hits(text: str, patterns) -> list[tuple[int, str]]:
    """(line, text) where a pattern matches starting on that line, reading the
    line joined to the next one so a phrase wrapped across a line break (and a
    comment or docstring continuation marker) still matches."""
    lines = text.splitlines()
    hits = []
    for i, line in enumerate(lines):
        head = line.strip().lower()
        nxt = _CONTINUATION.sub("", lines[i + 1]).lower() if i + 1 < len(lines) else ""
        joined = f"{head} {nxt}"
        for p in patterns:
            m = re.search(p, joined)
            if m and m.start() <= len(head):
                hits.append((i + 1, line.strip()))
                break
    return hits


def test_the_unconditional_scan_matches_a_phrase_wrapped_across_lines():
    text = ('"""\nDeFi on Base. All gas fees are\ncovered by the platform via ERC-4337 paymaster.\n"""\n'
            "# Estimate gas. Cost is covered by the\n# platform.\n"
            'print("All gas fees were covered by the platform.")\n')
    hits = _joined_line_hits(text, _UNCONDITIONAL)
    assert [n for n, _ in hits] == [2, 5, 7], hits


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


# ── a cap promised where none may be set, an allowlist where it does not bind ─

_CAP_PROMISE = re.compile(r"\bup to (?:a|the|its) (?:per-identity )?daily (?:sponsorship )?cap\b")
_CAP_CONDITION = re.compile(
    r"when (?:one|a cap|a daily cap|that policy sets|the policy sets) is set|if one is set|"
    r"\bsets? (?:a|no) (?:per-identity )?(?:daily )?cap|may set|when a (?:daily )?cap is set")
_ALLOWLIST_ON_PLATFORM = re.compile(
    r"platform[- ](?:signed|signs)|signed by the platform|platform would sign")
_ALLOWLIST_QUALIFIED = re.compile(
    r"only when|no cap|cap is (?:also )?set|when (?:it|that policy|the policy) sets a|paymaster/sign")


def _prose_sentences() -> list[tuple[str, str]]:
    out = subprocess.check_output(["git", "ls-files", "*.md", "*.html"], cwd=ROOT, text=True)
    sentences = []
    for rel in out.splitlines():
        if (rel.startswith(("tests/", "contracts/")) or rel in _NOT_EDITABLE_HERE
                or rel == "CHANGELOG.md" or not (ROOT / rel).is_file()):
            continue
        text = re.sub(r"<[^>]+>", " ", (ROOT / rel).read_text(encoding="utf-8"))
        flat = re.sub(r"\s*\n\s*(?:>\s*)?", " ", text)
        sentences.extend((rel, s) for s in re.split(r"(?<=[.!?])\s+", flat))
    return sentences


def _cap_and_allowlist_offenders(sentences) -> list[str]:
    offenders = []
    for rel, sentence in sentences:
        low = sentence.lower()
        if _CAP_PROMISE.search(low) and not _CAP_CONDITION.search(low):
            offenders.append(f"{rel}: cap promised unconditionally: {sentence.strip()[:160]}")
        if ("allowlist" in low and _ALLOWLIST_ON_PLATFORM.search(low)
                and not _ALLOWLIST_QUALIFIED.search(low)):
            offenders.append(f"{rel}: allowlist said to bind platform-signed operations "
                             f"without the cap condition: {sentence.strip()[:160]}")
    return offenders


def test_the_cap_and_allowlist_scan_catches_the_old_sentences():
    old = [
        ("x.md", "When an operator configures sponsorship, the platform pays that gas up to a "
                 "per-identity daily cap."),
        ("y.md", "State-modifying capabilities below are signed by the platform, which pays "
                 "their gas within the operator's sponsorship policy — a per-identity daily cap "
                 "and an action allowlist, when configured; past the cap an operation is refused."),
    ]
    assert len(_cap_and_allowlist_offenders(old)) == 2
    fixed = [("z.md", "Gas is sponsored within the policy — a per-identity daily cap when one is "
                      "set, up to a per-identity daily cap when one is set.")]
    assert not _cap_and_allowlist_offenders(fixed)


def test_no_published_prose_promises_a_cap_or_an_allowlist_the_policy_may_not_apply():
    # The measured premises: with no cap the describer reports none, and with an
    # allowlist and no cap the allowlist does not bind platform-signed operations.
    assert describe_gas_policy(UNCAPPED)["daily_cap_usd"] is None
    assert describe_gas_policy(UNCAPPED_ALLOWLIST)["allowlist_applies_to_platform_signed"] is False
    offenders = _cap_and_allowlist_offenders(_prose_sentences())
    assert not offenders, "\n".join(offenders)


async def test_the_capped_statement_names_what_the_cap_does_not_count():
    from runtime.blockchain.sponsorship import UNMETERED_PLATFORM_OPERATIONS

    d = describe_gas_policy(CAPPED)
    assert d["unmetered_operations"] == sorted(UNMETERED_PLATFORM_OPERATIONS)
    low = d["statement"].lower()
    assert "not counted against the cap" in low
    assert "attestations you ask for" in low and "are metered the same way" in low, d["statement"]
    assert not any(op.startswith("attestation.") or op == "eas.revoke"
                   for op in UNMETERED_PLATFORM_OPERATIONS), (
        "a caller's attestation capability is listed as unmetered", UNMETERED_PLATFORM_OPERATIONS)
    assert describe_gas_policy(UNCAPPED)["unmetered_operations"] == []


# ── an example that reports gas as paid whatever happened ────────────────────
#
# sdk/examples/blockchain_ops.py ended by printing "Gas for these operations
# was paid by the platform within its sponsorship policy; the dashboard result
# above carries that policy as gas_policy", on every run. With no paymaster
# configured nothing is sponsored, a refused operation paid no gas at all, and
# the dashboard result it pointed at was the agent's reply, cut to 200
# characters. A sentence that says gas WAS paid reports an event; an example
# may print one only inside a branch that tested what the code returned.

_GAS_PAID = re.compile(
    r"\bgas\b[^.]*\b(?:was|were|has been|have been)\s+(?:paid|covered|sponsored)\b"
    r"|\b(?:paid|covered|sponsored)\s+(?:the\s+)?gas\b[^.]*\bfor these\b", re.I)


def _printed_text(call) -> str:
    import ast
    parts = []
    for arg in call.args:
        for node in ast.walk(arg):
            if isinstance(node, ast.Constant) and isinstance(node.value, str):
                parts.append(node.value)
    return " ".join(parts)


def _unconditional_gas_paid_prints(source: str) -> list[str]:
    import ast
    tree = ast.parse(source)
    parents = {child: node for node in ast.walk(tree) for child in ast.iter_child_nodes(node)}
    out = []
    for node in ast.walk(tree):
        if not (isinstance(node, ast.Call) and getattr(node.func, "id", "") == "print"):
            continue
        text = _printed_text(node)
        if not _GAS_PAID.search(" ".join(text.split())):
            continue
        up, guarded = parents.get(node), False
        while up is not None:
            if isinstance(up, ast.If) and re.search(r"sponsored|gas_policy",
                                                    ast.unparse(up.test)):
                guarded = True
                break
            up = parents.get(up)
        if not guarded:
            out.append(f"line {node.lineno}: {text.strip()[:120]}")
    return out


def test_the_gas_paid_print_scan_catches_the_old_example():
    old = ('print("\\nGas for these operations was paid by the platform within its sponsorship "\n'
           '      "policy; the dashboard result above carries that policy as gas_policy.")\n')
    assert _unconditional_gas_paid_prints(old)
    guarded = ('if result.get("gas_policy", {}).get("sponsored"):\n'
               '    print("Gas for this operation was sponsored by the platform.")\n')
    assert not _unconditional_gas_paid_prints(guarded)
    assert not _unconditional_gas_paid_prints(
        'print("Whether the platform paid gas depends on the deployment.")\n')


def test_no_example_prints_that_gas_was_paid_whatever_happened():
    assert describe_gas_policy(NO_PAYMASTER)["sponsored"] is False  # measured premise
    offenders = []
    for folder in ("examples", "sdk/examples"):
        for path in sorted((ROOT / folder).glob("*.py")):
            rel = str(path.relative_to(ROOT))
            offenders += [f"{rel} {o}" for o in
                          _unconditional_gas_paid_prints(path.read_text(encoding="utf-8"))]
    assert not offenders, "\n".join(offenders)


# The same example printed the dashboard reply cut to 200 characters. The
# platform_stats result puts gas_policy last, after the network, the wallet,
# its balance, the block and the gas price, so the cut removed exactly the part
# the gas sentence pointed at. The example is run here with the client's
# transport replaced: Neo's reply is the dashboard's own platform_stats result
# for each configuration, and what the example prints about gas must be that
# result's gas_policy statement, or say the reply did not carry one.

class _Eth:
    block_number = 12_345_678
    gas_price = 1_000_000

    def get_balance(self, _address):
        return 0


class _Web3:
    eth = _Eth()

    @staticmethod
    def from_wei(value, _unit):
        return value / 10**9


def _platform_stats(config) -> str:
    import asyncio
    from runtime.blockchain.dashboard import Dashboard
    dashboard = Dashboard(config)
    dashboard._web3 = _Web3()
    return asyncio.run(dashboard.execute(action="platform_stats"))


def _run_the_sdk_example(monkeypatch, capsys, dashboard_reply: str) -> str:
    import asyncio
    import importlib.util
    import sys
    from sdk.client import MatrixClient

    async def post(self, path, data):
        reply = dashboard_reply if '"platform_stats"' in data.get("message", "") else "done"
        return {"response": reply, "agent": data.get("agent", ""), "tool_calls": []}

    monkeypatch.setattr(MatrixClient, "_post", post)
    monkeypatch.setenv("MATRIX_API_KEY", "the-operator-key")
    path = ROOT / "sdk" / "examples" / "blockchain_ops.py"
    spec = importlib.util.spec_from_file_location("sdk_blockchain_ops_under_test", path)
    module = importlib.util.module_from_spec(spec)
    monkeypatch.setitem(sys.modules, "sdk_blockchain_ops_under_test", module)
    spec.loader.exec_module(module)
    capsys.readouterr()
    asyncio.run(module.main())
    return capsys.readouterr().out


def _gas_section(out: str) -> str:
    return out.split("── Gas ──", 1)[1] if "── Gas ──" in out else ""


@pytest.mark.parametrize("name", ["no_paymaster", "capped", "uncapped"])
def test_the_sdk_example_prints_the_gas_policy_the_dashboard_reply_carries(
        monkeypatch, capsys, name):
    stats = _platform_stats(CONFIGS[name])
    policy = json.loads(stats)["gas_policy"]
    assert policy == describe_gas_policy(CONFIGS[name])  # measured premise
    reply = "Here are the platform stats:\n" + stats
    assert reply.index('"gas_policy"') > 200, "premise: a 200-character cut drops gas_policy"

    out = _run_the_sdk_example(monkeypatch, capsys, reply)
    assert stats in out, "the dashboard reply is not printed whole"
    gas = " ".join(_gas_section(out).split())
    assert gas == " ".join(policy["statement"].split()), (
        f"under {name}, the example printed {gas!r} for gas; the reply says "
        f"{policy['statement']!r}")


def test_the_sdk_example_says_so_when_the_reply_quotes_no_gas_policy(monkeypatch, capsys):
    out = _run_the_sdk_example(monkeypatch, capsys, "The dashboard is unavailable right now.")
    gas = " ".join(_gas_section(out).split())
    assert "does not quote" in gas and "gas policy" in gas, gas
    assert not _GAS_PAID.search(gas), gas


# The example also looked for the policy in each tool call's result_preview,
# and its docstring said the policy was "found in Neo's reply or a tool call's
# result preview". A client reads a tool's output as ToolOutcome.success cuts
# it, cut again where the reasoning loop writes result_preview, and
# platform_stats puts gas_policy after the cut, so a preview never carries it.
# When Neo describes the policy in words rather than quoting the object, the
# example cannot read it, and it said "the dashboard reply did not include the
# deployment's gas policy", which is then untrue.

def _the_cut_the_client_reads() -> int:
    """The length runtime/react_loop.py cuts a tool's client_preview to where
    it writes result_preview."""
    import ast
    tree = ast.parse((ROOT / "runtime" / "react_loop.py").read_text(encoding="utf-8"))
    cuts = [value.slice.upper.value for node in ast.walk(tree) if isinstance(node, ast.Dict)
            for key, value in zip(node.keys, node.values)
            if isinstance(key, ast.Constant) and key.value == "result_preview"
            and isinstance(value, ast.Subscript) and ast.unparse(value.value) == "client_preview"
            and isinstance(value.slice, ast.Slice) and isinstance(value.slice.upper, ast.Constant)]
    assert len(cuts) == 1, f"re-derive: result_preview is written as {cuts}"
    return cuts[0]


def _preview_the_client_reads(text: str) -> str:
    from runtime.tools.dispatcher import ToolOutcome
    return ToolOutcome.success(text).client_preview[:_the_cut_the_client_reads()]


def _the_sdk_example():
    import importlib.util
    path = ROOT / "sdk" / "examples" / "blockchain_ops.py"
    spec = importlib.util.spec_from_file_location("sdk_blockchain_ops_read", path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


_SAYS_IT_READS_A_PREVIEW = re.compile(
    r"\b(?:found|read|taken)(?: from| in)? [^.;]{0,60}\bresult[_ ]preview", re.I)


@pytest.mark.parametrize("name", ["no_paymaster", "capped", "uncapped"])
def test_the_sdk_example_names_no_source_that_cannot_carry_the_policy(name):
    import inspect
    stats = _platform_stats(CONFIGS[name])
    assert '"gas_policy"' in stats
    preview = _preview_the_client_reads(stats)
    assert '"gas_policy"' not in preview, "premise: a tool call's preview carries gas_policy now"

    example = _the_sdk_example()
    # It reads what it says it reads: a preview holding the whole result is
    # not read, and no docstring names the preview as where the policy is found.
    assert example.gas_policy_in({"response": "", "tool_calls": [{"result_preview": stats}]}) is None
    docs = " ".join(" ".join((inspect.getdoc(obj) or "").split())
                    for obj in (example, example.gas_policy_in))
    m = _SAYS_IT_READS_A_PREVIEW.search(docs)
    assert not m, f"the example says it reads the policy from a preview: ...{m.group(0)}..."


def test_the_sdk_example_does_not_deny_a_policy_neo_describes_in_words(monkeypatch, capsys):
    statement = describe_gas_policy(CONFIGS["capped"])["statement"]
    out = _run_the_sdk_example(monkeypatch, capsys,
                               "Gas on this deployment: " + statement + " (from the dashboard)")
    gas = " ".join(_gas_section(out).split())
    assert not re.search(r"\b(?:did|does) not (?:include|carry|contain)\b", gas), gas
    assert not _GAS_PAID.search(gas), gas


def test_the_preview_scan_sees_the_old_docstring():
    assert _SAYS_IT_READS_A_PREVIEW.search(
        "The gas_policy object the dashboard's platform_stats result carries, found in Neo's "
        "reply or a tool call's result preview, or None when neither holds one.")
    assert not _SAYS_IT_READS_A_PREVIEW.search(
        "It does not look in a tool call's result_preview: the gateway cuts a preview. "
        "A tool call's result_preview is not read: it is cut to 200 characters.")
