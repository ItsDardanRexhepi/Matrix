"""H2 / RUN-11 — the security seam must not disarm itself quietly.

Three related dishonesties, all in the same direction: the system reporting more
security than it has.

1. `runtime/security/__init__.py` caught `except Exception` around the import of
   the private enforcement core. That conflates "not installed" (legitimate —
   dev, CI and the open checkout all run this way) with "installed and broken"
   (a security core that blew up loading). The second silently became an inert
   OBSERVE no-op, so a broken enforcement layer looked exactly like an absent
   one and the gateway came up reporting itself fine.

2. `gateway/doctor.py` answered the question "is morpheus_security on disk?"
   using `find_spec`, and printed READY. The runtime decides the live backend at
   import time, so a package present-but-unloadable gave doctor READY while the
   process ran with no enforcement — the diagnostic tool agreeing with the
   misconfigured system it exists to catch.

3. Doctor called a configured RPC URL READY. It never dials it, so a dead
   endpoint and a typo read identically.
"""

from __future__ import annotations

import ast
import pathlib

import pytest

ROOT = pathlib.Path(__file__).resolve().parents[1]


# ── 1. the import guard ────────────────────────────────────────────────────

def test_security_import_guard_only_catches_import_errors():
    """A broken security core must crash, not silently disarm.

    Asserted structurally on the AST rather than by string match, so
    reformatting cannot make it pass vacuously.
    """
    src = (ROOT / "runtime" / "security" / "__init__.py").read_text()
    tree = ast.parse(src)

    guards = [
        node for node in tree.body
        if isinstance(node, ast.Try)
        and any(
            isinstance(n, (ast.Import, ast.ImportFrom))
            for n in ast.walk(node)
        )
    ]
    assert guards, "no import guard found — the seam has changed shape"

    for guard in guards:
        for handler in guard.handlers:
            assert handler.type is not None, (
                "bare `except:` on the security import — any failure would "
                "silently disable enforcement"
            )
            names = (
                [n.id for n in handler.type.elts if isinstance(n, ast.Name)]
                if isinstance(handler.type, ast.Tuple)
                else [handler.type.id] if isinstance(handler.type, ast.Name)
                else []
            )
            assert names, f"unreadable handler type: {ast.dump(handler.type)}"
            assert set(names) <= {"ImportError", "ModuleNotFoundError"}, (
                f"security import falls back on {names} — only a genuinely "
                "absent package may degrade to the no-op backend; anything "
                "else is a broken security core and must propagate"
            )


# ── 2. doctor reports the LIVE backend ─────────────────────────────────────

def test_doctor_reads_the_runtime_backend_not_the_filesystem():
    """The check must consult SECURITY_BACKEND, not just find_spec."""
    src = (ROOT / "gateway" / "doctor.py").read_text()
    fn_start = src.index("def check_security_backend")
    fn_end = src.index("\ndef ", fn_start + 1)
    body = src[fn_start:fn_end]

    assert "SECURITY_BACKEND" in body, (
        "doctor still answers 'is the package installed?' rather than "
        "'which backend is actually running?'"
    )


def test_doctor_flags_installed_but_inactive_as_a_problem(monkeypatch):
    """The divergence the old check structurally could not see."""
    import gateway.doctor as doctor

    monkeypatch.setattr("runtime.security.SECURITY_BACKEND", "noop", raising=False)
    monkeypatch.setattr(
        "importlib.util.find_spec", lambda name: object() if name == "morpheus_security" else None
    )

    name, status, detail = doctor.check_security_backend({})
    assert status != doctor.READY, "installed-but-inactive reported as READY"
    assert "INSTALLED" in detail and "noop" in detail, detail


def test_doctor_reports_ready_only_when_the_backend_is_live(monkeypatch):
    import gateway.doctor as doctor

    monkeypatch.setattr(
        "runtime.security.SECURITY_BACKEND", "morpheus_security", raising=False
    )
    _, status, detail = doctor.check_security_backend({})
    assert status == doctor.READY
    assert "ACTIVE" in detail


# ── 3. configured is not ready ─────────────────────────────────────────────

def test_doctor_does_not_call_an_undialled_rpc_ready():
    import gateway.doctor as doctor

    _, status, detail = doctor.check_chain(
        {"chain": {"rpc_url": "https://not-dialled.invalid", "chain_id": 8453}}
    )
    assert status == doctor.CONFIGURED, (
        f"an unverified RPC URL reported as {status} — doctor never dials it"
    )
    assert status != doctor.READY
    assert "NOT dialled" in detail


# ── 4. production refuses to boot without enforcement ──────────────────────

def test_production_refuses_to_start_with_a_noop_security_backend(monkeypatch):
    """/ready takes such an instance out of rotation, but that is the SECOND
    line of defence — it depends on something actually probing it. A process
    that runs is a process something can reach, so production refuses to boot.
    """
    import sys

    sys.path.insert(0, "tests")
    from test_route_sweep import SWEEP_CONFIG

    from gateway.server import GatewayServer

    monkeypatch.setenv("OPNMATRX_ENV", "production")
    monkeypatch.setattr("runtime.security.SECURITY_BACKEND", "noop", raising=False)

    with pytest.raises(RuntimeError, match="Refusing to start"):
        GatewayServer(SWEEP_CONFIG)


def test_non_production_still_starts_with_the_noop_backend(monkeypatch):
    """Fail-closed must not become fail-always: dev, CI and the open-source
    checkout all legitimately run without the private package."""
    import sys

    sys.path.insert(0, "tests")
    from test_route_sweep import SWEEP_CONFIG

    from gateway.server import GatewayServer

    monkeypatch.delenv("OPNMATRX_ENV", raising=False)
    server = GatewayServer(SWEEP_CONFIG)
    assert server is not None
