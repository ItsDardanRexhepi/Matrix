"""The two install paths must install the dependency set the suite ran against.

There are two ways this code gets its dependencies, and before this test they
disagreed with each other and with the code:

  * ``requirements.txt`` — what the production Docker image, install.sh,
    setup.py and CI install. Every entry was an unbounded ``>=`` with no lock,
    so a future major of web3, eth-account, aiohttp or cryptography entered the
    signing/RPC path of the image on its next build, unreviewed.

  * ``pyproject.toml`` — what ``pip install .`` / ``pip install -e .`` install
    (setup.py runs the latter after requirements.txt). It omitted PyJWT and
    cryptography, so on that install Sign in with Apple and App Store receipt
    verification both fail closed and the public route answers a 401 that is
    indistinguishable from a bad token. Its ``~=`` bounds also EXCLUDED the
    versions the suite actually runs on (``web3~=6.20`` against web3 7.16), so
    setup.py's editable install would downgrade what requirements.txt had just
    installed.

Nothing here reads a comment or a list someone maintains about what the code
needs. The needed set is derived from the code's own import statements, the
closure from installed distribution metadata, and the running versions from
the interpreter the suite is running in.
"""

from __future__ import annotations

import ast
import importlib.metadata as md
import sys
import tomllib
from pathlib import Path

import pytest
from packaging.requirements import Requirement
from packaging.specifiers import SpecifierSet
from packaging.utils import canonicalize_name

ROOT = Path(__file__).resolve().parent.parent

# Imports the code makes that are deliberately NOT a dependency of this
# package. Each names why. An import missing from here AND from the manifests
# fails the test — that is the point.
NOT_A_DEPENDENCY = {
    # The closed-source Morpheus core lives in a private repo; the public seam
    # imports it guarded and runs OBSERVE-only without it.
    "morpheus_security": "private package, optional seam",
    # Guarded import; tracing is off unless an operator installs it. Not
    # installed in the reference environment, so there is no tested version
    # to pin — declaring it unpinned would be exactly the defect this fixes.
    "opentelemetry": "optional, untested, never installed by either path",
}

# Imports whose distribution is declared in an optional group and is not
# installed in the reference environment (so packages_distributions() cannot
# map it). Mapped by hand; the assertion still checks the manifest.
OPTIONAL_UNINSTALLED = {
    "sentry_sdk": "sentry-sdk",
}


def _pyproject() -> dict:
    return tomllib.loads((ROOT / "pyproject.toml").read_text(encoding="utf-8"))


def _shipped_roots() -> list[Path]:
    include = _pyproject()["tool"]["setuptools"]["packages"]["find"]["include"]
    return [ROOT / pat.rstrip("*") for pat in include if (ROOT / pat.rstrip("*")).is_dir()]


def _requirements(path: Path) -> list[Requirement]:
    reqs = []
    for raw in path.read_text(encoding="utf-8").splitlines():
        line = raw.split("#", 1)[0].strip()
        if not line or line.startswith("-"):
            continue
        reqs.append(Requirement(line))
    return reqs


def _by_name(reqs) -> dict[str, Requirement]:
    return {canonicalize_name(r.name): r for r in reqs}


def _third_party_imports() -> dict[str, set[str]]:
    first_party = {p.name for p in ROOT.iterdir() if p.is_dir()} | {p.stem for p in ROOT.glob("*.py")}
    found: dict[str, set[str]] = {}
    for root in _shipped_roots():
        for f in root.rglob("*.py"):
            tree = ast.parse(f.read_text(encoding="utf-8"))
            for node in ast.walk(tree):
                if isinstance(node, ast.Import):
                    mods = [a.name for a in node.names]
                elif isinstance(node, ast.ImportFrom) and node.level == 0 and node.module:
                    mods = [node.module]
                else:
                    continue
                for mod in mods:
                    top = mod.split(".")[0]
                    if top in sys.stdlib_module_names or top in first_party:
                        continue
                    found.setdefault(top, set()).add(str(f.relative_to(ROOT)))
    return found


def test_every_imported_distribution_is_declared_by_the_package():
    """`pip install .` must install what the shipped code imports.

    Guarded imports count. A guarded import of a missing library is how the
    Apple sign-in verifier fails closed into a misleading 401 — the guard makes
    it quiet, not optional.
    """
    project = _pyproject()["project"]
    declared = set(_by_name(Requirement(r) for r in project["dependencies"]))
    optional = {
        canonicalize_name(Requirement(r).name)
        for group in project.get("optional-dependencies", {}).values()
        for r in group
    }
    dist_for = md.packages_distributions()

    problems = []
    for module, files in sorted(_third_party_imports().items()):
        if module in NOT_A_DEPENDENCY:
            continue
        if module in OPTIONAL_UNINSTALLED:
            dist = canonicalize_name(OPTIONAL_UNINSTALLED[module])
            if dist not in optional:
                problems.append(f"{module}: {dist} not in any optional group ({sorted(files)[0]})")
            continue
        dists = dist_for.get(module)
        if not dists:
            problems.append(f"{module}: imported by {sorted(files)[0]} but no installed distribution provides it")
            continue
        names = {canonicalize_name(d) for d in dists}
        if not names & declared:
            problems.append(f"{module} ({', '.join(sorted(names))}): imported by {sorted(files)[:3]} but not in [project].dependencies")
    assert not problems, "pyproject.toml does not declare what the code imports:\n  " + "\n  ".join(problems)


