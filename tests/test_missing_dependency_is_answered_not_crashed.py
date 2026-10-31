"""A handler's own `except` clause must not depend on an import that may not have run.

Both attestation write paths document a third answer beside "attested" and
"failed": when the chain libraries are not installed the call returns
``{"status": "skipped", "reason": "Missing dependency: ..."}`` rather than
reporting a fault. Metering a caller's attestation added an
`except SponsorshipDenied: raise` clause ahead of `except ImportError` in both
bodies (and in EASClient.attest). Had SponsorshipDenied been imported inside
the try, next to `from web3 import Web3`, a missing chain library would make
evaluating that clause raise UnboundLocalError before `except ImportError` is
considered, and the missing-dependency answer could never be produced. It is
imported at module scope; this guards that it stays so.

Two controls, because the line is an instance of a class:

  * BEHAVIOUR — `web3`, `eth_account` or `eth_abi` is made unimportable for
    the duration of one call and both paths are asked for their answer.
  * CLASS — every tracked .py file is parsed and every `try` is checked: no
    `except NAME` may name a symbol that only an import inside that same try
    body binds. It carries its own planted positive so a pass cannot be
    vacuous.

A guard, not a defect control: main never had the clause, so these pass there
too (the revocation case aside, which uses the metered signature).
"""

from __future__ import annotations

import ast
import asyncio
import importlib
import subprocess
import sys
import textwrap
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent

KEY = "0x" + "11" * 32
ADDR = "0x" + "22" * 20
UID = "0x" + "33" * 32

CONFIG: dict = {
    "blockchain": {
        "rpc_url": "http://rpc.invalid",
        "eas_contract": ADDR,
        "eas_schema": UID,
        "paymaster_private_key": KEY,
        "platform_wallet": ADDR,
        "chain_id": 84532,
    }
}


class _BlockImport:
    """A meta-path finder that makes one top-level package unimportable."""

    def __init__(self, blocked: str):
        self.blocked = blocked

    def find_module(self, fullname, path=None):  # pragma: no cover - py2 shim
        return None

    def find_spec(self, fullname, path=None, target=None):
        if fullname == self.blocked or fullname.startswith(self.blocked + "."):
            raise ImportError(f"No module named {fullname!r} (blocked by test)")
        return None


class blocked_import:
    """Context manager: `import <name>` raises ImportError inside the block."""

    def __init__(self, name: str):
        self.name = name
        self._saved: dict[str, object] = {}
        self._finder = _BlockImport(name)

    def __enter__(self):
        for mod in list(sys.modules):
            if mod == self.name or mod.startswith(self.name + "."):
                self._saved[mod] = sys.modules.pop(mod)
        sys.meta_path.insert(0, self._finder)
        importlib.invalidate_caches()
        return self

    def __exit__(self, *exc):
        sys.meta_path.remove(self._finder)
        sys.modules.update(self._saved)
        importlib.invalidate_caches()
        return False


@pytest.mark.parametrize("missing", ["web3", "eth_account", "eth_abi"])
def test_blocking_an_import_actually_blocks_it(missing):
    """The instrument is not a no-op: inside the block the import fails, and
    outside it the module is back."""
    with blocked_import(missing):
        with pytest.raises(ImportError):
            importlib.import_module(missing)
    assert importlib.import_module(missing) is not None


@pytest.mark.parametrize("missing", ["web3", "eth_account", "eth_abi"])
def test_time_critical_attestation_answers_skipped_when_a_chain_library_is_missing(missing):
    from runtime.blockchain.services.attestation.time_critical import TimeCriticalHandler

    handler = TimeCriticalHandler(CONFIG)
    with blocked_import(missing):
        result = asyncio.run(handler.attest_now(
            schema_uid=UID,
            data={"agent": "system"},
            recipient=ADDR,
            category="dispute_filing",
        ))
    assert result["status"] == "skipped", result
    assert "Missing dependency" in result["reason"], result


