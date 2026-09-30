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

Each JavaScript or TypeScript block that uses MatrixClient is read against the
TypeScript sources: the constructor's options, the client methods it calls and
the fields it reads off an answer whose type the method declares.

What this cannot see: a sample that builds its client some other way, and a
JavaScript answer whose type the client does not declare.
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


# ── The JavaScript samples ──────────────────────────────────────────────────
#
# docs/api-reference.md's JavaScript sample printed `response.text` after
# `await client.chat(...)`. The TypeScript SDK's chat() resolves to a
# ChatResponse (sdk-js/src/types.ts) with response, tool_calls, session_id,
# agent and provider, and no text, so the sample printed undefined. Each
# JavaScript or TypeScript block that uses MatrixClient is read against the
# SDK's own sources: the constructor's options, the client methods it calls,
# and the fields it reads off an answer whose type the method declares.

_JS_BLOCK = re.compile(r"```(?:typescript|javascript|ts|js)\n(.*?)```", re.S)


def _js_interfaces() -> dict[str, set[str]]:
    text = (ROOT / "sdk-js" / "src" / "types.ts").read_text(encoding="utf-8")
    return {m.group(1): set(re.findall(r"^\s+(\w+)\??\s*:", m.group(2), re.M))
            for m in re.finditer(r"export interface (\w+)\s*\{(.*?)\n\}", text, re.S)}


def _js_client() -> tuple[dict[str, str], set[str]]:
    """MatrixClient's methods, each with the type its promise resolves to, and
    the names its constructor's options take."""
    text = (ROOT / "sdk-js" / "src" / "client.ts").read_text(encoding="utf-8")
    body = text[text.index("export class MatrixClient"):]
    end = body.find("\nexport ", 10)
    body = body if end == -1 else body[:end]
    methods = {m.group(1): m.group(3) or "" for m in re.finditer(
        r"^  (?:(?:async|public|private|protected|static)\s+)*(\w+)\s*\(([^)]*)\)\s*(?::\s*Promise<(\w+)>)?",
        body, re.M | re.S) if m.group(1) not in ("if", "for", "while", "switch", "catch")}
    ctor = re.search(r"constructor\s*\((.*?)\)\s*\{", body, re.S).group(1)
    options = set(re.findall(r"^\s+(\w+)\??\s*:", ctor[ctor.index("options"):], re.M))
    return methods, options


def _js_sample_problems(code: str) -> list[str]:
    interfaces = _js_interfaces()
    methods, options = _js_client()
    code = re.sub(r"(?<![:\w])//[^\n]*|/\*.*?\*/", "", code, flags=re.S)  # comments, not URLs
    problems, clients, answers = [], set(), {}
    for m in re.finditer(r"(?:const|let|var)\s+(\w+)\s*=\s*new MatrixClient\(([^;]*?)\);", code, re.S):
        clients.add(m.group(1))
        opts = re.search(r"\{(.*)\}", m.group(2), re.S)
        for key in re.findall(r"(\w+)\s*:", opts.group(1) if opts else ""):
            if key not in options:
                problems.append(f"new MatrixClient(..., {{{key}}}) is not an option")
    for client in clients:
        for call in re.findall(rf"\b{client}\.(\w+)\s*\(", code):
            if call not in methods:
                problems.append(f"client.{call}() does not exist")
        for m in re.finditer(rf"(?:const|let|var)\s+(\w+)\s*=\s*await\s+{client}\.(\w+)\s*\(", code):
            if methods.get(m.group(2)) in interfaces:
                answers[m.group(1)] = methods[m.group(2)]
    for answer, kind in answers.items():
        for field in re.findall(rf"\b{answer}\.(\w+)", code):
            if field not in interfaces[kind]:
                problems.append(f"a {kind} has no .{field}")
    return problems


def test_the_javascript_sample_reader_catches_the_old_sample():
    old = ("import { MatrixClient } from '@the-matrix/sdk';\n"
           "const client = new MatrixClient('http://localhost:18790', { apiKey: 'K', gatewayUrl: 'x' });\n"
           "const response = await client.chat('What can you help me with?');\n"
           "console.log(response.text);\nawait client.deployContract('x');\n")
    problems = _js_sample_problems(old)
    assert "a ChatResponse has no .text" in problems
    assert any("gatewayUrl" in p for p in problems) and any("deployContract" in p for p in problems)
    assert not _js_sample_problems("const client = new MatrixClient('http://x', {\n  apiKey: 'K',  // optional: a key\n});\n"
                                   "const r = await client.chat('hi');\nconsole.log(r.response, r.tool_calls);\n")


def test_every_javascript_sdk_sample_uses_what_the_sdk_has():
    methods, options = _js_client()
    assert {"chat", "chatStream", "health", "status"} <= set(methods) and "apiKey" in options, (
        "the reader no longer reads the TypeScript client; re-derive this check")
    problems = []
    for rel in _documents():
        text = (ROOT / rel).read_text(encoding="utf-8")
        for block in _JS_BLOCK.findall(text):
            if "MatrixClient" in block:
                problems += [f"{rel}: {p}" for p in _js_sample_problems(block)]
    assert not problems, "\n".join(problems)
