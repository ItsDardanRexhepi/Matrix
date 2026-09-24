"""Every path that signs with the platform key under no sponsorship policy is
stated where the policy is documented.

The README, docs/blockchain.md and docs/COMPLETE_CAPABILITY_MAP.md said
three catalog capabilities, create_attestation, batch_attest and
revoke_attestation, reach the signers exempt from the policy. They are not
the only ones. The service dispatcher queues its own record of each
state-modifying action it completes on the same attestation queue, and the
queue signs through the eas.attest exemption once 50 have gathered; the
real-estate service keeps a queue of its own; the conversion pipeline
attests a deployment it made; and thirteen actions of Neo's blockchain tools
call EASClient.attest directly, each one a platform signature at the moment
it is called.

The tests measure this from the code:

* Every call into an exempt signer's method in runtime/ and gateway/ is found
  by reading the source, and docs/blockchain.md has to account for each one,
  by file and function, as a path that signs or as one that does not.
* Under a policy that allows nothing and caps at zero, against a stand-in
  chain, the tool actions, the dispatcher's record and the real-estate queue
  are driven, and every signature that reaches the network is recovered to
  the platform key. The three documents have to name each path that signed.
* The callers the documentation says do not sign are driven or read too,
  and fail the test if one of them starts signing.
"""
from __future__ import annotations

import ast
import asyncio
import pathlib
import re

import pytest

REPO = pathlib.Path(__file__).resolve().parent.parent
POLICY_DOCS = ("README.md", "docs/blockchain.md", "docs/COMPLETE_CAPABILITY_MAP.md")
ADDRESS = "0x" + "ab" * 20
SCHEMA = "0x" + "cd" * 32

# The methods through which a call reaches an exempt signer: EASClient.attest
# ("eas.attest"), TimeCriticalHandler.attest_now ("eas.attest_time_critical"),
# AttestationService.attest, .batch_attest and .revoke ("eas.revoke"), and
# GasSponsor.sponsor_transaction ("gas_sponsor.sponsor"). A contract's
# `functions.attest(...)` builds a transaction and is not one of them.
_EXEMPT_METHODS = {"attest", "batch_attest", "revoke", "attest_now", "sponsor_transaction"}


def _call_sites() -> set[tuple[str, str]]:
    sites = set()
    for root in ("runtime", "gateway"):
        for path in sorted((REPO / root).rglob("*.py")):
            tree = ast.parse(path.read_text(encoding="utf-8"))
            for fn in ast.walk(tree):
                if not isinstance(fn, (ast.FunctionDef, ast.AsyncFunctionDef)):
                    continue
                for node in ast.walk(fn):
                    if (isinstance(node, ast.Call) and isinstance(node.func, ast.Attribute)
                            and node.func.attr in _EXEMPT_METHODS
                            and not ast.unparse(node.func.value).endswith("functions")):
                        sites.add((str(path.relative_to(REPO)), fn.name))
    return sites


def _doc(rel: str) -> str:
    return (REPO / rel).read_text(encoding="utf-8")


def _passage(rel: str) -> str:
    """From the first mention of UNMETERED_PLATFORM_OPERATIONS to the next heading."""
    text = _doc(rel)
    start = text.index("UNMETERED_PLATFORM_OPERATIONS")
    start = text.rfind("\n\n", 0, start) + 1
    end = re.search(r"\n(#|---)", text[start:])
    return " ".join(text[start:start + (end.start() if end else len(text))].split())


def test_docs_blockchain_accounts_for_every_call_into_an_exempt_signer():
    sites = _call_sites()
    assert ("runtime/blockchain/services/service_dispatcher.py", "_attest_action") in sites, (
        "precondition: the dispatcher's record is found among the callers")
    lines = _doc("docs/blockchain.md").splitlines()
    missing = sorted(f"{path} {fn}" for path, fn in sites
                     if not any(f"`{path}`" in line and f"`{fn}`" in line for line in lines))
    assert not missing, (
        "these functions call into a signer exempt from the sponsorship policy, "
        "and docs/blockchain.md does not say whether they sign: " + ", ".join(missing))


