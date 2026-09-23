"""Every import of this repository's own modules names something that exists.

The service dispatcher imported ``extensions.registry`` for
``service_to_component`` inside ``try: … except Exception: pass``. No such
module has ever existed (extensions/ holds registry.json and schema.json), so
the import failed on every settled action, the bare except swallowed it, and
every feed event was stored with no component, with nothing in any log to say
so. An import that cannot resolve is invisible exactly when it is wrapped in
the handler that would have reported it.

This reads the source rather than importing it, so it sees imports inside
functions and inside ``try`` blocks, which is where these hide, and it needs
none of the optional dependencies installed.
"""

from __future__ import annotations

import ast
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent

# Trees that are not this repository's Python: vendored contract libraries,
# the web front end, and environments.
_SKIP_PARTS = {".git", "web", "node_modules", "lib", ".venv", "venv", "__pycache__"}


def _python_files() -> list[Path]:
    return [
        p for p in ROOT.rglob("*.py")
        if not (set(p.relative_to(ROOT).parts[:-1]) & _SKIP_PARTS)
    ]


def _installed_elsewhere(name: str) -> bool:
    """Is `name` a regular package or module outside this tree? A regular
    package anywhere on the path wins over a namespace directory, so a
    top-level folder with no __init__.py (packaging/) does not shadow the
    installed package of the same name."""
    import importlib.util
    try:
        spec = importlib.util.find_spec(name)
    except (ImportError, ValueError):
        return False
    if spec is None or spec.origin in (None, "namespace"):
        return False
    return ROOT not in Path(spec.origin).resolve().parents


def _first_party_roots() -> set[str]:
    """Top-level names an import resolves into this tree: every root module and
    every top-level directory, including ones with no Python in them, because
    `from extensions import registry` resolves (and fails) against
    extensions/ as a namespace package."""
    roots = {p.stem for p in ROOT.glob("*.py")}
    for d in ROOT.iterdir():
        if d.is_dir() and not d.name.startswith(".") and d.name not in _SKIP_PARTS:
            if (d / "__init__.py").is_file() or not _installed_elsewhere(d.name):
                roots.add(d.name)
    return roots


def _module_path(dotted: str) -> Path | None:
    base = ROOT.joinpath(*dotted.split("."))
    # A package wins over a module of the same name, as it does for Python's
    # own finder: `import setup` is the setup/ package, not setup.py.
    if (base / "__init__.py").is_file():
        return base / "__init__.py"
    if base.with_suffix(".py").is_file():
        return base.with_suffix(".py")
    if base.is_dir():
        return base  # a namespace package
    return None


def _defines(module: Path, name: str) -> bool:
    """Does `from <module> import name` find `name`?"""
    if module.is_dir():  # namespace package: only submodules resolve
        return _module_path(".".join(module.relative_to(ROOT).parts + (name,))) is not None
    pkg_dir = module.parent if module.name == "__init__.py" else None
    if pkg_dir is not None and ((pkg_dir / f"{name}.py").is_file() or (pkg_dir / name).is_dir()):
        return True
    tree = ast.parse(module.read_text(encoding="utf-8", errors="replace"))
    for node in ast.walk(tree):
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef)) and node.name in (name, "__getattr__"):
            return True
        if isinstance(node, (ast.Import, ast.ImportFrom)):
            for alias in node.names:
                if alias.name == "*" or (alias.asname or alias.name.split(".")[0]) == name:
                    return True
        if isinstance(node, (ast.Assign, ast.AnnAssign, ast.AugAssign)):
            targets = node.targets if isinstance(node, ast.Assign) else [node.target]
            for t in targets:
                for n in ast.walk(t):
                    if isinstance(n, ast.Name) and n.id == name:
                        return True
    return False


def _absolute(module: str | None, level: int, path: Path) -> str | None:
    if level == 0:
        return module
    package = list(path.relative_to(ROOT).parts[:-1])
    if level > 1:
        package = package[: len(package) - (level - 1)]
    return ".".join(package + ([module] if module else [])) or None


def test_every_first_party_import_resolves():
    files = _python_files()
    roots = _first_party_roots()
    unresolved: list[str] = []
    for path in files:
        try:
            tree = ast.parse(path.read_text(encoding="utf-8", errors="replace"))
        except SyntaxError:
            continue
        where = path.relative_to(ROOT)
        for node in ast.walk(tree):
            if isinstance(node, ast.Import):
                for alias in node.names:
                    if alias.name.split(".")[0] in roots and _module_path(alias.name) is None:
                        unresolved.append(f"{where}:{node.lineno} import {alias.name}")
            elif isinstance(node, ast.ImportFrom):
                target = _absolute(node.module, node.level, path)
                if not target or target.split(".")[0] not in roots:
                    continue
                module = _module_path(target)
                if module is None:
                    unresolved.append(f"{where}:{node.lineno} from {target} import …")
                    continue
                for alias in node.names:
                    if alias.name != "*" and not _defines(module, alias.name):
                        unresolved.append(f"{where}:{node.lineno} from {target} import {alias.name}")
    assert not unresolved, (
        "imports of this repository's own modules that name nothing:\n  "
        + "\n  ".join(unresolved)
    )
