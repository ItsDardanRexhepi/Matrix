#!/usr/bin/env bash
# ──────────────────────────────────────────────────────────────────────
# 0pnMatrx — One-Command Installer
#
# Install:
#   curl -sSL https://raw.githubusercontent.com/ItsDardanRexhepi/0pnMatrx/main/install.sh | bash
#
# Or clone first, then:
#   ./install.sh
# ──────────────────────────────────────────────────────────────────────
set -euo pipefail

REPO="https://github.com/ItsDardanRexhepi/0pnMatrx.git"
INSTALL_DIR="${OPNMATRX_DIR:-$HOME/.opnmatrx}"
BRANCH="${OPNMATRX_BRANCH:-main}"
MIN_PYTHON="3.10"

# ── Colors ───────────────────────────────────────────────────────────
BOLD='\033[1m'
DIM='\033[2m'
CYAN='\033[36m'
GREEN='\033[32m'
YELLOW='\033[33m'
RED='\033[31m'
NC='\033[0m'

info()  { echo -e "${GREEN}[0pnMatrx]${NC} $1"; }
warn()  { echo -e "${YELLOW}[0pnMatrx]${NC} $1"; }
error() { echo -e "${RED}[0pnMatrx]${NC} $1" >&2; }

# ── Banner ───────────────────────────────────────────────────────────
banner() {
    echo ""
    echo -e "  ${CYAN}${BOLD}┌──────────────────────────────────────┐${NC}"
    echo -e "  ${CYAN}${BOLD}│        0pnMatrx — Installer          │${NC}"
    echo -e "  ${CYAN}${BOLD}└──────────────────────────────────────┘${NC}"
    echo ""
}

# ── Dependency checks ────────────────────────────────────────────────
check_command() {
    if command -v "$1" &>/dev/null; then
        info "$1 found"
        return 0
    else
        error "$1 not found."
        return 1
    fi
}

check_python() {
    if ! command -v python3 &>/dev/null; then
        error "Python 3 is required. Install from https://python.org"
        exit 1
    fi

    local version
    version=$(python3 -c 'import sys; print(f"{sys.version_info.major}.{sys.version_info.minor}")')
    local major minor
    major=$(echo "$version" | cut -d. -f1)
    minor=$(echo "$version" | cut -d. -f2)

    if [ "$major" -ge 3 ] && [ "$minor" -ge 10 ]; then
        info "Python $version"
        return 0
    fi

    error "Python ${MIN_PYTHON}+ required (found $version)"
    exit 1
}

check_git() {
    if ! command -v git &>/dev/null; then
        error "Git is required. Install it first."
        exit 1
    fi
    info "Git found"
}

# ── Install steps ────────────────────────────────────────────────────
detect_mode() {
    # If we're already inside the repo, do a local install
    if [ -f "gateway/server.py" ] && [ -f "pyproject.toml" ]; then
        INSTALL_DIR="$(pwd)"
        LOCAL_MODE=true
        info "Local install (already in repo)"
    else
        LOCAL_MODE=false
        info "Installing to $INSTALL_DIR"
    fi
}

clone_repo() {
    if [ "$LOCAL_MODE" = true ]; then
        return
    fi

    if [ -d "$INSTALL_DIR/.git" ]; then
        info "Updating existing installation..."
        cd "$INSTALL_DIR"
        git pull --ff-only origin "$BRANCH" 2>/dev/null || {
            warn "Pull failed. Continuing with existing code."
        }
    else
        info "Cloning 0pnMatrx..."
        git clone --depth 1 --branch "$BRANCH" "$REPO" "$INSTALL_DIR"
        cd "$INSTALL_DIR"
    fi
}

create_venv() {
    cd "$INSTALL_DIR"
    if [ ! -d ".venv" ]; then
        info "Creating virtual environment..."
        python3 -m venv .venv
    fi
    # shellcheck disable=SC1091
    source .venv/bin/activate
    info "Virtual environment active"
}

install_deps() {
    info "Installing dependencies..."
    pip install --upgrade pip --quiet 2>/dev/null
    pip install -e ".[dev]" --quiet 2>/dev/null || {
        pip install -r requirements.txt --quiet 2>/dev/null
    }
    info "Dependencies installed"
}

