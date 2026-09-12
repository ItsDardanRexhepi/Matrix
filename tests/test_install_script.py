"""install.sh — what the one-liner leaves behind in the operator's shell.

Driven, not grepped: each test extracts the real shell code from install.sh
(the function body, or the wrapper heredoc it writes), runs it under bash in a
throwaway HOME, and asserts on what a later shell actually resolves.

Nothing here runs install.sh's main(): it clones, creates a venv, and links
into /usr/local/bin when that is writable — none of which a test may do to the
machine it runs on.
"""

from __future__ import annotations

import os
import re
import shutil
import subprocess
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent
INSTALL_SH = ROOT / "install.sh"

pytestmark = pytest.mark.skipif(shutil.which("bash") is None, reason="needs bash")


def _function(name: str) -> str:
    text = INSTALL_SH.read_text(encoding="utf-8")
    m = re.search(rf"^{re.escape(name)}\(\) \{{\n.*?^\}}\n", text, re.S | re.M)
    assert m, f"install.sh no longer defines {name}()"
    return m.group(0)


def _wrapper() -> str:
    text = INSTALL_SH.read_text(encoding="utf-8")
    m = re.search(r"<< 'WRAPPER'\n(.*?)^WRAPPER\n", text, re.S | re.M)
    assert m, "install.sh no longer writes the CLI wrapper from a WRAPPER heredoc"
    return m.group(1)


def _exe(path: Path, body: str) -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(body, encoding="utf-8")
    path.chmod(0o755)
    return path


def _add_path_to_rc(home: Path, directory: Path) -> subprocess.CompletedProcess:
    script = (
        'info() { echo "INFO $1"; }\nwarn() { echo "WARN $1"; }\n'
        + _function("_add_path_to_rc")
        + f'_add_path_to_rc "{directory}"\n'
    )
    env = {"HOME": str(home), "PATH": os.environ.get("PATH", "/usr/bin:/bin")}
    return subprocess.run(["bash", "-c", script], env=env, capture_output=True, text=True, timeout=30)


@pytest.fixture
def home(tmp_path):
    h = tmp_path / "home"
    h.mkdir()
    # Both candidates exist, so whichever the platform branch picks is present.
    for rc in (".zshrc", ".bashrc", ".bash_profile", ".profile"):
        (h / rc).write_text("# pre-existing\n", encoding="utf-8")
    return h


def _changed_rc(home: Path) -> list[Path]:
    return [p for p in home.iterdir() if p.is_file() and p.read_text() != "# pre-existing\n"]


def test_added_directory_cannot_shadow_existing_tools(home, tmp_path):
    """A binary written later into the added directory must not win over /usr/bin.

    The exposure: the installer used to PREPEND ~/.local/bin in the rc file, so
    anything any process running as the user dropped there — a `pip install
    --user` of a typosquat, say — took precedence over the system git/python3/
    curl in every future shell.
    """
    added = tmp_path / "local-bin"
    system = tmp_path / "system-bin"
    _exe(added / "git", "#!/bin/sh\necho shadow\n")
    _exe(system / "git", "#!/bin/sh\necho system\n")

    result = _add_path_to_rc(home, added)
    assert result.returncode == 0, result.stderr
    changed = _changed_rc(home)
    assert len(changed) == 1, f"expected exactly one rc file written, got {changed}"

    later_shell = subprocess.run(
        ["bash", "-c", f'. "{changed[0]}"; command -v git'],
        env={"HOME": str(home), "PATH": f"{system}:/usr/bin:/bin"},
        capture_output=True, text=True, timeout=30,
    )
    resolved = later_shell.stdout.splitlines()[0]
    assert resolved == str(system / "git"), (
        f"after sourcing {changed[0].name}, `git` resolves to {resolved} — the "
        "installer's PATH entry shadows a tool that was already on PATH"
    )


def test_added_directory_is_still_reachable(home, tmp_path):
    """Appending must still make the CLI resolvable — the reason the line exists."""
    added = tmp_path / "local-bin"
    _exe(added / "openmatrix", "#!/bin/sh\necho ok\n")
    assert _add_path_to_rc(home, added).returncode == 0
    rc = _changed_rc(home)[0]
    out = subprocess.run(
        ["bash", "-c", f'. "{rc}"; command -v openmatrix'],
        env={"HOME": str(home), "PATH": "/usr/bin:/bin"},
        capture_output=True, text=True, timeout=30,
    )
    assert out.stdout.strip() == str(added / "openmatrix")


def test_rerunning_does_not_duplicate_and_says_how_to_undo(home, tmp_path):
    added = tmp_path / "local-bin"
    added.mkdir()
    first = _add_path_to_rc(home, added)
    _add_path_to_rc(home, added)
    rc = _changed_rc(home)[0]
    assert rc.read_text().count(str(added)) == 1
    assert str(rc) in first.stdout, "the operator is not told which file was changed"


def test_a_legacy_prepend_line_is_reported_not_left_silently(home, tmp_path):
    """Installs made before this fix carry the prepend line. Re-running must say so.

    It is reported rather than rewritten: rc files are often symlinks into a
    dotfiles repo, and an installer editing one in place is the more
    destructive failure if the match is ever wrong.
    """
    added = tmp_path / "local-bin"
    added.mkdir()
    for rc in home.iterdir():
        rc.write_text(f'# pre-existing\n\n# 0pnMatrx CLI\nexport PATH="{added}:$PATH"\n')
    result = _add_path_to_rc(home, added)
    assert "WARN" in result.stdout and "front" in result.stdout.lower(), result.stdout


def test_wrapper_resolves_a_link_chain_the_kernel_resolves(tmp_path):
    """The wrapper must terminate — and land where the kernel lands.

    The resolution loop had no bound and resolved each hop's directory with a
    LOGICAL `cd`, so a relative `..` in a link target was applied lexically
    while the kernel applied it physically. This chain executes fine (the
    kernel reaches the wrapper) but the old loop walks
    L/w -> L/../w2 -> w3 -> L/w forever.
    """
    project = tmp_path / "project"
    venv_bin = project / ".venv" / "bin"
    wrapper = _exe(venv_bin / "openmatrix", _wrapper())
    (venv_bin / "activate").write_text('export PATH="$(dirname "${BASH_SOURCE[0]}"):$PATH"\n')
    _exe(venv_bin / "python3", '#!/bin/sh\npwd -P\necho "$@"\n')

    base = tmp_path / "links"
    (base / "real" / "sub").mkdir(parents=True)
    (base / "L").symlink_to("real/sub")
    (base / "real" / "sub" / "w").symlink_to("../w2")
    (base / "real" / "w2").symlink_to("w3")
    (base / "real" / "w3").symlink_to(wrapper)
    (base / "w3").symlink_to("L/w")          # only the lexical walk reaches this

    try:
        out = subprocess.run(
            [str(base / "L" / "w"), "version"],
            env={"PATH": "/usr/bin:/bin", "HOME": str(tmp_path)},
            capture_output=True, text=True, timeout=10,
        )
    except subprocess.TimeoutExpired:
        pytest.fail("the CLI wrapper never finished resolving its own path")
    assert out.returncode == 0, out.stderr
    lines = out.stdout.splitlines()
    assert lines[0] == os.path.realpath(project), f"wrapper ran from {lines[0]}"
    assert lines[1] == "-m cli version"
