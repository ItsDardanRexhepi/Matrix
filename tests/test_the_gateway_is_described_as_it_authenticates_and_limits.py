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
The same holds for the chat stream's events (the reference described a JSON
fragment with a delta; the gateway sends start, token and done events), every
gateway.<key> a document names (read against the keys the code reads), a
default a document gives (read with what python3 setup.py writes), the session
route count, and a sentence that calls the web pages public (read against the
served pages outside the public set).

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
    r"json fragment with a `?delta",
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
    stream = next(n for n in ast.walk(tree) if isinstance(n, ast.AsyncFunctionDef)
                  and n.name == "handle_chat_stream")
    if "delta" in ast.get_source_segment(source, stream):
        problems.append("the chat stream sends a delta now")
    return problems


def test_the_scan_catches_the_old_text():
    old = ("accepts authorization: bearer <key> or x-api-key: <key>. x-ratelimit-limit: 100. "
           "each api key has rate limits based on its subscription tier. limits are applied using a "
           "sliding window algorithm. the /health and /status endpoints have their own separate, more "
           "generous ip limits. get /status unauthenticated. returns detailed system status. "
           "extended timeouts via the x-timeout header. gateway.request_timeout_seconds` (default 30s). "
           "each event is a json fragment with a `delta` or a terminal `done: true`.")
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


# ── What the documents name as configuration, and what setup writes ─────────
#
# The README said rate limits are "configurable under gateway.rate_limits.wallet",
# and docs/api-reference.md named gateway.ws_max_message_size and
# gateway.ws_heartbeat_seconds; the gateway reads gateway.rate_limit_rpm_wallet
# and its siblings, and gateway.websocket.max_message_size and
# gateway.websocket.heartbeat_seconds. Nothing reads the names the documents
# gave. Every gateway.<key> a document names is read here against the keys the
# code reads.

_NOT_KEYS = {"md", "example"}  # gateway.md, gateway.example.com


def _gateway_keys_read() -> set[str]:
    """Every gateway config key the code reads, dotted for a nested one."""
    keys: set[str] = set()
    files = subprocess.check_output(["git", "ls-files", "*.py"], cwd=ROOT, text=True).splitlines()
    for rel in files:
        if rel.startswith("tests/"):
            continue
        text = (ROOT / rel).read_text(encoding="utf-8")
        if '"gateway"' not in text:
            continue
        keys |= set(re.findall(r'get\("gateway",\s*\{\}\)\.get\("(\w+)"', text))
        for var in set(re.findall(r'(\w+)\s*=\s*(?:self\.)?config\.(?:get|setdefault)\("gateway"', text)):
            keys |= set(re.findall(rf'\b{var}\.get\("(\w+)"', text))
            for sub, key in re.findall(rf'(\w+)\s*=\s*{var}\.get\("(\w+)",\s*\{{\}}\)', text):
                keys |= {f"{key}.{k}" for k in re.findall(rf'\b{sub}\.get\("(\w+)"', text)}
    return keys


def _gateway_keys_named(text: str) -> list[str]:
    modules = {p.stem for p in (ROOT / "gateway").glob("*.py")}
    named = []
    for m in re.finditer(r"\bgateway\.([a-z_*]+(?:\.[a-z_*]+)*)", text):
        key = m.group(1)
        if key.split(".")[0] in modules | _NOT_KEYS:
            continue
        named.append(key)
    return named


def test_the_key_reader_reads_the_gateway():
    read = _gateway_keys_read()
    assert {"api_key", "port", "cors_origins", "rate_limit_rpm_wallet", "request_timeout_seconds",
            "websocket.max_message_size", "websocket.heartbeat_seconds"} <= read, read
    assert _gateway_keys_named("limits under `gateway.rate_limits.wallet`; python -m gateway.server; "
                               "`gateway.ws_heartbeat_seconds`") == ["rate_limits.wallet",
                                                                     "ws_heartbeat_seconds"]


def test_every_gateway_setting_a_document_names_is_one_the_gateway_reads():
    read = _gateway_keys_read()
    out = subprocess.check_output(["git", "ls-files", "*.md", "*.html"], cwd=ROOT, text=True)
    unread = []
    for rel in out.splitlines():
        if rel in _NOT_READ or rel.startswith("tests/") or not (ROOT / rel).is_file():
            continue
        for key in _gateway_keys_named((ROOT / rel).read_text(encoding="utf-8")):
            pattern = "^" + re.escape(key).replace(r"\*", r"\w+") + "$"
            if not any(re.match(pattern, k) for k in read):
                unread.append(f"{rel}: gateway.{key}")
    assert not unread, "documents name gateway settings nothing reads:\n" + "\n".join(unread)


