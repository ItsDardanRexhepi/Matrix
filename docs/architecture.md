# Architecture

## Overview

The Matrix is a three-agent platform. A request reaches one agent's reasoning loop, and every tool call that loop makes is checked before it runs. The architecture is simple by design — complexity is in the intelligence, not the plumbing.

```
User
  │
  ▼
Gateway (HTTP, WebSocket, mobile bridge)
  │   picks the agent: Trinity for users; Neo and Morpheus
  │   only with the operator key
  ▼
ReAct Loop, running as that agent
  ├── Model Router
  ├── Pre-action check on every tool call
  │     (security seam, Rexhepi gate, contract auditor, Morpheus triggers)
  ├── Tool Dispatcher
  │     ├── built-in tools, blockchain capabilities, skills
  │     ├── platform_action → Service Dispatcher (the capability catalog)
  │     └── request_execution → the gated hand-off from Trinity to Neo
  ├── Memory Manager (SQLite)
  └── Temporal Context
```

## Components

### Gateway
`gateway/server.py`. Receives user messages over HTTP, WebSocket and the mobile bridge (`gateway/bridge.py`), resolves which agent serves the caller (`gateway/chat_agents.py`), and runs that agent's ReAct loop. A caller without the operator key is served by Trinity.

### ReAct Loop
`runtime/react_loop.py`. The core reasoning engine: the model thinks, calls a tool, observes the result, and repeats until it has a final answer. Model-agnostic — works with any provider.

### Model Router
`runtime/models/router.py`. Selects and calls the model provider. It tries the configured primary first, then the configured fallback, then the remaining providers.

### Pre-action check
`runtime/protocols/integration.py` (`ProtocolStack.pre_action`). Every tool call the loop makes is checked before it is dispatched: first the closed security layer's gate through the seam in `runtime/security/` (an inert no-op when that layer is not installed), then `RexhepiGate`, which runs the Unified Rexhepi Framework loop in `runtime/protocols/urf.py`, the Glasswing auditor on contract-related calls, and the Morpheus triggers. A denial stops the call; a Morpheus message is delivered with the result.

### Tool Dispatcher
`runtime/tools/dispatcher.py`. Routes tool calls to their handlers, enforces the per-agent tool boundary and timeouts, and says whether each call succeeded. Its tools are the built-ins (shell, files, web), the blockchain capabilities, the skills in `skills/`, `platform_action` (the Service Dispatcher, `runtime/blockchain/services/service_dispatcher.py`, which invokes any capability in `runtime/capabilities/catalog.py`), and `request_execution`, the only channel by which Trinity's requests reach Neo (`runtime/agents/handoff.py`).

### Memory Manager
`runtime/memory/manager.py`. Conversation continuity across sessions, stored in SQLite.

### Skill Loader
`runtime/skills/loader.py`. Loads the Python and YAML skills in `skills/` and registers each as a tool.

### Temporal Context
Gives agents awareness of the current date and time. Injected into system prompts.

## Decision Flow

1. A user sends a message
2. The gateway receives it and picks the agent (Trinity, for a user)
3. The agent's ReAct loop calls the model
4. Each tool call the model makes passes the pre-action check, which can deny it or add a Morpheus message
5. If execution is needed, Trinity hands it to Neo through `request_execution`, which is gated again
6. The response returns through the gateway

`hivemind/` holds an orchestrator, event bus and lifecycle manager for coordinating the agents; the flow above does not pass through it. See `hivemind/README.md`.

## Security

The enforcing security layer is closed source and not in this repository. See `SECURITY_STUB.md`.
