"""
Shared helpers for the modular setup wizards.

Every channel configurator uses these for consistent prompts, config
persistence, and `.env` updates.
"""

from __future__ import annotations

import json
import os
import stat
import sys
import tempfile
from pathlib import Path

# ANSI colors
BOLD  = "\033[1m"
DIM   = "\033[2m"
GREEN = "\033[32m"
YELLOW = "\033[33m"
RED   = "\033[31m"
CYAN  = "\033[36m"
RESET = "\033[0m"

CONFIG_PATH = Path("matrix.config.json")
ENV_PATH = Path(".env")


# ── Output helpers ──────────────────────────────────────────────────────

def info(msg: str) -> None:
    print(f"{DIM}• {msg}{RESET}")

def success(msg: str) -> None:
    print(f"{GREEN}✓ {msg}{RESET}")

def warn(msg: str) -> None:
    print(f"{YELLOW}! {msg}{RESET}")

def error(msg: str) -> None:
    print(f"{RED}✗ {msg}{RESET}")

def header(title: str) -> None:
    print()
    print(f"{BOLD}{CYAN}=== {title} ==={RESET}")
    print()


# ── Input helpers ───────────────────────────────────────────────────────

def ask(question: str, default: str = "", *, password: bool = False) -> str:
    """Prompt for input with an optional default."""
    suffix = f" [{default}]" if default else ""
    prompt = f"{BOLD}? {question}{suffix}:{RESET} "
    if password:
        import getpass
        resp = getpass.getpass(prompt)
    else:
        resp = input(prompt).strip()
    return resp or default


def yes_no(question: str, default: bool = False) -> bool:
    default_str = "yes" if default else "no"
    resp = ask(question, default=default_str)
    return resp.lower().startswith("y")


# ── Config persistence ─────────────────────────────────────────────────

def load_config() -> dict:
    if CONFIG_PATH.exists():
        try:
            return json.loads(CONFIG_PATH.read_text(encoding="utf-8"))
        except json.JSONDecodeError:
            warn("Existing config is not valid JSON. Starting with an empty config.")
    return {}


def _umask_mode() -> int:
    """The mode a plain ``open(path, "w")`` would create a file with.

    os.umask can only be read by setting it. It is set to the STRICTER 077 for
    that instant, so anything another thread creates meanwhile errs closed.
    """
    previous = os.umask(0o077)
    os.umask(previous)
    return 0o666 & ~previous


def _atomic_write_text(path: Path, text: str, *, new_file_mode: int | None) -> None:
    """Replace *path*'s contents all at once, keeping what the operator set up.

    Temp file in the same directory, fsync, rename. Two properties a bare
    ``tmp.write_text`` + ``os.replace`` (RUN-1's first version) lost:

    * the MODE. The rename installs a new inode, so a file the operator had
      chmod 600'd came back 644. An existing file's mode is carried over.
    * a SYMLINK. Renaming over a link replaces the link with a regular file, so
      a .env kept in a vault directory and linked in would silently stop being
      the one that is updated. The link's target is what gets replaced.

    A file that does not exist yet is created with *new_file_mode*, and that is
    the caller's decision because it depends on who else must read the file.
    ``None`` means what ``write_text`` would have given it (the umask): the
    config is bind-mounted into the Docker image and read there as uid 1000, so
    a 600 config written by any other uid stops the gateway from starting.

    The temp file is 600 while the secrets are written into it, whatever mode
    the result gets. Any failure — including one partway through writing —
    removes the temp file and leaves the original untouched.
    """
    target = path.resolve() if path.is_symlink() else path
    try:
        mode = stat.S_IMODE(target.stat().st_mode)
    except FileNotFoundError:
        mode = _umask_mode() if new_file_mode is None else new_file_mode
    fd, tmp_name = tempfile.mkstemp(
        dir=str(target.parent), prefix=f".{target.name}.", suffix=".tmp",
    )
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as fh:
            fh.write(text)
            fh.flush()
            os.fsync(fh.fileno())
        os.chmod(tmp_name, mode)
        os.replace(tmp_name, target)
    except BaseException:
        try:
            os.unlink(tmp_name)
        except FileNotFoundError:
            pass
        raise


# Who reads each secret file decides the mode it is CREATED with (an existing
# file always keeps its own):
#   matrix.config.json — the host gateway, and the Docker image, which
#     bind-mounts it read-only (docker-compose.yml) and runs as uid 1000. It is
#     created the way `cp matrix.config.json.example` or write_text would
#     create it, so a wizard run as any other uid (root on a VPS) still starts.
#   .env — only processes on the host running as the operator: the gateway's
#     load_dotenv and docker compose's variable interpolation. .dockerignore
#     keeps it out of the image and no compose file mounts it, so it is 600.
CONFIG_NEW_FILE_MODE: int | None = None
ENV_NEW_FILE_MODE: int | None = 0o600


# Directories whose .gitignore this process has already checked. See
# keep_secret_files_out_of_git().
_GITIGNORE_CHECKED: set[str] = set()


