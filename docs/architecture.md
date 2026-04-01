# Architecture

## Overview

0pnMatrx is a three-agent platform where every operation flows through a unified decision framework. The architecture is simple by design — complexity is in the intelligence, not the plumbing.

```
User
  │
  ▼
Gateway (HTTP)
  │
  ▼
Hivemind Orchestrator
  │
  ├── Trinity (conversation)
  ├── Morpheus (guidance)
  └── Neo (execution)
       │
       ├── ReAct Loop
       │    ├── Model Router
       │    └── Tool Dispatcher
       │
       ├── Memory Manager
       ├── Skill Loader
       └── Temporal Context
```

## Components

### Gateway
The HTTP entry point. Receives user messages, routes them to the hivemind, and returns responses. Stateless per request — conversation state is managed by the orchestrator.

### Hivemind Orchestrator
Coordinates the three agents. Checks Morpheus trigger conditions before every Trinity response. Routes execution tasks to Neo. Manages agent handoffs.

### ReAct Loop
The core reasoning engine. Implements the Reason-Act cycle: the model thinks, calls a tool, observes the result, and repeats until it has a final answer. Model-agnostic — works with any provider.

### Model Router
Selects and calls the appropriate model provider. Supports automatic fallback: if the primary provider (e.g., Ollama) is unreachable, it tries the fallback (e.g., Mistral).

### Tool Dispatcher
Routes tool calls from the ReAct loop to the correct handler. Enforces timeouts and error handling. Tools are registered at startup.

### Memory Manager
Provides conversation continuity across sessions. File-based, per-agent memory stored as JSONL.

### Skill Loader
Discovers and loads YAML-defined skills that extend agent capabilities. Skills define trigger conditions and execution steps.

### Temporal Context
Gives agents awareness of the current date and time. Injected into system prompts.

## Decision Flow

Every decision on the platform follows this path:

1. User sends a message
2. Gateway receives it
3. Hivemind checks Morpheus triggers
4. If triggered → Morpheus responds, then Trinity resumes
5. If not triggered → Trinity handles the conversation
6. If execution is needed → Neo handles it via the ReAct loop
7. Response returns through the gateway

Every step is governed by the Unified Rexhepi Framework.

## Security

The access protection protocol operates across three classifications. The implementation is closed-source. See `SECURITY_STUB.md`.
