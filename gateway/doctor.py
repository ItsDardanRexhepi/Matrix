"""Phase 7: gateway.doctor — a strictly READ-ONLY posture diagnostic.

`python -m gateway.doctor` inspects the loaded config and reports, per
subsystem, whether it is READY, UNCONFIGURED (a credential-gated no-op), or
STUB/degraded. It exists so an operator can answer "what will actually run if
I start the gateway right now?" without starting it.

**Hard guarantees — this tool has NO side effects:**
  - It never signs, never submits a transaction, never spends gas.
  - It never sends a push, an email, an SMS, or any outbound message.
  - It never opens a network connection (config-only introspection).
  - It never writes any file. There is no exception. This line used to name
    `--write-routes` as "the one exception"; no such option exists — `main()`
    defines `--config` and `--json`, and argparse exits 2 on anything else.
    Regenerating docs/ROUTES.md is `scripts/generate_route_table.py`'s job and
    this tool only read_text()s the result to test its freshness.

Exit code — the only part of this tool CI reads:
  * 0 when every subsystem is READY, CONFIGURED, or a deliberate UNCONFIGURED
    no-op.
  * 1 when a subsystem is HALF-CONFIGURED — the honest failure the operator
    must fix before go-live (e.g. a bundle id set but no trusted roots).
  * 1 when a STUB subsystem is not a deliberate posture. STUB is a fourth
    status and it used to exit 0, so a go-live gate keyed on this code passed
    while security enforcement was OFF. Two STUB shapes are refused now:
    morpheus_security present on disk but not the live backend (it failed to
    load — a misconfiguration in any environment), and no enforcement at all
    under MATRIX_ENV=production, which check_security_backend itself annotates
    FATAL. morpheus_security is a private package, so a development or public
    checkout without it is the deliberate no-op this still forgives.
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent


# ── Config (read-only; no env-override side effects, no secret enforcement) ──

def _load_config_readonly(path: str = "matrix.config.json") -> dict:
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
# RUN-11: distinct from READY on purpose. READY claims the thing works;
# CONFIGURED claims only that settings are present. Doctor does not dial the
# RPC, so it cannot honestly say more than CONFIGURED about it.
CONFIGURED = "CONFIGURED"


def check_config_file(config: dict) -> tuple:
    if config.get("__invalid_json__"):
        return ("config file", HALF, "matrix.config.json is not valid JSON")
    if not config:
        return ("config file", UNCONFIGURED,
                "no matrix.config.json — all features are no-ops (dev default)")
    return ("config file", READY, "loaded")


def check_chain(config: dict) -> tuple:
    chain = config.get("chain") or config.get("blockchain") or {}
    rpc = chain.get("rpc_url") or config.get("rpc_url")
    if not _filled(rpc):
        return ("chain rpc", UNCONFIGURED, "no rpc_url — on-chain routes are no-ops")
    # RUN-11: reported READY. Doctor never dials the RPC, so all it knows is
    # that a URL is present in config — a dead endpoint or a typo reads exactly
    # the same. READY invites an operator to treat on-chain routes as working;
    # CONFIGURED says only what was actually checked.
    return ("chain rpc", CONFIGURED,
            f"rpc_url set, NOT dialled (chain_id={chain.get('chain_id', '?')})")


def check_paymaster(config: dict) -> tuple:
    # Use the same resolver the /paymaster/sign route uses, so the doctor and the
    # route agree on where the signer key lives (top-level `paymaster`,
    # `blockchain.paymaster`, or the env-bridged `blockchain.paymaster_private_key`).
    from gateway.paymaster import paymaster_config
    pk = (paymaster_config(config).get("signer_key", "") or "")
    if not _filled(pk):
        return ("paymaster signer", UNCONFIGURED,
                "no signer_key — /api/v1/paymaster/sign returns 503")
    # This said READY, "signer configured (platform key, gas-only)". Two
    # overclaims in one string. READY on a `_filled()` check alone is the
    # RUN-11 overclaim CONFIGURED exists for. And "gas-only" is the ON-CHAIN
    # contract's role for the key (MatrixVerifyingPaymaster recovers it only
    # over the sponsorship digest) — not its scope in this codebase. When it
    # is resolved from the shared `blockchain.paymaster_private_key`, it is
    # the same key ~20 modules under runtime/blockchain/ use to sign and
    # broadcast arbitrary value-moving transactions. Doctor reports WHICH
    # slot it came from, because that is the fact that decides the answer.
    dedicated = _resolved_from_a_dedicated_slot(config)
    if dedicated:
        return ("paymaster signer", CONFIGURED,
                "signer from paymaster.signer_key — dedicated to gas "
                "sponsorship, NOT validated against the chain")
    return ("paymaster signer", CONFIGURED,
            "signer fell back to blockchain.paymaster_private_key — the "
            "platform's GENERAL signing key (runtime/blockchain/* signs and "
            "broadcasts value-moving txs with it), not a gas-only key")


def _resolved_from_a_dedicated_slot(config: dict) -> bool:
    """True when signer_key came from a `paymaster` block rather than from the
    shared `blockchain.paymaster_private_key` fallback."""
    cfg = config if isinstance(config, dict) else {}
    blockchain = cfg.get("blockchain")
    blockchain = blockchain if isinstance(blockchain, dict) else {}
    block = cfg.get("paymaster") or blockchain.get("paymaster") or {}
    return bool(isinstance(block, dict) and _filled(block.get("signer_key", "")))


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
    # This said "revocation READY" when the three credentials were filled in.
    # Nothing in this tree revokes an Apple token — gateway/apple_auth.py says
    # so at the top — so READY was doctor repeating a docstring rather than
    # reporting a subsystem. The credentials are still worth reporting: they
    # are half of what the revocation will need, and the operator who filled
    # them in should learn here that the other half is missing.
    revocation = all(_filled(auth.get(k, "")) for k in ("team_id", "key_id", "private_key_p8"))
    detail = "identity verify READY; token revocation NOT implemented " + (
        "(credentials are configured and unused — App Store 5.1.1(v) unmet)"
        if revocation else
        "(and no credentials configured) — local deletion still works")
    return ("apple auth", READY, detail)


def check_push(config: dict) -> tuple:
    """Ask the CHANNEL, because the channel is what sends.

    This read `config["apns"]` or `config["push"]` — a top-level key nothing in
    this repository populates, and which no sender reads. The live sender is
    `runtime/notifications/ios_push.py`, reading `notifications.ios_push`,
    which is the subtree the example config and setup_communications.py both
    write. So the UNCONFIGURED branch was unconditional on every real
    deployment — a gateway posting to api.push.apple.com was told its push
    fan-out "is a no-op (never sent)" — and the READY branch was reachable
    only by hand-writing a block no sender would ever read, which is the same
    drift pointing the other way.

    Reading the channel's own `available` also means the two cannot drift
    apart again: whatever the sender counts as configured is the answer here.
    READ-ONLY, as before — `available` consults config and nothing else, and
    doctor NEVER sends.
    """
    from runtime.notifications.ios_push import iOSPushChannel

    channel = iOSPushChannel(config if isinstance(config, dict) else {})
    if not channel.available:
        return ("push (apns)", UNCONFIGURED,
                "notifications.ios_push incomplete — the iOS push channel "
                "reports itself unavailable and sends nothing")
    return ("push (apns)", CONFIGURED,
            "notifications.ios_push filled — the channel reports itself "
            "available; doctor does NOT send (read-only)")


def check_security_backend(config: dict) -> tuple:
    """Report the backend that is ACTUALLY ACTIVE, not the one that is installed.

    H2/RUN-11: this used `importlib.util.find_spec` — a static probe answering
    "is the package on disk?". That is not the question an operator is asking.
    The seam decides the live backend at import time, and a package that is
    present but fails to load still yields SECURITY_BACKEND == "noop". So doctor
    could report READY while the running gateway had no enforcement at all —
    the tool meant to catch a misconfiguration agreeing with the misconfigured
    system. It now reads the same value the runtime uses.
    """
    from runtime.config.validation import is_production_mode
    from runtime.security import SECURITY_BACKEND

    installed = False
    try:
        import importlib.util

        installed = importlib.util.find_spec("morpheus_security") is not None
    except (ImportError, ModuleNotFoundError, ValueError):
        installed = False

    if SECURITY_BACKEND == "morpheus_security":
        return ("security backend", READY,
                "morpheus_security ACTIVE (real enforcement available)")

    if installed:
        # Present on disk, not the live backend — the divergence the old check
        # could not see, and the one worth shouting about.
        return ("security backend", STUB,
                "morpheus_security is INSTALLED but the live backend is 'noop' — "
                "it failed to load; enforcement is OFF")

    detail = ("morpheus_security NOT installed — App Attest / OTP soft-fail "
              "(noop seam)")
    if is_production_mode():
        detail += " — FATAL in production (MATRIX_ENV=production)"
    return ("security backend", STUB, detail)


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


def _stub_is_a_fault(result: tuple) -> bool:
    """Which STUBs the exit code refuses.

    A STUB that says the package is INSTALLED but not live failed to load, and
    that is a misconfiguration in any environment. A STUB that says enforcement
    is absent is the public/development posture — deliberate — unless
    check_security_backend has already annotated it FATAL, which it does under
    MATRIX_ENV=production.
    """
    detail = str(result[2])
    return "INSTALLED" in detail or "FATAL in production" in detail


CHECKS = [check_config_file, check_chain, check_paymaster, check_iap,
          check_apple_auth, check_push, check_security_backend, check_route_table]


def run(config: dict) -> list[tuple]:
    return [c(config) for c in CHECKS]


def main() -> int:
    ap = argparse.ArgumentParser(description="Read-only gateway posture diagnostic")
    ap.add_argument("--config", default="matrix.config.json")
    ap.add_argument("--json", action="store_true", help="emit machine-readable JSON")
    args = ap.parse_args()

    config = _load_config_readonly(args.config)
    results = run(config)
    half = [r for r in results if r[1] in (HALF,)]
    # STUB is the fourth status and it exited 0 — see the exit-code block at
    # the top of this module for which STUBs are a deliberate posture and
    # which are a misconfiguration the gate must not pass.
    stub_failures = [r for r in results if r[1] == STUB and _stub_is_a_fault(r)]
    failures = half + stub_failures

    if args.json:
        print(json.dumps([{"check": n, "status": s, "detail": d} for n, s, d in results], indent=2))
    else:
        print("gateway.doctor — read-only posture (no side effects)\n")
        icon = {READY: "✅", UNCONFIGURED: "⚪", HALF: "❌", STUB: "🟡"}
        for name, status, detail in results:
            print(f"  {icon.get(status, '?')} {name:20} {status:16} {detail}")
        print()
        if failures:
            print(f"{len(failures)} subsystem(s) to fix before go-live:")
            for name, _, detail in failures:
                print(f"    - {name}: {detail}")
        else:
            print("Posture consistent: every subsystem is READY, CONFIGURED, "
                  "or a deliberate no-op.")

    return 1 if failures else 0


if __name__ == "__main__":
    raise SystemExit(main())
