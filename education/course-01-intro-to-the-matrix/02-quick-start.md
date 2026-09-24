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

Among its startup log lines you should see the line the gateway writes just
before it starts serving:

```
The Matrix gateway starting
```

It then listens on port 18790 (`gateway.port`). With no private security core
installed it also says, once at import, that the security backend is `noop`
and runs in OBSERVE mode.

The gateway is now running. Leave this terminal open and open a new terminal for the next steps.

## Step 4: Check Health

In your new terminal, verify the gateway is responding:

```bash
curl http://localhost:18790/health
```

The response has this shape:

```json
{
  "status": "ok",
  "agents": ["neo", "trinity", "morpheus"],
  "model_provider": "ollama",
  "models": {}
}
```

`agents` lists the agents enabled in your config, and `models` says whether each configured model provider answered. The `/health` endpoint is unauthenticated and answers "is the process up?" for load balancers and monitoring. Whether the instance should take traffic is `/ready`, which fails when no model provider is reachable.

## Step 5: Check Status

The `/status` endpoint provides more detail about the running system. It needs the API key setup generated:

```bash
curl http://localhost:18790/status -H "Authorization: Bearer YOUR_API_KEY"
```

The response has this shape (values vary with your config and how long the
gateway has been up):

```json
{
  "platform": "The Matrix",
  "version": "1.0.0",
  "agents": ["neo", "trinity", "morpheus"],
  "model": {"provider": "ollama", "primary": "..."},
  "sessions": 0,
  "wallet_sessions": 0,
  "total_requests": 2,
  "uptime_seconds": 45.0,
  "memory_mb": 120.5,
  "subsystems": {"models": {}, "memory": {}, "blockchain": {"configured": false}, "protocols": {}}
}
```

The capability catalog is not part of `/status`:
`curl http://localhost:18790/api/v1/capabilities -H "Authorization: Bearer YOUR_API_KEY"`
lists all 195 capabilities, and `GET /api/v1/capabilities/categories` the
categories: twenty-one are declared, and one (Security & Wallets) holds none. Capabilities for protocols you haven't configured return a clean
not_deployed response rather than failing.

## Step 6: Your First Chat with Trinity

Now send your first message. The chat is public, so it needs no key:

```bash
curl -X POST http://localhost:18790/chat \
  -H "Content-Type: application/json" \
  -d '{"message": "Hello Trinity, what can you help me with?", "session_id": "quick-start"}'
```

Expected response (the wording is the model's):

```json
{
  "response": "Hello! I'm Trinity, your guide to The Matrix. I can help you with a wide range of blockchain operations on Base...",
  "tool_calls": [],
  "session_id": "quick-start",
  "agent": "trinity",
  "provider": "ollama"
}
```

## Understanding the Response Format

A successful answer from the `/chat` endpoint has these fields:

| Field | Description |
|-------|-------------|
| `response` | Trinity's natural language reply |
| `tool_calls` | The tools the agent called this turn (empty for conversational responses) |
| `session_id` | The conversation this turn belongs to; send it again to continue it |
| `agent` | Which agent generated the response (`trinity` unless you named another with the operator key) |
| `provider` | The model provider that answered |

The request's ID is not in the body: it is the `X-Request-ID` response header, which the gateway's log lines for the request carry too.

When the agent calls a tool, each entry in `tool_calls` names the tool, the arguments it was called with, a preview of what it returned, and whether it succeeded:

```json
{
  "tool_calls": [
    {
      "tool": "platform_action",
      "arguments": {"action": "get_staking_position", "params": {"staker": "0x..."}},
      "result_preview": "{\"status\": \"ok\", \"call_outcome\": \"failure\", ...}",
      "success": false,
      "reported": "failure"
    }
  ]
}
```

A service whose contract is not deployed on your gateway answers `not_deployed`, and the entry says the call did not succeed.

## Troubleshooting

**Port already in use**: If port 18790 is occupied, check for other processes: `lsof -i :18790`

**Module not found**: Make sure you ran `python3 setup.py` first, activated its virtual environment in this terminal with `source .venv/bin/activate`, and are using the correct Python version.

**Connection refused**: Verify the gateway is still running in your other terminal. Check for error messages in its output.

**Authentication failed** (`401` on `/status` or another key-gated route): Double-check your API key. You can find it in your local configuration file or regenerate it by running setup again.

## Key Takeaways

- The gateway runs on port 18790 and is started with `python -m gateway.server` after `source .venv/bin/activate`
- `/health` is unauthenticated and returns basic liveness information
- `/status` provides detailed information about the running gateway, behind the API key
- `/chat` is public; naming Neo or Morpheus takes the API key
- Every response carries an `X-Request-ID` header for tracing

---

**Next:** [Understanding the Gateway](./03-understanding-the-gateway.md) -- a deep dive into endpoints, authentication, and middleware.
