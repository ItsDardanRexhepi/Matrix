"""The rules the pseudocode parser applies for the README's layout.

The README's convert example indents each `function` line under `contract` and
writes `payable` before the keyword. `SourceParser._layout_prefix` and
`SourceParser._layout_body` state the rules in full; these tests hold the
parser to them:

- a `function` keyword takes the layout only when the text before it on its
  line is spaces or tabs, then optionally `payable` and spaces or tabs, and
  that text is under 256 characters long, both at the start of the source and
  on a later line (255 is read, 256 is not);
- `payable` there makes the function payable when what is read after the
  parameter list leaves it public and nonpayable and no `/*` comes earlier in
  the source, wherever that `/*` is; a `/*` after the function does not count;
- an indented function keeps the body the base parser reads when its header
  line has text after the signature and return type, or when that base body
  holds any of `; { } /* */ // #` `assembly` `unchecked` `try` `catch`, also
  inside a longer word and also in a later function before the next line that
  starts at column 0, but not after it;
- otherwise its body ends before the next line that is spaces or tabs, then
  optionally `payable`, then `function name(...)` on that one line, at the
  function's indent or a leading part of it, or, with no such line, at the
  next line that starts at column 0; any other line of spaces or tabs, then
  optionally `payable`, then `function` leaves the base body;
- that body gets a `;` before the trailing whitespace of each non-blank line
  only when every line is a plain one-line statement. There is a test for
  each character a line may not end with and each it may not begin with, each
  opening word, a bare `return`, an unbalanced `(` or `[`, a continuation
  indented with a tab, and CRLF line endings. When one line is not plain, the
  function keeps the whole base body: it is not cut at the next function.

Every other body is the base body, read by `_extract_pseudo_body`.
"""
from __future__ import annotations

import pytest

from runtime.blockchain.services.contract_conversion.parser import SourceParser

HEAD = "contract C\n    state n: uint256\n"
SIBLING = "    function g(x: uint256)\n        n = x\n"


def _functions(source: str) -> dict[str, dict]:
    return {f["name"]: f for f in SourceParser({}).parse(source, "pseudocode")["functions"]}


def _base_body(source: str, name: str) -> str:
    """The body the base parser reads for `name`: from the end of its signature."""
    start = source.index(f"function {name}(")
    return SourceParser._extract_pseudo_body(source, source.index(")", start) + 1)


def _body_of_f(body: str) -> tuple[str, str]:
    """(f's body as parsed, f's base body) for `body` under an indented f, followed by a sibling."""
    source = HEAD + "    function f(x: uint256)\n" + body + SIBLING
    return _functions(source)["f"]["body"], _base_body(source, "f")


# ── bodies left exactly as the base parser reads them ────────────────────────

LEFT_AS_BASE = {
    "semicolon": "        n = x;\n        n = n + 1\n",
    "open brace": "        n = x {\n        n = 1\n",
    "close brace": "        n = 1\n        }\n",
    "block comment open": "        n = x /* set\n        n = n + 1\n",
    "block comment close": "        n = x */ y\n",
    "line comment": "        n = x // set\n",
    "hash comment": "        n = x # set\n",
    "assembly": "        assembly\n        n = x\n",
    "unchecked": "        unchecked\n        n = x\n",
    "try": "        try n = x\n",
    "catch": "        n = x\n        catch\n",
    "if head": "        if (x > 1)\n            n = 1\n",
    "else head": "        n = 1\n        else\n            n = 2\n",
    "for head": "        for (x)\n            n = n + 1\n",
    "while head": "        while (x > n)\n            n = n + 1\n",
    "do head": "        do\n            n = n + 1\n",
    "bare return": "        n = x\n        return\n",
    "unbalanced parenthesis": "        n = (x\n        n = 1)\n",
    "unbalanced bracket": "        n = a[x\n        n = 1]\n",
    "continuation indented with a tab": "        n = x * 25\n\t\t\t/ 1000\n",
}


@pytest.mark.parametrize("body", LEFT_AS_BASE.values(), ids=LEFT_AS_BASE.keys())
def test_a_body_outside_the_plain_one_line_shape_is_the_base_body(body):
    parsed, base = _body_of_f(body)
    assert parsed == base


