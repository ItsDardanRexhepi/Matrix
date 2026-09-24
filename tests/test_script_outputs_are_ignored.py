"""What the scripts write into the working tree is either a tracked file they
regenerate or something git ignores.

scripts/deploy_all.py caches each compiled contract under artifacts/,
scripts/verify_platform.py writes platform_health_report.json, and
scripts/prepare_release.py writes RELEASE_MANIFEST.md, which names the private
files it found, and export/, a copy of the public tree, all at the repository
root. None of them was ignored, so a `git add -A` after running one staged its
output. The paths are derived from the scripts' own writes: an assignment
built from the repository root with `/`, then opened for writing, written or
made as a directory. The verdict is git's `check-ignore` against this
repository's rules with global excludes switched off. A path the scripts
regenerate on purpose (docs/ROUTES.md, CHANGELOG.md) is tracked, and passes as
tracked. `npm install` next to a tracked package.json writes node_modules/
there, and that is checked the same way.
"""

from __future__ import annotations

import ast
import os
import shutil
import subprocess
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent
GIT = shutil.which("git")
ROOT_NAMES = {"PROJECT_ROOT", "ROOT", "REPO_ROOT", "WORKSPACE", "workspace"}


def _in_git_checkout() -> bool:
    if GIT is None:
        return False
    return subprocess.run(
        [GIT, "-C", str(ROOT), "rev-parse", "--is-inside-work-tree"],
        capture_output=True, text=True,
    ).stdout.strip() == "true"


pytestmark = pytest.mark.skipif(not _in_git_checkout(), reason="needs a git checkout and git")

_GIT_ENV = {**os.environ, "GIT_CONFIG_GLOBAL": os.devnull, "GIT_CONFIG_NOSYSTEM": "1"}


def _git(*args: str) -> subprocess.CompletedProcess:
    return subprocess.run([GIT, "-C", str(ROOT), *args], capture_output=True, text=True,
                          env=_GIT_ENV)


def _relative(node: ast.AST, scope: dict) -> str | None:
    """The repository-relative path of `base / "x" / f"y"`, or None."""
    parts = []
    while isinstance(node, ast.BinOp) and isinstance(node.op, ast.Div):
        right = node.right
        if isinstance(right, ast.Constant) and isinstance(right.value, str):
            parts.append(right.value)
        elif isinstance(right, ast.JoinedStr):
            parts.append("".join(v.value if isinstance(v, ast.Constant) else "sample"
                                 for v in right.values))
        else:
            return None
        node = node.left
    if isinstance(node, ast.Name):
        if node.id in ROOT_NAMES:
            return "/".join(reversed(parts)) or None
        if node.id in scope:
            return "/".join([scope[node.id], *reversed(parts)])
    return None


def _written_by(path: Path) -> set[str]:
    tree = ast.parse(path.read_text(encoding="utf-8"))
    written: set[str] = set()
    module_scope: dict = {}
    for node in tree.body:
        if isinstance(node, ast.Assign) and len(node.targets) == 1 \
                and isinstance(node.targets[0], ast.Name):
            rel = _relative(node.value, module_scope)
            if rel:
                module_scope[node.targets[0].id] = rel
    scopes = [(tree, module_scope)]
    for fn in ast.walk(tree):
        if isinstance(fn, (ast.FunctionDef, ast.AsyncFunctionDef)):
            scope = dict(module_scope)
            for node in ast.walk(fn):
                if isinstance(node, ast.Assign) and len(node.targets) == 1 \
                        and isinstance(node.targets[0], ast.Name):
                    rel = _relative(node.value, scope)
                    if rel:
                        scope[node.targets[0].id] = rel
            scopes.append((fn, scope))
    for owner, scope in scopes:
        for node in ast.walk(owner):
            if not isinstance(node, ast.Call):
                continue
            func, target, is_dir = node.func, None, False
            if isinstance(func, ast.Name) and func.id == "open" and node.args:
                mode = node.args[1] if len(node.args) > 1 else next(
                    (k.value for k in node.keywords if k.arg == "mode"), None)
                if isinstance(mode, ast.Constant) and str(mode.value)[:1] in ("w", "a", "x"):
                    target = node.args[0]
            elif isinstance(func, ast.Attribute) and func.attr in (
                    "write_text", "write_bytes", "mkdir"):
                target, is_dir = func.value, func.attr == "mkdir"
            if target is None:
                continue
            rel = scope.get(target.id) if isinstance(target, ast.Name) else _relative(target, scope)
            if rel:
                written.add(rel + ("/sample" if is_dir else ""))
    return written


def _script_outputs() -> dict[str, str]:
    outputs = {}
    for path in sorted((ROOT / "scripts").glob("*.py")):
        for rel in _written_by(path):
            outputs[rel] = str(path.relative_to(ROOT))
    for manifest in _git("ls-files", "*package.json").stdout.split():
        folder = str(Path(manifest).parent)
        rel = "node_modules/sample" if folder == "." else f"{folder}/node_modules/sample"
        outputs[rel] = f"npm install ({manifest})"
    return outputs


def test_the_derivation_sees_the_scripts_writes():
    outputs = _script_outputs()
    for expected in ("docs/ROUTES.md", "artifacts/sample.json", "RELEASE_MANIFEST.md"):
        assert expected in outputs, (
            f"the derivation no longer finds {expected}; it found {sorted(outputs)}")


def test_script_outputs_are_tracked_or_ignored():
    committable = []
    for rel, writer in sorted(_script_outputs().items()):
        if _git("ls-files", "--", rel).stdout.strip():
            continue
        if _git("check-ignore", "--no-index", "-q", rel).returncode != 0:
            committable.append(f"{rel} ({writer})")
    assert not committable, (
        "these are written into the tree, are not tracked, and git would let a "
        f"`git add -A` stage them: {committable}")
