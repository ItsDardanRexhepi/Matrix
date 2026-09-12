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


# ── The .env writer: same gate, same atomicity ──────────────────────────────
#
# RUN-1 gave save_config() a persist flag and a temp-file-plus-rename write.
# update_env(), called on the very next line by eight of the nine channel
# modules, got neither: the wizard rewrote the operator's .env during step 7 no
# matter what was answered later, with the in-place write_text the fix had just
# removed from the config path. The first test above could not see it — every
# prompt answered "", so every module bailed before reaching update_env.

ENV_SENTINEL = "EXISTING_SECRET=keep-me\n"
ENV_WRITING_CHANNELS = [m for m in CHANNEL_MODULES if m != "web_chat"]


def _reaching_answers(tmp_path):
    """Answers that get every channel module past its early returns."""
    p8 = tmp_path / "AuthKey_TEST.p8"
    p8.write_text("-----BEGIN PRIVATE KEY-----\nstub\n-----END PRIVATE KEY-----\n")

    def answer(question, default="", **kwargs):
        q = question.lower()
        if "slack" in q:
            return "https://hooks.slack.com/services/T000/B000/XXXX"
        if "url" in q:
            return "https://example.invalid/hook"
        if ".p8" in q:
            return str(p8)
        if "port" in q:
            return "587"
        return "value-for-test"
    return answer


def _drive_to_update_env(monkeypatch, tmp_path, *, on_test=None):
    answer = _reaching_answers(tmp_path)
    for name in CHANNEL_MODULES:
        mod = importlib.import_module(f"setup.{name}")
        monkeypatch.setattr(mod, "ask", answer, raising=False)
        monkeypatch.setattr(mod, "yes_no", lambda *a, **k: True, raising=False)
        monkeypatch.setattr(
            mod, "test_channel_via_dispatcher",
            on_test or (lambda config, channel: {"status": "ok"}), raising=False,
        )
    telegram = importlib.import_module("setup.telegram")
    monkeypatch.setattr(telegram, "_verify_token", lambda token: {"username": "test_bot"})


def _load_wizard(name):
    spec = importlib.util.spec_from_file_location(name, ROOT / "setup.py")
    mod = importlib.util.module_from_spec(spec)
    sys.modules[name] = mod
    spec.loader.exec_module(mod)
    return mod


def test_channel_modules_do_not_write_env_when_told_not_to_persist(sandbox, monkeypatch, tmp_path):
    env = tmp_path / ".env"
    env.write_text(ENV_SENTINEL)
    _drive_to_update_env(monkeypatch, tmp_path)

    config: dict = {}
    for name in ENV_WRITING_CHANNELS:
        importlib.import_module(f"setup.{name}").configure(config, persist=False)
        assert env.read_text() == ENV_SENTINEL, (
            f"setup.{name}.configure(persist=False) rewrote .env — the wizard "
            "was told it owns the write"
        )
    # Not vacuous: every module really got as far as its update_env call.
    assert set(config["notifications"]) == set(ENV_WRITING_CHANNELS)


def test_declining_overwrite_leaves_env_byte_identical(sandbox, monkeypatch, tmp_path):
    env = tmp_path / ".env"
    env.write_text(ENV_SENTINEL)
    wizard = _load_wizard("setup_main_env_decline")
    monkeypatch.setattr(wizard, "ask", lambda prompt, default="", options=None, **k:
                        "no" if "verwrite" in prompt else "yes")
    _drive_to_update_env(monkeypatch, tmp_path)

    config: dict = {}
    wizard.configure_communications(config)
    assert env.read_text() == ENV_SENTINEL, "step 7 rewrote .env before anything was agreed"

    assert wizard.commit_setup(config) is False
    assert env.read_text() == ENV_SENTINEL, (
        'the wizard printed "Existing config preserved" over a rewritten .env'
    )


def test_accepted_setup_does_write_the_env_values(sandbox, monkeypatch, tmp_path):
    """The gate must defer the .env write, not lose it."""
    env = tmp_path / ".env"
    env.write_text(ENV_SENTINEL)
    wizard = _load_wizard("setup_main_env_accept")
    monkeypatch.setattr(wizard, "ask", lambda prompt, default="", options=None, **k: "yes")
    _drive_to_update_env(monkeypatch, tmp_path)

    config: dict = {}
    wizard.configure_communications(config)
    assert wizard.commit_setup(config) is True
    text = env.read_text()
    assert text.startswith(ENV_SENTINEL)
    for key in ("TELEGRAM_BOT_TOKEN", "DISCORD_WEBHOOK_URL", "SMTP_PASS", "APNS_KEY_ID"):
        assert f"{key}=" in text, f"{key} was collected but never reached .env"


