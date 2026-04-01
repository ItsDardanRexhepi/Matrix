#!/usr/bin/env bash
set -euo pipefail

# 0pnMatrx — Start Script
# Launches the gateway server

RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
NC='\033[0m'

info()  { echo -e "${GREEN}[0pnMatrx]${NC} $1"; }
warn()  { echo -e "${YELLOW}[0pnMatrx]${NC} $1"; }
error() { echo -e "${RED}[0pnMatrx]${NC} $1" >&2; }

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
cd "$SCRIPT_DIR"

if [ ! -d ".venv" ]; then
    error "Virtual environment not found. Run ./install.sh first."
    exit 1
fi

source .venv/bin/activate

if [ ! -f "openmatrix.config.json" ]; then
    error "No config file found. Run ./install.sh first."
    exit 1
fi

HOST=$(python3 -c "import json; c=json.load(open('openmatrix.config.json')); print(c.get('gateway',{}).get('host','0.0.0.0'))")
PORT=$(python3 -c "import json; c=json.load(open('openmatrix.config.json')); print(c.get('gateway',{}).get('port',18790))")

echo ""
echo "  ┌──────────────────────────────────┐"
echo "  │       0pnMatrx — Starting         │"
echo "  └──────────────────────────────────┘"
echo ""
info "Gateway: http://${HOST}:${PORT}"
info "Press Ctrl+C to stop"
echo ""

exec python3 -m gateway.server