# ── the stand-in chain ──────────────────────────────────────────────────────

class _Sent(Exception):
    pass


def _fake_web3(sent: list):
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

        def contract(self, address=None, abi=None):
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


@pytest.fixture
def chain(tmp_path, monkeypatch):
    """A policy that allows nothing and caps at zero, and a chain that records
    what is sent to it. Yields (config, platform address, sent)."""
    pytest.importorskip("eth_account")
    pytest.importorskip("eth_abi")
    import web3
    from eth_account import Account

    from runtime.blockchain.sponsorship import SponsorshipPolicy
    from runtime.blockchain.web3_manager import Web3Manager

    key = Account.create()
    config = {
        "blockchain": {
            "rpc_url": "http://127.0.0.1:9", "chain_id": 84532,
            "eas_contract": "0x" + "42" * 20, "eas_schema": SCHEMA,
            "paymaster_private_key": key.key.hex(), "platform_wallet": key.address,
            "schemas": {"document_verification": SCHEMA, "payments": SCHEMA},
        },
        "paymaster": {"policy": {"allowed_actions": [], "daily_cap_usd": 0}},
        "database": {"path": str(tmp_path / "platform.db")},
        "services": {"real_estate": {"enabled": True,
                                     "db_path": str(tmp_path / "real_estate.db")}},
    }
    policy = SponsorshipPolicy.from_config(config)
    assert policy.allowed_actions is not None and not policy.allowed_actions \
        and policy.enforces_a_cap and policy.daily_cap_usd == 0, (
        "precondition: the policy allows nothing and caps at zero")

    sent: list = []
    fake = _fake_web3(sent)
    monkeypatch.setattr(web3, "Web3", fake)

    class _Manager:
        available = True
        w3 = fake()

    monkeypatch.setattr(Web3Manager, "get_shared",
                        classmethod(lambda cls, config=None: _Manager()))
    return config, key.address, sent


def _signers(sent: list) -> set[str]:
    from eth_account import Account
    return {Account.recover_transaction(raw) for raw in sent}


# ── Neo's blockchain tools ──────────────────────────────────────────────────

def _tool_actions_calling_eas_client() -> dict[type, list[str]]:
    """For each tool in the registry, the actions whose handler calls
    EASClient(...).attest, read from its execute() dispatch."""
    import inspect

    from runtime.blockchain.registry import CAPABILITY_CLASSES

    found: dict[type, list[str]] = {}
    for cls in CAPABILITY_CLASSES:
        tree = ast.parse(inspect.getsource(inspect.getmodule(cls)))
        attesting = {fn.name for fn in ast.walk(tree)
                     if isinstance(fn, (ast.FunctionDef, ast.AsyncFunctionDef))
                     and "EASClient(" in ast.unparse(fn) and ".attest(" in ast.unparse(fn)}
        execute = next((fn for fn in ast.walk(tree)
                        if isinstance(fn, ast.AsyncFunctionDef) and fn.name == "execute"), None)
        if execute is None or not attesting:
            continue
        actions = []
        for node in ast.walk(execute):
            if (isinstance(node, ast.If) and isinstance(node.test, ast.Compare)
                    and isinstance(node.test.comparators[0], ast.Constant)):
                for stmt in node.body:
                    call = getattr(stmt, "value", None)
                    call = getattr(call, "value", call)  # through `await`
                    if (isinstance(call, ast.Call) and isinstance(call.func, ast.Attribute)
                            and call.func.attr in attesting):
                        actions.append(node.test.comparators[0].value)
        if actions:
            found[cls] = actions
    return found


