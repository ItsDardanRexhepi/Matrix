# The Matrix SDK

A Python SDK for building on top of the Matrix platform.

## Installation

```bash
pip install matrix-sdk
```

Or use directly from the repository:

```python
from sdk import MatrixClient
```

## Quick Start

```python
from sdk import MatrixClient

client = MatrixClient("http://localhost:18790")

# Send a message to Trinity
response = client.chat("What can you help me with?")
print(response.text)

# Check system health
health = client.health()
print(health.status)
```

## Features

- **Chat**: Send messages to any agent (sync and async)
- **Sessions**: Maintain conversation context across messages
- **Blockchain**: Access the platform's catalog of 195 Web3 capabilities across 20 categories
- **Memory**: Read/write agent memory
- **Health & Status**: Full platform monitoring
- **Async**: Full async support with `achat()`, `ahealth()`, etc.

## API Reference

See `client.py` for the full API. The SDK mirrors the gateway's REST endpoints:

| Method | Endpoint | Description |
|--------|----------|-------------|
| `chat()` | `POST /chat` | Send a message |
| `health()` | `GET /health` | Health check |
| `status()` | `GET /status` | System status |
| `memory_read()` | `POST /memory/read` | Read agent memory |
| `memory_write()` | `POST /memory/write` | Write agent memory |
| `blockchain()` | via `/chat` | Execute blockchain ops |

## Examples

See `examples/` for working examples:
- `quickstart.py` — Basic chat and status
- `blockchain_ops.py` — A price read, a contract conversion (you deploy the result yourself), a payment, an attestation and the dashboard
- `migration_example.py` — Importing agents from other frameworks
