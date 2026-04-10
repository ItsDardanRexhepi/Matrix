# API Reference

The 0pnMatrx gateway is an `aiohttp` server that exposes a public REST
surface, a WebSocket stream, a `/bridge/v1/` API for the MTRX iOS app,
and Prometheus metrics.

All JSON requests and responses are UTF-8. Every response carries an
`X-Request-Id` header that matches the `request_id` field in the
structured JSON logs — quote it when filing issues.

---

## Middleware

Every request passes through this chain (outer → inner):

1. `request_id` — generates (or accepts) an `X-Request-Id` header and
   publishes it through an async context variable so every log line
   emitted for the request carries the same ID.
2. `cors` — permissive CORS for `*` (lock down behind Caddy / Ingress
   in production).
3. `auth` — enforces an API key on protected routes; accepts
   `Authorization: Bearer <key>` or `X-API-Key: <key>`.
4. `rate_limit` — token-bucket limiter keyed by authenticated wallet,
   then by API key, then by client IP.
5. `timeout` — per-request deadline from `gateway.request_timeout_seconds`
   (default 30s). Exceeding it returns `504 Gateway Timeout`.
6. `logging` — structured JSON access log with method, path, status,
   duration, and `request_id`.

---

## Public REST endpoints

### `POST /chat`

Send a message to an agent. Blocking — returns the full response at once.

**Request**

```json
{
  "message": "What can you help me with?",
  "agent": "trinity",
  "session_id": "optional-session-id"
}
```

| Field        | Type   | Required | Default   | Description                              |
|--------------|--------|----------|-----------|------------------------------------------|
| `message`    | string | yes      | —         | The user's message                       |
| `agent`      | string | no       | `trinity` | One of `trinity`, `neo`, `morpheus`      |
| `session_id` | string | no       | generated | Stable ID for conversation continuity    |

**Response `200`**

```json
{
  "response": "I can help you with smart contracts, payments, identity...",
  "agent": "trinity",
  "session_id": "abc123",
  "tool_calls": [],
  "audit": null
}
```

### `POST /chat/stream`

Same request body as `/chat`, but returns `text/event-stream` (SSE).
Each event is a JSON fragment with a `delta` or a terminal `done: true`.

### `GET /ws`

WebSocket endpoint. The frame limit is set by
`gateway.ws_max_message_size` (default 1 MiB) and the heartbeat
interval by `gateway.ws_heartbeat_seconds` (default 30s).

**Client → server**
```json
{"type": "chat", "agent": "trinity", "message": "hello"}
```

**Server → client**
```json
{"type": "delta", "content": "Hi, I'm Trinity."}
{"type": "done",  "session_id": "abc123"}
```

### `GET /health`

Lightweight liveness probe. Never authenticated.

```json
{
  "status": "ok",
  "models": { "ollama": true }
}
```

### `GET /status`

Full platform status — agents, model provider, active sessions.

```json
{
  "platform": "0pnMatrx",
  "version": "0.5.0",
  "agents": ["neo", "trinity", "morpheus"],
  "model": { "provider": "ollama", "primary": "llama3.1" },
  "sessions": 3,
  "uptime_seconds": 12345
}
```

### `POST /memory/read`

Read a slice of an agent's memory. Requires API key.

```json
{ "agent": "neo", "key": "last_deployment" }
```

### `POST /memory/write`

Write to an agent's memory. Requires API key.

```json
{ "agent": "neo", "key": "last_deployment", "value": {"tx": "0x..."} }
```

### `POST /auth/nonce`

Request a sign-in nonce for a wallet address.

```json
{ "address": "0xabc..." }
```

Response:
```json
{ "nonce": "Sign in to 0pnMatrx: 3f7c…", "expires_at": 1712668800 }
```

### `POST /auth/verify`

Verify a signed nonce and mint a session.

```json
{ "address": "0xabc...", "signature": "0x..." }
```

Response:
```json
{ "session_token": "…", "expires_at": 1712755200 }
```

### `GET /metrics`

JSON dump of internal counters / gauges / histograms. Protected
behind the API key.

### `GET /metrics/prom`

Prometheus text exposition format. Counters end in `_total`,
histograms expose 0.5 / 0.95 / 0.99 quantiles. Scrape this from your
Prometheus server.

---

## MTRX bridge endpoints (`/bridge/v1/`)

These endpoints power the MTRX iOS app. They share the same auth and
rate limiting as the public surface but return iOS-friendly envelopes.

| Method | Path                                    | Description                                             |
|--------|-----------------------------------------|---------------------------------------------------------|
| `POST` | `/bridge/v1/session/create`             | Create a new mobile session                             |
| `POST` | `/bridge/v1/session/resume`             | Resume an existing session by token                     |
| `POST` | `/bridge/v1/chat`                       | Chat with an agent (same semantics as `/chat`)          |
| `POST` | `/bridge/v1/action`                     | Execute a named action (e.g. `deploy_contract`)         |
| `POST` | `/bridge/v1/wallet/link`                | Link a wallet to the session                            |
| `GET`  | `/bridge/v1/wallet/status`              | Get the currently linked wallet and balance             |
| `GET`  | `/bridge/v1/config`                     | Fetch client-safe config (network, feature flags)       |
| `GET`  | `/bridge/v1/services`                   | List all registered blockchain services                 |
| `POST` | `/bridge/v1/push/register`              | Register an APNs device token                           |
| `GET`  | `/bridge/v1/dashboard`                  | Home-screen dashboard payload                           |
| `GET`  | `/bridge/v1/components`                 | List UI components available to the client              |
| `GET`  | `/bridge/v1/components/manifest`        | Full manifest with versions and checksums               |
| `GET`  | `/bridge/v1/components/{component_id}`  | Fetch a single component definition                     |

