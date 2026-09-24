# Security Layer

The Matrix includes a closed-source security layer that is not part of this repository.

The security layer handles:
- Agent boundary enforcement
- Constraint manifest validation
- Audit trail and integrity verification
- The Neo access protection protocol
- Ban system and blockchain attestation
- Owner-level access verification

Its code is closed source by design, so it cannot be forked or replicated from this repository. It connects to the open source runtime through the seam in `runtime/security/`, documented in `runtime/security/SECURITY_INTERFACE.md`.

What it protects is a deployment that installs it. In a clone of this repository, with the closed package absent, the seam binds an inert no-op in OBSERVE mode: its gate allows every action it is asked about and applies none of the layer's checks, and the gateway says so at startup. The platform's own per-agent tool boundary still holds. A fork can also remove the seam's call sites entirely. So the layer is not something this repository makes impossible to bypass; it is something a deployment chooses to run.

If you are building on The Matrix, you do not need the security layer to run the platform locally. It is required for production: with `MATRIX_ENV=production` the gateway refuses to start on the no-op backend.
