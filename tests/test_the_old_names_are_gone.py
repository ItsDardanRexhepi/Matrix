"""The platform is The Matrix. The names it replaced must not come back.

0pnMatrx / OpenMatrix / opnmatrx became The Matrix, and matrix_server became the
Oracle Server. A rename is only finished if it stays finished, so this walks the
whole repository and fails on any reappearance.

Three categories are deliberately EXEMPT, because they are bound to things
outside this repository and renaming them would break the real world rather than
tidy it:

  * App Store bundle and product identifiers (opnmatrx.mtrx...). A product id
    cannot be changed once registered in App Store Connect; renaming one
    detaches existing subscribers from the entitlement they paid for.
  * The domain openmatrix-ai.com. A name is only a URL if it is owned.
  * Absolute filesystem paths that still resolve.

Those exemptions live in the name guard, a separate tool. When
MATRIX_NAME_GUARD points at it, this test runs it over the whole repository;
where it is not available the test is skipped rather than guessed at.

One spelling needs none of those exemptions, so it is swept here whether the
guard is present or not: the one with a zero (see
test_no_file_spells_the_old_name_with_a_zero).
"""
from __future__ import annotations

import os
import pathlib
import re
import subprocess
import sys

import pytest

REPO = pathlib.Path(__file__).resolve().parent.parent
_GUARD_PATH = os.environ.get("MATRIX_NAME_GUARD", "")
GUARD = pathlib.Path(_GUARD_PATH) if _GUARD_PATH else None


@pytest.mark.skipif(GUARD is None or not GUARD.exists(), reason="MATRIX_NAME_GUARD does not point at the name guard here")
def test_no_file_in_this_repository_carries_an_old_name():
    result = subprocess.run(
        [sys.executable, str(GUARD), str(REPO)],
        capture_output=True, text=True,
    )
    assert result.returncode == 0, (
        "the old names have reappeared:\n" + result.stdout + result.stderr)


def test_the_readme_introduces_the_platform_by_its_name():
    readme = (REPO / "README.md").read_text()
    assert readme.lstrip().startswith("# The Matrix"), readme[:80]
    for dead in ("0pnMatrx", "OpenMatrix"):
        assert dead not in readme, f"the README still says {dead}"


def test_the_quick_start_clones_and_enters_the_same_directory():
    """A rename that edits prose but leaves `cd <old name>` in the quick start
    hands a new user a command that cannot work."""
    readme = (REPO / "README.md").read_text()
    assert "cd TheMatrix" in readme
    assert "cd The Matrix" not in readme, "that is not a valid shell command"



#: The spelling with a zero names no bundle id and no domain. The guard
#: exempts it in two places, a checkout path on a machine and the
#: repository's former GitHub address, and neither belongs in a committed
#: file: the README clones the current address. So committed text needs no
#: exemption for it, and this sweep runs whether or not the guard is
#: installed. What can still carry it is the machine around the repository (a
#: checkout directory, a local config that records one), so the sweep reads
#: the files git would commit, not whatever else sits in the tree.
#:
#: Two files are held apart, by name, and only while they still carry it: the
#: privacy and terms pages the gateway serves from web/. They are legal text,
#: and a party's name in legal text is changed as legal text, not by a sweep.
#: Any other file, a new page in web/ included, fails here.
_ZERO_SPELLING = "0pnmatrx"
_LEGAL_PAGES_NOT_YET_RENAMED = ("web/privacy.html", "web/terms.html")
#: Used only where git is not available (an exported copy): directories that
#: are not this repository's own text.
_PRUNED = {".git", ".venv", "venv", "node_modules", "__pycache__",
           ".pytest_cache", ".mypy_cache", ".ruff_cache", "data"}


