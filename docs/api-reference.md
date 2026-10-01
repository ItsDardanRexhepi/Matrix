# API Reference

The Matrix gateway is an `aiohttp` server that exposes a public REST
surface, a WebSocket stream, a `/bridge/v1/` API for the MTRX iOS app,
and Prometheus metrics.

All JSON requests and responses are UTF-8. A response a handler returns
carries an `X-Request-Id` header that matches the `request_id` field in the
structured JSON logs — quote it when filing issues — unless the response is
streamed. Two kinds of answer go out without it:

* **A streamed response**, whose headers are sent before the handler
  finishes: `POST /chat/stream`, `GET /social/feed/stream`,
  `GET /api/v1/events/stream` and the `GET /ws` upgrade.
* **An answer raised as an exception.** On `/api/v1` that includes a `400` a
  service route raises for a missing field or bad JSON
  (`Missing required fields: …`, `Invalid JSON body`), a `403`, `404` or `501`
  a service route raises, a redacted error raised with its `ref` (quote the
  `ref` instead), the `500` of an exception no handler caught, and the
  router's own unmatched-path `404` and wrong-method `405`.

The sign-in and purchase routes (`POST /api/v1/auth/apple`,
`POST /api/v1/iap/verify`, `POST /api/v1/iap/asn`) return their `400`s
rather than raising them, so those carry the header.

---

## Middleware

Every request passes through this chain (outer → inner):

1. `request_id` — takes the caller's `X-Request-ID` or generates one,
   returns it on a response the handler returns (see the top of this page
   for the answers that go out without it), and publishes it through an async context
   variable so every log line emitted for the request carries the same ID.
2. `cors` — answers preflights and sets `Access-Control-Allow-Origin` only
   for the origins in `gateway.cors_origins` (empty by default, which
   allows no cross-origin caller; `["*"]` allows every origin, and
   `python3 setup.py` writes `["*"]`).
