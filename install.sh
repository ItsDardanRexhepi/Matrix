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
    fi
    cd "$INSTALL_DIR"
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
    pip install -r requirements.txt --quiet 2>/dev/null
    info "Dependencies installed"
}

install_cli() {
    local venv_bin="$INSTALL_DIR/.venv/bin"
    local wrapper="$venv_bin/openmatrix"

    # Create wrapper that resolves symlinks (so ~/.local/bin/openmatrix works).
    # rm first: `cat >` follows a link, so a symlink already sitting at this
    # path would have been written THROUGH (or, if it looped, failed) instead
    # of replaced.
    rm -f "$wrapper"
    cat > "$wrapper" << 'WRAPPER'
#!/usr/bin/env bash
set -euo pipefail
# Resolve our own path the way the kernel did when it ran us. `cd -P` matters:
# a logical cd applies a link target's `..` lexically, the kernel applies it
# physically, and on a chain where the two differ the walk never ends. The hop
# limit is the backstop for anything else (a link changed mid-walk).
SOURCE="${BASH_SOURCE[0]}"
HOPS=0
while [ -L "$SOURCE" ]; do
    HOPS=$((HOPS + 1))
    if [ "$HOPS" -gt 40 ]; then
        echo "openmatrix: too many symbolic links resolving ${BASH_SOURCE[0]}" >&2
        exit 1
    fi
    DIR="$(cd -P "$(dirname "$SOURCE")" && pwd)"
    SOURCE="$(readlink "$SOURCE")"
    [[ "$SOURCE" != /* ]] && SOURCE="$DIR/$SOURCE"
done
SCRIPT_DIR="$(cd -P "$(dirname "$SOURCE")" && pwd)"
VENV_DIR="$(dirname "$SCRIPT_DIR")"
PROJECT_DIR="$(dirname "$VENV_DIR")"
source "$VENV_DIR/bin/activate" 2>/dev/null
cd "$PROJECT_DIR"
exec python3 -m cli "$@"
WRAPPER
    chmod +x "$wrapper"

    # ── Make 'openmatrix' available system-wide ──
    # Strategy: symlink into a directory that's already in PATH.
    # Try /usr/local/bin first, then ~/.local/bin, then fall back to
    # shell rc PATH addition.

    local linked=false

    # Option 1: /usr/local/bin (works on macOS out of the box)
    if [ -d "/usr/local/bin" ] && [ -w "/usr/local/bin" ]; then
        # -n: if the destination is a link to a directory, replace the link
        # rather than creating a new one inside whatever it points at.
        ln -sfn "$wrapper" /usr/local/bin/openmatrix
        info "Linked: /usr/local/bin/openmatrix"
        linked=true
    fi

    # Option 2: ~/.local/bin (common on Linux, sometimes macOS)
    if [ "$linked" = false ]; then
        local local_bin="$HOME/.local/bin"
        mkdir -p "$local_bin"
        ln -sfn "$wrapper" "$local_bin/openmatrix"
        info "Linked: $local_bin/openmatrix"
        linked=true

        # Exact PATH-component match. `grep -q "$local_bin"` matched any
        # substring (…/.local/bin-old) and read the path as a regex.
        case ":$PATH:" in
            *":$local_bin:"*) ;;
            *) _add_path_to_rc "$local_bin" ;;
        esac
    fi
    # (There was an "Option 3" here that added the venv's own bin to PATH. It
    # could never run — Option 2 always links — and it is gone rather than
    # left to be re-enabled pointing PATH at a directory this script rewrites.)

    info "CLI ready: openmatrix"
}

_add_path_to_rc() {
    local dir_to_add="$1"
    local shell_rc=""

    # On macOS the login shell is almost always zsh.
    # When running via 'curl | bash' we're in bash, but the user's
    # actual shell is what matters for persistent PATH.
    if [ "$(uname -s)" = "Darwin" ]; then
        # macOS: prefer .zshrc (default shell since Catalina)
        if [ -f "$HOME/.zshrc" ]; then
            shell_rc="$HOME/.zshrc"
        elif [ -f "$HOME/.bash_profile" ]; then
            shell_rc="$HOME/.bash_profile"
        else
            shell_rc="$HOME/.zshrc"
        fi
    else
        # Linux: check common locations
        if [ -f "$HOME/.zshrc" ] && grep -q "zsh" /etc/shells 2>/dev/null; then
            shell_rc="$HOME/.zshrc"
        elif [ -f "$HOME/.bashrc" ]; then
            shell_rc="$HOME/.bashrc"
        elif [ -f "$HOME/.profile" ]; then
            shell_rc="$HOME/.profile"
        else
            shell_rc="$HOME/.bashrc"
        fi
    fi

    # APPENDED to PATH, never prepended. A prepended entry outranks /usr/bin in
    # every future shell, so anything later written into this directory by any
    # process running as the user (a `pip install --user` of a typosquat, for
    # one) would shadow git, python3, curl. Appended, it can only supply
    # commands nothing earlier on PATH already provides — which is all the
    # `openmatrix` link needs.
    local line="export PATH=\"\$PATH:$dir_to_add\""
    local legacy="export PATH=\"$dir_to_add:\$PATH\""

    if [ -f "$shell_rc" ] && grep -qxF "$legacy" "$shell_rc" 2>/dev/null; then
        # Written by an earlier version of this installer. Reported, not
        # rewritten: rc files are often symlinks into a dotfiles repo, and an
        # installer editing one in place is the worse failure if this match is
        # ever wrong.
        warn "$shell_rc puts $dir_to_add at the FRONT of PATH (an older installer wrote it)."
        warn "  Replace:  $legacy"
        warn "  With:     $line"
        return
    fi

    # Already configured some other way — leave the file alone.
    if [ -f "$shell_rc" ] && grep -qF "$dir_to_add" "$shell_rc" 2>/dev/null; then
        return
    fi

    printf '\n# 0pnMatrx CLI (delete this line and the next to undo)\n%s\n' "$line" >> "$shell_rc"
    info "Added $dir_to_add to the end of PATH in $shell_rc"
    info "  To undo, delete the two lines under '# 0pnMatrx CLI' in that file."
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
    install_cli
    check_ollama

    echo ""
    echo -e "  ${GREEN}${BOLD}Installation complete.${NC}"
    echo ""

    # ── Launch interactive setup ─────────────────────────────────────
    # If no config exists yet, walk the user through first-boot setup
    # using the interactive setup wizard.
    cd "$INSTALL_DIR"
    if [ ! -f "openmatrix.config.json" ]; then
        echo -e "  ${BOLD}Launching first-time setup...${NC}"
        echo ""
        sleep 1
        exec "$INSTALL_DIR/.venv/bin/python3" "$INSTALL_DIR/setup.py"
    else
        info "Config already exists — skipping setup wizard."
        echo ""
        echo -e "  ${BOLD}Quick start:${NC}"
        echo ""
        echo -e "    ${CYAN}openmatrix gateway start${NC}     Start the gateway"
        echo -e "    ${CYAN}openmatrix gateway start -d${NC}  Start in background"
        echo -e "    ${CYAN}openmatrix gateway status${NC}    Check status"
        echo -e "    ${CYAN}openmatrix gateway stop${NC}      Stop the gateway"
        echo -e "    ${CYAN}openmatrix gateway logs${NC}      View logs"
        echo -e "    ${CYAN}openmatrix health${NC}            Health check"
        echo -e "    ${CYAN}openmatrix version${NC}           Show version"
        echo ""
    fi
}

main "$@"
