"""A transaction that was sent is not a refusal because nobody saw its receipt.

THE DEFECT. Every blockchain capability the agent calls, and the two helpers the
services lean on (`eas_client.EASClient.attest`, `gas_sponsor.GasSponsor.
sponsor_transaction`), signed a transaction, sent it with
`w3.eth.send_raw_transaction`, and then called `w3.eth.wait_for_transaction_receipt`
inside the same `try`. When the wait ran out, web3 raised, and the `except`
answered the way it answers a bad address: "Stake failed: no receipt in time",
`{"ok": false}`, `{"status": "failed"}`. The transaction was out. It may be
mined. The answer dropped its hash, told the agent the stake did not happen, and
taught outcome learning that it failed — and an agent told a transfer failed
sends it again.

`tests/test_a_broadcast_is_not_a_settlement.py` holds the same line for the
services the dispatcher runs. This file holds it for everything else under
`runtime/blockchain/`: the census below finds every function that sends, and the
driver runs each one against a node that took the bytes and then answers three
ways — no receipt in time, a confirmed receipt, a reverted one.

THE THREE ANSWERS, in `outcome_truth`'s words:

    no receipt in time  -> UNKNOWN, with the hash   (it was FAILURE, without it)
    receipt status 1    -> SUCCESS                   (unchanged)
    receipt status 0    -> FAILURE                   (unchanged: a revert is known)

WHAT THIS DOES NOT CLAIM. The wait is still a wait; a node that never mines the
transaction leaves it unknown for good, and nothing here re-checks it later.
"""

from __future__ import annotations

import ast
import asyncio
import json
import pathlib
import sys
import time
import types

import pytest

from runtime.protocols.outcome_truth import FAILURE, SUCCESS, UNKNOWN, report_of

_REPO = pathlib.Path(__file__).resolve().parents[1]
_BLOCKCHAIN = _REPO / "runtime" / "blockchain"

_SEND_PRIMITIVES = frozenset({"send_transaction", "send_raw_transaction"})
_RAW_RECEIPT_WAITS = frozenset({"wait_for_receipt", "wait_for_transaction_receipt"})
#: The waits that answer a wait which ran out as unconfirmed, not failed.
_SHARED_WAITS = frozenset({"settle_transaction", "receipt_within", "_receipt"})

ADDR = "0x" + "1" * 40
HASH = bytes.fromhex("ab" * 32)


def _names_used(node: ast.AST) -> set[str]:
    names: set[str] = set()
    for sub in ast.walk(node):
        if isinstance(sub, ast.Attribute):
            names.add(sub.attr)
        elif isinstance(sub, ast.Name):
            names.add(sub.id)
    return names


def _called(node: ast.AST) -> set[str]:
    names: set[str] = set()
    for sub in ast.walk(node):
        if isinstance(sub, ast.Call):
            func = sub.func
            names.add(func.attr if isinstance(func, ast.Attribute) else getattr(func, "id", ""))
    return names


def _functions_outside_services():
    """Every function under runtime/blockchain/ outside services/, however deeply
    nested, with the class that holds it ("" at module level)."""
    for path in sorted(_BLOCKCHAIN.rglob("*.py")):
        if "services" in path.relative_to(_BLOCKCHAIN).parts:
            continue
        tree = ast.parse(path.read_text())
        owner_of: dict[ast.AST, str] = {}
        for parent in ast.walk(tree):
            for child in ast.iter_child_nodes(parent):
                owner_of[child] = (parent.name if isinstance(parent, ast.ClassDef)
                                   else owner_of.get(parent, ""))
        for node in ast.walk(tree):
            if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
                yield str(path.relative_to(_BLOCKCHAIN)), owner_of.get(node, ""), node


# ── the census ───────────────────────────────────────────────────────────

#: Where a raw receipt wait may appear under runtime/blockchain/ outside
#: services/: the shared wait itself and the helper that turns its three
#: outcomes into three answers. Everything else waits through them.
_RAW_WAIT_HOMES = frozenset({
    ("web3_manager.py", "", "wait_for_receipt_on"),
    ("web3_manager.py", "", "settle_transaction"),
})