_TOOL_PARAMS = {
    "agent_name": "neo", "agent_action": "anything", "details": {"k": "v"},
    "name": "someone", "address": ADDRESS, "to": ADDRESS, "amount": "1",
    "player_address": ADDRESS, "achievement": "first", "investor_address": ADDRESS,
    "contract_address": ADDRESS, "recipient": ADDRESS, "data": {"action": "anything"},
    "attestations": [{"action": "one"}, {"action": "two"}],
    "policy_holder": ADDRESS, "coverage_amount": "1", "premium": "1",
    "policy_id": "0x" + "ef" * 32, "claim_amount": "1", "reason": "r",
    "title": "work", "owner": ADDRESS, "ip_type": "copyright",
    "product_id": "p1", "product_name": "thing", "origin": "here", "status": "shipped",
    "location": "there",
}


def _signed_tool_actions(config, sent) -> dict[str, list[str]]:
    signed: dict[str, list[str]] = {}
    for cls, actions in _tool_actions_calling_eas_client().items():
        tool = cls(config)
        for action in actions:
            before = len(sent)
            asyncio.run(tool.execute(action=action, **_TOOL_PARAMS))
            if len(sent) > before:
                signed.setdefault(tool.name, []).append(action)
    return signed


def test_each_tool_action_that_signs_under_no_policy_is_named(chain):
    config, platform, sent = chain
    candidates = _tool_actions_calling_eas_client()
    assert candidates, "precondition: tool actions that call EASClient.attest are found"
    signed = _signed_tool_actions(config, sent)
    assert signed, "precondition: a tool action signed under the policy"
    assert _signers(sent) == {platform}, "precondition: the platform key signed"

    count = sum(len(actions) for actions in signed.values())
    for rel in POLICY_DOCS:
        passage = _passage(rel)
        silent = sorted(name for name in signed if f"`{name}`" not in passage)
        assert not silent, (
            f"under a policy that allows nothing and caps at zero, the tools "
            f"{sorted(signed)} signed with the platform key, and {rel} does not name "
            f"{silent} where it lists the exemptions")
        stated = re.search(r"(\d+) actions of Neo's blockchain tools", passage)
        assert stated and int(stated.group(1)) == count, (
            f"{count} tool actions signed with the platform key under a policy that "
            f"allows nothing; {rel} says {stated.group(1) if stated else 'no number'}")
    table = _doc("docs/blockchain.md")
    unnamed = sorted(f"{name}.{action}" for name, actions in signed.items()
                     for action in actions
                     if not re.search(rf"`{re.escape(name)}`[^\n]*`{re.escape(action)}`", table))
    assert not unnamed, (
        f"these tool actions signed with the platform key under a policy that "
        f"allows nothing, and docs/blockchain.md does not name them: {unnamed}")


# ── the service dispatcher's record, and the real-estate queue ──────────────

def test_the_dispatchers_record_is_signed_under_no_policy_and_named(chain):
    from runtime.blockchain.services.service_dispatcher import ServiceDispatcher

    config, platform, sent = chain
    dispatcher = ServiceDispatcher(config)
    threshold = dispatcher._get_registry().get("attestation")._batch_processor.batch_size

    async def record(n):
        for i in range(n):
            await dispatcher._attest_action("create_did", "did_identity",
                                            {"i": i}, {"status": "ok"}, actor=ADDRESS)

    asyncio.run(record(threshold - 1))
    assert not sent, "precondition: below the threshold nothing is sent"
    asyncio.run(record(1))
    assert len(sent) == threshold and _signers(sent) == {platform}, (
        f"precondition: the {threshold}th record sends the queue, one platform "
        f"signature each ({len(sent)} sent)")

    silent = [rel for rel in POLICY_DOCS if "service dispatcher" not in _passage(rel).lower()]
    assert not silent, (
        f"the service dispatcher's record of a completed action was signed with the "
        f"platform key, {len(sent)} times, under a policy that allows nothing and caps "
        f"at zero, and these do not say so where they list the exemptions: {silent}")


