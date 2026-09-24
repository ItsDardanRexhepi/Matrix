"""No door has the platform's key sign a contract call the request composed.

THE DEFECT (The Matrix ``main``). Neo's ``smart_contract`` tool had a ``send``
action that built ``contract.functions[function_name](*args)`` against the
``contract_address`` and ``abi`` the request wrote, with the request's
``value``, and signed it with the platform's key through ``_platform_signer``.
Aimed at the configured EAS contract it signed ``attest`` and ``revoke``, the
very calls the ``eas`` tool and the services layer's attestation actions refuse
on this branch. ``MeteredSigner`` read the allowlist only when a daily cap was
set, and the default configuration sets neither, so nothing stood between the
request and the signature.

THE PROBE. Nothing here stops at a spy. The tool runs as it is registered: the
real ``_platform_signer`` builds the real ``MeteredSigner`` from a configuration
with no sponsorship policy (the default: no allowlist, no cap), over a real
private key, and the transaction goes to a JSON-RPC endpoint the test answers.
What the endpoint receives as ``eth_sendRawTransaction`` is decoded: who signed
it, which contract it calls, and the four-byte selector. On ``main`` the
platform wallet signs ``attest((bytes32,(address,uint64,bool,bytes32,bytes,
uint256)))`` (``0xf17325e7``) and ``revoke((bytes32,(bytes32,uint256)))``
(``0x46926267``) on the EAS contract, the attestation's recipient the
request's, the revoked uid the request's.

THE DOORS, each driven:

  the tool                 ``SmartContracts.execute``, as registered;
  the dispatcher           ``ToolDispatcher.dispatch`` as Neo, for the operator
                           and for a caller with no HTTP request behind it (an
                           A2A job, an internal caller);
  the bridge and the chat  ``/bridge/v1/chat``, ``/chat``, ``/chat/stream`` and
                           ``/ws`` with the operator key, Neo answering and the
                           model calling the tool, through the real ReAct loop
                           and the real security seam;
  capability invoke and    ``/api/v1/capabilities/{id}/invoke`` and
  the bridge action        ``/bridge/v1/action``, for a session and for the
                           operator, under every name the call could go by;
  the agent hand-off       ``request_execution`` and ``platform_action``, as
                           Trinity for a session and as Neo for the operator.

THE CHANGE. The tool refuses ``send`` before anything is built or signed (this
branch, 7abfa21), and the tool dispatcher refuses it too, for every caller, the
operator key included, before the handler runs
(``runtime/access_policy.py`` ``REFUSED_TOOL_CALLS``). The action-dispatching
doors cannot name the tool at all: capability invoke, ``/bridge/v1/action``,
``request_execution`` and ``platform_action`` resolve an action through
ACTION_MAP to a services-layer method, and no entry reaches ``smart_contract``;
the guards below pin that. What the platform composes itself still signs under
the default policy: a read through the same tool, and a named function the
source writes.

CONTROL, measured on this file's 27 tests at The Matrix ``main`` 58b8b4d, at
fix/oldq-census a710052 and here. The 14 marked [control] fail on ``main``,
each because the platform wallet signed the request's attest or revoke on the
EAS contract (the tool, the dispatcher for both callers, and all four chat
entrances), and pass at a710052 and here. The 3 marked [control:door] fail on
``main`` and at a710052, where the tool refused but the dispatcher still ran
its handler, and pass here. The 10 marked [guard] pass at all three: no
action-dispatching door reaches the tool, a session's chat never held it, a
read still reads, and a platform-composed transfer still signs under the
default policy (on ``main`` too, so the probe sees a signature when there is
one). 17 fail on ``main``, 3 at a710052, none here.
"""

from __future__ import annotations

import json
import sys
import tempfile
import time

import pytest

sys.path.insert(0, "tests")

KEY = "0x" + "4c" * 32                         # the platform's key, for the test
OPERATOR = "test-operator-key"
B = "0xb2b2b2b2b2B2b2B2B2b2b2B2B2b2B2B2b2b2b2b2"   # somebody else
EAS = "0x4E4E4E4e4E4e4e4E4e4E4E4e4E4E4E4E4e4E4e4e"
SCHEMA = "0x" + "cd" * 32
UID = "0x" + "ef" * 32

