# Security Interface

This directory is the **seam** to The Matrix's closed-source security layer. It is
a boundary, not an implementation: `__init__.py` exposes the security contract
the platform calls and binds it to the private security package when that package
is installed. The rules — how the layer detects, classifies, bans, verifies
owners, or sanitizes — are **not in this repository** and never will be.

## What the platform sees

- The gateway builds the process-wide gate once, at startup, with
  `start_security_gate(config)`: from its whole configuration and database
  handle, loading the gate's saved state before it serves. The gate is handed
  out only when both steps succeeded. If either fails, a production gateway
  refuses to start; elsewhere `get_morpheus_security()` raises
  `SecurityGateUnavailable` instead of building a lesser gate for whoever asks
  next, every caller treats that as a gate fault (an action that moves value is
  refused), and `/ready` fails. While the gate is starting or after its start
  failed, `agent_access_allowed` refuses every tool call and asks no policy in
  the gate's place. With no gateway running (a script, the CLI) the accessor
  builds the gate on first use, and the tool boundary asks the policy, as
  before.
- A security gate is obtained via `from runtime.security import get_morpheus_security`
  and consulted **first** in
  `runtime/protocols/integration.py::ProtocolStack.pre_action`, ahead of
  `RexhepiGate`, so every execution path passes it before any privileged action.
- `gate.evaluate(action, context)` returns an allow/deny decision. The gate is
  **authoritative server-side** — app-side checks are UX only.
- The per-agent tool boundary, `agent_access_allowed(agent, tool, action, context)`,
  is asked on every tool call by `runtime/tools/dispatcher.py`. Its `context`
  carries the caller identity the entry point bound, under
  `CALLER_IDENTITY_KEY`, and never a value from the model's tool arguments. The
  hand-off (`runtime/agents/handoff.py`) hands its gate the same caller. What the
  core decides from it is the core's; the seam's part is that it arrives.
- A wallet address reaches the seam in one spelling, wherever the platform
  names a caller: `0x` and its digits in lower case (`runtime/auth/identity.py`).
  The session the gateway creates, the wallet it links to an Apple user, an
  identity the operator states, the context at the tool boundary and at the
  hand-off's gate, and the `wallet` bound for every gated HTTP action all use
  it, so one wallet signing in with its address in another case is one
  caller, not several.
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
root for the public-facing statement. Developers extending The Matrix should treat
the security layer as an opaque boundary: never bypass, replicate, or reach
around it. If you need security-layer behavior in a fork, implement your own.
