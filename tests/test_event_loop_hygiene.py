"""No retiring event-loop API, and no event loop nobody can close.

c902961 swept `asyncio.get_event_loop().run_until_complete(...)` out of three
test fixtures in favour of `asyncio.run`. The same family survived in a second
spelling — `asyncio.get_event_loop_policy().new_event_loop().run_until_complete(...)`
— which is worse on both axes:

  * `asyncio.get_event_loop_policy` is deprecated (Python 3.14) and slated for
    removal, so the suite breaks on a future interpreter for a reason unrelated
    to anything it tests.
  * the loop is created inline and never bound to a name, so nothing can close
    it. Measured under `-W error::ResourceWarning`, each site run alone:
    test_no_deployment_claims::test_smart_contract_deploy_action_refuses_... and
    test_contract_deploy_501::test_sdk_wrapper_refuses_rather_than_pretending
    each reported "unclosed event loop <_UnixSelectorEventLoop ...>"; after, 0.

The replacements are `asyncio.run` where the helper is synchronous, and a plain
`async def` test where the test only needed one await. Not `asyncio.run` in
test_contract_deploy_501: that module's earlier tests are async, and
asyncio.run's teardown (`set_event_loop(None)`) orphans the loop pytest-asyncio
left installed — measured, still one unclosed loop for the file.

Asserted on the AST, not on text, so a comment or a docstring naming the API
(this one does) cannot trip it and reformatting cannot hide a call.
"""
from __future__ import annotations

import ast
import pathlib

ROOT = pathlib.Path(__file__).resolve().parents[1]
SCANNED = ("tests", "runtime", "gateway", "hivemind", "cli", "sdk", "bridge",
           "skills", "scripts", "setup", "migration", "examples")


def _python_files():
    for top in SCANNED:
        base = ROOT / top
        if not base.is_dir():
            continue
        for path in sorted(base.rglob("*.py")):
            if "__pycache__" not in path.parts:
                yield path


def _attr_name(node: ast.AST) -> str | None:
    return node.attr if isinstance(node, ast.Attribute) else (
        node.id if isinstance(node, ast.Name) else None)


def _offenders():
    found: list[str] = []
    for path in _python_files():
        try:
            tree = ast.parse(path.read_text(encoding="utf-8"))
        except SyntaxError:
            continue
        rel = path.relative_to(ROOT)
        for node in ast.walk(tree):
            if not isinstance(node, ast.Call):
                continue
            name = _attr_name(node.func)
            if name == "get_event_loop_policy":
                found.append(f"{rel}:{node.lineno} calls get_event_loop_policy()")
            # `new_event_loop().<anything>(...)`: the loop is used without ever
            # being bound, so it can never be closed.
            if (isinstance(node.func, ast.Attribute)
                    and isinstance(node.func.value, ast.Call)
                    and _attr_name(node.func.value.func) == "new_event_loop"):
                found.append(f"{rel}:{node.lineno} uses an unbound new_event_loop()")
    return found


def test_no_retiring_or_unclosable_event_loop_use():
    offenders = _offenders()
    assert not offenders, (
        "use asyncio.run(...) or an async test — never a loop nobody closes:\n  "
        + "\n  ".join(offenders)
    )