def test_a_raw_receipt_wait_lives_only_in_the_shared_wait():
    """THE LOAD-BEARING CENSUS. Fails on the tree before this fix, naming 35
    functions: the 34 senders that waited inline, and
    `Web3Manager.wait_for_receipt`, which held the loop that is now
    `wait_for_receipt_on` and now calls it."""
    inline = {
        (path, owner, node.name)
        for path, owner, node in _functions_outside_services()
        if _names_used(node) & _RAW_RECEIPT_WAITS
    } - _RAW_WAIT_HOMES
    assert inline == set(), (
        "a function under runtime/blockchain/ waits for a receipt itself, so what "
        "a wait that runs out is reported as is up to its own except clause: "
        f"{sorted(inline)}")


def _senders() -> set[tuple[str, str, str]]:
    return {
        (path, owner, node.name)
        for path, owner, node in _functions_outside_services()
        if _called(node) & _SEND_PRIMITIVES
    }


def test_every_sender_waits_through_the_shared_wait():
    """Every function outside services/ that sends a transaction learns what
    happened through a wait that knows a wait which ran out is not a refusal —
    except the send primitive itself, which waits for nothing and claims
    nothing but the hash."""
    primitive = {("web3_manager.py", "Web3Manager", "send_transaction")}
    unaccounted = {
        (path, owner, node.name)
        for path, owner, node in _functions_outside_services()
        if _called(node) & _SEND_PRIMITIVES
        and (path, owner, node.name) not in primitive
        and not (_names_used(node) & _SHARED_WAITS)
    }
    assert unaccounted == set(), f"a sender waits for nothing or waits inline: {sorted(unaccounted)}"


# ── the driver ───────────────────────────────────────────────────────────


class _Receipt(dict):
    """A receipt the way web3 hands one back: by key and by attribute."""

    def __getattr__(self, name):
        try:
            return self[name]
        except KeyError as exc:  # pragma: no cover - test double
            raise AttributeError(name) from exc


def _receipt(status: int) -> _Receipt:
    return _Receipt(status=status, blockNumber=7, gasUsed=21000,
                    contractAddress="0x" + "9" * 40)


class _Call:
    def build_transaction(self, tx=None):
        return dict(tx or {})

    def call(self, *_a, **_k):
        return 18


class _Functions:
    def __getattr__(self, _name):
        return lambda *_a, **_k: _Call()

    def __getitem__(self, _name):
        return lambda *_a, **_k: _Call()


class _Contract:
    functions = _Functions()
    address = ADDR

    def constructor(self, *_a, **_k):
        return _Call()


class _Node:
    """A node that accepts the bytes. What the receipt wait answers is set by
    `outcome`: a receipt status, or None for a wait that runs out."""

    def __init__(self, outcome):
        self.sent = 0
        node = self

        class _Eth:
            gas_price = 1

            def contract(self, *_a, **_k):
                return _Contract()

            def get_transaction_count(self, *_a):
                return 0

            def estimate_gas(self, _tx):
                return 21000

            def send_raw_transaction(self, _raw):
                node.sent += 1
                return HASH

            def wait_for_transaction_receipt(self, tx_hash, timeout=120, **_k):
                # What the code before the fix called directly, answering the
                # same way, so a control run against it fails on what it did
                # with the answer.
                if outcome is None:
                    raise TimeoutError(f"no receipt for {tx_hash!r} within {timeout}s")
                return _receipt(outcome)

        self.eth = _Eth()

    @staticmethod
    def to_wei(value, _unit="ether"):
        return int(float(value) * 10**18)

    @staticmethod
    def from_wei(value, _unit="ether"):
        return value / 10**18


class _Signed:
    raw_transaction = b"\x01"
    rawTransaction = b"\x01"


class _Account:
    address = ADDR

    def sign_transaction(self, _tx):
        return _Signed()


_CONFIG = {"blockchain": {
    "rpc_url": "http://127.0.0.1:1", "paymaster_private_key": "0x" + "1" * 64,
    "platform_wallet": ADDR, "eas_contract": ADDR, "eas_schema": "0x" + "cd" * 32,
    "eas_schema_registry": ADDR, "chain_id": 84532, "network": "base-sepolia",
}}

