# Operator kit

All operator checks run from one entrypoint, `scripts/ops.sh`. The check
subcommands are **strictly read-only** — they never sign, spend gas, send a
push, or mutate state.

## Preflight (run before every deploy)

```bash
./scripts/ops.sh preflight
```

Runs, and fails on the first problem:
1. **`gateway.doctor`** — per-subsystem posture: `READY` (checked and working)
   / `CONFIGURED` (settings present, nothing dialled or signed) /
   `UNCONFIGURED` no-op / `HALF-CONFIGURED` (the honest failure to fix before
   go-live) / `STUB` (degraded). It exits non-zero on `HALF-CONFIGURED`, and
   on a `STUB` that is not a deliberate posture: `morpheus_security` present
   on disk but not the live backend, or no enforcement at all under
   `MATRIX_ENV=production`. A checkout without the private security package
   and not in production is the deliberate no-op, and still exits 0.
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
| `ops.sh routes-check` | Fail if `ROUTES.md` is stale | none |
| `ops.sh abis` | ABI doc/source drift audit | none |
| `ops.sh health [URL]` | `curl` the gateway `/health` | none |
