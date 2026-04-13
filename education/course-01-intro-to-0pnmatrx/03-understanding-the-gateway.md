# Module 03: Understanding the Gateway

## What the Gateway Does

The gateway is the central nervous system of 0pnMatrx. Every interaction -- whether from the MTRX CLI, a web interface, or a third-party application -- passes through the gateway. It handles authentication, rate limiting, request routing, and response formatting. Understanding the gateway is essential for building anything on top of 0pnMatrx.

## REST Endpoints

The gateway exposes five primary endpoints:

### POST /chat

The standard request-response endpoint. Send a message, receive a complete response after processing finishes.

```bash
curl -X POST http://localhost:18790/chat \
  -H "Content-Type: application/json" \
  -H "Authorization: Bearer YOUR_API_KEY" \
  -d '{"message": "Deploy an ERC-20 token called TestCoin with 1000 supply"}'
```

Use this when you want a simple request-response interaction and do not need real-time progress updates. The response arrives only after all processing (including any blockchain operations) is complete.

### POST /chat/stream

Server-Sent Events (SSE) endpoint for streaming responses. Trinity sends partial responses as they are generated, and you receive progress updates as Neo executes tools.

```bash
curl -X POST http://localhost:18790/chat/stream \
  -H "Content-Type: application/json" \
  -H "Authorization: Bearer YOUR_API_KEY" \
  -d '{"message": "Explain how staking works on Base"}'
```

The response arrives as a stream of events:

```
data: {"type": "token", "content": "Staking "}
data: {"type": "token", "content": "on Base "}
data: {"type": "token", "content": "works by..."}
data: {"type": "tool_call", "tool": "staking_info", "status": "started"}
data: {"type": "tool_result", "tool": "staking_info", "status": "complete"}
data: {"type": "done", "request_id": "req_xyz789"}
```

Use this for user-facing applications where you want to display responses as they arrive, similar to how ChatGPT streams its output.

### WebSocket /ws

Persistent bidirectional connection for real-time interaction. Ideal for applications that maintain ongoing sessions.

```javascript
const ws = new WebSocket("ws://localhost:18790/ws");
ws.onopen = () => {
  ws.send(JSON.stringify({
    type: "auth",
    api_key: "YOUR_API_KEY"
  }));
};
ws.onmessage = (event) => {
  const data = JSON.parse(event.data);
  console.log(data);
};
```

After authenticating, send messages and receive responses on the same connection. The WebSocket interface supports the same functionality as `/chat` and `/chat/stream` combined, with the added benefit of persistent state. The server sends heartbeat pings every 30 seconds to keep the connection alive.

### GET /health

Unauthenticated. Returns basic liveness status. Designed for load balancers, container orchestrators, and monitoring systems.

### GET /status

Unauthenticated. Returns detailed system status including agent states, active service count, and uptime.

## Authentication

The gateway supports two methods of authentication, both carrying an API key:

### Bearer Token (Authorization Header)

```
Authorization: Bearer mtrx_k_abc123def456
```

### X-API-Key Header

```
X-API-Key: mtrx_k_abc123def456
```

Both methods are equivalent. Use whichever fits your HTTP client or framework. API keys are prefixed with `mtrx_k_` for easy identification in logs and configuration.

API keys are tied to subscription tiers:

| Tier | Rate Limit | Features |
|------|------------|----------|
| Free | Base tier | Core services, community support |
| Pro | Elevated | All services, priority processing |
| Enterprise | Highest | All services, dedicated support, custom plugins |

Subscription pricing available in the MTRX app.

## Rate Limiting

The gateway enforces rate limits at three levels, checked in order:

### 1. Wallet-Based Rate Limiting

If the request is associated with a blockchain wallet address (via the `X-Wallet-Address` header), rate limits are applied per wallet. This prevents a single wallet from monopolizing service resources during heavy blockchain operations.

### 2. API Key Rate Limiting

Each API key has rate limits based on its subscription tier. Limits are applied using a sliding window algorithm. When you exceed your limit, the response includes a `Retry-After` header indicating when you can send the next request.

### 3. IP-Based Rate Limiting

As a final fallback, the gateway rate-limits by IP address. This catches unauthenticated abuse and provides a baseline protection layer. The `/health` and `/status` endpoints have their own separate, more generous IP limits.

Rate limit headers are included in every response:

```
X-RateLimit-Limit: 100
X-RateLimit-Remaining: 97
X-RateLimit-Reset: 1680000000
```

## The Middleware Chain

Every request passes through a chain of middleware before reaching the agent pipeline. Understanding this chain helps when debugging unexpected behavior:

```
Incoming Request
    |
    v
[1] request_id  -- Assigns a unique ID (req_xxx) to every request
    |
    v
[2] cors        -- Handles Cross-Origin Resource Sharing headers
    |
    v
[3] auth        -- Validates API key, loads user context and tier
    |
    v
[4] rate_limit  -- Checks wallet, API key, and IP rate limits
    |
    v
[5] timeout     -- Sets a maximum processing time for the request
    |
    v
[6] logging     -- Records request metadata for observability
    |
    v
Agent Pipeline (Trinity -> Neo -> Morpheus if needed)
```

Each middleware can short-circuit the chain. If authentication fails at step 3, steps 4-6 never execute. If rate limiting rejects at step 4, the request never reaches the agent pipeline.

The **timeout middleware** is particularly important for blockchain operations. Deploying a contract or waiting for transaction confirmation can take time. The default timeout is generous enough for standard operations, but complex multi-step tasks may need extended timeouts via the `X-Timeout` header (in milliseconds).

The **logging middleware** records the request ID, endpoint, response status, and processing duration. It does not log message content for privacy -- only metadata.

## Key Takeaways

- Five endpoints: `/chat`, `/chat/stream`, `/ws`, `/health`, `/status`
- Two authentication methods: Bearer token or X-API-Key header
- Three rate limiting tiers: wallet, API key, IP address
- Six middleware stages process every request in order
- The WebSocket interface provides persistent, bidirectional communication
- Rate limit headers are always included in responses

---

**Next:** [Your First Plugin](./04-your-first-plugin.md) -- extend 0pnMatrx with custom functionality.
