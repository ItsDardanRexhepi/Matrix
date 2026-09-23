"""The public tree keeps no copy of the security core's internals.

This repository may say what the security seam does and that the private core
decides. How the core decides (its vocabulary, its rules, its numbers) is the
core's, and it is not written here. tests/test_twins_seam.py did not keep to
that: without the core installed it fell back to a copy of the core's
vocabulary, and it cited the file and lines inside the core that the copy came
from. These checks keep either from coming back:

  1. no tracked file cites a location inside the core package (a core file and
     a line in it); checked on every backend
  2. with the core installed, no set, list or tuple literal in a tracked Python
     file, and no stretch of a tracked text file, restates most of any word
     set the core's gate module defines; the sets are read from the installed
     core, found without naming any of them (the module is the one the seam
     imports the gate class from), and never written here

§CC, measured against 2f503dd (the tree before the copy was removed): with the
core installed both failed, each naming tests/test_twins_seam.py and nothing
else; on the no-op backend check 1 failed the same way and check 2 was
skipped. After, check 1 passed on both backends and check 2 passed with the
core installed (it is skipped on the no-op backend).

Check 2 used to read one of those word sets by its name in the core, which
named a private symbol here and watched only that set. It now reads every word
set the gate module defines. Measured in a scratch copy of the tree with a
restatement of another of the gate's word sets planted in a tracked file: the
check as it was passed, the check as it is failed and named the planted file.
Against this tree, both pass.
"""

from __future__ import annotations

import ast
import re
import subprocess
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent
TEXT_SUFFIXES = {".py", ".md", ".txt", ".rst", ".json", ".yml", ".yaml", ".toml",
                 ".cfg", ".ini", ".sh", ".example", ".html", ".js", ".ts", ""}

# A citation of a location inside the core: its package name (or its gate
# module) followed by a line number, e.g. "<package>/<module>.py:<line>".
_PACKAGE_CITATION = re.compile(r"morpheus(?:_security)?(?:/[A-Za-z0-9_/]+)?\.py:[0-9]")


def _tracked_text_files() -> list[Path]:
    try:
        out = subprocess.run(["git", "ls-files", "-z"], cwd=ROOT, capture_output=True,
                             check=True, timeout=60).stdout.decode("utf-8", "replace")
        paths = [ROOT / p for p in out.split("\0") if p]
    except (OSError, subprocess.SubprocessError):
        paths = [p for p in ROOT.rglob("*") if ".git" not in p.parts]
    return [p for p in paths if p.is_file() and p.suffix in TEXT_SUFFIXES]


def _read(path: Path) -> str:
    try:
        return path.read_text(encoding="utf-8")
    except (UnicodeDecodeError, OSError):
        return ""


def test_no_file_cites_a_location_inside_the_core():
    cited = [f"{p.relative_to(ROOT)}:{n}"
             for p in _tracked_text_files()
             for n, line in enumerate(_read(p).splitlines(), 1)
             if _PACKAGE_CITATION.search(line)]
    core = _core_package_dir()
    if core is not None:
        # With the core installed, its module names are known: a citation of one
        # without the package prefix is caught too, unless this tree has a file
        # of the same name (then the citation is ambiguous and not the core's).
        ours = {p.name for p in ROOT.rglob("*.py")}
        names = sorted({p.name for p in core.rglob("*.py")} - ours)
        if names:
            by_name = re.compile(r"(?<![A-Za-z0-9_])(?:%s):[0-9]"
                                 % "|".join(re.escape(n) for n in names))
            cited += [f"{p.relative_to(ROOT)}:{n}"
                      for p in _tracked_text_files()
                      for n, line in enumerate(_read(p).splitlines(), 1)
                      if by_name.search(line)]
    cited = sorted(set(cited))
    assert not cited, f"a file cites a location inside the security core: {cited}"


def _core_package_dir() -> Path | None:
    try:
        import morpheus_security
    except ImportError:
        return None
    return Path(morpheus_security.__file__).resolve().parent


def _gate_word_sets() -> list[frozenset]:
    """Every set of five or more words the installed core's gate module
    defines, found without naming any: the module is the one the seam imports
    the gate class from."""
    import importlib

    import runtime.security as seam

    module = importlib.import_module(seam.MorpheusSecurity.__module__)
    assert module.__name__.split(".")[0] != "runtime", "the seam is not bound to the core"
    sets = {frozenset(v) for v in vars(module).values()
            if isinstance(v, (set, frozenset)) and len(v) >= 5
            and all(isinstance(w, str) for w in v)}
    return sorted(sets, key=sorted)


def _restatements(vocab: frozenset, files: list[Path]) -> list[str]:
    """Where a tracked file restates most of *vocab*: a set, list or tuple
    literal in Python, or any 800-character stretch of other text that quotes
    most of it as separate words."""
    most = max(5, (len(vocab) * 4) // 5)
    this_file = Path(__file__).resolve()
    copies = []
    for path in files:
        if path.resolve() == this_file:
            continue
        text = _read(path)
        if path.suffix == ".py":
            try:
                tree = ast.parse(text)
            except SyntaxError:
                tree = None
            for node in ast.walk(tree) if tree is not None else ():
                if isinstance(node, (ast.Set, ast.List, ast.Tuple)):
                    words = {e.value for e in node.elts
                             if isinstance(e, ast.Constant) and isinstance(e.value, str)}
                    if len(words & vocab) >= most:
                        copies.append(f"{path.relative_to(ROOT)}:{node.lineno}")
            continue
        for start in range(0, max(len(text), 1), 400):
            window = text[start:start + 800]
            quoted = set(re.findall(r"[\"'`]([a-z0-9_]+)[\"'`]", window))
            if len(quoted & vocab) >= most:
                copies.append(f"{path.relative_to(ROOT)}@{start}")
                break
    return copies


def test_no_file_restates_the_cores_vocabulary():
    pytest.importorskip("morpheus_security")
    sets = _gate_word_sets()
    assert sets, "the core's word sets could not be read"
    files = _tracked_text_files()
    copies = sorted({c for vocab in sets for c in _restatements(vocab, files)})
    assert not copies, f"the security core's vocabulary is restated at: {copies}"