def test_the_real_estate_queue_is_signed_under_no_policy_and_named(chain):
    from runtime.blockchain.services.real_estate.service import RealEstateService

    config, platform, sent = chain
    service = RealEstateService(config)

    async def attest(n):
        for _ in range(n):
            await service._attest(schema="document_verification",
                                  data={"category": "real_estate_document"},
                                  recipient=ADDRESS)

    threshold = service._attestation_svc()._batch_processor.batch_size
    asyncio.run(attest(threshold))
    assert len(sent) == threshold and _signers(sent) == {platform}, (
        f"precondition: the real-estate service's queue was sent ({len(sent)} sent)")

    silent = [rel for rel in POLICY_DOCS if "services.real_estate.enabled" not in _passage(rel)]
    assert not silent, (
        "the real-estate service's attestations were signed with the platform key "
        "under a policy that allows nothing, and these do not say so where they "
        f"list the exemptions: {silent}")


def test_the_conversion_attestation_is_named():
    source = _doc("runtime/blockchain/services/contract_conversion/service.py")
    convert = next(fn for fn in ast.walk(ast.parse(source))
                   if isinstance(fn, ast.AsyncFunctionDef) and fn.name == "convert")
    assert "EASClient(" in ast.unparse(convert) and ".attest(" in ast.unparse(convert), (
        "precondition: the conversion pipeline attests a deployment")
    silent = [rel for rel in POLICY_DOCS if "conversion.auto_deploy" not in _passage(rel)]
    assert not silent, (
        "the conversion pipeline attests the contract it deployed through EASClient.attest, "
        f"with no policy check, and these do not say so: {silent}")


# ── the callers that do not sign ────────────────────────────────────────────

def test_the_callers_documented_as_not_signing_do_not_sign(chain):
    from runtime.blockchain.services.cross_border.service import CrossBorderService
    from runtime.blockchain.services.insurance.claims_processor import ClaimsProcessor
    from runtime.blockchain.services.registry import ServiceRegistry
    from runtime.blockchain.services.x402_payments.limit_updater import LimitUpdater

    config, _, sent = chain
    payment = {"payment_id": "p", "sender": ADDRESS, "recipient": ADDRESS,
               "source_amount": 1, "source_currency": "USD",
               "destination_currency": "EUR", "converted_amount": 1}

    async def drive():
        for _ in range(60):
            await CrossBorderService(config)._attest_payment(payment)
            await ClaimsProcessor(config, None)._attest_claim("c", "approved", 1.0)
            await LimitUpdater(config)._attest_limit_change(
                "agent", {"changed_fields": {}, "authorized_by": ADDRESS, "change_hash": "h"})

    asyncio.run(drive())
    assert not sent, (
        f"a cross-border payment, an insurance claim or an x402 limit change now "
        f"reaches the chain ({len(sent)} sent); docs/blockchain.md says they do not sign")

    nft = ServiceRegistry(config).get("nft_services")
    assert nft._royalty._attestation is None, (
        "the NFT service now has an attestation service for royalty sales; "
        "docs/blockchain.md says process_sale attests nothing")

    constructed = sum(len(re.findall(r"\bGasSponsor\(", path.read_text(encoding="utf-8")))
                      for path in (REPO / "runtime").rglob("*.py"))
    stated = re.search(r"(\d+) services construct a `GasSponsor`", _doc("docs/blockchain.md"))
    assert stated and int(stated.group(1)) == constructed, (
        f"{constructed} places construct a GasSponsor; docs/blockchain.md says "
        f"{stated.group(1) if stated else 'nothing'}")

    uncalled = {"route_fee": "runtime/blockchain/services/neosafe.py",
                "route_revenue": "runtime/blockchain/services/neosafe.py",
                "process_usage": "runtime/blockchain/services/ip_royalties/royalty_enforcement.py",
                "sponsor_transaction": "runtime/blockchain/gas_sponsor.py"}
    called = []
    for root in ("runtime", "gateway"):
        for path in (REPO / root).rglob("*.py"):
            rel = str(path.relative_to(REPO))
            text = path.read_text(encoding="utf-8")
            for method, home in uncalled.items():
                if rel != home and re.search(r"\." + method + r"\(", text):
                    called.append(f"{rel} calls {method}")
    assert not called, (
        "docs/blockchain.md says nothing calls these, and something now does: "
        + ", ".join(called))
