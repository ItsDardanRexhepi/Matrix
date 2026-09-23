"""An attestation a caller asks for is metered by the sponsorship policy; only
the platform's own records are not.

D-045 put every platform signature behind the sponsorship policy: an action
allowlist, a per-identity rolling 24-hour USD cap, and a refusal when a capped
request cannot be attributed to an identity. Three exemptions stayed listed in
UNMETERED_PLATFORM_OPERATIONS on the premise that they were "fixed call data the
model never composes, written on the platform's own behalf":
`eas.attest`, `eas.attest_time_critical` and `eas.revoke`. Measured on main:

  * `EASClient.attest` signed every write as `eas.attest`, and nine
    model-facing tools called it with model-chosen action, agent, details and
    recipient (the `eas` tool, agent identity, cross-border, gaming, identity,
    insurance, IP royalties, securities, supply chain). With a $50 cap
    configured and no signed-in identity, a tool attestation signed and was
    sent: the cap did not apply to it at all;
  * the `eas` tool's `batch_attest` looped over a caller-supplied list with no
    bound, one platform-signed write per entry;
  * the attestation capabilities (`create_attestation`, `batch_attest`,
    `revoke_attestation`) reached `AttestationService.attest` / `batch_attest`
    / `revoke`, which signed as the exempt operations. A caller-selected
    `time_critical` (or a `data.category` in TIME_CRITICAL_CATEGORIES) signed
    inside the request; `revoke` signed as `eas.revoke`.

The properties, each driven through the code that signs rather than read from
its comments:

  1. every `.attest(` in a model-facing tool module names a metered operation
     of its own module;
  2. with a cap and no identity, a tool attestation is refused before anything
     is signed or sent, and a platform record with no operation still signs;
  3. the `eas` tool meters each entry and refuses a batch over the bound whole;
  4. no caller's attestation is listed as unmetered;
  5. every attestation action in ACTION_MAP reaches a metered entry point;
  6. the time-critical, queued, batch and revoke paths of the capabilities are
     refused by the policy (off the allowlist, no identity, over the cap), and a
     queued write is metered against the identity it was queued under, not the
     request that flushes the batch; a policy refusal at flush is dropped, not
     re-queued.

The platform's own records (the dispatcher's record of each capability call,
records services write after another operation) remain unmetered by design:
metering them against one caller's cap would charge that caller for another's
record.
"""

from __future__ import annotations

import ast
import json
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent
KEY = "0x" + "11" * 32
ADDR = "0x" + "22" * 20
EXAMPLE_POLICY = {"allowed_actions": ["transfer", "swap"], "daily_cap_usd": 50}


# ── 1. every tool attestation names its metered operation ───────────────────

def _tool_attest_calls_without_an_operation() -> list[str]:
    """Every `.attest(` call in a model-facing tool module (runtime/blockchain/*.py
    defining a BlockchainInterface subclass) must pass `operation=` a string of
    its own module."""
    offenders = []
    for path in sorted((ROOT / "runtime" / "blockchain").glob("*.py")):
        if path.name in ("eas_client.py", "interface.py"):
            continue
        tree = ast.parse(path.read_text(encoding="utf-8"))
        is_tool = any(isinstance(n, ast.ClassDef)
                      and any(getattr(b, "id", "") == "BlockchainInterface" for b in n.bases)
                      for n in tree.body)
        if not is_tool:
            continue
        for node in ast.walk(tree):
            if isinstance(node, ast.Call) and getattr(node.func, "attr", "") == "attest":
                op = next((k.value for k in node.keywords if k.arg == "operation"), None)
                if not (isinstance(op, ast.Constant) and isinstance(op.value, str)
                        and op.value.startswith(path.stem + ".")):
                    offenders.append(f"{path.relative_to(ROOT)}:{node.lineno}")
    return offenders


def test_the_tool_sweep_sees_the_tools():
    """Planted premise: the sweep reads the modules it claims to read."""
    tools = []
    for path in sorted((ROOT / "runtime" / "blockchain").glob("*.py")):
        source = path.read_text(encoding="utf-8")
        if "(BlockchainInterface)" in source and ".attest(" in source:
            tools.append(path.stem)
    assert {"eas_manager", "agent_identity", "insurance", "securities"} <= set(tools), tools