@pytest.mark.parametrize("missing", ["web3", "eth_account"])
def test_revocation_answers_skipped_when_a_chain_library_is_missing(missing):
    from runtime.blockchain.services.attestation.service import AttestationService

    service = AttestationService(CONFIG)
    with blocked_import(missing):
        result = asyncio.run(service.revoke(UID, UID, caller_identity="user:alice"))
    assert result["status"] == "skipped", result
    assert "Missing dependency" in result["reason"], result


# --- the class, not the line -------------------------------------------------

def _names_bound_by_import(body: list[ast.stmt]) -> dict[str, int]:
    """Local names that only an `import` statement somewhere in `body` binds."""
    names: dict[str, int] = {}
    for node in body:
        for sub in ast.walk(node):
            if isinstance(sub, (ast.Import, ast.ImportFrom)):
                for alias in sub.names:
                    local = alias.asname or alias.name.split(".")[0]
                    names.setdefault(local, sub.lineno)
    return names


def _handler_names(handler: ast.ExceptHandler) -> list[tuple[str, int]]:
    if handler.type is None:
        return []
    parts = handler.type.elts if isinstance(handler.type, ast.Tuple) else [handler.type]
    return [(p.id, p.lineno) for p in parts if isinstance(p, ast.Name)]


def _unbindable_handlers(source: str, rel: str) -> list[str]:
    """`except NAME` where NAME is bound only by an import inside the same try."""
    try:
        tree = ast.parse(source)
    except SyntaxError:
        return []
    offenders = []
    for node in ast.walk(tree):
        if not isinstance(node, ast.Try):
            continue
        imported = _names_bound_by_import(node.body)
        if not imported:
            continue
        for handler in node.handlers:
            for name, lineno in _handler_names(handler):
                if name in imported:
                    offenders.append(
                        f"{rel}:{lineno}: `except {name}` names a symbol bound only by "
                        f"the import at line {imported[name]} inside its own try")
    return offenders


def test_the_unbound_handler_scan_catches_a_planted_case_and_passes_the_safe_shapes():
    """Planted positive and its near misses, so a clean tree is not a vacuous pass."""
    bad = textwrap.dedent("""
        def f():
            try:
                from pkg_a import Thing
                from pkg_b import Denied
                go()
            except Denied:
                raise
            except ImportError:
                return None
    """)
    assert _unbindable_handlers(bad, "planted.py"), "the scan missed the planted case"

    safe_import_outside = textwrap.dedent("""
        from pkg_b import Denied
        def f():
            try:
                from pkg_a import Thing
                go()
            except Denied:
                raise
            except ImportError:
                return None
    """)
    safe_builtin_only = textwrap.dedent("""
        def f():
            try:
                import pkg_a
            except ImportError:
                pkg_a = None
    """)
    safe_nested = textwrap.dedent("""
        def f():
            from pkg_b import Denied
            for x in items:
                try:
                    go(x)
                except Denied:
                    continue
    """)
    for source in (safe_import_outside, safe_builtin_only, safe_nested):
        assert not _unbindable_handlers(source, "safe.py"), source


def test_no_except_clause_names_a_symbol_its_own_try_may_fail_to_bind():
    rels = subprocess.check_output(["git", "ls-files", "*.py"], cwd=ROOT, text=True).split()
    offenders: list[str] = []
    for rel in rels:
        path = ROOT / rel
        if not path.is_file():
            continue
        try:
            source = path.read_text(encoding="utf-8")
        except (UnicodeDecodeError, OSError):
            continue
        offenders.extend(_unbindable_handlers(source, rel))
    assert not offenders, (
        "an except clause names a symbol that only an import inside its own try "
        "binds; if an earlier statement in that try raises, evaluating the clause "
        "raises UnboundLocalError and the later handlers never run. Move the "
        "import above the ones that can fail, or to module scope:\n"
        + "\n".join(offenders))