def keep_secret_files_out_of_git(check=None) -> None:
    """Check .gitignore once per directory, before the first key is written there.

    Every write of a file holding keys goes through write_secret_file(), which
    calls this. Only setup.py's commit_setup() used to run the check, so the
    channel wizards run on their own (setup_communications.py, setup_telegram.py,
    ``python -m setup.<channel>``) wrote the config and .env into a project
    whose .gitignore listed neither, said nothing, and `git add -A` staged both.

    *check* is how setup.py runs the same check with its own output; by default
    it is setup/_gitignore.py's with this module's warn/info/success. The
    directory is the working directory, because that is where CONFIG_PATH and
    ENV_PATH are.
    """
    here = os.path.abspath(os.getcwd())
    if here in _GITIGNORE_CHECKED:
        return
    _GITIGNORE_CHECKED.add(here)
    if check is not None:
        check()
        return
    from setup import _gitignore
    _gitignore.setup_gitignore(warn=warn, info=info, success=success)


def write_secret_file(path: Path, text: str, *, new_file_mode: int | None, check=None) -> None:
    """The one way a file holding keys reaches disk: .gitignore first, then the
    atomic write."""
    keep_secret_files_out_of_git(check)
    _atomic_write_text(path, text, new_file_mode=new_file_mode)


def save_config(config: dict, persist: bool = True) -> None:
    """Persist *config*, atomically — unless the caller owns the write.

    ``persist=False`` is how the setup wizard says "I will do the writing".
    Channel modules mutate the dict and hand it back; only the wizard's
    ``write_config()`` touches disk, and only after the operator has agreed to
    overwrite. This is RUN-1: nine channel modules each called an unconditional
    ``write_text`` from inside step 7, so an existing config was already
    destroyed by the time the wizard printed "Existing config preserved".

    The default stays ``True`` so the modules remain independently runnable
    (``python setup_communications.py telegram``).

    The write goes through ``_atomic_write_text`` so an interrupted run cannot
    leave a truncated config behind — a half-written config is worse than
    either outcome, and the previous direct ``write_text`` had that window.
    """
    if not persist:
        return
    write_secret_file(CONFIG_PATH, json.dumps(config, indent=2) + "\n",
                      new_file_mode=CONFIG_NEW_FILE_MODE)


def update_channel(config: dict, channel_name: str, channel_cfg: dict) -> None:
    """Merge *channel_cfg* into config['notifications'][channel_name]."""
    notif = config.setdefault("notifications", {})
    existing = notif.get(channel_name, {})
    existing.update(channel_cfg)
    existing["enabled"] = True
    notif[channel_name] = existing


# .env updates collected while the wizard owns the write. See update_env().
_PENDING_ENV: dict[str, str] = {}


def update_env(updates: dict[str, str], persist: bool = True) -> None:
    """Merge key=value pairs into the top-level .env file — or stage them.

    ``persist`` means exactly what it means for ``save_config``, on the line
    above every call to this. It did not exist: RUN-1 gated the config write and
    left this one unconditional, so the wizard rewrote the operator's .env in
    step 7 whatever they answered afterwards, and printed "Existing config
    preserved" over it.

    With ``persist=False`` the updates are staged. The wizard writes them with
    ``flush_pending_env()`` once the operator has agreed, or they are dropped
    with the process.
    """
    if not persist:
        _PENDING_ENV.update(updates)
        return
    _write_env(updates)


def pending_env() -> dict[str, str]:
    """A copy of the staged updates, for the wizard to roll a channel back to."""
    return dict(_PENDING_ENV)


def restore_pending_env(snapshot: dict[str, str]) -> None:
    _PENDING_ENV.clear()
    _PENDING_ENV.update(snapshot)


def flush_pending_env() -> None:
    """Write everything staged with ``persist=False``, then forget it."""
    if _PENDING_ENV:
        _write_env(dict(_PENDING_ENV))
    _PENDING_ENV.clear()


def _write_env(updates: dict[str, str]) -> None:
    lines: list[str] = []
    if ENV_PATH.exists():
        lines = ENV_PATH.read_text(encoding="utf-8").splitlines()

    for var, value in updates.items():
        found = False
        for i, line in enumerate(lines):
            if line.startswith(f"{var}="):
                lines[i] = f"{var}={value}"
                found = True
                break
        if not found:
            lines.append(f"{var}={value}")

    write_secret_file(ENV_PATH, "\n".join(lines) + "\n", new_file_mode=ENV_NEW_FILE_MODE)


# ── Channel test ────────────────────────────────────────────────────────

def test_channel_via_dispatcher(config: dict, channel_name: str) -> dict:
    """Instantiate the NotificationDispatcher and fire a test message.

    Returns the adapter's result dict. Never raises.
    """
    try:
        from runtime.notifications import NotificationDispatcher
    except Exception as exc:
        return {"status": "error", "error": f"failed to import dispatcher: {exc}"}

    import asyncio
    dispatcher = NotificationDispatcher(config)
    try:
        return asyncio.run(dispatcher.test_channel(channel_name))
    except RuntimeError:
        # If an event loop is already running we can't use asyncio.run().
        loop = asyncio.new_event_loop()
        try:
            return loop.run_until_complete(dispatcher.test_channel(channel_name))
        finally:
            loop.close()