def test_every_tool_attestation_names_its_metered_operation():
    offenders = _tool_attest_calls_without_an_operation()
    assert not offenders, (
        "a model-facing tool attests without an operation name, so the platform "
        "signs it unmetered: " + ", ".join(offenders))


# ── 2. the EAS client meters a tool's write, not the platform's record ──────

class _FakeEth:
    gas_price = 1_000_000_000

    def __init__(self, sent):
        self._sent = sent

    def contract(self, address, abi):
        class _Tx:
            def build_transaction(self, params):
                return {"to": ADDR, "data": b"", "gas": params["gas"],
                        "gasPrice": params["gasPrice"], "nonce": 0,
                        "chainId": params["chainId"], "value": 0}

        class _Fn:
            def attest(self, request):
                return _Tx()

            def revoke(self, request):
                return _Tx()

        class _C:
            functions = _Fn()
        return _C()

    def get_transaction_count(self, address):
        return 0

    def send_raw_transaction(self, raw):
        self._sent.append(raw)
        return bytes(32)

    def wait_for_transaction_receipt(self, tx_hash, timeout=0):
        return {"status": 1, "blockNumber": 1}


def _eas_config(tmp_path, policy):
    return {"blockchain": {"rpc_url": "http://rpc.invalid", "paymaster_private_key": KEY,
                           "platform_wallet": ADDR, "eas_contract": ADDR,
                           "eas_schema": "0x" + "33" * 32, "chain_id": 84532,
                           "paymaster": {"address": ADDR, "policy": policy}},
            "database": {"path": str(tmp_path / "db.sqlite")}}


def _fake_signing(monkeypatch, signed_by: list):
    """Real key handling and the real policy; only the signed object is
    normalised (eth_account versions name the raw bytes differently) and the
    price is fixed ($3000/ETH)."""
    from eth_account.signers.local import LocalAccount
    from runtime.blockchain.price_feed import PriceFeed

    async def _quote(self, **_kw):
        return {"price": 3000.0}

    def _sign(self, tx):
        signed_by.append(tx)
        return type("Signed", (), {"raw_transaction": b"raw"})()

    monkeypatch.setattr(PriceFeed, "eth_usd", _quote)
    monkeypatch.setattr(LocalAccount, "sign_transaction", _sign)


def _eas_client(monkeypatch, config, sent):
    from runtime.blockchain.eas_client import EASClient

    client = EASClient(config)
    fake_w3 = type("W3", (), {"eth": _FakeEth(sent)})()
    monkeypatch.setattr(EASClient, "_is_configured", lambda self: True)
    monkeypatch.setattr(EASClient, "_validate_config", lambda self: None)
    monkeypatch.setattr(EASClient, "web3", property(lambda self: fake_w3))
    return client


async def test_a_tool_attestation_is_refused_by_a_capped_policy_and_a_platform_record_is_not(
        monkeypatch, tmp_path):
    from runtime.blockchain.sponsorship import SponsorshipDenied

    signed_by: list = []
    sent: list = []
    _fake_signing(monkeypatch, signed_by)
    client = _eas_client(monkeypatch, _eas_config(tmp_path, {"daily_cap_usd": 50}), sent)

    # No signed-in identity: a capped policy cannot attribute the spend.
    with pytest.raises(SponsorshipDenied) as denied:
        await client.attest("custom", "neo", {}, operation="eas_manager.attest")
    assert denied.value.decision.code == "identity_required"
    assert sent == [] and signed_by == [], "a refused attestation was signed or broadcast"

    # Off the allowlist, with an identity: refused too.
    client = _eas_client(monkeypatch, _eas_config(tmp_path, dict(EXAMPLE_POLICY)), sent)
    with pytest.raises(SponsorshipDenied) as denied:
        await client.attest("custom", "neo", {}, operation="eas_manager.attest",
                            identity="0xabc")
    assert denied.value.decision.code == "action_not_allowed" and sent == []

    # The platform's own record is listed as unmetered and still signs.
    result = await client.attest("custom", "neo", {})
    assert result["status"] == "attested" and len(sent) == 1, result


