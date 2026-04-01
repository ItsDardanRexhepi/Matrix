# API Reference

## Gateway Endpoints

The 0pnMatrx gateway exposes three HTTP endpoints.

### POST /chat

Send a message to an agent and receive a response.

**Request:**
```json
{
  "message": "What can you help me with?",
  "agent": "trinity",
  "session_id": "optional-session-id"
}
```

**Response:**
```json
{
  "response": "I can help you with smart contracts, payments, identity...",
  "agent": "trinity",
  "session_id": "abc123"
}
```

**Parameters:**

| Field | Type | Required | Description |
|-------|------|----------|-------------|
| `message` | string | yes | The user's message |
| `agent` | string | no | Agent to route to (default: `trinity`) |
| `session_id` | string | no | Session ID for conversation continuity |

### GET /health

Check system health and model availability.

**Response:**
```json
{
  "status": "ok",
  "models": {
    "ollama": true
  }
}
```

### GET /status

Get system status including active agents and model configuration.

**Response:**
```json
{
  "platform": "0pnMatrx",
  "version": "1.0.0",
  "agents": ["neo", "trinity", "morpheus"],
  "model": {
    "provider": "ollama",
    "primary": "llama3.1"
  },
  "sessions": 3
}
```

## SDK

For programmatic access, use the Python SDK:

```python
from sdk.openmatrix_sdk import OpenMatrixClient

client = OpenMatrixClient("http://localhost:18790")
response = client.chat("Deploy a smart contract for me")
print(response.text)
```

See `sdk/README.md` for full SDK documentation.
