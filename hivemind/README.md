# Hivemind

The hivemind is an orchestration layer for coordinating the three agents of The Matrix: an orchestrator that assigns and tracks tasks and delegates between agents (`orchestrator.py`), a typed event bus (`events.py`), and a session lifecycle manager with hooks (`lifecycle.py`).

## What runs it today

Nothing in the running platform does. The gateway serves each request through one agent's ReAct loop (`runtime/react_loop.py`), and Morpheus's triggers and the hand-off from Trinity to Neo live in `runtime/protocols/` and `runtime/agents/handoff.py`. See `docs/architecture.md`. The only code that imports this package is tests.

## What it writes

Run with a workspace, it writes under `<workspace>/hivemind/`: its event log (`events.jsonl`), per-agent message queues (`queues/<agent>.jsonl`) and session state (`sessions/<session>.json`). With the repository as the workspace, those paths are git-ignored.

## Design

- **Trinity → Morpheus**: when trigger conditions are met, Morpheus responds, then control returns to Trinity.
- **Trinity → Neo**: when the request needs blockchain or tool execution, Neo executes it in the background.
- **Morpheus → Trinity**: after Morpheus delivers guidance, Trinity resumes the conversation.

To add an agent to this design:

1. Create an identity document in `agents/<name>/identity.md`
2. Add the agent to `matrix.config.json`
3. Register the agent's role in `orchestrator.py`
4. Define routing rules for when the agent should be invoked
