"""No request composes a call the platform's key signs.

THE FIRST DEFECT (a security review of fix/oldq-census). Neo's
``smart_contract`` tool had a ``send`` action. It built
``contract.functions[function_name](*args)`` against the ``contract_address``
and ``abi`` the request wrote, with the request's ``value``, and signed it with
the platform's key from the platform wallet. Pointed at the EAS contract with
EASClient's own ABI it signed an ``attest`` whose schema, recipient and data the
request wrote (a platform "agent_registration" for any name, which
``agent_identity.verify`` accepts) and a ``revoke`` of any uid; pointed at an
NFT contract, a ``transferFrom(B, A, id)``. Each of those effects is refused
where it has a name. Its reach is ``eas``'s: Neo's tools, which the operator's
chat holds. And ``MeteredSigner`` consulted the sponsorship policy only when a
daily cap was set, so an operator who set ``allowed_actions`` and no cap had
every capability signature signed whatever the list said.

THE SECOND (the review of that repair). The first census passed any signed call
whose OUTER function was named in the source, and the services layer, which a
user session reaches through the capability route and through chat, signs
named functions that carry a call or a message the request wrote:

  tba.execute_as_tba           IERC6551Account.execute(to, value, data,
                               operation) on the contract the request names as
                               the account, with an ETH value from the
                               platform wallet. Driven over HTTP with a session
                               token: the platform signed it, value 10**20, to
                               an address a contract with a payable execute
                               could hold. Operation 1 is a DELEGATECALL.
  ccip.send_cross_chain_message  ccipSend / Mailbox.dispatch / publishMessage /
  ccip.bridge_hyperlane          callContract with the request's bytes. The
  ccip.bridge_wormhole           receiving chain hands its contract the
  ccip.bridge_axelar             platform's wallet as the message's sender.
  ccip.bridge_token_ccip         the same message riding a token transfer
                               (its data and extraArgs were the request's).

The census below, taught to read what a named function's bytes inputs carry,
found two more of the same shape, both attestations: advanced_governance's
``submit_retropgf`` signed an EAS attest whose data and recipient the request
wrote, under the platform's own schema by default; and
``kyc.issue_kyc_credential`` attests that an address passed KYC on a
``verification_result`` read from the request itself.

THE CHANGE. ``smart_contract`` writes nothing. ``execute_as_tba``, the four
message sends and ``submit_retropgf`` answer with a refusal before anything is
built or signed, in the service itself; ``bridge_token_ccip`` still bridges the
platform's own tokens and refuses a request that brings a message with them;
and every door refuses all six and the KYC credential, whoever asks
(runtime/access_policy.py REFUSED_ON_REQUEST). The KYC method stays callable in
process, where nothing calls it. ``MeteredSigner`` checks a configured
allowlist on every signature, cap or no cap.

THE CLASS, AND THE CENSUS. A platform signature on a call or a message the
request composed: the platform wallet becomes the sender of words somebody else
wrote. The walk reads every module under ``runtime/`` and ``gateway/``, finds
every ``sign_transaction(`` and ``send_transaction(`` call, follows what is
signed back to where it is built, and fails:

  * on a transaction built from a function chosen at run time
    (``functions[...]``, ``getattr``, ``get_function_by_*``);
  * on a transaction written out by hand whose ``data`` is not a constant, one
    unpacked from what the function was handed, one whose keys it cannot read,
    and one whose data is replaced or updated after it is built (``[...] =``,
    ``update``, ``setdefault``, ``|=``);
  * on a call of a named function that carries bytes of any length — calldata,
    a message, a payload; a ``bytes`` or ``bytes[]`` input of the function's
    ABI, inside a tuple too — that the function was handed: a parameter, a local
    name drawn from one, a ``self`` attribute some method of the class writes
    from what it was handed, or a module name a function writes that way. A def
    nested in another sees what the outer one was handed;
  * wherever it cannot read what is signed, which function is called, or that
    function's inputs; and on a signing method it does not read as a direct call
    inside a function: taken as a value, called in a lambda, at module or class
    level, or reached by its name through getattr.

Some sites are listed by name, each for a stated reason: the two signers that
sign what their caller hands them (every caller is itself a site the walk
reads), the two deployments (``tests/test_no_deployment_claims.py`` and the
``conversion.auto_deploy`` switch govern those), ``GasSponsor
.sponsor_transaction``, which signs whatever it is handed and which nothing
calls, pinned here; and, at the level of one bytes input, what is not a call or
a message the platform's wallet sends (an address encoded as bytes; the input
an Automation upkeep reads as its own; the twin attestation signer, which the
twin census walks), what no request reaches (every door refuses its pair), and
the stated limit below.

WHAT THIS DOES NOT COVER, stated. A call the platform's key signs to a
contract that then makes another call the request wrote: ``governance``
schedule_operation and execute_operation (a timelock's target, value and data),
``dao`` create_proposal and execute_proposal (a governor's targets and
calldatas). The contract makes the inner call as itself, under a role the
platform holds there, never as the platform's wallet; whether the platform
holds such a role is a deployment fact this repository cannot see, and the two
tools are Neo's, which a caller without the operator key never holds. Nor does
it cover a message the platform signs rather than a transaction (the paymaster's
sponsorship signature is over an operation the caller's own account executes).
The walk reads one function at a time: what a helper method returns counts as
the request's only when the call hands the helper something the request
carried; a request carried in another object's state, or a signing method
reached through a name computed at run time, it does not follow. Which of a
named function's other arguments must be the caller's own is the seam's
(``ACTION_BENEFICIARY_FIELDS``) and the gate's; an address a transfer
delivers to is not bound (CLOSEOUT §0 D), and the services layer's
``nft_lending`` borrow takes ``on_behalf_of`` from the request (§0 A10).

CONTROL. Of the file's 63 tests, 29 are marked [control]. At fix/oldq-census
420a88a all 29 fail; at d3dcf89 the 21 from the services section on fail (the
first round's 8 — the tool's five, the allowlist's two and the census of outer
functions — were fixed at 7abfa21); all 63 pass at the fix. The 34
marked [guard] pass at all three. The planted shapes are guards of the census
itself: on 15 of them the census as it stood at d3dcf89 reported nothing.
"""

from __future__ import annotations

import ast
import asyncio
import json
import pathlib
import re
import sys
import time
from typing import NamedTuple
from unittest.mock import MagicMock

import pytest

ROOT = pathlib.Path(__file__).resolve().parent.parent
A = "0x" + "a1" * 20      # the caller's bound identity
B = "0x" + "b2" * 20      # somebody else
EAS = "0x" + "4e" * 20
NFT = "0x" + "5f" * 20
SCHEMA = "0x" + "cd" * 32
CFG = {"blockchain": {
    "network": "base-sepolia", "rpc_url": "http://127.0.0.1:1",
    "paymaster_private_key": "0x" + "1" * 64, "platform_wallet": A,
    "eas_contract": EAS, "eas_schema": SCHEMA}}


def _eas_abi():
    from runtime.blockchain.eas_client import EAS_ATTEST_ABI
    return EAS_ATTEST_ABI


_REVOKE_ABI = [{"inputs": [{"components": [
    {"name": "schema", "type": "bytes32"},
    {"components": [{"name": "uid", "type": "bytes32"}, {"name": "value", "type": "uint256"}],
     "name": "data", "type": "tuple"}], "name": "request", "type": "tuple"}],
    "name": "revoke", "outputs": [], "stateMutability": "payable", "type": "function"}]
_TRANSFER_FROM_ABI = [{"inputs": [{"name": "from", "type": "address"},
                                  {"name": "to", "type": "address"},
                                  {"name": "tokenId", "type": "uint256"}],
                       "name": "transferFrom", "outputs": [],
                       "stateMutability": "nonpayable", "type": "function"}]

