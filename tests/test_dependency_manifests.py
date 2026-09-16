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
import re
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


def _entries(path: Path) -> list[tuple[Requirement, list[str]]]:
    """(requirement, its sha256 hashes) for each entry of a pip requirements file.

    Joins backslash continuations, so a hashed lock's `name==v \\` line and the
    `--hash=` lines under it read as one entry. Option lines (`-r`, `-c`) are
    skipped; markers are kept.
    """
    entries = []
    text = path.read_text(encoding="utf-8").replace("\\\n", " ")
    for raw in text.splitlines():
        line = raw if raw.lstrip().startswith("--hash") else raw.split(" #", 1)[0]
        line = line.strip()
        if not line or line.startswith("#") or line.startswith("-"):
            continue
        hashes = re.findall(r"--hash=sha256:([0-9a-f]{64})", line)
        entries.append((Requirement(re.sub(r"\s*--hash=\S+", "", line).strip()), hashes))
    return entries


def _requirements(path: Path) -> list[Requirement]:
    return [req for req, _ in _entries(path)]


def _by_name(reqs) -> dict[str, Requirement]:
    return {canonicalize_name(r.name): r for r in reqs}


def _applies(req: Requirement, env: dict | None = None) -> bool:
    return req.marker is None or req.marker.evaluate(env or {})


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


LOCKS = ("requirements.txt", "requirements-build.txt")


@pytest.mark.parametrize("lock", LOCKS)
def test_lock_is_exact_and_hashed(lock):
    """Every entry the image installs is pinned with == AND carries its hashes.

    `==` alone stops a new version arriving; it does not stop a new wheel file
    uploaded later for a version already pinned. A hash does: pip refuses a
    file whose digest is not listed.
    """
    entries = _entries(ROOT / lock)
    assert entries, f"{lock} has no entries"
    loose = [str(r) for r, _ in entries
             if len(r.specifier) != 1 or next(iter(r.specifier)).operator != "=="]
    assert not loose, f"{lock} entries that are not exact pins: {loose}"
    unhashed = [str(r) for r, hashes in entries if not hashes]
    assert not unhashed, f"{lock} entries without --hash (pip would not refuse a swapped file): {unhashed}"


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
        # No extras comparison: a hashed lock lists an extra's dependencies as
        # entries of their own (PyJWT[crypto] -> cryptography), because pip's
        # hash checking needs every installed file named. The closure test
        # walks pyproject's extras and fails if one of those is not locked.
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
    # Entries gated to another interpreter or platform (a 3.10 backport, a
    # Windows-only dependency) are not part of THIS interpreter's set;
    # test_the_lock_covers_every_supported_interpreter holds those.
    lock = _by_name(r for r in _requirements(ROOT / "requirements.txt") if _applies(r))
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
    """requires-python says 3.10; a lock that needs 3.11 would make that untrue.

    Read from the INSTALLED distribution, so it says something about the lock
    only where the installed version IS the locked one; anything else is
    reported rather than checked against the wrong version's metadata.
    """
    floor = _pyproject()["project"]["requires-python"]
    lowest = floor.removeprefix(">=").strip()
    floor_env = {"python_version": lowest, "python_full_version": f"{lowest}.0"}
    problems = []
    for req in _requirements(ROOT / "requirements.txt"):
        if not _applies(req, floor_env) and not _applies(req):
            continue   # e.g. Windows-only
        locked = next(iter(req.specifier)).version
        try:
            dist = md.distribution(req.name)
        except md.PackageNotFoundError:
            if _applies(req):
                problems.append(f"{req.name}: locked for this interpreter but not installed")
            continue   # gated to another interpreter; its own marker is the check
        if dist.version != locked:
            problems.append(f"{req.name}: installed {dist.version}, locked {locked} — cannot check the locked version")
            continue
        requires_python = dist.metadata.get("Requires-Python")
        if requires_python and lowest not in SpecifierSet(requires_python):
            problems.append(f"{req.name}: Requires-Python {requires_python}")
    assert not problems, f"locked versions not shown to install on Python {lowest}: {problems}"


# The interpreters and platforms the installers accept. install.sh and setup.py
# take any python3 >= 3.10; the image and CI use 3.11; pyproject lists Linux
# and macOS.
SUPPORTED_ENVS = [
    {"python_version": f"3.{minor}", "python_full_version": f"3.{minor}.0",
     "sys_platform": plat, "platform_system": system, "platform_machine": machine,
     "os_name": "posix", "implementation_name": "cpython",
     "platform_python_implementation": "CPython"}
    for minor in (10, 11, 12, 13, 14)
    for plat, system, machine in (("linux", "Linux", "x86_64"), ("linux", "Linux", "aarch64"),
                                  ("darwin", "Darwin", "arm64"))
]


