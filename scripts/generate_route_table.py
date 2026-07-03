#!/usr/bin/env python3
"""Phase 7: route-table doc generator.

Statically extracts every HTTP route the gateway registers — from both the
``app.router.add_*(...)`` calls (gateway/server.py) and the
``("METHOD", "/path", handler)`` tuple table (gateway/service_routes.py) — and
renders ``docs/ROUTES.md``: method, path, handler, source ``file:line``, and
whether the path is in ``_public_paths`` (no API key required).

Read-only and import-free: it parses source text, so it runs anywhere (CI, a
laptop, a locked-down box) with no model, no network, no app construction.

Usage:
    python scripts/generate_route_table.py           # (re)write docs/ROUTES.md
    python scripts/generate_route_table.py --check    # exit 1 if out of date
"""

from __future__ import annotations

import argparse
import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
SERVER = ROOT / "gateway" / "server.py"
SERVICE_ROUTES = ROOT / "gateway" / "service_routes.py"
BRIDGE = ROOT / "gateway" / "bridge.py"
OUT = ROOT / "docs" / "ROUTES.md"

# Every gateway file that registers routes. If a new module starts calling
# app.router.add_* it MUST be added here — the completeness test asserts no
# gateway/*.py registers routes outside this list.
ROUTE_SOURCES = [SERVER, SERVICE_ROUTES, BRIDGE]

# app.router.add_post("/path", self.handler)  /  add_get / add_delete / add_put
_ADD_RE = re.compile(
    r'\.router\.add_(post|get|delete|put|patch)\(\s*["\']([^"\']+)["\']\s*,\s*self\.(\w+)')
# ("POST", "/api/v1/...", self._handler)
_TUPLE_RE = re.compile(
    r'\(\s*["\'](POST|GET|DELETE|PUT|PATCH)["\']\s*,\s*["\']([^"\']+)["\']\s*,\s*self\.(\w+)')


def _public_paths(text: str) -> set[str]:
    """Extract the route strings inside the ``self._public_paths = {...}`` set.

    Reads the block line by line from the opening ``{`` to its closing ``}``
    and collects only ``/``-prefixed quoted strings — so comment prose and the
    inter-item separators never leak in, and a comment containing a brace can't
    truncate the block early.
    """
    lines = text.splitlines()
    start = next((i for i, ln in enumerate(lines)
                  if re.search(r"self\._public_paths\s*=\s*\{", ln)), None)
    if start is None:
        return set()
    paths: set[str] = set()
    for ln in lines[start:]:
        code = ln.split("#", 1)[0]            # ignore trailing comments
        paths.update(re.findall(r'"(/[^"]*)"', code))
        if "}" in code:                        # closing brace on a code line
            break
    return paths


def _routes_from(path: Path, pattern: re.Pattern) -> list[tuple]:
    out = []
    for i, line in enumerate(path.read_text().splitlines(), start=1):
        m = pattern.search(line)
        if not m:
            continue
        method, route, handler = m.group(1).upper(), m.group(2), m.group(3)
        out.append((method, route, handler, f"{path.name}:{i}"))
    return out


def collect() -> tuple[list[tuple], set[str]]:
    server_text = SERVER.read_text()
    routes: list[tuple] = []
    for src in ROUTE_SOURCES:
        routes += _routes_from(src, _ADD_RE)
    # service_routes.py also registers via a (METHOD, path, handler) tuple table.
    routes += _routes_from(SERVICE_ROUTES, _TUPLE_RE)
    # De-dupe on (method, route): service_routes both add_*'s and tuple-lists the
    # same paths; keep the first source seen.
    seen: dict[tuple, tuple] = {}
    for r in routes:
        key = (r[0], r[1])
        if key not in seen:
            seen[key] = r
    return sorted(seen.values(), key=lambda r: (r[1], r[0])), _public_paths(server_text)


def render(routes: list[tuple], public: set[str]) -> str:
    lines = [
        "# Gateway route table",
        "",
        "> **Generated** by `scripts/generate_route_table.py` — do not edit by hand.",
        "> Run `python scripts/generate_route_table.py` after adding a route;",
        "> CI runs it with `--check` and fails if this file is stale.",
        "",
        f"**{len(routes)} routes.** A **public** route requires no API key "
        "(its own auth applies — e.g. a signed JWS, SIWE, or per-IP caps).",
        "",
        "| Method | Path | Handler | Source | Public |",
        "|---|---|---|---|---|",
    ]
    for method, route, handler, src in routes:
        is_public = "✅" if route in public else ""
        lines.append(f"| {method} | `{route}` | `{handler}` | {src} | {is_public} |")
    lines.append("")
    return "\n".join(lines)


def main() -> int:
    ap = argparse.ArgumentParser(description="Generate docs/ROUTES.md")
    ap.add_argument("--check", action="store_true",
                    help="exit 1 if ROUTES.md is out of date (do not write)")
    args = ap.parse_args()

    routes, public = collect()
    content = render(routes, public)

    if args.check:
        current = OUT.read_text() if OUT.exists() else ""
        if current != content:
            print("docs/ROUTES.md is STALE — run: python scripts/generate_route_table.py",
                  file=sys.stderr)
            return 1
        print(f"docs/ROUTES.md up to date ({len(routes)} routes).")
        return 0

    OUT.parent.mkdir(parents=True, exist_ok=True)
    OUT.write_text(content)
    print(f"Wrote {OUT.relative_to(ROOT)} ({len(routes)} routes, "
          f"{sum(1 for r in routes if r[1] in public)} public).")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