#: The three calls the review had the platform key sign through ``send``.
SENDS = {
    "an EAS attestation the request wrote": lambda: {
        "contract_address": EAS, "abi": _eas_abi(), "function_name": "attest",
        "args": [[SCHEMA, [B, 0, True, "0x" + "00" * 32, "0x" + "ab" * 64, 0]]]},
    "a revocation of any uid": lambda: {
        "contract_address": EAS, "abi": _REVOKE_ABI, "function_name": "revoke",
        "args": [[SCHEMA, ["0x" + "ef" * 32, 0]]]},
    "an NFT moved from somebody else": lambda: {
        "contract_address": NFT, "abi": _TRANSFER_FROM_ABI,
        "function_name": "transferFrom", "args": [B, A, 1]},
}


@pytest.fixture
def signer_reached(monkeypatch):
    """Every platform signer the smart_contract tool asks for."""
    from runtime.blockchain.smart_contracts import SmartContracts
    reached = []

    async def spy(self, what):
        reached.append(what)
        raise RuntimeError("stopped at the platform signer by the test")

    monkeypatch.setattr(SmartContracts, "_platform_signer", spy)
    monkeypatch.setattr(SmartContracts, "web3", property(lambda self: MagicMock()))
    return reached


# ── the tool ─────────────────────────────────────────────────────────────

@pytest.mark.parametrize("case", sorted(SENDS))
def test_smart_contract_signs_no_call_the_request_wrote(case, signer_reached):
    """[control]"""
    from runtime.blockchain.smart_contracts import SmartContracts
    out = json.loads(asyncio.run(SmartContracts(CFG).execute(action="send", **SENDS[case]())))
    assert signer_reached == [], f"{case}: the request's call reached the platform signer"
    assert out.get("ok") is False and out.get("code") == "denied", out


async def test_through_the_seam_as_the_tool_loop_calls_it(signer_reached):
    """[control] The real pre_action, then the tool, as react_loop runs them.
    The seam has no field to check on ``send`` and the gate runs OBSERVE without
    the private package, so the tool itself has to refuse."""
    sys.path.insert(0, str(ROOT / "tests"))
    from test_twins_seam import _stack

    from runtime.blockchain.smart_contracts import SmartContracts
    args = {"action": "send", **SENDS["an EAS attestation the request wrote"]()}
    verdict = await _stack().pre_action("smart_contract", args, {"wallet": A})
    assert verdict["approved"] is True, "precondition: the seam passes it to an approving gate"
    out = json.loads(await SmartContracts(CFG).execute(**args))
    assert signer_reached == [], "the request's call reached the platform signer"
    assert out.get("ok") is False and out.get("code") == "denied", out


def test_the_tool_offers_no_write():
    """[control] A model reads the schema to choose an action; ``send`` is not
    in it, and the description does not promise writes."""
    from runtime.blockchain.smart_contracts import SmartContracts
    tool = SmartContracts(CFG)
    assert "send" not in tool.parameters["properties"]["action"]["enum"]
    assert "value" not in tool.parameters["properties"], "an ETH value is only for a write"
    assert "gas for writes" not in tool.description.lower(), tool.description


def test_a_read_still_reads_and_signs_nothing(signer_reached):
    """[guard] ``call`` is a read: an eth_call, no signature."""
    from runtime.blockchain.smart_contracts import SmartContracts
    out = json.loads(asyncio.run(SmartContracts(CFG).execute(
        action="call", contract_address=NFT, abi=_TRANSFER_FROM_ABI,
        function_name="transferFrom", args=[B, A, 1])))
    assert signer_reached == []
    assert "result" in out, out


# ── the second layer: the allowlist with no cap ──────────────────────────

class _Account:
    address = A

    def sign_transaction(self, tx):
        return "signed"


_TX = {"to": NFT, "value": 0, "gas": 21000, "gasPrice": 10**9, "nonce": 0, "chainId": 84532}


def test_a_configured_allowlist_binds_with_no_cap(tmp_path):
    """[control]"""
    from runtime.blockchain.sponsorship import (
        MeteredSigner, SponsorshipDenied, SponsorshipPolicy)
    policy = SponsorshipPolicy(allowed_actions=["nfts.transfer"], daily_cap_usd=None,
                               db_path=tmp_path / "spend.db")
    signer = MeteredSigner(_Account(), policy, "smart_contracts.send", A, None)
    with pytest.raises(SponsorshipDenied) as refused:
        signer.sign_transaction(_TX)
    assert refused.value.decision.code == "action_not_allowed"


async def test_the_signer_a_capability_gets_reads_the_allowlist(tmp_path, monkeypatch):
    """[control] Built from configuration, as every capability's
    ``_platform_signer`` builds it."""
    from runtime.blockchain.sponsorship import SponsorshipDenied, platform_signer
    monkeypatch.setattr("eth_account.Account.from_key", staticmethod(lambda _k: _Account()))
    cfg = {"blockchain": {**CFG["blockchain"],
                          "paymaster": {"policy": {"allowed_actions": ["nfts.transfer"]}}},
           "database": {"path": str(tmp_path / "x.db")}}
    signer = await platform_signer(cfg, "smart_contracts.send")
    with pytest.raises(SponsorshipDenied):
        signer.sign_transaction(_TX)


def test_a_listed_action_with_no_cap_still_signs(tmp_path):
    """[guard]"""
    from runtime.blockchain.sponsorship import MeteredSigner, SponsorshipPolicy
    policy = SponsorshipPolicy(allowed_actions=["nfts.transfer"], daily_cap_usd=None,
                               db_path=tmp_path / "spend.db")
    assert MeteredSigner(_Account(), policy, "nfts.transfer", A, None).sign_transaction(_TX) == "signed"


def test_no_policy_at_all_still_signs(tmp_path):
    """[guard] An operator who configured nothing sees no new refusal."""
    from runtime.blockchain.sponsorship import MeteredSigner, SponsorshipPolicy
    policy = SponsorshipPolicy(allowed_actions=None, daily_cap_usd=None,
                               db_path=tmp_path / "spend.db")
    assert MeteredSigner(_Account(), policy, "anything.at_all", "", None).sign_transaction(_TX) == "signed"


# ── the services layer: a call or a message the request composed ────────

ACCOUNT = "0x" + "ee" * 20   # a contract the request names as the account
DRAIN_TO = "0x" + "dd" * 20
TBA_EXECUTE = {"account": ACCOUNT, "to": DRAIN_TO, "value": 10**20,
               "data": "0xdeadbeef", "operation": 1}
MESSAGES = {
    "send_cross_chain_message": {"destination_chain_selector": 16015286601757825753,
                                 "receiver": B, "data": "0xdeadbeef"},
    "bridge_hyperlane": {"destination_domain": 1, "recipient": B, "message": "0xdeadbeef"},
    "bridge_wormhole": {"payload": "0xdeadbeef"},
    "bridge_axelar": {"destination_chain": "ethereum", "destination_contract": B,
                      "payload": "0xdeadbeef"},
}
CCIP_CFG = {**CFG, "services": {"ccip": {
    "hyperlane_mailbox": "0x" + "61" * 20, "wormhole_core": "0x" + "62" * 20,
    "axelar_gateway": "0x" + "63" * 20}}}
RETROPGF = {"project_id": "p1", "recipient": B, "metadata_uri": "ipfs://x"}
KYC_ASK = {"subject": B, "kyc_level": "enhanced",
           "verification_result": {"sanctions_screened": True, "review_answer": "GREEN"}}


class _Fn:
    def __init__(self, to, name, args):
        self.to, self.name, self.args = to, name, args

    def build_transaction(self, fields):
        return {"to": self.to, "fn": self.name, "args": self.args, **fields}

    def call(self):
        return 0


class _Functions:
    def __init__(self, to):
        self._to = to

    def __getattr__(self, name):
        return lambda *args: _Fn(self._to, name, args)


class _Contract:
    def __init__(self, address):
        self.functions = _Functions(address)


