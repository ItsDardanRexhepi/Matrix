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
