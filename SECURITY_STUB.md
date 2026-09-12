# Security Layer

0pnMatrx is built to run behind a closed-source security layer that is not part of this repository.

The security layer is designed to handle:
- Agent boundary enforcement
- Constraint manifest validation
- Audit trail and integrity verification
- The Neo access protection protocol
- Ban system and blockchain attestation
- Owner-level access verification

It connects to the open source runtime through the seam documented in `runtime/security/SECURITY_INTERFACE.md`. The platform consults the seam in two places: the per-agent tool boundary, which the ToolDispatcher checks on each tool call it dispatches, and the Morpheus gate, which `ProtocolStack.pre_action` evaluates after its seam-level refusals and before the Rexhepi gate.

## What is true today

- **Without the private package** — every clone of this repository — the Morpheus gate is an inert OBSERVE no-op: it allows every action it evaluates and makes no security decision, and none of the layer's own checks run. The public checks in this repository still run. Among those that can refuse an action:
  - the coarse per-agent tool boundary (`runtime/access_policy.py`): Trinity and Morpheus cannot run execution tools or state-changing actions, and an unknown or empty agent name is refused;
  - two seam-level refusals in `ProtocolStack.pre_action`, reached before the gate: a platform-signed action naming a beneficiary address other than the caller's (or naming one when no caller identity is bound), and an approve signed with the platform key when no operator allowance cap is set;
  - the Rexhepi (URF) gate, evaluated in `ProtocolStack.pre_action` after the Morpheus gate: it runs platform checks (safety, compliance, authorization, rate limit, fee validation, address screening, blocked action types), and an action proceeds only when every check passes and the URF outcome is EXECUTE — anything else, for example an action with an irreversible external downside that needs explicit approval, is refused; a fault inside the gate is logged and the action continues (`runtime/protocols/rexhepi_gate.py`);
  - the Glasswing audit block: a contract tool call that carries source code which fails the Glasswing audit, or cannot be audited, is refused (`runtime/security/audit.py`, `ContractAuditor.should_block`);
  - owner verification and OTP, which fail closed (they never authorize), so owner-gated operations are off rather than open.
- **With the private package installed**, the layer's documented default mode is OBSERVE (`OPNMATRX_MORPHEUS_MODE=observe`): it records what it would block and does not block. ENFORCE must not be enabled before a human security review and testnet validation; the layer is unverified until then.
- The layer can deny an action. It never signs a transaction or moves funds.

If you are building on 0pnMatrx, you do not need the security layer to run the platform locally. A deployment serving public users needs it installed, reviewed and switched to ENFORCE before it can claim any of the protections listed above.

## Reporting a vulnerability

Report privately as described in [.github/SECURITY.md](.github/SECURITY.md). A way around this layer's enforcement is in scope.
