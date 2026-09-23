"""A node accepting the bytes is not the chain agreeing they were valid.

CLUSTER attest-money, the axis the cluster's own fixes established and then did
not finish applying.

`neosafe.route_revenue` returned `"routed"` the moment `send_transaction`
returned, and `routed` reads as a real outcome, so the dispatcher EAS-attested
it and the public feed announced platform revenue that may have reverted. The
fix there was to wait for the receipt and attest from THAT. `web3_manager`
carries the shared form of it, `settle_transaction`, and says in its own header
what the two helpers beside it are for:

    Both emit the disclosure flags `settled` / `value_moved`, which are the
    highest-priority clause in `_outcome_is_real` and in `report_of`. A service
    that omits them gets graded on its status string alone.

TWENTY-SIX REACHABLE METHODS OMIT THEM. They return `{"status": "submitted",
"tx_hash": ...}` (or `claim_submitted`) with no `settled` key and no receipt
wait, across ten service directories, and every one is reachable as a
state-modifying action: the five CCIP bridges and the CCIP cross-chain message,
both payment channels, both token-bound accounts, the three auction/orderbook
writes, four advanced-governance writes, three NFT lending writes, MPC recovery
and session keys, the Lens profile, the keeper job, the compute job and the
compute reward claim. Twenty-five of them broadcast through `send_transaction`;
the compute job hands its request to a third party. A twenty-seventh function,
`social_protocols._launch_token`, has the same shape: it is the private helper
behind `launch_social_token` and `launch_creator_coin`, which no action names.

AND ONE THAT SAID A DIFFERENT WORD. `kyc.issue_kyc_credential` broadcast an EAS
attestation and returned `"issued"`, which the gate read as settled. A census
that searches for the gate's own words cannot find that, so the census below
starts from the send instead — see "the census by evidence".

`"submitted"` is in `_REAL_OUTCOME_STATUSES`, so `_outcome_is_real` answered
True for every one of them and the platform wrote an EAS attestation — a durable
claim addressed to third parties, whose entire value is that someone who does
not trust this platform can check it — asserting that a bridge, a channel close
or a liquidation HAPPENED, on the evidence that a node had accepted the bytes.
The same predicate governs the public feed, so the feed announced it too.

THE GATE HAD TWO ANSWERS AND THE TRUTH HAS THREE. Moving `"submitted"` out of
the real-outcome vocabulary would route these to `_attest_refusal`, which writes
"ACTION DECLINED" — a broadcast is not a decline, and that is the same defect
facing the other way. So the gate gains its third answer: settled, broadcast,
refused. A broadcast is recorded as a broadcast, carrying the hash that makes it
checkable, and is neither attested as done nor announced as done.

NOT A NEW VOCABULARY. `settle_transaction` already emits `settled: True` on a
confirmed receipt — including when its settled status is the word "submitted" —
and that flag still outranks everything, so no service that waits for its
receipt loses its attestation.

WHAT THIS DOES NOT TOUCH: `report_of`. Outcome learning asks whether the CALL
succeeded, and for a broadcast it did — the bytes went out. That question and
"may this be attested as done" are different, which is the distinction
`outcome_truth` was written to keep.
"""

from __future__ import annotations

import ast
import asyncio
import json
import pathlib

import pytest

from runtime.blockchain.services.service_dispatcher import (
    ACTION_MAP,
    RECORD_BROADCAST,
    RECORD_REFUSED,
    RECORD_SETTLED,
    _BROADCAST_STATUSES,
    _REAL_OUTCOME_STATUSES,
    _STATE_MODIFYING_ACTIONS,
    ServiceDispatcher,
    _record_verdict,
)

_SERVICES = pathlib.Path(__file__).resolve().parents[1] / "runtime" / "blockchain" / "services"


class _SpyFeed:
    def __init__(self) -> None:
        self.published: list[dict] = []

    async def ingest(self, **kwargs):  # noqa: D401 - test double
        self.published.append(kwargs)


@pytest.fixture
def dispatcher_with_spies():
    d = ServiceDispatcher({})
    feed = _SpyFeed()
    d._feed_engine = feed
    attested: list[str] = []
    declined: list[str] = []
    broadcast: list[str] = []

    async def _spy_attest(action, service_name, params, result, *, actor: str = "",
                          actor_source: str = "", actor_claimed: str = ""):
        attested.append(action)

    async def _spy_refusal(action, service_name, params, result, *, actor: str = "",
                           actor_source: str = "", actor_claimed: str = ""):
        declined.append(action)

    async def _spy_broadcast(action, service_name, params, result, *, actor: str = "",
                             actor_source: str = "", actor_claimed: str = ""):
        broadcast.append(action)

    d._attest_action = _spy_attest
    d._attest_refusal = _spy_refusal
    # Only bound once the third answer exists; harmless before then.
    d._record_broadcast = _spy_broadcast
    return d, feed, attested, declined, broadcast


# ── the census ───────────────────────────────────────────────────────────


#: Measured by `_bare_broadcast_methods` itself at the commit that pinned it: 27
#: functions (26 of them reachable as state-modifying actions, plus the private
#: helper `social_protocols._launch_token`, whose two public wrappers no action
#: names) in 10 service directories, reachable
#: under 27 action names (`submit_compute_job` has two).
_BARE_BROADCAST_METHODS_MEASURED = 27
_BARE_BROADCAST_ACTIONS_MEASURED = 27


def _bare_broadcast_methods() -> set[tuple[str, str]]:
    """Every method returning a broadcast status with no `settled` key.

    Re-derived from the tree rather than listed, so a method added later on the
    same pattern is caught here instead of shipping an attestation for an
    unconfirmed transaction.
    """
    words = {"submitted", "claim_submitted", "verification_submitted"}
    found: set[tuple[str, str]] = set()
    for path in _SERVICES.rglob("*.py"):
        try:
            tree = ast.parse(path.read_text())
        except SyntaxError:
            continue
        for node in ast.walk(tree):
            if not isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
                continue
            for sub in ast.walk(node):
                if not (isinstance(sub, ast.Return) and isinstance(sub.value, ast.Dict)):
                    continue
                keys = {k.value for k in sub.value.keys if isinstance(k, ast.Constant)}
                vals = {v.value for v in sub.value.values if isinstance(v, ast.Constant)}
                if "status" in keys and "settled" not in keys and (vals & words):
                    found.add((str(path.relative_to(_SERVICES)), node.name))
    return found