async def test_the_eas_tool_under_a_cap_signs_nothing_it_cannot_attribute(monkeypatch, tmp_path):
    """The behaviour, through the tool the model calls: with a $50 cap and no
    signed-in identity, `eas` attest must not sign or send. On main it signed
    as the exempt `eas.attest` and sent."""
    from runtime.blockchain.eas_manager import EASManager
    from runtime.blockchain.sponsorship import SponsorshipDenied

    signed_by: list = []
    sent: list = []
    _fake_signing(monkeypatch, signed_by)
    config = _eas_config(tmp_path, {"daily_cap_usd": 50})
    _eas_client(monkeypatch, config, sent)
    with pytest.raises(SponsorshipDenied):
        await EASManager(config).execute(action="attest", data={"action": "anything"},
                                         recipient=ADDR)
    assert sent == [] and signed_by == [], "the tool's attestation was signed unmetered"


async def test_a_tool_refusal_reaches_the_agent_as_a_refusal(monkeypatch, tmp_path):
    """Through the tool dispatcher, a policy refusal is a refusal the agent can
    say, not an unmetered signature and not a generic failure."""
    from runtime.blockchain.eas_client import EASClient
    from runtime.blockchain.identity import Identity
    from runtime.blockchain.sponsorship import SponsorshipDecision, SponsorshipDenied

    async def _refuse(self, *a, **kw):
        assert kw.get("operation") == "identity.register", kw
        raise SponsorshipDenied(SponsorshipDecision(False, "identity_required", "no identity"))

    monkeypatch.setattr(EASClient, "attest", _refuse)
    with pytest.raises(SponsorshipDenied):
        await Identity(_eas_config(tmp_path, {"daily_cap_usd": 50})).execute(
            action="register", name="n", address=ADDR)


# ── 3. the `eas` tool meters each entry and bounds a batch ──────────────────

async def test_the_eas_tool_meters_attest_and_bounds_a_batch(monkeypatch, tmp_path):
    from runtime.blockchain.eas_client import EASClient, MAX_ATTESTATIONS_PER_BATCH
    from runtime.blockchain.eas_manager import EASManager

    seen: list = []

    async def _attest(self, action, agent, details, recipient=None, *, operation=None,
                      identity=None):
        seen.append(operation)
        return {"status": "attested"}

    monkeypatch.setattr(EASClient, "attest", _attest)
    tool = EASManager(_eas_config(tmp_path, {"daily_cap_usd": 50}))
    await tool.execute(action="attest", data={"action": "x"})
    await tool.execute(action="batch_attest", attestations=[{"action": "x"}] * 2)
    assert seen == ["eas_manager.attest", "eas_manager.batch_attest", "eas_manager.batch_attest"]

    seen.clear()
    out = json.loads(await tool.execute(
        action="batch_attest", attestations=[{"action": "x"}] * (MAX_ATTESTATIONS_PER_BATCH + 1)))
    assert out["ok"] is False and out["code"] == "batch_too_large" and seen == [], out


# ── 4. no caller's attestation is listed as unmetered ───────────────────────

def test_no_caller_attestation_is_listed_unmetered():
    from runtime.blockchain.sponsorship import UNMETERED_PLATFORM_OPERATIONS

    assert "eas.revoke" not in UNMETERED_PLATFORM_OPERATIONS, (
        "nothing revokes on the platform's own behalf; a revocation is a caller's request")
    assert not any(op.startswith("attestation.") or op.startswith("eas_manager.")
                   for op in UNMETERED_PLATFORM_OPERATIONS), UNMETERED_PLATFORM_OPERATIONS


# ── 5. every attestation action reaches a metered entry point ───────────────

def test_every_attestation_action_targets_a_metered_entry_point():
    """Keyed on which method ACTION_MAP reaches, never on a field the caller
    writes: every write action that reaches the attestation service targets a
    method that meters, and the platform's own record (`attest`) is not
    reachable as an action."""
    import inspect
    from runtime.blockchain.services.attestation.service import AttestationService
    from runtime.blockchain.services.service_dispatcher import ACTION_MAP
    from runtime.capabilities.catalog import CAPABILITIES

    metered = {"attest_for_caller", "batch_attest", "revoke"}
    reached = {m for s, m in ACTION_MAP.values() if s == "attestation"}
    assert reached - {"verify"} == metered, reached
    reached_by_registry = {c["method"] for c in CAPABILITIES if c["service"] == "attestation"}
    assert "attest" not in reached_by_registry and reached_by_registry <= metered | {"verify"}
    for name in metered:
        method = getattr(AttestationService, name)
        assert "caller_identity" in inspect.signature(method).parameters, name
        src = inspect.getsource(method)
        assert "operation=" in src or "platform_signer" in src, name


