# Operator kit

All operator checks run from one entrypoint, `scripts/ops.sh`. The check
subcommands are **strictly read-only** — they never sign, spend gas, send a
push, or mutate state.

## Preflight (run before every deploy)

```bash
./scripts/ops.sh preflight
```

Runs, and fails on the first problem:
1. **`gateway.doctor`** — per-subsystem posture: `READY` / `UNCONFIGURED`
   no-op / `HALF-CONFIGURED` (the honest failure to fix before go-live).
2. **route-table freshness** — `docs/ROUTES.md` must match the generator
   (`scripts/generate_route_table.py`); CI enforces the same via `--check`.
3. **ABI verification audit** — `scripts/verify_abis.py --strict`: no drift
   between the `UNVERIFIED` flags in service source and
   `ABI_VERIFICATION_NEEDED.md`.

## Individual commands

| Command | What it does | Side effects |
|---|---|---|
| `ops.sh doctor` | Gateway posture diagnostic | none (read-only) |
| `ops.sh routes` | Regenerate `docs/ROUTES.md` | writes the doc only |
| `ops.sh routes-check` | Fail if `ROUTES.md` is stale | none |
| `ops.sh abis` | ABI doc/source drift audit | none |
| `ops.sh health [URL]` | `curl` the gateway `/health` | none |

### If you turn on GitHub Pages

The `API Docs` workflow builds the API reference with pdoc and then tries to
publish it to GitHub Pages. **Pages is disabled for this repository**, so the
deploy step returns 404. It no longer fails the workflow — publication is not a
test, and the `build` job is what gates the documentation.

**The caveat, where you will need it:** the deploy job carries
`continue-on-error: true`. The moment you enable Pages (Settings → Pages →
Source: GitHub Actions), that tolerance applies to *real* publication failures
too — a broken deploy will leave the run green and only its own step log will
say the site did not update. **Remove `continue-on-error` from the deploy job in
`.github/workflows/docs.yml` when you enable Pages**, so a failed publish is
visible in the run's status again.

## Deploy (side-effectful, run deliberately)

This repository ships its own production stack: `docker-compose.yml`, with
`docker-compose.prod.yml` layered on top for Caddy TLS termination, and a
Kubernetes stack in `k8s/` (README → Production Deployment).

Both run the gateway with `MATRIX_ENV=production` (`docker-compose.prod.yml` and
`k8s/deployment.yaml` set it, `docker-compose.yml` defaults to it), and a
production gateway refuses to start on the no-op security backend, naming the
cause. The `Dockerfile` installs only the public requirements, so the commands
below bring up a gateway only from an image that also carries the separately
installed security core (`CREDENTIALS_NEEDED.md`, section 5). For a testnet run
without the core, start `docker-compose.yml` alone with a non-production
`MATRIX_ENV` and put your own TLS in front of it.

```bash
export MATRIX_DOMAIN=gateway.example.com
export MATRIX_ADMIN_EMAIL=ops@example.com
docker compose -f docker-compose.yml -f docker-compose.prod.yml up -d
docker compose -f docker-compose.yml -f docker-compose.prod.yml logs -f gateway
```

The APNs `.p8` arrives as a mounted file, never an env value: point
`APNS_AUTH_KEY_P8_PATH` at it and the gateway reads its contents into the push
channel at startup. Push stays an honest no-op if the file is absent or
unreadable.

Never commit the real `.env`, `secrets/`, or `matrix.config.json` — `.gitignore`
excludes them, and only the `.example` files are tracked.
