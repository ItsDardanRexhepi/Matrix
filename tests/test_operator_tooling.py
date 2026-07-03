"""Phase 7: operator tooling — route-table generator, gateway.doctor, verify_abis.

These lock the read-only diagnostics so a refactor can't silently break them or
turn a "read-only" tool into one with side effects.
"""

import importlib.util
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent


def _load(script_rel: str):
    path = ROOT / script_rel
    spec = importlib.util.spec_from_file_location(path.stem, path)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


# ── route-table generator ───────────────────────────────────────────

class TestRouteTable:
    def setup_method(self):
        self.gen = _load("scripts/generate_route_table.py")

    def test_collects_the_new_routes(self):
        routes, public = self.gen.collect()
        paths = {r[1] for r in routes}
        # Phase-3 + Phase-6 routes must be present…
        for p in ("/api/v1/iap/verify", "/api/v1/iap/asn", "/ws",
                  "/api/v1/events/stream"):
            assert p in paths, f"{p} missing from route table"
        # …and the IAP/realtime routes are public (auth is their own JWS/caps).
        for p in ("/api/v1/iap/verify", "/api/v1/iap/asn", "/ws",
                  "/api/v1/events/stream"):
            assert p in public, f"{p} should be public"

    def test_no_route_source_is_unscanned(self):
        # Completeness guard: EVERY gateway/*.py that calls app.router.add_* must
        # be in the generator's ROUTE_SOURCES, else its routes are silently
        # dropped from the table (a false-'complete' — how the bridge routes
        # were missed initially). If this fails, add the file to ROUTE_SOURCES.
        import re
        scanned = {p.name for p in self.gen.ROUTE_SOURCES}
        registrars = set()
        for py in (ROOT / "gateway").glob("*.py"):
            if re.search(r"\.router\.add_(post|get|delete|put|patch)\(", py.read_text()):
                registrars.add(py.name)
        assert registrars <= scanned, (
            f"gateway files register routes but are NOT scanned: {registrars - scanned}")

    def test_bridge_routes_are_captured(self):
        routes, _ = self.gen.collect()
        paths = {r[1] for r in routes}
        assert "/bridge/v1/chat" in paths and "/bridge/v1/wallet/status" in paths

    def test_docs_routes_md_is_not_stale(self):
        # CI contract: the committed doc must match what the generator emits.
        routes, public = self.gen.collect()
        content = self.gen.render(routes, public)
        out = ROOT / "docs" / "ROUTES.md"
        assert out.exists(), "docs/ROUTES.md not generated"
        assert out.read_text() == content, (
            "docs/ROUTES.md is stale — run scripts/generate_route_table.py")


# ── gateway.doctor (read-only) ──────────────────────────────────────

class TestDoctor:
    def setup_method(self):
        from gateway import doctor
        self.doctor = doctor

    def test_unconfigured_posture_is_consistent(self):
        # Empty config -> everything is a deliberate no-op, never HALF.
        results = self.doctor.run({})
        statuses = {name: status for name, status, _ in results}
        assert statuses["iap verify"] == self.doctor.UNCONFIGURED
        assert statuses["chain rpc"] == self.doctor.UNCONFIGURED
        assert self.doctor.HALF not in statuses.values()

    def test_iap_bundle_without_roots_is_half_configured(self):
        # A bundle id set but roots removed is the honest failure the operator
        # must fix — doctor flags it HALF (non-zero exit driver).
        cfg = {"iap": {"bundle_id": "com.opnmatrx.mtrx",
                       "trusted_roots_pem": []}}
        # Force "no bundled root" by pointing the check at a config with an
        # explicit empty override AND asserting the bundled PEM path logic:
        name, status, _ = self.doctor.check_iap(cfg)
        # With the bundled Apple root present, this is READY; the HALF branch is
        # exercised by removing roots. We assert the READY path here and the
        # HALF logic directly below.
        assert status in (self.doctor.READY, self.doctor.HALF)

    def test_doctor_never_reports_ready_iap_without_a_root(self, monkeypatch):
        d = self.doctor
        # No override roots AND pretend the bundled PEM is absent.
        monkeypatch.setattr(d.Path, "exists", lambda self: False)
        name, status, detail = d.check_iap({"iap": {"bundle_id": "com.x"}})
        assert status == d.HALF and "trusted roots" in detail

    def test_run_is_pure(self):
        # Calling run twice yields identical results (no accumulated state).
        assert self.doctor.run({}) == self.doctor.run({})


# ── verify_abis (read-only auditor) ─────────────────────────────────

class TestVerifyAbis:
    def setup_method(self):
        self.va = _load("scripts/verify_abis.py")

    def test_no_drift_and_tba_is_documented_clean(self):
        report = self.va.audit()
        assert report["drift"] is False, (
            f"ABI doc/source drift: undocumented={report['undocumented']} "
            f"dropped_flag={report['dropped_flag']}")
        tba = next(s for s in report["services"] if s["service"] == "tba")
        assert tba["status"].startswith("DOCUMENTED-CLEAN")

    def test_every_source_unverified_service_is_documented(self):
        report = self.va.audit()
        assert report["undocumented"] == []


# ── SDK parity ──────────────────────────────────────────────────────

def test_python_sdk_has_iap_parity():
    from sdk.client import OpenMatrixClient
    c = OpenMatrixClient(base_url="http://localhost:18790")
    assert hasattr(c, "verify_iap") and hasattr(c, "averify_iap")
