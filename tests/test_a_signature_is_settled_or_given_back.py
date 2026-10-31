"""A sponsored signature's ledger row says what became of it.

attest-money F17. `SponsorshipPolicy.settle` and `.abandon` existed, and
`MeteredSigner.last_reservation_id` was added so a caller could reach them —
and nothing in production called any of the three. Every metered signature
stayed SIGNED until the 24h sweep: the ledger never recorded SPENT, and a
signature that never reached the chain never gave its budget back. Live,
because `Web3Manager.send_transaction` — the path the services sign through —
signs through the metered platform signer.

The signer files each signature under its transaction hash and in its nonce
slot (the chain, the account and the nonce it was signed with), and a receipt
closes the rows:

    its own receipt (mined, success or revert)             -> SPENT
    the receipt of another transaction the platform
    signed in the same slot                                -> given back

Only one transaction in a slot can ever be mined, so once one is, no other
signature in it ever will be: one the node refused, one whose fate nobody
learned, one never broadcast, and an earlier signature of the very same bytes,
whose one payment the mined copy's row already holds.

What the node answers the send closes nothing. The budget used to come back
for an answer on a list of refusals, once the node, asked by hash, held no
copy. Neither answer is about the network: a proxy that retries a POST can
deliver the bytes to one backend and relay another's refusal, and the lookup
can be answered by a backend that cannot see that pool. Over real HTTP that
gave the budget back for a transaction then mined, and granted the identity's
next send past its cap. The lookup also held a thread of the process's shared
pool for most of a minute against a node that does not answer, and enough
refused sends at once left an unrelated receipt wait queued behind them.

SIBLING AXIS, named and not changed: a receipt read anywhere but through
`wait_for_receipt_on` (the deploy tools in contracts/, demo.py, and the
crossborder, dashboard and real-estate reads by hash) settles nothing and gives
nothing back, and a row this process no longer holds (evicted, or signed by a
process since restarted) stays SIGNED until its window passes: budget held,
never handed out.
"""

from __future__ import annotations

import pytest
from eth_account import Account

from runtime.blockchain.sponsorship import (
    SPEND_STATES,
    MeteredSigner,
    SponsorshipPolicy,
)
from runtime.blockchain.web3_manager import Web3Manager, wait_for_receipt_on

_TX = {"to": "0x" + "11" * 20, "value": 0, "gas": 21000,
       "gasPrice": 1_000_000_000, "nonce": 0, "chainId": 8453}

# What one signature of _TX holds: 21000 gas at 1 gwei, ETH at $3000.
_ONE_SIGNATURE_USD = 21000 * 1_000_000_000 / 1e18 * 3000.0

_INSUFFICIENT = {"code": -32000, "message": "insufficient funds for gas * price + value"}


def _policy(tmp_path) -> SponsorshipPolicy:
    return SponsorshipPolicy.from_config({
        "paymaster": {"policy": {"daily_cap_usd": 100.0}},
        "database": {"path": str(tmp_path / "sponsor.db")},
    })


def _signer(policy, account=None, action="web3.send_transaction") -> MeteredSigner:
    return MeteredSigner(account or Account.create(), policy, action, "0xA", 3000.0)


def _rpc_error(error: dict):
    from web3.exceptions import Web3RPCError

    return Web3RPCError(repr(error), rpc_response={"error": error})


class _Eth:
    """A node, in process. Each send hears the next of *answers*: an exception
    is raised, None means the node took the bytes."""

    def __init__(self, answers=(), *, receipt=None, receipt_raises=None):
        self._answers = list(answers)
        self._receipt = receipt
        self._receipt_raises = receipt_raises
        self.reads_after_a_send: list[str] = []
        self.gas_price = 1_000_000_000

    def send_raw_transaction(self, raw):
        answer = self._answers.pop(0) if self._answers else None
        if answer is not None:
            raise answer
        from eth_utils import keccak
        return keccak(raw)

    def get_transaction(self, tx_hash):
        self.reads_after_a_send.append("get_transaction")
        from web3.exceptions import TransactionNotFound
        raise TransactionNotFound(f"Transaction with hash: {tx_hash!r} not found.")

    def get_transaction_count(self, _addr):
        return 0

    def wait_for_transaction_receipt(self, _tx_hash, timeout=0):
        if self._receipt_raises is not None:
            raise self._receipt_raises
        return self._receipt


