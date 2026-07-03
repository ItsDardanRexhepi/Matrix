#!/usr/bin/env bash
# ops.sh — 0pnMatrx operator kit.
#
# One entrypoint for the read-only checks an operator runs before and during a
# deploy. Nothing here signs, spends gas, sends a push, or mutates state — the
# side-effectful actions (deploy up/down, backup) are thin wrappers around
# docker compose and are clearly labelled.
#
#   ./scripts/ops.sh preflight     # doctor + routes-fresh + abi-audit (read-only)
#   ./scripts/ops.sh doctor        # gateway posture (read-only)
#   ./scripts/ops.sh routes        # (re)generate docs/ROUTES.md
#   ./scripts/ops.sh routes-check  # fail if docs/ROUTES.md is stale (CI)
#   ./scripts/ops.sh abis          # ABI doc/source drift audit
#   ./scripts/ops.sh health [URL]  # curl the gateway /health (default :18790)
#   ./scripts/ops.sh help
set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$ROOT"
PY="${PYTHON:-python3}"
export PYTHONPATH="${PYTHONPATH:-.}"

_doctor()       { "$PY" -m gateway.doctor "$@"; }
_routes()       { "$PY" scripts/generate_route_table.py; }
_routes_check() { "$PY" scripts/generate_route_table.py --check; }
_abis()         { "$PY" scripts/verify_abis.py "$@"; }

_health() {
  local url="${1:-http://localhost:18790/health}"
  echo "GET $url"
  curl -fsS --max-time 10 "$url" && echo && echo "OK: gateway healthy" \
    || { echo "FAIL: gateway did not return 200 at $url"; return 1; }
}

_preflight() {
  echo "== ops preflight (read-only) =="
  local rc=0
  echo; echo "-- gateway.doctor --";        _doctor        || rc=$?
  echo; echo "-- route table freshness --"; _routes_check  || rc=$?
  echo; echo "-- ABI verification audit --"; _abis --strict || rc=$?
  echo
  if [ "$rc" -eq 0 ]; then
    echo "PREFLIGHT PASS — posture consistent, docs fresh, no ABI drift."
  else
    echo "PREFLIGHT FAIL — fix the flagged item(s) before deploy."
  fi
  return "$rc"
}

_help() { grep -E '^#( |$)' "${BASH_SOURCE[0]}" | sed -e 's/^# //' -e 's/^#$//'; }

cmd="${1:-help}"; shift || true
case "$cmd" in
  preflight)     _preflight ;;
  doctor)        _doctor "$@" ;;
  routes)        _routes ;;
  routes-check)  _routes_check ;;
  abis)          _abis "$@" ;;
  health)        _health "$@" ;;
  help|-h|--help) _help ;;
  *) echo "unknown command: $cmd"; echo; _help; exit 2 ;;
esac
