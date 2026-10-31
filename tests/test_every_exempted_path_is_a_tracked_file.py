"""A file a test says it does not read is a file this repository has.

Several tests read every tracked page and document and leave a few out: the
legal copy, which only counsel changes, and the changelog, which records
history. Each keeps that list as a module-level set. An entry naming a file the
repository does not hold can never match anything, so it exempts nothing, and it
reads as though the file were here.

This reads every test module's exemption sets (module-level names containing
NOT_READ, LEFT_FOR, LEGAL, EXEMPT, SKIP or EXCLUDE) and requires each entry that
is a file path to be a tracked file.

What this cannot see: an exemption written inline in a condition rather than
kept in a named set, and an entry that is a directory prefix.
"""

from __future__ import annotations

import ast
import re
import subprocess
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
_SET_NAME = re.compile(r"NOT_READ|LEFT_FOR|LEGAL|EXEMPT|SKIP|EXCLUDE")
_A_PATH = re.compile(r"^[\w./-]+\.(?:md|html|py|json|txt|ya?ml|js|ts|sol|toml|sh)$")


def _exempted_paths(source: str) -> list[tuple[str, str]]:
    """(set name, entry) for every file-path entry of a module-level exemption set."""
    out = []
    for node in ast.parse(source).body:
        if not isinstance(node, (ast.Assign, ast.AnnAssign)):
            continue
        targets = node.targets if isinstance(node, ast.Assign) else [node.target]
        names = [t.id for t in targets if isinstance(t, ast.Name)]
        if not any(_SET_NAME.search(n) for n in names) or node.value is None:
            continue
        for const in ast.walk(node.value):
            if (isinstance(const, ast.Constant) and isinstance(const.value, str)
                    and _A_PATH.match(const.value)):
                out.append((names[0], const.value))
    return out


def test_the_reader_finds_exemption_sets():
    sample = ('_NOT_READ = {"CHANGELOG.md", "web/terms.html"}\n'
              '_LEFT_FOR_COUNSEL = {"web/gone.md"}\n'
              '_EXEMPT_METHODS = {"attest", "revoke"}\n'
              'PAGES = ["web/audit.html"]\n')
    assert _exempted_paths(sample) == [("_NOT_READ", "CHANGELOG.md"), ("_NOT_READ", "web/terms.html"),
                                       ("_LEFT_FOR_COUNSEL", "web/gone.md")]


def test_every_exempted_path_is_a_tracked_file():
    tracked = set(subprocess.check_output(["git", "ls-files"], cwd=ROOT, text=True).splitlines())
    problems, seen = [], 0
    for path in sorted((ROOT / "tests").glob("*.py")):
        for name, entry in _exempted_paths(path.read_text(encoding="utf-8")):
            seen += 1
            if entry not in tracked:
                problems.append(f"tests/{path.name}: {name} names {entry}, which is not a tracked file")
    assert seen, "no exemption set was found; the reader is looking at the wrong thing"
    assert not problems, "\n".join(problems)
