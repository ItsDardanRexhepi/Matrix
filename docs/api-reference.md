# API Reference

The Matrix gateway is an `aiohttp` server that exposes a public REST
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
| `context`    | string | no       | —         | Per-turn client context (language, recap). Up to 8,000 characters; reaches the model prefixed to that turn's message, between platform-written labels that mark it as client-supplied and mark where it ends. It is sent at the user role — never as system text, on any model provider (the Anthropic and Gemini clients merge every system message into the platform's instructions, so a separate system message would not stay separate there) — and never stored. It does not choose the model tier: intelligent routing classifies the message as the user wrote it. Honoured identically on `/chat`, `/chat/stream`, `/ws` and `/bridge/v1/chat`. |
| `app_attest` | object | no       | —         | App Attest assertion, verified by the security gate |

`/chat`, `/chat/stream`, `/ws` and `/bridge/v1/chat` are one chat with one
posture: all four are public, and none takes the caller's identity from the
body — see [Authentication](#authentication).

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
  "platform": "The Matrix",
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

## Authentication

Two credentials exist, and they open different doors.

| credential | how it is presented | what it opens |
|---|---|---|
| **The operator key** (`gateway.api_key` / `MATRIX_API_KEY`) | `Authorization: Bearer <key>` or `?api_key=` | every route. Naming `agent: "neo"` or `"morpheus"` on `/chat`, `/chat/stream`, `/ws` or `/bridge/v1/chat` requires it. |
| **A wallet session** — the token returned by `POST /auth/verify` (Sign-In with Ethereum) or `POST /api/v1/auth/apple` (Sign in with Apple) | `Authorization: Bearer <token>` or `X-Wallet-Session: <token>` | exactly the routes the iOS app calls: `gateway/session_routes.py`, generated by `scripts/generate_session_routes.py` from the app's own call sites (81 routes at the time of writing). Any other non-public route answers **403** to a session. `/memory/read` and `/memory/write` are deliberately excluded: they read an agent's memory shared by every user. |

**A URL on the list is not every operation behind it.** Three session-reachable doors dispatch an operation by name into the same service dispatcher the dedicated `/api/v1` routes call: `POST /api/v1/capabilities/{id}/invoke`, `POST /bridge/v1/action`, and the chat agent's `request_execution` / `platform_action` tools on the public chat surfaces. Each refuses a session, and an anonymous chat caller, any operation whose (service, method) backs a route the session is refused — the same answer the dedicated route gives (`SERVICE_METHODS_OFF_ALLOWLIST` in `gateway/session_routes.py`). The operator key is unaffected.

Without either, a non-public route answers **401** — whether or not the path exists; an anonymous caller is not told which paths are real. A **401** always means the credential is bad (absent, expired, or never issued): with a live session, a path that matches no route answers **404** and a matched path with another method answers **405** with `Allow`, exactly as they answer the operator — never 401, which the iOS client reads as a bad token and signs the user out. Sessions expire (`gateway.wallet_session_ttl_seconds`, default 24 h); an expired token is no credential anywhere.

**Identity is derived from a session; on the operator path it is asserted, and this says which.** On a request carrying a wallet session the caller's identity is the session's subject, and nothing in the request overrides it — the wallet linked to the Apple user when one exists, else `apple:<sub>` or the SIWE address. As the caller's identity — what the security gate attributes a POST to an `/api/v1/*` route to, the caller the chat entrances hand the dispatcher, the follower on `/social/follow`, the identity `/security/appattest/attest` verifies for — an `X-Wallet-Address` or `X-Apple-Id` header or a `wallet` / `apple_id` body field is consulted only when no session is presented and the request carries the operator key (an operator integration naming the user it acts for; development, where auth is off, counts). Two things are not that: the `identity` a client names on `/security/appattest/challenge` and in the attest body is the binding of a server-issued one-time challenge, not a credential; and some `/api/v1` service routes take a `wallet` parameter the service acts on (for example `/api/v1/defi/swap/execute`), which this gateway does not check against the caller. The chat entrances are public, so this matters most there: an anonymous chat has **no** identity, and the body's `wallet`, `apple_id`, `wallet_connected`, `network`, `balance`, `jurisdiction` and `total_transactions` are read only from an operator's request — they feed the dispatcher's caller identity and the security gates' verdicts, so a caller may not write them about itself. Where no session is presented and the request is the operator's, the value is ASSERTED, not authenticated — the header as the caller wrote it — and the routes that record or check "the caller" (for example `/api/v1/capabilities/{id}/invoke`, `/api/v1/insurance/claim`, `/api/v1/paymaster/sign`) receive that asserted value. A wallet proven by `POST /auth/verify` while holding an Apple session is linked to that Apple user.

**Conversations belong to whoever started them.** `session_id` on the chat surfaces is the caller's own id, never `"default"`: with a session and no id, the conversation is `user:<subject>`; in production a request with no id and no session answers **400 `session_required`** (development keeps `"default"` for local runs). A conversation with an owner is continued only by that account (**403** otherwise); an ownerless one is claimed by the first signed-in caller. A claim is stored when it is made, before the conversation has any stored turn, and it stays until the account is deleted — also when the turn that made it fails and the conversation never gets a stored turn. A turn is stored — both the conversation and the agent memory it writes — only if the claim it was admitted under still stands when the model answers. Each claim is its own record: deleting the account removes it, and the same account signing in again makes a new one. So a turn still running when its account is deleted is not written back, even if the account has signed in again (or kept another signed-in session) and continued that conversation meanwhile, and it removes nothing the re-created account has stored. The same holds for an anonymous turn that was already running when an account claimed its conversation and was then deleted: deletion leaves the conversation unclaimed again, but not in the state that turn was admitted under, so it is not stored and the next caller naming the id is not shown it. To tell the two states apart, deletion keeps the ids of the erased conversations and when they were erased (no owner, no content) for `conversation_erasure_log_seconds` (default one hour; a value that is not a finite, non-negative number of seconds is ignored with a warning and the default is used), then prunes them on every later account deletion, also one that erases no conversation, and on the gateway's five-minute sweep; an anonymous turn admitted before a deletion and still running after that deletion's entry is pruned is not stored. The account's own `user:<subject>` conversation is erased but its id is not kept: it names the account, and no turn is stored on it without the account's claim. The other kept ids are the ones the client chose. An ownerless (anonymous) conversation has no credential but its id: whoever presents the id continues it, so a client must generate the id unguessably (the iOS app and the web chat page use random UUIDs). An id of the form `user:<subject>` names an account and is refused (**403**) to every caller but that account's session. A `session_id` is taken as one spelling everywhere — surrounding whitespace removed, at most 100 characters — so `"conv-A "` names `conv-A`. The bridge legs keyed by `session_id` follow the same rule: `/bridge/v1/session/resume` and `/bridge/v1/push/register` answer **403** for a conversation another account owns, and a wallet linked with `/bridge/v1/wallet/link` is shown by `/bridge/v1/wallet/status` and `/bridge/v1/dashboard`, and acts in `/bridge/v1/action`, only for the account that linked it. Agent memory and protocol state are scoped to the account, or to the conversation when anonymous — in a namespace of its own (`conv:<session_id>`), so an anonymous `session_id` spelled like an account's subject (a SIWE address, `apple:<sub>`) neither reads nor writes that account's memory. `DELETE /api/v1/auth/account` removes the session it is sent with (another session of the same account, such as one on a second device, stays valid until it expires), the account's conversations, its scoped memory and protocol state, the memory its conversations gathered before it claimed them, and its push tokens: every device registered under one of the account's sessions, and a device with no recorded owner (one stored before tokens carried one) filed under one of the account's conversations. A device registered without a session to a conversation the account never owned is not found. If erasing the account's conversations and memory fails, it erases *none* of them — the conversations, their claims, the account's scoped memory and the memory its conversations gathered before it claimed them all go in one transaction — and the deletion answers **503 `storage failure`** and removes nothing further: the session it was sent with stays valid and its devices stay registered, so the client can retry and the retry deletes all of it, rather than `200` with the data still stored. The gateway drops its own in-process copies of the account's conversations either way, so no later caller naming one of those ids is served the deleted account's history. A request presenting no live session (an expired token, or none) answers **401 `session required`**: there is no account to identify, so nothing is deleted — where this answered `200 {"success": true}` having deleted nothing. The two removals after the erasure answer the same way: if the push tokens cannot be removed, or the session cannot be removed, the deletion answers **503 `storage failure`** rather than `200 {"success": true}` — a deletion that leaves the account's session token valid is not a deletion, and the push tokens go first so a failure there leaves the caller a credential to retry with. Apple token revocation is the one step that does not fail the request when it is skipped: it runs only where `auth.apple.{team_id,key_id,private_key_p8}` are configured, the local deletion genuinely did complete without it, and which of the two a deployment is doing is logged for the operator rather than announced in the response.

### `POST /auth/nonce`

Request a sign-in nonce for a wallet address.

```json
{ "address": "0xabc..." }
```

Response:
```json
{ "nonce": "Sign in to The Matrix: 3f7c…", "expires_at": 1712668800 }
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

## Capability registry

The gateway exposes a data-driven capability surface backed by
`runtime/capabilities/catalog.py` — the canonical inventory of 195
capabilities across 20 categories, served by 43 underlying services. The
catalog declares a twenty-first category, Security & Wallets, that holds
none; `GET /api/v1/capabilities/categories` lists it with a count of 0.
Every capability has an `id`, `category`, `service`, `method`, and
`params_schema`; see `docs/COMPLETE_CAPABILITY_MAP.md` for the full
catalog.

### `GET /api/v1/capabilities`

List capabilities. All filters are optional query parameters.

| Param       | Type   | Description                                                    |
|-------------|--------|----------------------------------------------------------------|
| `category`  | string | Restrict to a category id (e.g. `defi`, `staking`)             |
| `min_tier`  | string | `free`, `pro`, or `enterprise`                                 |
| `available` | `1`/`0`| When `1`, only capabilities with deployed backends are returned |

**Response `200`**

```json
{
  "capabilities": [
    {
      "id": "swap_tokens",
      "name": "Swap Tokens",
      "category": "defi",
      "service": "dex",
      "method": "swap",
      "min_tier": "free",
      "uses_paymaster": true,
      "available": true,
      "params_schema": { "type": "object", "properties": {} }
    }
  ],
  "count": 1
}
```

### `GET /api/v1/capabilities/categories`

Return the 21 declared categories with per-category capability counts (Security & Wallets has 0).

```json
{
  "categories": [
    { "id": "defi", "name": "DeFi", "icon": "chart.line.uptrend.xyaxis", "count": 10 },
    { "id": "staking", "name": "Staking & Restake", "icon": "lock.square.stack", "count": 11 }
  ]
}
```

### `GET /api/v1/capabilities/{id}`

Full descriptor for a single capability. Returns `404 not_found` for
unknown ids.

### `POST /api/v1/capabilities/{id}/invoke`

Execute a capability. `params` must be an object (**400** otherwise). Before
the call, `params` is bound against the target service method's signature —
not against the capability's published `params_schema`, which many
capabilities do not yet match — and arguments that do not bind answer **400**
with `code: "validation"`. Any other failure the dispatcher reports carries its
status (`not_found` 404, `not_implemented` 501, `service_unavailable` 503,
`service_error` 502); where the underlying message is internal (a binding
message, a service's exception text) the body is the redacted
`{error, code, ref}` shape instead. `POST /bridge/v1/action` relays the
dispatcher the same way.

A refusal the service RETURNS — `not_deployed` above all — is not one of those
statuses, and this route answered `200 {"status": "ok"}` over it while the
dedicated `/api/v1` route for the same service answered `503`. The envelope
states `call_outcome` beside its own `status` now, and a refusal that means the
capability is absent carries the same HTTP status it carries everywhere else:
`status` is this route saying the id resolved and the dispatcher ran,
`call_outcome` is what the dispatcher answered.

```json
{ "params": { "token_in": "USDC", "token_out": "WETH", "amount": "1000" } }
```

`uses_paymaster: true` marks a capability the platform signs, so it is
eligible for gas sponsorship; the flag is static and does not say whether this
deployment sponsors. Gas is paid by the platform only when an operator
configures the paymaster, and then within the sponsorship policy: with a daily
cap set, an operation past the cap, not on the action allowlist, or not
attributable to a signed-in identity is refused rather than charged. See **Gas**
in `docs/blockchain.md`; the dashboard, payments and cross-border tools return
this deployment's policy as `gas_policy`.

---

## MTRX bridge endpoints (`/bridge/v1/`)

These endpoints power the MTRX iOS app. They share the same auth and
rate limiting as the public surface but return iOS-friendly envelopes.

| Method | Path                                    | Description                                             |
|--------|-----------------------------------------|---------------------------------------------------------|
| `POST` | `/bridge/v1/session/create`             | Create a new mobile session                             |
| `POST` | `/bridge/v1/session/resume`             | Resume an existing session by token                     |
| `POST` | `/bridge/v1/chat`                       | Chat with an agent (same semantics as `/chat`)          |
| `POST` | `/bridge/v1/action`                     | Execute a named action (e.g. `convert_contract`)        |
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

## Service envelope

Every `/api/v1/*` route that calls a service answers with the same two-part
envelope, and the two parts answer different questions:

```json
{
  "status": "ok",
  "call_outcome": "success",
  "data": { "...the service's own result..." }
}
```

`status` is about the **wrapping** — the gateway resolved the service, called
it, and has its answer. `call_outcome` is about the **action**, read from the
payload's own named fields: `success`, `failure`, or `unknown` when the service
reported something that does not decide the question (`pending` means "not
paid" in one service and "record written" in another, so neither reading is
correct for both). `call_outcome` is present on every response, not only on
refusals — a field that appears only when something went wrong reads as silence
everywhere else.

The name is namespaced because `outcome` is a word the **services** own: a
prediction market has a resolved outcome, so do a dispute and a governance
proposal, and `gaming.resolve_market` writes the caller's own argument into the
record it returns. While the envelope used the bare word, resolving a market
*to* `"failure"` was read as the CALL having failed — for an action the same
response attested as real.

Of the 101 `/api/v1` routes, 14 answer with something else, and each of them
answers with its own status rather than dressing a refusal as a success:

* **The gateway's own answers**, which are not a service result to wrap —
  `GET /api/v1/price/eth-usd` (the price, `503` when no source is reachable),
  `POST /api/v1/paymaster/sign` (`{paymasterAndData}`),
  `POST /api/v1/security/preflight` (`{allow, mode}`, or `403` for a denial),
  `POST /api/v1/batch` (each item carries the sub-response's own status, body
  and `call_outcome`, so an item inherits the `503` its route would have
  answered *and* the verdict a domain refusal's deliberate `200` would
  otherwise have hidden — `unknown` for an item that timed out, which was
  cancelled mid-flight and may have acted. The completion event counts
  `success_count` and `refused_count` from those verdicts, and
  `abort_on_failure` stops on anything that is not a success) and
  `GET /api/v1/events/stream` (SSE).
* **`POST /api/v1/capabilities/{id}/invoke`**, which relays the dispatcher
  under `{status, call_outcome, capability_id, action, result}`. The
  `call_outcome` rule holds there exactly as it does here, including the `503`.
* **Eight routes that are not implemented and say so** — `501` with
  `status: "not_implemented"`, what the platform does not do, and where to go
  instead: `/api/v1/contracts/deploy`, `/api/v1/portfolio/history/{wallet}`,
  `/api/v1/intent/summary/{plan_id}`, `/api/v1/intent/execute`,
  `/api/v1/compute/arweave/store`, `/api/v1/governance/multisig/approve`,
  `/api/v1/social/gate/create`, `/api/v1/social/message/send`.

A refusal that is a **domain answer** the caller asked for — a rejected claim,
a failed transaction — stays `200` with `status: "ok"` and
`call_outcome: "failure"`.
A refusal that means the platform **could not act at all** —
`not_deployed`, `not_configured`, `not_available`, `unavailable` → `503`;
`not_implemented`, `unsupported`, `provider_unsupported` → `501` — carries its
own status word and a real HTTP failure, because a client that checks only the
HTTP status (the Python SDK does exactly that) would otherwise read it as a
success. The bridge's `/bridge/v1/*` envelope makes the same split with
`ok` and `call_outcome`, and answers `ok: false, refused: true` for a refusal the
platform relayed.

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
| `GET`  | `/audit`                 | Glasswing audit: the 12 checks and the report they return (ordering is not live) |
| `GET`  | `/marketplace`           | Developer plugin marketplace         |
| `GET`  | `/services/conversion`   | Contract conversion: what the pipeline returns (ordering is not live) |

---

## In-app purchase endpoints

Subscriptions are sold in the MTRX iOS app through Apple In-App Purchase. The
gateway has no checkout, card-payment or subscription-status endpoint; it
verifies what the App Store signed.

### `POST /api/v1/iap/verify`

Verify a StoreKit `signedTransaction` JWS (the certificate chain to the pinned
Apple root, and the bundle id) and record it. A subscription records an
entitlement row; a consumable is recorded in the transaction ledger but never
grants a tier. Replaying the same transaction returns `200` with `replay: true`
and records nothing new.

```json
{ "signedTransaction": "eyJhbGciOi..." }
```

`400` missing or invalid body · `401` the transaction did not verify · `503` IAP
is not configured on this gateway.

### `POST /api/v1/iap/asn`

App Store Server Notifications V2 receiver. Called by Apple's servers, not by a
client; authenticated by the Apple-signed JWS chain.

---

## Audit service endpoints

**Not available.** Both routes are registered, but the gateway has no audit
service wired to them (`GatewayServer.audit_service` is never assigned), so
each answers `503` with `{"status": "not_available"}` whatever the request
carries. Nothing takes an audit order or a payment, and no report is produced.
Both routes also sit behind the API key on a gateway that sets one.

A contract's Glasswing scan does run in two places that work: on a contract
tool call that carries source code (`ProtocolStack.pre_action`, which refuses a
deployment that fails it) and on `POST /badge/issue`, which audits the source
itself before issuing a badge.

### `POST /audit/request`

Answers `503 not_available`. The handler would read `source_code`,
`contract_name`, `email` and `tier` from the body if an audit service existed.

### `GET /audit/{audit_id}`

Answers `503 not_available`.

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

### `POST /marketplace/plugins/{plugin_id}/purchase`

Answer a purchase request for a plugin. It installs nothing. No body: the plugin
comes from the path. The route needs the operator's key: it is not one a wallet
session reaches (`gateway/session_routes.py`), so a session is answered `403`.
The buyer is the `X-Wallet-Address` header the operator sends, and `anonymous`
without one. A free listing returns `200` with
`status: "already_purchased"` and `installed: false`: free listings count as
owned by every caller, and nothing is recorded. Nothing in the gateway loads a
plugin either: `runtime/plugins/loader.py` can import a package from
`plugins/installed/`, and no code in the gateway calls it. A paid plugin returns
`501` with `status: "not_built"` — paid purchases have no completion path — and
reports `platform_commission_rate` from `plugin_marketplace.commission_rate`
(`null` when unset). An unknown `plugin_id` returns `404`.

### `POST /marketplace/plugins/submit`

Submit a new plugin listing. Requires the API key; no subscription tier is
checked. The listing is stored with `status: "pending"` and is not returned by
`GET /marketplace/plugins` (which lists `active` listings held in memory).
Nothing in this gateway approves or activates a listing, and stored listing rows
are not read back after a restart. `author` is taken from the body as given
(default `"anonymous"`); it is not verified against the caller. Paid sales are
not built, so a `price_usd` above zero produces a listing that cannot be bought
(see purchase above).

```json
{
  "name": "My Plugin",
  "description": "Does something useful",
  "author": "0xYourWallet",
  "category": "defi",
  "repository_url": "https://github.com/..."
}
```

Response: `{"status": "submitted", "plugin_id": "...", "message": "..."}`.

### `GET /marketplace/purchased`

List the plugins the caller owns (same identity rule as purchase): every free
listing, plus any recorded purchase — and nothing records one today.

---

## A2A commerce endpoints

### `GET /a2a/services`

List all registered agent-to-agent services. Optional query: `?category=...`.

### `POST /a2a/jobs`

Record a job for an agent service. Returns the job record with `201` and
`status: "pending"`. Nothing in the gateway runs it: the coordinator that would
complete a job is not constructed, so the job stays `pending`.

```json
{
  "service_id": "svc_abc123",
  "requester": "user",
  "provider": "agent_xyz",
  "input": {},
  "max_price_usd": 0
}
```

### `GET /a2a/jobs/{job_id}`

Get a job's record. `404` if the job does not exist.

---

## Extensions registry

### `GET /extensions/registry`

List all registered platform extensions.

### `GET /extensions/registry/{component_id}`

Get one registered component. `404` when the id is not in the registry.

---

## Social media endpoints

### `POST /social/post`

Post to the configured social media platforms. Returns
`{"status": "not_configured"}` when none is configured.

```json
{
  "content": "New feature launched!",
  "platform": "all"
}
```

---

## SDK

For programmatic access, use the Python SDK:

```python
from sdk import MatrixClient

client = MatrixClient("http://localhost:18790", api_key="sk-...")
response = client.chat("Deploy a smart contract for me")
print(response.text)
```

Or the JavaScript SDK:

```typescript
import { MatrixClient } from '@the-matrix/sdk';

const client = new MatrixClient('http://localhost:18790', { apiKey: 'sk-...' });
const response = await client.chat('Deploy a smart contract for me');
console.log(response.text);
```

See `sdk/README.md` for full SDK documentation.
