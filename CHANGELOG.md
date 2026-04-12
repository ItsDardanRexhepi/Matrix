# Changelog

All notable changes to 0pnMatrx are documented here.

---

## [0.5.0] — 2026-04-09

### Production hardening — round 3 (mainnet-ready)

#### Secrets & configuration

- New `runtime/config/validation.py` enforces env-only loading for
  every secret listed in `SECRET_PATHS`. Placeholder values
  (`YOUR_…`, `CHANGE_ME`, `REPLACE_…`, `xxx-…`) are treated as
  unset.
- Strict mode (`OPNMATRX_ENV=production`) refuses to start the
  gateway if a required secret is missing from the environment —
  no more silent fallback to committed placeholders.
- `ValidationReport` returns structured missing/warnings lists so CI
  can diff them.

#### Observability

- New `runtime/logging/` package with `JsonFormatter`,
  `RequestIdFilter`, and a `configure_logging()` bootstrap. Every
  log line is single-line JSON with `timestamp`, `level`, `logger`,
  `message`, `request_id`, and arbitrary `extra` fields.
- Per-request `request_id` propagated through an async
  `contextvars.ContextVar`, generated (or accepted via
  `X-Request-Id`) by a new middleware in `gateway/server.py`. The
  request ID is returned to the client and stamped on every log
  line for the request.
- New `runtime/monitoring/otel.py` soft-failing OTLP push exporter
  that bridges the internal `MetricsCollector` into OpenTelemetry
  when the SDK is installed. Controlled by
  `monitoring.otel.{enabled,endpoint,headers,interval_seconds}` or
  `OTEL_EXPORTER_OTLP_ENDPOINT`.

#### Gateway hardening

- Per-authenticated-wallet rate limiter (three-tier: wallet → API
  key → IP) replaces the single-shape bucket. Fixed a bug where
  `wallet_session` was checked against the wrong field (`expired`
  instead of `expires_at`).
- New `timeout` middleware enforces
  `gateway.request_timeout_seconds` (default 30s) and returns
  `504 Gateway Timeout` for deadline overruns.
- WebSocket frame limit (`gateway.ws_max_message_size`, default
  1 MiB) and heartbeat interval (`gateway.ws_heartbeat_seconds`,
  default 30s) are now pulled from config instead of hard-coded.

#### Deployment

- `docker-compose.prod.yml` composes a Caddy sidecar on top of the
  base `docker-compose.yml`. Gateway port is reset to
  `expose`-only; Caddy handles TLS.
- `Caddyfile` — auto-HTTPS via Let's Encrypt, HSTS, X-Frame-Options,
  WebSocket-aware upstream, JSON access logs.
- `k8s/` directory with namespace, configmap, secret template,
  PVC, deployment (securityContext, readOnlyRootFilesystem,
  liveness/readiness/startup probes), service, ingress, and
  README.

#### Solidity contracts

- `foundry.toml` pins solc 0.8.20, sets `evm_version = shanghai`,
  enables the optimizer, and wires gas reports for all nine
  production contracts.
- `remappings.txt` maps `forge-std/` to `contracts/lib/forge-std/`.
- `scripts/build-contracts.sh` is a one-shot wrapper: installs
  forge-std + OpenZeppelin (pinned), builds, then runs the full
  test suite. `--no-test` and `--clean` flags supported.
- New `contracts/test/` directory with nine Foundry test files
  covering every production contract:
  - `OpenMatrixPaymaster.t.sol` (14 tests — agent auth, sponsorGas,
    withdraw, ownership)
  - `OpenMatrixAttestation.t.sol` (10 tests including a fuzz run)
  - `OpenMatrixStaking.t.sol` (9 tests — stake / unstake / claim /
    fees)
  - `OpenMatrixDAO.t.sol` (6 tests — deposit, propose, voting power)
  - `OpenMatrixDID.t.sol` (8 tests — create, resolve, update,
    addService)
  - `OpenMatrixInsurance.t.sol` (7 tests — premium tiers, purchase,
    expire)
  - `OpenMatrixNFT.t.sol` (9 tests — constructor, mint, royalty)
  - `OpenMatrixDEX.t.sol` (5 tests — createPool, swap)
  - `OpenMatrixMarketplace.t.sol` (5 tests — listItem, approval,
    ownership)
  - `mocks/MockERC20.sol` helper

#### Tests

- New: `tests/test_config_validation.py` (36 tests) covering
  production detection, placeholder detection, env-only enforcement
  in strict and lenient modes, required-secret errors,
  `validate_config`, and `ValidationReport`.
- New: `tests/test_logging_json.py` (20 tests) covering request-ID
  contextvars, async task isolation, `JsonFormatter` field emission,
  exception capture, non-serializable fallback, and
  `configure_logging()`.
- New: `tests/test_sentry_init.py` (8 tests) covering Sentry DSN
  detection, placeholder stripping, env-var precedence, missing-SDK
  fallback, and init-exception handling.
- New: `tests/test_otel_bridge.py` (12 tests) covering
  `_parse_headers`, disabled-by-default, missing-endpoint handling,
  non-dict config, shutdown-before-start, and env-var override.
- Extended: `tests/test_gateway.py` and `tests/test_websocket.py`
  fixtures now seed `rate_limiter_wallet`, `request_timeout`,
  `ws_max_message_size`, `ws_heartbeat_seconds`, and `otel_bridge`.

#### Repo hygiene

- `pytest.ini` removed — `[tool.pytest.ini_options]` in
  `pyproject.toml` is now the single source of truth.
- `docs/api-reference.md` rewritten to cover the full HTTP +
  WebSocket + `/bridge/v1/` surface, middleware chain, and error
  envelope.