# A line ending in one of these characters goes on to the next line. Each line
# here has as many `(` as `)` and `[` as `]`, so only the line's last
# character decides it.
ENDS_OPEN = {c: f"        n = a {c}\n            x\n" for c in "-+*/%&|^<>=!?:,.~"}
ENDS_OPEN["("] = "        n = a) * (\n            x\n"
ENDS_OPEN["["] = "        n = a] * [\n            x\n"


@pytest.mark.parametrize("body", ENDS_OPEN.values(), ids=ENDS_OPEN.keys())
def test_a_line_ending_in_an_open_character_leaves_the_base_body(body):
    parsed, base = _body_of_f(body)
    assert parsed == base


# A line beginning with one of these characters continues the line before it.
BEGINS_AS_CONTINUATION = {c: f"        n = x\n            {c} y\n" for c in "-+*/%&|^<>=?:.,"}
BEGINS_AS_CONTINUATION[")"] = "        n = x\n            ) * (y\n"
BEGINS_AS_CONTINUATION["]"] = "        n = x\n            ] * [y\n"


@pytest.mark.parametrize("body", BEGINS_AS_CONTINUATION.values(), ids=BEGINS_AS_CONTINUATION.keys())
def test_a_line_beginning_as_a_continuation_leaves_the_base_body(body):
    parsed, base = _body_of_f(body)
    assert parsed == base


@pytest.mark.parametrize("body", [
    "        n = x +\n            1\n",
    "        n = x\n        return\n",
], ids=["line ending in an operator", "bare return"])
def test_a_crlf_body_outside_the_plain_shape_is_the_base_body(body):
    source = (HEAD + "    function f(x: uint256)\n" + body + SIBLING).replace("\n", "\r\n")
    assert _functions(source)["f"]["body"] == _base_body(source, "f")


@pytest.mark.parametrize("word", ["retry", "catcher", "unchecked_n"])
def test_a_marker_inside_a_longer_word_also_leaves_the_base_body(word):
    parsed, base = _body_of_f(f"        n = {word}\n")
    assert parsed == base


@pytest.mark.parametrize("word", ["iffy", "elsewhere", "format", "whilst", "done"])
def test_a_line_beginning_with_a_longer_word_than_an_opening_word_is_plain(word):
    parsed, _ = _body_of_f(f"        n = x\n        {word} = 1\n")
    assert parsed == f"n = x;\n        {word} = 1;"


@pytest.mark.parametrize("returns", ["-> uint256", "returns uint256"])
def test_a_return_type_after_the_signature_still_takes_the_layout(returns):
    source = HEAD + f"    function f(x: uint256) {returns}\n        n = x\n" + SIBLING
    assert _functions(source)["f"]["body"] == "n = x;"


def test_spaces_after_the_signature_still_take_the_layout():
    source = HEAD + "    function f(x: uint256)   \n        n = x\n" + SIBLING
    assert _functions(source)["f"]["body"] == "n = x;"


def test_text_after_the_signature_on_the_header_line_leaves_the_base_body():
    source = HEAD + "    function f(x: uint256) public\n        n = x\n" + SIBLING
    assert _functions(source)["f"]["body"] == _base_body(source, "f")


def test_a_marker_in_a_later_function_inside_the_base_body_leaves_the_base_body():
    source = HEAD + "    function f(x: uint256)\n        n = x\n    function g(x: uint256)\n        n = x;\n"
    fns = _functions(source)
    assert fns["f"]["body"] == _base_body(source, "f")
    assert fns["g"]["body"] == "n = x;"


def test_a_marker_after_the_next_column_0_line_does_not_reach_the_function():
    source = (HEAD + "    function f(x: uint256)\n        n = x\n" + SIBLING
              + "event Done(x: uint256)\n    function h(x: uint256)\n        n = x;\n")
    assert _functions(source)["f"]["body"] == "n = x;"


def test_a_marker_in_an_earlier_function_does_not_reach_a_later_one():
    source = HEAD + "    function f(x: uint256)\n        n = x;\n" + SIBLING
    assert _functions(source)["g"]["body"] == "n = x;"


