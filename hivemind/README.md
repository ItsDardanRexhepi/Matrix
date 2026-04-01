# Hivemind

The hivemind is the orchestration layer that coordinates the three agents of 0pnMatrx.

## How It Works

Every user message passes through the hivemind orchestrator before reaching any agent. The orchestrator:

1. **Checks Morpheus triggers** — is this a pivotal moment that requires guidance?
2. **Routes to Trinity** — all user-facing conversation goes through Trinity
3. **Delegates to Neo** — when execution is needed, Neo handles it invisibly

## Agent Handoffs

- **Trinity → Morpheus**: Automatic when trigger conditions are met. Morpheus responds, then control returns to Trinity.
- **Trinity → Neo**: When the user's request requires blockchain or tool execution. Neo executes in the background.
- **Morpheus → Trinity**: After Morpheus delivers guidance, Trinity resumes the conversation.

Users only ever see Trinity and Morpheus. Neo is invisible.

## Extending

To add a new agent to the hivemind:

1. Create an identity document in `agents/<name>/identity.md`
2. Add the agent to `openmatrix.config.json`
3. Register the agent's role in `orchestrator.py`
4. Define routing rules for when the agent should be invoked
