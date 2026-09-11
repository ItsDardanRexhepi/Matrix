"""RUN-1 — the setup wizard must not destroy an existing config.

Reproduction from the audit:

    echo '{"SENTINEL":"do-not-overwrite"}' > openmatrix.config.json
    python setup.py          # accept defaults, answer "no" to the overwrite prompt
    cat openmatrix.config.json   # sentinel is gone

`write_config()` is correct in isolation — it checks, and returns False without
writing. The damage is done earlier: step 7 hands the in-memory config to the
nine channel modules and every one of them calls `save_config()`, which is an
unconditional `write_text`. "Web chat" defaults to *yes*, so this fires on the
default path with no unusual answers.

The operator is then told "Setup cancelled. Existing config preserved." over a
file that has already been replaced — and replaced with a step-7 snapshot, so
even the generated config is missing everything steps 8 and 9 would have added.

These tests drive the wizard's real code paths rather than piping stdin, so
they cannot pass by accident when the prompt sequence changes.
"""

from __future__ import annotations

import importlib
import json
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent
SENTINEL = {"SENTINEL": "do-not-overwrite"}

CHANNEL_MODULES = [
    "telegram", "discord", "slack", "email",
    "sms", "whatsapp", "web_chat", "ios_push", "webhook",
]


@pytest.fixture
def sandbox(tmp_path, monkeypatch):
    """Run inside a throwaway cwd holding a sentinel config.

    CONFIG_PATH is a cwd-relative constant, so chdir fully isolates this from
    the developer's real openmatrix.config.json.
    """
    monkeypatch.chdir(tmp_path)
    cfg = tmp_path / "openmatrix.config.json"
    cfg.write_text(json.dumps(SENTINEL) + "\n", encoding="utf-8")
    if str(ROOT) not in sys.path:
        sys.path.insert(0, str(ROOT))
    for name in list(sys.modules):
        if name == "setup" or name.startswith("setup."):
            del sys.modules[name]
    return cfg


def test_channel_modules_do_not_write_when_told_not_to_persist(sandbox, monkeypatch):
    """A channel module invoked BY THE WIZARD must not touch disk.

    This is the core of the fix: the wizard owns the write. Channel modules
    mutate the dict and hand it back. `persist=False` is how the wizard says so;
    the default stays True so `python setup_communications.py telegram` keeps
    working standalone.
    """
    before = sandbox.read_bytes()
    config: dict = {}

    for name in CHANNEL_MODULES:
        mod = importlib.import_module(f"setup.{name}")
        # Answer every prompt with the safest possible input.
        monkeypatch.setattr(mod, "ask", lambda *a, **k: "", raising=False)
        monkeypatch.setattr(mod, "yes_no", lambda *a, **k: False, raising=False)
        try:
            mod.configure(config, persist=False)
        except TypeError as exc:
            pytest.fail(
                f"setup.{name}.configure() does not accept persist=: {exc}. "
                "Without it the wizard cannot stop the module writing to disk."
            )
        except Exception:
            # A module bailing on missing credentials is fine. Writing is not.
            pass

        assert sandbox.read_bytes() == before, (
            f"setup.{name}.configure(persist=False) wrote to "
            "openmatrix.config.json. Channel modules must not touch disk when "
            "the wizard drives them — that is RUN-1's mechanism."
        )


def test_declining_overwrite_leaves_config_byte_identical(sandbox, monkeypatch):
    """The audit's exact reproduction, end to end.

    Drives the wizard's real steps 7-9 with defaults, then answers "no" at the
    overwrite prompt, and asserts the file is byte-for-byte what it was.
    """
    import setup as _  # noqa: F401  (package import guard)

    spec = importlib.util.spec_from_file_location("setup_main", ROOT / "setup.py")
    setup_main = importlib.util.module_from_spec(spec)
    sys.modules["setup_main"] = setup_main
    spec.loader.exec_module(setup_main)

    before = sandbox.read_bytes()

    # Every prompt takes its default; the overwrite prompt answers "no".
    def fake_ask(prompt, default="", options=None, **kwargs):
        if "verwrite" in prompt:
            return "no"
        return default

    monkeypatch.setattr(setup_main, "ask", fake_ask)
    monkeypatch.setattr(setup_main, "yes_no", lambda *a, **k: False, raising=False)

    # Each channel module resolves `ask`/`yes_no` in ITS OWN namespace, and
    # configure_communications swallows any exception a module raises. Without
    # patching the modules too, web_chat EOFs on its first prompt, the failure
    # is swallowed, save_config is never reached, and this test passes while
    # proving nothing. Patch them so the write path genuinely executes.
    for name in CHANNEL_MODULES:
        mod = importlib.import_module(f"setup.{name}")
        monkeypatch.setattr(mod, "ask", lambda *a, **k: "", raising=False)
        monkeypatch.setattr(mod, "yes_no", lambda *a, **k: True, raising=False)

    config: dict = {"gateway": {"host": "127.0.0.1", "port": 18790}}
    setup_main.configure_communications(config)

    assert sandbox.read_bytes() == before, (
        "step 7 (channel configuration) rewrote the config before the operator "
        "was ever asked about overwriting it"
    )

    wrote = setup_main.write_config(config)
    assert wrote is False, "write_config must report that it declined to write"
    assert sandbox.read_bytes() == before, (
        'the wizard printed "Existing config preserved" but the file changed'
    )
    assert json.loads(sandbox.read_text()) == SENTINEL


def test_overwrite_check_runs_before_any_work(sandbox, monkeypatch):
    """Declining must be possible BEFORE the wizard does nine steps of work.

    Ordering matters beyond tidiness: as long as the check comes last, every
    step before it is an opportunity for some future writer to land on disk
    first. Moving the gate to the top makes the safe path structural.
    """
    spec = importlib.util.spec_from_file_location("setup_main2", ROOT / "setup.py")
    setup_main = importlib.util.module_from_spec(spec)
    sys.modules["setup_main2"] = setup_main
    spec.loader.exec_module(setup_main)

    assert hasattr(setup_main, "confirm_overwrite_upfront"), (
        "setup.py must expose confirm_overwrite_upfront() and call it at the "
        "top of main(), so the operator is asked before any work is done."
    )

    monkeypatch.setattr(setup_main, "ask", lambda *a, **k: "no")
    assert setup_main.confirm_overwrite_upfront() is False

    monkeypatch.setattr(setup_main, "ask", lambda *a, **k: "yes")
    assert setup_main.confirm_overwrite_upfront() is True