_GOVERNOR = {"governor_address": ADDR, "targets": [ADDR], "values": ["0"],
             "calldatas": ["0x"], "description": "d", "proposal_id": "1", "support": 1}
_POOL = {"token": "WETH", "amount": "1", "pool_address": ADDR}
_TIMELOCK = {"timelock_address": ADDR, "target": ADDR, "value": "0", "delay": 60,
             "role": "0x" + "ab" * 32, "account": ADDR}

#: Every sender outside services/, and what to call it with. The census test
#: below holds this table to the tree, so a sender added later without an entry
#: fails by name rather than escaping the driver.
_DRIVEN = {
    ("daos.py", "DAOs", "_create_proposal"): dict(_GOVERNOR),
    ("daos.py", "DAOs", "_vote"): dict(_GOVERNOR),
    ("daos.py", "DAOs", "_execute_proposal"): dict(_GOVERNOR),
    ("defi.py", "DeFi", "_supply"): dict(_POOL),
    ("defi.py", "DeFi", "_borrow"): dict(_POOL),
    ("defi.py", "DeFi", "_withdraw"): dict(_POOL),
    ("defi.py", "DeFi", "_repay"): dict(_POOL),
    ("eas_client.py", "EASClient", "attest"): {"action": "a", "agent": "neo", "details": {}},
    ("eas_manager.py", "EASManager", "_create_schema"): {"schema": "string action"},
    ("eas_manager.py", "EASManager", "_revoke"): {"attestation_uid": "0x" + "ef" * 32},
    ("gaming.py", "Gaming", "_mint_item"): {"contract_address": ADDR, "player_address": ADDR},
    ("gaming.py", "Gaming", "_transfer_item"): {"contract_address": ADDR, "to": ADDR},
    ("gas_sponsor.py", "GasSponsor", "sponsor_transaction"): {"tx": {"to": ADDR}},
    ("governance.py", "Governance", "_schedule"): dict(_TIMELOCK),
    ("governance.py", "Governance", "_execute_op"): dict(_TIMELOCK),
    ("governance.py", "Governance", "_grant_role"): dict(_TIMELOCK),
    ("governance.py", "Governance", "_revoke_role"): dict(_TIMELOCK),
    ("ip_royalties.py", "IPRoyalties", "_distribute"): {
        "royalty_recipients": [{"address": ADDR, "share_bps": 10000}], "amount": "1"},
    ("nfts.py", "NFTs", "_mint"): {"contract_address": ADDR, "to": ADDR, "token_uri": "ipfs://x"},
    ("nfts.py", "NFTs", "_transfer"): {"contract_address": ADDR, "to": ADDR, "token_id": 1},
    ("payments.py", "Payments", "_send_eth"): {"to": ADDR, "amount": "1"},
    ("payments.py", "Payments", "_send_token"): {"to": ADDR, "amount": "1", "token_address": ADDR},
    ("securities.py", "Securities", "_transfer"): {"contract_address": ADDR, "to": ADDR, "amount": "1"},
    ("securities.py", "Securities", "_freeze"): {"contract_address": ADDR, "investor_address": ADDR},
    ("smart_contracts.py", "SmartContracts", "_send"): {
        "contract_address": ADDR, "abi": [], "function_name": "set", "args": []},
    ("smart_contracts.py", "SmartContracts", "_deploy_disabled_implementation"): {
        "source_code": "contract C {}"},
    ("stablecoins.py", "Stablecoins", "_transfer"): {"token": "USDC", "amount": "1", "to": ADDR},
    ("stablecoins.py", "Stablecoins", "_approve"): {"token": "USDC", "amount": "1", "spender": ADDR},
    ("staking.py", "Staking", "_stake"): {"staking_contract": ADDR, "amount": "1"},
    ("staking.py", "Staking", "_unstake"): {"staking_contract": ADDR, "amount": "1"},
    ("staking.py", "Staking", "_claim_rewards"): {"staking_contract": ADDR},
    ("tokenization.py", "Tokenization", "_transfer"): {"contract_address": ADDR, "to": ADDR, "amount": "1"},
    ("tokenization.py", "Tokenization", "_approve"): {"contract_address": ADDR, "spender": ADDR, "amount": "1"},
    ("tokenization.py", "Tokenization", "_mint"): {"contract_address": ADDR, "to": ADDR, "amount": "1"},
}


