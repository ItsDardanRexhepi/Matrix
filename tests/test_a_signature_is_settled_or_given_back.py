"""A sponsored signature's ledger row says what became of it.

attest-money F17. `SponsorshipPolicy.settle` and `.abandon` existed, and
`MeteredSigner.last_reservation_id` was added so a caller could reach them —
and nothing in production called any of the three. Every metered signature
stayed SIGNED until the 24h sweep: the ledger never recorded SPENT, and a
signature the node refused outright never gave its budget back. Live, because
`Web3Manager.send_transaction` — the one signing path of the services — signs
through the metered platform signer.

The row is now closed by the two places that learn a signature's fate, keyed
by the transaction hash the signed bytes already determine:

    a receipt arrives (mined, success or revert)  -> SPENT     wait_for_receipt_on
    the node answers the send with a refusal       -> released  Web3Manager.send_transaction

and it stays SIGNED — holding budget — for everything that does not establish
either: a transport fault on the send, a node saying it already has the bytes,
a receipt wait that runs out.

SIBLING AXIS, named and not changed: the metered blockchain capabilities in
runtime/blockchain/*.py (nfts, staking, daos, payments, gaming, eas_manager,
stablecoins, tokenization, ip_royalties, securities, governance,
smart_contracts, defi) and contract_conversion's deploy sign through the
metered signer and broadcast with their own `send_raw_transaction`, so a node
refusal there still leaves the row SIGNED until the sweep (the budget is held,
never over-granted). Their receipts DO settle: they wait through `_receipt` ->
`receipt_within` -> `wait_for_receipt_on`, or through `settle_transaction`.
"""

from __future__ import annotations

import pytest
from eth_account import Account

from runtime.blockchain.sponsorship import (
    SPEND_STATES,
    MeteredSigner,
    SponsorshipPolicy,
    node_refused,
)
from runtime.blockchain.web3_manager import Web3Manager, wait_for_receipt_on

_TX = {"to": "0x" + "11" * 20, "value": 0, "gas": 21000,
       "gasPrice": 1_000_000_000, "nonce": 0, "chainId": 8453}


def _policy(tmp_path) -> SponsorshipPolicy:
    return SponsorshipPolicy.from_config({
        "paymaster": {"policy": {"daily_cap_usd": 100.0}},
        "database": {"path": str(tmp_path / "sponsor.db")},
    })


def _signer(policy) -> MeteredSigner:
    return MeteredSigner(Account.create(), policy, "web3.send_transaction", "0xA", 3000.0)


class _Eth:
    def __init__(self, *, send_raises=None, receipt=None, receipt_raises=None):
        self._send_raises = send_raises
        self._receipt = receipt
        self._receipt_raises = receipt_raises
        self.gas_price = 1_000_000_000

    def send_raw_transaction(self, raw):
        if self._send_raises is not None:
            raise self._send_raises
        from eth_utils import keccak
        return keccak(raw)

    def get_transaction_count(self, _addr):
        return 0

    def wait_for_transaction_receipt(self, _tx_hash, timeout=0):
        if self._receipt_raises is not None:
            raise self._receipt_raises
        return self._receipt


class _W3:
    def __init__(self, eth: _Eth) -> None:
        self.eth = eth


def _manager(w3, signer) -> Web3Manager:
    mgr = Web3Manager.__new__(Web3Manager)
    mgr.w3 = w3
    mgr.available = True
    mgr.chain_id = 8453
    mgr._nonce_lock = None

    async def _signer_for(_action=None):
        return signer

    mgr.signer = _signer_for
    return mgr


async def test_a_mined_transaction_is_recorded_as_spent(tmp_path):
    """DEFECT-PROVER. The receipt came back and the row still said SIGNED."""
    policy = _policy(tmp_path)
    signer = _signer(policy)
    signed = signer.sign_transaction(dict(_TX))
    row = signer.last_reservation_id

    receipt = await wait_for_receipt_on(
        _W3(_Eth(receipt={"status": 1, "blockNumber": 7})), signed.hash, timeout=2)

    assert receipt["status"] == 1, "the caller must still get its receipt"
    assert policy.state_of(row) == SPEND_STATES.SPENT