class _Chain:
    """The shared Web3Manager with its chain faked and its signer recorded:
    every transaction handed to send_transaction is one the platform's key
    would have signed."""

    available = True
    chain_id = 84532
    paymaster_key = "0x" + "1" * 64

    def __init__(self):
        self.signed: list[dict] = []
        self.w3 = MagicMock()
        self.w3.to_checksum_address = lambda a: a
        self.w3.eth.gas_price = 1
        self.w3.eth.get_transaction_count = lambda _a: 0

    def load_contract(self, address, abi):
        return _Contract(address)

    def get_account(self):
        account = MagicMock()
        account.address = A
        return account

    async def send_transaction(self, tx, *, action=None):
        self.signed.append(tx)
        return "0x" + "12" * 32

    def explorer_url(self, tx_hash):
        return ""


@pytest.fixture
def chain(monkeypatch):
    from runtime.blockchain.web3_manager import Web3Manager
    fake = _Chain()
    monkeypatch.setattr(Web3Manager, "get_shared", classmethod(lambda cls, config=None: fake))
    return fake


async def test_the_tba_service_executes_no_call_the_request_wrote(chain):
    """[control] The review's reproduction, at the service."""
    from runtime.blockchain.services.tba.service import TokenBoundAccountService
    out = await TokenBoundAccountService(CFG).execute_as_tba(**TBA_EXECUTE)
    assert chain.signed == [], "the platform signed a call the request wrote"
    assert out["status"] == "refused" and out["refused"] is True, out


async def test_a_session_has_the_platform_execute_nothing_over_http(chain, tmp_path):
    """[control] The review drove this through the real door: a user session's
    bearer token, POST /api/v1/capabilities/execute_as_tba/invoke, the gate
    running OBSERVE as it does without the private package. HTTP 200, and the
    platform signed value 10**20 to the account the request named."""
    from aiohttp.test_utils import TestClient, TestServer

    server = _server(tmp_path)
    async with TestClient(TestServer(server.create_app())) as client:
        await _with_session(server)
        resp = await client.post("/api/v1/capabilities/execute_as_tba/invoke",
                                 headers={"Authorization": "Bearer 0xTEST_SESSION"},
                                 json={"params": TBA_EXECUTE})
        status = resp.status
    assert chain.signed == [], f"HTTP {status}: the platform signed {chain.signed}"
    assert status == 403, status


@pytest.mark.parametrize("caller_kind", ["session", "operator", ""])
async def test_no_chat_has_the_platform_execute_as_a_tba(chain, caller_kind):
    """[control] Trinity's hand-off, which a session's chat holds, as the review
    drove it: the default gate, Neo, the real dispatcher and service."""
    from runtime.tools.dispatcher import ToolDispatcher
    out = await ToolDispatcher({"workspace": "."}).dispatch(
        "request_execution", {"action": "execute_as_tba", "params": TBA_EXECUTE},
        agent_name="trinity", caller_identity=A, caller_kind=caller_kind)
    assert chain.signed == [], f"a {caller_kind or 'caller-less'} chat had the platform sign"
    assert out.ok is False and "[DENIED]" in out.model_text, out.model_text


@pytest.mark.parametrize("method", sorted(MESSAGES))
async def test_the_platform_sends_no_message_the_request_wrote(chain, method):
    """[control]"""
    from runtime.blockchain.services.ccip.service import CrossChainMessagingService
    out = await getattr(CrossChainMessagingService(CCIP_CFG), method)(**MESSAGES[method])
    assert chain.signed == [], f"{method}: the platform signed {chain.signed}"
    assert out["status"] == "refused", out


async def test_a_token_bridge_carries_no_message_the_request_wrote(chain):
    """[control] The same message, riding the platform's own tokens."""
    from runtime.blockchain.services.ccip.service import CrossChainMessagingService
    svc = CrossChainMessagingService(CCIP_CFG)
    for extra in ({"data": "0xdeadbeef"}, {"extra_args": "0x97a657c9" + "00" * 32}):
        out = await svc.bridge_token_ccip(destination_chain_selector=1, receiver=B,
                                          token=NFT, amount=5, **extra)
        assert chain.signed == [], f"{extra}: the platform signed {chain.signed}"
        assert out["status"] == "refused", out


async def test_a_token_bridge_still_bridges_and_says_nothing(chain):
    """[guard] With no message asked for, it still signs the ccipSend, and the
    message it carries is empty: no data, the router's default extraArgs."""
    from runtime.blockchain.services.ccip.service import CrossChainMessagingService
    out = await CrossChainMessagingService(CCIP_CFG).bridge_token_ccip(
        destination_chain_selector=1, receiver=B, token=NFT, amount=5)
    assert out["status"] == "submitted", out
    (tx,) = chain.signed
    assert tx["fn"] == "ccipSend"
    receiver, data, amounts, _fee_token, extra_args = tx["args"][1]
    assert data == b"" and extra_args == b"", tx["args"]
    assert receiver == bytes.fromhex(B[2:]).rjust(32, b"\x00") and amounts == [(NFT, 5)]


async def test_the_platform_attests_no_retropgf_application_the_request_wrote(chain):
    """[control] An EAS attest with the request's data and recipient, under
    blockchain.eas_schema by default: the platform's own registrations' schema."""
    from runtime.blockchain.services.advanced_governance.service import (
        AdvancedGovernanceService)
    out = await AdvancedGovernanceService(CFG).submit_retropgf(**RETROPGF)
    assert chain.signed == [], f"the platform signed {chain.signed}"
    assert out["status"] == "refused", out


# ── the doors: the KYC credential, and every pair now refused ────────────

@pytest.fixture
def dispatched(monkeypatch):
    """Every action that reached ServiceDispatcher.execute, under a gate that
    allows everything, so a refusal can only be the door's."""
    from runtime.blockchain.services.service_dispatcher import ServiceDispatcher

    calls: list[str] = []

    class _Allow:
        async def initialize(self):
            return None

        async def evaluate(self, action, context):
            return {"allow": True}

    async def execute(self, action, service=None, params=None, **kwargs):
        calls.append(action if not service else f"{action}@{service}")
        return json.dumps({"status": "ok", "result": {"status": "recorded by the test"}})

    monkeypatch.setattr(ServiceDispatcher, "execute", execute)
    monkeypatch.setattr("runtime.security.get_morpheus_security", lambda *a, **k: _Allow())
    return calls


def _server(tmp_path):
    sys.path.insert(0, str(ROOT / "tests"))
    from test_capability_catalog_truth import _session_server
    from test_route_sweep import SWEEP_CONFIG
    return _session_server(tmp_path, SWEEP_CONFIG)


async def _with_session(server):
    now = time.time()
    await server.wallet_sessions.add(token="0xTEST_SESSION", address="apple:sub",
                                     issued_at=now, expires_at=now + 3600)


#: Every action newly refused at the doors, with what a request would send.
NEWLY_REFUSED = {"execute_as_tba": TBA_EXECUTE, "submit_retropgf": RETROPGF,
                 "issue_kyc_credential": KYC_ASK, **MESSAGES}
HEADERS = {"session": {"Authorization": "Bearer 0xTEST_SESSION"},
           "operator": {"Authorization": "Bearer k"}}


@pytest.mark.parametrize("who", sorted(HEADERS))
async def test_no_http_door_dispatches_them(dispatched, tmp_path, who):
    """[control] Capability invoke and /bridge/v1/action, for a session and for
    the operator key: answered 403 before the dispatcher runs."""
    from aiohttp.test_utils import TestClient, TestServer

    server = _server(tmp_path)
    answered = {}
    async with TestClient(TestServer(server.create_app())) as client:
        await _with_session(server)
        for action, params in NEWLY_REFUSED.items():
            resp = await client.post(f"/api/v1/capabilities/{action}/invoke",
                                     headers=HEADERS[who], json={"params": params})
            answered[f"invoke {action}"] = resp.status
            resp = await client.post("/bridge/v1/action", headers=HEADERS[who],
                                     json={"action": action, "params": params,
                                           "session_id": "s1"})
            answered[f"bridge {action}"] = resp.status
    assert dispatched == [], f"the {who}'s doors ran {dispatched}"
    assert set(answered.values()) == {403}, answered


