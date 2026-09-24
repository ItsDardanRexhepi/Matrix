"""What the documents say about the SDKs is what this repository ships.

Course 01's SDK module described a Python client that does not exist:
`MatrixClient(gateway_url=..., api_key=...)` that checks the gateway on
construction, a `ChatResponse` with `request_id` and `tools_used`, a
`chat_stream()` of typed events, `sdk.exceptions` with typed errors,
`connect_ws()` with `requires_confirmation` and `confirm()`, and retry and
timeout options. It and the SDK READMEs said to `pip install the-matrix`,
`pip install matrix-sdk` and `npm install @the-matrix/sdk`. Neither SDK is
published: no workflow in this repository uploads to PyPI or npm, the two PyPI
names belong to unrelated projects, and the npm name is unclaimed. Course 01's
quick start and exercises showed a /chat answer with `request_id`,
`tools_used` and `timestamp` fields and keys prefixed `mtrx_k_`.

Each Python code block in a document that uses MatrixClient is parsed: the
constructor's keywords, the client methods it calls, the `sdk` modules it
imports and the attributes it reads off a chat answer must all exist.

What this cannot see: a JavaScript sample's calls (the TypeScript client is
not loaded here), and a Python sample that builds its client some other way.
"""

from __future__ import annotations

import ast
import dataclasses
import importlib
import inspect
import re
import subprocess
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
_NOT_READ = {"CHANGELOG.md", "web/terms.html", "web/privacy.html"}
_REGISTRY_INSTALL = re.compile(
    r"pip3? install (?:the-matrix|matrix-sdk)\b|npm install @the-matrix/sdk\b", re.I)
_PY_BLOCK = re.compile(r"```python\n(.*?)```", re.S)


def _documents() -> list[str]:
    out = subprocess.check_output(["git", "ls-files", "*.md", "*.html"], cwd=ROOT, text=True)
    return [rel for rel in out.splitlines()
            if rel not in _NOT_READ and not rel.startswith("tests/") and (ROOT / rel).is_file()]


def _nothing_publishes_the_sdks() -> bool:
    workflows = "\n".join(p.read_text(encoding="utf-8")
                          for p in (ROOT / ".github" / "workflows").glob("*.y*ml"))
    return not re.search(r"twine upload|pypi-publish|npm publish", workflows)


def _sentence_around(text: str, start: int, end: int) -> str:
    left = max(text.rfind(".", 0, start), text.rfind("\n\n", 0, start))
    right = min([i for i in (text.find(".", end), text.find("\n\n", end)) if i != -1] or [len(text)])
    return text[left + 1:right]


def test_the_install_scan_sees_an_instruction_and_lets_a_warning_stand():
    text = "```bash\npip install matrix-sdk\n```\n\nDo not `pip install the-matrix`: that name is unrelated."
    found = [m for m in _REGISTRY_INSTALL.finditer(text)
             if not re.search(r"\bdo not\b|not published|unrelated",
                              _sentence_around(text, m.start(), m.end()), re.I)]
    assert [m.group(0) for m in found] == ["pip install matrix-sdk"]


def test_no_document_installs_an_sdk_from_a_registry():
    assert _nothing_publishes_the_sdks(), "a workflow publishes a package now; re-derive this check"
    offenders = []
    for rel in _documents():
        text = (ROOT / rel).read_text(encoding="utf-8")
        for m in _REGISTRY_INSTALL.finditer(text):
            if re.search(r"\bdo not\b|not published|unrelated",
                         _sentence_around(text, m.start(), m.end()), re.I):
                continue
            offenders.append(f"{rel}: {m.group(0)}")
    assert not offenders, "\n".join(offenders)


def _chat_fields() -> set[str]:
    from sdk.client import ChatResponse
    return {f.name for f in dataclasses.fields(ChatResponse)}


