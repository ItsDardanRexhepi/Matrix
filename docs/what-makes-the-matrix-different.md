# What Makes The Matrix Different

## Free to Start, Fees Stated

The software is open source and free to run. Using the platform has a free tier; Pro and Enterprise subscriptions are sold in the MTRX app. Gas is paid by the platform when an operator configures sponsorship, within the operator's policy. When that policy sets a per-identity daily cap, an operation past the cap is refused rather than charged to you (this includes attestations you ask for, through an agent tool or the attestation capabilities; only the platform's own records — its record of each capability call and records it writes after another operation — are not counted against it); a deployment that sets no cap sponsors without a daily limit. Some operations carry a platform fee (marketplace sales, staking rewards, stablecoin transfers, cross-border payments and others); the fees and their rates are listed in `docs/blockchain.md` under **Fees**, together with how that list is checked against the code and what the check cannot see.

## Everything Is Conversation

There are no forms. No dashboards. No settings pages. No documentation users need to read. Every single capability is accessible through a conversation with Trinity. A user who has never touched blockchain in their life can deploy a smart contract by describing what they want in their own words, in their own language.

## Everything Is Governed

Every tool call the agents' reasoning loop makes passes through the Unified Rexhepi Framework before it is dispatched (`RexhepiGate`, `runtime/protocols/rexhepi_gate.py`, run by `ProtocolStack.pre_action`). It scores six gates, applies the hard rules and resolves one outcome, EXECUTE, PROBE, ASK, DEFER or ABORT, and only EXECUTE runs the call. It is this repository's own code, so a fork can change it or take it out; what keeps it in place here is that this repository runs it and its tests pin how it decides. `docs/unified-rexhepi-framework.md` says more.

## Three Agents, Not One

Most platforms have one AI. The Matrix has three, each with a distinct role:

- **Trinity** handles conversation — warm, capable, always present
- **Morpheus** handles guidance — appears only at pivotal moments
- **Neo** handles execution — invisible to users, runs everything

This separation means the user-facing experience is never polluted by execution logic, and critical moments are never rushed past.

## Model Agnostic

The Matrix works with any LLM. Run it locally with Ollama for complete privacy, or connect to any cloud provider. The platform does not depend on any single model provider. Switch models without changing anything else.

## Open Source, Closed Security

The entire platform is open source. The runtime, the agents, the contracts, the SDK — all of it. What is not open source is the security layer: the access protection protocol, the Unified Rexhepi Framework scoring criteria, and the hard rules. This is deliberate. The security of the system depends on parts of it being opaque.

## For Everyone

The Matrix is designed for every person in the world regardless of their technical knowledge, location, or language. Trinity speaks the user's native language. The interface is a conversation. The barrier to entry is zero.