def test_the_bare_broadcast_surface_is_what_it_was_measured_to_be():
    """PREMISE. If this shrinks the defect is gone by another route; if it
    grows, a new method joined the pattern and the gate must still cover it.
    Either way the number is not allowed to drift unnoticed — which is why it is
    pinned to the measured count. It was `>= 20` at first, against a measured
    27: a floor that let the surface shrink by seven, or grow by any amount,
    without anyone looking."""
    found = _bare_broadcast_methods()
    assert len(found) == _BARE_BROADCAST_METHODS_MEASURED, (
        f"the bare-broadcast surface is {len(found)} functions, measured at "
        f"{_BARE_BROADCAST_METHODS_MEASURED} — re-derive before trusting the gate "
        f"or changing the number: {sorted(found)}"
    )


def test_those_methods_are_reachable_as_attested_actions():
    """REACHABILITY. A defect behind an unreachable path is a different finding.
    These are state-modifying actions, which is the ENTIRE condition under which
    the dispatcher attests and publishes."""
    method_names = {m for _, m in _bare_broadcast_methods()}
    reachable = {
        action for action, spec in ACTION_MAP.items()
        if isinstance(spec, (tuple, list)) and len(spec) > 1
        and spec[1] in method_names and action in _STATE_MODIFYING_ACTIONS
    }
    assert len(reachable) == _BARE_BROADCAST_ACTIONS_MEASURED, (
        f"expected {_BARE_BROADCAST_ACTIONS_MEASURED} attested actions to reach "
        f"the broadcast methods, found {len(reachable)}: {sorted(reachable)}"
    )


# ── the predicate ────────────────────────────────────────────────────────


@pytest.mark.parametrize(
    "label,result",
    [
        ("the shape 26 methods return", {"status": "submitted", "tx_hash": "0xabc"}),
        ("compute's reward claim", {"status": "claim_submitted", "tx_hash": "0xabc"}),
        ("explorer verification", {"status": "verification_submitted"}),
        ("case-insensitive", {"status": "SUBMITTED"}),
    ],
)
def test_a_bare_broadcast_is_its_own_answer(label, result):
    """Not settled, and NOT a refusal. Both of the other two answers are false
    about a transaction that was sent and may yet be mined."""
    assert _record_verdict(result) == RECORD_BROADCAST, label


@pytest.mark.parametrize(
    "label,result",
    [
        # THE ORDERING ARGUMENT, ASSERTED. `settle_transaction`'s settled status
        # DEFAULTS to the word "submitted", so a gate reading the word before
        # the flag would strip the attestation from every service that waits for
        # its receipt through `settle_transaction` — see the census of waits
        # below for which those are.
        ("settle_transaction's confirmed shape",
         {"status": "submitted", "settled": True, "value_moved": True,
          "block_number": 1, "tx_hash": "0xabc"}),
        ("a plain success with no chain in sight", {"pool_id": "p", "shares_minted": 1.0}),
        ("completed", {"status": "completed"}),
        ("a record-creating action", {"status": "pending", "created": True}),
    ],
)
def test_a_settlement_is_still_a_settlement(label, result):
    """SCOPE PIN. The great majority of attested actions never touch a chain and
    never emit `settled`; diverting them would be the mirror-image defect."""
    assert _record_verdict(result) == RECORD_SETTLED, label


@pytest.mark.parametrize(
    "label,result",
    [
        ("not_deployed", {"status": "not_deployed"}),
        ("error", {"status": "error"}),
        ("this audit's unsettled idiom", {"status": "recorded_unsettled"}),
        ("flags outrank the word", {"status": "submitted", "settled": False}),
        ("value_moved False", {"status": "submitted", "value_moved": False}),
        ("None", None),
        ("not a dict", "ok"),
    ],
)
def test_a_refusal_is_not_laundered_into_a_broadcast(label, result):
    """THE THIRD ANSWER MUST NOT BECOME A PLACE REFUSALS HIDE.

    Note the last two: a service that says `settled: False` while its status
    word says "submitted" is refusing, and 15-A's flags outrank the word in
    BOTH directions — that is the clause `_outcome_is_real` already runs first,
    and routing through it is why this holds without restating it.
    """
    assert _record_verdict(result) == RECORD_REFUSED, label


def test_the_broadcast_vocabulary_is_drawn_from_the_real_outcome_set():
    """PREMISE OF THE WHOLE FIX. These words were classified as REAL outcomes —
    that is precisely why they were attested. If one were ever moved to the
    non-outcome set instead, it would become a refusal, which is the mislabel
    this fix exists to avoid, and this fails."""
    assert _BROADCAST_STATUSES <= _REAL_OUTCOME_STATUSES, (
        "a broadcast word left the real-outcome vocabulary — it is now recorded "
        "as a REFUSAL, which is false about a transaction that was sent"
    )


# ── end to end ───────────────────────────────────────────────────────────


async def test_a_bare_broadcast_is_not_attested_as_a_completed_action(
    dispatcher_with_spies, monkeypatch,
):
    """THE LOAD-BEARING ASSERTION.

    Pre-fix this wrote an EAS attestation saying `create_tba` happened, on the
    evidence that a node had accepted the bytes. The transaction may revert.
    """
    d, feed, attested, declined, broadcast = dispatcher_with_spies

    from runtime.blockchain.services.tba.service import TokenBoundAccountService

    async def _broadcast_only(self, **params):
        return {
            "status": "submitted",
            "service": "tba",
            "method": "create_tba",
            "tx_hash": "0xdeadbeef",
        }

    monkeypatch.setattr(TokenBoundAccountService, "create_tba", _broadcast_only)

    await d.execute("create_tba", params={
        "token_contract": "0x" + "1" * 40, "token_id": 1,
    })
    await asyncio.sleep(0)

    assert attested == [], (
        "an unconfirmed broadcast was EAS-attested as a completed action"
    )
    assert feed.published == [], (
        "an unconfirmed broadcast was announced on the public feed as done"
    )