@pytest.mark.parametrize("tool,agent,caller_kind", [
    ("request_execution", "trinity", "session"), ("request_execution", "trinity", "operator"),
    ("platform_action", "neo", "operator"), ("platform_action", "neo", "")])
async def test_no_chat_door_dispatches_them(dispatched, tool, agent, caller_kind):
    """[control]"""
    from runtime.tools.dispatcher import ToolDispatcher
    for action, params in NEWLY_REFUSED.items():
        out = await ToolDispatcher({"workspace": "."}).dispatch(
            tool, {"action": action, "params": params},
            agent_name=agent, caller_identity=A, caller_kind=caller_kind)
        assert out.ok is False and "[DENIED]" in out.model_text, (action, out.model_text)
    assert dispatched == [], f"{tool} ran {dispatched}"


async def test_the_platforms_own_code_still_reaches_the_kyc_service(monkeypatch):
    """[guard] The KYC refusal is at the doors. In process, the dispatcher still
    runs the service, whose own gates decide; nothing in the platform calls it."""
    from runtime.blockchain.services.kyc.service import KYCService
    from runtime.blockchain.services.service_dispatcher import ServiceDispatcher

    ran = []

    async def issue(self, **params):
        ran.append(params.get("subject"))
        return {"status": "not_verified", "refused": True}

    monkeypatch.setattr(KYCService, "issue_kyc_credential", issue)
    d = ServiceDispatcher({})
    d._get_registry()._instances["kyc"] = KYCService({})
    await d.execute("issue_kyc_credential", params=dict(KYC_ASK))
    assert ran == [B], ran


def test_every_refused_pair_is_offered_nowhere():
    """[control] Each is refused by name at every door, catalogued as
    unavailable (still routed, so a caller hears the refusal, not a 404), and
    the six refused in the service say why without signing."""
    from runtime.access_policy import REFUSED_ON_REQUEST, refused_on_request
    from runtime.capabilities import catalog
    for action in NEWLY_REFUSED:
        assert refused_on_request(action), action
        cap = catalog.get_by_id(action)
        assert cap is not None and cap["available"] is False, (action, cap)
    for (service, method), statement in REFUSED_ON_REQUEST.items():
        assert statement.endswith("Nothing was signed."), (service, method)


# ── the census ───────────────────────────────────────────────────────────

SIGNING_CALLS = frozenset({"sign_transaction", "send_transaction"})
DATA_KEYS = frozenset({"data", "input"})
LOOKUPS = frozenset({"get_function_by_name", "get_function_by_selector",
                     "get_function_by_signature", "get_function_by_identifier",
                     "find_functions_by_name", "find_functions_by_identifier"})
NAME_LOOKUPS = frozenset({"getattr", "attrgetter", "methodcaller"})
MUTATORS = frozenset({"update", "append", "extend", "insert", "setdefault",
                      "__setitem__", "add"})
#: An ABI type that carries bytes of any length: calldata, a message, a payload.
DYNAMIC_BYTES = re.compile(r"^bytes(\[\d*\])*$")
_SCOPES = (ast.FunctionDef, ast.AsyncFunctionDef, ast.Lambda, ast.ClassDef)


class Site(NamedTuple):
    """One finding: a signing call (kind 'built', 'deployment' or 'handed'),
    bytes one carries that the function was handed ('carries', with the ABI
    path of the input), or a signing method the walk cannot read ('unread')."""
    qual: str
    line: int
    kind: str
    problem: str | None
    path: str | None = None


#: The signers that sign what their caller hands them. Every caller of theirs
#: calls ``sign_transaction(`` or ``send_transaction(`` itself, so the walk
#: reads each one at its own site.
PASS_THROUGH = {
    ("runtime/blockchain/sponsorship.py", "MeteredSigner.sign_transaction"),
    ("runtime/blockchain/web3_manager.py", "Web3Manager.send_transaction"),
}
#: Deployments. The twin's is unreferenced (its ``deploy`` is refused,
#: tests/test_no_deployment_claims.py); the conversion pipeline's runs only with
#: ``conversion.auto_deploy`` set, which the README documents.
DEPLOYMENTS = {
    ("runtime/blockchain/smart_contracts.py", "SmartContracts._deploy_disabled_implementation"),
    ("runtime/blockchain/services/contract_conversion/service.py",
     "ContractConversionService._compile_and_deploy"),
}
#: Signs a transaction whose to, value and data it is handed. Nothing calls it
#: (test_nothing_calls_the_signer_that_signs_what_it_is_handed).
UNCALLED = {("runtime/blockchain/gas_sponsor.py", "GasSponsor.sponsor_transaction")}

_CCIP = "runtime/blockchain/services/ccip/service.py"
_INNER_CALL = (
    "an inner call the request wrote, which the timelock or governor the request "
    "names makes as ITSELF, under a role the platform holds there, never as the "
    "platform's wallet; the governance and dao tools are Neo's, which a caller "
    "without the operator key never holds (test_the_inner_call_tools_are_the_operators)")
#: Bytes a signed call carries that the function was handed, and which are not
#: a call or a message the platform's wallet sends — or which are governed by
#: another walk — each with the reason. Keyed on (file, function, the input's
#: path in the ABI).
LISTED_BYTES = {
    ("runtime/blockchain/governance.py", "Governance._schedule", "data"): _INNER_CALL,
    ("runtime/blockchain/governance.py", "Governance._execute_op", "data"): _INNER_CALL,
    ("runtime/blockchain/daos.py", "DAOs._create_proposal", "calldatas"): _INNER_CALL,
    ("runtime/blockchain/daos.py", "DAOs._execute_proposal", "calldatas"): (
        "the calls of a proposal the governor's vote passed: execute runs only "
        "calldatas that hash to that proposal, and the governor makes them as itself"),
    (_CCIP, "CrossChainMessagingService.bridge_token_ccip", "message.receiver"): (
        "the receiver's address, checksummed and left-padded to 32 bytes: where "
        "the platform's own tokens go, not a message (test_the_listed_addresses_are_addresses)"),
    (_CCIP, "CrossChainMessagingService.bridge_stargate", "to"): (
        "the recipient's address, checksummed, as 20 bytes: where the platform's "
        "own tokens go, not a message (test_the_listed_addresses_are_addresses)"),
    ("runtime/blockchain/services/oracles_plus/service.py",
     "OraclesPlusService.register_keeper_job", "requestParams.checkData"): (
        "the input the Automation network hands the upkeep contract the request "
        "named, as that contract's own; no call is made in the platform's name"),
    ("runtime/blockchain/eas_client.py", "EASClient.attest", "request.data.data"): (
        "the twin tools' attestation signer: it encodes (platform, action, agent, "
        "timestamp) from what its caller hands it, and every twin attestation is "
        "walked by tests/test_every_twin_attestation_is_the_platforms_own.py"),
}
#: Bytes the function was handed, at a service method no request reaches:
#: every door refuses the (service, method) a request would run to get there
#: (runtime/access_policy.py REFUSED_ON_REQUEST), and the platform's own code
#: calls it in process.
DOOR_REFUSED = {
    ("runtime/blockchain/services/attestation/time_critical.py",
     "TimeCriticalHandler.attest_now", "request.data.data"): ("attestation", "attest"),
    ("runtime/blockchain/services/kyc/service.py",
     "KYCService.issue_kyc_credential", "request.data.data"): ("kyc", "issue_kyc_credential"),
}


def _own_nodes(fn):
    """The nodes of *fn*'s own body, not of a def, lambda or class inside it."""
    stack = list(ast.iter_child_nodes(fn))
    while stack:
        node = stack.pop()
        yield node
        if not isinstance(node, _SCOPES):
            stack.extend(ast.iter_child_nodes(node))


