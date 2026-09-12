# Security Layer

0pnMatrx is built to run behind a closed-source security layer that is not part of this repository.

The security layer is designed to handle:
- Agent boundary enforcement
- Constraint manifest validation
- Audit trail and integrity verification
- The Neo access protection protocol
- Ban system and blockchain attestation
- Owner-level access verification

It connects to the open source runtime through the seam documented in `runtime/security/SECURITY_INTERFACE.md`, which the platform consults before privileged actions (first in `ProtocolStack.pre_action`).

## What is true today

- **Without the private package** — every clone of this repository — the seam runs an inert OBSERVE no-op: every action is allowed and logged, and nothing listed above is enforced. Owner verification and OTP fail closed (they never authorize), so owner-gated operations are off rather than open.
- **With the private package installed**, the layer's documented default mode is OBSERVE (`OPNMATRX_MORPHEUS_MODE=observe`): it records what it would block and does not block. ENFORCE must not be enabled before a human security review and testnet validation; the layer is unverified until then.
- The layer can deny an action. It never signs a transaction or moves funds.

If you are building on 0pnMatrx, you do not need the security layer to run the platform locally. A deployment serving public users needs it installed, reviewed and switched to ENFORCE before it can claim any of the protections listed above.

## Reporting a vulnerability

Report privately as described in [.github/SECURITY.md](.github/SECURITY.md). A way around this layer's enforcement is in scope.