async def test_the_broadcast_is_still_recorded_as_a_broadcast(
    dispatcher_with_spies, monkeypatch,
):
    """THE THIRD ANSWER, NOT SILENCE AND NOT A DECLINE.

    Suppressing the record would trade a false record for no record. Calling it
    a refusal would be a falsehood in the other direction: the bytes went out
    and the hash is real.
    """
    d, feed, attested, declined, broadcast = dispatcher_with_spies

    from runtime.blockchain.services.tba.service import TokenBoundAccountService

    async def _broadcast_only(self, **params):
        return {"status": "submitted", "tx_hash": "0xdeadbeef"}

    monkeypatch.setattr(TokenBoundAccountService, "create_tba", _broadcast_only)

    await d.execute("create_tba", params={
        "token_contract": "0x" + "1" * 40, "token_id": 1,
    })

    assert broadcast == ["create_tba"], "the broadcast left no record at all"
    assert declined == [], "a broadcast was recorded as a refusal"


async def test_a_confirmed_settlement_is_still_attested(
    dispatcher_with_spies, monkeypatch,
):
    """SCOPE PIN, and the reason the fix reads the flag rather than the word.

    `settle_transaction` returns its settled status — which DEFAULTS to the
    word "submitted" — alongside `settled: True` once the receipt is in. A gate
    keyed on the word alone would stop attesting exactly the services that do
    wait for their receipt, which is the whole remediation facing backwards.
    """
    d, feed, attested, declined, broadcast = dispatcher_with_spies

    from runtime.blockchain.services.tba.service import TokenBoundAccountService

    async def _settled(self, **params):
        return {
            "status": "submitted",
            "tx_hash": "0xdeadbeef",
            "settled": True,
            "value_moved": True,
            "block_number": 12345,
        }

    monkeypatch.setattr(TokenBoundAccountService, "create_tba", _settled)

    await d.execute("create_tba", params={
        "token_contract": "0x" + "1" * 40, "token_id": 1,
    })
    await asyncio.sleep(0)

    assert attested == ["create_tba"], (
        "a settlement confirmed by a receipt lost its attestation"
    )
    assert [p["action"] for p in feed.published] == ["create_tba"]
    assert broadcast == []


async def test_a_refusal_is_still_a_refusal(dispatcher_with_spies, monkeypatch):
    """SCOPE PIN. The third answer must not become a place refusals hide."""
    d, feed, attested, declined, broadcast = dispatcher_with_spies

    from runtime.blockchain.services.tba.service import TokenBoundAccountService

    async def _refused(self, **params):
        return {"status": "not_deployed", "service": "tba"}

    monkeypatch.setattr(TokenBoundAccountService, "create_tba", _refused)

    await d.execute("create_tba", params={
        "token_contract": "0x" + "1" * 40, "token_id": 1,
    })

    assert declined == ["create_tba"]
    assert attested == []
    assert broadcast == []
    assert feed.published == []


# ── the helper's own unconfirmed shape ───────────────────────────────────
#
# AN INDEPENDENT REVIEW FOUND THE THIRD ANSWER MISSING FROM THE ONE PLACE THAT
# ALREADY SAID IT. `web3_manager.settle_transaction` is the shared form of
# "wait for the receipt", and when no receipt arrives in time it returns
# `{"status": "pending", "settled": False, "broadcast": True, "tx_hash": ...}`
# and says in its own disclosure: NOT a refusal and NOT a failure — it may be
# mined. `_record_verdict` asked `_outcome_is_real` first, `settled: False`
# makes that False, and the result went to `_attest_refusal`: "ACTION DECLINED",
# for a transaction the platform signed, paid gas for and sent. That is the
# same defect this file exists for, facing the other way, and it sat in the
# services that waited through a helper — neosafe, restaking, kyc — and in
# creator_platforms' mint, which wrote the same shape out inline. The services
# that waited inline and wrote a different shape are further down, under "the
# services that waited inline".
#
# The controls build the shape by CALLING the emitters, not by typing a dict:
# a hand-written dict is exactly how a control ends up missing the field that
# breaks the code.


class _NoReceiptWeb3:
    """A node that accepted the bytes and never produced a receipt in time."""

    async def wait_for_receipt(self, tx_hash, timeout=120):
        raise TimeoutError(f"no receipt for {tx_hash}")


class _Receipt:
    def __init__(self, status: int) -> None:
        self.status = status
        self.blockNumber = 7
        self.gasUsed = 21000


class _ReceiptWeb3:
    def __init__(self, status: int) -> None:
        self._status = status

    async def wait_for_receipt(self, tx_hash, timeout=120):
        return _Receipt(self._status)


def _emitters():
    from runtime.blockchain.services.restaking import _guards as restaking_guards
    from runtime.blockchain.web3_manager import settle_transaction

    async def shared(web3):
        return await settle_transaction(web3, "0xabc", "m", "svc", {}, timeout=1)

    async def restaking(web3):
        return await restaking_guards.settle_transaction(web3, "0xabc", "m", "svc", {})

    return [pytest.param(shared, id="web3_manager.settle_transaction"),
            pytest.param(restaking, id="restaking._guards.settle_transaction")]


@pytest.mark.parametrize("emit", _emitters())
async def test_a_transaction_sent_with_no_receipt_yet_is_a_broadcast_not_a_decline(emit):
    out = await emit(_NoReceiptWeb3())
    assert out.get("broadcast") is True and out.get("settled") is False, (
        f"premise changed — the emitter's unconfirmed shape is now {out}")
    assert _record_verdict(out) == RECORD_BROADCAST, (
        "a transaction that was SENT and may be mined was filed as "
        f"{_record_verdict(out)!r}: {out}")


@pytest.mark.parametrize("emit", _emitters())
async def test_a_confirmed_receipt_is_still_a_settlement(emit):
    """SCOPE PIN: the flag says the bytes went out, and a receipt that
    confirms them still outranks it."""
    out = await emit(_ReceiptWeb3(1))
    assert _record_verdict(out) == RECORD_SETTLED, out


