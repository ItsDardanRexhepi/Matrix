"""The Vyper branch must not lose `payable` off a stacked decorator.

There were zero Vyper tests in this suite — `git grep -i vyper tests/` returned
nothing — which is why this survived a green suite (§AT: a defect lives where no
test asserts what it touches).

THE DEFECT. _parse_vyper matched the whole signature with one regex whose middle
group was `(?:@(\\w+)[^\\n]*\\n)*`. Python's `re` retains only the FINAL
repetition of a repeated group, so the idiomatic three-decorator form

    @external
    @payable
    @nonreentrant("lock")
    def deposit(): ...

parsed as ["external", "nonreentrant"] and `payable` vanished. The function was
emitted as a nonpayable Solidity function — a deposit endpoint that reverts on
every call carrying value — in output the user is invited to deploy.

It is the same silent mutability loss part 1 fixed on the pseudocode branch, on
the sibling language. §CD: a fix establishes a class.
"""

from __future__ import annotations

import pytest

from runtime.blockchain.services.contract_conversion.parser import SourceParser


STACKED = """
@external
@payable
@nonreentrant("lock")
def deposit():
    self.balances[msg.sender] += msg.value

@external
@view
def balanceOf(who: address) -> uint256:
    return self.balances[who]

@external
def withdraw(amount: uint256):
    self.balances[msg.sender] -= amount

@internal
@pure
def _double(x: uint256) -> uint256:
    return x * 2
"""


@pytest.fixture
def ir():
    return SourceParser({})._parse_vyper(STACKED)


def _fn(ir, name):
    for f in ir["functions"]:
        if f["name"] == name:
            return f
    raise AssertionError(f"{name} not parsed at all: "
                         f"{[f['name'] for f in ir['functions']]}")


def test_payable_survives_three_stacked_decorators(ir):
    fn = _fn(ir, "deposit")
    assert fn["mutability"] == "payable", (
        "payable was dropped — the generated Solidity would revert on every "
        "call that carries value")
    assert fn["visibility"] == "external"


def test_the_decorator_order_does_not_decide_the_answer(ir):
    """`@external` comes first and `@nonreentrant` last; neither position may
    be what determines mutability."""
    assert _fn(ir, "balanceOf")["mutability"] == "view"
    assert _fn(ir, "_double")["mutability"] == "pure"
    assert _fn(ir, "_double")["visibility"] == "internal"


def test_a_function_with_no_mutability_decorator_stays_nonpayable(ir):
    """The complement: nothing is invented for a function that declares none."""
    assert _fn(ir, "withdraw")["mutability"] == "nonpayable"


def test_every_declared_function_is_parsed(ir):
    assert {f["name"] for f in ir["functions"]} == {
        "deposit", "balanceOf", "withdraw", "_double"}