def test_a_marker_in_each_function_leaves_each_base_body():
    source = (HEAD + "    function f(x: uint256)\n        n = x;\n"
              "    function g(x: uint256)\n        n = x;\n    function h(x: uint256)\n        n = x;\n")
    fns = _functions(source)
    assert [fns[k]["body"] for k in "fgh"] == [_base_body(source, k) for k in "fgh"]


def test_a_column_0_function_keeps_the_base_body():
    source = "contract C\nstate n: uint256\nfunction f(x: uint256)\n    n = x\nfunction g(x: uint256)\n    n = x\n"
    assert _functions(source)["f"]["body"] == _base_body(source, "f") == "n = x"


@pytest.mark.parametrize("before", ["", HEAD], ids=["at the start of the source", "on a later line"])
@pytest.mark.parametrize("width", [255, 256])
def test_the_text_before_function_is_read_only_when_under_256_characters(before, width):
    pad = " " * (width - len("payable "))
    source = (before + pad + "payable function f(x: uint256)\n" + pad + "    n = x\n" + SIBLING)
    assert source.index("function f") - len(before) == width
    f = _functions(source)["f"]
    if width < 256:
        assert (f["mutability"], f["body"]) == ("payable", "n = x;")
    else:
        assert (f["mutability"], f["body"]) == ("nonpayable", _base_body(source, "f"))


def test_an_indent_past_256_characters_leaves_the_base_body_and_reads_no_payable():
    pad = " " * 300
    source = HEAD + pad + "payable function f(x: uint256)\n" + pad + "    n = x\n"
    f = _functions(source)["f"]
    assert f["body"] == _base_body(source, "f")
    assert f["mutability"] == "nonpayable"


def test_only_the_lowercase_function_keyword_takes_the_layout():
    source = HEAD + "    def f(x: uint256)\n        n = x\n    Function g(x: uint256)\n        n = x\n"
    fns = _functions(source)
    assert fns["f"]["body"] == SourceParser._extract_pseudo_body(source, source.index(")") + 1)
    assert not fns["g"]["body"].endswith(";")


# ── where an indented function's body ends ───────────────────────────────────

def test_a_sibling_at_the_same_indent_ends_the_body():
    source = HEAD + "    function f(x: uint256)\n        n = x\n" + SIBLING
    assert _functions(source)["f"]["body"] == "n = x;"


def test_a_tab_indented_sibling_ends_a_tab_indented_body():
    source = "contract C\n\tfunction f(x: uint256)\n\t\tn = x\n\tfunction g(x: uint256)\n\t\tn = x\n"
    assert _functions(source)["f"]["body"] == "n = x;"


def test_a_payable_sibling_ends_the_body():
    source = HEAD + "    function f(x: uint256)\n        n = x\n    payable function g()\n        n = 1\n"
    assert _functions(source)["f"]["body"] == "n = x;"


def test_a_sibling_at_a_leading_part_of_the_indent_ends_the_body():
    source = HEAD + "        function f(x: uint256)\n            n = x\n" + SIBLING
    assert _functions(source)["f"]["body"] == "n = x;"


def test_a_line_beginning_with_a_longer_word_than_function_does_not_end_the_body():
    parsed, _ = _body_of_f("        n = x\n        functionCount = n\n")
    assert parsed == "n = x;\n        functionCount = n;"


@pytest.mark.parametrize("line", [
    "        function g(x: uint256)\n",
    "\tfunction g(x: uint256)\n",
    "    function g(\n",
    "    function g(\n        x: uint256)\n",
    "    payable function\n",
], ids=["deeper", "other indent characters", "signature without its closing parenthesis",
        "parameters over two lines", "no name"])
def test_any_other_next_function_line_leaves_the_base_body(line):
    source = HEAD + "    function f(x: uint256)\n        n = x\n" + line + "        n = 1\n"
    assert _functions(source)["f"]["body"] == _base_body(source, "f")