# Course 01 module 03 and the reference gave the code's defaults, no allowed
# origin and 120 requests a minute with a burst of 30, while the course's own
# install path is python3 setup.py, which writes cors_origins ["*"],
# rate_limit_rpm 60 and rate_limit_burst 15. A document that states those
# defaults also states what setup writes.

_STATES_A_DEFAULT = [
    r"cors_origins`?[^.\n]{0,80}\b(?:none|empty) by default",
    r"\bdefaults? (?:are|is) 120 requests",
]


def _what_setup_writes() -> dict:
    import importlib.util
    spec = importlib.util.spec_from_file_location("matrix_setup_gateway_values", ROOT / "setup.py")
    setup = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(setup)
    setup.ask = lambda prompt, default="", **kwargs: default
    for name in ("success", "info", "warn"):
        setattr(setup, name, lambda *a, **k: None)
    config: dict = {}
    setup.configure_gateway(config)
    return config["gateway"]


def test_a_document_that_gives_a_default_gives_what_setup_writes():
    written = _what_setup_writes()
    assert written.get("cors_origins") == ["*"], written
    rpm, burst = written["rate_limit_rpm"], written["rate_limit_burst"]
    out = subprocess.check_output(["git", "ls-files", "*.md", "*.html"], cwd=ROOT, text=True)
    missing = []
    for rel in out.splitlines():
        if rel in _NOT_READ or rel.startswith("tests/") or not (ROOT / rel).is_file():
            continue
        text = (ROOT / rel).read_text(encoding="utf-8")
        for pattern in _STATES_A_DEFAULT:
            for m in re.finditer(pattern, text, re.I):
                around = text[max(0, m.start() - 400):m.end() + 400]
                cors = "cors" in pattern
                wanted = ['setup.py', '["*"]'] if cors else ["setup.py", f"rate_limit_rpm: {rpm}",
                                                             f"rate_limit_burst: {burst}"]
                if not all(w in around for w in wanted):
                    missing.append(f"{rel}: ...{text[m.start():m.end()]}... without {wanted}")
    assert not missing, "\n".join(missing)


# docs/api-reference.md gave the session route list's length as "81 routes at
# the time of writing"; gateway/session_routes.py holds 82.

def test_the_session_route_count_is_the_lists_length():
    from gateway.session_routes import USER_SESSION_ROUTES
    text = (ROOT / "docs" / "api-reference.md").read_text(encoding="utf-8")
    stated = re.findall(r"session_routes\.py[^|]{0,200}?\((\d+) routes", text)
    assert stated, "the reference no longer states the session route count"
    assert all(int(n) == len(USER_SESSION_ROUTES) for n in stated), (stated, len(USER_SESSION_ROUTES))


# Course 01 module 03 said "the web pages are public". The badge page, its status
# and embed routes and the widget script are served pages outside the public
# set, and answer 401 without a credential.

def test_a_sentence_that_calls_the_pages_public_names_the_ones_that_are_not(tmp_path):
    import sys
    sys.path.insert(0, str(ROOT / "tests"))
    from test_curl_examples_carry_the_key import _public_paths
    from scripts.generate_route_table import collect

    source = SERVER.read_text(encoding="utf-8")
    tree = ast.parse(source)
    serving = {n.name for n in ast.walk(tree) if isinstance(n, (ast.FunctionDef, ast.AsyncFunctionDef))
               and re.search(r"_serve_html|text/html|application/javascript",
                             ast.get_source_segment(source, n) or "")}
    routes, _ = collect()
    public = _public_paths(tmp_path)
    gated = sorted({r[1] for r in routes if r[0] == "GET" and r[2] in serving and r[1] not in public})
    assert gated, "every served page is public now; re-derive this check"
    out = subprocess.check_output(["git", "ls-files", "*.md", "*.html"], cwd=ROOT, text=True)
    offenders = []
    for rel in out.splitlines():
        if rel in _NOT_READ or rel.startswith("tests/") or not (ROOT / rel).is_file():
            continue
        flat = _flat((ROOT / rel).read_text(encoding="utf-8"))
        for sentence in re.split(r"(?<=[.!?])\s+", flat):
            if not re.search(r"\bweb pages\b.*\bpublic\b", sentence):
                continue
            if not all(path.split("{")[0].rstrip("/") in sentence for path in gated):
                offenders.append(f"{rel}: ...{sentence.strip()[:160]}... (not public: {gated})")
    assert not offenders, "\n".join(offenders)
