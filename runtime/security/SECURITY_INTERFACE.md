# Security Interface

This directory is a placeholder for the closed-source security layer.

The security layer governs:
- The access protection protocol for Neo
- Morpheus's security response role
- Trinity's interception of unintentional Neo access

The implementation is proprietary. See `SECURITY_STUB.md` in the project root for the public-facing statement.

Developers extending 0pnMatrx should treat the security layer as an opaque boundary. Your code should never attempt to bypass, replicate, or interface with it directly. If you need security-layer behavior in a fork, implement your own.
