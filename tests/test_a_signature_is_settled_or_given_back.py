"""A sponsored signature's ledger row says what became of it.

attest-money F17. `SponsorshipPolicy.settle` and `.abandon` existed, and
`MeteredSigner.last_reservation_id` was added so a caller could reach them —
and nothing in production called any of the three. Every metered signature
stayed SIGNED until the 24h sweep: the ledger never recorded SPENT, and a
signature the node refused outright never gave its budget back. Live, because
`Web3Manager.send_transaction` — the path the services sign through — signs
through the metered platform signer.

The row is now closed by the two places that learn a signature's fate, keyed
by the transaction hash the signed bytes already determine:

    a receipt arrives (mined, success or revert)  -> SPENT     wait_for_receipt_on
    the node answers the send with a listed
    refusal, and then holds no copy of the hash    -> released  Web3Manager.send_transaction

and it stays SIGNED — holding budget — for everything that does not establish
either: a transport fault on the send, any answer off the refusal list (a
JSON-RPC timeout, a relayed internal error), a node saying it already has the
bytes or that the nonce is used (both are what a node says once this
transaction is pending or mined), a node that holds the hash or cannot be
asked, a receipt wait that runs out. The refusal read is the answer to the
only delivery: the provider does not re-send a raw transaction.

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
    def __init__(self, *, send_raises=None, receipt=None, receipt_raises=None,
                 lookup=None, lookup_raises=None):
        self._send_raises = send_raises
        self._receipt = receipt
        self._receipt_raises = receipt_raises
        # What the node says when asked for the transaction by its hash: by
        # default that it holds none (web3 raises TransactionNotFound for a
        # null answer).
        self._lookup = lookup
        self._lookup_raises = lookup_raises
        self.lookups: list = []
        self.gas_price = 1_000_000_000

    def send_raw_transaction(self, raw):
        if self._send_raises is not None:
            raise self._send_raises
        from eth_utils import keccak
        return keccak(raw)

    def get_transaction(self, tx_hash):
        self.lookups.append(tx_hash)
        if self._lookup_raises is not None:
            raise self._lookup_raises
        if self._lookup is None:
            from web3.exceptions import TransactionNotFound
            raise TransactionNotFound(f"Transaction with hash: {tx_hash!r} not found.")
        return self._lookup

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
    """DEFECT-PROVER, the other direction, through the real send path. The
    refusal is one no mined or pending copy of the transaction could produce:
    the sender cannot pay for it. ("nonce too low", which this used first, is
    what a node says once the transaction IS mined; see below.)"""
    from web3.exceptions import Web3RPCError

    policy = _policy(tmp_path)
    signer = _signer(policy)
    mgr = _manager(_W3(_Eth(send_raises=Web3RPCError(
        "insufficient funds for gas * price + value"))), signer)

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
    (ValueError({"code": -32000, "message": "insufficient funds for gas * price + value"}), True),
    (ValueError({"code": -32000, "message": "nonce too low"}), False),
    (ValueError({"code": -32000, "message": "already known"}), False),
    (ValueError("not an rpc answer"), False),
    (OSError("broken pipe"), False),
])
def test_what_counts_as_the_node_saying_no(exc, expected):
    assert node_refused(exc) is expected


# ── a refusal is only a refusal of the bytes the node was sent once ─────────
#
# The release above over-granted. Two ways, one outcome: a row DELETED, and
# the day's budget handed back, for a transaction the platform paid gas on.
#
#   1. The shared manager's HTTP provider carried web3's default retry, and
#      that retry list includes eth_sendRawTransaction. A first POST that
#      delivered the bytes and lost its reply was re-sent; by then the
#      transaction was mined, the node answered the SECOND delivery with
#      "nonce too low", and that answer was read as the node refusing the
#      FIRST.
#   2. "nonce too low" was counted as a refusal at all. It says the nonce is
#      already used, which is exactly what a node says once THIS transaction
#      is mined. So is "AlreadyKnown", the spelling without a space, for one
#      still in the mempool.
#
# Both are closed: the provider sends a raw transaction once, and an answer
# that fits the transaction being in a mempool or on chain is not a refusal.

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
    retry and web3's error decoding all run for real; only the wire is fake."""

    def __init__(self, raw_answers, *, lookup="none"):
        self.raw_answers = list(raw_answers)
        self.raw_posts = 0
        self.methods: list[str] = []
        # The answer to eth_getTransactionByHash: "none" (a null result: the
        # node holds no such transaction), "holds" (the transaction, pending),
        # or a JSON-RPC error object.
        self.lookup = lookup
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
            asked = request["params"][0]
            if isinstance(self.lookup, dict):
                return _rpc_reply(data, error=self.lookup)
            if self.lookup == "holds" and asked.lower() in self.sent_hashes:
                return _rpc_reply(data, result={"hash": asked, "blockNumber": None,
                                                "nonce": "0x0"})
            return _rpc_reply(data, result=None)
        raise AssertionError(f"unexpected RPC {method}")