- README updated with a "Production Deployment" section pointing at
  the new Caddy / k8s / Foundry plumbing, and the blockchain
  capability count corrected to match the 30 services exposed by
  `ServiceDispatcher`.

---

## [0.4.0] — 2026-04-09

### Production hardening — round 2

#### Database

- Versioned schema migrations replace the flat `SCHEMA` list. Each
  migration runs inside `BEGIN IMMEDIATE` and is recorded in a new
  `schema_version` table; partial failures roll back atomically.
- `Database.restore_from()` closes the live connection, atomically
  swaps the database file, reopens it, and re-runs migrations to bring
  the snapshot up to the current version.
- `BackupManager.restore_latest()` and `restore_from()` higher-level
  helpers; full restore procedure documented in `docs/RUNBOOK.md`.

#### Observability

- New `GET /metrics/prom` endpoint exposes counters, gauges, and
  histograms in Prometheus text exposition format (counters as
  `_total`, histograms as summaries with 0.5 / 0.95 / 0.99 quantiles).
- Service / oracle cache prune is now wired into the gateway cleanup
  loop via a duck-typed `prune_caches()` chain
  (`ToolDispatcher → ServiceDispatcher → ServiceRegistry →
  OracleGateway`). Evictions are reported via `caches.evicted`.
- `MatrixBridge` now performs real on-chain balance lookups via a
  lazily constructed `Web3Manager`, falling back gracefully when the
  chain is not configured.

#### Packaging

- `pyproject.toml` is now the source of truth for metadata, build
  config, optional dependency groups, and tool configuration (pytest,
  coverage, mypy, interrogate).
- `requirements.txt` is now runtime-only with `~=` ("compatible
  release") pins. Development tooling moved to `requirements-dev.txt`,
  optional Sentry monitoring extras to `requirements-monitoring.txt`
  and the `[opnmatrx[monitoring]]` extra.

#### CI / repo hygiene

- New CI jobs: mypy type-check, interrogate docstring coverage,
  pytest-cov coverage reporting, pip-audit dependency audit, and a
  Docker smoke-test job that builds the image and curls `/health`.
- New release workflow (`.github/workflows/release.yml`) cuts a
  GitHub Release when a `v*` tag is pushed, builds sdist + wheel, and
  pulls the matching CHANGELOG section as the release body.
- `.github/CODEOWNERS` and `.github/PULL_REQUEST_TEMPLATE.md` added.
- `docs/RUNBOOK.md` added with the full on-call playbook.

#### Tests

- New: `tests/test_db_migrations.py` (12 tests) covering schema
  versioning, idempotency, additive migrations, and rollback on
  failure.
- New: `tests/test_metrics.py` (14 tests) covering counter / gauge /
  histogram collection plus Prometheus formatting.
- New: `tests/test_websocket.py` (8 tests) covering the previously
  uncovered `handle_websocket` endpoint: happy path, conversation
  persistence, validation errors, and graceful failure when the ReAct
  loop raises.
- Extended: `tests/test_backup.py` and `tests/test_graceful_degradation.py`
  with restore-flow and cache-eviction coverage.

#### Notes

- The MTRX iOS app remains intentionally out of scope for this
  repository — see `ROADMAP.md` for what belongs in the separate
  `MTRX-iOS` repo (Swift code, APNs, TestFlight CI, StoreKit).

---

## [0.3.0] — 2026-04-08

### Managed Agent Orchestration

- Event-driven inter-agent communication via typed EventBus
- 20 event types covering session, agent, task, security, and protocol lifecycle
- Session persistence and resumable sessions via LifecycleManager
- 8 lifecycle hook points: pre/post session start, pre/post tool use, pre/post shutdown, on error, on resume
- Agent activity tracking: message counts, tool calls, error rates per session
- Task delegation now emits TASK_DELEGATED / TASK_COMPLETED / TASK_FAILED events
- Morpheus interventions tracked via MORPHEUS_INTERVENTION events
- Glasswing audit blocks emit AUDIT_BLOCKED events for observability
- Event log persisted to hivemind/events.jsonl for audit trails
- Session state persisted to hivemind/sessions/ for crash recovery
- MTRX iOS app: Glasswing security knowledge in agent conversations
- MTRX iOS app: managed agent architecture awareness in Trinity/Neo/Morpheus responses

---

## [0.2.0] — 2026-04-08

### Glasswing Integration

- Security audit layer: 12 vulnerability checks run on every contract before deployment
- Reentrancy, unchecked calls, tx.origin, selfdestruct, delegatecall, unbounded loops, integer overflow, floating pragma, locked ether, access control, front-running, timestamp dependence
- Audit gate on deploy: critical vulnerabilities block deployment
- Audit report included in every contract conversion response
- Morpheus enforces audit findings — no unsafe contracts reach the chain
- Mythos Preview added as model provider (Glasswing frontier model)
- Security configuration in openmatrix.config.json
- HiveMind security instance type for collective vulnerability reasoning
- Ultron deploy planning now includes mandatory security audit step
- Friday monitors security vulnerability events
- Vision tracks security patterns across user activity
- Omniversal protocol tracks security as an expansion domain

---

## [0.1.0] — 2026-04-01

### Initial Release

- Three-agent architecture: Neo, Trinity, Morpheus
- ReAct reasoning loop with full tool dispatch
- File-backed memory system
- HTTP gateway on configurable port
- 36 skills loaded via skills loader
- HiveMind shared state across all agents
- 20 blockchain capabilities on Base (Ethereum L2)
- Unified Rexhepi Framework governing all agent decisions
- Full SDK for external integrations
- Migration system for upgrading between versions
- Support for Ollama (local), OpenAI, Anthropic, NVIDIA, Gemini
- One-command install and start scripts
- MIT licensed