def _files_to_sweep():
    here = pathlib.Path(__file__).resolve()
    listed = subprocess.run(
        ["git", "ls-files", "-z", "--cached", "--others", "--exclude-standard"],
        cwd=REPO, capture_output=True,
    ) if (REPO / ".git").exists() else None
    if listed is not None and listed.returncode == 0:
        paths = [REPO / p for p in listed.stdout.decode().split("\0") if p]
    else:
        paths = []
        for root, dirs, files in os.walk(REPO):
            base = pathlib.Path(root)
            dirs[:] = [d for d in dirs if d not in _PRUNED
                       and base / d != REPO / "contracts" / "lib"]
            paths += [base / name for name in files if name != ".git"]
    for path in paths:
        if path.resolve() != here and path.is_file():
            yield path


def test_no_file_spells_the_old_name_with_a_zero():
    offenders = []
    for path in _files_to_sweep():
        rel = path.relative_to(REPO).as_posix()
        if rel in _LEGAL_PAGES_NOT_YET_RENAMED:
            continue
        try:
            text = path.read_text(encoding="utf-8")
        except (UnicodeDecodeError, OSError):
            continue
        for number, line in enumerate(text.splitlines(), 1):
            if _ZERO_SPELLING in line.lower():
                offenders.append(f"{rel}:{number}: {line.strip()[:100]}")
    assert not offenders, (
        "the old name is back, spelled with a zero:\n  " + "\n  ".join(offenders))


def test_a_page_held_apart_still_needs_to_be():
    # An exemption that exempts nothing is a door left open: once a page is
    # renamed, it leaves the list and the sweep covers it like any other file.
    # So does a page that is gone. This checked only pages that exist, so a
    # deleted page stayed on the list, and a new file later written at that
    # path would have been exempt without anyone deciding it should be.
    stale = []
    for rel in _LEGAL_PAGES_NOT_YET_RENAMED:
        page = REPO / rel
        if not page.is_file():
            stale.append(f"{rel} (no such file)")
        elif _ZERO_SPELLING not in page.read_text(encoding="utf-8").lower():
            stale.append(f"{rel} (no longer carries the old name)")
    assert not stale, (
        f"{stale}: remove them from _LEGAL_PAGES_NOT_YET_RENAMED so the sweep "
        "covers whatever is at that path")


# The name guard knows the old names themselves; it does not know what was
# coined from them. examples/09_full_user_journey.py staked a token named after
# the former name, and Trinity's credential examples in
# runtime/chat/intent_actions.py used a DID method coined from it, one the DID
# service never mints (it writes did:<method>:<network>:0x…, "matrix" by
# default). This runs without the guard. Legal copy is changed only by counsel
# and the changelog records history; neither is read.
_COINED = re.compile(r"\b0pn(?!matrx\b)[a-z0-9_]*|\bdid:0pn\b", re.I)
_LEFT_FOR_COUNSEL = {"CHANGELOG.md", "web/terms.html", "web/privacy.html"}


def test_the_coined_name_scan_sees_the_old_tokens():
    prefix = "0" + "pn"  # the former name's first letters, not written out whole here
    assert _COINED.search(f'"token": "{prefix}MTX",')
    assert _COINED.search(f'"example": "did:{prefix}:abc123"')
    assert not _COINED.search(f"{prefix}Matrx is the name the guard owns; "
                              "did:matrix:base:0xabc is not coined")


def test_no_tracked_file_carries_a_name_coined_from_the_old_one():
    out = subprocess.check_output(["git", "ls-files"], cwd=REPO, text=True)
    offenders = []
    for rel in out.splitlines():
        if rel in _LEFT_FOR_COUNSEL or rel.startswith("tests/"):
            continue
        path = REPO / rel
        if not path.is_file() or path.suffix not in (".py", ".md", ".html", ".js", ".ts",
                                                      ".json", ".yaml", ".yml", ".sh", ".txt"):
            continue
        for lineno, line in enumerate(path.read_text(encoding="utf-8", errors="replace")
                                      .splitlines(), 1):
            for m in _COINED.finditer(line):
                offenders.append(f"{rel}:{lineno}: {m.group(0)}")
    assert not offenders, "\n".join(offenders)
