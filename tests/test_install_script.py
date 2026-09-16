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
    _exe(added / "matrix", "#!/bin/sh\necho ok\n")
    assert _add_path_to_rc(home, added).returncode == 0
    rc = _changed_rc(home)[0]
    out = subprocess.run(
        ["bash", "-c", f'. "{rc}"; command -v matrix'],
        env={"HOME": str(home), "PATH": "/usr/bin:/bin"},
        capture_output=True, text=True, timeout=30,
    )
    assert out.stdout.strip() == str(added / "matrix")


def test_rerunning_does_not_duplicate_and_says_how_to_undo(home, tmp_path):
    added = tmp_path / "local-bin"
    added.mkdir()
    first = _add_path_to_rc(home, added)
    _add_path_to_rc(home, added)
    rc = _changed_rc(home)[0]
    assert rc.read_text().count(str(added)) == 1
    assert str(rc) in first.stdout, "the operator is not told which file was changed"


def _install_cli(home: Path, tmp_path: Path, *, option: int, path: str) -> subprocess.CompletedProcess:
    """Run install.sh's REAL install_cli, with every function it calls.

    The one substitution: /usr/local/bin becomes a scratch directory, writable
    for Option 1 and absent for Option 2, so the test never links into the
    machine's /usr/local/bin. PATH is the caller's, because what PATH already
    holds is the gate under test.
    """
    install_dir = tmp_path / "the-matrix"
    (install_dir / ".venv" / "bin").mkdir(parents=True, exist_ok=True)
    system_bin = tmp_path / "usr-local-bin"
    if option == 1:
        system_bin.mkdir(exist_ok=True)
    text = INSTALL_SH.read_text(encoding="utf-8")
    helpers = "".join(
        _function(name) for name in re.findall(r"^(_[a-z_]+)\(\) \{", text, re.M)
    )
    body = _function("install_cli").replace("/usr/local/bin", str(system_bin))
    script = (
        "set -euo pipefail\n"
        'info() { echo "INFO $1"; }\nwarn() { echo "WARN $1"; }\n'
        f'INSTALL_DIR="{install_dir}"\n'
        + helpers + body + "install_cli\n"
    )
    env = {"HOME": str(home), "PATH": path}
    return subprocess.run(["bash", "-c", script], env=env, capture_output=True, text=True, timeout=30)


_RC_FILES = (".zshrc", ".bashrc", ".bash_profile", ".profile")


@pytest.mark.parametrize("option", [1, 2], ids=["usr-local-bin-writable", "links-into-local-bin"])
@pytest.mark.parametrize("rc_name", _RC_FILES)
@pytest.mark.parametrize("legacy", ["local-bin", "venv-bin"])
def test_a_legacy_prepend_is_reported_on_the_real_rerun_path(home, tmp_path, option, rc_name, legacy):
    """Round-1 review: the report existed but the re-run that needs it never reached it.

    install_cli called the legacy check only from _add_path_to_rc, and only when
    ~/.local/bin was NOT already on PATH. The legacy line is what PUTS it on the
    PATH that `curl | bash` inherits, and Option 1 skipped the call entirely.
    So every earlier install re-ran with no report. Driven here through
    install_cli itself, with PATH as the legacy line leaves it, the legacy line
    in each rc file an earlier version could have picked, both directories an
    earlier version wrote, and both link options.
    """
    local_bin = home / ".local" / "bin"
    venv_bin = tmp_path / "the-matrix" / ".venv" / "bin"
    directory, comment = (local_bin, "# The Matrix CLI") if legacy == "local-bin" else (venv_bin, "# The Matrix")
    rc = home / rc_name
    rc.write_text(f'# pre-existing\n\n{comment}\nexport PATH="{directory}:$PATH"\n')
    before = rc.read_bytes()

    result = _install_cli(home, tmp_path, option=option, path=f"{directory}:/usr/bin:/bin")

    assert result.returncode == 0, result.stderr
    warned = [ln for ln in result.stdout.splitlines() if ln.startswith("WARN")]
    assert any(str(rc) in ln and "FRONT" in ln for ln in warned), result.stdout
    assert any(f'export PATH="$PATH:{directory}"' in ln for ln in warned), (
        "the report does not give the replacement line:\n" + result.stdout
    )
    # Reported, not rewritten. (Option 2 may still APPEND its own line when
    # ~/.local/bin itself is not on PATH — that is not an edit of the legacy one.)
    assert rc.read_bytes().startswith(before), "the rc file's existing lines were edited in place"


def test_a_legacy_line_without_its_comment_is_still_reported(home, tmp_path):
    local_bin = home / ".local" / "bin"
    (home / ".bashrc").write_text(f'export PATH="{local_bin}:$PATH"\n')
    result = _install_cli(home, tmp_path, option=2, path=f"{local_bin}:/usr/bin:/bin")
    assert any("FRONT" in ln for ln in result.stdout.splitlines()), result.stdout


@pytest.mark.parametrize("rc_text", [
    'export PATH="$HOME/bin:$PATH"\n',                       # the operator's own prepend
    '\n# The Matrix CLI (delete this line and the next to undo)\nexport PATH="$PATH:{local_bin}"\n',
])
def test_what_is_not_an_earlier_installers_prepend_is_not_reported(home, tmp_path, rc_text):
    local_bin = home / ".local" / "bin"
    (home / ".bashrc").write_text(rc_text.format(local_bin=local_bin))
    result = _install_cli(home, tmp_path, option=2, path=f"/usr/bin:/bin:{local_bin}")
    assert result.returncode == 0, result.stderr
    assert not [ln for ln in result.stdout.splitlines() if ln.startswith("WARN")], result.stdout


def test_the_printed_undo_matches_the_line_written(home, tmp_path):
    """The rc comment said "delete this line and the next"; the printed text said
    "the two lines under" it, which read literally deletes an unrelated line.
    Following the printed instruction must restore the file's content."""
    added = tmp_path / "local-bin"
    added.mkdir()
    result = _add_path_to_rc(home, added)
    rc = _changed_rc(home)[0]
    assert "delete the '# The Matrix CLI' comment line and the line after it" in result.stdout
    lines = rc.read_text().splitlines()
    at = next(i for i, ln in enumerate(lines) if ln.startswith("# The Matrix CLI"))
    assert "delete this line and the next" in lines[at]
    kept = lines[:at] + lines[at + 2:]
    assert [ln for ln in kept if ln.strip()] == ["# pre-existing"]


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
    wrapper = _exe(venv_bin / "matrix", _wrapper())
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