def _functions(tree):
    """(qualified name, function, enclosing class or None, enclosing functions)
    for every def at any depth."""
    def walk(node, prefix, cls, outer):
        for child in ast.iter_child_nodes(node):
            if isinstance(child, (ast.FunctionDef, ast.AsyncFunctionDef)):
                yield prefix + child.name, child, cls, outer
                yield from walk(child, prefix + child.name + ".", None, (*outer, child))
            elif isinstance(child, ast.ClassDef):
                yield from walk(child, prefix + child.name + ".", child, ())
            else:
                yield from walk(child, prefix, cls, outer)
    yield from walk(tree, "", None, ())


def _params(fn) -> set[str]:
    a = fn.args
    names = {x.arg for x in a.posonlyargs + a.args + a.kwonlyargs}
    names |= {x.arg for x in (a.vararg, a.kwarg) if x is not None}
    return names - {"self", "cls"}


def _bindings(fn) -> dict[str, list[ast.AST]]:
    out: dict[str, list[ast.AST]] = {}
    for n in _own_nodes(fn):
        if isinstance(n, ast.Assign):
            for t in n.targets:
                if isinstance(t, ast.Name):
                    out.setdefault(t.id, []).append(n.value)
        elif (isinstance(n, (ast.AnnAssign, ast.NamedExpr)) and n.value is not None
              and isinstance(n.target, ast.Name)):
            out.setdefault(n.target.id, []).append(n.value)
    return out


def _scope(fn, outer) -> tuple[set, dict]:
    """The parameters and local names *fn* reads, its enclosing functions'
    included: a def nested in another sees what the outer one was handed."""
    params: set = set()
    bindings: dict = {}
    for f in (*outer, fn):
        params |= _params(f)
        for name, values in _bindings(f).items():
            bindings.setdefault(name, []).extend(values)
    return params, bindings


class _Ctx(NamedTuple):
    """What one function's walk counts as the request: its parameters, its
    local names, the ``self`` attributes its class writes from what a method
    was handed, and the module names a function writes the same way."""
    fn: ast.AST
    params: set
    bindings: dict
    self_tainted: frozenset
    module_tainted: frozenset


def _draws(expr, ctx: _Ctx, seen=frozenset()) -> bool:
    """Whether *expr* reads what the function was handed: a parameter, directly,
    through local names, or carried on ``self`` or a module name."""
    for n in ast.walk(expr):
        if isinstance(n, ast.Name):
            if n.id in ctx.params or n.id in ctx.module_tainted:
                return True
            if n.id in ctx.bindings and n.id not in seen and any(
                    _draws(v, ctx, seen | {n.id}) for v in ctx.bindings[n.id]):
                return True
        elif (isinstance(n, ast.Attribute) and isinstance(n.value, ast.Name)
              and n.value.id == "self" and n.attr in ctx.self_tainted):
            return True
    return False


def _root(target):
    """('self', attr) or ('name', id) for what an assignment or mutation writes."""
    while isinstance(target, (ast.Subscript, ast.Attribute)):
        if (isinstance(target, ast.Attribute) and isinstance(target.value, ast.Name)
                and target.value.id == "self"):
            return ("self", target.attr)
        target = target.value
    return ("name", target.id) if isinstance(target, ast.Name) else None


def _writes(fn):
    """(root, value, plain) for each write in *fn*'s own body; *plain* is True
    for a bare ``name = ...``, which binds a local unless declared global."""
    for n in _own_nodes(fn):
        if isinstance(n, ast.Assign):
            for t in n.targets:
                yield _root(t), n.value, isinstance(t, ast.Name)
        elif isinstance(n, (ast.AugAssign, ast.AnnAssign)) and n.value is not None:
            yield _root(n.target), n.value, isinstance(n.target, ast.Name)
        elif (isinstance(n, ast.Call) and isinstance(n.func, ast.Attribute)
              and n.func.attr in MUTATORS):
            yield (_root(n.func.value),
                   ast.Tuple(elts=[*n.args, *(k.value for k in n.keywords)], ctx=ast.Load()),
                   False)


def _taint(tree):
    """{class: attributes} and module names that some function writes from what
    it was handed, to a fixed point."""
    module_names = {t.id for n in tree.body if isinstance(n, (ast.Assign, ast.AnnAssign))
                    for t in (n.targets if isinstance(n, ast.Assign) else [n.target])
                    if isinstance(t, ast.Name)}
    functions = list(_functions(tree))
    by_class: dict = {}
    module: set = set()
    changed = True
    while changed:
        changed = False
        for _qual, fn, cls, outer in functions:
            declared = {g for n in _own_nodes(fn) if isinstance(n, ast.Global) for g in n.names}
            ctx = _Ctx(fn, *_scope(fn, outer),
                       frozenset(by_class.get(cls, ())), frozenset(module))
            for root, value, plain in _writes(fn):
                if root is None or not _draws(value, ctx):
                    continue
                kind, name = root
                if kind == "self" and cls is not None:
                    if name not in by_class.setdefault(cls, set()):
                        by_class[cls].add(name)
                        changed = True
                elif kind == "name" and (name in declared or (not plain and name in module_names)):
                    if name not in module:
                        module.add(name)
                        changed = True
    return by_class, module


def _callee_problem(f, bindings, seen=frozenset()) -> str | None:
    """None when *f*, the function a transaction is built from, is named in
    the source (``contract.functions.transfer``) or is a constructor."""
    unread = "the census cannot read which function it calls"
    if isinstance(f, ast.Name):
        if f.id in bindings and f.id not in seen:
            return next((w for w in (_callee_problem(v, bindings, seen | {f.id})
                                     for v in bindings[f.id]) if w), None)
        return unread
    if isinstance(f, ast.Attribute):
        if f.attr in LOOKUPS:
            return "the function is looked up by a name or selector at run time"
        if f.attr == "constructor" or (isinstance(f.value, ast.Attribute)
                                       and f.value.attr == "functions"):
            return None
        return unread
    if isinstance(f, ast.Subscript):
        return "the function is chosen at run time (functions[...])"
    if isinstance(f, ast.Call):
        if isinstance(f.func, ast.Name) and f.func.id == "getattr":
            return "the function is chosen at run time (getattr)"
        if isinstance(f.func, ast.Attribute) and f.func.attr in LOOKUPS:
            return "the function is looked up by a name or selector at run time"
    return unread


def _unnamed_function(recv, bindings, seen=frozenset()) -> str | None:
    """None when *recv*, what ``build_transaction`` is called on, is a call of
    a function named in the source (or of a constructor); otherwise why not."""
    if isinstance(recv, ast.Name) and recv.id in bindings and recv.id not in seen:
        return next((w for w in (_unnamed_function(v, bindings, seen | {recv.id})
                                 for v in bindings[recv.id]) if w), None)
    if isinstance(recv, ast.Call):
        return _callee_problem(recv.func, bindings)
    return "the census cannot read which function it calls"


def _named_calls(recv, bindings, seen=frozenset()):
    """(function name, call) for each ``contract.functions.NAME(...)`` that
    *recv* can be, following local names."""
    if isinstance(recv, ast.Name) and recv.id in bindings and recv.id not in seen:
        for v in bindings[recv.id]:
            yield from _named_calls(v, bindings, seen | {recv.id})
        return
    if not isinstance(recv, ast.Call):
        return
    f = recv.func
    for _ in range(4):  # fn = c.functions.transfer; fn(...)
        if isinstance(f, ast.Name) and f.id in bindings and len(bindings[f.id]) == 1:
            f = bindings[f.id][0]
    if (isinstance(f, ast.Attribute) and isinstance(f.value, ast.Attribute)
            and f.value.attr == "functions"):
        yield f.attr, recv


def _deploys(recv, bindings, seen=frozenset()) -> bool:
    if isinstance(recv, ast.Name) and recv.id in bindings and recv.id not in seen:
        return any(_deploys(v, bindings, seen | {recv.id}) for v in bindings[recv.id])
    return (isinstance(recv, ast.Call) and isinstance(recv.func, ast.Attribute)
            and recv.func.attr == "constructor")


