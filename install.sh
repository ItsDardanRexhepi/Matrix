#!/usr/bin/env bash
set -euo pipefail

# 0pnMatrx — Install Script
# Installs dependencies for macOS and Linux

RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
NC='\033[0m'

info()  { echo -e "${GREEN}[0pnMatrx]${NC} $1"; }
warn()  { echo -e "${YELLOW}[0pnMatrx]${NC} $1"; }
error() { echo -e "${RED}[0pnMatrx]${NC} $1" >&2; }

OS="$(uname -s)"

check_python() {
    if command -v python3 &>/dev/null; then
        PYTHON_VERSION=$(python3 -c 'import sys; print(f"{sys.version_info.major}.{sys.version_info.minor}")')
        MAJOR=$(echo "$PYTHON_VERSION" | cut -d. -f1)
        MINOR=$(echo "$PYTHON_VERSION" | cut -d. -f2)
        if [ "$MAJOR" -ge 3 ] && [ "$MINOR" -ge 10 ]; then
            info "Python $PYTHON_VERSION found"
            return 0
        fi
    fi
    error "Python 3.10+ is required. Install it from https://python.org"
    exit 1
}

check_ollama() {
    if command -v ollama &>/dev/null; then
        info "Ollama found"
        return 0
    fi
    warn "Ollama not found. Install it from https://ollama.com for local model support."
    warn "You can still use cloud providers (OpenAI, Anthropic, etc.) without Ollama."
}

setup_venv() {
    if [ ! -d ".venv" ]; then
        info "Creating virtual environment..."
        python3 -m venv .venv
    fi
    info "Activating virtual environment..."
    source .venv/bin/activate
}

install_dependencies() {
    info "Installing Python dependencies..."
    pip install --upgrade pip --quiet

    pip install --quiet \
        aiohttp>=3.9.0 \
        aiofiles>=23.0 \
        web3>=6.0.0 \
        py-solc-x>=2.0.0 \
        pynacl>=1.5.0 \
        requests>=2.31.0 \
        pyyaml>=6.0

    info "Dependencies installed"
}

setup_config() {
    if [ ! -f "openmatrix.config.json" ]; then
        if [ -f "openmatrix.config.json.example" ]; then
            cp openmatrix.config.json.example openmatrix.config.json
            warn "Created openmatrix.config.json from example — edit it with your settings"
        else
            error "No config example found"
            exit 1
        fi
    else
        info "Config file already exists"
    fi
}

pull_default_model() {
    if command -v ollama &>/dev/null; then
        info "Pulling default model (llama3.1)..."
        ollama pull llama3.1 || warn "Could not pull llama3.1 — you can pull it manually later"
    fi
}

main() {
    echo ""
    echo "  ┌──────────────────────────────────┐"
    echo "  │       0pnMatrx — Install          │"
    echo "  └──────────────────────────────────┘"
    echo ""

    check_python
    check_ollama
    setup_venv
    install_dependencies
    setup_config

    echo ""
    info "Installation complete."
    info "Run ./start.sh to launch 0pnMatrx"
    echo ""
}

main "$@"