@pytest.mark.parametrize("emit", _emitters())
async def test_a_reverted_receipt_is_still_not_a_settlement_or_a_broadcast(emit):
    """SCOPE PIN: a mined revert is ESTABLISHED — nothing moved — so it is not
    the unknown middle. It carries `broadcast: True` as well, which is why the
    flag alone cannot decide: `settled: True` says a receipt answered."""
    out = await emit(_ReceiptWeb3(0))
    assert out.get("broadcast") is True, out
    assert _record_verdict(out) == RECORD_REFUSED, out


@pytest.mark.parametrize(
    "label,result",
    [
        ("a string is not the flag", {"status": "pending", "settled": False,
                                      "broadcast": "true"}),
        ("broadcast False", {"status": "error", "broadcast": False}),
        ("no flag at all", {"status": "pending", "settled": False}),
    ],
)
def test_only_the_boolean_flag_makes_an_unsettled_result_a_broadcast(label, result):
    """THE FLAG IS NOT A NEW PLACE FOR REFUSALS TO HIDE. Only the boolean that
    the emitters write after `send_transaction` has returned a hash counts."""
    assert _record_verdict(result) == RECORD_REFUSED, label


async def test_an_action_whose_receipt_did_not_arrive_is_recorded_as_a_broadcast(
    dispatcher_with_spies, monkeypatch,
):
    """END TO END, through `execute`, with the shape the shared helper returns."""
    from runtime.blockchain.services.tba.service import TokenBoundAccountService
    from runtime.blockchain.web3_manager import settle_transaction

    d, feed, attested, declined, broadcast = dispatcher_with_spies

    async def _timed_out(self, **params):
        return await settle_transaction(_NoReceiptWeb3(), "0xdeadbeef", "create_tba",
                                        "tba", {"service": "tba"}, timeout=1)

    monkeypatch.setattr(TokenBoundAccountService, "create_tba", _timed_out)

    await d.execute("create_tba", params={
        "token_contract": "0x" + "1" * 40, "token_id": 1,
    })
    await asyncio.sleep(0)

    assert declined == [], "a sent transaction was recorded as ACTION DECLINED"
    assert broadcast == ["create_tba"], "the broadcast left no record of itself"
    assert attested == [] and feed.published == []


# ── the census by evidence, not by word ──────────────────────────────────
#
# THE FIRST CENSUS ASSUMED ITS OWN CONCLUSION. It looked for methods returning
# "submitted", "claim_submitted" or "verification_submitted" — the gate's own
# words — so it could only ever find the broadcasts the gate already handled.
# `kyc.issue_kyc_credential` sent an EAS attestation through `send_transaction`,
# waited for nothing, and returned `{"status": "issued", "tx_hash": ...}`. The
# gate read "issued" as SETTLED, the dispatcher EAS-attested it and the feed
# published it: a durable statement about a person's KYC status, made on the
# evidence that a node had accepted the bytes. The census could not see it,
# because it searched for the words and not for the send.
#
# This census starts from the EVIDENCE: a function under `services/` that calls
# a send primitive and no receipt wait. For every literal dict such a function
# returns, the gate itself is asked what it would record — with the literal's
# constant fields filled in — and SETTLED is the one answer that is never true
# of a transaction nobody has seen a receipt for. A method added later that
# broadcasts and says "bridged", "sent" or "issued" fails here by name.

_SEND_PRIMITIVES = frozenset({"send_transaction", "send_raw_transaction"})
_RECEIPT_WAITS = frozenset({
    "settle_transaction", "wait_for_receipt", "wait_for_transaction_receipt",
})

#: Measured at the commit that wrote this line, by `_no_wait_broadcasters`
#: itself: 26 functions in 10 service directories. Pinned exactly, so the
#: surface cannot grow or shrink without someone re-reading it.
_NO_WAIT_BROADCASTERS_MEASURED = 26



def _called_names(node: ast.AST) -> set[str]:
    names: set[str] = set()
    for sub in ast.walk(node):
        if isinstance(sub, ast.Call):
            func = sub.func
            if isinstance(func, ast.Attribute):
                names.add(func.attr)
            elif isinstance(func, ast.Name):
                names.add(func.id)
    return names


def _no_wait_broadcasters() -> dict[tuple[str, str], list[ast.Dict]]:
    """Every function that sends a transaction and waits for no receipt, with
    the dict literals it returns."""
    found: dict[tuple[str, str], list[ast.Dict]] = {}
    for path in sorted(_SERVICES.rglob("*.py")):
        try:
            tree = ast.parse(path.read_text())
        except SyntaxError:
            continue
        for node in ast.walk(tree):
            if not isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
                continue
            called = _called_names(node)
            if not (called & _SEND_PRIMITIVES) or (called & _RECEIPT_WAITS):
                continue
            returns = [sub.value for sub in ast.walk(node)
                       if isinstance(sub, ast.Return) and isinstance(sub.value, ast.Dict)]
            found[(str(path.relative_to(_SERVICES)), node.name)] = returns
    return found


def _as_the_gate_would_see_it(literal: ast.Dict) -> dict:
    """The literal with its constant fields, and a stand-in for every computed
    value — the gate reads named fields, so a computed hash is still a hash."""
    shaped: dict = {}
    for key, value in zip(literal.keys, literal.values):
        if not isinstance(key, ast.Constant):
            continue
        shaped[key.value] = value.value if isinstance(value, ast.Constant) else "<computed>"
    return shaped


def test_no_method_that_sends_without_waiting_can_be_recorded_as_settled():
    """THE LOAD-BEARING CENSUS. Fails on the pre-fix tree by name:
    `kyc/service.py issue_kyc_credential` returned `status: "issued"`."""
    settled_claims = []
    handed_off = []
    for (path, name), returns in _no_wait_broadcasters().items():
        shapes = [_as_the_gate_would_see_it(literal) for literal in returns]
        for shaped in shapes:
            if _record_verdict(shaped) == RECORD_SETTLED:
                settled_claims.append((path, name, shaped.get("status")))
        if not any("tx_hash" in shaped for shaped in shapes):
            handed_off.append((path, name))
    assert settled_claims == [], (
        "a method broadcasts a transaction, waits for no receipt, and returns a "
        "result the gate records as SETTLED — it would be EAS-attested and "
        f"published as done: {settled_claims}")
    # THE CENSUS'S BLIND SPOT, MADE TO FAIL RATHER THAN PASS. It reads the
    # literals of the function that SENDS. A function that sends and hands the
    # hash to a caller, which then writes the status, would be invisible here —
    # so every sender must report its own broadcast, with the hash, itself.
    assert handed_off == [], (
        "a function sends a transaction and returns no result carrying its hash; "
        "whatever labels that broadcast is outside this census — follow it: "
        f"{handed_off}")


