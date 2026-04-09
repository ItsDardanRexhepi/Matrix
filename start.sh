#!/usr/bin/env bash
set -euo pipefail

# 0pnMatrx — Start Script
# Launches the gateway server

RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
CYAN='\033[0;36m'
BOLD='\033[1m'
NC='\033[0m'

info()  { echo -e "${GREEN}[0pnMatrx]${NC} $1"; }
warn()  { echo -e "${YELLOW}[0pnMatrx]${NC} $1"; }
error() { echo -e "${RED}[0pnMatrx]${NC} $1" >&2; }

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
cd "$SCRIPT_DIR"

# Activate venv if available
if [ -d ".venv" ]; then
    source .venv/bin/activate
fi

# Check Python
if ! command -v python3 &> /dev/null; then
    error "Python 3 is required. Install it first."
    exit 1
fi

# Check config — run interactive setup if missing
if [ ! -f "openmatrix.config.json" ]; then
    warn "No configuration found."
    echo ""
    info "Running interactive setup..."
    echo ""
    python3 setup.py
    echo ""
    if [ ! -f "openmatrix.config.json" ]; then
        error "Setup did not create config. Cannot start."
        exit 1
    fi
fi

# Check dependencies
python3 -c "import aiohttp" 2>/dev/null || {
    warn "Dependencies not installed. Installing..."
    python3 -m pip install -r requirements.txt -q
}

HOST=$(python3 -c "import json; c=json.load(open('openmatrix.config.json')); print(c.get('gateway',{}).get('host','0.0.0.0'))")
PORT=$(python3 -c "import json; c=json.load(open('openmatrix.config.json')); print(c.get('gateway',{}).get('port',18790))")

echo ""
echo -e "  ${CYAN}${BOLD}┌──────────────────────────────────┐${NC}"
echo -e "  ${CYAN}${BOLD}│       0pnMatrx — Starting         │${NC}"
echo -e "  ${CYAN}${BOLD}└──────────────────────────────────┘${NC}"
echo ""
info "Gateway: http://${HOST}:${PORT}"
info "Press Ctrl+C to stop"
echo ""

exec python3 -m gateway.server
