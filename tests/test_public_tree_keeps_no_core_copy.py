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
  3. no tracked file names anything of the core's beyond what the seam
     imports: a dotted name under the core's package (a module of the core,
     or a name reached through the package) and a private attribute of the
     gate class the seam exports, checked on every backend; and, with the
     core installed, any name the core's gate module or its gate class
     defines that the core's package root does not export, the seam does not
     import and this tree does not define itself

§CC, measured against the tree at the commit "The agent-tool boundary refuses
while the security gate is not up" (the tree before the copy was removed): with
the core installed both failed, each naming tests/test_twins_seam.py and
nothing else; on the no-op backend check 1 failed the same way and check 2 was
skipped. After, check 1 passed on both backends and check 2 passed with the
core installed (it is skipped on the no-op backend).

Check 2 used to read one of those word sets by its name in the core, which
named a private symbol here and watched only that set. It now reads every word
set the gate module defines. Measured in a scratch copy of the tree with a
restatement of another of the gate's word sets planted in a tracked file: the
check as it was passed, the check as it is failed and named the planted file.
Against this tree, both pass.

§CC for check 3, measured against the tree at the commit "Schema migration 8
merges the turns the platform numbered, and a failing migration step is always
rolled back" (the tree before it was added): with
the core installed it failed naming tests/test_twins_seam.py at four lines (the
core's gate module by its dotted name, twice; one of the gate module's word
sets by its name; a private attribute of the gate class) and
runtime/access_policy.py at one (a module of the core by its dotted name); on
the no-op backend it failed naming the same lines but the word set's. After
those two files were changed, it passes on both backends.
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


# ── 3. nothing of the core's is named here beyond what the seam imports ──────
#
# The seam imports what it needs from the core's package root; nothing else in
# this tree reaches into the core. A dunder attribute of the package (its file,
# its version) is not a reach into it.
_DOTTED_CORE_NAME = re.compile(r"(?<![A-Za-z0-9_.])morpheus_security\.(?!__)[A-Za-z_]")
_GATE_PRIVATE_ATTRIBUTE = re.compile(r"(?<![A-Za-z0-9_])MorpheusSecurity\._(?!_)")


def _names_this_tree_defines(files: list[Path]) -> set[str]:
    """Every name a tracked Python file defines: a module-level binding, a
    function or class anywhere, an attribute assigned on ``self``. A name this
    tree defines is its own (or a copy, which check 2 catches), not a reach
    into the core."""
    names: set[str] = set()
    for path in files:
        if path.suffix != ".py":
            continue
        try:
            tree = ast.parse(_read(path))
        except SyntaxError:
            continue
        for node in tree.body:
            if isinstance(node, ast.Assign):
                names.update(t.id for t in node.targets if isinstance(t, ast.Name))
            elif isinstance(node, ast.AnnAssign) and isinstance(node.target, ast.Name):
                names.add(node.target.id)
        for node in ast.walk(tree):
            if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef)):
                names.add(node.name)
            elif (isinstance(node, ast.Attribute) and isinstance(node.ctx, ast.Store)
                    and isinstance(node.value, ast.Name) and node.value.id == "self"):
                names.add(node.attr)
    return names


def _names_the_seam_imports() -> set[str]:
    tree = ast.parse(_read(ROOT / "runtime" / "security" / "__init__.py"))
    return {alias.name for node in ast.walk(tree)
            if isinstance(node, ast.ImportFrom) and node.module == "morpheus_security"
            for alias in node.names}


def _core_names_that_are_not_the_seams() -> set[str]:
    """Names the installed core's gate module defines at its top level, and
    private attributes of its gate class, that the core's package root does
    not export and the seam does not import. Found through the class the
    seam imports; none of them is written here."""
    import importlib

    import morpheus_security
    import runtime.security as seam

    module = importlib.import_module(seam.MorpheusSecurity.__module__)
    assert module.__name__.split(".")[0] != "runtime", "the seam is not bound to the core"
    tree = ast.parse(Path(module.__file__).read_text(encoding="utf-8"))
    names: set[str] = set()
    for node in tree.body:
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef)):
            names.add(node.name)
        elif isinstance(node, ast.Assign):
            names.update(t.id for t in node.targets if isinstance(t, ast.Name))
        elif isinstance(node, ast.AnnAssign) and isinstance(node.target, ast.Name):
            names.add(node.target.id)
    names.update(a for a in vars(seam.MorpheusSecurity) if a.startswith("_"))
    exported = set(getattr(morpheus_security, "__all__", ())) | _names_the_seam_imports()
    return {n for n in names if not n.startswith("__") and n not in exported}


def test_no_file_names_anything_of_the_core_beyond_what_the_seam_imports():
    files = _tracked_text_files()
    this_file = Path(__file__).resolve()
    patterns = [_DOTTED_CORE_NAME, _GATE_PRIVATE_ATTRIBUTE]
    if _core_package_dir() is not None:
        names = _core_names_that_are_not_the_seams() - _names_this_tree_defines(files)
        assert names, "the core's own names could not be read"
        patterns.append(re.compile(r"(?<![A-Za-z0-9_])(?:%s)(?![A-Za-z0-9_])"
                                   % "|".join(sorted(map(re.escape, names)))))
    named = sorted({f"{p.relative_to(ROOT)}:{n}"
                    for p in files if p.resolve() != this_file
                    for n, line in enumerate(_read(p).splitlines(), 1)
                    if any(pat.search(line) for pat in patterns)})
    assert not named, f"a file names something of the core's beyond what the seam imports: {named}"