async def test_a_mined_revert_is_recorded_as_spent_too(tmp_path):
    """A revert pays gas. Recording it as anything but spent would hand back
    budget that was used."""
    policy = _policy(tmp_path)
    signer = _signer(policy)
    signed = signer.sign_transaction(dict(_TX))

    await wait_for_receipt_on(_W3(_Eth(receipt={"status": 0})), signed.hash, timeout=2)

    assert policy.state_of(signer.last_reservation_id) == SPEND_STATES.SPENT
    assert policy.spent_today("0xA") > 0


async def test_a_signature_the_node_refused_gives_its_budget_back(tmp_path):
    """DEFECT-PROVER, the other direction, through the real send path."""
    from web3.exceptions import Web3RPCError

    policy = _policy(tmp_path)
    signer = _signer(policy)
    mgr = _manager(_W3(_Eth(send_raises=Web3RPCError("nonce too low"))), signer)

    with pytest.raises(Web3RPCError):
        await mgr.send_transaction(dict(_TX))

    assert policy.state_of(signer.last_reservation_id) is None, (
        "a transaction the node refused still holds sponsorship budget"
    )
    assert policy.spent_today("0xA") == pytest.approx(0.0)


@pytest.mark.parametrize("label,exc", [
    ("a transport fault may have delivered the bytes", ConnectionError("reset by peer")),
    ("a timeout may have delivered the bytes", TimeoutError("read timed out")),
])
async def test_a_send_that_may_have_landed_keeps_its_budget(tmp_path, label, exc):
    """SCOPE PIN. Releasing on a fault that says nothing about delivery would
    over-grant sponsorship for a transaction that can still be mined."""
    policy = _policy(tmp_path)
    signer = _signer(policy)
    mgr = _manager(_W3(_Eth(send_raises=exc)), signer)

    with pytest.raises(type(exc)):
        await mgr.send_transaction(dict(_TX))

    assert policy.state_of(signer.last_reservation_id) == SPEND_STATES.SIGNED, label


async def test_a_node_that_already_has_the_bytes_is_not_a_refusal(tmp_path):
    from web3.exceptions import Web3RPCError

    policy = _policy(tmp_path)
    signer = _signer(policy)
    mgr = _manager(_W3(_Eth(send_raises=Web3RPCError("already known"))), signer)

    with pytest.raises(Web3RPCError):
        await mgr.send_transaction(dict(_TX))

    assert policy.state_of(signer.last_reservation_id) == SPEND_STATES.SIGNED


async def test_a_wait_that_runs_out_keeps_the_signature_signed(tmp_path):
    policy = _policy(tmp_path)
    signer = _signer(policy)
    signed = signer.sign_transaction(dict(_TX))

    with pytest.raises(TimeoutError):
        await wait_for_receipt_on(
            _W3(_Eth(receipt_raises=TimeoutError("slice"))), signed.hash, timeout=1)

    assert policy.state_of(signer.last_reservation_id) == SPEND_STATES.SIGNED


async def test_send_then_settle_end_to_end(tmp_path):
    """The whole path a service takes: `send_transaction`, then
    `settle_transaction` over the same manager — the hash the send returns is
    the hash the row was filed under."""
    from runtime.blockchain.web3_manager import settle_transaction

    policy = _policy(tmp_path)
    signer = _signer(policy)
    mgr = _manager(_W3(_Eth(receipt={"status": 1, "blockNumber": 9})), signer)

    tx_hash = await mgr.send_transaction(dict(_TX))
    outcome = await settle_transaction(mgr, tx_hash, "m", "svc", timeout=2)

    assert outcome["settled"] is True
    assert policy.state_of(signer.last_reservation_id) == SPEND_STATES.SPENT


@pytest.mark.parametrize("exc,expected", [
    (ValueError({"code": -32000, "message": "nonce too low"}), True),
    (ValueError({"code": -32000, "message": "already known"}), False),
    (ValueError("not an rpc answer"), False),
    (OSError("broken pipe"), False),
])
def test_what_counts_as_the_node_saying_no(exc, expected):
    assert node_refused(exc) is expected