ATTEST_SIG = "attest((bytes32,(address,uint64,bool,bytes32,bytes,uint256)))"
REVOKE_SIG = "revoke((bytes32,(bytes32,uint256)))"


def _selector(sig: str) -> str:
    from eth_utils import keccak
    return "0x" + keccak(text=sig)[:4].hex()


def _platform_wallet() -> str:
    from eth_account import Account
    return Account.from_key(KEY).address


def _config(tmp: str) -> dict:
    """The default sponsorship policy: no paymaster.policy at all."""
    from test_route_sweep import SWEEP_CONFIG
    return {**SWEEP_CONFIG,
            "workspace": ".",
            "memory_dir": f"{tmp}/memory",
            "database": {"path": f"{tmp}/matrix.db"},
            "rexhepi": {"rate_limit_max_actions": 100_000},
            "gateway": {**SWEEP_CONFIG["gateway"], "api_key": OPERATOR},
            "blockchain": {"network": "base-sepolia", "chain_id": 84532,
                           "rpc_url": "http://127.0.0.1:1",
                           "paymaster_private_key": KEY,
                           "platform_wallet": _platform_wallet(),
                           "eas_contract": EAS, "eas_schema": SCHEMA}}


_REVOKE_ABI = [{"inputs": [{"components": [
    {"name": "schema", "type": "bytes32"},
    {"components": [{"name": "uid", "type": "bytes32"}, {"name": "value", "type": "uint256"}],
     "name": "data", "type": "tuple"}], "name": "request", "type": "tuple"}],
    "name": "revoke", "outputs": [], "stateMutability": "payable", "type": "function"}]


def _calls() -> dict:
    """The request's two calls, aimed at the configured EAS contract, each with
    the ABI a caller would hand the tool."""
    from runtime.blockchain.eas_client import EAS_ATTEST_ABI
    return {
        "attest": {"action": "send", "contract_address": EAS, "abi": EAS_ATTEST_ABI,
                   "function_name": "attest",
                   "args": [[SCHEMA, [B, 0, True, "0x" + "00" * 32, "0x" + "ab" * 64, 0]]]},
        "revoke": {"action": "send", "contract_address": EAS, "abi": _REVOKE_ABI,
                   "function_name": "revoke", "args": [[SCHEMA, [UID, 0]]]},
    }


SELECTOR = {"attest": _selector(ATTEST_SIG), "revoke": _selector(REVOKE_SIG)}


# ── the chain the platform signs for ─────────────────────────────────────

class _Chain:
    """A JSON-RPC endpoint that answers what a send asks for and records every
    raw transaction it is handed, decoded."""

    def __init__(self):
        self.sent: list[dict] = []
        self.methods: list[str] = []

    def answer(self, method: str, params: list):
        self.methods.append(method)
        if method == "eth_chainId":
            return hex(84532)
        if method == "eth_gasPrice":
            return hex(10 ** 9)
        if method in ("eth_getTransactionCount", "eth_blockNumber"):
            return hex(7)
        if method == "eth_estimateGas":
            return hex(100_000)
        if method == "eth_call":
            return "0x" + "00" * 32
        if method == "eth_sendRawTransaction":
            self.sent.append(_decode(params[0]))
            return "0x" + "77" * 32
        if method == "eth_getTransactionReceipt":
            return {"transactionHash": params[0], "transactionIndex": "0x0",
                    "blockHash": "0x" + "88" * 32, "blockNumber": "0x8",
                    "from": _platform_wallet(), "to": EAS, "cumulativeGasUsed": "0x5208",
                    "gasUsed": "0x5208", "effectiveGasPrice": hex(10 ** 9),
                    "contractAddress": None, "logs": [], "logsBloom": "0x" + "00" * 256,
                    "status": "0x1", "type": "0x0"}
        raise ValueError(f"the test chain does not answer {method}")


