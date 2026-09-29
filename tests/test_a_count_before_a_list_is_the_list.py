"""A number stated before a list is the length of the list.

tests/test_the_security_layers_are_described_as_they_run.py opened "Three
statements had outlived the code they describe:" over four bullets, one added
after the count was written; tests/test_gas_sponsorship_is_described_as_it_signs.py
said "Two statements had drifted from the code:" over three, and
tests/test_refusal_survives_the_envelope.py "in three more places:" over four.

This reads every docstring in the tracked Python files and every tracked
Markdown document: a line that ends in a colon after a number word (two to
twelve), followed by a bulleted or numbered list, states the length of that
list, and has to equal it.

What this cannot see: a count written in digits, a count that is not directly
followed by its list, and a lead-in whose number counts something other than
the list (one that also names an ordinal, "two are fixed and the third is not",
or gives a range, "one or two of these", is left out).
"""

from __future__ import annotations

import ast
import re
import subprocess
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
_NUMBERS = {"two": 2, "three": 3, "four": 4, "five": 5, "six": 6, "seven": 7,
            "eight": 8, "nine": 9, "ten": 10, "eleven": 11, "twelve": 12}
_LEAD = re.compile(r"(?<!or )\b(" + "|".join(_NUMBERS) + r")\b ([A-Za-z-]+(?: [A-Za-z-]+){0,8}):[ \t]*$",
                   re.I)
_ORDINAL = re.compile(r"\b(?:first|second|third|fourth|fifth|sixth|last)\b", re.I)
_ITEM = r"(?:[*-]|\d+\.) "


def _counted_lists(text: str) -> list[tuple[int, int, str]]:
    """(stated number, items in the list after it, the lead-in line)."""
    lines = text.split("\n")
    found = []
    for i, line in enumerate(lines):
        lead = _LEAD.search(line)
        if not lead or _ORDINAL.search(lead.group(0)):
            continue
        j = i + 1
        while j < len(lines) and not lines[j].strip():
            j += 1
        first = re.match(r"^([ \t]*)" + _ITEM, lines[j]) if j < len(lines) else None
        if not first:
            continue
        indent, items = len(first.group(1)), 0
        item = re.compile(r"^[ \t]{%d}" % indent + _ITEM)
        while j < len(lines):
            current = lines[j]
            if not current.strip():
                k = j + 1
                while k < len(lines) and not lines[k].strip():
                    k += 1
                if k < len(lines) and item.match(lines[k]):
                    j = k
                    continue
                break
            if item.match(current):
                items += 1
            elif len(current) - len(current.lstrip()) <= indent:
                break
            j += 1
        found.append((_NUMBERS[lead.group(1).lower()], items, line.strip()))
    return found


def _texts():
    out = subprocess.check_output(["git", "ls-files", "*.py", "*.md"], cwd=ROOT, text=True)
    for rel in out.splitlines():
        path = ROOT / rel
        if rel == "CHANGELOG.md" or not path.is_file():
            continue
        text = path.read_text(encoding="utf-8")
        if rel.endswith(".md"):
            yield rel, text
            continue
        try:
            tree = ast.parse(text)
        except SyntaxError:
            continue
        for node in ast.walk(tree):
            if isinstance(node, (ast.Module, ast.ClassDef, ast.FunctionDef, ast.AsyncFunctionDef)):
                doc = ast.get_docstring(node, clean=False)
                if doc:
                    yield rel, doc


def test_the_reader_counts_a_list_and_its_continuations():
    text = ("Three statements had outlived the code they describe:\n\n"
            "  * the first, which runs\n    onto a second line;\n"
            "  * the second;\n\n  * the third;\n  * a fourth.\n\nAfter the list.\n")
    assert _counted_lists(text) == [(3, 4, "Three statements had outlived the code they describe:")]
    assert _counted_lists("Two modes:\n\n1. one\n2. two\n") == [(2, 2, "Two modes:")]
    assert _counted_lists("three evasions worked; two are fixed here and the third is not:\n\n"
                          "* a\n* b\n* c\n") == []
    assert _counted_lists("after any one or two of these were fixed:\n\n  1. a\n  2. b\n  3. c\n") == []


def test_every_count_before_a_list_is_the_length_of_the_list():
    wrong = [f"{rel}: {line!r} states {stated}, the list has {items}"
             for rel, text in _texts()
             for stated, items, line in _counted_lists(text) if stated != items]
    assert not wrong, "\n".join(wrong)
