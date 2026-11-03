# Module 06: The SDK

## Overview

curl is useful for quick interactions; an application wants a client library. This repository ships two: a Python client (`sdk/`) and a JavaScript/TypeScript client (`sdk-js/`). Both are thin wrappers over the gateway's HTTP routes from Module 03. Neither is published to a package registry, so you use them from your clone.

## Python SDK

### Installation

The Python client is the `sdk` package in this repository. Use it from your clone: run your script from the repository root, or install the clone into your environment with `pip install -e .` from that root (the `sdk` package is part of the repository's own distribution).

Do not `pip install the-matrix` or `pip install matrix-sdk`: those names on PyPI belong to unrelated projects, and neither is this client.

### Connecting to the Gateway

```python
from sdk import MatrixClient

client = MatrixClient("http://localhost:18790")

# With the gateway's operator key, for key-gated routes and for naming Neo:
operator = MatrixClient("http://localhost:18790", api_key="YOUR_GATEWAY_KEY")
```

`api_key` is the gateway's operator key (`gateway.api_key`, or `MATRIX_API_KEY` on the gateway). When you give it, every request carries it as `Authorization: Bearer`. Without it the client reaches the public routes: the chat (as Trinity) and `/health`. The constructor makes no request; a gateway that is not reachable shows up as an error on the first call.

### Sending Chat Messages

```python
import asyncio
from sdk import MatrixClient


async def main():
    client = MatrixClient("http://localhost:18790")

    response = await client.achat("What is the current gas price on Base?")

    print(f"Agent: {response.agent}")
    print(f"Response: {response.text}")
    print(f"Tool calls: {len(response.tool_calls)}")


asyncio.run(main())
```

`achat()` posts to `/chat` and returns a `ChatResponse` with `text`, `agent`, `tool_calls`, `session_id`, `provider` and the raw JSON in `raw`. `chat()` is the synchronous form for scripts that are not already running an event loop. `achat(message, agent="neo")` names Neo, which takes the operator key.

### Streaming

```python
async def stream_example():
    client = MatrixClient("http://localhost:18790")
    async for text in client.astream_chat("Explain how DeFi lending works"):
        print(text, end="", flush=True)
```

`astream_chat()` reads `/chat/stream` and yields the text of each `token` event. The gateway runs the whole turn before it streams (Module 03), so the pieces arrive together at the end of the turn. If the stream route answers anything other than 200, the client falls back to one `/chat` call and yields its whole answer.

### Errors

A response other than 200 is raised as an `Exception` whose message carries the status and the body, for example `HTTP 403: {"error": "forbidden", ...}` when you name Neo without the key, or `HTTP 429: {"error": "rate_limited", ...}` when you are over the limit. There are no typed exception classes and no automatic retries.

### Blockchain Helpers

`convert_contract()`, `get_price()`, `send_payment()`, `mint_nft()`, `create_attestation()` and `ablockchain()` each send Neo a chat message asking him to use a tool, so each takes the operator key on a gateway that has one set, and each returns Neo's reply. `deploy_contract()` raises `NotImplementedError`: the platform deploys no contract for you.

## JavaScript SDK

### Installation

The JavaScript client is `sdk-js/` in this repository, and it is not published to npm. Build it from your clone and install it from that directory:

```bash
cd sdk-js
npm install
npm run build
cd ../your-app
npm install ../path/to/your/clone/sdk-js
```

### Connecting and Sending Messages

```javascript
import { MatrixClient } from "@the-matrix/sdk";

const client = new MatrixClient("http://localhost:18790", {
  apiKey: "YOUR_GATEWAY_KEY",   // optional: the operator key
});

async function main() {
  const response = await client.chat("What tokens are in my wallet?");

  console.log(`Response: ${response.response}`);
  console.log(`Tool calls: ${JSON.stringify(response.tool_calls)}`);
}

main();
```

The constructor also takes `walletSession` (a session token, sent as `X-Wallet-Session`), `defaultAgent` and `sessionId`. `chat()` returns the gateway's JSON: `response`, `tool_calls`, `session_id`, `agent` and `provider`. A failed request throws an `Error` naming the status.

### Streaming in JavaScript

```javascript
const stream = await client.chatStream("Explain how DAOs vote");

for await (const event of stream) {
  if (event.event === "token") {
    process.stdout.write(String(event.data.text));
  } else if (event.event === "done") {
    console.log(`\nTools used: ${JSON.stringify(event.data.tool_calls)}`);
  }
}
```

The events are the gateway's: `start`, `token`, `done` and `error`. `stream.text()` collects the tokens into one string.

## WebSocket Connections

The JavaScript SDK has a WebSocket client; the Python SDK does not.

```javascript
import { MatrixWebSocket } from "@the-matrix/sdk";

const ws = new MatrixWebSocket("http://localhost:18790");
await ws.connect();

ws.on("token", (frame) => process.stdout.write(frame.text));
ws.on("done", (frame) => console.log(`\n[${frame.agent}] done`));
ws.on("error", (frame) => console.error(frame.error));

ws.send("Check my wallet balance");
```

Each `send()` is one chat frame, and the answer comes back as `token` frames and a `done` frame on the same connection; `on("*", ...)` receives every frame. The WebSocket client sends no key, so it talks to Trinity. The server sends heartbeat pings every 30 seconds by default, and the runtime's WebSocket answers them.

## Key Takeaways

- Both SDKs live in this repository and are not published: `sdk/` (Python) and `sdk-js/` (JavaScript)
- Pass the operator key (`api_key` in Python, `apiKey` in JavaScript) for key-gated routes and for naming Neo
- Streaming yields the gateway's token events after the turn has run
- Errors are raised with the gateway's status and body; neither SDK retries
- The WebSocket client is JavaScript-only and talks to Trinity

---

**Next:** [Exercises](./EXERCISES.md) -- put everything you have learned into practice.
