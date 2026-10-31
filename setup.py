#!/usr/bin/env python3
"""
The Matrix — Interactive First-Boot Setup, from a clone

Run once after cloning, from the clone's root:

    python3 setup.py          # or ./setup.py — the file is executable

The wizard itself is setup/wizard.py, inside the `setup` package, so an
installed package carries it too and runs it as `matrix setup`. From here it
creates a virtual environment in .venv beside this file and re-launches
itself inside it, installs dependencies, creates matrix.config.json with your
settings, verifies connectivity, and prints how to start the gateway.

This file is also the one setuptools executes during every build of the
package, which it is handed straight back to.
"""

import sys

# setuptools executes a project's setup.py as __main__ during every build:
# `pip install .`, `pip install -e .`, `python -m build`. Those runs arrive
# with one of these as argv[1]. The wizard must hand them to setuptools
# instead of asking the operator questions from inside pip (which is exactly
# what happened before: banner, "Checking environment", EOFError).
SETUPTOOLS_COMMANDS = frozenset({
    "egg_info", "dist_info", "bdist_wheel", "editable_wheel", "sdist",
    "build", "build_py", "build_ext", "develop", "install", "clean",
    "--name", "--version", "--help-commands",
})


def invoked_by_setuptools(argv=None):
    argv = sys.argv if argv is None else argv
    return len(argv) > 1 and argv[1] in SETUPTOOLS_COMMANDS


if __name__ == "__main__":
    if invoked_by_setuptools():
        # A pip/setuptools build is running this file — hand over. All the
        # package metadata lives in pyproject.toml.
        from setuptools import setup
        setup()
    else:
        # `python3 setup.py` puts this folder first on sys.path, and a package
        # wins over a module of the same name there: this is setup/wizard.py.
        from setup.wizard import main
        sys.exit(main() or 0)
