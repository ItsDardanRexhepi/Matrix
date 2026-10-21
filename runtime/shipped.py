"""Where the gateway finds the agents' prompts, its pages, the registry and the skills.

They sit at a clone's root: the agents' identity prompts in agents/, the pages
the gateway serves in web/, the component registry in
extensions/registry.json and the skills in skills/. The gateway has always
read them from its working folder (the skills from the configured workspace,
which is that folder unless the configuration names another), and a clone
runs from its root. An installed package runs the gateway in the
user's own folder instead (~/.matrix, or $MATRIX_HOME; cli/home.py), which
holds the configuration and the data and none of these, so the package
carries its own copy of each beside its packages, at the path a clone has it
(pyproject.toml).

A page or the registry is read from the working folder when it is there, as
before, and otherwise from beside the packages, where before the gateway went
without it. The prompts and the skills are read from both folders, the
packaged one first: an agent's prompt or a skill in the working folder (the
skills' in the workspace) replaces the packaged one of the same name, and one
the package does not have is added. Read from the working folder alone, an
agent imported into it (migration/ writes one to agents/<name>/) would leave
Trinity, Neo and Morpheus without their prompts. In a clone run from its root
both folders are that root, read once. An install reads the copies it
carries, with whatever has been put in its folder over them.
"""
from __future__ import annotations

from pathlib import Path

#: The folder that holds the runtime package: a clone's root, or site-packages.
PACKAGE_PARENT = Path(__file__).resolve().parent.parent


def shipped(relative: str | Path, folder: str | Path | None = None) -> Path:
    """*relative* under *folder* (the working folder when None) when it exists
    there, otherwise the copy beside the packages, whether or not that exists."""
    here = Path(relative) if folder is None else Path(folder) / relative
    if here.exists():
        return here
    return PACKAGE_PARENT / relative


def shipped_folders(relative: str | Path, folder: str | Path | None = None) -> list[Path]:
    """Each folder named *relative* that exists: the one beside the packages,
    then the one under *folder* (the working folder when None), each read once
    when both are the same folder. Read in this order, a name in the second
    replaces the same name in the first."""
    found: list[Path] = []
    here = Path(relative) if folder is None else Path(folder) / relative
    for candidate in (PACKAGE_PARENT / relative, here):
        if candidate.is_dir() and all(candidate.resolve() != seen.resolve() for seen in found):
            found.append(candidate)
    return found