3. `auth` — enforces a credential on protected routes: the operator key as
   `Authorization: Bearer <key>` or `?api_key=<key>`, or a wallet session
   (see [Authentication](#authentication)). No other header carries the key.
4. `security_context` — carries the caller's identity to the security gate
   for `/api/v1/*` POSTs; it makes no decision.
5. `rate_limit` — token-bucket limiter keyed by wallet session
   (`X-Wallet-Session`), then by the operator key, then by client IP.
6. `timeout` — per-request deadline from `gateway.request_timeout_seconds`
   (default 120s). Exceeding it returns `504 Gateway Timeout`. `/ws` is not
   timed out.
7. `logging` — access log line with method, path, status and duration,
   carrying the `request_id`.

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
The events are `start` (`session_id`, `agent`), then `token` events,
each carrying `text`, and a final `done`. The turn runs to its end
first; the answer is then sent in pieces of 80 characters. A turn that
fails sends an `error` event, then `done`.

### `GET /ws`

WebSocket endpoint. The frame limit is set by
`gateway.websocket.max_message_size` (default 1 MiB) and the heartbeat
interval by `gateway.websocket.heartbeat_seconds` (default 30s).

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
| **A wallet session** — the token returned by `POST /auth/verify` (Sign-In with Ethereum) or `POST /api/v1/auth/apple` (Sign in with Apple) | `Authorization: Bearer <token>` or `X-Wallet-Session: <token>` | exactly the routes the iOS app calls: `gateway/session_routes.py`, generated by `scripts/generate_session_routes.py` from the app's own call sites (81 routes at the time of writing). Any other non-public route answers **403** to a session. `/memory/read` and `/memory/write` are deliberately excluded: they read an agent's memory shared by every user. So is `POST /api/v1/stablecoin/transfer`, which takes its sender from the body, and which records nothing (below). |

**A URL on the list is not every operation behind it.** Three session-reachable doors dispatch an operation by name into the same service dispatcher the dedicated `/api/v1` routes call: `POST /api/v1/capabilities/{id}/invoke`, `POST /bridge/v1/action`, and the chat agent's `request_execution` / `platform_action` tools on the public chat surfaces. Each refuses a session, and an anonymous chat caller, any operation whose (service, method) backs a route the session is refused — the same answer the dedicated route gives (`SERVICE_METHODS_OFF_ALLOWLIST` in `gateway/session_routes.py`). The operator key is unaffected.

**A session is refused what would have the platform act on what it names.** The same three doors refuse a session, and chat acting for one, each action a test finds, in the shapes it reads, in which the platform's wallet or a platform credential would sign, pay, publish or authorise while the request names the payee, the account, the asset, the contract the call is sent to, the key, the digest or the content (`REFUSED_TO_A_SESSION` in `runtime/access_policy.py`): among them `claim_compute_reward`, `bridge_token_ccip`, `bridge_stargate`, `borrow_against_nft`, `breed_nft`, `register_keeper_job`, the restaking and payment-channel actions, `mpc_sign`, `publish_mirror_post`, `publish_paragraph_post`, `publish_cast`, `ceramic_stream_create`, `orbit_db_write`, `store_filecoin`, `start_kyc`, `check_aml_risk` and `redstone_request`. So is each action the same test finds in which the platform's server would send, with a platform credential, a request whose address, method, headers, query names or body the request writes: `redstone_request` reads the RedStone gateway with the platform's API key at the data-service path the request names. A read that carries a platform credential and only query values the request writes, to an address the platform fixes, is kept (the weather reading, the cross-chain message tracker). The refusal is decided on the method an action reaches, not on its name: an action whose method hands the call on, inside the services layer, to one of those is refused with it (`HANDS_THE_CALL_TO`: `compute_job_submit`, `decentralized_store` and `ipfs_pin`, privacy's names for the compute job and the Filecoin store), and so is a `platform_action` `service` override onto such a method. `create_lens_profile`, `launch_social_token`, `launch_creator_coin` and `push_subscribe` are kept for a session and must name the address it is bound to, and a session bound to no wallet is refused them (`BOUND_TO_THE_CALLER`); `oracle_request` answers a session a price, a weather reading or randomness only, and refuses any other `oracle_type`, whatever its type (`HELD_FOR_A_SESSION`). `POST /api/v1/stablecoin/transfer` is not a session route, and `transfer_stablecoin` is refused to a session at every dispatcher with it: each takes its sender from the request, and nothing binds that sender to the caller. The route records nothing, for any caller: its handler hands the service's transfer `sender` and `recipient`, which it does not take (it takes `from_addr` and `to_addr`), so a body with the four fields the handler requires and an amount that is a number between -1e308 and 1e308 is answered 400, and one whose amount is null, a list, an object, a string float() cannot read as a number, or an integer of up to 4,300 digits beyond the largest float (about 1.8e308, of either sign) is answered 500; an integer of more digits is refused as not JSON and answered 400. The capability records only on the service's in-memory ledger, which starts empty and which only a test helper funds, so for the operator key it answers that the balance is insufficient. The operator key is unaffected by these refusals: `/bridge/v1/action` and Neo's `platform_action` run each of them for it, and capability invoke runs those the catalog marks available.

Without either, a non-public route answers **401** — whether or not the path exists; an anonymous caller is not told which paths are real. A **401** always means the credential is bad (absent, expired, or never issued): with a live session, a path that matches no route answers **404** and a matched path with another method answers **405** with `Allow`, exactly as they answer the operator — never 401, which the iOS client reads as a bad token and signs the user out. Sessions expire (`gateway.wallet_session_ttl_seconds`, default 24 h); an expired token is no credential anywhere.

**Identity is derived from a session; on the operator path it is asserted, and this says which.** On a request carrying a wallet session the caller's identity is the session's subject, and nothing in the request overrides it — the wallet linked to the Apple user when one exists, else `apple:<sub>` or the SIWE address. As the caller's identity — what the security gate attributes a POST to an `/api/v1/*` route to, the caller the chat entrances hand the dispatcher, the follower on `/social/follow`, the identity `/security/appattest/attest` verifies for — an `X-Wallet-Address` or `X-Apple-Id` header or a `wallet` / `apple_id` body field is consulted only when no session is presented and the request carries the operator key (an operator integration naming the user it acts for; development, where auth is off, counts). Two things are not that: the `identity` a client names on `/security/appattest/challenge` and in the attest body is the binding of a server-issued one-time challenge, not a credential; and some `/api/v1` service routes take a `wallet` parameter the service acts on (for example `/api/v1/defi/swap/execute`), which this gateway does not check against the caller. The chat entrances are public, so this matters most there: an anonymous chat has **no** identity, and the body's `wallet`, `apple_id`, `wallet_connected`, `network`, `balance`, `jurisdiction` and `total_transactions` are read only from an operator's request — they feed the dispatcher's caller identity and the security gates' verdicts, so a caller may not write them about itself. Where no session is presented and the request is the operator's, the value is ASSERTED, not authenticated — the header as the caller wrote it — and the routes that record or check "the caller" (for example `/api/v1/capabilities/{id}/invoke`, `/api/v1/insurance/claim`, `/api/v1/paymaster/sign`) receive that asserted value. A wallet proven by `POST /auth/verify` while holding an Apple session is linked to that Apple user. A wallet address has one spelling wherever the gateway names a caller: `0x` followed by its forty hex digits in lower case (`runtime/auth/identity.py`). The session `/auth/verify` creates, the wallet linked to an Apple user, a session or link stored before this rule, an operator's `X-Wallet-Address` header or `wallet` body field, and the identity handed to the security gate and to a tool all use it, so a wallet that signs in with its address in upper case, in EIP-55 mixed case or with `0X` is the same caller as the one that signed in with it in lower case. Everything else the gateway stored under a wallet before this rule is rewritten in it once, when the gateway first opens its database at schema version 10: conversation claims and turns, an account's own `user:<address>` conversation, its scoped agent memory, its devices, its IAP entitlements, the follow graph and plugin purchases (the sponsorship ledger rewrites its spenders when it is opened). The two shadow logs of schema versions 8 and 9 (`urf_decision_log`, `evidence_shadow`) hold a caller only as a sha256 digest, which the rewrite cannot reach; nothing reads them to decide anything. An account from before the rule therefore keeps its conversations, and deleting it deletes what it stored. Two spellings one wallet signed in under before the rule become one account: a conversation's turns follow each other, the newer of two memory values for the same key stays, and a conversation claimed under the same id by two different accounts is left as it is. A conversation id of the form `user:<address>` is read with its address in the one spelling wherever a caller names one. Anything that is not a hex address (`apple:<sub>`, a label) is left as it is. Where the platform checks that the caller is the party a record names (an insurance policy's `holder`, a listing's seller, an offer's lender or borrower, whoever set an NFT's rights or royalty, and the other owner checks of the `/api/v1` services), a wallet address the record holds in another case names the same party, while two ids that are not addresses and differ only in case stay two callers. The follow graph holds both ends in the one spelling and reads an address asked about in it.

**Conversations belong to whoever started them.** `session_id` on the chat surfaces is the caller's own id, never `"default"`: with a session and no id, the conversation is `user:<subject>`; in production a request with no id and no session answers **400 `session_required`** (development keeps `"default"` for local runs). A conversation with an owner is continued only by that account (**403** otherwise); an ownerless one is claimed by the first signed-in caller. A claim is stored when it is made, before the conversation has any stored turn, and it stays until the account is deleted — also when the turn that made it fails and the conversation never gets a stored turn. A turn is stored — both the conversation and the agent memory it writes — only if the claim it was admitted under still stands when the model answers. Each claim is its own record: deleting the account removes it, and the same account signing in again makes a new one. So a turn still running when its account is deleted is not written back, even if the account has signed in again (or kept another signed-in session) and continued that conversation meanwhile, and it removes nothing the re-created account has stored. The same holds for an anonymous turn that was already running when an account claimed its conversation and was then deleted: deletion leaves the conversation unclaimed again, but not in the state that turn was admitted under, so it is not stored and the next caller naming the id is not shown it. To tell the two states apart, deletion keeps the ids of the erased conversations and when they were erased (no owner, no content) for `conversation_erasure_log_seconds` (default one hour; a value that is not a finite, non-negative number of seconds is ignored with a warning and the default is used), then prunes them on every later account deletion, also one that erases no conversation, and on the gateway's five-minute sweep; an anonymous turn admitted before a deletion and still running after that deletion's entry is pruned is not stored. The account's own `user:<subject>` conversation is erased but its id is not kept: it names the account, and no turn is stored on it without the account's claim. The other kept ids are the ones the client chose. An ownerless (anonymous) conversation has no credential but its id: whoever presents the id continues it, so a client must generate the id unguessably (the iOS app and the web chat page use random UUIDs). An id of the form `user:<subject>` names an account and is refused (**403**) to every caller but that account's session. A `session_id` is taken as one spelling everywhere — surrounding whitespace removed, at most 100 characters — so `"conv-A "` names `conv-A`. The bridge legs keyed by `session_id` follow the same rule: `/bridge/v1/session/resume` and `/bridge/v1/push/register` answer **403** for a conversation another account owns, and a wallet linked with `/bridge/v1/wallet/link` is shown by `/bridge/v1/wallet/status` and `/bridge/v1/dashboard`, and acts in `/bridge/v1/action`, only for the account that linked it. Agent memory and protocol state are scoped to the account, or to the conversation when anonymous — in a namespace of its own (`conv:<session_id>`), so an anonymous `session_id` spelled like an account's subject (a SIWE address, `apple:<sub>`) neither reads nor writes that account's memory. `DELETE /api/v1/auth/account` removes the session it is sent with (another session of the same account, such as one on a second device, stays valid until it expires), the account's conversations, its scoped memory and protocol state, the memory its conversations gathered before it claimed them, and its push tokens: every device registered under one of the account's sessions, and a device with no recorded owner (one stored before tokens carried one) filed under one of the account's conversations. A device registered without a session to a conversation the account never owned is not found. If erasing the account's conversations and memory fails, it erases *none* of them — the conversations, their claims, the account's scoped memory and the memory its conversations gathered before it claimed them all go in one transaction — and the deletion answers **503 `storage failure`** and removes nothing further: the session it was sent with stays valid and its devices stay registered, so the client can retry and the retry deletes all of it, rather than `200` with the data still stored. The gateway drops its own in-process copies of the account's conversations either way, so no later caller naming one of those ids is served the deleted account's history. A request presenting no live session (an expired token, or none) answers **401 `session required`**: there is no account to identify, so nothing is deleted — where this answered `200 {"success": true}` having deleted nothing. The two removals after the erasure answer the same way: if the push tokens cannot be removed, or the session cannot be removed, the deletion answers **503 `storage failure`** rather than `200 {"success": true}` — a deletion that leaves the account's session token valid is not a deletion, and the push tokens go first so a failure there leaves the caller a credential to retry with. Apple token revocation is the one step that does not fail the request when it is skipped: it runs only where `auth.apple.{team_id,key_id,private_key_p8}` are configured, the local deletion genuinely did complete without it, and which of the two a deployment is doing is logged for the operator rather than announced in the response.

### `POST /auth/nonce`

Request a sign-in nonce for a wallet address. The nonce is single-use. The
address may be written in any case, with `0x` or `0X`; a value that is not a
20-byte hex address answers **400**.

```json
{ "address": "0xAbC..." }
```

Response: the nonce, and the EIP-4361 message the wallet signs.
```json
{ "nonce": "3f7c…", "message": "the-matrix.local wants you to sign in with your Ethereum account:\n0xAbC...\n…\nNonce: 3f7c…\nIssued At: …" }
```

### `POST /auth/verify`

Verify the signed message and mint a session.

```json
{ "address": "0xAbC...", "message": "…", "signature": "0x...", "nonce": "3f7c…" }
```

Response: the session token (sent afterwards as `X-Wallet-Session` or
`Authorization: Bearer`), the address in the gateway's one spelling of a
caller (lower case, whatever case was sent), and when the session expires.
```json
{ "token": "…", "address": "0xabc...", "expires_at": 1712755200 }
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

Full descriptor for a single capability. An unknown id answers `404`
`{"ok": false, "error": "unknown_capability", "capability_id": …}`.

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

A capability the catalog marks `"available": false` is not run here: the route
answers **503** `{"status": "unavailable", "error": "unavailable"}` to every
caller it has not already refused, the operator key included, before the
security gate is asked. A capability refused to every caller, or to the caller
asking (a session), answers **403** first.

`POST /bridge/v1/action` reads an `Idempotency-Key` header only while
`engines.durable.mode` is `shadow` or `on`; at `off`, the default, the header
is not read. A key is scoped to its caller (the kind of credential, and the
subject a session was issued to or, for the operator key, the user it names),
in the platform's one spelling of a caller: every spelling of one wallet
address is one caller, and an `apple:` subject or a name is kept as given, so
two that differ only in case are two callers with two scopes. It is read after
the security gate: a replay is gated again like any request. At `shadow`
the key is recorded against the first request that used it and nothing
changes: a replay runs again. At `on`, with the canary at its second stage
(`engines.durable.canary`, both stages by default), a state-modifying action
runs once under a key. A later request with the same key and body runs nothing and gets
the first answer, byte for byte, while the process that gave it still holds it
(up to 24 hours, the latest 4,096 answers); otherwise it answers **422** with
`code` `idempotency_in_progress` (the first has not answered yet),
`idempotency_conflict` (the key was used for another action or other
parameters) or `idempotency_answer_not_held`. A key that is not 1 to 255
printable ASCII characters, with no leading or trailing space, answers
**400** `validation`, and an action whose run cannot be recorded first — or
any action the engine owns when it could not be built — is not run and answers
**503** `service_unavailable`.

A refusal the service RETURNS — `not_deployed` above all — is not one of those
statuses, and this route answered `200 {"status": "ok"}` over it while the
dedicated `/api/v1` route for the same service answered `503`. The envelope
states `call_outcome` beside its own `status` now, and a refusal that means the
capability is absent carries the same HTTP status it carries everywhere else:
`status` is this route saying the id resolved and the dispatcher ran,
`call_outcome` is what the dispatcher answered.

An id that names no capability never reaches the dispatcher: this route
answers it `400`
`{"status": "error", "error": "unknown_capability", "capability_id": …}`,
where `GET /api/v1/capabilities/{id}` answers the same id `404` with
`"ok": false` in place of `"status": "error"`. A session can be refused `403`
first, for an id the session's refusal tables name.

```json
{ "params": { "token_in": "USDC", "token_out": "WETH", "amount": "1000" } }
```

`uses_paymaster: true` marks a capability the platform signs, so it is
eligible for gas sponsorship; the flag is static and does not say whether this
deployment sponsors. Gas is paid by the platform only when an operator
configures the paymaster, and then within the sponsorship policy: an operation
not on the action allowlist, when one is set, is refused with or without a
daily cap, and with a daily cap set, an operation past the cap or not
attributable to a signed-in identity is refused too, rather than charged. See **Gas**
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

Of the 148 `/api/v1` routes, 74 answer with something else at this commit —
the handler does not write the envelope, or the service call it makes can
never succeed — and each of them answers with its own status rather than
dressing a refusal as a success:

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
  `GET /api/v1/events/stream` (SSE). `GET /api/v1/oracle/price/{pair}` gives
  the same bare price when the pair is `eth-usd` (in any case, with `-` or
  `_`, or as `ethusd`), but it is not counted here: any other pair goes to
  the service, and a price the service returns is written inside the
  envelope (a pair the service does not support answers `400`, and an
  unreachable price backend `503 {"error": "price unavailable"}`).
* **`POST /api/v1/capabilities/{id}/invoke`**, which relays the dispatcher
  under `{status, call_outcome, capability_id, action, result}`. The
  `call_outcome` rule holds there exactly as it does here, including the `503`.
* **Sign-in and purchase** — `POST /api/v1/auth/apple`,
  `DELETE /api/v1/auth/account`, `POST /api/v1/iap/verify` and
  `POST /api/v1/iap/asn`, each answering in a shape of its own.
  `DELETE /api/v1/auth/account` and its answers are described under
  [Authentication](#authentication), where `POST /api/v1/auth/apple` is named
  as a route that returns a session token; the two `iap` routes have sections
  under In-app purchase endpoints below.
* **Forty-six routes that are not implemented and say so** — `501` with a
  not-implemented error. Nine carry detail of their own, saying what the
  platform does not do. Four of them also name the route to use instead:
  `/api/v1/contracts/deploy`, `/api/v1/portfolio/history/{wallet}`,
  `/api/v1/intent/summary/{plan_id}` and `/api/v1/intent/execute`. Four more
  are `/api/v1/compute/arweave/store`, `/api/v1/governance/multisig/approve`,
  `/api/v1/social/gate/create` and `/api/v1/social/message/send` — the last
  three validate their input first, so a missing-fields body answers `400`
  and a valid one the `501`. `POST /api/v1/governance/snapshot/vote` does the
  same: `400` on missing fields, then `501` saying Snapshot voting is
  unavailable, or, when the body names a `space`, that Snapshot spaces are
  not implemented. The remaining 37
  are the client-skeleton legs — storage, messaging, groups, licensing,
  events, indexer, oracle feeds and compute (jobs and providers), plus
  `/api/v1/portfolio/performance/{wallet}` — each an honest `501` until its
  service lands. `/api/v1/privacy/delete` answers `501` too, inside the
  standard envelope (`call_outcome: "failure"`, `error_category:
  "not_implemented"`), so it is not among these.
* **Eighteen routes whose service call can never succeed at this commit.**
  Seven call a method their service does not have and answer `404`
  `{"error": "Method '…' not found on '…'"}`: `GET /api/v1/rwa/listings`,
  `POST /api/v1/defi/swap/route`, `POST /api/v1/defi/swap/execute`,
  `POST /api/v1/defi/bridge/quote`, `POST /api/v1/defi/bridge/execute`,
  `POST /api/v1/identity/zk-proof/generate` and `POST /api/v1/social/post`.
  Eleven pass the service method an argument it does not take and answer a
  redacted `400` with `code: "invalid_request"`, or the plain `500` of an
  exception no handler caught when the handler fails first on a value it
  converts to a number: `/api/v1/agent/register`,
  `/api/v1/fundraising/campaign/create`, `/api/v1/governance/proposal/create`,
  `/api/v1/insurance/policy/create`, `/api/v1/ip/register`,
  `/api/v1/nft/mint`, `/api/v1/rwa/tokenize`, `/api/v1/securities/create`,
  `/api/v1/stablecoin/transfer`, `/api/v1/staking/stake` and
  `/api/v1/staking/unstake` (all `POST`).

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

There is no single error shape. The table lists the error answers measured at
this commit; it is not exhaustive, and the service envelope and the invoke
route above carry statuses of their own. The `X-Request-Id` header is on some
of these answers and not others (see the top of this page), and no error body
carries the correlation id as a top-level `request_id` field. A redacted error
carries it as `ref`, both as its own field and at the end of the `error` text
— quote it when filing issues:

```json
{
  "error": "That request could not be completed. (ref: …)",
  "code": "internal_error",
  "ref": "…"
}
```

| HTTP | Body | When |
|------|------|------|
| 400  | `{"error": "<what is wrong>"}`, e.g. `Invalid JSON body`, `Missing required fields: …` or `message is required` | Bad JSON, missing required field |
| 400  | redacted, `code: "invalid_request"` | A service refused the request as malformed, or the gateway passed the service method an argument it does not take — how the eleven routes named above answer every request their handler accepts |
| 400  | redacted, `code: "validation"` | The invoke route relaying a dispatcher validation refusal |
| 401  | `{"error": "unauthorized", "message": …}` | Missing or invalid API key / session token |
| 401  | `{"success": false, "error": "session required"}` | `DELETE /api/v1/auth/account` without a session |
| 403  | `{"error": "forbidden", "message": …}` | A session asking for a route or capability that requires the operator key, or another access-policy refusal |
| 403  | `{"error": "This action couldn't be authorized right now. Please try again."}` | The security gate refusing the action (only with the security package installed); raised on the service routes, so without `X-Request-Id` there. `POST /api/v1/capabilities/{id}/invoke` and `POST /bridge/v1/action` return the same refusal with the header (the bridge adds `ok` and `timestamp`) |
| 403  | `{"error": "<service> is disabled", "detail": …}` | A regulated service that ships disabled |
| 404  | plain text `404: Not Found` | Unmatched path (the router's own answer) |
| 404  | `{"error": "<the dispatcher's sentence>", "code": "not_found"}`, no `ref` | An action the dispatcher does not know (`POST /bridge/v1/action` adds `ok` and `timestamp`) |
| 404  | a route's own `{"error": …}`, e.g. `Method '…' not found on '…'` | Unknown resource; a service method that does not exist is raised, so without `X-Request-Id` |
| 405  | plain text `405: Method Not Allowed` | Wrong method for a served path |
| 422  | the service envelope, `call_outcome: "failure"` | A well-formed request the operation could not complete |
| 429  | `{"error": "rate_limited", "message": "Too many requests. Please slow down."}` | Token bucket exhausted for wallet / key / IP |
| 500  | redacted, `code: "internal_error"` | Server error a handler caught — quote `ref` |
| 500  | aiohttp's own `500 Internal Server Error` page (plain text, or HTML for a client that accepts `text/html`) | An exception no handler caught; no id is returned |
| 501  | `{"error": …, "status": "not_implemented"}` or a route's own detail | Not implemented (see above) |
| 502  | redacted, `code: "service_error"` | The invoke route relaying a service error |
| 503  | the service envelope with the refusal's own `status` (e.g. `not_deployed`); on invoke, `{"status": "ok", "call_outcome": "failure", …}` for a refusal the dispatcher relays, or `{"status": "unavailable", "error": "unavailable", …}` for a capability the catalog marks unavailable | The capability is absent (see above) |
| 503  | `{"error": "<feature> not configured"}` | `POST /api/v1/paymaster/sign`, `POST /api/v1/auth/apple` or `POST /api/v1/iap/verify` on a gateway without that configuration |
| 503 / 504 | redacted, `code: "upstream_unavailable"` / `"upstream_timeout"` | A service the request depends on is unreachable or slow |
| 503  | `{"status": "unavailable", "error": "<sentence>"}`, raised: no `ref`, no `X-Request-Id` | `GET /api/v1/portfolio/complete/{wallet}` or `GET /api/v1/portfolio/positions/{wallet}` when reading the wallet's portfolio fails after its address was accepted |
| 504  | `{"error": "request_timeout", "message": "Request exceeded Ns budget."}` | Request exceeded `request_timeout_seconds` |

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
session reaches (`gateway/session_routes.py`), so a session alone is answered
`403`. The buyer is the address of a wallet session the operator's request also
carries in `X-Wallet-Session`, when it carries one; otherwise the
`X-Wallet-Address` header the operator sends, and `anonymous` without either.
With no key set (development) every request counts as the operator's, by the
same rule. A free listing returns `200` with
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

client = MatrixClient("http://localhost:18790")
response = client.chat("What can you help me with?")
print(response.text)
```

Pass the gateway's operator key as `MatrixClient(url, api_key=...)` to reach
the key-gated routes and to name Neo or Morpheus; without it the client
reaches the public routes, `/chat` (as Trinity) among them. The SDK is the
`sdk` package in this repository and is not published to PyPI.

Or the JavaScript SDK:

```typescript
import { MatrixClient } from '@the-matrix/sdk';

const client = new MatrixClient('http://localhost:18790', { apiKey: 'YOUR_GATEWAY_KEY' });
const response = await client.chat('What can you help me with?');
console.log(response.response);
```

`sdk-js/` is not published to npm; `sdk-js/README.md` says how to build and
install it from your clone. See `sdk/README.md` for the Python SDK.
