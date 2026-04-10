# Module 06: The SDK

## Overview

While curl and the MTRX CLI are useful for quick interactions, production applications need a programmatic interface. 0pnMatrx provides official SDKs for Python and JavaScript that handle authentication, connection management, streaming, and error handling.

## Python SDK

### Installation

The Python SDK is included with the 0pnMatrx repository. For standalone use:

```bash
pip install opnmatrx
```

### Connecting to the Gateway

```python
from sdk import OpenMatrixClient

client = OpenMatrixClient(
    gateway_url="http://localhost:18790",
    api_key="mtrx_k_your_api_key_here"
)
```

The client verifies connectivity on initialization by calling `/health`. If the gateway is not reachable, it raises a `ConnectionError` immediately rather than failing on the first request.

### Sending Chat Messages

```python
import asyncio
from sdk import OpenMatrixClient


async def main():
    client = OpenMatrixClient(
        gateway_url="http://localhost:18790",
        api_key="mtrx_k_your_api_key_here"
    )

    # Simple request-response
    response = await client.chat("What is the current gas price on Base?")

    print(f"Request ID: {response.request_id}")
    print(f"Response: {response.text}")
    print(f"Tools used: {response.tools_used}")


asyncio.run(main())
```

The `chat()` method sends a message to `/chat` and returns a `ChatResponse` object with typed attributes for `request_id`, `text`, `agent`, `tools_used`, and `timestamp`.

### Handling Streaming Responses

For real-time output, use the streaming interface:

```python
async def stream_example():
    client = OpenMatrixClient(
        gateway_url="http://localhost:18790",
        api_key="mtrx_k_your_api_key_here"
    )

    async for event in client.chat_stream("Explain how DeFi lending works"):
        if event.type == "token":
            print(event.content, end="", flush=True)
        elif event.type == "tool_call":
            print(f"\n[Neo invoking: {event.tool}]")
        elif event.type == "tool_result":
            print(f"[Tool complete: {event.tool}]")
        elif event.type == "done":
            print(f"\n\nRequest ID: {event.request_id}")
```

The `chat_stream()` method returns an async generator that yields `StreamEvent` objects. Each event has a `type` field indicating whether it is a text token, a tool invocation, a tool result, or the final completion signal.

### Error Handling

```python
from sdk import OpenMatrixClient
from sdk.exceptions import (
    AuthenticationError,
    RateLimitError,
    TimeoutError,
    GatewayError,
)

try:
    response = await client.chat("Deploy a token")
except AuthenticationError:
    print("Invalid or expired API key")
except RateLimitError as e:
    print(f"Rate limited. Retry after {e.retry_after} seconds")
except TimeoutError:
    print("Request timed out -- the operation may still be processing")
except GatewayError as e:
    print(f"Gateway error: {e.status_code} - {e.message}")
```

## JavaScript SDK

### Installation

```bash
npm install @opnmatrx/sdk
```

### Connecting and Sending Messages

```javascript
import { OpenMatrixClient } from "@opnmatrx/sdk";

const client = new OpenMatrixClient({
  gatewayUrl: "http://localhost:18790",
  apiKey: "mtrx_k_your_api_key_here",
});

async function main() {
  const response = await client.chat("What tokens are in my wallet?");

  console.log(`Request ID: ${response.requestId}`);
  console.log(`Response: ${response.text}`);
  console.log(`Tools used: ${JSON.stringify(response.toolsUsed)}`);
}

main();
```

### Streaming in JavaScript

```javascript
const stream = client.chatStream("Create a DAO called BuilderDAO");

for await (const event of stream) {
  switch (event.type) {
    case "token":
      process.stdout.write(event.content);
      break;
    case "tool_call":
      console.log(`\n[Neo invoking: ${event.tool}]`);
      break;
    case "done":
      console.log(`\nComplete: ${event.requestId}`);
      break;
  }
}
```

## WebSocket Connections

Both SDKs support persistent WebSocket connections for session-based interactions:

```python
async def websocket_example():
    client = OpenMatrixClient(
        gateway_url="http://localhost:18790",
        api_key="mtrx_k_your_api_key_here"
    )

    async with client.connect_ws() as ws:
        # Send multiple messages on the same connection
        response1 = await ws.send("Check my wallet balance")
        print(response1.text)

        response2 = await ws.send("Now transfer 10 USDC to 0xabc...")
        print(response2.text)

        # Morpheus may intervene for the transfer
        if response2.requires_confirmation:
            print(f"Confirmation required: {response2.confirmation_prompt}")
            await ws.confirm()  # or ws.cancel()
```

The WebSocket connection maintains context between messages within the same session. The server sends heartbeat pings every 30 seconds; the SDK handles pong responses automatically.

```javascript
const ws = await client.connectWs();

ws.on("message", (response) => {
  console.log(response.text);
});

ws.on("confirmation", (prompt) => {
  console.log(`Confirm: ${prompt.description}`);
  ws.confirm(); // or ws.cancel()
});

await ws.send("Deploy a staking contract");
```

## SDK Configuration Options

Both SDKs accept the same configuration parameters:

| Parameter | Default | Description |
|-----------|---------|-------------|
| `gateway_url` | `http://localhost:18790` | Gateway address |
| `api_key` | Required | Your API key |
| `timeout` | 30000 | Request timeout in milliseconds |
| `max_retries` | 3 | Automatic retry count for transient errors |
| `retry_delay` | 1000 | Base delay between retries in milliseconds |

## Key Takeaways

- Python SDK: `from sdk import OpenMatrixClient`
- JavaScript SDK: `npm install @opnmatrx/sdk`
- Both support synchronous chat, streaming, and WebSocket connections
- Streaming returns typed events: token, tool_call, tool_result, done
- WebSocket connections maintain session context
- Built-in error handling for auth, rate limiting, timeouts, and gateway errors

---

**Next:** [Exercises](./EXERCISES.md) -- put everything you have learned into practice.
