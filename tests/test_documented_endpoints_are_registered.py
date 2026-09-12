"""Every endpoint the public docs and SDK tell a client to call is one the
gateway actually registers.

The API reference kept `POST /subscription/checkout` and
`POST /subscription/webhook` (and `GET /subscription/status`) after the Stripe
integration was removed and subscriptions moved to Apple IAP. A client
following the reference, or the JavaScript SDK's `subscriptionStatus()` and
`checkout()`, got a 404 from aiohttp's router. The same drift had spread: the
reference documented audit, marketplace, A2A, extensions and social paths that
were renamed or never existed; README pointed at `/pricing` and
`POST /referral/generate`; the capability map listed gateway endpoints for
capabilities that are served only through the registry, or were removed from it.

The truth side is derived from source, never from a doc: the registered set is
`scripts/generate_route_table.collect()`, which parses every `add_*` call and
route tuple in the gateway (the same extraction docs/ROUTES.md is generated and
CI-checked from). The doc side is every `METHOD /path` and every
`localhost:18790/path` in the public docs, and every `${baseUrl}/path` the JS
SDK fetches. Path parameters compare by position, not by name.

The web pages the gateway serves are clients too, and the most direct ones: a
page that links or fetches a path sends the visitor's browser there. The first
version of this control only saw `METHOD /path` text, so the plugin-submission
form (`fetch("/marketplace/submit")`), the conversion order form
(`fetch('/services/conversion/request')`) and ten `href="/pricing"` links all
passed it while every one answered 404. Tracked `web/*.html` and `web/*.js` are
now read for root-relative `href`/`src`/`action` attributes, the first literal
argument of `fetch()` / `new EventSource()`, and `*_URL = '/path'` constants.
A literal cut off by string concatenation (`"/badge/" + id`) must be a prefix
of a registered route.

Two files are legal copy that this repository may not edit without counsel
(web/terms.html, web/privacy.html). Their unregistered links are listed
exactly, and the test fails if the list stops matching — in either direction —
so a counsel fix removes the entry rather than leaving a stale exemption.
"""

from __future__ import annotations

import re
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "scripts"))

import generate_route_table  # noqa: E402

# Historical or third-party documents: a changelog records removed routes on
# purpose, and the ABI note documents external protocol APIs, not this gateway.
_NOT_A_CLIENT_CONTRACT = {"CHANGELOG.md", "docs/ROUTES.md", "ABI_VERIFICATION_NEEDED.md"}

_INLINE = re.compile(r"\b(GET|POST|PUT|DELETE|PATCH)`?\s*(?:\|\s*)?`?(/[A-Za-z0-9_{}/.$-]*)")
_LOCAL_URL = re.compile(r"localhost:18790(/[A-Za-z0-9_{}/.$-]*)")
_SDK_FETCH = re.compile(r"\$\{this\.baseUrl\}(/[A-Za-z0-9_{}/.$-]*)")


def _norm(path: str) -> str:
    path = path.split("?")[0].rstrip(".,;:)")
    path = re.sub(r"\$\{[^}]+\}", "{}", path)
    path = re.sub(r"\{[^}]+\}", "{}", path)
    return path.rstrip("/") or "/"


def _registered() -> tuple[set[tuple[str, str]], set[str]]:
    routes, _public = generate_route_table.collect()
    pairs = {(m, _norm(p)) for m, p, *_ in routes}
    return pairs, {p for _, p in pairs}


def _documented() -> list[tuple[str, str, str]]:
    out = subprocess.check_output(["git", "ls-files", "*.md", "*.html", "*.ts"],
                                  cwd=ROOT, text=True)
    found = []
    for rel in out.splitlines():
        if rel in _NOT_A_CLIENT_CONTRACT or not (ROOT / rel).is_file():
            continue
        text = (ROOT / rel).read_text(encoding="utf-8")
        for m in _INLINE.finditer(text):
            path = _norm(m.group(2))
            if path != "/":
                found.append((rel, m.group(1), path))
        for m in _LOCAL_URL.finditer(text):
            path = _norm(m.group(1))
            if path != "/":
                found.append((rel, "ANY", path))
        if rel.endswith(".ts"):
            for m in _SDK_FETCH.finditer(text):
                found.append((rel, "ANY", _norm(m.group(1))))
    return found


def test_the_extraction_sees_the_documented_surface():
    """Planted positive, both sides: the scanner finds endpoints in the docs, and
    a path that is not registered is not in the registered set."""
    documented = _documented()
    pairs, paths = _registered()
    assert len(documented) > 40
    assert ("POST", "/chat") in pairs
    assert "/subscription/checkout" not in paths