# ── 6. the capability paths are refused by the policy ───────────────────────

def _time_critical_web3(monkeypatch, sent):
    from runtime.blockchain.services.attestation.time_critical import TimeCriticalHandler

    fake_w3 = type("W3", (), {"eth": _FakeEth(sent)})()
    monkeypatch.setattr(TimeCriticalHandler, "web3", property(lambda self: fake_w3))


async def test_a_time_critical_capability_attestation_is_refused_by_the_policy(
        monkeypatch, tmp_path):
    from runtime.blockchain.services.attestation.service import AttestationService
    from runtime.blockchain.sponsorship import (
        SponsorshipDenied, reset_caller_identity, set_caller_identity,
    )

    sent: list = []
    _fake_signing(monkeypatch, [])
    _time_critical_web3(monkeypatch, sent)
    critical = {"category": "dispute_filing", "action": "x"}

    # No identity bound, cap set: cannot attribute the spend.
    svc = AttestationService(_eas_config(tmp_path, {"daily_cap_usd": 50}))
    with pytest.raises(SponsorshipDenied) as denied:
        await svc.attest_for_caller("primary", dict(critical), ADDR, time_critical=True)
    assert denied.value.decision.code == "identity_required" and sent == []

    # Identity injected by the dispatcher, action off the allowlist.
    svc = AttestationService(_eas_config(tmp_path, dict(EXAMPLE_POLICY)))
    with pytest.raises(SponsorshipDenied) as denied:
        await svc.attest_for_caller("primary", dict(critical), ADDR, caller_identity="0xabc")
    assert denied.value.decision.code == "action_not_allowed" and sent == []

    # Identity bound to the dispatch, action allowed, but the write would cross
    # the cap (500k gas at 1 gwei and $3000/ETH is $1.50; cap $1).
    svc = AttestationService(_eas_config(
        tmp_path, {"daily_cap_usd": 1, "allowed_actions": ["attestation.attest"]}))
    token = set_caller_identity("0xabc")
    try:
        with pytest.raises(SponsorshipDenied) as denied:
            await svc.attest_for_caller("primary", dict(critical), ADDR)
    finally:
        reset_caller_identity(token)
    assert denied.value.decision.code == "daily_cap_exceeded" and sent == []

    # Within the cap, it signs — and the platform's own record still signs
    # unmetered with no identity at all.
    svc = AttestationService(_eas_config(
        tmp_path, {"daily_cap_usd": 50, "allowed_actions": ["attestation.attest"]}))
    out = await svc.attest_for_caller("primary", dict(critical), ADDR, caller_identity="0xabc")
    assert out["status"] == "attested" and len(sent) == 1, out
    record = await svc.attest("primary", dict(critical), ADDR)
    assert record["status"] == "attested" and len(sent) == 2, record


