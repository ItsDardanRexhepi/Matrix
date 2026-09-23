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
nothing calls it, and the README's architecture diagram, which drew it
among the protocols between the ReAct loop and the tools, to say it is
never called.

The section's opening line said every user interaction passes through
these protocols "except Omega". Four of them are reached only from the
stack's pre_action, on a tool call, and a turn in which the model calls no
tool never reaches them; the Rexhepi Gate entry below it already said the
reply does not pass through the gate. The second test reads, from the
stack's hooks, which protocols every turn reaches and which only a tool
call reaches, and holds the opening line to that.
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


def _architecture_lines() -> list[str]:
    readme = (REPO / "README.md").read_text()
    return readme.split("## Architecture", 1)[1].split("\n---", 1)[0].splitlines()


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
        name = module.replace("_", " ").title()
        for n, line in enumerate(_architecture_lines(), 1):
            if re.search(rf"\b{re.escape(name)}\b", line) and "never called" not in line:
                wrong.append(f"README.md's architecture diagram names {name} among the "
                             f"protocols a request passes through: {line.strip()!r}")
    assert not wrong, (
        f"the protocol stack constructs {sorted(idle.values())} and never calls "
        f"it: " + "; ".join(wrong))


def _reached_from(hooks: set[str]) -> set[str]:
    """Every ``self._<attr>`` a method is called on inside the named stack hooks."""
    reached = set()
    for fn in ast.walk(ast.parse(INTEGRATION.read_text())):
        if isinstance(fn, (ast.FunctionDef, ast.AsyncFunctionDef)) and fn.name in hooks:
            for node in ast.walk(fn):
                if (isinstance(node, ast.Call) and isinstance(node.func, ast.Attribute)
                        and isinstance(node.func.value, ast.Attribute)
                        and isinstance(node.func.value.value, ast.Name)
                        and node.func.value.value.id == "self"):
                    reached.add(node.func.value.attr)
    return reached


def test_the_opening_line_says_which_protocols_a_turn_reaches():
    built = _constructed_protocols()
    # pre_process runs once a turn before the model is called and post_process
    # once on the reply; pre_action and post_action run around each tool call.
    every_turn = _reached_from({"pre_process", "post_process"}) & set(built)
    tool_call_only = (_reached_from({"pre_action", "_pre_action", "post_action"})
                      & set(built)) - every_turn
    assert "_jarvis" in every_turn and "_rexhepi_gate" in tool_call_only, (
        f"precondition: the hooks are read ({sorted(every_turn)}, {sorted(tool_call_only)})")

    section = (REPO / "README.md").read_text().split("## Protocol Stack", 1)[1]
    opening = section.split("\n**", 1)[0]
    sentences = [s for s in re.split(r"(?<=\.)\s+", " ".join(opening.split())) if s]
    names = {name.lower().replace(" ", "_"): name
             for name in re.findall(r"^\*\*([^*]+)\*\*\s+—", section, re.MULTILINE)}
    turn_sentences = [s for s in sentences if s.startswith("Every turn")]
    tool_sentences = [s for s in sentences if "only on a tool call" in s]

    wrong = []
    if re.search(r"every (user )?(interaction|turn|message)[^.]*passes through these protocols",
                 opening, re.IGNORECASE):
        wrong.append("it says every interaction passes through all of them")
    for attr in sorted(every_turn):
        name = names.get(built[attr], built[attr])
        if not any(name in s for s in turn_sentences):
            wrong.append(f"{name} is reached on every turn and no sentence beginning "
                         f"'Every turn' names it")
    for attr in sorted(tool_call_only):
        name = names.get(built[attr], built[attr])
        if not any(name in s for s in tool_sentences):
            wrong.append(f"{name} is reached only on a tool call and no sentence saying "
                         f"'only on a tool call' names it")
        if any(name in s for s in turn_sentences):
            wrong.append(f"{name} is reached only on a tool call and is named among "
                         f"what every turn reaches")
    assert not wrong, (
        "the Protocol Stack section's opening line does not say which protocols a "
        "turn reaches: " + "; ".join(wrong))
