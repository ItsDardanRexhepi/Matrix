"""Where the matrix command keeps what it writes.

Run from a clone, the command keeps everything in the clone, as it always has:
matrix.config.json, .env and data/ at the clone's root, the gateway's PID and
log in data/, and the clone's .venv to run the gateway with. A clone is told
apart by the two files a checkout has beside the package and an install does
not: setup.py and pyproject.toml.

An installed package (pipx, ``pip install``, a Homebrew formula) has no such
folder. The folder above its own files is site-packages, which is no place for
keys and which the next upgrade replaces, and the setup that a clone runs from
its root is not there at all. So an install keeps its configuration, its keys,
its data, and the gateway's PID and log in one folder of the user's own:
``$MATRIX_HOME`` when that is set, otherwise ``~/.matrix``. The setup writes
there, and the gateway runs with that folder as its working directory, so the
platform reads the config, the .env and the database there exactly as it reads
them at a clone's root. ``MATRIX_HOME`` is read only by an install; a clone
keeps its files in the clone whatever it says.
"""
from __future__ import annotations

import os
import sys
from pathlib import Path

#: The folder that holds the cli package: a clone's root, or site-packages.
PACKAGE_PARENT = Path(__file__).resolve().parent.parent

#: The variable that moves an install's folder.
HOME_ENV = "MATRIX_HOME"

#: An install's folder when MATRIX_HOME is not set, under the user's home.
DEFAULT_HOME_NAME = ".matrix"


def checkout(parent: Path | None = None) -> Path | None:
    """The clone this command runs from, or None when it runs from an install."""
    parent = PACKAGE_PARENT if parent is None else Path(parent)
    if (parent / "setup.py").is_file() and (parent / "pyproject.toml").is_file():
        return parent
    return None


def home(env=None, parent: Path | None = None) -> Path:
    """The folder the command reads and writes: the clone, or the install's own."""
    clone = checkout(parent)
    if clone is not None:
        return clone
    env = os.environ if env is None else env
    chosen = (env.get(HOME_ENV) or "").strip()
    if chosen:
        return Path(os.path.abspath(os.path.expanduser(chosen)))
    return Path.home() / DEFAULT_HOME_NAME


def make_home(path: Path) -> Path:
    """Create an install's folder, readable by its owner only, if it is missing.

    It holds the keys the setup asks for. An existing folder keeps the mode
    its owner gave it.
    """
    path.mkdir(mode=0o700, parents=True, exist_ok=True)
    return path


# Python 3.10 has no -P. There the command is run through runpy with the
# folder it starts in (the first entry of sys.path under -c) taken off first.
_WITHOUT_THE_FOLDER = ("import runpy, sys; del sys.path[0]; "
                       "runpy.run_module(sys.argv.pop(1), run_name='__main__', alter_sys=True)")


def module_command(module: str, *args: str, version=None) -> list[str]:
    """The command that runs *module* as a script under this interpreter.

    An install starts the wizard and the gateway in its own folder, which
    holds the user's data and not code, so that folder is kept off the import
    path: nothing in it can stand in for an installed module. -P does that on
    Python 3.11 and later. Unlike -I it keeps the user's site-packages, where
    ``pip install --user`` puts the package, and PYTHONPATH, which a
    ``pip install --target`` folder needs.
    """
    version = sys.version_info if version is None else version
    if tuple(version[:2]) >= (3, 11):
        return [sys.executable, "-P", "-m", module, *args]
    return [sys.executable, "-c", _WITHOUT_THE_FOLDER, module, *args]
