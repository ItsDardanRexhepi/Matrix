# 0pnMatrx SDK

A Python SDK for building on top of the 0pnMatrx platform.

## Installation

```bash
pip install openmatrix-sdk
```

Or use directly from the repository:

```python
from sdk.openmatrix_sdk import OpenMatrixClient
```

## Quick Start

```python
from sdk.openmatrix_sdk import OpenMatrixClient

client = OpenMatrixClient("http://localhost:18790")

# Send a message to Trinity
response = client.chat("What can you help me with?")
print(response.text)

# Check system health
health = client.health()
print(health)
```

## Features

- **Chat**: Send messages to any agent
- **Sessions**: Maintain conversation context across messages
- **Health**: Check system and model status
- **Async**: Full async support with `AsyncOpenMatrixClient`

## API Reference

See `openmatrix_sdk.py` for the full API. The SDK mirrors the gateway's REST endpoints:

| Method | Endpoint | Description |
|--------|----------|-------------|
| `chat()` | `POST /chat` | Send a message |
| `health()` | `GET /health` | Health check |
| `status()` | `GET /status` | System status |
