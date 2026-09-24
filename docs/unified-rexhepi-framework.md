# The Unified Rexhepi Framework

## What It Is

The Unified Rexhepi Framework is a unified theoretical and operational structure for modeling adaptive systems in terms of how they evaluate and select future trajectories under constraints and uncertainty. It was written by Neo from operational experience and authored by Dardan Rexhepi.

The framework brings together two complementary layers: a formal theoretical foundation and a practical operational layer that translates those principles into a scored decision protocol for real-world execution. It is both a scientific hypothesis and a practical decision architecture.

## What Problem It Solves

Across disciplines — neuroscience, artificial intelligence, control theory, evolutionary biology, economics — researchers study systems that anticipate, plan, and adapt. The theoretical tools used to describe these phenomena remain fragmented. Each field offers powerful local insights, but there is no widely accepted, domain-agnostic framework that captures the shared structural features of adaptive decision-making across scales.

The Unified Rexhepi Framework provides that cross-domain organizing principle. Any system that can be reasonably described as intelligent or adaptive can be modeled as maintaining beliefs over possible futures, subject to feasibility constraints, and using internal mechanisms to evaluate and select from those futures.

## How It Governs The Matrix

In this repository the framework's operational layer is code you can read. `runtime/protocols/urf.py` scores six gates in a fixed order — Clarity, Feasibility, Risk, Uncertainty, Value, Capability Expansion — applies the hard rules, which remove a decision from the feasible set whatever it scored, and resolves exactly one canonical outcome: EXECUTE, PROBE, ASK, DEFER or ABORT. It writes an auditable record of each decision.

`RexhepiGate` (`runtime/protocols/rexhepi_gate.py`) runs that loop, with the platform's own safety checks — sanctions, authorization, rate limits, fee validation, address screening — feeding its hard rules and its Risk and Feasibility gates. It runs on every tool call the agents' reasoning loop makes, before the call is dispatched (`ProtocolStack.pre_action` in `runtime/protocols/integration.py`), after the closed security layer's gate when that layer is installed.

It is this runtime's own code, so a fork can change it or take it out. What keeps it in place here is that this repository runs it, and its tests pin how it decides.

## What Is Public and What Is Not

The operational layer is public: the gates and how they are scored, the hard rules, the canonical outcomes and the logic that chooses between them are all in `runtime/protocols/urf.py`. It is not part of the closed-source security layer described in `SECURITY_STUB.md`, which runs its own checks ahead of it.

What is not reproduced here is the full manuscript authored by Dardan Rexhepi: the framework's theoretical foundations, formal mathematical structure, cross-domain applications, and empirical predictions.
