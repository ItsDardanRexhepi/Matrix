"""A fault raised after the request was handed over is not proof it never left.

`creator_platforms/_guards.py` said the TypeError/ValueError branch of
`classify_transport_fault` is "proof the request never left this process —
encoding failed before any socket write", and `publish_not_sent` tells the
operator "Nothing was published and retrying is safe". Checking
JSONDecodeError first closed one member of the class. With httpx 0.28,
``resp.json()`` on a 2xx body that is not valid UTF-8 raises
UnicodeDecodeError, which is a ValueError and not a JSONDecodeError, and
`publish_mirror_post` answered "retrying is safe" about a post the gateway had
accepted: the duplicate permanent post the rule exists to prevent.

The type of a fault says where it was raised only before the hand-over, so
the call sites now say when a response arrived, `Web3Manager.send_transaction`
marks a fault raised while the node had the signed bytes, and the deployment
in contract_conversion sends in a step of its own.
"""

from __future__ import annotations

import sys
import types
from types import SimpleNamespace

import httpx
import pytest

from runtime.blockchain.services.creator_platforms._guards import classify_transport_fault
from runtime.blockchain.services.creator_platforms.service import CreatorPlatformsService
from runtime.blockchain import web3_manager
from runtime.blockchain.web3_manager import Web3Manager


# Read through getattr so that, against a tree without the marker, each check
# fails on its own assertion instead of the module failing to import.
def mark_handed_to_node(exc: BaseException) -> None:
    getattr(web3_manager, "mark_handed_to_node", lambda _e: None)(exc)


def was_handed_to_node(exc: BaseException) -> bool:
    return getattr(web3_manager, "was_handed_to_node", lambda _e: False)(exc)

_NOT_UTF8 = b'{"id": "\xff"}'


def _undecodable() -> UnicodeDecodeError:
    try:
        _NOT_UTF8.decode("utf-8")
    except UnicodeDecodeError as exc:
        return exc
    raise AssertionError("premise: the body decodes")


# ── the classifier ─────────────────────────────────────────────────────────

def test_a_body_that_is_not_utf8_is_not_never_sent():
    """THE MEASURED CASE, as the exception itself."""
    assert classify_transport_fault(_undecodable()) == "unknown"


@pytest.mark.parametrize("exc", [
    ValueError("a reply this code could not read"),
    TypeError("a reply of the wrong shape"),
    KeyError("id"),
    RuntimeError("anything"),
])
def test_after_the_hand_over_every_fault_is_unknown(exc):
    assert classify_transport_fault(exc, after_send=True) == "unknown"
    marked = type(exc)(*exc.args)
    mark_handed_to_node(marked)
    assert was_handed_to_node(marked)
    assert classify_transport_fault(marked) == "unknown"


def test_after_the_hand_over_a_4xx_is_still_a_refusal():
    class _Err(Exception):
        response = SimpleNamespace(status_code=401)

    assert classify_transport_fault(_Err(), after_send=True) == "rejected"


@pytest.mark.parametrize("exc,expected", [
    (ConnectionRefusedError("refused"), "not_sent"),
    (ConnectionResetError("reset by peer after the request was written"), "unknown"),
    (BrokenPipeError("broken pipe"), "unknown"),
    (ConnectionAbortedError("aborted"), "unknown"),
])
def test_only_a_refused_connection_proves_nothing_was_written(exc, expected):
    assert classify_transport_fault(exc) == expected


def test_before_the_hand_over_an_encoding_fault_is_still_not_sent():
    """SCOPE PIN: 21-E's half must hold — an unserialisable param never left."""
    assert classify_transport_fault(TypeError("Object of type set is not JSON serializable")) == "not_sent"
    assert classify_transport_fault(ValueError("bad header value")) == "not_sent"


# ── the publishers ─────────────────────────────────────────────────────────

def _cfg() -> dict:
    return {"services": {"creator_platforms": {
        "enabled": True,
        "mirror_api_key": "k", "mirror_endpoint": "https://mirror.example",
        "mirror_author": "0xAUTHOR", "mirror_publication": "pub",
        "paragraph_api_key": "k", "paragraph_endpoint": "https://paragraph.example",
        "paragraph_publication": "pub",
    }}}


