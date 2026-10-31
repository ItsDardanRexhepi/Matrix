# The Matrix SDK

A Python SDK for building on top of the Matrix platform.

## Installation

The SDK is the `sdk` package in this repository, and it is not published to
PyPI. Use it from your clone: run from the repository root, or install the
clone with `pip install -e .` from that root. Do not `pip install matrix-sdk`
or `pip install the-matrix`: those PyPI names belong to unrelated projects.

```python
from sdk import MatrixClient
```

## Quick Start

```python
from sdk import MatrixClient

client = MatrixClient("http://localhost:18790")

# Send a message to Trinity (the chat is public)
response = client.chat("What can you help me with?")
print(response.text)

# Check system health
health = client.health()
print(health.status)

# The gateway's operator key, for key-gated routes and for naming Neo or Morpheus
operator = MatrixClient("http://localhost:18790", api_key="YOUR_GATEWAY_KEY")
```

## Features

- **Chat**: Send messages to Trinity; with the operator key (`api_key`), to Neo and Morpheus too (sync and async)
- **Sessions**: Maintain conversation context across messages
- **Blockchain**: Ask Neo to use a tool from the platform's catalog of 195 Web3 capabilities across 20 categories (takes the operator key)
- **Memory**: Read/write agent memory (takes the operator key where one is set)
- **Health & Status**: `/health`, and `/status` with the operator key
- **Async**: `achat()`, `ahealth()`, `astatus()`, `astream_chat()` and the rest

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
