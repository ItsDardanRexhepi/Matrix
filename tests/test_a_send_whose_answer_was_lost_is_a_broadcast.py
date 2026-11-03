"""A restaking send whose answer was lost is a broadcast, not a refusal.

Each of RestakingService's seven value-moving methods says, above its
`settle_transaction` call: "no receipt -> pending + broadcast:True, so a
broadcast transaction is never recorded as a refusal." That held for a
transaction whose hash came back and whose receipt did not. It did not hold for
the send itself: when `send_raw_transaction` raises after the signed bytes
reached the node (a read timeout, a reset connection, a reply that does not
decode), the method's `except` answered `{"status": "error"}`, and the service
dispatcher records that as "ACTION DECLINED" — about a transaction that may be
mined, with no hash anyone could look it up by.

`Web3Manager.send_transaction` already marked such an exception as handed to
the node. It now also carries the hash of the transaction that was signed, and
the restaking methods answer that fault with the one broadcast shape
(`unconfirmed_broadcast`) under that hash, so the dispatcher records a
broadcast.
"""

from __future__ import annotations

from types import SimpleNamespace

import pytest

from runtime.blockchain.services.restaking.service import RestakingService
from runtime.blockchain.services.service_dispatcher import (
    RECORD_BROADCAST,
    RECORD_REFUSED,
    _record_verdict,
)
from runtime.blockchain.web3_manager import Web3Manager, was_handed_to_node

VAULT = "0x2222222222222222222222222222222222222222"
OPERATOR = "0x3333333333333333333333333333333333333333"
SIGNED_HASH = bytes.fromhex("cd" * 32)


class _Account:
    address = "0x" + "1" * 40

    def __init__(self, sign_fault: Exception | None = None) -> None:
        self._sign_fault = sign_fault

    def sign_transaction(self, _tx):
        if self._sign_fault is not None:
            raise self._sign_fault
        return SimpleNamespace(raw_transaction=b"\x01\x02", hash=SIGNED_HASH)


def _manager(send_fault: Exception, sign_fault: Exception | None = None,
             nonce_fault: Exception | None = None):
    """The parts of a Web3Manager its own send_transaction reads, around a
    node whose answer to the send raises (or, with *nonce_fault*, whose answer
    to the nonce lookup before it does)."""
    import asyncio

    lock = asyncio.Lock()

    def _send(_raw):
        raise send_fault

    def _nonce(_a):
        if nonce_fault is not None:
            raise nonce_fault
        return 0

    eth = SimpleNamespace(get_transaction_count=_nonce, gas_price=1,
                          estimate_gas=lambda _tx: 21000, send_raw_transaction=_send)

    async def _signer(_action=None):
        return _Account(sign_fault)

    return SimpleNamespace(available=True, w3=SimpleNamespace(eth=eth), chain_id=8453,
                           signer=_signer, _get_nonce_lock=lambda: lock)


async def test_the_manager_says_which_transaction_it_handed_over():
    from runtime.blockchain import web3_manager

    fault = TimeoutError("read timed out")
    with pytest.raises(TimeoutError) as caught:
        await Web3Manager.send_transaction(_manager(fault), {"to": VAULT})
    assert was_handed_to_node(caught.value)
    handed = getattr(web3_manager, "handed_tx_hash", lambda _exc: "")
    assert handed(caught.value) == SIGNED_HASH.hex(), (
        "the fault does not say which signed transaction reached the node")


class _Stub:
    """The Web3Manager surface the restaking methods touch, sending through a
    send that raises as the real one does after the hand-over."""

    available = True
    chain_id = 8453

    def __init__(self, manager) -> None:
        from web3 import Web3

        self.w3 = Web3()
        self._manager = manager
        self.sent = 0

    def is_placeholder(self, _v):
        return False

    def get_account(self):
        return SimpleNamespace(address="0x" + "1" * 40)

    def explorer_url(self, h):
        return f"https://basescan.org/tx/{h}"

    def load_contract(self, addr, abi):
        class _Fn:
            @staticmethod
            def build_transaction(opts):
                return {"to": addr, "data": "0x", **opts}

            @staticmethod
            def call():
                return VAULT

        class _Functions:
            def __getattr__(self, _name):
                return lambda *a, **k: _Fn()

        return SimpleNamespace(functions=_Functions())

    async def send_transaction(self, tx, **_kw):
        """The real Web3Manager.send_transaction, so the exception carries
        exactly what that method marks on it."""
        self.sent += 1
        return await Web3Manager.send_transaction(self._manager, tx)

    async def wait_for_receipt(self, tx_hash, timeout=120):  # pragma: no cover
        raise AssertionError("nothing was sent, so nothing is waited for")


