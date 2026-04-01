# Contributing to 0pnMatrx

Welcome. 0pnMatrx is open source and welcomes contributions from developers everywhere. This document explains how contributions work, what gets reviewed, and how the process flows from start to finish.

---

## The Möbius Loop Contribution Model

0pnMatrx uses a contribution model called the Möbius loop. It works like this:

**Build freely.** Any developer can fork 0pnMatrx, build anything they want on top of it, and run it on their own infrastructure without asking permission. The MIT license guarantees this. You do not need approval to build, experiment, extend, or deploy.

**Submit formally.** If you want your work to be integrated into the official 0pnMatrx platform or into MTRX (the iOS app), you submit a formal contribution through the process described below. This triggers a three-layer review.

**Three layers, no shortcuts.** Every formal submission passes through three independent layers before it can be merged:

1. **Neo Security Audit** — Neo reviews the submission for security integrity, protocol compliance, and alignment with the platform's operational constraints. This is automated and non-negotiable. Submissions that fail the security audit are returned with specific feedback.

2. **Community Governance Vote** — Submissions that pass the security audit are presented to the community for a governance vote. The voting mechanism is transparent, on-chain, and tamper-proof. The community decides whether the feature adds value to the platform.

3. **Owner Explicit Approval** — Submissions that pass both the security audit and the community vote require explicit approval from the platform owner before merging. This is the final gate.

No feature touches MTRX without all three layers passing. No exceptions.

---

## What You Can Contribute

- **New tools** — Extend the tool system in `runtime/tools/`
- **New skills** — Add capabilities to the skills system in `runtime/skills/`
- **Migration importers** — Help users migrate from other platforms via `migration/`
- **Documentation** — Improve or translate docs in `docs/`
- **Smart contracts** — Propose new blockchain capabilities in `blockchain/contracts/`
- **SDK extensions** — Extend the developer SDK in `sdk/`
- **Bug fixes** — Fix issues anywhere in the open source codebase
- **HiveMind extensions** — Extend the agent orchestration system in `hivemind/`

---

## What You Cannot Access

The following are closed source and are never exposed to contributors:

- **The security layer** — The full implementation of agent boundary enforcement, constraint validation, audit trails, and the access protection protocol
- **The Unified Rexhepi Framework implementation** — The specific gate criteria, scoring logic, probability weights, thresholds, and outcome definitions that govern every agent decision
- **Neo's private runtime** — The Matrix server and its operational configuration

These boundaries exist by design. You do not need access to any of them to build on 0pnMatrx. The open source runtime connects to the security layer through a documented interface at `runtime/security/SECURITY_INTERFACE.md`.

---

## How to Submit

1. **Fork the repository** and create a feature branch from `main`
2. **Build your contribution** following the existing code patterns and conventions
3. **Test locally** — ensure the platform starts and runs with your changes
4. **Write clear documentation** for any new features or capabilities
5. **Open a pull request** against the `main` branch with:
   - A clear title describing what the contribution does
   - A description of why it adds value to the platform
   - Any relevant testing or verification steps
   - Screenshots or examples if applicable

---

## What Gets Reviewed

Every pull request is evaluated on:

- **Security** — Does it introduce any vulnerabilities, data leaks, or bypass mechanisms?
- **Quality** — Is the code clean, well-documented, and consistent with existing patterns?
- **Value** — Does it add meaningful capability to the platform?
- **Compatibility** — Does it work with the existing architecture without breaking changes?
- **Privacy** — Does it respect user privacy and data sovereignty?

---

## Code of Conduct

Be respectful. Build something meaningful. Help others do the same. 0pnMatrx exists to give everyone a balanced chance — contributions should reflect that spirit.

---

## Questions

If you have questions about the contribution process, open an issue with the `question` label. The community and maintainers will respond.
