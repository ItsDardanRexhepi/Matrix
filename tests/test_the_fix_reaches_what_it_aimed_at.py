"""The outcome-truth fix, checked against the things it was aimed at.

``runtime/protocols/outcome_truth.py`` cites this file by name for two claims it
makes about itself. Neither was checked by anything: the file did not exist. A
module that states in its own documentation that a contract is pinned, when
nothing pins it, is the defect the module was written for, one level up — a
consequential fact (the next engineer's belief that a guard exists) derived from
writing it down rather than from a guard existing.

WHAT IS PINNED HERE.

1. THE IDENTITY CONTRACT. ``report_of`` returns one of the three module
   constants, never a copy of one. The module says so:

       `report_of(result) is SUCCESS` at five sites added in one pass, because
       every other path returns the interned module constant and the idiom
       looked safe.

   It is safe today because every return path hands back the module-level name
   or a value routed through ``_CANONICAL``. It stops being safe the moment any
   path returns ``stated.strip().lower()`` — a NEW string, equal to ``SUCCESS``
   and not ``SUCCESS`` — and CPython's interning of short identifier-like
   literals would hide the break on most inputs while exposing it on some. The
   readers below do not fail loudly when that happens; they quietly take the
   other branch.

   WHAT THE OTHER BRANCH COSTS, at the sites that actually compare with ``is``:

     * ``attestation/batch_processor`` decides ``landed`` vs ``requeue`` on it.
       A landed attestation graded not-landed is a SECOND ON-CHAIN WRITE.
     * ``subscriptions`` decides ``paid`` / ``declined`` / ``unresolved`` on it,
       which is whether a customer is billed.
     * ``social/scheduler`` decides ``published`` vs ``failed``, and a post
       marked published is never retried.
     * ``crossborder`` and ``neosafe`` publish ``attested`` from it.

2. THE FIX REACHING ITS OWN CALLER. ``foreign_report_of`` was written for one
   caller and names it in its docstring. It had none: ``SubscriptionService``
   called ``report_of``, so the reader written to stop a gateway's silence
   becoming a settled charge sat unused beside the code that needed it. A
   function whose reason to exist is a named call site must be called there.

NONE OF THIS IS A STRING SNIFF (§NEW-27). Every assertion is about identity of
objects and named fields of structures, never about the wording of any text.
"""
from __future__ import annotations

import ast
import json
import pathlib

import pytest

from runtime.protocols import outcome_truth
from runtime.protocols.outcome_truth import (
    FAILURE,
    OUTCOME_FIELD,
    SUCCESS,
    UNKNOWN,
    combine,
    foreign_report_of,
    report_of,
)

REPO = pathlib.Path(__file__).resolve().parent.parent
_ANSWERS = (SUCCESS, FAILURE, UNKNOWN)


def _is_canonical(value: object) -> bool:
    """True only for the module's own constant — identity, not equality."""
    return any(value is answer for answer in _ANSWERS)


# ── 1. the identity contract, on every path that can return a verdict ──────

#: One input per RETURN PATH in `report_of`, named for the path it exercises.
#: Not a sample of plausible payloads — the point is coverage of the branches,
#: because the contract breaks per-branch.
_EVERY_PATH = [
    pytest.param(None, id="no-structure-at-all"),
    pytest.param("not json", id="bare-string"),
    pytest.param([1, 2, 3], id="list-is-not-a-report"),
    pytest.param({}, id="empty-object"),
    pytest.param({"balance": "5.0"}, id="data-only-no-verdict"),
    pytest.param({"ok": True}, id="boolean-verdict-true"),
    pytest.param({"ok": False}, id="boolean-verdict-false"),
    pytest.param({"error": "boom"}, id="populated-error"),
    pytest.param({"error": None}, id="empty-error-field"),
    pytest.param({"created": True, "status": "pending"}, id="created-outranks-status"),
    pytest.param({"settled": False}, id="disclosure-flag"),
    pytest.param({"status": "not_deployed"}, id="status-failed-vocabulary"),
    pytest.param({"status": "queried"}, id="status-read-vocabulary"),
    pytest.param({"status": "pending"}, id="status-indeterminate"),
    pytest.param({"status": "deployed"}, id="status-real-outcome"),
    pytest.param({"status": "a word nobody has used"}, id="status-unrecognised"),
    # The stated-verdict path, which is the one that introduced the risk.
    pytest.param({OUTCOME_FIELD: "success"}, id="stated-success"),
    pytest.param({OUTCOME_FIELD: "failure"}, id="stated-failure"),
    pytest.param({OUTCOME_FIELD: "unknown"}, id="stated-unknown"),
    pytest.param({OUTCOME_FIELD: "SUCCESS"}, id="stated-uppercase"),
    pytest.param({OUTCOME_FIELD: "  success  "}, id="stated-padded"),
    pytest.param({OUTCOME_FIELD: "sideways"}, id="stated-unrecognised"),
    pytest.param({OUTCOME_FIELD: "success", "ok": False}, id="stated-contradicted"),
    # The unwrapping paths, including the JSON-string envelope.
    pytest.param({"ok": True, "data": {"status": "not_deployed"}}, id="wrapped-failure"),
    pytest.param({"ok": True, "data": {"status": "pending"}}, id="wrapped-unknown"),
    pytest.param({"ok": True, "data": {"status": "deployed"}}, id="wrapped-success"),
    pytest.param(json.dumps({"status": "ok", "result": {"status": "not_deployed"}}),
                 id="json-string-envelope"),
    pytest.param({"ok": True, "data": {"ok": True, "result": {"ok": False}}},
                 id="two-envelopes-deep"),
]