def test_the_no_wait_broadcast_surface_is_what_it_was_measured_to_be():
    found = _no_wait_broadcasters()
    assert len(found) == _NO_WAIT_BROADCASTERS_MEASURED, (
        f"the no-receipt-wait broadcast surface is {len(found)} functions, "
        f"measured at {_NO_WAIT_BROADCASTERS_MEASURED} — re-read it before "
        f"changing the number: {sorted(found)}")


def test_the_census_sees_a_send_that_uses_neither_word():
    """THE CENSUS'S OWN CONTROL. A census that cannot see the defect it is for
    proves nothing when it comes back clean, so it is run over a planted
    function shaped like the one it missed."""
    planted = ast.parse(
        "async def issue(self):\n"
        "    tx_hash = await self._web3.send_transaction({})\n"
        "    return {'status': 'issued', 'tx_hash': tx_hash}\n"
    ).body[0]
    called = _called_names(planted)
    assert called & _SEND_PRIMITIVES and not (called & _RECEIPT_WAITS)
    literal = next(sub.value for sub in ast.walk(planted) if isinstance(sub, ast.Return))
    assert _record_verdict(_as_the_gate_would_see_it(literal)) == RECORD_SETTLED, (
        "the census's reading no longer flags the shape it was written to catch")


# ── the one it missed ────────────────────────────────────────────────────


class _Chain:
    """Just enough of Web3Manager for `issue_kyc_credential` to reach the send."""

    available = True
    paymaster_key = "0x" + "1" * 64
    chain_id = 8453

    def __init__(self, receipt_status: int | None) -> None:
        self._receipt_status = receipt_status
        self.sent: list[dict] = []

        class _Eth:
            gas_price = 1
            def get_transaction_count(self, _addr):
                return 0

        class _W3:
            eth = _Eth()

        self.w3 = _W3()

    def get_account(self):
        class _Account:
            address = "0x" + "3" * 40
        return _Account()

    def load_contract(self, _address, _abi):
        class _Call:
            def build_transaction(self, tx):
                return dict(tx)

        class _Functions:
            def attest(self, _request):
                return _Call()

        class _Contract:
            functions = _Functions()

        return _Contract()

    async def send_transaction(self, tx, *, action=None):
        self.sent.append(tx)
        return "0x" + "ab" * 32

    async def wait_for_receipt(self, tx_hash, timeout=120):
        if self._receipt_status is None:
            raise TimeoutError(f"no receipt for {tx_hash}")
        return _Receipt(self._receipt_status)

    def explorer_url(self, _tx_hash):
        return None


def _kyc_dispatcher(receipt_status, spies):
    d, feed, attested, declined, broadcast = spies
    config = {
        "services": {"kyc": {"enabled": True}},
        "blockchain": {"eas_contract": "0x" + "2" * 40, "eas_schema": "0x" + "cd" * 32},
    }
    from runtime.blockchain.services.kyc.service import KYCService
    svc = KYCService(config)
    chain = _Chain(receipt_status)
    svc._web3 = chain
    d._get_registry()._instances["kyc"] = svc
    return d, svc, chain


_SCREENED = {"subject": "0x" + "4" * 40, "kyc_level": "verified",
             "verification_result": {"sanctions_screened": True, "review_answer": "GREEN"}}


async def test_a_kyc_credential_that_was_only_sent_is_not_attested_as_issued(
    dispatcher_with_spies,
):
    """DEFECT-PROVER for the method the word census could not see."""
    d, svc, chain = _kyc_dispatcher(None, dispatcher_with_spies)
    _, feed, attested, declined, broadcast = dispatcher_with_spies

    await d.execute("issue_kyc_credential", params=dict(_SCREENED))
    await asyncio.sleep(0)

    assert len(chain.sent) == 1, "premise changed — the credential was never sent"
    assert attested == [], (
        "a KYC credential nobody has seen a receipt for was EAS-attested as issued")
    assert feed.published == [], "and announced on the public feed as done"
    assert declined == [], "a sent credential is not a decline either"
    assert broadcast == ["issue_kyc_credential"]


async def test_a_kyc_credential_with_a_confirmed_receipt_is_still_attested(
    dispatcher_with_spies,
):
    """SCOPE PIN. Waiting must not become never attesting."""
    d, svc, chain = _kyc_dispatcher(1, dispatcher_with_spies)
    _, feed, attested, declined, broadcast = dispatcher_with_spies

    raw = await svc.issue_kyc_credential(**_SCREENED)
    assert raw["status"] == "issued" and raw["settled"] is True, raw

    await d.execute("issue_kyc_credential", params=dict(_SCREENED))
    await asyncio.sleep(0)
    assert attested == ["issue_kyc_credential"], (
        "a credential the chain confirmed lost its attestation")
    assert declined == [] and broadcast == []


async def test_a_kyc_credential_the_chain_reverted_is_not_issued(dispatcher_with_spies):
    d, svc, chain = _kyc_dispatcher(0, dispatcher_with_spies)
    _, feed, attested, declined, broadcast = dispatcher_with_spies

    raw = await svc.issue_kyc_credential(**_SCREENED)
    assert raw["status"] == "failed", raw

    await d.execute("issue_kyc_credential", params=dict(_SCREENED))
    await asyncio.sleep(0)
    assert attested == [] and feed.published == []
    assert declined == ["issue_kyc_credential"]


# ── the services that waited inline ──────────────────────────────────────
#
# AN INDEPENDENT REVIEW FOUND THE SAME DEFECT WHERE THE CENSUS COULD NOT LOOK.
# The census above skips every function that waits for a receipt, on the
# reasoning that a service which waits knows its outcome. Two did not know what
# to do when the wait ran out. `attestation.revoke` and the time-critical
# `attest_now` behind `create_attestation` called `send_raw_transaction`, then
# `w3.eth.wait_for_transaction_receipt` inside the same `try`, and a wait that
# timed out fell into `except Exception` and came back as
# `{"status": "failed", "error": ...}` with no hash. The dispatcher filed it
# "ACTION DECLINED" for a revocation or an emergency freeze the platform had
# signed, paid gas for and sent. `contract_conversion._compile_and_deploy` had
# the same shape, and on a receipt that did arrive it said "deployed" without
# reading the receipt's status, so a reverted deployment was EAS-attested.
#
# The node below accepts the bytes. What it does next is the parameter.