class _W3:
    def __init__(self, eth: _Eth) -> None:
        self.eth = eth


def _manager(w3, policy, signers: list, *, account=None) -> Web3Manager:
    """A manager whose every send gets a signer of its own, as production's
    `Web3Manager.signer()` builds one per call, all over one platform key."""
    account = account or Account.create()
    mgr = Web3Manager.__new__(Web3Manager)
    mgr.w3 = w3
    mgr.available = True
    mgr.chain_id = 8453
    mgr._nonce_lock = None

    async def _signer_for(_action=None):
        signer = _signer(policy, account)
        signers.append(signer)
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
    signers: list = []
    mgr = _manager(_W3(_Eth(receipt={"status": 1, "blockNumber": 9})), policy, signers)

    tx_hash = await mgr.send_transaction(dict(_TX))
    outcome = await settle_transaction(mgr, tx_hash, "m", "svc", timeout=2)

    assert outcome["settled"] is True
    assert policy.state_of(signers[0].last_reservation_id) == SPEND_STATES.SPENT


@pytest.mark.parametrize("label,exc", [
    ("a transport fault may have delivered the bytes", ConnectionError("reset by peer")),
    ("a timeout may have delivered the bytes", TimeoutError("read timed out")),
])
async def test_a_send_that_may_have_landed_keeps_its_budget(tmp_path, label, exc):
    """SCOPE PIN. Releasing on a fault that says nothing about delivery would
    over-grant sponsorship for a transaction that can still be mined."""
    policy = _policy(tmp_path)
    signers: list = []
    mgr = _manager(_W3(_Eth([exc])), policy, signers)

    with pytest.raises(type(exc)):
        await mgr.send_transaction(dict(_TX))

    assert policy.state_of(signers[0].last_reservation_id) == SPEND_STATES.SIGNED, label


# ── what the node answers the send gives nothing back ───────────────────────
#
# Every answer below once had a reading. The refusals a node gives when it turns
# a transaction away at its pool (geth, and op-geth, reth, erigon and anvil,
# which share its errors), and a node with no send method at all, gave the
# budget back once a lookup by hash found no copy. The rest kept it: timeouts in
# every spelling, proxy and transport failures relayed as JSON-RPC, rate limits,
# and the answers a node gives once the transaction is pending or mined. None of
# them is an answer about the network, so none decides anything now.

_LISTED_REFUSALS = [
    "insufficient funds for gas * price + value",
    "insufficient funds for gas * price + value: balance 0, tx cost 21000000000000, overshot 21000000000000",
    "intrinsic gas too low",
    "intrinsic gas too low: gas 20000, minimum needed 21000",
    "transaction underpriced",
    "replacement transaction underpriced",
    "max fee per gas less than block base fee",
    "invalid sender",
    "exceeds block gas limit",
    "tx fee (1.20 ether) exceeds the configured cap (1.00 ether)",
    "txpool is full",
    "only replay-protected (EIP-155) transactions allowed over RPC",
    "invalid chain id for signer",
    "oversized data",
    "transaction type not supported",
    "max priority fee per gas higher than max fee per gas",
]

_PENDING_OR_MINED = [
    "nonce too low",
    "NonceTooLow",
    "Transaction nonce is too low. Try incrementing the nonce.",
    "already known",
    "AlreadyKnown",
    "known transaction: 0xabc",
]

_NOT_REFUSALS = [
    "request timed out",
    "Internal error",
    "context deadline exceeded",
    "gateway timeout",
    "Bad Gateway",
    "failed to forward tx to sequencer",
    "tx already in mempool",
    "rate limit exceeded",
    "",
]

_ANSWERS = (
    [{"code": -32000, "message": m} for m in _LISTED_REFUSALS + _PENDING_OR_MINED + _NOT_REFUSALS]
    + [{"code": -32601, "message": "the method eth_sendRawTransaction does not exist/is not available"},
       {"code": -32002, "message": "request timed out"},
       {"code": -32603, "message": "Internal error"}]
)


