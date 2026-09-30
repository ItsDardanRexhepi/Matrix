"""Course-01's quick start shows the output the gateway actually produces.

Step 3 showed five startup log lines ("[INFO] Agents initialized: Neo,
Trinity, Morpheus", "[INFO] 221 capabilities across 21 categories loaded",
...) that nothing in the gateway logs. Step 4 showed `/health` answering
`{"status": "healthy", "timestamp": ..., "version": ...}` and Step 5 showed
`/status` answering `{"status": "operational", "capabilities": {"total": 221,
...}}`; the handlers answer neither shape. A reader comparing their terminal
with the course would conclude their gateway was broken.

Measured from source, not from the course: the keys of the dict each handler
passes to `web.json_response`, and the message of the startup `logger.info`
in `main()`. The course's JSON blocks must have exactly those keys, and every
log line it shows must be one the gateway writes.
"""

from __future__ import annotations

import ast
import json
import re
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
SERVER = ROOT / "gateway" / "server.py"
QUICK_START = ROOT / "education" / "course-01-intro-to-the-matrix" / "02-quick-start.md"


def _response_keys(handler: str) -> set[str]:
    tree = ast.parse(SERVER.read_text(encoding="utf-8"))
    for node in ast.walk(tree):
        if isinstance(node, ast.AsyncFunctionDef) and node.name == handler:
            for sub in ast.walk(node):
                if (isinstance(sub, ast.Call) and getattr(sub.func, "attr", "") == "json_response"
                        and sub.args and isinstance(sub.args[0], ast.Dict)):
                    return {k.value for k in sub.args[0].keys if isinstance(k, ast.Constant)}
    raise AssertionError(f"{handler} not found or returns no literal dict")


def _logged_messages() -> set[str]:
    source = SERVER.read_text(encoding="utf-8")
    return set(re.findall(r'logger\.(?:info|warning)\(\s*"([^"%]+)"', source))


def _json_block_after(text: str, marker: str) -> dict:
    start = text.index(marker)
    m = re.search(r"```json\n(.*?)```", text[start:], re.S)
    assert m, f"no JSON block after {marker!r}"
    return json.loads(m.group(1))


def test_the_handlers_are_read():
    assert {"status", "agents"} <= _response_keys("handle_health")
    assert {"platform", "uptime_seconds"} <= _response_keys("handle_status")
    assert "The Matrix gateway starting" in _logged_messages()


def test_the_health_and_status_examples_have_the_handlers_keys():
    text = QUICK_START.read_text(encoding="utf-8")
    health = _json_block_after(text, "curl http://localhost:18790/health")
    status = _json_block_after(text, "curl http://localhost:18790/status")
    assert set(health) == _response_keys("handle_health"), sorted(health)
    assert set(status) == _response_keys("handle_status"), sorted(status)


def test_every_startup_line_shown_is_one_the_gateway_logs():
    text = QUICK_START.read_text(encoding="utf-8")
    step3 = text[text.index("## Step 3"):text.index("## Step 4")]
    # fenced blocks with no language tag are the output shown; ```bash is input
    blocks = [body for lang, body in re.findall(r"(?m)^```(\w*)\n(.*?)^```", step3, re.S)
              if not lang]
    shown = [ln.strip() for b in blocks for ln in b.splitlines() if ln.strip()]
    assert shown, "Step 3 shows no output; re-derive this check"
    logged = _logged_messages()
    invented = [ln for ln in shown if not any(msg in ln for msg in logged)]
    assert not invented, f"log lines the gateway does not write: {invented}"