class _EASNode:
    """A raw web3 stand-in for the services that build their own `Web3`."""

    def __init__(self) -> None:
        self.sent: list[bytes] = []
        node = self

        class _Call:
            def build_transaction(self, tx):
                return dict(tx)

        class _Functions:
            def attest(self, *_a):
                return _Call()

            def revoke(self, *_a):
                return _Call()

        class _Contract:
            functions = _Functions()

        class _Eth:
            gas_price = 1

            def contract(self, **_kw):
                return _Contract()

            def get_transaction_count(self, _address):
                return 0

            def send_raw_transaction(self, raw):
                node.sent.append(raw)
                return bytes.fromhex("ab" * 32)

            def wait_for_transaction_receipt(self, _tx_hash, timeout=120):
                # What the code before this fix called directly. It is made to
                # time out too, so a control run against that code fails for
                # the reason the review found and not for a missing stub.
                raise TimeoutError("no receipt in time")

        self.eth = _Eth()


class _SignedTx:
    raw_transaction = b"\x01\x02"
    rawTransaction = b"\x01\x02"


class _PlatformAccount:
    address = "0x" + "3" * 40

    def sign_transaction(self, _tx):
        return _SignedTx()


def _web3_receipt(status: int):
    """A receipt the way web3 returns one: readable by key and by attribute."""
    from web3.datastructures import AttributeDict

    return AttributeDict({"status": status, "blockNumber": 7, "gasUsed": 21000,
                          "contractAddress": "0x" + "9" * 40})


def _receipt_wait(monkeypatch, outcome, node):
    """Decide what a receipt wait answers. `outcome` is a receipt status, or
    None for a wait that runs out.

    Both waits are set: the shared one the fix routes through, and the node's
    own, which the code before the fix called directly. So a control run
    against that code fails on what it did with the answer, not on a stub it
    never reached."""
    from runtime.blockchain import web3_manager

    async def _wait(_w3, tx_hash, timeout=120):
        if outcome is None:
            raise TimeoutError(f"no receipt for {tx_hash} within {timeout}s")
        return _web3_receipt(outcome)

    def _node_wait(tx_hash, timeout=120):
        if outcome is None:
            raise TimeoutError(f"no receipt for {tx_hash} within {timeout}s")
        return _web3_receipt(outcome)

    monkeypatch.setattr(web3_manager, "wait_for_receipt_on", _wait, raising=False)
    node.eth.wait_for_transaction_receipt = _node_wait


_EAS_CONFIG = {"blockchain": {
    "eas_contract": "0x" + "2" * 40, "eas_schema": "0x" + "cd" * 32,
    "paymaster_private_key": "0x" + "1" * 64, "platform_wallet": "0x" + "3" * 40,
    "rpc_url": "http://127.0.0.1:1",
}}


def _attestation_dispatcher(monkeypatch, spies):
    import web3 as web3_module
    from web3 import Web3 as _RealWeb3

    import runtime.blockchain.sponsorship as sponsorship
    from runtime.blockchain.services.attestation.service import AttestationService

    node = _EASNode()

    class _Web3:
        HTTPProvider = staticmethod(lambda _url: None)
        to_checksum_address = staticmethod(_RealWeb3.to_checksum_address)

        def __new__(cls, *_a, **_k):
            return node

    monkeypatch.setattr(web3_module, "Web3", _Web3)
    monkeypatch.setattr(sponsorship, "unmetered_platform_signer",
                        lambda _key, _action: _PlatformAccount())
    d = spies[0]
    svc = AttestationService(_EAS_CONFIG)
    svc._time_critical._web3 = node
    d._get_registry()._instances["attestation"] = svc
    return d, svc, node


_REVOKE = {"attestation_uid": "0x" + "ef" * 32, "schema_uid": "0x" + "cd" * 32}
_FREEZE = {"schema_uid": "0x" + "cd" * 32, "recipient": "0x" + "4" * 40,
           "data": {"category": "emergency_freeze", "agent": "neo"}}


async def test_a_revocation_that_was_sent_and_not_confirmed_is_a_broadcast(
    dispatcher_with_spies, monkeypatch,
):
    """DEFECT-PROVER. Before: status "failed", no hash, ACTION DECLINED."""
    d, svc, node = _attestation_dispatcher(monkeypatch, dispatcher_with_spies)
    _, feed, attested, declined, broadcast = dispatcher_with_spies
    _receipt_wait(monkeypatch, None, node)

    raw = await svc.revoke(**_REVOKE)
    assert len(node.sent) == 1, "premise changed — the revocation was never sent"
    assert raw.get("broadcast") is True and raw.get("settled") is False, raw
    assert raw.get("tx_hash") == "ab" * 32, f"the hash of a sent revocation was lost: {raw}"
    assert _record_verdict(raw) == RECORD_BROADCAST, raw

    await d.execute("revoke_attestation", params=dict(_REVOKE))
    await asyncio.sleep(0)
    assert declined == [], "a sent revocation was recorded as ACTION DECLINED"
    assert broadcast == ["revoke_attestation"]
    assert attested == [] and feed.published == []


async def test_a_confirmed_revocation_is_still_settled(dispatcher_with_spies, monkeypatch):
    """SCOPE PIN: waiting through the helper must not stop a confirmed
    revocation being recorded as done."""
    d, svc, node = _attestation_dispatcher(monkeypatch, dispatcher_with_spies)
    _, feed, attested, declined, broadcast = dispatcher_with_spies
    _receipt_wait(monkeypatch, 1, node)

    raw = await svc.revoke(**_REVOKE)
    assert raw["status"] == "revoked" and raw["settled"] is True, raw
    await d.execute("revoke_attestation", params=dict(_REVOKE))
    await asyncio.sleep(0)
    assert attested == ["revoke_attestation"] and declined == [] and broadcast == []