@pytest.mark.parametrize("error", _ANSWERS, ids=lambda e: f"{e['code']} {e['message'][:48]}")
async def test_no_answer_to_the_send_gives_budget_back(tmp_path, error):
    """DEFECT-PROVER for the refusals on the list and the missing send method:
    each gave the budget back the moment the node, asked by hash, held no copy."""
    policy = _policy(tmp_path)
    signers: list = []
    mgr = _manager(_W3(_Eth([_rpc_error(error)])), policy, signers)

    with pytest.raises(Exception):
        await mgr.send_transaction(dict(_TX))

    assert policy.state_of(signers[0].last_reservation_id) == SPEND_STATES.SIGNED, (
        f"{error['message']!r} gave a signature's budget back; an answer to the send "
        f"is not an answer about the network")
    assert policy.spent_today("0xA") == pytest.approx(_ONE_SIGNATURE_USD)


async def test_a_refused_signature_is_given_back_once_another_takes_its_nonce(tmp_path):
    """DEFECT-PROVER, and what gives the budget back now. The node refuses the
    first send; the next transaction from the platform account goes out under
    the same nonce, because the refused one never took it, and is mined. The two
    could never both be, so the refused one never will be."""
    policy = _policy(tmp_path)
    signers: list = []
    eth = _Eth([_rpc_error(_INSUFFICIENT)], receipt={"status": 1, "blockNumber": 9})
    mgr = _manager(_W3(eth), policy, signers)

    with pytest.raises(Exception):
        await mgr.send_transaction(dict(_TX))
    refused = signers[0].last_reservation_id
    assert policy.state_of(refused) == SPEND_STATES.SIGNED, (
        "the refusal gave the budget back; only a receipt in its slot may")

    tx_hash = await mgr.send_transaction({**_TX, "value": 1})
    await wait_for_receipt_on(_W3(eth), tx_hash, timeout=2)

    assert policy.state_of(signers[1].last_reservation_id) == SPEND_STATES.SPENT
    assert policy.state_of(refused) is None, (
        "another transaction took the refused one's nonce and was mined, and the "
        "refused signature still holds budget")
    assert policy.spent_today("0xA") == pytest.approx(_ONE_SIGNATURE_USD)


async def test_a_signature_never_sent_is_given_back_once_its_nonce_is_taken(tmp_path):
    """DEFECT-PROVER. Whichever path signed it and whatever became of its send
    (a capability that broadcasts on its own, a send that raised before the
    bytes left), a signature whose nonce another mined transaction took holds
    nothing the chain can still charge."""
    policy = _policy(tmp_path)
    account = Account.create()
    first = _signer(policy, account, action="staking.stake")
    first.sign_transaction(dict(_TX))
    second = _signer(policy, account)
    mined = second.sign_transaction({**_TX, "value": 1})

    await wait_for_receipt_on(_W3(_Eth(receipt={"status": 1})), mined.hash, timeout=2)

    assert policy.state_of(first.last_reservation_id) is None
    assert policy.state_of(second.last_reservation_id) == SPEND_STATES.SPENT


async def test_an_unmetered_signatures_receipt_takes_the_nonce_too(tmp_path):
    """DEFECT-PROVER. The platform's own records are signed unmetered and have no
    row, but a transaction of theirs mined in a slot is as final as any."""
    from runtime.blockchain.sponsorship import unmetered_platform_signer

    policy = _policy(tmp_path)
    account = Account.create()
    metered = _signer(policy, account)
    metered.sign_transaction(dict(_TX))
    record = unmetered_platform_signer(account.key, "eas.attest")
    mined = record.sign_transaction({**_TX, "value": 1})

    await wait_for_receipt_on(_W3(_Eth(receipt={"status": 1})), mined.hash, timeout=2)

    assert policy.state_of(metered.last_reservation_id) is None