def _pairs_problem(pairs, ctx, seen) -> tuple[str | None, list]:
    """What is wrong with a transaction written out key by key, and the named
    calls any ``**`` part of it came from. Its data must be a constant."""
    calls: list = []
    for key, value in pairs:
        if key is None:
            if _draws(value, ctx):
                return "the transaction is unpacked from what the function was handed", calls
            _kind, problem, more = _signs(value, ctx, seen)
            calls += more
            if problem:
                return problem, calls
            continue
        if not isinstance(key, ast.Constant):
            return "the census cannot read a key of the transaction", calls
        if key.value in DATA_KEYS and not isinstance(value, ast.Constant):
            if _draws(value, ctx):
                return f"the transaction's '{key.value}' is what the function was handed", calls
            return f"the transaction's '{key.value}' is not a constant the census can read", calls
    return None, calls


def _update_problem(value, ctx, seen) -> str | None:
    """What an update of a transaction from *value* can put into it."""
    if isinstance(value, ast.Dict):
        return _pairs_problem(zip(value.keys, value.values), ctx, seen)[0]
    if _draws(value, ctx):
        return "the transaction is updated from what the function was handed"
    return "the census cannot read what the transaction is updated from"


def _mutated(name, fn, ctx) -> str | None:
    """What a later write into the transaction bound to *name* can change."""
    for n in _own_nodes(fn):
        if isinstance(n, ast.Assign):
            for t in n.targets:
                if isinstance(t, ast.Subscript) and isinstance(t.value, ast.Name) and t.value.id == name:
                    key = t.slice
                    if not isinstance(key, ast.Constant):
                        return "the census cannot read which key of the transaction is set"
                    if key.value in DATA_KEYS and not isinstance(n.value, ast.Constant):
                        return "the transaction's data is replaced after it is built"
        elif (isinstance(n, ast.AugAssign) and isinstance(n.target, ast.Name)
              and n.target.id == name):
            problem = _update_problem(n.value, ctx, frozenset())
            if problem:
                return problem
        if not (isinstance(n, ast.Call) and isinstance(n.func, ast.Attribute)
                and isinstance(n.func.value, ast.Name) and n.func.value.id == name):
            continue
        if n.func.attr in ("setdefault", "__setitem__") and len(n.args) == 2:
            key, value = n.args
            if not isinstance(key, ast.Constant):
                return "the census cannot read which key of the transaction is set"
            if key.value in DATA_KEYS and not isinstance(value, ast.Constant):
                return "the transaction's data is replaced after it is built"
        elif n.func.attr == "update":
            for part in n.args:
                problem = _update_problem(part, ctx, frozenset())
                if problem:
                    return problem
            named = [(ast.Constant(k.arg) if k.arg else None, k.value) for k in n.keywords]
            problem = _pairs_problem(named, ctx, frozenset())[0]
            if problem:
                return problem
    return None


def _signs(arg, ctx, seen=frozenset()) -> tuple[str, str | None, list]:
    """(kind, problem, named calls) for what one signing call signs: kind is
    'built', 'deployment' or 'handed'."""
    unread = "the census cannot read what is signed"
    if isinstance(arg, ast.Dict):
        problem, calls = _pairs_problem(zip(arg.keys, arg.values), ctx, seen)
        return "built", problem, calls
    if isinstance(arg, ast.Call):
        f = arg.func
        if isinstance(f, ast.Attribute) and f.attr == "build_transaction":
            if _deploys(f.value, ctx.bindings):
                return "deployment", None, []
            return ("built", _unnamed_function(f.value, ctx.bindings),
                    list(_named_calls(f.value, ctx.bindings)))
        if isinstance(f, ast.Name) and f.id == "dict":
            if len(arg.args) == 1 and not arg.keywords:  # a copy
                return _signs(arg.args[0], ctx, seen)
            pairs = [(None, a) for a in arg.args]
            pairs += [(ast.Constant(k.arg) if k.arg else None, k.value) for k in arg.keywords]
            problem, calls = _pairs_problem(pairs, ctx, seen)
            return "built", problem, calls
        return "built", unread, []
    if isinstance(arg, ast.Name):
        if arg.id in ctx.params:
            return "handed", None, []
        if arg.id in ctx.bindings and arg.id not in seen:
            found = [_signs(v, ctx, seen | {arg.id}) for v in ctx.bindings[arg.id]]
            kinds = {k for k, _p, _c in found}
            kind = next(k for k in ("handed", "deployment", "built") if k in kinds)
            problem = next((p for _k, p, _c in found if p), None)
            calls = [c for _k, _p, cs in found for c in cs]
            return kind, problem or _mutated(arg.id, ctx.fn, ctx), calls
    return "built", unread, []


def _abis(tree) -> dict[str, list[list[dict]]]:
    """{function name: [inputs, ...]} for every ABI entry written out in *tree*."""
    out: dict = {}
    for n in ast.walk(tree):
        if not isinstance(n, ast.Dict):
            continue
        keys = {k.value for k in n.keys if isinstance(k, ast.Constant)}
        if not {"name", "inputs"} <= keys:
            continue
        try:
            entry = ast.literal_eval(n)
        except ValueError:
            continue
        if isinstance(entry.get("name"), str) and isinstance(entry.get("inputs"), list):
            out.setdefault(entry["name"], []).append(entry["inputs"])
    return out


def _tree_files():
    for top in ("runtime", "gateway"):
        yield from sorted((ROOT / top).rglob("*.py"))


def _all_abis() -> dict[str, list[list[dict]]]:
    out: dict = {}
    for path in _tree_files():
        for name, inputs in _abis(ast.parse(path.read_text(encoding="utf-8"))).items():
            out.setdefault(name, []).extend(inputs)
    return out


class _LazyAbis(dict):
    """Every ABI entry written out under runtime/ and gateway/, read once, for
    a function whose ABI another module defines (EAS's attest)."""

    def get(self, key, default=None):
        if not self:
            self.update(_all_abis())
        return super().get(key, default)


_GLOBAL_ABIS = _LazyAbis()


def _carries_bytes(inp: dict) -> bool:
    return bool(DYNAMIC_BYTES.match(str(inp.get("type", "")))) or any(
        _carries_bytes(c) for c in inp.get("components") or ())


def _literal(expr, bindings, seen=frozenset()):
    """The one tuple or list literal *expr* is, following local names, or None."""
    if isinstance(expr, ast.Name) and expr.id in bindings and expr.id not in seen:
        values = bindings[expr.id]
        return _literal(values[0], bindings, seen | {expr.id}) if len(values) == 1 else None
    return expr if isinstance(expr, (ast.Tuple, ast.List)) else None


def _bytes_in(inp: dict, expr, path: str, bindings):
    """(path, expression) for each dynamic-bytes input under *inp*."""
    if DYNAMIC_BYTES.match(str(inp.get("type", ""))):
        yield path, expr
        return
    comps = inp.get("components")
    if not comps or not _carries_bytes(inp):
        return
    lit = _literal(expr, bindings)
    if lit is not None and not str(inp.get("type", "")).endswith("]") and len(lit.elts) == len(comps):
        for comp, elt in zip(comps, lit.elts):
            yield from _bytes_in(comp, elt, f"{path}.{comp.get('name', '?')}", bindings)
    else:
        yield path, expr


def _carried(name, call, abis, ctx):
    """(path, expression or None) for the dynamic bytes a call of *name* carries;
    None when the census cannot read the function's inputs."""
    if any(isinstance(a, ast.Starred) for a in call.args) or call.keywords:
        yield name, None
        return
    candidates = [i for i in (abis.get(name) or _GLOBAL_ABIS.get(name) or [])
                  if len(i) == len(call.args)]
    if not candidates:
        yield name, None
        return
    seen = set()
    for inputs in candidates:
        for inp, arg in zip(inputs, call.args):
            for path, expr in _bytes_in(inp, arg, str(inp.get("name", "?")), ctx.bindings):
                if path not in seen:
                    seen.add(path)
                    yield path, expr