async def test_a_reverted_revocation_is_not_a_revocation(dispatcher_with_spies, monkeypatch):
    d, svc, node = _attestation_dispatcher(monkeypatch, dispatcher_with_spies)
    _, feed, attested, declined, broadcast = dispatcher_with_spies
    _receipt_wait(monkeypatch, 0, node)

    raw = await svc.revoke(**_REVOKE)
    assert raw["status"] == "failed" and raw["settled"] is True, raw
    await d.execute("revoke_attestation", params=dict(_REVOKE))
    await asyncio.sleep(0)
    assert declined == ["revoke_attestation"] and attested == [] and broadcast == []


async def test_a_time_critical_attestation_that_was_sent_and_not_confirmed_is_a_broadcast(
    dispatcher_with_spies, monkeypatch,
):
    """DEFECT-PROVER, the other one. `create_attestation` for an emergency
    freeze, a ban record, a dispute filing or a rights reversion submits at
    once, and a wait that ran out came back "failed" with no hash."""
    d, svc, node = _attestation_dispatcher(monkeypatch, dispatcher_with_spies)
    _, feed, attested, declined, broadcast = dispatcher_with_spies
    _receipt_wait(monkeypatch, None, node)

    raw = await svc.attest(**_FREEZE)
    assert len(node.sent) == 1, "premise changed — the attestation was never sent"
    assert raw.get("broadcast") is True and raw.get("settled") is False, raw
    assert raw.get("tx_hash") == "ab" * 32, f"the hash of a sent attestation was lost: {raw}"
    assert raw.get("attestation_tx") == "ab" * 32, raw
    assert _record_verdict(raw) == RECORD_BROADCAST, raw

    await d.execute("create_attestation", params=dict(_FREEZE))
    await asyncio.sleep(0)
    assert declined == [], "a sent emergency freeze was recorded as ACTION DECLINED"
    assert broadcast == ["create_attestation"]
    assert attested == [] and feed.published == []


async def test_a_confirmed_time_critical_attestation_is_still_settled(
    dispatcher_with_spies, monkeypatch,
):
    d, svc, node = _attestation_dispatcher(monkeypatch, dispatcher_with_spies)
    _, feed, attested, declined, broadcast = dispatcher_with_spies
    _receipt_wait(monkeypatch, 1, node)

    raw = await svc.attest(**_FREEZE)
    assert raw["status"] == "attested" and raw["settled"] is True, raw
    assert raw["time_critical"] is True and raw["category"] == "emergency_freeze", raw
    await d.execute("create_attestation", params=dict(_FREEZE))
    await asyncio.sleep(0)
    assert attested == ["create_attestation"] and declined == [] and broadcast == []


async def test_a_reverted_time_critical_attestation_is_not_attested(
    dispatcher_with_spies, monkeypatch,
):
    d, svc, node = _attestation_dispatcher(monkeypatch, dispatcher_with_spies)
    _, feed, attested, declined, broadcast = dispatcher_with_spies
    _receipt_wait(monkeypatch, 0, node)

    raw = await svc.attest(**_FREEZE)
    assert raw["status"] == "failed" and raw["settled"] is True, raw
    await d.execute("create_attestation", params=dict(_FREEZE))
    await asyncio.sleep(0)
    assert declined == ["create_attestation"] and attested == [] and broadcast == []


def _deploying_conversion(monkeypatch, receipt_status):
    """A conversion service whose compiler and chain are stubbed and whose
    decisions are not. `receipt_status` None is a wait that runs out."""
    import sys
    import types

    from runtime.blockchain import web3_manager
    from runtime.blockchain.services.contract_conversion.service import (
        ContractConversionService,
    )

    fake_solcx = types.ModuleType("solcx")
    fake_solcx.compile_source = lambda *_a, **_k: {
        "<stdin>:Drop": {"abi": [], "bin": "6000"}}
    monkeypatch.setitem(sys.modules, "solcx", fake_solcx)

    svc = ContractConversionService({"conversion": {"auto_deploy": True}})
    monkeypatch.setattr(svc, "_ensure_solc", lambda: True)
    node = _EASNode()

    class _Constructor:
        def build_transaction(self, tx):
            return dict(tx)

    class _Deployable:
        def constructor(self):
            return _Constructor()

    node.eth.contract = lambda **_kw: _Deployable()
    node.eth.estimate_gas = lambda _tx: 100_000

    class _Chain:
        available = True
        chain_id = 84532
        w3 = node

        async def signer(self, _action):
            return _PlatformAccount()

        def explorer_url(self, tx_hash):
            return f"https://explorer/tx/{tx_hash}"

        async def wait_for_receipt(self, tx_hash, timeout=120):
            return await web3_manager.wait_for_receipt_on(self.w3, tx_hash, timeout)

    svc._web3 = _Chain()
    _receipt_wait(monkeypatch, receipt_status, node)
    return svc, node


async def test_a_reverted_deployment_is_not_deployed(monkeypatch):
    """DEFECT-PROVER. The deploy read `contractAddress` and `blockNumber` off
    the receipt and never its status, so a reverted deployment came back
    "deployed" and `convert` EAS-attested `contract_deployed` for it."""
    svc, node = _deploying_conversion(monkeypatch, 0)
    out = await svc._compile_and_deploy("contract Drop {}", "Drop")
    assert len(node.sent) == 1, "premise changed — the deployment was never sent"
    assert out["status"] != "deployed", f"a reverted deployment was reported deployed: {out}"
    assert out.get("settled") is True and out["status"] == "failed", out


async def test_a_deployment_with_no_receipt_is_a_broadcast_with_its_hash(monkeypatch):
    svc, node = _deploying_conversion(monkeypatch, None)
    out = await svc._compile_and_deploy("contract Drop {}", "Drop")
    assert len(node.sent) == 1
    assert out.get("broadcast") is True and out.get("settled") is False, out
    assert out.get("tx_hash") == "ab" * 32, f"the hash of a sent deployment was lost: {out}"