@pytest.mark.parametrize("value", _EVERY_PATH)
def test_report_of_returns_the_constant_and_never_a_copy_of_it(value):
    result = report_of(value)
    assert _is_canonical(result), (
        f"report_of returned {result!r}, which is equal to a verdict but is not "
        "the module's constant. Every reader that compares with `is` silently "
        "takes the other branch — a landed attestation is re-submitted, a "
        "charge is re-decided, a published post is marked failed."
    )


@pytest.mark.parametrize("value", _EVERY_PATH)
def test_the_same_contract_holds_when_the_caller_states_the_status_reading(value):
    """The keyword the dispatcher passes must not open a path of its own."""
    assert _is_canonical(report_of(value, status_describes_the_call=False))


@pytest.mark.parametrize("value", _EVERY_PATH)
def test_foreign_report_of_returns_the_constant_too(value):
    """It routes several answers through ``report_of`` and returns others
    directly, so it has return paths of its own to pin."""
    assert _is_canonical(foreign_report_of(value))


@pytest.mark.parametrize("parts", [
    (), (SUCCESS,), (FAILURE,), (UNKNOWN,),
    (SUCCESS, SUCCESS), (FAILURE, FAILURE), (SUCCESS, FAILURE),
    (SUCCESS, UNKNOWN), (FAILURE, UNKNOWN), (SUCCESS, FAILURE, UNKNOWN),
])
def test_combine_returns_the_constant_too(parts):
    """``social/scheduler`` compares ``combine(...)`` with ``is`` directly."""
    assert _is_canonical(combine(parts))


def test_the_three_answers_are_distinct_objects():
    """The contract is worth nothing if two of them are the same object."""
    assert len({id(a) for a in _ANSWERS}) == 3


def test_learnable_success_reads_the_constants_it_is_given():
    """The one consumer inside the module: it must agree with the readers."""
    assert outcome_truth.learnable_success(report_of({"ok": True})) is True
    assert outcome_truth.learnable_success(report_of({"ok": False})) is False
    assert outcome_truth.learnable_success(report_of({"status": "pending"})) is None


# ── 2. the readers that depend on it, re-derived rather than listed ────────

def _identity_readers() -> list[str]:
    """Every ``<expr> is SUCCESS/FAILURE/UNKNOWN`` comparison under runtime/ and
    gateway/, found by parsing rather than by grep, so a new one is covered the
    day it is written.

    Listing them here instead would be a second source of truth that goes stale
    exactly the way the missing file did.
    """
    names = {"SUCCESS", "FAILURE", "UNKNOWN"}
    found: list[str] = []
    for root in ("runtime", "gateway"):
        for path in sorted((REPO / root).rglob("*.py")):
            if "__pycache__" in path.parts:
                continue
            if path == REPO / "runtime" / "protocols" / "outcome_truth.py":
                continue  # the module itself is not one of its readers
            try:
                tree = ast.parse(path.read_text(encoding="utf-8", errors="replace"))
            except SyntaxError:
                continue
            for node in ast.walk(tree):
                if not isinstance(node, ast.Compare):
                    continue
                if not any(isinstance(op, ast.Is) for op in node.ops):
                    continue
                sides = [node.left, *node.comparators]
                if any(isinstance(s, ast.Name) and s.id in names for s in sides):
                    found.append(f"{path.relative_to(REPO)}:{node.lineno}")
    return found


