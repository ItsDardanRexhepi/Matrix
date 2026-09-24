# Module 02: Quick Start

## Goal

By the end of this module, you will have The Matrix running on your machine, the gateway serving requests on port 18790, and you will have had your first conversation with Trinity.

## Step 1: Clone the Repository

```bash
git clone https://github.com/ItsDardanRexhepi/Matrix.git TheMatrix
cd TheMatrix
```

Verify you are in the right directory:

```bash
ls gateway/
```

You should see `server.py`, `__init__.py`, and several other modules.

## Step 2: Run Setup

The setup script installs dependencies and configures your local environment:

```bash
python3 setup.py
```

This will:
- Install all Python dependencies from `requirements.txt`
- Create a default configuration file if one does not exist
- Generate a local API key for development
- Verify that Python 3.10+ is available

If you encounter version errors, confirm your Python version:

```bash
python3 --version
```

You need Python 3.10 or newer; setup refuses anything older. On macOS the command is `python3` — there is no `python`.

## Step 3: Start the Gateway

```bash
source .venv/bin/activate    # once per terminal; setup created .venv
python -m gateway.server
```

The gateway logs as it starts and then listens on port 18790 (or `$PORT`). Leave this terminal open and open a new terminal for the next steps.

## Step 4: Check Health

In your new terminal, verify the gateway is responding:

```bash
curl http://localhost:18790/health
```

The response looks like this (your agents and provider are the ones you chose in setup):

```json
{
  "status": "ok",
  "agents": ["neo", "trinity", "morpheus"],
  "model_provider": "ollama",
  "models": {"ollama": true}
}
```

`agents` lists the agents enabled in your config, and `models` says whether each configured model provider answered. The `/health` endpoint is unauthenticated and answers "is the process up?" for load balancers and monitoring. Whether the instance should take traffic is `/ready`, which fails when no model provider is reachable.

## Step 5: Check Status

The `/status` endpoint provides more detail about the running system. It needs the API key setup generated:

```bash
curl http://localhost:18790/status -H "Authorization: Bearer YOUR_API_KEY"
```

The response names the platform and version, the enabled agents, the model, the session and request counts, uptime, memory, and the health of each subsystem:

```json
{
  "platform": "The Matrix",
  "version": "1.0.0",
  "agents": ["neo", "trinity", "morpheus"],
  "model": {"provider": "ollama", "primary": "llama3.1"},
  "sessions": 0,
  "wallet_sessions": 0,
  "total_requests": 2,
  "uptime_seconds": 45.2,
  "memory_mb": 180.4,
  "subsystems": {"...": "..."}
}
```

The capability catalog is its own endpoint. `curl http://localhost:18790/api/v1/capabilities -H "Authorization: Bearer YOUR_API_KEY"` lists all 195 capabilities, in 21 categories. Capabilities for protocols you haven't configured return a clean not_deployed response rather than failing.

## Step 6: Your First Chat with Trinity

Now send your first message. You will need your API key (generated during setup -- check your config file or the setup output):

```bash
curl -X POST http://localhost:18790/chat \
  -H "Content-Type: application/json" \
  -H "Authorization: Bearer YOUR_API_KEY" \
  -d '{"message": "Hello Trinity, what can you help me with?"}'
```

Expected response:

```json
{
  "request_id": "req_abc123def456",
  "response": "Hello! I'm Trinity, your guide to The Matrix. I can help you with a wide range of blockchain operations on Base...",
  "agent": "trinity",
  "tools_used": [],
  "timestamp": "2026-04-10T12:01:00Z"
}
```

## Understanding the Response Format

Every response from the `/chat` endpoint includes these fields:

| Field | Description |
|-------|-------------|
| `request_id` | Unique identifier for tracing this request through the system |
| `response` | Trinity's natural language reply |
| `agent` | Which agent generated the response (usually "trinity") |
| `tools_used` | List of blockchain services Neo invoked (empty for conversational responses) |
| `timestamp` | When the response was generated |

When Neo executes blockchain operations, the `tools_used` array will contain entries describing what was done:

```json
{
  "tools_used": [
    {
      "tool": "token_deploy",
      "status": "success",
      "result": {"contract_address": "0x..."}
    }
  ]
}
```

## Troubleshooting

**Port already in use**: If port 18790 is occupied, check for other processes: `lsof -i :18790`

**Module not found**: Make sure you ran `python3 setup.py` first, activated its virtual environment in this terminal with `source .venv/bin/activate`, and are using the correct Python version.

**Connection refused**: Verify the gateway is still running in your other terminal. Check for error messages in its output.

**Authentication failed**: Double-check your API key. You can find it in your local configuration file or regenerate it by running setup again.

## Key Takeaways

- The gateway runs on port 18790 and is started with `python -m gateway.server` after `source .venv/bin/activate`
- `/health` is unauthenticated and returns basic liveness information
- `/status` provides detailed information about agents and services
- `/chat` requires authentication via Bearer token
- Every response includes a `request_id` for tracing

---

**Next:** [Understanding the Gateway](./03-understanding-the-gateway.md) -- a deep dive into endpoints, authentication, and middleware.