async def test_a_queued_capability_attestation_is_metered_against_the_caller_it_was_queued_under(
        monkeypatch, tmp_path):
    from runtime.blockchain.eas_client import EASClient
    from runtime.blockchain.services.attestation.service import AttestationService
    from runtime.blockchain.sponsorship import SponsorshipDenied

    signed: list = []

    async def _attest(self, action, agent, details, recipient=None, *, operation=None,
                      identity=None):
        signed.append((operation, identity))
        return {"status": "attested"}

    monkeypatch.setattr(EASClient, "attest", _attest)

    # Off the allowlist: refused when queued, and nothing is queued.
    svc = AttestationService(_eas_config(tmp_path, dict(EXAMPLE_POLICY)), batch_size=2)
    with pytest.raises(SponsorshipDenied) as denied:
        await svc.attest_for_caller("primary", {"action": "x"}, ADDR, caller_identity="0xabc")
    assert denied.value.decision.code == "action_not_allowed"
    assert svc._batch_processor.pending_count == 0

    # No identity with a cap: refused when queued.
    svc = AttestationService(_eas_config(tmp_path, {"daily_cap_usd": 50}), batch_size=2)
    with pytest.raises(SponsorshipDenied) as denied:
        await svc.attest_for_caller("primary", {"action": "x"}, ADDR)
    assert denied.value.decision.code == "identity_required"
    assert svc._batch_processor.pending_count == 0

    # Allowed and attributed: queued with a metered disclosure, then signed by
    # the batch under the identity it was queued under, not the flusher's.
    svc = AttestationService(_eas_config(
        tmp_path, {"daily_cap_usd": 50, "allowed_actions": ["attestation.attest"]}), batch_size=2)
    queued = await svc.attest_for_caller("primary", {"action": "x"}, ADDR,
                                         caller_identity="0x" + "AB" * 20)
    assert queued["status"] == "queued"
    assert "metered under 'attestation.attest'" in queued["disclosure"], queued
    await svc.attest("primary", {"action": "platform-record"}, ADDR)  # the flusher
    assert signed == [("attestation.attest", "0x" + "ab" * 20), (None, None)], signed


async def test_a_queued_write_the_policy_refuses_at_flush_is_dropped_not_requeued(
        monkeypatch, tmp_path):
    from runtime.blockchain.eas_client import EASClient
    from runtime.blockchain.services.attestation.batch_processor import BatchProcessor
    from runtime.blockchain.sponsorship import SponsorshipDecision, SponsorshipDenied

    async def _attest(self, action, agent, details, recipient=None, *, operation=None,
                      identity=None):
        if operation:
            raise SponsorshipDenied(SponsorshipDecision(
                False, "daily_cap_exceeded", "cap reached"))
        return {"status": "attested"}

    monkeypatch.setattr(EASClient, "attest", _attest)
    processor = BatchProcessor(_eas_config(tmp_path, {"daily_cap_usd": 50}), batch_size=10)
    await processor.add({"data": {"action": "x"}, "recipient": ADDR,
                         "operation": "attestation.attest", "identity": "0xabc"})
    await processor.add({"data": {"action": "record"}, "recipient": ADDR})
    results = await processor.flush()
    assert [r["status"] for r in results] == ["refused", "attested"], results
    assert processor.pending_count == 0, "a policy refusal was re-queued to be asked again"


async def test_batch_attest_and_revoke_are_metered(monkeypatch, tmp_path):
    from runtime.blockchain.eas_client import MAX_ATTESTATIONS_PER_BATCH
    from runtime.blockchain.services.attestation.service import AttestationService
    from runtime.blockchain.sponsorship import SponsorshipDenied

    sent: list = []
    _fake_signing(monkeypatch, [])
    _time_critical_web3(monkeypatch, sent)
    svc = AttestationService(_eas_config(tmp_path, {"daily_cap_usd": 50}))
    with pytest.raises(SponsorshipDenied) as denied:
        await svc.batch_attest([{"data": {"category": "ban_record"}, "recipient": ADDR}])
    assert denied.value.decision.code == "identity_required" and sent == []

    with pytest.raises(ValueError):
        await svc.batch_attest([{"data": {}, "recipient": ADDR}] * (MAX_ATTESTATIONS_PER_BATCH + 1),
                               caller_identity="0xabc")
    assert svc._batch_processor.pending_count == 0 and sent == []

    import web3 as _web3
    real = _web3.Web3

    class _FakeWeb3:
        HTTPProvider = staticmethod(lambda url: url)
        to_checksum_address = staticmethod(real.to_checksum_address)

        def __init__(self, provider):
            self.eth = _FakeEth(sent)

    monkeypatch.setattr(_web3, "Web3", _FakeWeb3)
    with pytest.raises(SponsorshipDenied) as denied:
        await svc.revoke("0x" + "44" * 32, "primary")
    assert denied.value.decision.code == "identity_required" and sent == []

    svc = AttestationService(_eas_config(tmp_path, dict(EXAMPLE_POLICY)))
    with pytest.raises(SponsorshipDenied) as denied:
        await svc.revoke("0x" + "44" * 32, "primary", caller_identity="0xabc")
    assert denied.value.decision.code == "action_not_allowed" and sent == []
