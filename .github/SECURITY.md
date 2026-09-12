# Security Policy

## Reporting a Vulnerability

If you discover a security vulnerability in 0pnMatrx, do not open a public GitHub issue.

Email: security@openmatrix-ai.com

Include:
- A description of the vulnerability
- Steps to reproduce
- Potential impact
- Any suggested fix

You will receive a response within 72 hours. We take all security reports seriously.

## Scope

In scope: everything in this repository, and any way to get past the security enforcement this runtime relies on. That includes the security seam in `runtime/security/`, every call site that consults it, and the behaviour of the closed-source security layer as observed through this runtime. The layer's source is not published, but a bypass of its enforcement is exactly what this policy exists to receive — report it here, privately, like anything else.

One default is documented rather than a finding: without the private security package installed, the Morpheus gate is an OBSERVE no-op that allows every action it evaluates (see `SECURITY_STUB.md` for what still applies). A way past the public checks that do still apply — the per-agent tool boundary, the seam-level refusals on platform-signed actions, fail-closed owner verification and OTP — is a finding, and so is a way to make a deployment that has the package installed behave as if it did not.

## Responsible Disclosure

We ask for a 90-day responsible disclosure window before any public publication of a discovered vulnerability.