def _gateway_answers(status: int, body: bytes):
    class _C(httpx.AsyncClient):
        def __init__(self, *a, **k):
            k["transport"] = httpx.MockTransport(
                lambda request: httpx.Response(status, content=body))
            super().__init__(*a, **k)
    return _C


@pytest.mark.parametrize("method,kwargs", [
    ("publish_mirror_post", {"title": "T", "content": "c"}),
    ("publish_paragraph_post", {"title": "T", "body": "b"}),
])
async def test_an_accepted_post_whose_body_does_not_decode_is_not_safe_to_retry(
    monkeypatch, method, kwargs,
):
    monkeypatch.setattr(httpx, "AsyncClient", _gateway_answers(200, _NOT_UTF8))
    out = await getattr(CreatorPlatformsService(_cfg()), method)(**kwargs)
    assert "retrying is safe" not in out.get("disclosure", ""), (
        f"a post the gateway accepted was reported safe to retry: {out}")
    assert out["dispatched"] is True and out["status"] == "pending", out


@pytest.mark.parametrize("method,kwargs", [
    ("publish_mirror_post", {"title": "T", "content": "c"}),
    ("publish_paragraph_post", {"title": "T", "body": "b"}),
])
async def test_any_fault_reading_an_answer_is_not_never_sent(monkeypatch, method, kwargs):
    """The class, not the one type: a reader that fails in some other way
    after the gateway answered is the same fact."""
    monkeypatch.setattr(httpx, "AsyncClient", _gateway_answers(200, b'{"id": "x"}'))

    def _unreadable(self, **_kw):
        raise ValueError("a reply this code could not read")

    monkeypatch.setattr(httpx.Response, "json", _unreadable)
    out = await getattr(CreatorPlatformsService(_cfg()), method)(**kwargs)
    assert out["dispatched"] is True and out["status"] == "pending", out


async def test_a_refused_connection_is_still_safe_to_retry(monkeypatch):
    """SCOPE PIN: the request that provably never left still says so."""
    class _C(httpx.AsyncClient):
        def __init__(self, *a, **k):
            def _refuse(request):
                raise httpx.ConnectError("refused", request=request)
            k["transport"] = httpx.MockTransport(_refuse)
            super().__init__(*a, **k)

    monkeypatch.setattr(httpx, "AsyncClient", _C)
    out = await CreatorPlatformsService(_cfg()).publish_mirror_post(title="T", content="c")
    assert out["dispatched"] is False and "retrying is safe" in out["disclosure"], out


# ── the paymaster's send ───────────────────────────────────────────────────

class _Account:
    address = "0x" + "3" * 40

    def __init__(self, sign_fault: Exception | None = None) -> None:
        self._sign_fault = sign_fault

    def sign_transaction(self, _tx):
        if self._sign_fault is not None:
            raise self._sign_fault
        return SimpleNamespace(raw_transaction=b"\x01\x02", hash=bytes.fromhex("cd" * 32))


def _manager(send_fault: Exception | None, sign_fault: Exception | None = None):
    import asyncio

    lock = asyncio.Lock()

    def _send(_raw):
        raise send_fault

    eth = SimpleNamespace(get_transaction_count=lambda _a: 0, gas_price=1,
                          estimate_gas=lambda _tx: 21000, send_raw_transaction=_send)

    async def _signer(_action=None):
        return _Account(sign_fault)

    return SimpleNamespace(available=True, w3=SimpleNamespace(eth=eth), chain_id=8453,
                           signer=_signer, _get_nonce_lock=lambda: lock)


async def test_a_fault_from_the_nodes_reply_is_marked_as_handed_over():
    """web3 decodes the node's reply to send_raw_transaction AFTER the node
    has the bytes; a reply it cannot decode raises a ValueError."""
    fault = ValueError("Non-hexadecimal digit found")
    with pytest.raises(ValueError) as caught:
        await Web3Manager.send_transaction(_manager(fault), {"to": "0x" + "1" * 40})
    assert was_handed_to_node(caught.value)
    assert classify_transport_fault(caught.value) == "unknown"