def _svc(manager) -> RestakingService:
    svc = RestakingService({"services": {"restaking": {
        "enabled": True,
        "karak_vault_address": VAULT, "symbiotic_vault_address": VAULT,
        "lido_steth_address": VAULT, "strategy_manager_address": VAULT,
        "strategy_address": VAULT, "delegation_manager_address": VAULT,
        "rocketpool_deposit_address": VAULT,
    }}})
    svc._web3 = _Stub(manager)
    return svc


_SEVEN = [
    ("restake", {"amount": 1}),
    ("restake_symbiotic", {"amount": 1}),
    ("restake_karak", {"amount": 1}),
    ("delegate_to_operator", {"operator": OPERATOR}),
    ("withdraw_restake", {"shares": 1}),
    ("liquid_stake_lido", {"amount": 1}),
    ("liquid_stake_rocketpool", {"amount": 1}),
]


#: What a node can do to the answer once it has the bytes: time out reading it,
#: reset the connection, or send back something that does not decode. Each is a
#: fresh exception per case, because the hand-over is marked on the exception.
_LOST_ANSWERS = {
    "timeout": lambda: TimeoutError("read timed out"),
    "reset": lambda: ConnectionResetError("connection reset by peer"),
    "undecodable": lambda: ValueError("Non-hexadecimal digit found"),
}


@pytest.mark.parametrize("lost", sorted(_LOST_ANSWERS))
@pytest.mark.parametrize("method,kwargs", _SEVEN, ids=[m for m, _ in _SEVEN])
async def test_a_send_whose_answer_was_lost_is_recorded_as_a_broadcast(method, kwargs, lost):
    """Decided by the hand-over, not by the kind of fault: every one of these
    after the node took the bytes is a broadcast."""
    svc = _svc(_manager(_LOST_ANSWERS[lost]()))

    out = await getattr(svc, method)(**kwargs)

    assert svc._web3.sent == 1, f"premise: {method} reached its send: {out}"
    assert _record_verdict(out) == RECORD_BROADCAST, (
        f"{method}: a send that raised after the hand-over is recorded as "
        f"{_record_verdict(out)}: {out}")
    assert out["tx_hash"] == SIGNED_HASH.hex()
    assert out["broadcast"] is True and out["settled"] is False


@pytest.mark.parametrize("method,kwargs", _SEVEN, ids=[m for m, _ in _SEVEN])
async def test_a_fault_before_the_hand_over_is_still_a_refusal(method, kwargs):
    """SCOPE PIN: a send that never reached the node is an error, as before."""
    svc = _svc(_manager(RuntimeError("never reached"), sign_fault=ValueError("could not sign")))

    out = await getattr(svc, method)(**kwargs)

    assert svc._web3.sent == 1, f"premise: {method} reached its send: {out}"
    assert out["status"] == "error"
    assert _record_verdict(out) == RECORD_REFUSED


@pytest.mark.parametrize("method,kwargs", _SEVEN, ids=[m for m, _ in _SEVEN])
async def test_a_timeout_before_the_hand_over_is_still_a_refusal(method, kwargs):
    """SCOPE PIN: a timeout is not by itself a broadcast. One on the nonce
    lookup, before anything was signed or sent, is an error, as before."""
    svc = _svc(_manager(AssertionError("not reached"),
                        nonce_fault=TimeoutError("nonce lookup timed out")))

    out = await getattr(svc, method)(**kwargs)

    assert svc._web3.sent == 1, f"premise: {method} reached its send: {out}"
    assert out["status"] == "error", out
    assert _record_verdict(out) == RECORD_REFUSED, out