async def test_the_same_bytes_signed_twice_and_mined_once_are_held_once(tmp_path):
    """DEFECT-PROVER. A send whose fate nobody learned, and a second send of the
    very same bytes: signing is deterministic, so it is one transaction signed
    twice, and it is mined once. Both rows held budget until the window passed,
    an identity charged twice for one payment. The mined copy's row is spent and
    the other is given back."""
    policy = _policy(tmp_path)
    signers: list = []
    eth = _Eth([TimeoutError("read timed out")], receipt={"status": 1, "blockNumber": 3})
    mgr = _manager(_W3(eth), policy, signers)

    with pytest.raises(TimeoutError):
        await mgr.send_transaction(dict(_TX))
    tx_hash = await mgr.send_transaction(dict(_TX))
    first, second = (s.last_reservation_id for s in signers)
    assert first != second
    assert policy.spent_today("0xA") == pytest.approx(2 * _ONE_SIGNATURE_USD)

    await wait_for_receipt_on(_W3(eth), tx_hash, timeout=2)

    assert sorted([str(policy.state_of(first)), str(policy.state_of(second))]) == [
        "None", SPEND_STATES.SPENT]
    assert policy.spent_today("0xA") == pytest.approx(_ONE_SIGNATURE_USD)


@pytest.mark.parametrize("label,mined_tx,other_account", [
    ("another chain", {**_TX, "chainId": 1, "value": 1}, False),
    ("another account", {**_TX, "value": 1}, True),
    ("the next nonce, which a mined copy of the first would also leave", {**_TX, "nonce": 1}, False),
])
async def test_a_slot_is_one_chain_one_account_one_nonce(tmp_path, label, mined_tx, other_account):
    """SCOPE PIN. A receipt says nothing about a signature outside its slot: on
    another chain the nonce is another account's history, another account's
    nonce is its own, and a later nonce mined says the first was taken, not by
    whom, so the first may be the one mined."""
    policy = _policy(tmp_path)
    account = Account.create()
    held = _signer(policy, account)
    held.sign_transaction(dict(_TX))
    other = _signer(policy, Account.create() if other_account else account)
    mined = other.sign_transaction(mined_tx)

    await wait_for_receipt_on(_W3(_Eth(receipt={"status": 1})), mined.hash, timeout=2)

    assert policy.state_of(held.last_reservation_id) == SPEND_STATES.SIGNED, label


async def test_a_transaction_without_a_chain_id_is_in_no_slot(tmp_path):
    """SCOPE PIN. A legacy transaction signed without a chain id can be mined on
    any chain that shares the account, so no receipt on one chain shows it can
    never be mined, and none of its own gives another's budget back."""
    policy = _policy(tmp_path)
    account = Account.create()
    legacy = {k: v for k, v in _TX.items() if k != "chainId"}
    held = _signer(policy, account)
    held.sign_transaction(dict(legacy))
    other = _signer(policy, account)
    mined = other.sign_transaction({**legacy, "value": 1})

    await wait_for_receipt_on(_W3(_Eth(receipt={"status": 1})), mined.hash, timeout=2)

    assert policy.state_of(held.last_reservation_id) == SPEND_STATES.SIGNED
    assert policy.state_of(other.last_reservation_id) == SPEND_STATES.SPENT


async def test_the_same_bytes_without_a_chain_id_keep_both_rows(tmp_path):
    """SCOPE PIN. Bytes signed with no chain id can be mined on another chain
    the account is on as well, so a receipt for them on one chain is not their
    only payment, and an earlier signature of them keeps holding."""
    policy = _policy(tmp_path)
    account = Account.create()
    legacy = {k: v for k, v in _TX.items() if k != "chainId"}
    first = _signer(policy, account)
    signed = first.sign_transaction(dict(legacy))
    second = _signer(policy, account)
    second.sign_transaction(dict(legacy))

    await wait_for_receipt_on(_W3(_Eth(receipt={"status": 1})), signed.hash, timeout=2)

    assert policy.state_of(first.last_reservation_id) == SPEND_STATES.SIGNED
    assert policy.state_of(second.last_reservation_id) == SPEND_STATES.SPENT


