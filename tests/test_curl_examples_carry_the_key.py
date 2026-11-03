"""A curl example in the documents runs as written on a default setup.

setup.py generates a gateway API key unless the operator types 'none', and
with a key set the gateway answers 401 on every path outside its public set
(GatewayServer._public_paths). An example that calls a key-gated path without
the key is refused as written. The README gave three of them: /status and the
two capability listings.

The test reads every curl example aimed at the local gateway in the
repository's files (tests aside) and checks that each one names a route the
gateway registers, and that each one outside the public set, or naming Neo or
Morpheus on a chat entrance, carries the key. A conversion example must convert
a contract (one that elides its source or reads it from a file is not run), and
no example or page may offer a conversion through an anonymous chat, which a
gateway with a key set refuses.
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


# The README's "Try It Now: Convert a contract" sent Trinity a description in
# prose ("Convert this rental agreement into a smart contract: Monthly rent of
# $2000, ...") with no key. The converter reads pseudocode, Solidity or Vyper:
# that text, read as pseudocode, comes back partial, with an empty contract
# named GeneratedContract and an audit that does not apply. And on a gateway
# with a key set, which setup makes by default, an anonymous chat caller is
# refused convert_contract, so the sample could not produce a conversion as
# written. web/conversion-service.html and course 01 module 05 offered the chat
# conversion with no credential either.

def _body(command: str) -> dict | None:
    import json
    m = re.search(r"-d\s+'(.*)'", command, re.S)
    if not m:
        return None
    try:
        return json.loads(m.group(1))
    except ValueError:
        return None


def _converts(source_code: str, source_lang: str) -> dict:
    import asyncio
    from runtime.blockchain.services.contract_conversion.service import ContractConversionService
    return asyncio.run(ContractConversionService({}).convert(source_code=source_code,
                                                             source_lang=source_lang))


def _anonymous_chat_is_refused_a_conversion() -> bool:
    from gateway.session_routes import caller_refused_route
    return (caller_refused_route("anonymous", "convert_contract") is not None
            and caller_refused_route("session", "convert_contract") is None)


def test_the_old_sample_converts_nothing():
    old = ("Convert this rental agreement into a smart contract: Monthly rent of $2000, 12 month "
           "term, $4000 security deposit, late fee of $100 after 5 days")
    result = _converts(old, "pseudocode")
    assert result["status"] != "success" and not result["audit_passed"], result["status"]
    assert _anonymous_chat_is_refused_a_conversion()


def test_every_conversion_example_converts_a_contract():
    examples = [(rel, command) for rel, path, command in _examples()
                if path == "/api/v1/contracts/convert"]
    assert examples, "no curl example calls the conversion route"
    failures, run = [], 0
    for rel, command in examples:
        if re.search(r"-d\s+@", command):
            continue  # the source is read from a file, not written in the example
        body = _body(command)
        if body is None:
            failures.append(f"{rel}: the example's body is not JSON")
            continue
        if "..." in body["source_code"]:
            continue  # an elided source shows the request's shape, not a contract
        run += 1
        result = _converts(body["source_code"], body["source_lang"])
        if result["status"] != "success" or "function " not in result.get("generated_source", ""):
            failures.append(f"{rel}: the example's source converts as {result['status']}, "
                            f"contract {result.get('contract_name')}")
    assert run, "no conversion example writes out its source; re-derive this check"
    assert not failures, "\n".join(failures)


def test_no_example_asks_an_anonymous_chat_for_a_conversion():
    from gateway.server import CHAT_ENTRANCES
    assert _anonymous_chat_is_refused_a_conversion(), "re-derive this check"
    offenders = []
    for rel, path, command in _examples():
        keyed = "Authorization: Bearer" in command or "api_key=" in command
        body = _body(command) or {}
        if path in CHAT_ENTRANCES and not keyed and re.search(
                r"\bconvert\b", str(body.get("message", "")), re.I):
            offenders.append(f"{rel}: {str(body.get('message'))[:80]}")
    out = subprocess.run(["git", "-C", str(REPO), "ls-files", "*.md", "*.html"], capture_output=True,
                         text=True, check=True).stdout.split()
    for rel in out:
        if rel.startswith("tests/") or rel in ("CHANGELOG.md", "web/terms.html", "web/privacy.html"):
            continue
        flat = re.sub(r"\s+", " ", re.sub(r"<[^>]+>", " ", (REPO / rel).read_text(encoding="utf-8")))
        for sentence in re.split(r"(?<=[.!?])\s+", flat):
            trinity = re.search(r"\b(?:ask|asks) trinity\b|\btrinity converts\b", sentence, re.I)
            # The credential has to be the chat's: a key named for the REST
            # route earlier in the sentence does not reach Trinity.
            if (trinity and re.search(r"\bconver(?:t|sion)", sentence, re.I)
                    and not re.search(r"\bkey\b|\bsession\b", sentence[trinity.start():], re.I)):
                offenders.append(f"{rel}: {sentence.strip()[:140]}")
    assert not offenders, (
        "an anonymous chat caller is refused convert_contract on a gateway with a key set, "
        "and these offer it with no credential:\n" + "\n".join(offenders))