def _census(source: str, filename: str):
    """Every signing call in the source, and every bytes argument one carries
    that the function was handed, as Sites; and every mention of a signing
    method the walk does not read as a direct call inside a function."""
    tree = ast.parse(source, filename=filename)
    abis = _abis(tree)
    by_class, module = _taint(tree)
    read: set[int] = set()
    for qual, fn, cls, outer in _functions(tree):
        ctx = _Ctx(fn, *_scope(fn, outer), frozenset(by_class.get(cls, ())),
                   frozenset(module))
        for n in _own_nodes(fn):
            if not (isinstance(n, ast.Call) and isinstance(n.func, ast.Attribute)
                    and n.func.attr in SIGNING_CALLS):
                continue
            read.add(id(n.func))
            arg = n.args[0] if n.args else next(
                (k.value for k in n.keywords if k.arg in ("tx", "transaction_dict")), None)
            if arg is None:
                yield Site(qual, n.lineno, "built", "the census cannot read what is signed")
                continue
            kind, problem, calls = _signs(arg, ctx)
            yield Site(qual, n.lineno, kind, problem)
            for name, call in calls:
                for path, expr in _carried(name, call, abis, ctx):
                    if expr is None:
                        yield Site(qual, n.lineno, "built",
                                   f"the census cannot read the inputs of {name}", path)
                    elif _draws(expr, ctx):
                        yield Site(qual, n.lineno, "carries",
                                   f"the call carries bytes the function was handed ({path})", path)
    for n in ast.walk(tree):
        if isinstance(n, ast.Attribute) and n.attr in SIGNING_CALLS and id(n) not in read:
            yield Site("(not read)", n.lineno, "unread",
                       "a signing method the census does not read as a direct call "
                       "inside a function (an alias, a lambda, module or class level)")
        elif isinstance(n, ast.Call) and any(
                isinstance(a, ast.Constant) and a.value in SIGNING_CALLS for a in n.args):
            f = n.func
            called = f.id if isinstance(f, ast.Name) else getattr(f, "attr", "")
            if called in NAME_LOOKUPS:
                yield Site("(not read)", n.lineno, "unread", "a signing method reached by its name")


def _sites():
    for path in _tree_files():
        rel = str(path.relative_to(ROOT))
        for site in _census(path.read_text(encoding="utf-8"), rel):
            yield rel, site


def test_every_call_the_platform_key_signs_names_its_function_in_the_source():
    """[control]"""
    sites = list(_sites())
    signing = [(rel, s) for rel, s in sites if s.kind in ("built", "deployment", "handed")]
    assert len(signing) >= 60, f"the walk read {len(signing)} signing calls; it is not reading the tree"
    bad, handed, deployed = [], set(), set()
    for rel, s in sites:
        if s.kind == "handed":
            handed.add((rel, s.qual))
        elif s.kind == "deployment":
            deployed.add((rel, s.qual))
        if s.kind != "carries" and s.problem and (rel, s.qual) not in UNCALLED:
            bad.append(f"{rel}:{s.line} {s.qual}: {s.problem}")
    assert bad == [], "the platform key signs a call the request chose:\n  " + "\n  ".join(bad)
    assert handed == PASS_THROUGH, handed ^ PASS_THROUGH
    assert deployed == DEPLOYMENTS, deployed ^ DEPLOYMENTS
    flagged = {(rel, s.qual) for rel, s in sites if s.problem and s.kind != "carries"}
    assert flagged == UNCALLED, flagged ^ UNCALLED


def test_no_signed_call_carries_bytes_the_request_wrote():
    """[control] A named function whose bytes input the request wrote is a call
    or a message the request composed, unless it is listed, with the reason."""
    carried = {(rel, s.qual, s.path) for rel, s in _sites() if s.kind == "carries"}
    listed = set(LISTED_BYTES) | set(DOOR_REFUSED)
    unlisted = sorted(f"{rel} {qual}: {path}" for rel, qual, path in carried - listed)
    assert unlisted == [], ("the platform key signs bytes the request wrote:\n  "
                            + "\n  ".join(unlisted))
    assert carried == listed, sorted(listed - carried)


def test_what_no_request_reaches_is_refused_at_every_door():
    """[control] A door-refused listing holds only while every door refuses the
    pair a request would run to reach it."""
    from runtime.access_policy import REFUSED_ON_REQUEST
    missing = {site: pair for site, pair in DOOR_REFUSED.items() if pair not in REFUSED_ON_REQUEST}
    assert missing == {}, missing


def test_the_inner_call_tools_are_the_operators():
    """[guard] The stated limit's reach: governance and dao are Neo's tools, and
    a caller without the operator key is served within Trinity's reach, which
    holds neither."""
    from runtime.tools.dispatcher import ToolDispatcher
    from runtime.security import agent_access_allowed
    for tool in ("governance", "dao"):
        assert agent_access_allowed("trinity", tool)[0] is False, tool
        assert agent_access_allowed("neo", tool)[0] is True, tool
    out = asyncio.run(ToolDispatcher({"workspace": "."}).dispatch(
        "governance", {"action": "schedule_operation", "timelock_address": NFT,
                       "target": B, "data": "0xdeadbeef"},
        agent_name="neo", caller_identity=A, caller_kind="session"))
    assert out.ok is False and "[DENIED]" in out.model_text, out.model_text


def test_the_listed_addresses_are_addresses():
    """[guard] Each bytes input listed as an address is built through a
    checksum, which refuses anything that is not a 20-byte address."""
    tree = ast.parse((ROOT / _CCIP).read_text(encoding="utf-8"))
    funcs = {qual: fn for qual, fn, _c, _o in _functions(tree)}

    def calls(node):
        return {getattr(n.func, "attr", getattr(n.func, "id", ""))
                for n in ast.walk(node) if isinstance(n, ast.Call)}

    assert "to_checksum_address" in calls(funcs["CrossChainMessagingService._addr_to_bytes32"])
    stargate = funcs["CrossChainMessagingService.bridge_stargate"]
    (to_bytes,) = _bindings(stargate)["to_bytes"]
    assert "to_checksum_address" in calls(to_bytes), ast.unparse(to_bytes)
    ccip = funcs["CrossChainMessagingService.bridge_token_ccip"]
    (receiver,) = _bindings(ccip)["receiver_bytes"]
    assert "_addr_to_bytes32" in calls(receiver), ast.unparse(receiver)


def test_nothing_calls_the_signer_that_signs_what_it_is_handed():
    """[guard] Its listing above rests on this."""
    callers = []
    for top in ("runtime", "gateway", "sdk", "scripts", "examples"):
        for path in sorted((ROOT / top).rglob("*.py")) if (ROOT / top).is_dir() else ():
            if str(path.relative_to(ROOT)) == "runtime/blockchain/gas_sponsor.py":
                continue
            tree = ast.parse(path.read_text(encoding="utf-8"))
            callers += [f"{path.relative_to(ROOT)}:{n.lineno}" for n in ast.walk(tree)
                        if isinstance(n, ast.Attribute) and n.attr == "sponsor_transaction"]
    assert callers == [], callers


def test_no_tool_note_offers_a_write_the_platform_refuses():
    """[control] A generated-source note told the model to deploy with
    smart_contract, which refuses to (securities, as dao and nft did)."""
    from runtime.blockchain.securities import Securities
    note = json.loads(asyncio.run(Securities(CFG).execute(action="create_token")))["note"]
    assert "does not deploy" in note and "Deploy via" not in note, note


_EXECUTE_ABI = ("EXECUTE = [{'name': 'execute', 'type': 'function', 'inputs': ["
                "{'name': 'to', 'type': 'address'}, {'name': 'value', 'type': 'uint256'},"
                "{'name': 'data', 'type': 'bytes'}, {'name': 'operation', 'type': 'uint8'}]}]\n"
                "SEND = [{'name': 'send', 'type': 'function', 'inputs': ["
                "{'name': 'message', 'type': 'tuple', 'components': ["
                "{'name': 'receiver', 'type': 'bytes'}, {'name': 'data', 'type': 'bytes'}]}]}]\n")

