"""A protocol the stack builds and never calls is not described as running.

The README's protocol list called Omega "the synthesis layer" that
"combines all protocol outputs into a single unified agent response — the
orchestration brain". ProtocolStack._init_protocols constructs an
OmegaMind, and nothing ever calls a method on it: the ReAct loop calls the
stack's pre_process, pre_action, post_action and post_process, and none of
them reach it.

The test finds, from runtime/protocols/integration.py, every protocol the
stack constructs and never calls a method on (and that nothing else in the
runtime or the gateway reaches through the stack), and requires the
README's entry for it, and the protocol's own module text, to say that
nothing calls it.
"""
from __future__ import annotations

import ast
import pathlib
import re

REPO = pathlib.Path(__file__).resolve().parent.parent
INTEGRATION = REPO / "runtime/protocols/integration.py"


def _constructed_protocols() -> dict[str, str]:
    """``self._<attr>`` -> the runtime.protocols module its class came from."""
    tree = ast.parse(INTEGRATION.read_text())
    init = next(fn for fn in ast.walk(tree)
                if isinstance(fn, ast.FunctionDef) and fn.name == "_init_protocols")
    imported: dict[str, str] = {}
    for node in ast.walk(init):
        if isinstance(node, ast.ImportFrom) and (node.module or "").startswith("runtime.protocols."):
            for alias in node.names:
                imported[alias.asname or alias.name] = node.module.rsplit(".", 1)[1]
    built: dict[str, str] = {}
    for node in ast.walk(init):
        if (isinstance(node, ast.Assign) and len(node.targets) == 1
                and isinstance(node.targets[0], ast.Attribute)
                and isinstance(node.targets[0].value, ast.Name)
                and node.targets[0].value.id == "self"
                and isinstance(node.value, ast.Call)
                and isinstance(node.value.func, ast.Name)
                and node.value.func.id in imported):
            built[node.targets[0].attr] = imported[node.value.func.id]
    return built


def _attributes_called_on() -> set[str]:
    """Every ``self._<attr>`` a method is called on, anywhere in integration.py."""
    called = set()
    for node in ast.walk(ast.parse(INTEGRATION.read_text())):
        if (isinstance(node, ast.Call) and isinstance(node.func, ast.Attribute)
                and isinstance(node.func.value, ast.Attribute)
                and isinstance(node.func.value.value, ast.Name)
                and node.func.value.value.id == "self"):
            called.add(node.func.value.attr)
    return called


def _reached_elsewhere(attr: str) -> bool:
    pattern = re.compile(r"\." + re.escape(attr) + r"\b")
    for root in ("runtime", "gateway"):
        for path in (REPO / root).rglob("*.py"):
            if path == INTEGRATION:
                continue
            if pattern.search(path.read_text(encoding="utf-8", errors="replace")):
                return True
    return False


def _readme_protocol_entries() -> dict[str, str]:
    readme = (REPO / "README.md").read_text()
    section = readme.split("## Protocol Stack", 1)[1].split("\n---", 1)[0]
    entries = {}
    for line in section.splitlines():
        m = re.match(r"\*\*([^*]+)\*\*\s+—\s+(.*)", line)
        if m:
            entries[m.group(1).strip().lower().replace(" ", "_")] = m.group(2)
    return entries


def test_a_protocol_the_stack_never_calls_is_said_to_be_idle():
    built = _constructed_protocols()
    assert "_jarvis" in built and "_rexhepi_gate" in built, (
        f"precondition: the stack's protocols are found ({sorted(built)})")
    called = _attributes_called_on()
    idle = {attr: module for attr, module in built.items()
            if attr not in called and not _reached_elsewhere(attr)}
    assert not {"_jarvis", "_rexhepi_gate"} & set(idle), (
        "precondition: protocols the stack calls are not counted as idle")

    entries = _readme_protocol_entries()
    wrong = []
    for attr, module in sorted(idle.items()):
        entry = entries.get(module)
        if entry is None:
            wrong.append(f"README.md has no Protocol Stack entry for {module}")
        elif "Nothing calls it" not in entry:
            wrong.append(f"README.md's {module} entry does not say nothing calls it: {entry[:80]}")
        head = " ".join((REPO / f"runtime/protocols/{module}.py").read_text()[:1200].split())
        if "Nothing calls it" not in head:
            wrong.append(f"runtime/protocols/{module}.py does not say nothing calls it")
    assert not wrong, (
        f"the protocol stack constructs {sorted(idle.values())} and never calls "
        f"it: " + "; ".join(wrong))