async def test_a_fault_before_the_send_is_not_marked():
    fault = ValueError("invalid field")
    with pytest.raises(ValueError) as caught:
        await Web3Manager.send_transaction(
            _manager(RuntimeError("unreachable"), sign_fault=fault), {"to": "0x" + "1" * 40})
    assert not was_handed_to_node(caught.value)
    assert classify_transport_fault(caught.value) == "not_sent"


async def test_a_mint_whose_send_raised_after_the_hand_over_may_be_minting():
    cfg = {"services": {"creator_platforms": {
        "enabled": True, "sound_edition_address": "0x" + "5" * 40}}}
    svc = CreatorPlatformsService(cfg)
    fault = ValueError("Non-hexadecimal digit found")
    mark_handed_to_node(fault)

    class _Contract:
        class functions:  # noqa: N801 — the web3 attribute name
            @staticmethod
            def mint(_to, _qty):
                return SimpleNamespace(build_transaction=lambda tx: dict(tx))

    async def _send(_tx, **_kw):
        raise fault

    svc._web3 = SimpleNamespace(
        available=True, paymaster_key="0x" + "1" * 64,
        w3=SimpleNamespace(to_checksum_address=lambda a: a),
        load_contract=lambda *_a: _Contract(),
        get_account=lambda: _Account(), send_transaction=_send)
    out = await svc.mint_sound(to="0x" + "7" * 40, quantity=1)
    assert out.get("status") == "pending" and out.get("dispatched") is True, out


# ── the deployment ─────────────────────────────────────────────────────────

def _deploying(monkeypatch, send_fault: Exception | None, sign_fault: Exception | None = None):
    from runtime.blockchain.services.contract_conversion.service import (
        ContractConversionService,
    )

    fake_solcx = types.ModuleType("solcx")
    fake_solcx.compile_source = lambda *_a, **_k: {"<stdin>:Drop": {"abi": [], "bin": "6000"}}
    monkeypatch.setitem(sys.modules, "solcx", fake_solcx)
    svc = ContractConversionService({"conversion": {"auto_deploy": True}})
    monkeypatch.setattr(svc, "_ensure_solc", lambda: True)

    manager = _manager(send_fault, sign_fault)
    manager.w3.eth.contract = lambda **_kw: SimpleNamespace(
        constructor=lambda: SimpleNamespace(build_transaction=lambda tx: dict(tx)))
    manager.explorer_url = lambda h: None
    svc._web3 = manager
    return svc


async def test_a_deployment_whose_send_raised_is_not_called_undeployed(monkeypatch):
    svc = _deploying(monkeypatch, TimeoutError("read timed out"))
    out = await svc._compile_and_deploy("contract Drop {}", "Drop")
    assert out["status"] != "error", (
        f"a deployment the node may have accepted was reported as an error: {out}")
    assert out["status"] == "pending" and out["broadcast"] is True, out
    assert out["tx_hash"] == "cd" * 32, "the hash of the signed deployment was lost"


async def test_a_deployment_that_failed_before_it_was_sent_is_an_error(monkeypatch):
    """SCOPE PIN: nothing sent is still `error`."""
    svc = _deploying(monkeypatch, RuntimeError("unreachable"),
                     sign_fault=ValueError("invalid field"))
    out = await svc._compile_and_deploy("contract Drop {}", "Drop")
    assert out["status"] == "error" and out["stage"] == "deploy", out


def test_the_deploy_docstring_names_every_status_nothing_deployed_answers():
    import inspect

    from runtime.blockchain.services.contract_conversion.service import (
        ContractConversionService,
    )

    doc = " ".join(inspect.getdoc(ContractConversionService._compile_and_deploy).split())
    src = inspect.getsource(ContractConversionService._compile_and_deploy)
    # The two answers the method writes itself when nothing was deployed.
    for status in ("skipped", "error"):
        assert f'"status": "{status}"' in src, f"premise: the method answers {status!r}"
    for status in ("skipped", "error", "deployed", "failed", "pending"):
        assert f"``{status}``" in doc or f'"{status}"' in doc, (
            f"the docstring does not say when it answers {status!r}")
    assert 'Returns ``{"status": "error", ...}`` when nothing was deployed' not in doc
