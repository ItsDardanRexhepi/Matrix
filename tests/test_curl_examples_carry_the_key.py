"""A curl example in the documents runs as written on a default setup.

setup.py generates a gateway API key unless the operator types 'none', and
with a key set the gateway answers 401 on every path outside its public set
(GatewayServer._public_paths). An example that calls a key-gated path without
the key is refused as written. The README gave three of them: /status and the
two capability listings.

The test reads every curl example aimed at the local gateway in the
repository's files (tests aside) and checks that each one names a route the
gateway registers, and that each one outside the public set, or naming Neo or
Morpheus on a chat entrance, carries the key.
"""
from __future__ import annotations

import re
import subprocess
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent
SUFFIXES = (".md", ".py", ".sh", ".txt", ".yml", ".yaml")
_CONTINUATION = re.compile(r"\\\\?\n[ \t]*")
_CURL = re.compile(
    r"curl\b[^\n`]*?(?:https?://)?(?:localhost|127\.0\.0\.1):(?:18790|\{port\})"
    r"(/[^\s\"'`\\|)]*)")


def _examples():
    files = subprocess.run(["git", "-C", str(REPO), "ls-files"], capture_output=True,
                           text=True, check=True).stdout.split()
    for rel in files:
        if rel.startswith("tests/") or not rel.endswith(SUFFIXES):
            continue
        try:
            text = (REPO / rel).read_text(encoding="utf-8")
        except (OSError, UnicodeDecodeError):
            continue
        joined = _CONTINUATION.sub(" ", text)
        for m in _CURL.finditer(joined):
            end = joined.find("\n", m.start())
            command = joined[m.start():end if end >= 0 else None]
            if command.count("'") % 2 and end >= 0:
                # A -d '...' body that spans lines: read it to its closing quote.
                close = joined.find("'", end)
                command = joined[m.start():close + 1 if close >= 0 else None]
            yield rel, m.group(1).split("?")[0], command


def _public_paths(scratch: Path):
    from gateway.server import GatewayServer

    return frozenset(GatewayServer({"memory_dir": str(scratch),
                                    "database": {"path": str(scratch / "p.db")}})._public_paths)


def _registered(path: str, routes) -> bool:
    for route in routes:
        pattern = "^" + re.sub(r"\{[^}]+\}", "[^/]+", route[1]) + "$"
        if re.match(pattern, path):
            return True
    return False


def test_every_gated_curl_example_carries_the_key(tmp_path):
    from gateway.server import CHAT_ENTRANCES
    from scripts.generate_route_table import collect

    routes, _ = collect()
    public = _public_paths(tmp_path)
    examples = list(_examples())
    assert examples, "no curl example aimed at the local gateway was found"
    assert any(path not in public for _, path, _ in examples), (
        "precondition: some example calls a key-gated path")

    unrouted, keyless = [], []
    for rel, path, command in examples:
        if not _registered(path, routes):
            unrouted.append(f"{rel}: {path}")
        keyed = "Authorization: Bearer" in command or "api_key=" in command
        names_operator_agent = (path in CHAT_ENTRANCES and re.search(
            r'"agent"\s*:\s*"(neo|morpheus)"', command, re.IGNORECASE))
        if (path not in public or names_operator_agent) and not keyed:
            keyless.append(f"{rel}: {path}")
    assert not unrouted, f"curl examples call paths the gateway does not register: {unrouted}"
    assert not keyless, (
        "with the API key setup generates, the gateway refuses these examples as "
        f"written (no Authorization header): {keyless}")