async def test_a_row_the_table_no_longer_holds_stays_signed(tmp_path, monkeypatch):
    """SCOPE PIN. The tables are bounded; a signature they evicted is no longer
    known by hash or by slot, so nothing gives it back, and it holds its budget
    until its window passes."""
    from runtime.blockchain import sponsorship

    monkeypatch.setattr(sponsorship, "_MAX_TRACKED_SIGNATURES", 2)
    policy = _policy(tmp_path)
    account = Account.create()
    evicted = _signer(policy, account)
    evicted.sign_transaction(dict(_TX))
    for n in (1, 2):
        _signer(policy, Account.create()).sign_transaction({**_TX, "nonce": n})
    mined = _signer(policy, account).sign_transaction({**_TX, "value": 1})

    await wait_for_receipt_on(_W3(_Eth(receipt={"status": 1})), mined.hash, timeout=2)

    assert policy.state_of(evicted.last_reservation_id) == SPEND_STATES.SIGNED


async def test_refused_sends_hold_up_no_receipt_wait(tmp_path):
    """DEFECT-PROVER. The lookup the release made after a refusal ran in the
    process's shared worker pool, one unsliced call, for most of a minute against
    a node that does not answer. With more refused sends at once than the pool
    has threads, an unrelated receipt that was already there waited behind
    them. Here the pool has two threads, four sends are refused, and the node
    takes three seconds over a lookup."""
    import asyncio
    import concurrent.futures
    import threading
    import time

    loop = asyncio.get_running_loop()
    pool = concurrent.futures.ThreadPoolExecutor(max_workers=2)
    loop.set_default_executor(pool)
    answered = threading.Event()

    class _SlowLookup(_Eth):
        def get_transaction(self, tx_hash):
            answered.wait(timeout=3.0)
            return super().get_transaction(tx_hash)

    policy = _policy(tmp_path)
    sends = []
    for _ in range(4):
        mgr = _manager(_W3(_SlowLookup([_rpc_error(_INSUFFICIENT)])), policy, [])
        sends.append(asyncio.ensure_future(mgr.send_transaction(dict(_TX))))
    await asyncio.sleep(0.2)

    started = time.monotonic()
    receipt = await wait_for_receipt_on(
        _W3(_Eth(receipt={"status": 1})), "0x" + "22" * 32, timeout=10)
    waited = time.monotonic() - started
    answered.set()
    await asyncio.gather(*sends, return_exceptions=True)
    pool.shutdown(wait=True)

    assert receipt["status"] == 1
    assert waited < 1.0, f"an unrelated receipt waited {waited:.2f}s behind refused sends"


# ── the real provider ──────────────────────────────────────────────────────
#
# The shared manager's HTTP provider once carried web3's default retry, whose
# list includes eth_sendRawTransaction. A first POST that delivered the bytes
# and lost its reply was sent again, the node answered the SECOND delivery, and
# once the first was mined that answer was "nonce too low". The provider now
# sends a raw transaction once; what the answer says is still not read as the
# signature's fate.

import json  # noqa: E402

import requests  # noqa: E402

_RPC_URL = "http://rpc.node.test"


def _rpc_reply(request_body: bytes, *, result=None, error=None) -> requests.Response:
    rid = json.loads(request_body).get("id", 1)
    body = {"jsonrpc": "2.0", "id": rid}
    if error is not None:
        body["error"] = error
    else:
        body["result"] = result
    reply = requests.Response()
    reply.status_code = 200
    reply._content = json.dumps(body).encode()
    reply.headers["Content-Type"] = "application/json"
    return reply


class _Node:
    """A JSON-RPC node behind a real `requests` session: the provider, its
    retry and web3's error decoding all run for real; only the wire is fake.
    Asked for a transaction by hash, it answers null: whatever took the bytes,
    the backend that answers lookups cannot see it."""

    def __init__(self, raw_answers):
        self.raw_answers = list(raw_answers)
        self.raw_posts = 0
        self.methods: list[str] = []
        self.sent_hashes: list[str] = []

    def post(self, _url, data=None, **_kwargs):
        request = json.loads(data)
        method = request["method"]
        self.methods.append(method)
        if method == "web3_clientVersion":
            return _rpc_reply(data, result="node/test")
        if method == "eth_sendRawTransaction":
            from eth_utils import keccak
            self.sent_hashes.append("0x" + keccak(hexstr=request["params"][0]).hex())
            self.raw_posts += 1
            answer = self.raw_answers.pop(0) if self.raw_answers else requests.Timeout("lost")
            if isinstance(answer, BaseException):
                raise answer
            return _rpc_reply(data, error=answer)
        if method == "eth_getTransactionByHash":
            return _rpc_reply(data, result=None)
        raise AssertionError(f"unexpected RPC {method}")