def _live_manager(monkeypatch, node, signer) -> Web3Manager:
    """The real Web3Manager, built by its own constructor, so its provider is
    the one production gets."""
    monkeypatch.setattr(requests.Session, "post", node.post)
    mgr = Web3Manager({"blockchain": {"rpc_url": _RPC_URL, "chain_id": 8453}})
    assert mgr.available, "the test node did not answer the manager's connect check"

    async def _signer_for(_action=None):
        return signer

    mgr.signer = _signer_for
    return mgr


async def test_a_lost_reply_and_a_resend_that_hears_nonce_too_low_keep_the_budget(
        tmp_path, monkeypatch):
    """DEFECT-PROVER for the over-grant. The first POST delivers the bytes and
    its reply is lost; the node's next answer about the same bytes is "nonce
    too low", because the transaction was mined in between. The platform paid
    that gas, so its budget stays held."""
    policy = _policy(tmp_path)
    signer = _signer(policy)
    node = _Node([requests.Timeout("reply lost after delivery"),
                  {"code": -32000, "message": "nonce too low"}])
    mgr = _live_manager(monkeypatch, node, signer)

    with pytest.raises(Exception):
        await mgr.send_transaction(dict(_TX))

    assert policy.state_of(signer.last_reservation_id) == SPEND_STATES.SIGNED, (
        "a transaction whose first delivery may have been mined gave its "
        "sponsorship budget back"
    )
    assert policy.spent_today("0xA") > 0
    assert node.raw_posts == 1, (
        f"the signed bytes were POSTed {node.raw_posts} times; an answer to a "
        f"re-send is not an answer about the first delivery"
    )


async def test_the_managers_provider_sends_a_raw_transaction_once(tmp_path, monkeypatch):
    policy = _policy(tmp_path)
    signer = _signer(policy)
    node = _Node([requests.Timeout("t1"), requests.Timeout("t2"), requests.Timeout("t3")])
    mgr = _live_manager(monkeypatch, node, signer)

    with pytest.raises(requests.Timeout):
        await mgr.send_transaction(dict(_TX))

    assert node.raw_posts == 1
    assert policy.state_of(signer.last_reservation_id) == SPEND_STATES.SIGNED


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


@pytest.mark.parametrize("message", [
    "nonce too low",
    "Nonce too low",
    "NonceTooLow",
    "NONCE_TOO_LOW",
    "OldNonce",
    "Transaction nonce is too low. Try incrementing the nonce.",
    "already known",
    "AlreadyKnown",
    "TRANSACTION_ALREADY_KNOWN",
    "known transaction: 0xabc",
])
def test_an_answer_that_fits_a_mined_or_pending_transaction_is_not_a_refusal(message):
    from web3.exceptions import Web3RPCError

    assert node_refused(Web3RPCError(str({"code": -32000, "message": message}))) is False
    assert node_refused(ValueError({"code": -32000, "message": message})) is False


@pytest.mark.parametrize("message", [
    "insufficient funds for gas * price + value",
    "intrinsic gas too low",
    "max fee per gas less than block base fee",
    "invalid sender",
])
def test_a_refusal_of_the_bytes_themselves_is_still_a_refusal(message):
    """SCOPE PIN: the release still happens for an answer no mined or pending
    copy of the transaction could produce."""
    from web3.exceptions import Web3RPCError

    assert node_refused(Web3RPCError(str({"code": -32000, "message": message}))) is True


async def test_nonce_too_low_through_the_send_keeps_the_budget(tmp_path):
    from web3.exceptions import Web3RPCError

    policy = _policy(tmp_path)
    signer = _signer(policy)
    mgr = _manager(_W3(_Eth(send_raises=Web3RPCError("nonce too low"))), signer)

    with pytest.raises(Web3RPCError):
        await mgr.send_transaction(dict(_TX))

    assert policy.state_of(signer.last_reservation_id) == SPEND_STATES.SIGNED


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