def _decode(raw_hex: str) -> dict:
    """Signer, destination and selector of a raw transaction."""
    import rlp
    from eth_account import Account

    raw = bytes.fromhex(raw_hex[2:] if raw_hex.startswith("0x") else raw_hex)
    if raw[0] >= 0xc0:                       # legacy: nonce, gasPrice, gas, to, value, data, ...
        fields = rlp.decode(raw)
        to, data = fields[3], fields[5]
    else:                                     # typed: 0x02 || rlp(chainId, nonce, tip, fee, gas, to, value, data, ...)
        fields = rlp.decode(raw[1:])
        to, data = fields[5], fields[7]
    return {"from": Account.recover_transaction(raw),
            "to": "0x" + to.hex(), "selector": "0x" + data[:4].hex()}


@pytest.fixture
def chain(monkeypatch):
    """Every capability's ``web3`` talks to the test chain."""
    from web3 import Web3
    from web3.providers.base import BaseProvider

    from runtime.blockchain.interface import BlockchainInterface

    probe = _Chain()

    class Provider(BaseProvider):
        def make_request(self, method, params):
            return {"jsonrpc": "2.0", "id": 1, "result": probe.answer(method, list(params))}

        def is_connected(self, show_traceback=False):
            return True

    w3 = Web3(Provider())
    monkeypatch.setattr(BlockchainInterface, "web3", property(lambda self: w3))
    return probe


def _eas_calls_signed(chain: _Chain) -> list[dict]:
    return [tx for tx in chain.sent if tx["to"].lower() == EAS.lower()]


# ── the tool ─────────────────────────────────────────────────────────────

@pytest.mark.parametrize("call", ["attest", "revoke"])
async def test_the_tool_has_the_platform_sign_neither(chain, tmp_path, call):
    """[control] The tool as registered, under the default policy."""
    from runtime.blockchain.smart_contracts import SmartContracts
    out = json.loads(await SmartContracts(_config(str(tmp_path))).execute(**_calls()[call]))
    assert _eas_calls_signed(chain) == [], (
        f"the platform wallet signed the request's {call}: {chain.sent}")
    assert out.get("ok") is False and out.get("code") == "denied", out


# ── the dispatcher ───────────────────────────────────────────────────────

def _tool_dispatcher(tmp: str):
    from runtime.tools.dispatcher import ToolDispatcher
    return ToolDispatcher(_config(tmp))


@pytest.mark.parametrize("caller_kind", ["operator", ""])
@pytest.mark.parametrize("call", ["attest", "revoke"])
async def test_the_dispatcher_signs_neither_for_any_caller(chain, tmp_path, call, caller_kind):
    """[control] Neo's tool call, for the operator's chat and for a caller with
    no HTTP request behind it."""
    out = await _tool_dispatcher(str(tmp_path)).dispatch(
        "smart_contract", _calls()[call], agent_name="neo",
        caller_identity=B, caller_kind=caller_kind)
    assert _eas_calls_signed(chain) == [], (
        f"the platform wallet signed the request's {call}: {chain.sent}")
    assert "Nothing was signed" in out.model_text, out.model_text


@pytest.mark.parametrize("caller_kind", ["operator", ""])
async def test_the_dispatcher_refuses_it_before_the_handler_runs(chain, tmp_path, monkeypatch,
                                                                  caller_kind):
    """[control:door] The door's own answer, not only the tool's: the handler is
    never entered, so a tool that forgot its refusal still signs nothing."""
    from runtime.blockchain.smart_contracts import SmartContracts

    entered = []
    original = SmartContracts.execute

    async def spy(self, **kwargs):
        entered.append(kwargs.get("action"))
        return await original(self, **kwargs)

    monkeypatch.setattr(SmartContracts, "execute", spy)
    for spelling in ("send", "Send", " send "):
        out = await _tool_dispatcher(str(tmp_path)).dispatch(
            "smart_contract", {**_calls()["attest"], "action": spelling},
            agent_name="neo", caller_kind=caller_kind)
        assert out.ok is False and out.code == "denied", (spelling, out.model_text)
        assert "[DENIED]" in out.model_text, (spelling, out.model_text)
    assert entered == [], f"the handler ran for {entered}"


