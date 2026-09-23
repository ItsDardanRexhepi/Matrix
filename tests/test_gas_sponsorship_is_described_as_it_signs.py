"""What the code and the documents say about gas sponsorship is what the
signers do.

Two statements had drifted from the code:

* runtime/blockchain/gas_sponsor.py said its paymaster "funds the operations
  the policy allows; the rest are refused", and that sponsor_transaction pays
  "when the sponsorship policy allows it". sponsor_transaction signs through
  unmetered_platform_signer(..., "gas_sponsor.sponsor"), an exemption listed
  in UNMETERED_PLATFORM_OPERATIONS, and an exempt signer checks nothing
  before it signs. A signing path that skips the policy has to say so where
  it is written, so each exempt call site's docstring names its exemption.

* The README, docs/blockchain.md and docs/COMPLETE_CAPABILITY_MAP.md said an
  action outside the allowlist is refused. The paymaster route reads the
  allowlist on every request, but the signer the platform uses for its own
  capability transactions reads it only when a daily cap is set. The test
  runs that signer and checks that each document describes what it did, so
  a change to either side has to bring the other along.

* sponsorship.py called its exemptions fixed call data the model never
  composes, and gas_sponsor.sponsor "the gas-sponsorship accounting path".
  The attestation capabilities reach the EAS exemptions with a recipient,
  payload, uid or schema the caller supplies, and gas_sponsor.sponsor signs
  whatever transaction it is handed. The test drives revoke_attestation's
  method and a time-critical create_attestation under a policy that allows
  nothing and caps at zero, and checks that the exemption list and the three
  documents name the capabilities that got signed.
"""
from __future__ import annotations

import ast
import pathlib

import pytest

REPO = pathlib.Path(__file__).resolve().parent.parent
POLICY_DOCS = ("README.md", "docs/blockchain.md", "docs/COMPLETE_CAPABILITY_MAP.md")


def _exempt_call_sites():
    for path in sorted((REPO / "runtime").rglob("*.py")):
        src = path.read_text()
        if "unmetered_platform_signer(" not in src:
            continue
        for fn in ast.walk(ast.parse(src)):
            if not isinstance(fn, (ast.FunctionDef, ast.AsyncFunctionDef)):
                continue
            if fn.name == "unmetered_platform_signer":
                continue
            for node in ast.walk(fn):
                if not isinstance(node, ast.Call):
                    continue
                name = getattr(node.func, "id", None) or getattr(node.func, "attr", None)
                if name != "unmetered_platform_signer":
                    continue
                actions = [a.value for a in node.args
                           if isinstance(a, ast.Constant) and isinstance(a.value, str)]
                yield path.relative_to(REPO), fn, actions


def test_every_exempt_signer_names_its_exemption_in_its_docstring():
    from runtime.blockchain.sponsorship import UNMETERED_PLATFORM_OPERATIONS

    sites = list(_exempt_call_sites())
    assert sites, "no call site of unmetered_platform_signer was found"
    silent = []
    for path, fn, actions in sites:
        assert actions, f"{path}:{fn.lineno} {fn.name} names its exemption indirectly"
        for action in actions:
            assert action in UNMETERED_PLATFORM_OPERATIONS, (
                f"{path}:{fn.name} signs as {action!r}, which is not a listed exemption")
            doc = ast.get_docstring(fn) or ""
            if action not in doc or "UNMETERED_PLATFORM_OPERATIONS" not in " ".join(doc.split()):
                silent.append(f"{path}:{fn.lineno} {fn.name} ({action})")
    assert not silent, (
        "these functions sign with no sponsorship check, and their docstrings "
        "do not say so: " + ", ".join(silent))


def test_gas_sponsor_does_not_claim_the_policy_governs_it():
    text = " ".join((REPO / "runtime/blockchain/gas_sponsor.py").read_text().split())
    for claim in ("funds the operations the policy allows",
                  "when the sponsorship policy allows it",
                  "users never pay",
                  "covers ALL gas fees"):
        assert claim not in text, f"gas_sponsor.py still says {claim!r}"