# ── a refusal is one the node names, about a hash it does not hold ──────────
#
# The rule above was still a deny-list: any JSON-RPC error whose text named
# none of the pending or mined answers counted as the node refusing the bytes,
# and released the row. A JSON-RPC error is not always a refusal:
#
#   * geth answers -32002 "request timed out" while the handler that received
#     the bytes keeps running, so the transaction can still enter the pool;
#     web3 itself raises that answer as `RequestTimedOut`;
#   * a Base replica (op-geth) forwards the transaction to the sequencer and
#     hands back the forwarding error as it is, and a forwarding timeout can
#     come after the sequencer has the bytes;
#   * a proxy answers -32603 "Internal error", "context deadline exceeded" or
#     "gateway timeout" having forwarded them.
#
# Each one handed back a signature's budget for gas the platform can still
# pay. The budget now comes back only for an answer on the list of refusals a
# node makes when it turns a transaction away at admission
# (`sponsorship._REFUSED_AT_ADMISSION`), and only when the node, asked right
# after, holds no transaction under that hash. Anything else keeps the row
# SIGNED: it holds budget, and is never released early.

_INSUFFICIENT = {"code": -32000, "message": "insufficient funds for gas * price + value"}


@pytest.mark.parametrize("error", [
    {"code": -32002, "message": "request timed out"},
    {"code": -32603, "message": "Internal error"},
    {"code": -32000, "message": "context deadline exceeded"},
    {"code": -32000, "message": "gateway timeout"},
    {"code": -32000, "message": "upstream request timeout"},
    {"code": -32000, "message": "an answer no list in this repository names"},
], ids=lambda e: e["message"])
async def test_a_json_rpc_error_that_names_no_refusal_keeps_the_budget(
        tmp_path, monkeypatch, error):
    """DEFECT-PROVER. Through the real manager, provider and web3 error
    decoding: each of these released the row and zeroed the day's spend."""
    policy = _policy(tmp_path)
    signer = _signer(policy)
    node = _Node([error])
    mgr = _live_manager(monkeypatch, node, signer)

    with pytest.raises(Exception):
        await mgr.send_transaction(dict(_TX))

    assert policy.state_of(signer.last_reservation_id) == SPEND_STATES.SIGNED, (
        f"{error['message']!r} is not the node refusing the bytes, and the "
        f"signature's budget was handed back"
    )
    assert policy.spent_today("0xA") > 0
    assert node.raw_posts == 1


def test_web3s_own_timeout_answer_is_not_a_refusal():
    from web3.exceptions import RequestTimedOut, Web3RPCError

    timed_out = {"code": -32002, "message": "request timed out"}
    assert node_refused(RequestTimedOut(repr(timed_out), rpc_response={"error": timed_out})) is False
    assert node_refused(Web3RPCError(repr({"code": -32603, "message": "Internal error"}))) is False
    assert node_refused(ValueError({"code": -32000, "message": "context deadline exceeded"})) is False


# The answers geth and the clients that share its errors (op-geth, reth,
# erigon, anvil) give when they turn a transaction away before it enters the
# pool. None is taken on its word alone: the budget comes back only when the
# node, asked right after, also holds no transaction under the hash (below).
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

# Answers that are not a refusal of the bytes, or that nothing establishes is
# one: timeouts in every spelling, proxy and transport failures relayed as
# JSON-RPC, rate limits, and text no client is known to send.
_NOT_REFUSALS = [
    "request timed out",
    "Internal error",
    "internal server error",
    "context deadline exceeded",
    "context canceled",
    "gateway timeout",
    "upstream request timeout",
    "Bad Gateway",
    "service unavailable",
    "connection reset by peer",
    "EOF",
    "failed to forward tx to sequencer",
    "tx already in mempool",
    "rate limit exceeded",
    "Too Many Requests",
    "execution timeout",
    "header not found",
    "something went wrong",
    "",
]


@pytest.mark.parametrize("message", _LISTED_REFUSALS)
def test_a_listed_refusal_is_a_refusal(message):
    from web3.exceptions import Web3RPCError

    error = {"code": -32000, "message": message}
    assert node_refused(Web3RPCError(repr(error), rpc_response={"error": error})) is True
    assert node_refused(Web3RPCError(repr(error))) is True
    assert node_refused(ValueError(error)) is True