def test_the_refusal_is_keyed_on_the_tool_call():
    """[control:door]"""
    from runtime.access_policy import REFUSED_TOOL_CALLS, refused_tool_call

    assert set(REFUSED_TOOL_CALLS) == {("smart_contract", "send")}
    assert refused_tool_call("smart_contract", {"action": "send"})
    assert refused_tool_call("smart_contract", {"action": "SEND"})
    for tool, args in (("smart_contract", {"action": "call"}),
                       ("smart_contract", {"action": "compile"}),
                       ("smart_contract", {}),
                       ("smart_contract", {"action": ["send"]}),
                       ("smart_contract", "send"),
                       ("payment", {"action": "send"})):
        assert refused_tool_call(tool, args) is None, (tool, args)


# ── the chat entrances: the model calls the tool, as Neo, with the operator key ─

def _gateway(tmp: str, call: str):
    from gateway.server import GatewayServer
    from runtime.models.model_interface import ModelResponse

    server = GatewayServer(_config(tmp))
    replies = [
        ModelResponse(tool_calls=[{"id": "c1", "function": {
            "name": "smart_contract", "arguments": json.dumps(_calls()[call])}}]),
        ModelResponse(content="done"),
    ]
    seen: list[list] = []

    async def complete(**kwargs):
        seen.append(list(kwargs["messages"]))
        return replies.pop(0) if replies else ModelResponse(content="done")

    server.react_loop.router.complete = complete
    return server, seen


@pytest.mark.parametrize("entrance", ["/bridge/v1/chat", "/chat", "/chat/stream", "/ws"])
@pytest.mark.parametrize("call", ["attest", "revoke"])
async def test_no_chat_entrance_has_the_platform_sign_it(chain, call, entrance):
    """[control] The whole turn: the operator's chat with Neo, the model
    composing the call, the real ReAct loop, security seam and dispatcher."""
    from aiohttp.test_utils import TestClient, TestServer
    from test_chat_entrances_one_posture import _drive

    tmp = tempfile.mkdtemp(prefix="the-matrix-composed-call-")
    server, seen = _gateway(tmp, call)
    async with TestClient(TestServer(server.create_app())) as client:
        status = await _drive(client, entrance,
                              {"message": "sign it", "agent": "neo", "session_id": f"s-{call}"},
                              {"Authorization": f"Bearer {OPERATOR}"})
    assert len(seen) == 2, f"{entrance} did not run the model's tool call (status {status})"
    assert _eas_calls_signed(chain) == [], (
        f"{entrance}: the platform wallet signed the request's {call}: {chain.sent}")
    told = [m.content for m in seen[1] if m.role == "tool"]
    assert len(told) == 1 and "Nothing was signed" in told[0], told


# ── the action-dispatching doors cannot name the tool ─────────────────────

NAMES = ("smart_contract", "send", "smart_contract.send", "smart_contract_send",
         "contract_send", "send_contract", "call_contract", "execute_contract")


def _server(tmp_path):
    from gateway.server import GatewayServer
    return GatewayServer(_config(str(tmp_path)))


async def _with_session(server):
    now = time.time()
    await server.wallet_sessions.add(token="0xTEST_SESSION", address="apple:sub",
                                     issued_at=now, expires_at=now + 3600)


HEADERS = {"session": {"Authorization": "Bearer 0xTEST_SESSION"},
           "operator": {"Authorization": f"Bearer {OPERATOR}"}}