async def test_a_confirmed_deployment_still_names_its_contract(monkeypatch):
    svc, node = _deploying_conversion(monkeypatch, 1)
    out = await svc._compile_and_deploy("contract Drop {}", "Drop")
    assert out["status"] == "deployed" and out["settled"] is True, out
    assert out["contract_address"] == "0x" + "9" * 40, out
    assert out["tx_hash"] == "ab" * 32 and out["explorer"], out


async def test_convert_attests_a_deployment_only_when_its_receipt_confirms_it(monkeypatch):
    """The attestation follows the receipt: `convert` writes `contract_deployed`
    on-chain for a deployment the chain confirmed, and for nothing else."""
    import runtime.blockchain.eas_client as eas_client

    attested: list[dict] = []

    class _EAS:
        def __init__(self, _config):
            pass

        async def attest(self, **kwargs):
            attested.append(kwargs)
            return {"status": "attested"}

    monkeypatch.setattr(eas_client, "EASClient", _EAS)
    source = "contract Drop { function mint() public { uint256 x = 1; x += 1; } }"
    for status, expected in ((0, 0), (None, 0), (1, 1)):
        attested.clear()
        svc, _node = _deploying_conversion(monkeypatch, status)
        monkeypatch.setattr(svc._auditor, "audit", lambda *_a, **_k: type(
            "Report", (), {"auditable": True, "passed": True, "to_dict": lambda self: {}})())
        out = await svc.convert(source, "solidity")
        assert "deployment" in out, f"premise changed — nothing reached the deploy: {out}"
        assert len(attested) == expected, (
            f"receipt status {status!r}: {len(attested)} contract_deployed attestations "
            f"for {out['deployment']}")


# ── the census of waits ──────────────────────────────────────────────────
#
# THE CENSUS ABOVE COULD NOT SEE A WAIT THAT HANDLED ITS OWN TIMEOUT WRONGLY,
# because it skipped every function that waited. This one looks at exactly
# those. Under `services/`, a receipt wait is allowed in one kind of place: a
# `settle_transaction`, whose three shapes are driven above. Any other function
# that names a receipt wait decides for itself what a wait that ran out means,
# and three of them decided "failed". A method added later that waits inline
# fails here by name, whatever it does in its `except`.

_RAW_RECEIPT_WAITS = frozenset({"wait_for_receipt", "wait_for_transaction_receipt"})

#: Where a raw receipt wait may appear under `services/`: the settle helper.
#: `web3_manager.settle_transaction`, the shared form, is outside `services/`.
_SETTLE_HELPERS = frozenset({("restaking/_guards.py", "settle_transaction")})


def _names_used(node: ast.AST) -> set[str]:
    """Every attribute or name the function mentions — a wait passed by
    reference to a thread counts as much as one that is called."""
    names: set[str] = set()
    for sub in ast.walk(node):
        if isinstance(sub, ast.Attribute):
            names.add(sub.attr)
        elif isinstance(sub, ast.Name):
            names.add(sub.id)
    return names


def _functions_under(root: pathlib.Path):
    for path in sorted(root.rglob("*.py")):
        try:
            tree = ast.parse(path.read_text())
        except SyntaxError:
            continue
        for node in ast.walk(tree):
            if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
                yield path, node


def _inline_receipt_waiters(root: pathlib.Path = _SERVICES) -> set[tuple[str, str]]:
    return {
        (str(path.relative_to(root)), node.name)
        for path, node in _functions_under(root)
        if _names_used(node) & _RAW_RECEIPT_WAITS
    }


def test_a_receipt_wait_under_services_lives_only_in_settle_transaction():
    """THE LOAD-BEARING CENSUS for the services that wait. Fails on the tree
    before this fix, naming `attestation/service.py revoke`,
    `attestation/time_critical.py attest_now`,
    `contract_conversion/service.py _compile_and_deploy` and
    `creator_platforms/service.py mint_sound`."""
    inline = _inline_receipt_waiters() - _SETTLE_HELPERS
    assert inline == set(), (
        "a function under services/ waits for a receipt itself instead of through "
        "settle_transaction, so what a wait that runs out is recorded as is up to "
        f"its own except clause: {sorted(inline)}")


def test_the_census_of_waits_sees_a_wait_by_reference():
    """ITS OWN CONTROL: a planted inline wait, in the two forms the tree uses."""
    for source in (
        "async def f(self):\n"
        "    h = self.w3.eth.send_raw_transaction(b'')\n"
        "    r = self.w3.eth.wait_for_transaction_receipt(h, timeout=1)\n",
        "async def f(self):\n"
        "    h = self.w3.eth.send_raw_transaction(b'')\n"
        "    r = await asyncio.to_thread(self.w3.eth.wait_for_transaction_receipt, h)\n",
    ):
        node = ast.parse(source).body[0]
        assert _names_used(node) & _RAW_RECEIPT_WAITS, source


#: Measured by `_senders_by_wait` at the commit that wrote this line.
_SETTLE_SENDERS_MEASURED = 13


def _senders_by_wait() -> tuple[set, set, set]:
    """Every function under `services/` that sends a transaction, sorted by how
    it learns what happened: through `settle_transaction`, not at all, or
    inline. The three add up to every sender, so none can be outside all of
    them."""
    settle, no_wait, inline = set(), set(), set()
    for path, node in _functions_under(_SERVICES):
        if not (_called_names(node) & _SEND_PRIMITIVES):
            continue
        key = (str(path.relative_to(_SERVICES)), node.name)
        used = _names_used(node)
        if used & _RAW_RECEIPT_WAITS:
            inline.add(key)
        elif "settle_transaction" in used:
            settle.add(key)
        else:
            no_wait.add(key)
    return settle, no_wait, inline


def test_every_sender_under_services_is_accounted_for():
    settle, no_wait, inline = _senders_by_wait()
    assert inline == set(), f"a sender waits inline: {sorted(inline)}"
    assert len(no_wait) == _NO_WAIT_BROADCASTERS_MEASURED, sorted(no_wait)
    assert set(_no_wait_broadcasters()) == no_wait, (
        "the literal census and the sender census disagree about which senders wait")
    assert len(settle) == _SETTLE_SENDERS_MEASURED, (
        f"{len(settle)} senders wait through settle_transaction, measured at "
        f"{_SETTLE_SENDERS_MEASURED} — re-read them before changing the number: "
        f"{sorted(settle)}")
