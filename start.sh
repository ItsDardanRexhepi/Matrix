#!/usr/bin/env bash
# ──────────────────────────────────────────────────────────────────────
# 0pnMatrx — Legacy start script (wraps openmatrix gateway start)
#
# Prefer using the CLI directly:
#   openmatrix gateway start
#   openmatrix gateway start -d   (background)
# ──────────────────────────────────────────────────────────────────────
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
cd "$SCRIPT_DIR"

# Activate venv if available
if [ -d ".venv" ]; then
    # shellcheck disable=SC1091
    source .venv/bin/activate
fi

# Try the CLI first
if command -v openmatrix &>/dev/null; then
    exec openmatrix gateway start "$@"
fi

# Fallback: run gateway directly
if ! command -v python3 &>/dev/null; then
    echo "[0pnMatrx] Python 3 is required."
    exit 1
fi

# Check config
if [ ! -f "openmatrix.config.json" ]; then
    echo "[0pnMatrx] No config found. Running setup..."
    python3 setup.py
fi

HOST=$(python3 -c "import json; c=json.load(open('openmatrix.config.json')); print(c.get('gateway',{}).get('host','0.0.0.0'))")
PORT=$(python3 -c "import json; c=json.load(open('openmatrix.config.json')); print(c.get('gateway',{}).get('port',18790))")

echo ""
echo "  0pnMatrx Gateway"
echo "  http://${HOST}:${PORT}"
echo "  Press Ctrl+C to stop"
echo ""

exec python3 -m gateway.server