_PLANTED = {
    "a function chosen by name": (
        "async def go(self, params):\n"
        "    c = self.web3.eth.contract(address=params['to'], abi=params['abi'])\n"
        "    tx = c.functions[params['fn']](*params['args']).build_transaction({})\n"
        "    account.sign_transaction(tx)\n", "run time (functions"),
    "a function reached through getattr": (
        "async def go(self, params):\n"
        "    fn = getattr(contract.functions, params['fn'])\n"
        "    tx = fn(1).build_transaction({})\n"
        "    await self._web3.send_transaction(tx)\n", "run time (getattr)"),
    "a function looked up by name": (
        "async def go(self, params):\n"
        "    tx = contract.get_function_by_name(params['fn'])(1).build_transaction({})\n"
        "    account.sign_transaction(tx)\n", "looked up"),
    "calldata the request wrote": (
        "async def go(self, params):\n"
        "    await self._web3.send_transaction({'to': params['to'], 'data': params['data']})\n",
        "'data' is what"),
    "calldata put in afterwards": (
        "async def go(self, params):\n"
        "    tx = contract.functions.ping().build_transaction({})\n"
        "    tx['data'] = params['data']\n"
        "    account.sign_transaction(tx)\n", "replaced"),
    "a transaction updated from the request": (
        "async def go(self, params):\n"
        "    tx = contract.functions.ping().build_transaction({})\n"
        "    tx.update(params)\n"
        "    account.sign_transaction(tx)\n", "updated"),
    "a transaction unpacked from the request": (
        "async def go(self, params):\n"
        "    account.sign_transaction({**params, 'nonce': 1})\n", "unpacked"),
    "something the walk cannot read": (
        "async def go(self, params):\n"
        "    account.sign_transaction(self._pending)\n", "cannot read"),
    # The second review's shapes, each of which the first census let through.
    "a signing method taken as a value": (
        "async def go(self, params):\n"
        "    sign = account.sign_transaction\n"
        "    c = self.web3.eth.contract(address=params['to'], abi=params['abi'])\n"
        "    sign(c.functions[params['fn']](*params['args']).build_transaction({}))\n",
        "does not read as a direct call"),
    "a signing method reached by its name": (
        "async def go(self, params):\n"
        "    c = self.web3.eth.contract(address=params['to'], abi=params['abi'])\n"
        "    tx = c.functions[params['fn']](*params['args']).build_transaction({})\n"
        "    getattr(account, 'sign_transaction')(tx)\n", "reached by its name"),
    "calldata carried on self": (
        "async def go(self):\n"
        "    await self._web3.send_transaction({'to': self._req['to'], 'data': self._req['data']})\n",
        "not a constant"),
    "calldata read from a module name": (
        "async def go(self):\n"
        "    await self._web3.send_transaction({'to': PENDING['to'], 'data': PENDING['data']})\n",
        "not a constant"),
    "a key the walk cannot read": (
        "async def go(self, params):\n"
        "    k = 'data'\n"
        "    await self._web3.send_transaction({'to': params['to'], k: params['d']})\n",
        "cannot read a key"),
    "calldata written as a keyword": (
        "async def go(self, params):\n"
        "    await self._web3.send_transaction(dict(to=params['to'], data=params['d']))\n",
        "'data' is what"),
    "calldata merged in with |=": (
        "async def go(self, params):\n"
        "    tx = {}\n"
        "    tx |= {'data': params['d']}\n"
        "    account.sign_transaction(tx)\n", "'data' is what"),
    "a function bound by a loop": (
        "async def go(self, params):\n"
        "    for fn in [c.functions[params['fn']]]:\n"
        "        account.sign_transaction(fn(1).build_transaction({}))\n",
        "cannot read which function"),
    "a signature inside a lambda": (
        "async def go(self, params):\n"
        "    later = lambda: account.sign_transaction(params['tx'])\n"
        "    later()\n", "does not read as a direct call"),
    "a signature at module level": (
        "account.sign_transaction(PENDING)\n", "does not read as a direct call"),
    # A named function carrying a call or a message the request wrote.
    "an inner call the request wrote": (
        _EXECUTE_ABI +
        "async def go(self, params):\n"
        "    tba = self._web3.load_contract(params['account'], EXECUTE)\n"
        "    tx = tba.functions.execute(params['to'], 0, params['data'], 1).build_transaction({})\n"
        "    await self._web3.send_transaction(tx)\n", "bytes the function was handed (data)"),
    "a message inside a tuple": (
        _EXECUTE_ABI +
        "async def go(self, params):\n"
        "    message = (b'', bytes.fromhex(params['data']))\n"
        "    tx = router.functions.send(message).build_transaction({})\n"
        "    await self._web3.send_transaction(tx)\n", "(message.data)"),
    "a message carried on self from another method": (
        _EXECUTE_ABI +
        "class Relay:\n"
        "    def take(self, params):\n"
        "        self._payload = params['data']\n"
        "    async def go(self):\n"
        "        tx = router.functions.send((b'', self._payload)).build_transaction({})\n"
        "        await self._web3.send_transaction(tx)\n", "(message.data)"),
    "a message carried in a module name": (
        _EXECUTE_ABI + "PENDING = {}\n"
        "def take(params):\n"
        "    PENDING['m'] = params['data']\n"
        "async def go(self):\n"
        "    tx = router.functions.send((b'', PENDING['m'])).build_transaction({})\n"
        "    await self._web3.send_transaction(tx)\n", "(message.data)"),
    "a message a nested def was handed by its outer one": (
        _EXECUTE_ABI +
        "async def go(self, params):\n"
        "    async def inner():\n"
        "        tx = router.functions.send((b'', params['data'])).build_transaction({})\n"
        "        await self._web3.send_transaction(tx)\n"
        "    await inner()\n", "(message.data)"),
    "a function whose inputs the walk cannot read": (
        "async def go(self, params):\n"
        "    tx = c.functions.no_abi_anywhere(params['x']).build_transaction({})\n"
        "    account.sign_transaction(tx)\n", "cannot read the inputs"),
    "arguments passed by keyword": (
        _EXECUTE_ABI +
        "async def go(self, params):\n"
        "    tx = c.functions.execute(to=params['to'], value=0, data=b'', operation=0)"
        ".build_transaction({})\n"
        "    account.sign_transaction(tx)\n", "cannot read the inputs"),
}


@pytest.mark.parametrize("shape", sorted(_PLANTED))
def test_the_census_sees_a_planted_shape(shape):
    """[guard] Each way of letting a request choose the call is reported."""
    source, expected = _PLANTED[shape]
    problems = [s.problem for s in _census(source, "<planted>") if s.problem]
    assert any(expected in p for p in problems), (shape, problems)


def test_the_census_passes_the_shape_every_signer_uses():
    """[guard] A named function whose arguments come from the request is not
    this class; which argument must be the caller's is the seam's. Neither are
    bytes the platform composes, nor a constant."""
    clean = (
        _EXECUTE_ABI +
        "async def go(self, params):\n"
        "    c = self.web3.eth.contract(address=params['contract'], abi=ABI)\n"
        "    call = c.functions.transferFrom(self.wallet, params['to'], 1)\n"
        "    tx = call.build_transaction({'from': self.wallet, 'nonce': 0})\n"
        "    signed = account.sign_transaction(tx)\n"
        "    await self._web3.send_transaction({'to': params['to'], 'value': 1, 'gas': 21000})\n"
        "    await self._web3.send_transaction({'to': params['to'], 'data': b''})\n"
        "    payload = encode(['address'], [PLATFORM])\n"
        "    tx = router.functions.send((b'', payload)).build_transaction({})\n"
        "    await self._web3.send_transaction(tx)\n"
    )
    assert [s.problem for s in _census(clean, "<clean>") if s.problem] == []
