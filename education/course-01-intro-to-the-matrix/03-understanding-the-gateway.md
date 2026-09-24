# Module 03: Understanding the Gateway

## What the Gateway Does

The gateway is the central server of The Matrix. Every interaction -- from the MTRX app, the web chat page it serves at `/chat`, or your own HTTP client -- passes through it. It handles authentication, rate limiting, request routing, and response formatting. Understanding the gateway is essential for building anything on top of The Matrix.

## REST Endpoints

The gateway exposes five primary endpoints for talking to the agents and checking on it:

### POST /chat

The standard request-response endpoint. Send a message, receive a complete response after processing finishes.

```bash
curl -X POST http://localhost:18790/chat \
  -H "Content-Type: application/json" \
  -d '{"message": "What is my staking position?"}'
```

Use this when you want a simple request-response interaction. The response arrives only after all processing (including any service calls the agent makes) is complete. `/chat` is public: it needs no key, and it answers as Trinity. Naming `"agent": "neo"` or `"morpheus"` takes the operator key (below); without it the answer is `403`.

### POST /chat/stream

Server-Sent Events (SSE) endpoint with the same body as `/chat`. The gateway runs the whole turn first, then streams the finished answer to you in pieces of about 80 characters:

```bash
curl -N -X POST http://localhost:18790/chat/stream \
  -H "Content-Type: application/json" \
  -d '{"message": "Explain how staking works on Base"}'
```

The response arrives as a stream of named events:

```
event: start
data: {"session_id": "...", "agent": "trinity"}

event: token
data: {"text": "Staking on Base works by ..."}

event: done
data: {"session_id": "...", "agent": "trinity", "tool_calls": [...], "provider": "..."}
```

A turn that fails sends an `error` event, then `done`. There is no event per tool call: the tools the agent used arrive together in `done`.

### WebSocket /ws

A persistent connection for a series of turns. Each turn is a JSON frame; there is no separate authentication message. A key or a session, when you have one, rides on the handshake's headers.

```javascript
const ws = new WebSocket("ws://localhost:18790/ws");
ws.onopen = () => {
  ws.send(JSON.stringify({
    type: "chat",
    message: "What is my staking position?",
    session_id: "my-session"
  }));
};
ws.onmessage = (event) => {
  const data = JSON.parse(event.data);
  console.log(data);   // {"type": "token", ...} frames, then {"type": "done", ...}
};
```

The answer comes back as `token` frames and a final `done` frame, the same content as `/chat/stream`; a refused or malformed frame is answered with an `error` frame and the connection stays open. The server sends heartbeat pings every 30 seconds by default (`gateway.websocket.heartbeat_seconds`).

### GET /health

Unauthenticated. Returns basic liveness status. Designed for load balancers, container orchestrators, and monitoring systems.

### GET /status

Behind the operator key when one is set. Returns the enabled agents, the model provider, session and request counts, uptime, memory use, and a health probe of each subsystem.

## Authentication

Authentication is off until the gateway has a key: set `gateway.api_key` in the config or `MATRIX_API_KEY` in the environment. With a key set, the protected routes need one of two credentials.

### The operator key

The key you configured, presented as a bearer token:

```
Authorization: Bearer YOUR_GATEWAY_KEY
```

or as a query parameter, `?api_key=YOUR_GATEWAY_KEY`. No other header carries it, and the gateway imposes no prefix or format: it accepts whatever string is configured (setup generates a random one if you do not choose one). The operator key opens every route.

### A wallet session

The MTRX app signs in and receives a session token (`/api/v1/auth/apple`, or Sign-In with Ethereum through `/auth/nonce` and `/auth/verify`). It presents the token as `X-Wallet-Session: <token>` or as `Authorization: Bearer <token>`. A session reaches only the routes the app uses (`gateway/session_routes.py`); any other route answers it `403`.

The chat entrances (`/chat`, `/chat/stream`, `/ws`, `/bridge/v1/chat`), `/health`, the sign-in routes and the web pages are public.

The key is not tied to a subscription tier. Every capability in the catalog is free tier, and nothing in the gateway reads a subscription to decide what a request may do. Pro and Enterprise are the MTRX app's subscription tiers: the gateway records a subscription the App Store verifies (`POST /api/v1/iap/verify`), and no capability, limit or route depends on the tier yet.

## Rate Limiting

Every request that gets past authentication (other than a CORS preflight) is counted in one of three buckets, picked in this order:

### 1. Wallet session

A request carrying a live `X-Wallet-Session` is counted per wallet address, so one signer cannot use up the gateway's capacity. (A session sent as `Authorization: Bearer` is counted by IP, below.)

### 2. Operator key

A request carrying the operator key is counted in the key's bucket.

### 3. IP address

Everything else is counted per client IP (the first `X-Forwarded-For` address when a proxy sets one). This covers anonymous traffic, including `/health` and the public chat.

Each bucket is a token bucket. The defaults are 120 requests a minute with a burst of 30 for the operator key and for wallet sessions, and 20 a minute with a burst of 5 per IP (`gateway.rate_limit_rpm_*` and `gateway.rate_limit_burst_*`). A request over the limit is answered `429` with `{"error": "rate_limited"}`. The gateway sends no rate-limit headers, so a client that is refused should back off and retry.

## The Middleware Chain

Every request passes through a chain of middleware before reaching its handler. Understanding this chain helps when debugging unexpected behavior:

```
Incoming Request
    |
    v
[1] request_id        -- Takes the caller's X-Request-ID or makes one, and returns it on the response
    |
    v
[2] cors              -- Answers preflights; allows the origins in gateway.cors_origins (none by default)
    |
    v
[3] auth              -- Checks the operator key or a wallet session on protected routes
    |
    v
[4] security_context  -- Carries the caller's identity to the security gate for /api/v1 POSTs; decides nothing
    |
    v
[5] rate_limit        -- Counts the request in its wallet, key or IP bucket
    |
    v
[6] timeout           -- Stops a request that runs past the deadline
    |
    v
[7] logging           -- Records method, path, status and duration
    |
    v
Handler (for the chat entrances: Trinity by default, Neo or Morpheus with the operator key)
```

A middleware can answer on its own. If authentication fails at step 3, the request never reaches the rate limiter or its handler; if rate limiting refuses it at step 5, it never reaches the handler.

The **timeout** is `gateway.request_timeout_seconds`, 120 seconds by default; a request that runs longer is answered `504`. The WebSocket is not timed out, and a request cannot ask for a longer deadline.

The **logging middleware** records the request's method, path, response status, and processing duration. It does not log message content -- only metadata.

## Key Takeaways

- Five endpoints: `/chat`, `/chat/stream`, `/ws`, `/health`, `/status`
- The chat entrances are public; naming Neo or Morpheus takes the operator key
- Two credentials: the operator key (`Authorization: Bearer` or `?api_key=`) and a wallet session
- Three rate-limit buckets: wallet session, operator key, IP address; over the limit is `429`
- Seven middleware stages process every request in order
- The WebSocket takes one JSON frame per turn and answers with token frames and a done frame

---

**Next:** [Your First Plugin](./04-your-first-plugin.md) -- extend The Matrix with custom functionality.
