#!/usr/bin/env bash
#
# scripts/build-contracts.sh
#
# One-shot Foundry bootstrap for the 0pnMatrx Solidity contracts.
#
# What this script does:
#   1. Verifies `forge` is installed (Foundry).
#   2. Installs the pinned dependencies into `contracts/lib` (forge-std
#      and OpenZeppelin) if they are missing.
#   3. Builds every contract under `contracts/` with solc 0.8.20
#      (pinned in `foundry.toml`).
#   4. Runs the full Foundry test suite under `contracts/test/`.
#
# Usage:
#   ./scripts/build-contracts.sh            # install + build + test
#   ./scripts/build-contracts.sh --no-test  # install + build only
#   ./scripts/build-contracts.sh --clean    # nuke cache + out + rebuild
#
# Exit codes:
#   0  success
#   1  forge not installed
#   2  dependency install failed
#   3  build failed
#   4  tests failed

set -euo pipefail

REPO_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "${REPO_ROOT}"

SKIP_TEST=0
CLEAN=0
for arg in "$@"; do
    case "${arg}" in
        --no-test) SKIP_TEST=1 ;;
        --clean)   CLEAN=1 ;;
        -h|--help)
            sed -n '2,30p' "${BASH_SOURCE[0]}"
            exit 0
            ;;
        *)
            echo "unknown flag: ${arg}" >&2
            exit 64
            ;;
    esac
done

log() { printf '\033[1;36m[build-contracts]\033[0m %s\n' "$*"; }
err() { printf '\033[1;31m[build-contracts]\033[0m %s\n' "$*" >&2; }

# ---------------------------------------------------------------------------
# 1. forge must be installed
# ---------------------------------------------------------------------------
if ! command -v forge >/dev/null 2>&1; then
    err "forge is not installed."
    err "install Foundry: curl -L https://foundry.paradigm.xyz | bash && foundryup"
    exit 1
fi

log "using $(forge --version | head -n1)"

# ---------------------------------------------------------------------------
# 2. dependencies — only install when missing so we don't re-download on
#    every invocation
# ---------------------------------------------------------------------------
mkdir -p contracts/lib

install_lib() {
    local name="$1"
    local repo="$2"
    local tag="$3"
    local target="contracts/lib/${name}"

    if [[ -d "${target}" ]]; then
        log "dependency ${name} already present — skipping"
        return 0
    fi

    log "installing ${name}@${tag}"
    if ! forge install --no-commit --no-git "${repo}@${tag}" >/dev/null 2>&1; then
        # Fallback to plain git clone when we're not inside a git repo
        # or when forge install refuses the non-git flag combination.
        git clone --depth 1 --branch "${tag}" "https://github.com/${repo}.git" "${target}" || {
            err "failed to install ${name}"
            exit 2
        }
    fi
}

install_lib "forge-std"             "foundry-rs/forge-std"             "v1.9.4"
install_lib "openzeppelin-contracts" "OpenZeppelin/openzeppelin-contracts" "v5.0.2"

# ---------------------------------------------------------------------------
# 3. build
# ---------------------------------------------------------------------------
if [[ "${CLEAN}" -eq 1 ]]; then
    log "cleaning contracts/out and contracts/cache"
    rm -rf contracts/out contracts/cache
fi

log "compiling contracts with solc 0.8.20"
if ! forge build; then
    err "forge build failed"
    exit 3
fi

# ---------------------------------------------------------------------------
# 4. test
# ---------------------------------------------------------------------------
if [[ "${SKIP_TEST}" -eq 1 ]]; then
    log "--no-test requested; skipping forge test"
    exit 0
fi

log "running forge test"
if ! forge test -vv; then
    err "forge test failed"
    exit 4
fi

log "all contract checks passed"
