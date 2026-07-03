"""Phase 7: gateway.doctor — a strictly READ-ONLY posture diagnostic.

`python -m gateway.doctor` inspects the loaded config and reports, per
subsystem, whether it is READY, UNCONFIGURED (a credential-gated no-op), or
STUB/degraded. It exists so an operator can answer "what will actually run if
I start the gateway right now?" without starting it.

**Hard guarantees — this tool has NO side effects:**
  - It never signs, never submits a transaction, never spends gas.
  - It never sends a push, an email, an SMS, or any outbound message.
  - It never opens a network connection (config-only introspection).
  - It never writes any file (the one exception, `--write-routes`, only
    regenerates the committed route-table doc and is opt-in).

Exit code: 0 when the posture is internally consistent (every subsystem is
either READY or a deliberate UNCONFIGURED no-op). Non-zero only when a
subsystem is HALF-configured — the honest failure the operator must fix
before go-live (e.g. a bundle id set but no trusted roots).
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent


# ── Config (read-only; no env-override side effects, no secret enforcement) ──

def _load_config_readonly(path: str = "openmatrix.config.json") -> dict:
    p = Path(path)
    if not p.is_absolute():
        p = ROOT / path
    if not p.exists():
        return {}
    try:
        return json.loads(p.read_text())
    except json.JSONDecodeError:
        return {"__invalid_json__": True}


def _filled(value) -> bool:
    """A config value is 'filled' if it is a non-empty string that is not a
    placeholder (`YOUR_...`, `<...>`, `changeme`, `...`)."""
    if not isinstance(value, str):
        return bool(value)
    v = value.strip()
    if not v:
        return False
    low = v.lower()
    return not (v.startswith("YOUR_") or v.startswith("<") or
                low in {"changeme", "...", "todo", "placeholder"})


# ── Checks — each returns (name, status, detail). Pure functions of config. ──

READY, UNCONFIGURED, HALF, STUB = "READY", "UNCONFIGURED", "HALF-CONFIGURED", "STUB"


def check_config_file(config: dict) -> tuple:
    if config.get("__invalid_json__"):
        return ("config file", HALF, "openmatrix.config.json is not valid JSON")
    if not config:
        return ("config file", UNCONFIGURED,
                "no openmatrix.config.json — all features are no-ops (dev default)")
    return ("config file", READY, "loaded")


def check_chain(config: dict) -> tuple:
    chain = config.get("chain") or config.get("blockchain") or {}
    rpc = chain.get("rpc_url") or config.get("rpc_url")
    if not _filled(rpc):
        return ("chain rpc", UNCONFIGURED, "no rpc_url — on-chain routes are no-ops")
    return ("chain rpc", READY, f"rpc configured (chain_id={chain.get('chain_id', '?')})")


def check_paymaster(config: dict) -> tuple:
    pk = ((config.get("paymaster") or {}).get("signer_key", ""))
    if not _filled(pk):
        return ("paymaster signer", UNCONFIGURED,
                "no signer_key — /api/v1/paymaster/sign returns 503")
    return ("paymaster signer", READY, "signer configured (platform key, gas-only)")


def check_iap(config: dict) -> tuple:
    iap = config.get("iap") or {}
    bundle = iap.get("bundle_id", "")
    # Trusted roots: an override list, or the bundled Apple root PEM.
    roots_override = iap.get("trusted_roots_pem")
    bundled_root = (ROOT / "gateway" / "certs" / "AppleRootCA-G3.pem").exists()
    has_roots = bool(roots_override) or bundled_root
    if not _filled(bundle):
        return ("iap verify", UNCONFIGURED,
                "no iap.bundle_id — /api/v1/iap/{verify,asn} return 503")
    if not has_roots:
        return ("iap verify", HALF,
                "bundle_id set but NO trusted roots (missing AppleRootCA-G3.pem) — fix before go-live")
    return ("iap verify", READY, f"bundle={bundle}, pinned root present")


def check_apple_auth(config: dict) -> tuple:
    auth = ((config.get("auth") or {}).get("apple") or {})
    if not _filled(auth.get("bundle_id", "")):
        return ("apple auth", UNCONFIGURED,
                "no auth.apple.bundle_id — /api/v1/auth/apple returns 503")
    revocation = all(_filled(auth.get(k, "")) for k in ("team_id", "key_id", "private_key_p8"))
    detail = "identity verify READY" + (
        "; revocation READY" if revocation else "; revocation SKIPPED (no .p8) — deletion still works")
    return ("apple auth", READY, detail)


def check_push(config: dict) -> tuple:
    apns = config.get("apns") or config.get("push") or {}
    # READ-ONLY: we only report whether APNs is configured. We NEVER send.
    key_path = apns.get("key_path") or apns.get("p8_path") or ""
    if not (_filled(key_path) or _filled(apns.get("key_id", ""))):
        return ("push (apns)", UNCONFIGURED, "no APNs .p8 — push fan-out is a no-op (never sent)")
    return ("push (apns)", READY, "APNs configured (doctor does NOT send — read-only)")


def check_security_backend(config: dict) -> tuple:
    # Static import probe — does NOT construct the verifier or touch state.
    try:
        import importlib.util
        installed = importlib.util.find_spec("morpheus_security") is not None
    except Exception:
        installed = False
    if installed:
        return ("security backend", READY, "morpheus_security installed (real verifier)")
    return ("security backend", STUB,
            "morpheus_security NOT installed — App Attest / OTP soft-fail (noop seam)")


def check_route_table(config: dict) -> tuple:
    try:
        from scripts.generate_route_table import collect  # type: ignore
        routes, public = collect()
        public_count = sum(1 for r in routes if r[1] in public)
        out = ROOT / "docs" / "ROUTES.md"
        fresh = out.exists() and str(len(routes)) in out.read_text()[:400]
        status = READY if fresh else HALF
        detail = f"{len(routes)} routes ({public_count} public)" + (
            "" if fresh else " — docs/ROUTES.md STALE, run scripts/generate_route_table.py")
        return ("route table", status, detail)
    except Exception as exc:
        return ("route table", HALF, f"could not introspect routes: {exc}")


CHECKS = [check_config_file, check_chain, check_paymaster, check_iap,
          check_apple_auth, check_push, check_security_backend, check_route_table]


def run(config: dict) -> list[tuple]:
    return [c(config) for c in CHECKS]


def main() -> int:
    ap = argparse.ArgumentParser(description="Read-only gateway posture diagnostic")
    ap.add_argument("--config", default="openmatrix.config.json")
    ap.add_argument("--json", action="store_true", help="emit machine-readable JSON")
    args = ap.parse_args()

    config = _load_config_readonly(args.config)
    results = run(config)
    half = [r for r in results if r[1] in (HALF,)]

    if args.json:
        print(json.dumps([{"check": n, "status": s, "detail": d} for n, s, d in results], indent=2))
    else:
        print("gateway.doctor — read-only posture (no side effects)\n")
        icon = {READY: "✅", UNCONFIGURED: "⚪", HALF: "❌", STUB: "🟡"}
        for name, status, detail in results:
            print(f"  {icon.get(status, '?')} {name:20} {status:16} {detail}")
        print()
        if half:
            print(f"{len(half)} HALF-CONFIGURED subsystem(s) — fix before go-live:")
            for name, _, detail in half:
                print(f"    - {name}: {detail}")
        else:
            print("Posture consistent: every subsystem is READY or a deliberate no-op.")

    # Non-zero ONLY on a half-configured subsystem (the honest failure).
    return 1 if half else 0


if __name__ == "__main__":
    raise SystemExit(main())