setup_config() {
    cd "$INSTALL_DIR"
    if [ ! -f "openmatrix.config.json" ]; then
        if [ -f "openmatrix.config.json.example" ]; then
            cp openmatrix.config.json.example openmatrix.config.json
            warn "Created openmatrix.config.json — edit it with your settings"
        fi
    else
        info "Config already exists"
    fi
}

install_cli() {
    # Create shell wrapper so 'openmatrix' works from anywhere
    local bin_dir="$INSTALL_DIR/.venv/bin"
    local wrapper="$bin_dir/openmatrix"

    # pip install -e . should have created the entry point,
    # but if not, create a wrapper script
    if [ ! -f "$wrapper" ]; then
        cat > "$wrapper" << WRAPPER
#!/usr/bin/env bash
SCRIPT_DIR="\$(cd "\$(dirname "\${BASH_SOURCE[0]}")" && pwd)"
VENV_DIR="\$(dirname "\$SCRIPT_DIR")"
PROJECT_DIR="\$(dirname "\$VENV_DIR")"
source "\$VENV_DIR/bin/activate" 2>/dev/null
cd "\$PROJECT_DIR"
exec python3 -m cli "\$@"
WRAPPER
        chmod +x "$wrapper"
    fi

    info "CLI installed: openmatrix"
}

add_to_path() {
    local bin_dir="$INSTALL_DIR/.venv/bin"
    local shell_rc=""

    # Detect shell config file
    if [ -n "${ZSH_VERSION:-}" ] || [ "$SHELL" = "$(command -v zsh)" ]; then
        shell_rc="$HOME/.zshrc"
    elif [ -n "${BASH_VERSION:-}" ] || [ "$SHELL" = "$(command -v bash)" ]; then
        shell_rc="$HOME/.bashrc"
    fi

    if [ -z "$shell_rc" ]; then
        warn "Could not detect shell. Add this to your shell config:"
        echo "  export PATH=\"$bin_dir:\$PATH\""
        return
    fi

    # Check if already in PATH
    if echo "$PATH" | grep -q "$bin_dir"; then
        info "Already in PATH"
        return
    fi

    # Check if already in rc file
    if [ -f "$shell_rc" ] && grep -q "opnmatrx" "$shell_rc" 2>/dev/null; then
        info "PATH entry already in $shell_rc"
        return
    fi

    echo "" >> "$shell_rc"
    echo "# 0pnMatrx" >> "$shell_rc"
    echo "export PATH=\"$bin_dir:\$PATH\"" >> "$shell_rc"
    info "Added to PATH in $shell_rc"
    warn "Run: source $shell_rc  (or open a new terminal)"
}

check_ollama() {
    if command -v ollama &>/dev/null; then
        info "Ollama found (optional, for local models)"
    else
        warn "Ollama not found — optional, for local AI models"
        echo -e "  ${DIM}Install from: https://ollama.com${NC}"
    fi
}

# ── Main ─────────────────────────────────────────────────────────────
main() {
    banner

    echo -e "  ${DIM}This will install 0pnMatrx and the 'openmatrix' CLI command.${NC}"
    echo ""

    # Checks
    check_python
    check_git

    # Install
    detect_mode
    clone_repo
    create_venv
    install_deps
    setup_config
    install_cli
    add_to_path
    check_ollama

    # Done
    echo ""
    echo -e "  ${GREEN}${BOLD}Installation complete.${NC}"
    echo ""
    echo -e "  ${BOLD}Quick start:${NC}"
    echo ""
    echo -e "    ${CYAN}openmatrix setup${NC}            Run interactive setup"
    echo -e "    ${CYAN}openmatrix gateway start${NC}     Start the gateway"
    echo -e "    ${CYAN}openmatrix gateway start -d${NC}  Start in background"
    echo -e "    ${CYAN}openmatrix gateway status${NC}    Check status"
    echo -e "    ${CYAN}openmatrix gateway stop${NC}      Stop the gateway"
    echo -e "    ${CYAN}openmatrix gateway logs${NC}      View logs"
    echo -e "    ${CYAN}openmatrix health${NC}            Health check"
    echo -e "    ${CYAN}openmatrix version${NC}           Show version"
    echo ""
    if [ "$LOCAL_MODE" = false ]; then
        echo -e "  ${DIM}Installed to: $INSTALL_DIR${NC}"
    fi
    echo ""
}

main "$@"
