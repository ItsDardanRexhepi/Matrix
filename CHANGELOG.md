# Changelog

All notable changes to 0pnMatrx are documented here.

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
- Claude Mythos Preview added as model provider (Glasswing frontier model)
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