def test_the_identity_contract_actually_has_readers():
    """The premise of everything above. If this ever returns nothing the
    contract is free to relax — but then the comment in outcome_truth.py that
    justifies it has to go too, and this failure is what forces that."""
    readers = _identity_readers()
    assert readers, (
        "no code compares a verdict with `is` any more, so the interning "
        "contract has no reader left to protect — revisit the note in "
        "outcome_truth.py that cites this file before deleting it"
    )


def test_every_identity_reader_gets_its_verdict_from_this_module():
    """An ``is SUCCESS`` against a string from somewhere else would be a
    comparison the contract above cannot protect, and it would look identical
    at the call site."""
    offenders = []
    for reader in _identity_readers():
        path = REPO / reader.rsplit(":", 1)[0]
        source = path.read_text(encoding="utf-8", errors="replace")
        if "outcome_truth import" not in source and "outcome_truth." not in source:
            offenders.append(reader)
    assert not offenders, (
        "these compare with `is` against names that do not come from "
        f"outcome_truth, so the constants may not be the same objects: {offenders}"
    )


# ── 3. the reader written for one caller is called there ───────────────────

def test_foreign_report_of_is_used_by_the_service_it_was_written_for():
    """``foreign_report_of``'s docstring names ``SubscriptionService`` and the
    exact defect it exists to stop — a decline delivered as an HTTP response
    object, a plain string or ``None`` becoming a settled charge. The service
    called ``report_of``, whose no-report-means-success default is measured over
    THIS tree and says nothing about a payment gateway.

    Pinned structurally, on the import and the call, so the fix cannot be
    reverted to the measured default without this failing.
    """
    path = REPO / "runtime/blockchain/services/subscriptions/service.py"
    tree = ast.parse(path.read_text(encoding="utf-8"))

    imported = {
        alias.name
        for node in ast.walk(tree)
        if isinstance(node, ast.ImportFrom)
        and node.module == "runtime.protocols.outcome_truth"
        for alias in node.names
    }
    assert "foreign_report_of" in imported, (
        "the subscription service no longer imports the reader written for it")
    assert "report_of" not in imported, (
        "the service imports this tree's own reader; a gateway is not this "
        "tree, and its silence is not a yes")

    called = {
        node.func.id
        for node in ast.walk(tree)
        if isinstance(node, ast.Call) and isinstance(node.func, ast.Name)
    }
    assert "foreign_report_of" in called and "report_of" not in called, (
        f"the charge is graded by the wrong reader: {sorted(called & {'report_of', 'foreign_report_of'})}")


def test_a_foreign_party_saying_nothing_is_not_a_yes():
    """The behaviour the call site above buys, stated once here so the contract
    is readable without the service."""
    for silent in (None, "DECLINED", object(), {"result": "declined"}, {}):
        assert foreign_report_of(silent) is UNKNOWN, (
            f"a party whose refusal idiom we have never measured said nothing "
            f"this tree recognises, and it was read as a success: {silent!r}")


def test_a_foreign_party_that_speaks_plainly_is_still_believed():
    """The scope pin. Refusing to read silence as a yes must not make an
    explicit answer unreadable."""
    assert foreign_report_of({"ok": True}) is SUCCESS
    assert foreign_report_of({"ok": False}) is FAILURE
    assert foreign_report_of({"error": "card declined"}) is FAILURE
    assert foreign_report_of({"status": "not_deployed"}) is FAILURE
    assert foreign_report_of({OUTCOME_FIELD: "success"}) is SUCCESS
    assert foreign_report_of({"ok": False, "error": "card declined"}) is FAILURE
    assert foreign_report_of({"status": "declined"}) is FAILURE
    assert foreign_report_of({"status": "declined", "created": True}) is FAILURE


@pytest.mark.parametrize("reply", [
    {"status": "paid"}, {"status": "cancelled"}, {"status": "processing"},
    {"status": "refunded"}, {"status": "requested"},
    {"status": "declined", "created": True},
    {"ok": True, "status": "refunded"}, {"ok": True, "error": "card declined"},
    {"ok": True, "settled": False}, {OUTCOME_FIELD: "success", "status": "declined"},
])
def test_a_foreign_party_is_believed_only_where_everything_it_said_agrees(reply):
    """A FOREIGN STATUS WORD IS NEVER A YES, and a reply that speaks in more than
    one field is believed only where every field says the same thing. The first
    version of `foreign_report_of` handed any reply with a `status` to
    `report_of`, which reads the platform's own real-outcome words as success
    and `created: True` as success before the status — a vocabulary measured over
    this tree, applied to a party it was never measured on. A refusal word still
    counts as a refusal: it costs a grace period, never a charge."""
    assert foreign_report_of(reply) is not SUCCESS, f"{reply!r} was read as a settled yes"
