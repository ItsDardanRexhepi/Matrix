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
import os
import shutil
import subprocess
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
    # .gitignore: the writer ensures the secret files are ignored before writing.
    left = sorted(p.name for p in tmp_path.iterdir() if p.name != ".gitignore")
    assert left == [".env", "openmatrix.config.json"], (
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


def test_new_env_is_created_owner_only(sandbox, tmp_path):
    """.env's only readers run on the host as the operator (load_dotenv, compose
    interpolation); .dockerignore keeps it out of the image and nothing mounts it."""
    import stat
    from setup import _shared
    _shared.update_env({"SMTP_PASS": "hunter2"})
    assert stat.S_IMODE((tmp_path / ".env").stat().st_mode) == 0o600


@pytest.fixture
def umask():
    previous = os.umask(0o022)
    try:
        yield lambda value: os.umask(value)
    finally:
        os.umask(previous)


@pytest.mark.parametrize("operator_umask, expected", [(0o022, 0o644), (0o077, 0o600)])
@pytest.mark.parametrize("writer", ["save_config", "write_config"])
def test_new_config_is_created_the_way_the_docker_image_can_read_it(
        sandbox, monkeypatch, umask, writer, operator_umask, expected):
    """Round-1 review, REGRESSION. The shared writer created a NEW config 600.

    docker-compose.yml bind-mounts ./openmatrix.config.json read-only into an
    image running as uid 1000 (Dockerfile `useradd --uid 1000`, `USER opnmatrx`),
    and gateway/server.py load_config exits 1 on an unreadable config. So a
    config the wizard created as root on a VPS — or as any uid but 1000 — stopped
    the documented Docker deploy from starting, where the write_text it replaced
    created it 644 and it started. A new config now gets what write_text, or a
    `cp` of the .example, would give it: the operator's umask decides. An
    existing file keeps its own mode (test_rewrite_keeps_owner_only_permissions).
    """
    import stat
    sandbox.unlink()
    umask(operator_umask)
    if writer == "save_config":
        from setup import _shared
        _shared.save_config({"a": "b"})
    else:
        wizard = _load_wizard("setup_main_new_config_mode")
        monkeypatch.setattr(wizard, "ask", lambda *a, **k: pytest.fail("no file existed to ask about"))
        assert wizard.write_config({"a": "b"}) is True
    assert stat.S_IMODE(sandbox.stat().st_mode) == expected, (
        f"a new config from {writer} under umask {operator_umask:03o} is not what write_text "
        "would have created; at 600 the uid-1000 Docker image cannot read a config written by another uid"
    )


def test_every_secret_write_states_its_new_file_mode():
    """Which readers a new file must admit is a per-file decision. The writer
    has no default for it, so a new caller cannot inherit one by accident."""
    import inspect
    from setup import _shared
    param = inspect.signature(_shared._atomic_write_text).parameters["new_file_mode"]
    assert param.default is inspect.Parameter.empty
    assert param.kind is inspect.Parameter.KEYWORD_ONLY


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


# ── .gitignore: both branches must protect both secret files ────────────────
#
# setup_gitignore() had two branches that disagreed. Creating a .gitignore
# wrote `.env`; amending an existing one checked for and appended only
# `openmatrix.config.json`. The common case is the amend branch — nearly every
# project already has a .gitignore — so the file the channel wizards put
# Telegram/SMTP/Twilio credentials in was never ensured ignored. The verdict
# below is git's own, not a string search of the file.

GIT = shutil.which("git")

# Git matches .gitignore patterns caselessly when core.ignorecase is true, and
# `git init` sets it true on macOS (APFS) and Windows, the platforms install.sh
# and the README target, while Linux CI gets false. A verdict taken under only
# the runner's own setting passes `!.ENV` on Linux and fails it on a Mac, so
# every verdict below is taken under BOTH, pinned on the command line.
IGNORECASE = ("true", "false")

# The four pathspec switches an operator can leave in the environment. Each
# changes how git reads a pathspec, and setup_gitignore's git calls pass
# pathspecs of their own: with GIT_LITERAL_PATHSPECS the `:(glob)*` that lists
# the index entries is a literal name matching nothing, and each of the other
# three makes check-ignore or ls-files die ("pathspec magic not supported by
# this command", "'literal' and 'glob' are incompatible"), which turned git's
# whole verdict into one "Could not ask git" line.
PATHSPEC_ENV = ("GIT_LITERAL_PATHSPECS", "GIT_GLOB_PATHSPECS",
                "GIT_NOGLOB_PATHSPECS", "GIT_ICASE_PATHSPECS")


def _git_ignores(repo: Path, rel: str, ignorecase: str, *, index: bool = False) -> bool:
    """Git's verdict. With index=True a TRACKED file counts as not ignored, which
    is what it is to `git commit -a`: ignore rules never apply to a tracked file."""
    return subprocess.run(
        [GIT, "-c", f"core.ignorecase={ignorecase}",
         "-C", str(repo), "check-ignore", *([] if index else ["--no-index"]), "-q", rel],
        capture_output=True,
        # The developer's global excludes must not answer for the file.
        env={**os.environ, "GIT_CONFIG_GLOBAL": os.devnull, "GIT_CONFIG_NOSYSTEM": "1"},
    ).returncode == 0


def _isolated_wizard(name, monkeypatch):
    """The wizard with its warn()/success() recorded, and the git it may run
    itself blind to the developer's global and system excludes too."""
    monkeypatch.setenv("GIT_CONFIG_GLOBAL", os.devnull)
    monkeypatch.setenv("GIT_CONFIG_NOSYSTEM", "1")
    wizard = _load_wizard(name)
    said = {"warn": [], "success": []}
    monkeypatch.setattr(wizard, "warn", lambda text: said["warn"].append(text))
    monkeypatch.setattr(wizard, "success", lambda text: said["success"].append(text))
    return wizard, said


@pytest.mark.skipif(GIT is None, reason="needs git for the ignore verdict")
@pytest.mark.parametrize("existing", [
    None,                                            # create branch
    "openmatrix.config.json\n",                      # amend branch, the finding
    "node_modules/\n.env.example\n",                 # substring trap: `.env` in `.env.example`
    "# openmatrix.config.json\n# .env\n",            # mentioned only in comments
    ".env\nopenmatrix.config.json\n!.env\n",         # re-included later in the file
    # Round-1 review: the helper said "covered" and appended nothing, and git
    # still committed the file. Git keeps leading whitespace (and tabs) as part
    # of the pattern, and any later negation whose pattern can match — not only
    # the literal `!.env` — re-includes it.
    "openmatrix.config.json\n  .env\n",              # leading spaces: pattern is "  .env"
    "openmatrix.config.json\n\t.env\n",              # leading tab
    ".env\t\nopenmatrix.config.json\n",              # trailing tab is NOT stripped by git
    "openmatrix.config.json\n.env\n!.env*\n",        # wildcard negation
    "openmatrix.config.json\n.env\n!**/.env\n",      # double-star negation
    "openmatrix.config.json\n.env\n!*\n",            # negate-everything (both files)
    "openmatrix.config.json\n.env\n!.e[n]v\n",       # bracket negation
    "openmatrix.config.json\n.env\n!.env \n",        # negation with a trailing space git strips
    "openmatrix.config.json\r\n.env\r\n!.env\r\n",   # CRLF file: git strips the \r
    "openmatrix.config.json\n.env\n!\\.env\n",       # escaped negation
    "!.env\r.env\nopenmatrix.config.json\n",         # lone CR: one literal negation to git
    # Round-2 review: a literal negation was ruled out by a case-SENSITIVE
    # compare, but under core.ignorecase=true git re-includes .env for `!.ENV`.
    "openmatrix.config.json\n.env\n!.ENV\n",         # case-variant negation
    "openmatrix.config.json\n.env\n!/.Env\n",        # anchored, mixed case
    ".env\nopenmatrix.config.json\n!OPENMATRIX.CONFIG.JSON\n",
    ".env\nopenmatrix.config.json\n!OpenMatrix.config.json\n",
    "OPENMATRIX.CONFIG.JSON\n.ENV\n",               # covers only caselessly
    # Round-3 review: git reads each pattern as a C string, so a NUL ends it.
    "openmatrix.config.json\n.env\n!.env\x00junk\n",  # to git: `!.env`
    "openmatrix.config.json\n.env\n!.ENV\x00\n",      # to git: `!.ENV`
    ".env\r\x00\nopenmatrix.config.json\n",          # CR not before LF: `.env<CR>`, covers nothing
    "\ufeff.env\nopenmatrix.config.json\n",          # git skips a leading UTF-8 BOM
])
def test_setup_gitignore_ignores_both_secret_files(sandbox, monkeypatch, existing):
    repo = sandbox.parent
    subprocess.run([GIT, "init", "-q", str(repo)], check=True, capture_output=True)
    if existing is not None:
        (repo / ".gitignore").write_bytes(existing.encode())
    wizard, said = _isolated_wizard("setup_main_gitignore", monkeypatch)
    wizard.setup_gitignore()
    for ignorecase in IGNORECASE:
        for secret in ("openmatrix.config.json", ".env"):
            assert _git_ignores(repo, secret, ignorecase), (
                f"after setup_gitignore(), git (core.ignorecase={ignorecase}) would "
                f"commit {secret} (starting .gitignore: {existing!r})"
            )
    assert not said["warn"], f"warned although git ignores both: {said['warn']}"


# Round-3 review: the helper read .gitignore through a symlink, and git has not
# followed an in-tree .gitignore symlink since 2.32; it skips a pattern file of
# 100 MiB or more; it cannot read a directory or a file it may not open. In each
# case the helper counted lines git never reads, said nothing, and git staged
# .env. Appending cannot help (the write would land where git does not look),
# so the requirement is: every secret git would commit is named in a warning,
# nothing is written through or into the file git skips, and nothing says
# ".gitignore created/updated".
UNREAD_GITIGNORE = ["symlink", "dangling-symlink", "directory", "oversized", "unreadable"]
PATTERN_MAX_FILE_SIZE = 100 * 1024 * 1024   # git: dir.c, `size >= PATTERN_MAX_FILE_SIZE` is skipped


@pytest.mark.skipif(GIT is None, reason="needs git for the ignore verdict")
@pytest.mark.parametrize("kind", UNREAD_GITIGNORE)
def test_setup_gitignore_warns_when_git_will_not_read_it(sandbox, monkeypatch, kind):
    repo = sandbox.parent
    subprocess.run([GIT, "init", "-q", str(repo)], check=True, capture_output=True)
    listing = b"openmatrix.config.json\n.env\n"
    gitignore = repo / ".gitignore"
    elsewhere = repo / "dotfiles" / "gitignore"
    elsewhere.parent.mkdir()
    if kind == "symlink":
        elsewhere.write_bytes(listing)
        gitignore.symlink_to(elsewhere)
    elif kind == "dangling-symlink":
        gitignore.symlink_to(elsewhere)
    elif kind == "directory":
        gitignore.mkdir()
    elif kind == "oversized":
        with open(gitignore, "wb") as f:     # sparse: both entries, then NULs to the limit
            f.write(listing + b"#")
            f.truncate(PATTERN_MAX_FILE_SIZE)
    elif kind == "unreadable":
        if hasattr(os, "geteuid") and os.geteuid() == 0:
            pytest.skip("root reads a mode-000 file")
        gitignore.write_bytes(listing)
        gitignore.chmod(0)
    (repo / ".env").write_text("TOKEN=real\n")
    before = (elsewhere.read_bytes() if elsewhere.exists() else None,
              gitignore.is_symlink(), gitignore.is_dir(), os.lstat(gitignore).st_size)

    wizard, said = _isolated_wizard("setup_main_gitignore_unread", monkeypatch)
    try:
        wizard.setup_gitignore()
        # Git's verdict must be taken while the file is still in that state.
        committable = {s for ic in IGNORECASE for s in ("openmatrix.config.json", ".env")
                       if not _git_ignores(repo, s, ic, index=True)}
    finally:
        if kind == "unreadable":
            gitignore.chmod(0o644)
    if not committable:
        pytest.skip(f"this git reads a {kind} .gitignore, so nothing is committable")
    unwarned = [s for s in sorted(committable) if not any(s in w for w in said["warn"])]
    assert not unwarned, (
        f"{kind} .gitignore: git would commit {unwarned} and setup_gitignore() "
        f"did not say so (warnings: {said['warn']}, successes: {said['success']})"
    )
    assert not said["success"], f"claimed success over a {kind} .gitignore: {said['success']}"
    after = (elsewhere.read_bytes() if elsewhere.exists() else None,
             gitignore.is_symlink(), gitignore.is_dir(), os.lstat(gitignore).st_size)
    assert after == before, f"setup_gitignore() wrote to a {kind} .gitignore git does not read"

    # The file check alone must say it too: with no git verdict to be had (no
    # git on PATH at setup time, or not yet a repository), both names are warned.
    if kind == "unreadable":
        gitignore.chmod(0)
    monkeypatch.setattr(wizard, "_git_verdict", lambda names: None)
    said["warn"].clear()
    try:
        wizard.setup_gitignore()
    finally:
        if kind == "unreadable":
            gitignore.chmod(0o644)
    assert all(any(s in w for w in said["warn"]) for s in ("openmatrix.config.json", ".env")), said


@pytest.mark.skipif(GIT is None, reason="needs git for the ignore verdict")
@pytest.mark.parametrize("kind", ["read-only", "append-would-reach-the-size-limit"])
def test_setup_gitignore_warns_when_it_cannot_add_the_lines(sandbox, monkeypatch, kind):
    """Git reads this .gitignore, but the missing line cannot usefully go in: the
    file is read-only (the wizard used to crash), or the append would take it to
    the size git skips (the wizard used to append, say "updated", and leave git
    reading none of the file)."""
    repo = sandbox.parent
    subprocess.run([GIT, "init", "-q", str(repo)], check=True, capture_output=True)
    gitignore = repo / ".gitignore"
    with open(gitignore, "wb") as f:
        f.write(b"openmatrix.config.json\n#")
        if kind != "read-only":
            f.truncate(PATTERN_MAX_FILE_SIZE - 16)   # sparse; the append is longer than 16
    if kind == "read-only":
        if hasattr(os, "geteuid") and os.geteuid() == 0:
            pytest.skip("root writes a mode-444 file")
        gitignore.chmod(0o444)
    size = gitignore.stat().st_size
    wizard, said = _isolated_wizard("setup_main_gitignore_cannot_add", monkeypatch)
    try:
        wizard.setup_gitignore()
        committable = {s for ic in IGNORECASE for s in ("openmatrix.config.json", ".env")
                       if not _git_ignores(repo, s, ic, index=True)}
    finally:
        gitignore.chmod(0o644)
    assert committable, "the scenario must leave something committable"
    unwarned = [s for s in sorted(committable) if not any(s in w for w in said["warn"])]
    assert not unwarned, f"{kind}: git would commit {unwarned} unannounced ({said})"
    assert not said["success"], f"{kind}: claimed success: {said['success']}"
    assert gitignore.stat().st_size == size


def test_setup_gitignore_warns_when_it_cannot_create_the_file(sandbox, monkeypatch):
    """The create branch opened .gitignore unguarded, so a directory it may not
    write in crashed the wizard instead of saying the secrets are unprotected.
    Now that the check runs before the first secret is written, a crash there
    would also lose the operator's answers."""
    if hasattr(os, "geteuid") and os.geteuid() == 0:
        pytest.skip("root writes into a mode-555 directory")
    project = sandbox.parent / "project"
    project.mkdir()
    monkeypatch.chdir(project)
    wizard, said = _isolated_wizard("setup_main_gitignore_cannot_create", monkeypatch)
    project.chmod(0o555)
    try:
        wizard.setup_gitignore()
    finally:
        project.chmod(0o755)
    assert all(any(s in w for w in said["warn"]) for s in ("openmatrix.config.json", ".env")), said
    assert not said["success"], said


@pytest.mark.skipif(GIT is None, reason="needs git for the ignore verdict")
def test_setup_gitignore_warns_about_a_tracked_secret(sandbox, monkeypatch):
    """Ignore rules never apply to a tracked file: a .env already in the index is
    committed on the next `git commit -a` however well .gitignore lists it."""
    repo = sandbox.parent
    subprocess.run([GIT, "init", "-q", str(repo)], check=True, capture_output=True)
    (repo / ".gitignore").write_text("openmatrix.config.json\n.env\n")
    (repo / ".env").write_text("TOKEN=real\n")
    subprocess.run([GIT, "-C", str(repo), "add", "-f", ".env"], check=True, capture_output=True)
    wizard, said = _isolated_wizard("setup_main_gitignore_tracked", monkeypatch)
    wizard.setup_gitignore()
    assert not _git_ignores(repo, ".env", "true", index=True)     # the scenario is real
    assert any(".env" in w and "git rm --cached" in w for w in said["warn"]), said["warn"]
    assert not any("openmatrix.config.json" in w for w in said["warn"]), said["warn"]


def _filesystem_ignores_case(directory: Path) -> bool:
    probe = directory / "case-probe-a"
    probe.write_text("")
    try:
        return (directory / "CASE-PROBE-A").exists()
    finally:
        probe.unlink()


# Round-4 review: `git check-ignore` looks a name up in the index case-
# SENSITIVELY. With `.ENV` tracked and .gitignore listing `.env`, it reports
# `.env` ignored, yet on a case-insensitive filesystem (the macOS default) the
# wizard's write to .env lands in the tracked .ENV and `git commit -a` commits it.
@pytest.mark.skipif(GIT is None, reason="needs git for the ignore verdict")
@pytest.mark.parametrize("pathspec_env", [None, *PATHSPEC_ENV])
@pytest.mark.parametrize("ignorecase", IGNORECASE)
def test_setup_gitignore_warns_about_a_secret_tracked_under_another_case(
        sandbox, monkeypatch, ignorecase, pathspec_env):
    repo = sandbox.parent
    if not _filesystem_ignores_case(repo):
        pytest.skip("case-sensitive filesystem: .ENV and .env are different files here")
    if pathspec_env:            # an operator's environment must not blind the lookup
        monkeypatch.setenv(pathspec_env, "1")
    subprocess.run([GIT, "init", "-q", str(repo)], check=True, capture_output=True)
    subprocess.run([GIT, "-C", str(repo), "config", "core.ignorecase", ignorecase],
                   check=True, capture_output=True)
    sandbox.unlink()
    (repo / ".gitignore").write_text("openmatrix.config.json\n.env\n")
    (repo / ".ENV").write_text("TOKEN=old\n")
    (repo / "OpenMatrix.config.json").write_text("{}\n")
    subprocess.run([GIT, "-C", str(repo), "add", "-f", ".ENV", "OpenMatrix.config.json"],
                   check=True, capture_output=True)
    wizard, said = _isolated_wizard("setup_main_gitignore_tracked_case", monkeypatch)
    wizard.setup_gitignore()
    for tracked in (".ENV", "OpenMatrix.config.json"):
        assert any(f"git rm --cached {tracked}" in w for w in said["warn"]), (
            f"core.ignorecase={ignorecase}: {tracked} is tracked and is the file the "
            f"wizard writes, and nothing said so (warnings: {said['warn']})"
        )


@pytest.mark.skipif(GIT is None, reason="needs git for the ignore verdict")
@pytest.mark.parametrize("pathspec_env", PATHSPEC_ENV)
@pytest.mark.parametrize("scenario", ["tracked", "unlisted"])
def test_git_verdict_is_not_blinded_by_a_pathspec_switch_in_the_environment(
        sandbox, monkeypatch, pathspec_env, scenario):
    """8a232c7 dropped GIT_LITERAL_PATHSPECS from git's environment, with which
    `:(glob)*` matches nothing, and left the other three switches. Each of them
    made check-ignore or ls-files die, and git's whole verdict — a tracked
    secret, or one no rule ignores — became a single "Could not ask git" line.
    On any filesystem: the tracked secret here is spelled exactly."""
    repo = sandbox.parent
    subprocess.run([GIT, "init", "-q", str(repo)], check=True, capture_output=True)
    sandbox.unlink()
    if scenario == "tracked":
        (repo / ".gitignore").write_text("openmatrix.config.json\n.env\n")
        (repo / ".env").write_text("TOKEN=real\n")
        subprocess.run([GIT, "-C", str(repo), "add", "-f", ".env"], check=True, capture_output=True)
        expected = {".env": [".env"]}
    else:
        (repo / ".gitignore").write_text("__pycache__/\n*.pyc\nnode_modules/\n")
        expected = {"openmatrix.config.json": [], ".env": []}
    monkeypatch.setenv("GIT_CONFIG_GLOBAL", os.devnull)
    monkeypatch.setenv("GIT_CONFIG_NOSYSTEM", "1")
    monkeypatch.setenv(pathspec_env, "1")
    from setup import _gitignore
    infos = []
    verdict = _gitignore.git_verdict(_gitignore.SECRET_FILES, info=infos.append)
    assert verdict == expected, (pathspec_env, verdict, infos)
    assert not infos, (pathspec_env, infos)


def test_setup_gitignore_warns_when_the_new_file_cannot_be_written(sandbox, monkeypatch):
    """The create branch guarded the open but not the write, so a disk that
    filled between them raised out of the check — which now runs before the
    first secret is written, taking the operator's answers with it — and left
    an empty .gitignore behind. Same class as the mode-555 directory above."""
    import errno
    sandbox.unlink()
    wizard, said = _isolated_wizard("setup_main_gitignore_cannot_write", monkeypatch)
    real_fdopen = os.fdopen

    class _FullDisk:
        def __init__(self, f):
            self._f = f
        def write(self, _text):
            raise OSError(errno.ENOSPC, os.strerror(errno.ENOSPC))
        def __enter__(self):
            return self
        def __exit__(self, *exc):
            self._f.close()
            return False

    def fdopen(fd, mode="r", *args, **kwargs):
        f = real_fdopen(fd, mode, *args, **kwargs)
        return _FullDisk(f) if "w" in mode else f
    monkeypatch.setattr(os, "fdopen", fdopen)
    wizard.setup_gitignore()                                   # must not raise
    assert not Path(".gitignore").exists(), "an empty .gitignore was left behind"
    assert all(any(s in w for w in said["warn"]) for s in ("openmatrix.config.json", ".env")), said
    assert not said["success"], said


@pytest.mark.skipif(GIT is None, reason="needs git for the ignore verdict")
def test_git_verdict_survives_undecodable_git_output(sandbox, monkeypatch):
    """git echoes paths in its errors, and a path need not be UTF-8. The check
    ran after the config was written, so a decode error crashed the wizard
    mid-commit."""
    repo = sandbox.parent
    subprocess.run([GIT, "init", "-q", str(repo)], check=True, capture_output=True)
    wizard, said = _isolated_wizard("setup_main_gitignore_undecodable", monkeypatch)
    monkeypatch.setitem(os.environb, b"GIT_DIR", b"/nonexistent-\xff-dir")
    wizard.setup_gitignore()                                   # must not raise
    monkeypatch.delitem(os.environb, b"GIT_DIR")
    for ignorecase in IGNORECASE:
        for secret in ("openmatrix.config.json", ".env"):
            assert _git_ignores(repo, secret, ignorecase)


@pytest.mark.parametrize("failure", ["timeout", "no-git"])
def test_git_verdict_says_when_it_could_not_ask_git(sandbox, monkeypatch, failure):
    """A git that hangs, or is not on PATH, used to leave no git verdict and no
    word about it, while every other git error printed one."""
    wizard, said = _isolated_wizard("setup_main_gitignore_no_verdict", monkeypatch)
    infos = []
    monkeypatch.setattr(wizard, "info", lambda text: infos.append(text))

    def broken_run(argv, *a, **k):
        if failure == "timeout":
            raise subprocess.TimeoutExpired(argv, 30)
        raise FileNotFoundError(2, "No such file or directory", argv[0])
    monkeypatch.setattr(subprocess, "run", broken_run)
    wizard.setup_gitignore()
    assert any("git" in line and ".env" in line for line in infos), infos


# Round-4 review: the channel wizards run on their own too. setup_communications.py
# ("run it any time — before, during, or after initial setup"), setup_telegram.py
# and each `python -m setup.<channel>` call save_config()/update_env() with
# persist=True, which wrote the config and .env without ever looking at
# .gitignore. Only setup.py's commit_setup() ran setup_gitignore(). A derived
# project's .gitignore without either entry then let `git add -A` stage both.
DERIVED_GITIGNORE = "__pycache__/\n*.pyc\nnode_modules/\n"


@pytest.mark.skipif(GIT is None, reason="needs git for the ignore verdict")
@pytest.mark.parametrize("name", CHANNEL_MODULES)
def test_a_channel_wizard_run_on_its_own_keeps_its_secrets_out_of_git(
        sandbox, monkeypatch, tmp_path, name):
    repo = tmp_path
    sandbox.unlink()
    subprocess.run([GIT, "init", "-q", str(repo)], check=True, capture_output=True)
    (repo / ".gitignore").write_text(DERIVED_GITIGNORE)
    monkeypatch.setenv("GIT_CONFIG_GLOBAL", os.devnull)
    monkeypatch.setenv("GIT_CONFIG_NOSYSTEM", "1")
    from setup import _shared
    warned = []
    monkeypatch.setattr(_shared, "warn", lambda text: warned.append(text))
    _drive_to_update_env(monkeypatch, tmp_path)

    importlib.import_module(f"setup.{name}").configure({})     # persist defaults to True

    written = [s for s in ("openmatrix.config.json", ".env") if (repo / s).exists()]
    assert "openmatrix.config.json" in written, "not vacuous: the module must have written"
    if name in ENV_WRITING_CHANNELS:
        assert ".env" in written, "not vacuous: the module must have written .env"
    for ignorecase in IGNORECASE:
        for secret in written:
            assert _git_ignores(repo, secret, ignorecase, index=True) or any(
                secret in w for w in warned), (
                f"setup.{name}.configure() wrote {secret}, git (core.ignorecase="
                f"{ignorecase}) would commit it, and nothing said so"
            )


@pytest.mark.skipif(GIT is None, reason="needs git for the ignore verdict")
def test_setup_communications_entry_point_keeps_secrets_out_of_git(tmp_path):
    """The documented command, end to end, as its own process: the reviewer's
    reproduction, with the dispatcher's test message pointed at a closed port."""
    subprocess.run([GIT, "init", "-q", str(tmp_path)], check=True, capture_output=True)
    (tmp_path / ".gitignore").write_text(DERIVED_GITIGNORE)
    env = {**os.environ, "GIT_CONFIG_GLOBAL": os.devnull, "GIT_CONFIG_NOSYSTEM": "1",
           "OPNMATRX_SETUP_NO_VENV": "1", "PYTHONDONTWRITEBYTECODE": "1",
           "PYTHONPATH": str(ROOT)}
    run = subprocess.run(
        [sys.executable, str(ROOT / "setup_communications.py"), "discord"],
        cwd=tmp_path, env=env, input="https://127.0.0.1:9/hook\nbot\n",
        capture_output=True, text=True, timeout=120,
    )
    assert (tmp_path / ".env").read_text().startswith("DISCORD_WEBHOOK_URL="), run.stdout + run.stderr
    staged = subprocess.run([GIT, "-C", str(tmp_path), "add", "-A", "--dry-run"],
                            capture_output=True, text=True, env=env).stdout
    for secret in (".env", "openmatrix.config.json"):
        assert f"'{secret}'" not in staged or secret in run.stdout, (
            f"`git add -A` would stage {secret} and the wizard said nothing:\n"
            f"{staged}\n--- wizard output ---\n{run.stdout}{run.stderr}"
        )


def test_setup_gitignore_is_idempotent(sandbox):
    (sandbox.parent / ".gitignore").write_text("dist/\n")
    wizard = _load_wizard("setup_main_gitignore_twice")
    wizard.setup_gitignore()
    once = (sandbox.parent / ".gitignore").read_text()
    wizard.setup_gitignore()
    assert (sandbox.parent / ".gitignore").read_text() == once
    assert once.startswith("dist/\n"), "existing entries must be kept"


def _line_pool(entry):
    """.gitignore lines that do, might, or do not decide whether *entry* is ignored."""
    head = entry[:2]
    return [
        entry, "/" + entry, "**/" + entry, entry + "*", entry + "/", "\\" + entry,
        " " + entry, "\t" + entry, entry + " ", entry + "\t", entry + "\r", entry + "\\ ",
        "!" + entry, "!/" + entry, "! " + entry, "!" + entry + " ", "!" + entry + "/",
        "!" + entry + "*", "!**/" + entry, "!" + head + "*", "!" + entry.replace(".", "[.]", 1),
        "!\\" + entry, "\\!" + entry, "!foo/" + entry, "!", "!*", "*", "#" + entry, "# !" + entry,
        # Case variants: equal to *entry* only under core.ignorecase=true.
        entry.upper(), "/" + entry.title(), "!" + entry.upper(), "!/" + entry.title(),
        "!" + entry.upper() + " ", "!" + entry[:1] + entry[1:].swapcase(),
        # NUL ends a pattern (git reads C strings); CR is dropped only right
        # before LF; a BOM is skipped only at the very start of the file.
        "!" + entry + "\x00junk", "!" + entry.upper() + "\x00", entry + "\x00x",
        entry + "\r\x00", "!" + entry + "\r\x00", "\x00!" + entry,
        "\ufeff" + entry, "\ufeff!" + entry, entry + "\\\\ ",
    ]


@pytest.mark.skipif(GIT is None, reason="needs git for the ignore verdict")
def test_setup_gitignore_never_leaves_a_secret_committable_generated(sandbox, monkeypatch):
    """The CLASS, not the cases: whatever the existing .gitignore says, afterwards
    git ignores both files. Seeded, so a failure reproduces; each generated file
    mixes exact, wildcard, negated, escaped and whitespace-damaged lines for both
    secrets. The verdict is git's, one batched check-ignore over every case.
    """
    import random
    rng = random.Random(20260912)
    pool = sorted({ln for e in ("openmatrix.config.json", ".env") for ln in _line_pool(e)}
                  | {"", "node_modules/", "!keep.txt", "dist/", ".env.example"})
    repo = sandbox.parent
    subprocess.run([GIT, "init", "-q", str(repo)], check=True, capture_output=True)
    wizard, said = _isolated_wizard("setup_main_gitignore_generated", monkeypatch)
    cases, paths = {}, []
    for i in range(400):
        text = "\n".join(rng.choice(pool) for _ in range(rng.randint(1, 6)))
        if rng.random() < 0.7:
            text += "\n"
        case = repo / f"case{i:03d}"
        case.mkdir()
        (case / ".gitignore").write_bytes(text.encode())
        cases[case.name] = text
        # A .gitignore in a subdirectory anchors to that directory, exactly as the
        # root one does to the root, so each case is its own project here.
        os.chdir(case)
        wizard.setup_gitignore()
        paths += [f"{case.name}/openmatrix.config.json", f"{case.name}/.env"]
    os.chdir(sandbox.parent)
    committable = []
    for ignorecase in IGNORECASE:
        result = subprocess.run(
            [GIT, "-c", f"core.ignorecase={ignorecase}",
             "-C", str(repo), "check-ignore", "--no-index", "--stdin"],
            input="\n".join(paths) + "\n", capture_output=True, text=True,
            env={**os.environ, "GIT_CONFIG_GLOBAL": os.devnull, "GIT_CONFIG_NOSYSTEM": "1"},
        )
        ignored = set(result.stdout.splitlines())
        committable += [(ignorecase, p) for p in paths if p not in ignored]
    assert not committable, (
        f"git would commit {len(committable)} of {2 * len(paths)} (setting, path) pairs "
        "after setup_gitignore():\n" + "\n".join(
            f"  core.ignorecase={ic} {p}  (starting .gitignore {cases[p.split('/')[0]]!r})"
            for ic, p in committable[:15]
        )
    )
    assert not said["warn"], f"warned although git ignores every case: {said['warn'][:5]}"


@pytest.mark.skipif(GIT is None, reason="needs git for the ignore verdict")
def test_the_setup_wizard_checks_gitignore_once_before_it_writes(sandbox, monkeypatch, tmp_path):
    """setup.py's own path, now that the check lives with the writer: accepted,
    it leaves both files ignored, runs the check before the first write, and
    runs it once although it writes two files."""
    subprocess.run([GIT, "init", "-q", str(tmp_path)], check=True, capture_output=True)
    (tmp_path / ".gitignore").write_text(DERIVED_GITIGNORE)
    sandbox.unlink()
    wizard, said = _isolated_wizard("setup_main_gitignore_commit", monkeypatch)
    monkeypatch.setattr(wizard, "ask", lambda prompt, default="", options=None, **k: "yes")
    _drive_to_update_env(monkeypatch, tmp_path)
    runs = []
    real = wizard.setup_gitignore

    def recording():
        runs.append([s for s in ("openmatrix.config.json", ".env") if (tmp_path / s).exists()])
        real()
    monkeypatch.setattr(wizard, "setup_gitignore", recording)

    config: dict = {}
    wizard.configure_communications(config)
    assert wizard.commit_setup(config) is True
    assert runs == [[]], f"check ran {len(runs)} times; secret files already on disk: {runs}"
    assert (tmp_path / ".env").exists() and (tmp_path / "openmatrix.config.json").exists()
    for ignorecase in IGNORECASE:
        for secret in ("openmatrix.config.json", ".env"):
            assert _git_ignores(tmp_path, secret, ignorecase, index=True), secret
    assert not said["warn"], said["warn"]


def test_only_the_guarded_writer_puts_a_secret_file_on_disk():
    """The class, structurally: nothing writes a file holding keys except
    setup/_shared.py's write_secret_file(), which checks .gitignore first.
    Every entry point (setup.py, setup_communications.py, setup_telegram.py,
    each channel module) reaches disk through it."""
    import ast
    sources = [ROOT / "setup.py", ROOT / "setup_communications.py",
               ROOT / "setup_telegram.py", *sorted((ROOT / "setup").glob("*.py"))]
    offenders = []
    for path in sources:
        tree = ast.parse(path.read_text(encoding="utf-8"))
        for node in ast.walk(tree):
            if not isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
                continue
            for call in ast.walk(node):
                if (isinstance(call, ast.Call)
                        and isinstance(call.func, ast.Name)
                        and call.func.id == "_atomic_write_text"
                        and node.name != "write_secret_file"):
                    offenders.append(f"{path.name}:{call.lineno} in {node.name}()")
    assert not offenders, (
        "these write a secret file without the .gitignore check that "
        "write_secret_file() runs first: " + ", ".join(offenders)
    )
