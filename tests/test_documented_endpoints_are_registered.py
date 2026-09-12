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
