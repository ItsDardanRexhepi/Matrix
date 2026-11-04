"""The Vyper parser reads a source once, in time that grows with its length.

THE DEFECT (pre-existing on The Matrix ``main``). The function header was one
pattern whose parameter list ``\\(([^)]*)\\)`` ran to the end of the source for
every ``def`` line that never closes its parentheses, so the cost of the
convert route a signed-in user reaches (``POST /api/v1/contracts/convert``)
grew with the square of the source: 21 KB of ``def f(`` lines took 0.7 s on
the event loop, 42 KB 3.1 s. The line each header is on was counted from the
start of the source for every header, and the body after each header was cut
from a copy of the rest of the source, the same way. The lines the count named
were not the lines the decorators were read on (``splitlines`` also breaks on
a form feed and other separators), so a separator in a comment above a
function lost the function.
"""
from __future__ import annotations

import re
import time

import pytest

from runtime.blockchain.services.contract_conversion.parser import SourceParser


def _seconds(source):
    start = time.perf_counter()
    SourceParser({}).parse(source, "vyper")
    return time.perf_counter() - start


@pytest.mark.parametrize("source", [
    pytest.param("@external\n" + "def f(\n" * 6000, id="parameter lists never close, 42 KB"),
    pytest.param("@external\n" + "def f() -> uint256\n" * 6000, id="return types never end, 114 KB"),
    pytest.param("@external\ndef f():\n    pass\n" * 3000, id="3,000 functions, 84 KB"),
    pytest.param("@external\ndef f(a: uint256,\n        b: address) -> uint256:\n    return a\n" * 4000,
                 id="4,000 two-line headers, 280 KB"),
])
def test_the_header_reading_is_linear_in_the_source(source):
    """[control] Seconds on the previous commit, well under half of one now."""
    assert _seconds(source) < 0.5


OLD_HEADER = re.compile(
    r"^[ \t]*def\s+(\w+)\s*\(([^)]*)\)\s*(?:->\s*([^:]+))?\s*:", re.MULTILINE)

SOURCES = [
    "# @version ^0.3.7\n# @title Vault\n\nbalance: public(uint256)\n\n@external\n@payable\n"
    "def deposit():\n    self.balance += msg.value\n\n@external\n@view\ndef total() -> uint256:\n"
    "    return self.balance\n",
    "@external\ndef multi(\n    a: uint256,\n    b: address\n) -> uint256:\n    return a\n\n"
    "@internal\ndef _h(x: uint256) -> (uint256, uint256):\n    return x, x\n",
    "@external\ndef f():\n    pass\ndef bare():\n    pass\n@external\ndef g() -> :\n    pass\n"
    "@external\ndef h() x:\n    pass\n@external\ndef tail() -> address:\n    return msg.sender",
    "@external\ndef f():\n    if True:\n        pass\n\n    pass\nx: uint256\n@external\ndef g():\n    pass\n",
]


def _old_reading(source):
    """What the previous pattern read: name, parameters, return type and the
    end of each header that has a decorator stack above it."""
    lines = source.splitlines()
    out = []
    for m in OLD_HEADER.finditer(source):
        line_no = source.count("\n", 0, m.start())
        i, decorated = line_no - 1, False
        while i >= 0:
            if not lines[i].strip():
                i -= 1
                continue
            decorated = lines[i].lstrip().startswith("@")
            break
        if decorated:
            out.append((m.group(1), m.group(2).strip(), (m.group(3) or "").strip() or None, m.end()))
    return out


@pytest.mark.parametrize("source", SOURCES)
def test_the_functions_read_are_the_ones_the_previous_pattern_read(source):
    """[guard] On well-formed sources the same functions, with the same
    parameters, return types and bodies."""
    ir = SourceParser({}).parse(source, "vyper")
    got = [(f["name"], f["params"], f["returns"], f["body"]) for f in ir["functions"]]
    parser = SourceParser({})
    want = []
    for name, params_raw, returns, end in _old_reading(source):
        body_lines = []
        for line in source[end:].split("\n")[1:]:
            if line and not line[0].isspace() and line.strip():
                break
            body_lines.append(line)
        want.append((name if name != "__init__" else "constructor",
                     parser._parse_vyper_params(params_raw),
                     parser._vyper_type_to_solidity(returns) if returns else None,
                     "\n".join(body_lines).strip()))
    assert got == want


def test_a_separator_in_a_comment_does_not_lose_the_function():
    """[control] A form feed in the comment above a decorated function put the
    line count and the lines out of step, and the function was dropped."""
    ir = SourceParser({}).parse("# notes \x0c here\n@external\ndef f():\n    pass\n", "vyper")
    assert [f["name"] for f in ir["functions"]] == ["f"]