def test_the_lock_covers_every_supported_interpreter():
    """No interpreter an installer accepts may resolve a dependency freely.

    The first lock was resolved for 3.11 only. On 3.10, which install.sh and
    requires-python accept, aiohttp pulls async-timeout and anyio pulls
    exceptiongroup, and neither was locked. With hashes that is no longer a
    quiet float but a refused install, so it is held here for every supported
    interpreter and platform: walking the installed Requires-Dist under that
    environment's markers, every requirement reached must be locked under a
    marker that applies there, at a version the requirement accepts.

    Limit: a dependency OF a package that is not installed here (because its
    marker excludes this interpreter) cannot be walked offline. Those are named
    in the failure message if anything else fails.
    """
    lock = {}
    for req in _requirements(ROOT / "requirements.txt"):
        lock.setdefault(canonicalize_name(req.name), []).append(req)
    roots = [Requirement(r) for r in _pyproject()["project"]["dependencies"]]
    problems, unwalked = [], set()
    for env in SUPPORTED_ENVS:
        label = f"{env['sys_platform']}-{env['platform_machine']}-py{env['python_version']}"
        seen: set[tuple[str, frozenset]] = set()
        stack = [(r, frozenset(r.extras)) for r in roots]
        while stack:
            req, extras = stack.pop()
            name = canonicalize_name(req.name)
            if (name, extras) in seen:
                continue
            seen.add((name, extras))
            pins = [p for p in lock.get(name, []) if _applies(p, env)]
            if not pins:
                problems.append(f"{label}: {req} is needed and not locked for this environment")
                continue
            version = next(iter(pins[0].specifier)).version
            if req.specifier and version not in req.specifier:
                problems.append(f"{label}: {req} is needed; lock pins {version}")
            try:
                dist = md.distribution(req.name)
            except md.PackageNotFoundError:
                unwalked.add(f"{name}=={version}")
                continue
            if dist.version != version:
                problems.append(f"{label}: {name} installed {dist.version}, locked {version} — walked the wrong metadata")
                continue
            for raw in dist.requires or []:
                sub = Requirement(raw)
                wanted = [dict(env, extra=e) for e in extras] + [dict(env, extra="")]
                if sub.marker is None or any(sub.marker.evaluate(w) for w in wanted):
                    stack.append((sub, frozenset(sub.extras)))
    assert not problems, "\n  ".join(
        ["the lock does not cover every supported interpreter:", *sorted(set(problems))[:40],
         f"(not walkable offline, not installed here: {sorted(unwalked)})"]
    )


def _pip_install_commands(text: str) -> list[str]:
    """Each shell command that runs `pip install`, continuations joined and
    `&&` / `||` / `;` chains split, so one command is judged on its own files."""
    joined = re.sub(r"\\\n\s*", " ", text)
    commands = (part.strip() for ln in joined.splitlines() for part in re.split(r"&&|\|\||;", ln))
    return [c for c in commands if re.search(r"\bpip\b.*\binstall\b", c)]


def test_no_install_mixes_the_hashed_lock_with_an_unhashed_file():
    """pip turns on hash checking for a whole command when any requirement has a
    hash, and then refuses every unhashed requirement in it. So every command
    that installs requirements.txt must install nothing else, and no other
    requirements file may pull it in with `-r` (requirements-dev.txt did)."""
    problems = []
    sources = [ROOT / p for p in ("Dockerfile", "install.sh", "setup.py")]
    sources += sorted((ROOT / ".github" / "workflows").glob("*.yml"))
    for src in sources:
        if not src.is_file():
            continue
        text = src.read_text(encoding="utf-8")
        if src.suffix == ".py":
            text = "\n".join(" ".join(re.findall(r'"([^"]*)"', ln)) for ln in text.splitlines())
        for cmd in _pip_install_commands(text):
            files = re.findall(r"-r\s+(\S+)", cmd)
            if "requirements.txt" in files and len(files) > 1:
                problems.append(f"{src.relative_to(ROOT)}: {cmd}")
    for req_file in ROOT.glob("requirements*.txt"):
        if req_file.name in LOCKS:
            continue
        if re.search(r"^\s*-[rc]\s+requirements\.txt", req_file.read_text(encoding="utf-8"), re.M):
            problems.append(f"{req_file.name} includes requirements.txt")
    assert not problems, "these would fail in pip's hash-checking mode:\n  " + "\n  ".join(problems)


def test_the_image_builds_from_content_pinned_inputs():
    """The Dockerfile's inputs are pinned to content, not to names that move.

    Both FROM lines by digest; every pip install from a hashed lock with
    --require-hashes; the runtime lock wheels-only, so no unpinned build
    backend runs; no bare `--upgrade` of tooling.
    """
    text = (ROOT / "Dockerfile").read_text(encoding="utf-8")
    froms = re.findall(r"^FROM\s+(\S+)", text, re.M)
    assert froms, "Dockerfile has no FROM"
    undigested = [f for f in froms if not re.search(r"@sha256:[0-9a-f]{64}$", f)]
    assert not undigested, f"base images not pinned by digest: {undigested}"
    assert len(set(froms)) == 1, f"builder and runtime stages use different bases: {froms}"

    installs = _pip_install_commands(text)
    assert installs, "Dockerfile installs nothing with pip"
    for cmd in installs:
        files = re.findall(r"-r\s+(\S+)", cmd)
        assert files and set(files) <= set(LOCKS), f"Dockerfile pip install not from a lock: {cmd}"
        assert "--require-hashes" in cmd, f"Dockerfile pip install without --require-hashes: {cmd}"
        assert "--upgrade" not in cmd, f"Dockerfile upgrades unpinned tooling: {cmd}"
        if "requirements.txt" in files:
            assert "--only-binary=:all:" in cmd, f"runtime lock may build from source: {cmd}"
    copied = set(re.findall(r"^COPY\s+(.*?)\s+\./\s*$", text, re.M))
    assert any(set(LOCKS) <= set(c.split()) for c in copied), "Dockerfile does not COPY both locks"


def test_build_tool_lock_agrees_with_the_runtime_lock():
    runtime = {canonicalize_name(r.name): next(iter(r.specifier)).version
               for r in _requirements(ROOT / "requirements.txt")}
    clash = [f"{r.name}: build {next(iter(r.specifier)).version}, runtime {runtime[canonicalize_name(r.name)]}"
             for r in _requirements(ROOT / "requirements-build.txt")
             if canonicalize_name(r.name) in runtime
             and runtime[canonicalize_name(r.name)] != next(iter(r.specifier)).version]
    assert not clash, f"the two locks pin the same package differently: {clash}"