def test_the_driver_drives_every_sender():
    """The table is the tree's senders, no more and no fewer."""
    primitive = {("web3_manager.py", "Web3Manager", "send_transaction")}
    assert _senders() - primitive == set(_DRIVEN), (
        f"missing from the driver: {sorted(_senders() - primitive - set(_DRIVEN))}; "
        f"no longer in the tree: {sorted(set(_DRIVEN) - _senders())}")


class _Manager:
    available = True

    def __init__(self, node):
        self.w3 = node

    def get_account(self):
        return _Account()


def _build(key, node, monkeypatch):
    import importlib

    import runtime.blockchain.sponsorship as sponsorship
    from runtime.blockchain import web3_manager

    path, owner, _name = key
    module = importlib.import_module("runtime.blockchain." + path[:-3])
    monkeypatch.setattr(sponsorship, "unmetered_platform_signer", lambda *_a: _Account())
    monkeypatch.setattr(web3_manager.Web3Manager, "get_shared",
                        classmethod(lambda cls, _config: _Manager(node)))

    async def _wait(_w3, tx_hash, timeout=120):
        return node.eth.wait_for_transaction_receipt(tx_hash, timeout=timeout)

    monkeypatch.setattr(web3_manager, "wait_for_receipt_on", _wait, raising=False)

    fake_solcx = types.ModuleType("solcx")
    fake_solcx.install_solc = lambda *_a, **_k: None
    fake_solcx.compile_source = lambda *_a, **_k: {"<stdin>:C": {"abi": [], "bin": "6000"}}
    monkeypatch.setitem(sys.modules, "solcx", fake_solcx)
    if path == "smart_contracts.py":
        monkeypatch.setattr(module.ContractAuditor, "should_block", lambda *_a: False)

    obj = getattr(module, owner)(_CONFIG)
    if hasattr(obj, "_manager"):
        obj._manager = _Manager(node)
    else:
        obj._web3 = node

    async def _signer(_action):
        return _Account()

    obj._platform_signer = _signer
    return obj


async def _drive(key, outcome, monkeypatch):
    node = _Node(outcome)
    obj = _build(key, node, monkeypatch)
    method = getattr(obj, key[2])
    params = _DRIVEN[key]
    if key[2] in ("attest", "sponsor_transaction"):
        out = await method(**params)
    else:
        out = await method(dict(params))
    parsed = json.loads(out) if isinstance(out, str) else out
    return node, parsed


def _items(parsed):
    """`ip_royalties._distribute` reports one transaction per recipient."""
    if isinstance(parsed, dict) and isinstance(parsed.get("distributions"), list):
        return parsed["distributions"]
    return [parsed]


_KEYS = sorted(_DRIVEN)


@pytest.mark.parametrize("key", _KEYS, ids=["/".join(k[::2]) for k in _KEYS])
async def test_a_sent_transaction_with_no_receipt_is_unknown_and_keeps_its_hash(key, monkeypatch):
    """DEFECT-PROVER, one per sender. Before: a refusal with no hash."""
    node, parsed = await _drive(key, None, monkeypatch)
    assert node.sent == 1, f"premise changed — {key} never sent: {parsed}"
    for item in _items(parsed):
        assert report_of(item) == UNKNOWN, (
            f"{key}: a sent transaction with no receipt was reported as "
            f"{report_of(item)}: {item}")
        assert item.get("broadcast") is True and item.get("settled") is False, item
        assert item.get("tx_hash") == HASH.hex(), f"{key}: the hash was lost: {item}"


@pytest.mark.parametrize("key", _KEYS, ids=["/".join(k[::2]) for k in _KEYS])
async def test_a_confirmed_transaction_is_still_a_success(key, monkeypatch):
    """SCOPE PIN: the wait must not stop a confirmed transaction being one."""
    node, parsed = await _drive(key, 1, monkeypatch)
    assert node.sent == 1, parsed
    for item in _items(parsed):
        assert report_of(item) == SUCCESS, f"{key}: {item}"


