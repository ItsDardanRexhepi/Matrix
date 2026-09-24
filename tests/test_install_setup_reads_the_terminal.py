"""`curl … | bash` hands the setup wizard a terminal to read answers from.

Under the README's one-line install, bash reads install.sh from the pipe curl
writes into, and by the time main() launches the setup wizard that pipe has
been read to its end. The wizard inherited it as stdin, so its first prompt
read end-of-input: EOFError, and the install ended in a traceback.

These drive the pipe case for real. The launch is taken from install.sh as it
is: every definition above main(), then the line main() uses to start the
wizard. A stand-in setup.py asks one question. bash reads that script from a
pipe, exactly as it reads install.sh under curl. Nothing here clones, creates a
venv, or links into /usr/local/bin.
"""

from __future__ import annotations

import builtins
import importlib.util
import os
import re
import select
import shutil
import subprocess
import sys
import time
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent
INSTALL_SH = ROOT / "install.sh"

pytestmark = pytest.mark.skipif(shutil.which("bash") is None, reason="needs bash")

_WIZARD = """import sys
try:
    answer = input("Your name? ")
except EOFError:
    print("WIZARD-READ-END-OF-INPUT")
    sys.exit(3)
print("WIZARD-GOT " + answer)
"""


def _launch_script() -> str:
    """install.sh's definitions, then the line main() starts the wizard with."""
    text = INSTALL_SH.read_text(encoding="utf-8")
    head, sep, rest = text.partition("\nmain() {\n")
    assert sep, "install.sh no longer defines main()"
    body = rest.split("\n}\n", 1)[0]
    launch = [ln.strip() for ln in body.splitlines()
              if re.fullmatch(r"\s*(exec .*setup\.py.*|launch_setup)\s*", ln)]
    assert len(launch) == 1, f"expected one wizard launch in main(), found {launch}"
    return head + "\n" + launch[0] + "\n"


@pytest.fixture
def install_dir(tmp_path):
    d = tmp_path / "install"
    (d / ".venv" / "bin").mkdir(parents=True)
    python = d / ".venv" / "bin" / "python3"
    python.write_text(f'#!/bin/sh\nexec "{sys.executable}" "$@"\n', encoding="utf-8")
    python.chmod(0o755)
    (d / "setup.py").write_text(_WIZARD, encoding="utf-8")
    script = tmp_path / "install-piece.sh"
    script.write_text(_launch_script(), encoding="utf-8")
    return d, script


def _env(install: Path) -> dict:
    return {"MATRIX_DIR": str(install), "HOME": str(install.parent),
            "PATH": os.environ.get("PATH", "/usr/bin:/bin")}


def test_piped_with_no_terminal_it_stops_with_a_message(install_dir):
    """No controlling terminal (a CI job): no wizard that cannot be answered."""
    install, script = install_dir
    result = subprocess.run(
        ["bash"], input=script.read_text(encoding="utf-8"), env=_env(install),
        capture_output=True, text=True, timeout=60,
        start_new_session=True,  # no controlling terminal, like a CI runner
    )
    out = result.stdout + result.stderr
    assert "WIZARD-READ-END-OF-INPUT" not in out, (
        "the wizard was started on the exhausted pipe and met end-of-input:\n" + out)
    assert result.returncode != 0, out
    assert "no terminal" in out and "setup.py" in out, out


@pytest.mark.skipif(not hasattr(os, "fork"), reason="needs a pty")
def test_piped_with_a_terminal_the_wizard_reads_it(install_dir):
    """`curl … | bash` typed at a terminal: the answer typed there arrives."""
    import pty

    install, script = install_dir
    pid, master = pty.fork()
    if pid == 0:  # child: the pty is its controlling terminal; bash reads a pipe
        os.execve("/bin/sh", ["sh", "-c", f'cat "{script}" | bash'], _env(install))

    seen, answered = b"", False
    deadline = time.monotonic() + 60
    try:
        while time.monotonic() < deadline:
            ready, _, _ = select.select([master], [], [], 0.5)
            if not ready:
                continue
            try:
                chunk = os.read(master, 4096)
            except OSError:
                break
            if not chunk:
                break
            seen += chunk
            if not answered and b"Your name? " in seen:
                os.write(master, b"Neo\n")
                answered = True
    finally:
        os.close(master)
        _, status = os.waitpid(pid, 0)

    text = seen.decode(errors="replace")
    assert "WIZARD-READ-END-OF-INPUT" not in text, text
    assert "WIZARD-GOT Neo" in text, text
    assert os.WEXITSTATUS(status) == 0, text


def _wizard_module():
    spec = importlib.util.spec_from_file_location("matrix_setup_wizard_eof", ROOT / "setup.py")
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


def _end_of_input(*_a, **_k):
    raise EOFError


def test_the_wizards_prompt_at_end_of_input_exits_with_a_message(monkeypatch, capsys):
    """setup.py run with its input redirected or closed ends plainly, not in a traceback."""
    wizard = _wizard_module()
    monkeypatch.setattr(builtins, "input", _end_of_input)
    with pytest.raises(SystemExit) as exit_:
        wizard.ask("Gateway port", default="18790")
    assert exit_.value.code == 1
    assert "input ended" in capsys.readouterr().out


def test_a_channel_prompt_at_end_of_input_exits_with_a_message(monkeypatch, capsys):
    """setup/_shared.ask: SystemExit, which the wizard's channel loop does not
    catch and carry on past to its next question."""
    from setup import _shared

    monkeypatch.setattr(builtins, "input", _end_of_input)
    with pytest.raises(SystemExit) as exit_:
        _shared.ask("Bot token")
    assert exit_.value.code == 1
    assert "input ended" in capsys.readouterr().out