def test_the_documents_say_when_the_allowlist_is_read():
    pytest.importorskip("eth_account")
    from eth_account import Account

    from runtime.blockchain.sponsorship import (
        MeteredSigner,
        SponsorshipDenied,
        SponsorshipPolicy,
    )

    policy = SponsorshipPolicy(allowed_actions=["listed.action"], daily_cap_usd=None)
    signer = MeteredSigner(Account.create(), policy, "unlisted.action",
                           "0x" + "ab" * 20, None)
    tx = {"to": "0x" + "11" * 20, "value": 0, "gas": 21000,
          "gasPrice": 10**9, "nonce": 0, "chainId": 84532}
    try:
        signer.sign_transaction(tx)
        allowlist_read_without_a_cap = False
    except SponsorshipDenied:
        allowlist_read_without_a_cap = True

    wrong = []
    for rel in POLICY_DOCS:
        text = " ".join((REPO / rel).read_text().split())
        says_unread = ("only when a daily cap is set" in text
                       or "without reading the allowlist" in text)
        if says_unread == allowlist_read_without_a_cap:
            wrong.append(rel)
    if allowlist_read_without_a_cap:
        detail = "the capability signer now refuses an unlisted action with no cap set"
    else:
        detail = ("the capability signer signed an action outside the allowlist "
                  "with no daily cap set")
    assert not wrong, f"{detail}, and these documents say otherwise: {wrong}"


class _Sent(Exception):
    pass


def _fake_web3(sent: list):
    """Stands in for web3.Web3: builds real transaction dicts, records the raw
    signed bytes handed to send_raw_transaction, and stops there."""

    class _Call:
        def __init__(self, to):
            self._to = to

        def build_transaction(self, params):
            return {"to": self._to, "data": "0x", "value": 0, **params}

    class _Functions:
        def __init__(self, to):
            self._to = to

        def __getattr__(self, name):
            return lambda *args, **kwargs: _Call(self._to)

    class _Contract:
        def __init__(self, address):
            self.functions = _Functions(address)

    class _Eth:
        gas_price = 10**9

        def contract(self, address, abi):
            return _Contract(address)

        def get_transaction_count(self, address):
            return 0

        def send_raw_transaction(self, raw):
            sent.append(bytes(raw))
            raise _Sent()

    class FakeWeb3:
        HTTPProvider = staticmethod(lambda url: None)
        to_checksum_address = staticmethod(lambda address: address)

        def __init__(self, provider=None):
            self.eth = _Eth()

    return FakeWeb3


def test_the_exemptions_name_the_capabilities_that_reach_them(tmp_path, monkeypatch):
    pytest.importorskip("eth_account")
    pytest.importorskip("eth_abi")
    import asyncio

    import web3
    from eth_account import Account

    from runtime.blockchain.services.attestation.service import AttestationService
    from runtime.blockchain.sponsorship import SponsorshipPolicy

    key = Account.create()
    config = {
        "blockchain": {
            "rpc_url": "http://127.0.0.1:9", "chain_id": 84532,
            "eas_contract": "0x" + "42" * 20, "eas_schema": "0x" + "cd" * 32,
            "paymaster_private_key": key.key.hex(), "platform_wallet": key.address,
        },
        "paymaster": {"policy": {"allowed_actions": [], "daily_cap_usd": 0}},
        "database": {"path": str(tmp_path / "p.db")},
    }
    policy = SponsorshipPolicy.from_config(config)
    assert policy.allowed_actions is not None and not policy.allowed_actions \
        and policy.enforces_a_cap and policy.daily_cap_usd == 0, (
        "precondition: the policy allows nothing and caps at zero")

    sent: list = []
    monkeypatch.setattr(web3, "Web3", _fake_web3(sent))
    service = AttestationService(config)
    asyncio.run(service.revoke("0x" + "ab" * 32, "0x" + "cd" * 32))
    revoke_signed = len(sent) == 1
    asyncio.run(service.attest(schema_uid="0x" + "cd" * 32, data={"agent": "caller-chosen"},
                               recipient="0x" + "77" * 20, time_critical=True))
    attest_signed = len(sent) == (2 if revoke_signed else 1)

    source = (REPO / "runtime/blockchain/sponsorship.py").read_text()
    head, _, tail = source.partition("UNMETERED_PLATFORM_OPERATIONS = {")
    comment = " ".join(ln.strip().lstrip("#") for ln in head.splitlines()[-40:]
                       if ln.strip().startswith("#"))
    listing = " ".join((comment + " " + tail.split("}", 1)[0]).split())

    assert "never composes" not in listing, (
        "sponsorship.py still says the exempt call data is never composed by the model")
    assert "accounting path" not in listing, (
        "sponsorship.py still calls gas_sponsor.sponsor an accounting path")
    reached = [name for name, signed in (("revoke_attestation", revoke_signed),
                                         ("create_attestation", attest_signed)) if signed]
    assert reached, "precondition: an exempt signer signed under the policy"
    silent = [rel for rel in ("runtime/blockchain/sponsorship.py",) + POLICY_DOCS
              for name in reached
              if name not in (listing if rel.endswith(".py")
                              else " ".join((REPO / rel).read_text().split()))]
    assert not silent, (
        f"{reached} were signed with the platform key under a policy that allows "
        f"nothing and caps at zero, and these do not name them: {sorted(set(silent))}")