@pytest.mark.parametrize("key", _KEYS, ids=["/".join(k[::2]) for k in _KEYS])
async def test_a_reverted_transaction_is_still_a_failure(key, monkeypatch):
    """SCOPE PIN: a revert is established, so it stays a failure."""
    node, parsed = await _drive(key, 0, monkeypatch)
    assert node.sent == 1, parsed
    for item in _items(parsed):
        assert report_of(item) == FAILURE, f"{key}: {item}"


# ── the shared wait itself ───────────────────────────────────────────────


async def test_receipt_within_answers_none_for_a_wait_that_runs_out():
    from runtime.blockchain.web3_manager import receipt_within

    class _Stalled:
        class eth:  # noqa: N801 - web3's attribute name
            @staticmethod
            def wait_for_transaction_receipt(_tx_hash, timeout=120):
                time.sleep(timeout)  # what web3 does: poll until its timeout
                raise TimeoutError("still nothing")

    assert await receipt_within(_Stalled(), HASH, 1, what="probe") is None


async def test_receipt_within_hands_back_the_receipt_it_got():
    from runtime.blockchain.web3_manager import receipt_within

    class _Mined:
        class eth:  # noqa: N801 - web3's attribute name
            @staticmethod
            def wait_for_transaction_receipt(_tx_hash, timeout=120):
                return _receipt(1)

    assert (await receipt_within(_Mined(), HASH, 1))["status"] == 1


async def test_receipt_within_lets_a_cancellation_through():
    from runtime.blockchain import web3_manager

    async def _cancelled(*_a, **_k):
        raise asyncio.CancelledError()

    original = web3_manager.wait_for_receipt_on
    web3_manager.wait_for_receipt_on = _cancelled
    try:
        with pytest.raises(asyncio.CancelledError):
            await web3_manager.receipt_within(object(), HASH, 1)
    finally:
        web3_manager.wait_for_receipt_on = original


# ── the batch that re-sent what it could not confirm ─────────────────────


async def test_a_batched_attestation_that_was_sent_is_not_sent_again(monkeypatch, caplog):
    """DEFECT-PROVER. The batch processor re-queues every attestation that did
    not land, and a wait that ran out used to come back "failed", so the next
    flush signed and sent the same attestation again — two on-chain claims
    where one was asked for, if the first was mined. A sent attestation with no
    receipt is recorded with its hash and left alone."""
    import logging

    from runtime.blockchain.services.attestation import batch_processor as bp

    key = ("eas_client.py", "EASClient", "attest")
    node = _Node(None)
    client = _build(key, node, monkeypatch)
    monkeypatch.setattr(bp, "_eas_client_for", lambda _cfg: client, raising=False)
    proc = bp.BatchProcessor({}, batch_size=1000, flush_interval_seconds=3600)
    await proc.add({"schema_uid": "0x1", "data": {"action": "a"}, "recipient": ADDR})

    with caplog.at_level(logging.WARNING):
        results = await proc.flush()
        await proc.flush()

    assert node.sent == 1, f"the attestation was sent {node.sent} times"
    assert proc.pending_count == 0, "a sent attestation was queued to be sent again"
    assert [report_of(r) for r in results] == [UNKNOWN], results
    assert any(HASH.hex() in r.getMessage() for r in caplog.records), (
        "the batch kept no record of the hash it could not confirm")


async def test_a_batched_attestation_that_was_never_sent_is_still_retried(monkeypatch):
    """SCOPE PIN: an attestation that did not go out is still owed."""
    from runtime.blockchain.services.attestation import batch_processor as bp

    class _Unconfigured:
        async def attest(self, **_kwargs):
            return {"status": "skipped", "reason": "blockchain not configured"}

    monkeypatch.setattr(bp, "_eas_client_for", lambda _cfg: _Unconfigured(), raising=False)
    proc = bp.BatchProcessor({}, batch_size=1000, flush_interval_seconds=3600)
    await proc.add({"schema_uid": "0x1", "data": {"action": "a"}, "recipient": ADDR})
    await proc.flush()
    assert proc.pending_count == 1