def test_a_column_0_line_still_ends_the_body():
    source = (HEAD + "    function f(x: uint256)\n        n = x\nevent Done(x: uint256)\n        n = 1\n"
              "    function g(x: uint256)\n        n = x\nevent Gone(x: uint256)\n")
    fns = _functions(source)
    assert fns["f"]["body"] == "n = x;"
    assert fns["g"]["body"] == "n = x;"


# ── the `;` each plain statement gets ────────────────────────────────────────

def test_each_non_blank_line_of_a_plain_body_gets_a_semicolon_and_blank_lines_stay():
    source = (HEAD + "    function f(x: uint256)\n        n = x\n\n        n = n + 1   \n"
              "    function g()\n        n = 1\n")
    assert _functions(source)["f"]["body"] == "n = x;\n\n        n = n + 1;"


def test_a_crlf_line_gets_its_semicolon_before_the_carriage_return():
    source = (HEAD + "    function f(x: uint256)\n        n = x\n        n = n + 1\n").replace("\n", "\r\n")
    assert _functions(source)["f"]["body"] == "n = x;\r\n        n = n + 1;"


# ── `payable` written before `function` ──────────────────────────────────────

def test_payable_before_function_makes_it_payable():
    assert _functions(HEAD + "    payable function f()\n        n = 1\n")["f"]["mutability"] == "payable"


def test_payable_before_a_column_0_function_makes_it_payable():
    assert _functions("contract C\npayable function f()\n    n = 1\n")["f"]["mutability"] == "payable"


def test_a_tab_between_payable_and_function_still_reads_payable():
    assert _functions(HEAD + "    payable\tfunction f()\n        n = 1\n")["f"]["mutability"] == "payable"


@pytest.mark.parametrize("source", [
    HEAD + '    function f()\n        s = "payable function g()"\n',
    HEAD + "    function f()\n        n = 1 // payable function g()\n",
    HEAD + "    function f()\n        n = 1 # payable function g()\n",
    HEAD + "    x = payable function g()\n        n = 1\n",
    "contract C\n\fpayable function g()\n    n = 1\n",
    "contract C\n\vpayable function g()\n    n = 1\n",
], ids=["inside a one-line string", "after //", "after #", "after other words",
        "after a form feed", "after a vertical tab"])
def test_payable_is_not_read_after_other_text_on_its_line(source):
    assert _functions(source)["g"]["mutability"] == "nonpayable"


@pytest.mark.parametrize("source", [
    HEAD + "    /* note */\n    payable function g()\n        n = 1\n",
    (HEAD + "    /* note */\n" + "    state k: uint256\n" * 20
     + "    payable function g()\n        n = 1\n"),
], ids=["on the line before", "more than 256 characters before"])
def test_payable_is_not_read_after_an_earlier_block_comment_opens(source):
    assert _functions(source)["g"]["mutability"] == "nonpayable"


def test_a_block_comment_after_the_function_does_not_stop_payable():
    source = HEAD + "    payable function g()\n        n = 1\nevent E(x: uint256)\n/* note */\n"
    assert _functions(source)["g"]["mutability"] == "payable"


@pytest.mark.parametrize("suffix, expected", [
    (" internal", ("internal", "nonpayable")),
    (" private", ("internal", "nonpayable")),
    (" view", ("public", "view")),
    (" pure", ("public", "pure")),
])
def test_payable_is_not_added_when_the_suffix_sets_visibility_or_mutability(suffix, expected):
    f = _functions(HEAD + f"    payable function f(x: uint256){suffix}\n        n = x\n")["f"]
    assert (f["visibility"], f["mutability"]) == expected


@pytest.mark.parametrize("suffix", [" public", " external", " returns uint256", " -> uint256"])
def test_payable_is_added_when_the_suffix_leaves_the_function_public_and_nonpayable(suffix):
    f = _functions(HEAD + f"    payable function f(x: uint256){suffix}\n        n = x\n")["f"]
    assert (f["visibility"], f["mutability"]) == ("public", "payable")


@pytest.mark.parametrize("word", ["view", "pure", "internal", "private", "external", "public"])
def test_other_words_before_function_are_not_read(word):
    f = _functions(HEAD + f"    {word} function f(x: uint256)\n        n = x\n")["f"]
    assert (f["visibility"], f["mutability"]) == ("public", "nonpayable")