def _live_manager(monkeypatch, node, policy, signers) -> Web3Manager:
    """The real Web3Manager, built by its own constructor, so its provider is
    the one production gets."""
    monkeypatch.setattr(requests.Session, "post", node.post)
    mgr = Web3Manager({"blockchain": {"rpc_url": _RPC_URL, "chain_id": 8453}})
    assert mgr.available, "the test node did not answer the manager's connect check"
    account = Account.create()

    async def _signer_for(_action=None):
        signer = _signer(policy, account)
        signers.append(signer)
        return signer

    mgr.signer = _signer_for
    return mgr


async def test_a_refusal_relayed_for_bytes_another_backend_took_keeps_the_budget(
        tmp_path, monkeypatch):
    """DEFECT-PROVER for the over-grant. Behind a proxy that retries a POST, one
    backend took the bytes and the answer relayed is another backend's refusal;
    asked by hash, a third answers null. The budget came back, the backend that
    took the bytes mined them, and the platform paid gas the ledger no longer
    held."""
    policy = _policy(tmp_path)
    signers: list = []
    node = _Node([{"code": -32000, "message": "transaction underpriced"}])
    mgr = _live_manager(monkeypatch, node, policy, signers)

    with pytest.raises(Exception):
        await mgr.send_transaction(dict(_TX))
    row = signers[0].last_reservation_id

    assert policy.state_of(row) == SPEND_STATES.SIGNED, (
        "a refusal relayed for bytes another backend took gave the budget back")
    assert policy.spent_today("0xA") == pytest.approx(_ONE_SIGNATURE_USD)

    await wait_for_receipt_on(
        _W3(_Eth(receipt={"status": 1, "blockNumber": 5})), node.sent_hashes[0], timeout=2)

    assert policy.state_of(row) == SPEND_STATES.SPENT


async def test_the_send_asks_the_node_nothing_after_its_answer(tmp_path, monkeypatch):
    """DEFECT-PROVER. A refused send went on to ask the node for the transaction
    by hash, a read the provider retries on a timeout: most of a minute of a
    worker thread on a node that does not answer, for an answer that decides
    nothing."""
    policy = _policy(tmp_path)
    node = _Node([_INSUFFICIENT])
    mgr = _live_manager(monkeypatch, node, policy, [])

    with pytest.raises(Exception):
        await mgr.send_transaction(dict(_TX))

    assert node.raw_posts == 1
    assert node.methods[-1] == "eth_sendRawTransaction", (
        f"after its answer the send asked the node more: {node.methods}")


async def test_a_lost_reply_and_a_resend_that_hears_nonce_too_low_keep_the_budget(
        tmp_path, monkeypatch):
    """DEFECT-PROVER for the first over-grant. The first POST delivers the bytes
    and its reply is lost; the node's next answer about the same bytes is "nonce
    too low", because the transaction was mined in between. The platform paid
    that gas, so its budget stays held, and the bytes are POSTed once."""
    policy = _policy(tmp_path)
    signers: list = []
    node = _Node([requests.Timeout("reply lost after delivery"),
                  {"code": -32000, "message": "nonce too low"}])
    mgr = _live_manager(monkeypatch, node, policy, signers)

    with pytest.raises(Exception):
        await mgr.send_transaction(dict(_TX))

    assert policy.state_of(signers[0].last_reservation_id) == SPEND_STATES.SIGNED
    assert policy.spent_today("0xA") > 0
    assert node.raw_posts == 1, (
        f"the signed bytes were POSTed {node.raw_posts} times; an answer to a "
        f"re-send is not an answer about the first delivery"
    )


async def test_the_managers_provider_sends_a_raw_transaction_once(tmp_path, monkeypatch):
    policy = _policy(tmp_path)
    signers: list = []
    node = _Node([requests.Timeout("t1"), requests.Timeout("t2"), requests.Timeout("t3")])
    mgr = _live_manager(monkeypatch, node, policy, signers)

    with pytest.raises(requests.Timeout):
        await mgr.send_transaction(dict(_TX))

    assert node.raw_posts == 1
    assert policy.state_of(signers[0].last_reservation_id) == SPEND_STATES.SIGNED