def test_requirements_txt_is_an_exact_lock():
    """Every entry the image installs is pinned with == — no floating range."""
    loose = [str(r) for r in _requirements(ROOT / "requirements.txt")
             if len(r.specifier) != 1 or next(iter(r.specifier)).operator != "=="]
    assert not loose, f"requirements.txt entries that are not exact pins: {loose}"


def test_the_lock_satisfies_the_package_bounds():
    """Both install paths agree: each package dependency is locked, inside its bound.

    Before: pyproject said web3~=6.20 while the image and the suite ran 7.16, so
    setup.py's `pip install -e .` after `pip install -r requirements.txt` would
    downgrade the signing library under the operator.
    """
    lock = _by_name(_requirements(ROOT / "requirements.txt"))
    problems = []
    for spec in _pyproject()["project"]["dependencies"]:
        req = Requirement(spec)
        name = canonicalize_name(req.name)
        if not req.specifier or all(s.operator in (">=", ">") for s in req.specifier):
            problems.append(f"{spec}: pyproject bound has no upper limit")
        pinned = lock.get(name)
        if pinned is None:
            problems.append(f"{spec}: not locked in requirements.txt")
            continue
        version = next(iter(pinned.specifier)).version
        if version not in req.specifier:
            problems.append(f"{spec}: lock pins {version}, outside the package bound")
        if set(req.extras) != set(pinned.extras):
            problems.append(f"{spec}: extras differ from the lock ({sorted(pinned.extras)})")
    assert not problems, "\n  ".join(["pyproject.toml and requirements.txt disagree:", *problems])


def _closure(roots: list[Requirement]) -> dict[str, tuple[str, set[str]]]:
    """Walk installed Requires-Dist, honouring extras and markers, for THIS interpreter."""
    seen: dict[str, tuple[str, set[str]]] = {}
    stack = list(roots)
    while stack:
        req = stack.pop()
        name = canonicalize_name(req.name)
        try:
            dist = md.distribution(req.name)
        except md.PackageNotFoundError:
            seen.setdefault(name, ("<not installed>", set()))
            continue
        if name in seen and set(req.extras) <= seen[name][1]:
            continue
        extras = seen.get(name, (dist.version, set()))[1] | set(req.extras)
        seen[name] = (dist.version, extras)
        for raw in dist.requires or []:
            sub = Requirement(raw)
            envs = [{"extra": e} for e in extras] + [{"extra": ""}]
            if sub.marker is None or any(sub.marker.evaluate(env) for env in envs):
                stack.append(sub)
    return seen


def test_the_lock_is_the_set_this_suite_runs_against():
    """The lock covers the whole runtime closure, and the suite ran on exactly it.

    A top-level-only lock still lets eth-keys, eth-utils and hexbytes float —
    and they are in the signing path (hexbytes' `.hex()` dropped its 0x prefix
    across a major). If this fails because a contributor's environment differs
    from the lock, the green run beside it does not describe the image.
    """
    lock = _by_name(_requirements(ROOT / "requirements.txt"))
    closure = _closure([Requirement(r) for r in _pyproject()["project"]["dependencies"]])

    unpinned = sorted(n for n in closure if n not in lock)
    assert not unpinned, f"runtime closure members not locked in requirements.txt: {unpinned}"

    strays = sorted(n for n in lock if n not in closure)
    assert not strays, f"requirements.txt locks packages nothing in [project].dependencies needs: {strays}"

    drift = sorted(
        f"{n}: lock {next(iter(lock[n].specifier)).version}, running {v}"
        for n, (v, _) in closure.items()
        if next(iter(lock[n].specifier)).version != v
    )
    assert not drift, "the suite is not running against the locked set:\n  " + "\n  ".join(drift)


def test_every_locked_version_supports_the_declared_python_floor():
    """requires-python says 3.10; a lock that needs 3.11 would make that untrue."""
    floor = _pyproject()["project"]["requires-python"]
    lowest = floor.removeprefix(">=").strip()
    problems = []
    for name, req in _by_name(_requirements(ROOT / "requirements.txt")).items():
        try:
            requires_python = md.metadata(req.name).get("Requires-Python")
        except md.PackageNotFoundError:
            continue  # reported by the closure test
        if requires_python and lowest not in SpecifierSet(requires_python):
            problems.append(f"{name}: Requires-Python {requires_python}")
    assert not problems, f"locked versions that cannot install on Python {lowest}: {problems}"
