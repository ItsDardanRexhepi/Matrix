# Module 02: Quick Start

## Goal

By the end of this module, you will have 0pnMatrx running on your machine, the gateway serving requests on port 18790, and you will have had your first conversation with Trinity.

## Step 1: Clone the Repository

```bash
git clone https://github.com/0pnMatrx/0pnMatrx.git
cd 0pnMatrx
```

Verify you are in the right directory:

```bash
ls gateway/
```

You should see `server.py`, `__init__.py`, and several other modules.

## Step 2: Run Setup

The setup script installs dependencies and configures your local environment:

```bash
python setup.py
```

This will:
- Install all Python dependencies from `requirements.txt`
- Create a default configuration file if one does not exist
- Generate a local API key for development
- Verify that Python 3.11+ is available

If you encounter version errors, confirm your Python version:

```bash
python --version
```

You need Python 3.11 or higher. If you have multiple versions installed, you may need to use `python3.11` or `python3` explicitly.

## Step 3: Start the Gateway

```bash
python -m gateway.server
```

You should see output indicating the server has started:

```
[INFO] 0pnMatrx Gateway starting...
[INFO] Loading middleware chain...
[INFO] Agents initialized: Neo, Trinity, Morpheus
[INFO] 30 blockchain services loaded
[INFO] Gateway listening on port 18790
```

The gateway is now running. Leave this terminal open and open a new terminal for the next steps.

## Step 4: Check Health

In your new terminal, verify the gateway is responding:

```bash
curl http://localhost:18790/health
```

Expected response:

```json
{
  "status": "healthy",
  "timestamp": "2026-04-10T12:00:00Z",
  "version": "1.0.0"
}
```

The `/health` endpoint is unauthenticated -- it is designed for load balancers and monitoring systems to check that the server is running.

## Step 5: Check Status

The `/status` endpoint provides more detail about the running system:

```bash
curl http://localhost:18790/status
```

Expected response:

```json
{
  "status": "operational",
  "agents": {
    "neo": {"status": "active", "role": "execution"},
    "trinity": {"status": "active", "role": "conversation"},
    "morpheus": {"status": "active", "role": "confirmation"}
  },
  "services": {
    "total": 30,
    "active": 30
  },
  "uptime_seconds": 45
}
```

This tells you all three agents are loaded and all 30 blockchain services are available.

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
  "response": "Hello! I'm Trinity, your guide to 0pnMatrx. I can help you with a wide range of blockchain operations on Base...",
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

**Module not found**: Make sure you ran `python setup.py` first and are using the correct Python version.

**Connection refused**: Verify the gateway is still running in your other terminal. Check for error messages in its output.

**Authentication failed**: Double-check your API key. You can find it in your local configuration file or regenerate it by running setup again.

## Key Takeaways

- The gateway runs on port 18790 and is started with `python -m gateway.server`
- `/health` is unauthenticated and returns basic liveness information
- `/status` provides detailed information about agents and services
- `/chat` requires authentication via Bearer token
- Every response includes a `request_id` for tracing

---

**Next:** [Understanding the Gateway](./03-understanding-the-gateway.md) -- a deep dive into endpoints, authentication, and middleware.