@pytest.mark.parametrize("error", [
    {"code": -32002, "message": "request timed out"},
    {"code": -32603, "message": "Internal error"},
    {"code": -32000, "message": "context deadline exceeded"},
    {"code": -32000, "message": "insufficient funds for gas * price + value"},
    {"code": -32601, "message": "the method eth_sendRawTransaction does not exist/is not available"},
], ids=lambda e: e["message"][:40])
async def test_through_the_real_provider_no_answer_gives_budget_back(
        tmp_path, monkeypatch, error):
    """Through the real manager, provider and web3 error decoding."""
    policy = _policy(tmp_path)
    signers: list = []
    node = _Node([error])
    mgr = _live_manager(monkeypatch, node, policy, signers)

    with pytest.raises(Exception):
        await mgr.send_transaction(dict(_TX))

    assert policy.state_of(signers[0].last_reservation_id) == SPEND_STATES.SIGNED
    assert node.raw_posts == 1


def test_the_providers_reads_are_still_retried():
    """SCOPE PIN. Only the send is taken off the retry list: a read that times
    out is still asked again, as before."""
    from web3.providers.rpc.utils import check_if_retry_on_failure

    from runtime.blockchain.web3_manager import broadcast_safe_http_provider

    retry = broadcast_safe_http_provider(_RPC_URL).exception_retry_configuration
    assert retry is not None and retry.retries > 1
    assert not check_if_retry_on_failure("eth_sendRawTransaction", retry.method_allowlist)
    for read in ("eth_getTransactionReceipt", "eth_getTransactionCount", "eth_call",
                 "eth_getBalance", "eth_chainId"):
        assert check_if_retry_on_failure(read, retry.method_allowlist), read


def test_the_providers_text_counts_the_attempts_a_read_gets(monkeypatch):
    """The provider's text said web3 retries a read "up to five times". Its loop
    makes that many attempts in all, the first included: four of them are
    re-sends. Measured with a read that never gets an answer, then held against
    the text."""
    import web3.providers.rpc.rpc as rpc_module

    from runtime.blockchain import web3_manager

    posts: list[str] = []

    def _post(self, _url, data=None, **_kwargs):
        posts.append(json.loads(data)["method"])
        raise requests.Timeout("no answer")

    monkeypatch.setattr(requests.Session, "post", _post)
    monkeypatch.setattr(rpc_module.time, "sleep", lambda _s: None)
    provider = web3_manager.broadcast_safe_http_provider(_RPC_URL)

    with pytest.raises(requests.Timeout):
        provider.make_request("eth_chainId", [])

    attempts = len(posts)
    assert posts == ["eth_chainId"] * attempts and attempts > 1
    number = {2: "two", 3: "three", 4: "four", 5: "five", 6: "six", 7: "seven"}[attempts]
    text = " ".join((web3_manager.broadcast_safe_http_provider.__doc__ or "").split())
    assert f"up to {number} attempts" in text, (
        f"a read gets {attempts} attempts in all; the text says: {text[:300]}")


def test_every_http_provider_in_the_platform_sends_a_raw_transaction_once():
    """THE CLASS. A provider built anywhere in the platform's own process with
    web3's default retry re-sends a raw transaction whose reply was lost, and
    whoever reads the answer reads the re-send's. Every one is built by
    `broadcast_safe_http_provider`; this finds them from the source, so a new
    one cannot quietly bring the default back.

    Outside the running platform and not changed: the operator's deploy tools
    (contracts/deploy.py, deployer.py, eas_deployer.py, neosafe_verifier.py,
    scripts/verify_platform.py) and demo.py keep web3's default retry. None of
    them holds a sponsorship ledger or an attestation queue; a lost reply
    there can make a deploy that landed report an error."""
    import pathlib
    import re

    root = pathlib.Path(__file__).resolve().parent.parent
    helper = root / "runtime/blockchain/web3_manager.py"
    offenders = []
    for base in ("runtime", "gateway"):
        for path in sorted((root / base).rglob("*.py")):
            text = path.read_text(encoding="utf-8")
            for m in re.finditer(r"\b(?:Async)?HTTPProvider\s*\(", text):
                if path == helper:
                    continue
                line = text.count("\n", 0, m.start()) + 1
                offenders.append(f"{path.relative_to(root)}:{line}")
    assert offenders == [], (
        "HTTP providers built outside broadcast_safe_http_provider: " + ", ".join(offenders))


