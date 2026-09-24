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
  next, and `/ready` fails. While the gate is starting or after its start
  failed (`security_gate_withheld()`), nothing is decided in the gate's place:
  `agent_access_allowed` refuses every tool call, the HTTP gate
  (`gateway/security_gate.py`) refuses every gated action, reads included, and
  `ProtocolStack.pre_action` refuses every tool call, each without asking any
  other policy. A gate that is up and faults on one call keeps the platform's
  fail direction for that call: an action that could move value is refused, a
  plain read proceeds. With no gateway running (a script, the CLI) the
  accessor builds the gate on first use, and the tool boundary asks the
  policy, as before.
- A security gate is obtained via `from runtime.security import get_morpheus_security`
  and consulted **first** in
  `runtime/protocols/integration.py::ProtocolStack.pre_action`, ahead of
  `RexhepiGate`, so every execution path passes it before any privileged action.
- `gate.evaluate(action, context)` returns an allow/deny decision. The gate is
  **authoritative server-side** — app-side checks are UX only. The decision
  says in `route` whether the gate evaluated the call at all: `pass_through`
  is a call it did not; any other value is a route it took. Every label the
  seam produces for a platform-key-signed twin action
  (`runtime/security/action_map.py`) is one the installed gate evaluates;
  `tests/test_twins_seam.py` asks the gate that through `evaluate` where the
  package is installed, and this repository keeps no copy of what the gate
  evaluates, nor names anything of the core's beyond what the seam imports
  (`tests/test_public_tree_keeps_no_core_copy.py`).
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
- The core names a caller by the same rule, and exports it as
  `canonical_identity`. Before the gateway starts the gate,
  `start_security_gate` checks that the installed backend's rule gives the
  platform's answer for a set of spellings; a core that exports no rule, or
  another one, is not started (stage `"identity"`), and the start is handled
  like any other failed start. Without that, whatever the core holds about a
  caller under another spelling of the same wallet would match no caller the
  platform hands it. How the core applies the rule to what it holds is the
  core's. The no-op backend holds nothing about any caller and uses the
  platform's rule.
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
testnet-only and feature-flagged. It defaults to OBSERVE, where a verdict's deny
is not applied; a fault on a call that could move value or change state and App
Attest, when it is enforced, still deny, and the seam applies every deny it is
handed, in either mode. ENFORCE mode must not be enabled before a human security review and
testnet validation. The non-custodial invariant is absolute: the layer can deny
an action, never sign or move funds.

The Glasswing contract auditor (`audit.py`) is a **separate, open** feature —
static analysis of generated Solidity — and is imported directly as
`runtime.security.audit`. It does not pass through this seam.

The security implementation is proprietary. See `SECURITY_STUB.md` in the project
root for the public-facing statement. Developers extending The Matrix should treat
the security layer as an opaque boundary: never bypass, replicate, or reach
around it. If you need security-layer behavior in a fork, implement your own.