def test_every_documented_endpoint_is_registered():
    pairs, paths = _registered()
    missing = sorted({
        f"{rel}: {method} {path}"
        for rel, method, path in _documented()
        if (method == "ANY" and path not in paths)
        or (method != "ANY" and (method, path) not in pairs)
    })
    assert not missing, "documented but not registered (a client gets 404):\n" + "\n".join(missing)


# ── Web pages served by the gateway ─────────────────────────────────────────

_LEGAL_COPY = {"web/terms.html", "web/privacy.html"}
# Unregistered paths in legal copy, carried to counsel as a redline.
_LEGAL_COPY_PENDING_REDLINE = {
    ("web/privacy.html", "/pricing"),
    ("web/terms.html", "/pricing"),
}

_WEB_ATTR = re.compile(r"""\b(?:href|src|action)\s*=\s*(["'])(/(?!/)[^"'\s>]*)""")
_WEB_CALL = re.compile(r"""\b(?:fetch|EventSource)\(\s*(["'`])(/(?!/)[^"'`\s]*)""")
_WEB_CONST = re.compile(r"""\b[A-Z_]*URL\s*=\s*(["'`])(/(?!/)[^"'`\s]*)""")
_WEB_TEMPLATE = re.compile(r"""\bfetch\(\s*`\$\{[^}]+\}(/[^`\s]*)`""")


def _web_links(rel: str, text: str) -> list[tuple[str, str, bool]]:
    """(rel, path, is_prefix) for every root-relative client target in a page."""
    found = []
    for pattern in (_WEB_ATTR, _WEB_CALL, _WEB_CONST, _WEB_TEMPLATE):
        for m in pattern.finditer(text):
            raw = m.group(m.lastindex)
            end = m.end(m.lastindex)
            tail = text[end:end + 12].lstrip()
            # quote or template close followed by concatenation → a prefix
            is_prefix = bool(re.match(r"""["'`]?\s*\+""", tail)) or "${" in raw
            raw = raw.split("${")[0]
            path = raw.split("?")[0].split("#")[0]
            if is_prefix:
                found.append((rel, path, True))
            else:
                found.append((rel, _norm(path), False))
    return found


def _web_pages() -> list[str]:
    out = subprocess.check_output(["git", "ls-files", "web/*.html", "web/*.js"],
                                  cwd=ROOT, text=True)
    return [rel for rel in out.splitlines() if (ROOT / rel).is_file()]


def _unregistered_web_links() -> set[tuple[str, str]]:
    _pairs, paths = _registered()
    missing = set()
    for rel in _web_pages():
        for _rel, path, is_prefix in _web_links(rel, (ROOT / rel).read_text(encoding="utf-8")):
            if is_prefix:
                ok = any(p.startswith(path) or p == _norm(path) for p in paths)
            else:
                ok = path in paths
            if not ok:
                missing.add((rel, path))
    return missing


def test_the_web_extraction_sees_links_fetches_and_prefixes():
    """Planted positive: each extraction shape is seen, and a concatenated
    literal is a prefix, not a whole path."""
    page = (
        '<a href="/pricing">x</a> <form action="/nope/form">'
        'fetch("/marketplace/submit", {method:"POST"}); '
        "fetch('/badge/' + id + '/status'); new EventSource('/social/feed/stream'); "
        "const FEED_URL = '/social/feed'; fetch(`${baseUrl()}/chat/stream`); "
        '<a href="https://example.com/x">external</a> <a href="//cdn/x">proto</a>'
    )
    links = {(p, pre) for _r, p, pre in _web_links("planted.html", page)}
    assert ("/pricing", False) in links
    assert ("/nope/form", False) in links
    assert ("/marketplace/submit", False) in links
    assert ("/badge/", True) in links
    assert ("/social/feed/stream", False) in links
    assert ("/social/feed", False) in links
    assert ("/chat/stream", False) in links
    assert not any("example.com" in p or p.startswith("//") for p, _ in links)
    assert len(_web_pages()) >= 10


def test_every_web_page_link_and_fetch_is_registered():
    missing = {m for m in _unregistered_web_links() if m[0] not in _LEGAL_COPY}
    assert not missing, (
        "served web pages send a browser to paths the gateway does not register "
        "(the visitor gets 404):\n" + "\n".join(f"{r}: {p}" for r, p in sorted(missing)))


def test_legal_copy_unregistered_links_match_the_pending_redline():
    legal = {m for m in _unregistered_web_links() if m[0] in _LEGAL_COPY}
    assert legal == _LEGAL_COPY_PENDING_REDLINE, (
        "legal-copy links no longer match the redline list; update "
        f"_LEGAL_COPY_PENDING_REDLINE. found={sorted(legal)} "
        f"listed={sorted(_LEGAL_COPY_PENDING_REDLINE)}")