# ── a path that broadcasts on its own ───────────────────────────────────────
#
# The attestation service's queued writes are signed in its batch, through the
# EAS client, and broadcast there, not through the shared manager's send. A
# refusal there was never read: the row stayed SIGNED, the batch queued the
# write again and signed it on every flush, and each signature held budget of
# its own until the window passed.

_ADDR = "0x" + "11" * 20
_IDENTITY = "0x" + "ab" * 20


class _AttestingEth(_Eth):
    """The EAS contract as the batch builds against it: the transaction it
    builds carries the nonce, gas and chain the client asks for."""

    def contract(self, address, abi):
        class _Built:
            def build_transaction(self, fields):
                return {"to": _ADDR, "data": b"", "value": 0, "gas": fields["gas"],
                        "gasPrice": fields["gasPrice"], "nonce": fields["nonce"],
                        "chainId": fields["chainId"]}

        class _Functions:
            def attest(self, _request):
                return _Built()

        class _Contract:
            functions = _Functions()

        return _Contract()


async def test_a_queued_attestation_the_node_refused_is_given_back_once_its_nonce_is_taken(
        tmp_path, monkeypatch):
    """DEFECT-PROVER, through the attestation service, its batch processor and
    the EAS client. The node refuses the write; the batch signs it again on the
    next two flushes; then a transaction from the platform account takes the
    nonce and is mined. Every signature of the write is given back."""
    import runtime.blockchain.price_feed as price_feed
    from runtime.blockchain.eas_client import EASClient
    from runtime.blockchain.services.attestation.service import AttestationService

    async def _quote(self, **_kwargs):
        return {"price": 3000.0}

    account = Account.create()
    eth = _AttestingEth([_rpc_error(_INSUFFICIENT)] * 3, receipt={"status": 1, "blockNumber": 4})
    monkeypatch.setattr(price_feed.PriceFeed, "eth_usd", _quote)
    monkeypatch.setattr(EASClient, "_is_configured", lambda self: True)
    monkeypatch.setattr(EASClient, "_validate_config", lambda self: None)
    monkeypatch.setattr(EASClient, "web3", property(lambda self: _W3(eth)))
    monkeypatch.setattr(Web3Manager, "_instance", None)
    config = {"blockchain": {"rpc_url": "", "paymaster_private_key": "0x" + account.key.hex().removeprefix("0x"),
                             "platform_wallet": account.address, "eas_contract": _ADDR,
                             "eas_schema": "0x" + "33" * 32, "chain_id": 84532},
              "paymaster": {"policy": {"daily_cap_usd": 100.0,
                                       "allowed_actions": ["attestation.attest"]}},
              "database": {"path": str(tmp_path / "the-matrix.db")}}
    service = AttestationService(config, batch_size=1)

    await service.attest_for_caller("primary", {"action": "x"}, _ADDR,
                                    caller_identity=_IDENTITY)
    await service._batch_processor.flush()
    await service._batch_processor.flush()
    policy = SponsorshipPolicy.from_config(config)
    per_write = 300000 * 1_000_000_000 / 1e18 * 3000.0
    assert policy.spent_today(_IDENTITY) == pytest.approx(3 * per_write), (
        "re-derive this test: the batch did not sign the refused write three times")

    taker = MeteredSigner(account, policy, "attestation.attest", _IDENTITY, 3000.0)
    mined = taker.sign_transaction({**_TX, "chainId": 84532, "value": 1, "gas": 300000})
    await wait_for_receipt_on(_W3(eth), mined.hash, timeout=2)

    assert policy.spent_today(_IDENTITY) == pytest.approx(per_write), (
        "the refused write's signatures still hold budget after another "
        "transaction took their nonce and was mined")