@pytest.mark.parametrize("message", _NOT_REFUSALS)
def test_an_answer_that_names_no_listed_refusal_is_not_one(message):
    """THE CLASS. Being a JSON-RPC error is not enough: the answer has to be
    one of the refusals a node gives at admission."""
    from web3.exceptions import Web3RPCError

    for code in (-32000, -32002, -32603, -32005):
        error = {"code": code, "message": message}
        assert node_refused(Web3RPCError(repr(error), rpc_response={"error": error})) is False, error
        assert node_refused(ValueError(error)) is False, error


def test_a_listed_word_in_the_data_field_is_not_the_nodes_answer():
    """The refusal is read from the answer's message. A timeout whose `data`
    happens to carry a listed word was still a timeout."""
    from web3.exceptions import Web3RPCError

    error = {"code": -32002, "message": "request timed out",
             "data": "insufficient funds for gas * price + value"}
    assert node_refused(Web3RPCError(repr(error), rpc_response={"error": error})) is False


def test_a_node_without_the_send_method_did_not_take_the_bytes():
    from web3.exceptions import MethodUnavailable

    error = {"code": -32601, "message": "the method eth_sendRawTransaction does not exist/is not available"}
    assert node_refused(MethodUnavailable(repr(error), rpc_response={"error": error})) is True
    assert node_refused(ValueError(error)) is True


async def test_a_listed_refusal_about_a_hash_the_node_holds_keeps_the_budget(
        tmp_path, monkeypatch):
    """DEFECT-PROVER. The answer names a refusal, but the node, asked, holds a
    transaction under this very hash: a proxy that delivered the bytes to one
    backend and relayed another's answer, or a retry made somewhere between us
    and the node. A copy exists, so the gas may yet be paid."""
    policy = _policy(tmp_path)
    signer = _signer(policy)
    node = _Node([_INSUFFICIENT], lookup="holds")
    mgr = _live_manager(monkeypatch, node, signer)

    with pytest.raises(Exception):
        await mgr.send_transaction(dict(_TX))

    assert policy.state_of(signer.last_reservation_id) == SPEND_STATES.SIGNED
    assert policy.spent_today("0xA") > 0
    assert node.methods.count("eth_getTransactionByHash") >= 1


async def test_a_listed_refusal_the_node_cannot_be_asked_about_keeps_the_budget(
        tmp_path, monkeypatch):
    """The lookup must answer "no such transaction" for the budget to come
    back. A node that cannot say (still indexing) has not said it."""
    policy = _policy(tmp_path)
    signer = _signer(policy)
    node = _Node([_INSUFFICIENT],
                 lookup={"code": -32000, "message": "transaction indexing is in progress"})
    mgr = _live_manager(monkeypatch, node, signer)

    with pytest.raises(Exception):
        await mgr.send_transaction(dict(_TX))

    assert policy.state_of(signer.last_reservation_id) == SPEND_STATES.SIGNED
    assert policy.spent_today("0xA") > 0


@pytest.mark.parametrize("fault", [
    ConnectionError("reset by peer"),
    TimeoutError("read timed out"),
], ids=["connection", "timeout"])
async def test_a_listed_refusal_whose_lookup_fails_keeps_the_budget(tmp_path, fault):
    from web3.exceptions import Web3RPCError

    policy = _policy(tmp_path)
    signer = _signer(policy)
    eth = _Eth(send_raises=Web3RPCError(repr(_INSUFFICIENT)), lookup_raises=fault)
    mgr = _manager(_W3(eth), signer)

    with pytest.raises(Web3RPCError):
        await mgr.send_transaction(dict(_TX))

    assert eth.lookups, "the node was never asked for the transaction"
    assert policy.state_of(signer.last_reservation_id) == SPEND_STATES.SIGNED


async def test_a_listed_refusal_about_a_hash_the_node_does_not_hold_gives_the_budget_back(
        tmp_path, monkeypatch):
    """SCOPE PIN. The release still happens, through the real provider, when
    the node refused the bytes and holds no copy of them."""
    policy = _policy(tmp_path)
    signer = _signer(policy)
    node = _Node([_INSUFFICIENT])
    mgr = _live_manager(monkeypatch, node, signer)

    with pytest.raises(Exception):
        await mgr.send_transaction(dict(_TX))

    assert policy.state_of(signer.last_reservation_id) is None
    assert policy.spent_today("0xA") == pytest.approx(0.0)
    assert node.raw_posts == 1
    assert "eth_getTransactionByHash" in node.methods, (
        "the budget came back without the node being asked whether it holds the transaction"
    )
