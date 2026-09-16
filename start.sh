#!/usr/bin/env bash
# ──────────────────────────────────────────────────────────────────────
# The Matrix — Legacy start script (wraps matrix gateway start)
#
# Prefer using the CLI directly:
#   matrix gateway start
#   matrix gateway start -d   (background)
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
if command -v matrix &>/dev/null; then
    exec matrix gateway start "$@"
fi

# Fallback: run gateway directly
if ! command -v python3 &>/dev/null; then
    echo "[The Matrix] Python 3 is required."
    exit 1
fi

# Check config
if [ ! -f "matrix.config.json" ]; then
    echo "[The Matrix] No config found. Running setup..."
    python3 setup.py
fi

HOST=$(python3 -c "import json; c=json.load(open('matrix.config.json')); print(c.get('gateway',{}).get('host','0.0.0.0'))")
PORT=$(python3 -c "import json; c=json.load(open('matrix.config.json')); print(c.get('gateway',{}).get('port',18790))")

echo ""
echo "  The Matrix Gateway"
echo "  http://${HOST}:${PORT}"
echo "  Press Ctrl+C to stop"
echo ""

exec python3 -m gateway.server
