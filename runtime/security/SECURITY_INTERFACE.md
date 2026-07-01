# Security Interface

This directory is the **seam** to 0pnMatrx's closed-source security layer. It is
a boundary, not an implementation: `__init__.py` exposes the security contract
the platform calls and binds it to the private security package when that package
is installed. The rules — how the layer detects, classifies, bans, verifies
owners, or sanitizes — are **not in this repository** and never will be.

## What the platform sees

- A security gate is obtained via `from runtime.security import get_morpheus_security`
  and consulted **first** in
  `runtime/protocols/integration.py::ProtocolStack.pre_action`, ahead of
  `RexhepiGate`, so every execution path passes it before any privileged action.
- `gate.evaluate(action, context)` returns an allow/deny decision. The gate is
  **authoritative server-side** — app-side checks are UX only.
- OTP / owner-verification services are obtained the same way
  (`from runtime.security import OTPService, OwnerVerification`) and back the
  `/security/...` endpoints and the bridge approval gate.

## Two backends

- **`morpheus_security` installed** → real enforcement (the private package,
  co-installed at deploy).
- **not installed** (open-source clone, local dev) → an inert **OBSERVE no-op**:
  every action is allowed and logged, nothing is enforced. The platform boots
  and runs normally; it simply has no real security layer.

`SECURITY_BACKEND` (`"morpheus_security"` or `"noop"`) reports which is active.

## Status

**SECURITY-REVIEW-REQUIRED.** The enforcement layer is unverified scaffolding:
testnet-only and feature-flagged (default OBSERVE — logs, never hard-blocks).
ENFORCE mode must not be enabled before a human security review and testnet
validation. The non-custodial invariant is absolute: the layer can deny an
action, never sign or move funds.

The Glasswing contract auditor (`audit.py`) is a **separate, open** feature —
static analysis of generated Solidity — and is imported directly as
`runtime.security.audit`. It does not pass through this seam.

The security implementation is proprietary. See `SECURITY_STUB.md` in the project
root for the public-facing statement. Developers extending 0pnMatrx should treat
the security layer as an opaque boundary: never bypass, replicate, or reach
around it. If you need security-layer behavior in a fork, implement your own.
