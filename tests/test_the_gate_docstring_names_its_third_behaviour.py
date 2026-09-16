"""`gateway/security_gate.py` describes itself as a two-item module. It has three.

The header says: "This is a BOUNDARY caller, not an implementation. It contains
NO security logic ... It only: (1) carries the per-request security CONTEXT ...
and (2) calls get_morpheus_security().evaluate(action, context)".

There is a third behaviour, and it is the one that matters most: when the seam
cannot be reached, `gate_action` makes its own allow/deny decision with no
`evaluate()` result in hand. It imports `runtime.access_policy`, asks whether
the action could move value, and on yes returns a BINDING deny — `is_blocked`
reads it as a deny and three call sites 403 on it. That is security logic, and
it is the correct behaviour; the enumeration is what is false.

Two neighbouring sentences fail with it:

* "that classification lives only in the private gate" — a public, code-enforced
  classification of value-moving actions exists in this repository, in
  `runtime/access_policy.py`, and it is what drives the deny above. The module
  says so itself: the private policy "supersedes this when it is installed".
* `gate_action`'s own docstring says the fault path "returns an OBSERVE allow"
  and "only declines to add a second, redundant block here". It adds a block.

Every assertion below is anchored to an observation, so the prose cannot be
corrected into a second wrong shape: the behaviour is exercised first and the
docstring is required to describe what was just seen.
"""

from __future__ import annotations

import pytest

import gateway.security_gate as security_gate


async def _faulted_gate(monkeypatch):
    """Make the seam raise, which is the path the header does not describe."""
    def _boom():
        raise RuntimeError("seam unreachable")

    monkeypatch.setattr("runtime.security.get_morpheus_security", _boom)


# ── 1. the third behaviour, observed ───────────────────────────────────────

async def test_a_faulted_seam_produces_a_binding_deny_this_module_computed(
        monkeypatch):
    await _faulted_gate(monkeypatch)
    decision = await security_gate.gate_action("transfer", {}, {})
    assert security_gate.is_blocked(decision) is True, decision
    assert decision.get("route") == "fail-closed", decision


async def test_a_faulted_seam_observe_allows_a_benign_read(monkeypatch):
    await _faulted_gate(monkeypatch)
    decision = await security_gate.gate_action("get_balance", {}, {})
    assert security_gate.is_blocked(decision) is False, decision


def test_the_public_classification_exists_and_is_reachable():
    from runtime.access_policy import could_move_value

    assert could_move_value("transfer") is True
    assert could_move_value("a_verb_no_table_has_ever_seen") is True, (
        "the public floor is fail-closed on the unknown")


# ── 2. the prose describes what was just observed ──────────────────────────

def _no_longer_asserted(text: str, phrase: str) -> bool:
    """The phrase is either gone, or every occurrence is a quotation of what the
    docstring used to say. A correction is allowed to quote what it corrects."""
    start = 0
    while (i := text.find(phrase, start)) != -1:
        if "used to" not in text[max(0, i - 260):i]:
            return False
        start = i + 1
    return True


def test_the_header_does_not_enumerate_two_behaviours_and_have_three():
    head = security_gate.__doc__ or ""
    assert _no_longer_asserted(head, "It only:"), (
        "the header still enumerates exactly two behaviours; the fault path is "
        "a third, and it is a binding deny this module computes itself")
    assert "fail-clos" in head or "fail clos" in head.lower(), head
    assert "three things" in head, head


def test_the_header_does_not_say_the_classification_is_only_private():
    head = security_gate.__doc__ or ""
    assert _no_longer_asserted(head, "lives only in the private gate"), head
    assert "access_policy" in head, (
        "the public floor that drives the fault-path deny is not named")


def test_gate_action_does_not_describe_the_fault_path_it_does_not_take():
    doc = security_gate.gate_action.__doc__ or ""
    assert _no_longer_asserted(doc, "returns an OBSERVE allow"), doc
    assert _no_longer_asserted(
        doc, "only declines to add a second, redundant block here"), doc
    assert "fail-closed" in doc, doc


@pytest.mark.parametrize("name", ["carries", "evaluate"])
def test_the_two_true_halves_are_still_stated(name):
    assert name in (security_gate.__doc__ or "")