def _sample_problems(code: str) -> list[str]:
    from sdk.client import MatrixClient

    try:
        tree = ast.parse(code)
    except SyntaxError:
        return []
    takes = set(inspect.signature(MatrixClient.__init__).parameters) - {"self"}
    clients, answers, problems = set(), set(), []
    for node in ast.walk(tree):
        if isinstance(node, ast.ImportFrom) and (node.module or "").startswith("sdk"):
            try:
                module = importlib.import_module(node.module)
            except ImportError:
                problems.append(f"imports {node.module}, which does not exist")
                continue
            for alias in node.names:
                if not hasattr(module, alias.name):
                    problems.append(f"imports {alias.name} from {node.module}, which has none")
        if isinstance(node, ast.Assign) and isinstance(node.value, ast.Call):
            call = node.value
            if getattr(call.func, "id", "") == "MatrixClient":
                clients |= {t.id for t in node.targets if isinstance(t, ast.Name)}
                for kw in call.keywords:
                    if kw.arg not in takes:
                        problems.append(f"MatrixClient({kw.arg}=...) is not a parameter")
        value = node.value if isinstance(node, (ast.Assign, ast.AnnAssign)) else None
        if isinstance(value, ast.Await):
            value = value.value
        if (isinstance(value, ast.Call) and isinstance(value.func, ast.Attribute)
                and value.func.attr in ("chat", "achat")):
            answers |= {t.id for t in getattr(node, "targets", []) if isinstance(t, ast.Name)}
    for node in ast.walk(tree):
        if isinstance(node, ast.Attribute) and isinstance(node.value, ast.Name):
            if node.value.id in clients and not hasattr(MatrixClient, node.attr) \
                    and node.attr not in ("base_url", "session_id", "api_key"):
                problems.append(f"client.{node.attr} does not exist")
            if node.value.id in answers and node.attr not in _chat_fields():
                problems.append(f"a chat answer has no .{node.attr}")
    return problems


def test_the_sample_reader_catches_the_old_module():
    old = ("from sdk import MatrixClient\nfrom sdk.exceptions import AuthenticationError\n"
           "async def main():\n    client = MatrixClient(gateway_url='x', api_key='k')\n"
           "    response = await client.chat('hi')\n    print(response.request_id, response.tools_used)\n"
           "    async for e in client.chat_stream('x'):\n        pass\n")
    problems = _sample_problems(old)
    assert any("sdk.exceptions" in p for p in problems)
    assert any("gateway_url" in p for p in problems)
    assert any(".request_id" in p for p in problems) and any(".tools_used" in p for p in problems)
    assert any("chat_stream" in p for p in problems)
    assert not _sample_problems("from sdk import MatrixClient\nclient = MatrixClient('x', api_key='k')\n"
                                "r = client.chat('hi')\nprint(r.text, r.tool_calls)\n")


def test_every_python_sdk_sample_uses_what_the_sdk_has():
    problems = []
    for rel in _documents():
        text = (ROOT / rel).read_text(encoding="utf-8")
        for block in _PY_BLOCK.findall(text):
            if "MatrixClient" not in block and "from sdk" not in block:
                continue
            problems += [f"{rel}: {p}" for p in _sample_problems(block)]
    assert not problems, "\n".join(problems)


def _chat_answer_keys() -> set[str]:
    source = (ROOT / "gateway" / "server.py").read_text(encoding="utf-8")
    handler = source[source.index("    async def handle_chat(self"):]
    handler = handler[:handler.index("\n    async def ", 10)]
    last = handler[handler.rindex("web.json_response({"):]
    return set(re.findall(r'^\s+"(\w+)":', last, re.M))


def test_no_document_shows_a_chat_field_or_key_format_the_gateway_does_not_have():
    keys = _chat_answer_keys()
    assert keys == {"response", "tool_calls", "session_id", "agent", "provider"}, keys
    code = "\n".join(p.read_text(encoding="utf-8") for d in ("gateway", "runtime")
                     for p in (ROOT / d).rglob("*.py"))
    code += (ROOT / "setup.py").read_text(encoding="utf-8")
    assert "tools_used" not in code and "mtrx_k_" not in code, "re-derive this check"
    offenders = []
    for rel in _documents():
        text = (ROOT / rel).read_text(encoding="utf-8")
        for m in re.finditer(r"tools_used|mtrx_k_", text):
            offenders.append(f"{rel}: {m.group(0)}")
    assert not offenders, "\n".join(offenders)
