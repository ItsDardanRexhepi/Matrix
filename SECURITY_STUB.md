# Security Layer

0pnMatrx includes a closed-source security layer that is not part of this repository.

The security layer handles:
- Agent boundary enforcement
- Constraint manifest validation
- Audit trail and integrity verification
- The Neo access protection protocol
- Ban system and blockchain attestation
- Owner-level access verification

This layer is closed source by design. It cannot be bypassed, forked, or replicated from this repository. It connects to the open source runtime through the interface documented in `runtime/security/SECURITY_INTERFACE.md`.

If you are building on 0pnMatrx, you do not need the security layer to run the platform locally. It is required only for production deployments serving public users.