def test_interrupted_channel_leaves_nothing_behind(sandbox, monkeypatch, tmp_path):
    """"Skipped." must be true: no half-configured channel in config or .env.

    Email writes its channel block and its .env values, THEN sends a test
    message. Ctrl-C there used to print "Skipped." over both.
    """
    env = tmp_path / ".env"
    env.write_text(ENV_SENTINEL)
    wizard = _load_wizard("setup_main_env_interrupt")
    monkeypatch.setattr(wizard, "ask", lambda prompt, default="", options=None, **k: "yes")

    def interrupt_email(config, channel):
        if channel == "email":
            raise KeyboardInterrupt
        return {"status": "ok"}
    _drive_to_update_env(monkeypatch, tmp_path, on_test=interrupt_email)

    config: dict = {}
    wizard.configure_communications(config)
    assert "email" not in config["notifications"], "a skipped channel was kept in the config"
    assert "discord" in config["notifications"], "rollback took more than the skipped channel"

    assert wizard.commit_setup(config) is True
    text = env.read_text()
    assert "SMTP_" not in text, "a skipped channel's credentials reached .env"
    assert "DISCORD_WEBHOOK_URL=" in text


def test_env_write_is_atomic(sandbox, tmp_path):
    """A write that fails part-way must leave the previous .env whole.

    An unencodable value makes the write raise after the file is opened —
    which, for an in-place write_text, is after it has been truncated.
    """
    from setup import _shared
    env = tmp_path / ".env"
    env.write_text(ENV_SENTINEL)
    with pytest.raises(UnicodeEncodeError):
        _shared.update_env({"BROKEN": "\udcff"})
    assert env.read_text() == ENV_SENTINEL, "a failed write destroyed the existing .env"
    assert sorted(p.name for p in tmp_path.iterdir()) == [".env", "openmatrix.config.json"], (
        "a failed write left a temp file behind"
    )


@pytest.mark.parametrize("writer", ["env", "config"])
def test_rewrite_keeps_owner_only_permissions(sandbox, tmp_path, writer):
    """Temp-file-plus-rename replaces the inode — and with it the mode.

    An operator who chmod 600'd the file holding their SMTP password got it
    back 644 from the first write. RUN-1's save_config already did this.
    """
    import stat
    from setup import _shared
    path = tmp_path / (".env" if writer == "env" else "openmatrix.config.json")
    path.write_text(ENV_SENTINEL if writer == "env" else "{}\n")
    path.chmod(0o600)
    if writer == "env":
        _shared.update_env({"A": "b"})
    else:
        _shared.save_config({"a": "b"})
    assert stat.S_IMODE(path.stat().st_mode) == 0o600


def test_new_secret_files_are_created_owner_only(sandbox, tmp_path):
    import stat
    from setup import _shared
    _shared.update_env({"SMTP_PASS": "hunter2"})
    assert stat.S_IMODE((tmp_path / ".env").stat().st_mode) == 0o600


@pytest.mark.parametrize("writer", ["env", "config"])
def test_rewrite_goes_through_a_symlinked_file(sandbox, tmp_path, writer):
    """A .env kept elsewhere and linked in must be updated, not replaced by a copy."""
    from setup import _shared
    name = ".env" if writer == "env" else "openmatrix.config.json"
    vault = tmp_path / "vault"
    vault.mkdir()
    real = vault / name
    real.write_text(ENV_SENTINEL if writer == "env" else "{}\n")
    link = tmp_path / name
    link.unlink(missing_ok=True)
    link.symlink_to(real)
    if writer == "env":
        _shared.update_env({"A": "b"})
        assert "A=b" in real.read_text()
    else:
        _shared.save_config({"a": "b"})
        assert json.loads(real.read_text()) == {"a": "b"}
    assert link.is_symlink(), f"{name} was replaced by a regular file"


def test_wizard_config_write_keeps_owner_only_permissions(sandbox, monkeypatch):
    """The wizard's own writer had the same rename-loses-the-mode window."""
    import stat
    sandbox.chmod(0o600)
    wizard = _load_wizard("setup_main_mode")
    monkeypatch.setattr(wizard, "ask", lambda *a, **k: "yes")
    assert wizard.write_config({"a": "b"}) is True
    assert stat.S_IMODE(sandbox.stat().st_mode) == 0o600
