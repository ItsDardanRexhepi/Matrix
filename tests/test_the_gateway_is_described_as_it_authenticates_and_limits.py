"""What the documents say the gateway reads, sends and limits is what it does.

docs/api-reference.md said the auth middleware accepts "Authorization: Bearer
<key> or X-API-Key: <key>", course 01's gateway module called the two
"equivalent", and nothing in gateway/ reads an X-API-Key header: the key is
read from the bearer token or ?api_key (`_presented_api_key`). The same module
said every response carries X-RateLimit-* headers (the gateway sends none),
that limits use a sliding window per subscription tier (a token bucket, with
one operator key and no tiers), that /health and /status have their own more
generous limits (the limiter counts them like any request), that /status is
unauthenticated (it is behind the key), and that an X-Timeout header extends
the deadline (nothing reads one). The reference gave the timeout as 30 s; the
default is 120 s.

The premises are read from gateway/server.py; the documents are then read.

What this cannot see: a claim about the gateway worded outside these patterns.
"""

from __future__ import annotations

import ast
import re
import subprocess
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
SERVER = ROOT / "gateway" / "server.py"
_NOT_READ = {"CHANGELOG.md", "web/terms.html", "web/privacy.html"}

_CLAIMS = [
    r"x-api-key",
    r"x-ratelimit-",
    r"x-timeout",
    r"sliding window algorithm|rate limit[^.]{0,120}sliding window",
    r"(?:/health|/status)[^.]{0,80}(?:own|separate)[^.]{0,40}(?:more generous|limits)",
    r"get /status\W+unauthenticated",
    r"request_timeout_seconds`?\s*\(default 30s\)",
]


def _flat(text: str) -> str:
    return re.sub(r"\s+", " ", re.sub(r"<[^>]+>", " ", text)).lower()


def _premises() -> list[str]:
    """Why each pattern is false of this gateway; empty when all hold."""
    source = SERVER.read_text(encoding="utf-8")
    gateway = "\n".join(p.read_text(encoding="utf-8") for p in sorted((ROOT / "gateway").glob("*.py")))
    problems = []
    tree = ast.parse(source)
    key_reader = next(n for n in ast.walk(tree)
                      if isinstance(n, ast.FunctionDef) and n.name == "_presented_api_key")
    reader = ast.get_source_segment(source, key_reader)
    if "Authorization" not in reader or "api_key" not in reader:
        problems.append("the key is read some other way now")
    if re.search(r"x-api-key", gateway, re.I):
        problems.append("the gateway reads an X-API-Key header now")
    if re.search(r"x-ratelimit", gateway, re.I):
        problems.append("the gateway sends rate-limit headers now")
    if re.search(r"x-timeout", gateway, re.I):
        problems.append("the gateway reads an X-Timeout header now")
    if "class RateLimiter" not in source or "Token-bucket" not in source:
        problems.append("the limiter is no longer the token bucket")
    public = source[source.index("self._public_paths = {"):]
    public = public[:public.index("\n        }")]
    if '"/status"' in public:
        problems.append("/status is public now")
    limiter = next(n for n in ast.walk(tree) if isinstance(n, ast.AsyncFunctionDef)
                   and n.name == "_rate_limit_middleware")
    if re.search(r"/health|/status", ast.get_source_segment(source, limiter)):
        problems.append("the limiter treats /health or /status apart now")
    if 'request_timeout_seconds", 120' not in source:
        problems.append("the default request timeout is not 120 s now")
    return problems


def test_the_scan_catches_the_old_text():
    old = ("accepts authorization: bearer <key> or x-api-key: <key>. x-ratelimit-limit: 100. "
           "each api key has rate limits based on its subscription tier. limits are applied using a "
           "sliding window algorithm. the /health and /status endpoints have their own separate, more "
           "generous ip limits. get /status unauthenticated. returns detailed system status. "
           "extended timeouts via the x-timeout header. gateway.request_timeout_seconds` (default 30s).")
    hits = {p for p in _CLAIMS if re.search(p, old)}
    assert hits == set(_CLAIMS), set(_CLAIMS) - hits
    assert not any(re.search(p, "the operator key as authorization: bearer <key> or ?api_key=<key>; "
                                "a token bucket; get /status behind the operator key.")
                   for p in _CLAIMS)


def test_no_document_describes_a_header_limit_or_deadline_the_gateway_does_not_have():
    premises = _premises()
    assert not premises, "re-derive this check: " + "; ".join(premises)
    out = subprocess.check_output(["git", "ls-files", "*.md", "*.html"], cwd=ROOT, text=True)
    offenders = []
    for rel in out.splitlines():
        if rel in _NOT_READ or rel.startswith("tests/") or not (ROOT / rel).is_file():
            continue
        flat = _flat((ROOT / rel).read_text(encoding="utf-8"))
        for pattern in _CLAIMS:
            for m in re.finditer(pattern, flat):
                offenders.append(f"{rel}: ...{flat[max(0, m.start() - 50):m.end() + 30]}...")
    assert not offenders, "\n".join(offenders)