@pytest.mark.parametrize("who", sorted(HEADERS))
async def test_no_action_door_reaches_the_tool(chain, tmp_path, monkeypatch, who):
    """[guard] Capability invoke and /bridge/v1/action, under every name the
    call could go by, with and without a service override. None of them reaches
    ``smart_contract``; none of them signs."""
    from aiohttp.test_utils import TestClient, TestServer

    from runtime.blockchain.smart_contracts import SmartContracts

    entered = []
    original = SmartContracts.execute

    async def spy(self, **kwargs):
        entered.append(kwargs.get("action"))
        return await original(self, **kwargs)

    monkeypatch.setattr(SmartContracts, "execute", spy)
    server = _server(tmp_path)
    answered = {}
    params = _calls()["attest"]
    async with TestClient(TestServer(server.create_app())) as client:
        await _with_session(server)
        for name in NAMES:
            resp = await client.post(f"/api/v1/capabilities/{name}/invoke",
                                     headers=HEADERS[who], json={"params": params})
            answered[f"invoke {name}"] = resp.status
            for body in ({"action": name, "params": params},
                         {"action": "send", "service": name, "params": params}):
                resp = await client.post("/bridge/v1/action", headers=HEADERS[who],
                                         json={**body, "session_id": "s1"})
                answered[f"action {json.dumps(body)[:60]}"] = resp.status
    assert entered == [] and _eas_calls_signed(chain) == [], (entered, chain.sent)
    assert all(status >= 400 for status in answered.values()), answered


@pytest.mark.parametrize("tool,agent,caller_kind", [
    ("request_execution", "trinity", "session"),
    ("platform_action", "trinity", "session"),
    ("request_execution", "neo", "operator"),
    ("platform_action", "neo", "operator"),
    ("platform_action", "neo", ""),
])
async def test_no_hand_off_reaches_the_tool(chain, tmp_path, monkeypatch, tool, agent, caller_kind):
    """[guard] Trinity's hand-off to Neo and Neo's mega-tool resolve an action to
    a services-layer method; no name, and no service override, is the tool."""
    from runtime.blockchain.smart_contracts import SmartContracts

    entered = []
    original = SmartContracts.execute

    async def spy(self, **kwargs):
        entered.append(kwargs.get("action"))
        return await original(self, **kwargs)

    monkeypatch.setattr(SmartContracts, "execute", spy)
    dispatcher = _tool_dispatcher(str(tmp_path))
    for name in NAMES:
        for args in ({"action": name, "params": _calls()["attest"]},
                     {"action": "send", "service": name, "params": _calls()["attest"]}):
            out = await dispatcher.dispatch(tool, args, agent_name=agent, caller_kind=caller_kind)
            answered = json.loads(out.model_text) if out.ok else {}
            assert out.ok is False or answered.get("call_outcome") == "failure", (
                tool, args, out.model_text)
    assert entered == [] and _eas_calls_signed(chain) == [], (entered, chain.sent)


async def test_a_session_chat_holds_no_such_tool(chain, tmp_path):
    """[guard] Trinity, who answers every caller without the operator key, never
    held ``smart_contract``."""
    out = await _tool_dispatcher(str(tmp_path)).dispatch(
        "smart_contract", _calls()["attest"], agent_name="trinity", caller_kind="session")
    assert out.ok is False and "[DENIED]" in out.model_text
    assert chain.sent == []


# ── what the platform composes itself still signs ────────────────────────

async def test_a_read_through_the_same_door_still_reads(chain, tmp_path):
    """[guard] ``call`` is an eth_call: the dispatcher runs it, nothing is signed."""
    args = {**_calls()["attest"], "action": "call"}
    out = await _tool_dispatcher(str(tmp_path)).dispatch(
        "smart_contract", args, agent_name="neo", caller_kind="operator")
    assert out.ok is True, out.model_text
    assert "eth_call" in chain.methods and chain.sent == []


async def test_a_platform_composed_call_still_signs_under_the_default_policy(chain, tmp_path):
    """[guard] A function the source names, signed by the same platform signer
    under the same default policy, through the same dispatcher: an ERC-20
    transfer of the platform's own USDC, which the operator asked for. The
    refusal is of a call the request composed, not of platform signing."""
    out = await _tool_dispatcher(str(tmp_path)).dispatch(
        "stablecoin", {"action": "transfer", "token": "USDC", "to": B, "amount": "1"},
        agent_name="neo", caller_kind="operator")
    signed = [tx for tx in chain.sent if tx["from"] == _platform_wallet()]
    transfer = _selector("transfer(address,uint256)")
    assert [tx["selector"] for tx in signed] == [transfer], (out.model_text, chain.sent)