---

## Error envelope

All error responses share this shape:

```json
{
  "error": "rate_limited",
  "message": "Too many requests",
  "request_id": "01HV…"
}
```

| HTTP | `error` value      | When                                                 |
|------|--------------------|------------------------------------------------------|
| 400  | `invalid_request`  | Bad JSON, missing required field, schema violation  |
| 401  | `unauthorized`     | Missing or invalid API key / session token           |
| 403  | `forbidden`        | Valid credential but insufficient scope              |
| 404  | `not_found`        | Unknown route or resource                            |
| 408  | `request_timeout`  | Client did not finish sending the body in time       |
| 429  | `rate_limited`     | Token bucket exhausted for wallet / key / IP         |
| 500  | `internal_error`   | Unhandled server error — `request_id` is mandatory   |
| 504  | `gateway_timeout`  | Request exceeded `request_timeout_seconds`           |

---

## Web pages

| Method | Path                     | Description                          |
|--------|--------------------------|--------------------------------------|
| `GET`  | `/`                      | Landing page                         |
| `GET`  | `/chat`                  | Web chat interface (Trinity)         |
| `GET`  | `/pricing`               | Pricing and subscription tiers       |
| `GET`  | `/audit`                 | Glasswing security audit service     |
| `GET`  | `/marketplace`           | Developer plugin marketplace         |
| `GET`  | `/services/conversion`   | Smart contract conversion service    |

---

## Subscription endpoints

### `GET /subscription/status`

Get the current subscription tier and usage for a wallet.

**Query:** `?wallet=0xabc...`

```json
{
  "tier": "pro",
  "usage": { "contract_conversions": 12, "nft_mints": 3 },
  "limits": { "contract_conversions": 100, "nft_mints": 50 },
  "trial_active": false
}
```

### `POST /subscription/checkout`

Create a Stripe checkout session for upgrading.

```json
{ "wallet_address": "0xabc...", "tier": "pro" }
```

### `POST /subscription/webhook`

Stripe webhook receiver. Automatically processes subscription events.

---

## Audit service endpoints

### `POST /audit/scan`

Submit a smart contract for Glasswing security scanning.

```json
{
  "contract_source": "pragma solidity ^0.8.20; ...",
  "contract_name": "MyToken"
}
```

### `GET /audit/report/{report_id}`

Retrieve a completed audit report.

---

## Plugin marketplace endpoints

### `GET /marketplace/plugins`

List available plugins. Supports query filters:

| Param      | Type   | Description                        |
|------------|--------|------------------------------------|
| `category` | string | Filter by category                 |
| `tier`     | string | Filter by minimum tier requirement |

### `GET /marketplace/plugins/{plugin_id}`

Get details for a single plugin.

### `POST /marketplace/plugins/purchase`

Purchase or install a plugin.

```json
{ "wallet_address": "0xabc...", "plugin_id": "plugin_abc123" }
```

### `POST /marketplace/plugins/submit`

Submit a new plugin for review (Enterprise tier required).

```json
{
  "name": "My Plugin",
  "description": "Does something useful",
  "price_usd": 4.99,
  "category": "defi",
  "repository_url": "https://github.com/..."
}
```

### `GET /marketplace/plugins/purchased`

List all plugins purchased by a wallet.

**Query:** `?wallet=0xabc...`

---

## A2A commerce endpoints

### `GET /a2a/services`

List all registered agent-to-agent services.

### `POST /a2a/services/register`

Register a new A2A service.

### `POST /a2a/services/invoke`

Invoke an A2A service by ID.

---

## Extensions registry

### `GET /extensions/registry`

List all registered platform extensions.

### `POST /extensions/register`

Register a new extension.

---

## Social media endpoints

### `POST /social/announce`

Post an announcement to configured social channels (Twitter, Discord).

```json
{
  "message": "New feature launched!",
  "channels": ["twitter", "discord"]
}
```

---

## SDK

For programmatic access, use the Python SDK:

```python
from sdk import OpenMatrixClient

client = OpenMatrixClient("http://localhost:18790", api_key="sk-...")
response = client.chat("Deploy a smart contract for me")
print(response.text)
```

Or the JavaScript SDK:

```typescript
import { OpenMatrixClient } from '@opnmatrx/sdk';

const client = new OpenMatrixClient('http://localhost:18790', { apiKey: 'sk-...' });
const response = await client.chat('Deploy a smart contract for me');
console.log(response.text);
```

See `sdk/README.md` for full SDK documentation.
