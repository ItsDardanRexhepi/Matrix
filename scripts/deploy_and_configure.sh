#!/usr/bin/env bash
set -euo pipefail

# =============================================================================
# deploy_and_configure.sh
#
# Full deployment pipeline for the Matrix platform:
#   1. Validate environment variables
#   2. Deploy all smart contracts via deploy_all.py
#   3. Read the deployment manifest, and refuse one that names a retired
#      contract before anything is configured or funded
#   4. Update matrix.config.json with every deployed address
#   5. Say where paymaster funding actually happens (not here)
#   6. Restart the gateway via docker compose
#   7. Health-check the platform with retry logic
#   8. Print a summary of all configured addresses
#
# Usage: bash scripts/deploy_and_configure.sh
# =============================================================================

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PROJECT_ROOT="$(cd "$SCRIPT_DIR/.." && pwd)"

MANIFEST_PATH="$PROJECT_ROOT/deployment_manifest.json"
CONFIG_PATH="$PROJECT_ROOT/matrix.config.json"

# ---------------------------------------------------------------------------
# 1. Validate required environment variables
# ---------------------------------------------------------------------------

echo "==> Checking required environment variables..."

if [[ -z "${BASE_RPC_URL:-}" ]]; then
    echo "ERROR: BASE_RPC_URL is not set. Export it before running this script."
    echo "  Example: export BASE_RPC_URL=https://mainnet.base.org"
    exit 1
fi

if [[ -z "${DEPLOYER_PRIVATE_KEY:-}" ]]; then
    echo "ERROR: DEPLOYER_PRIVATE_KEY is not set. Export it before running this script."
    exit 1
fi

# NEOSAFE_ADDRESS defaults to the canonical NeoSafe multisig if not overridden
export NEOSAFE_ADDRESS="${NEOSAFE_ADDRESS:-0x46fF491D7054A6F500026B3E81f358190f8d8Ec5}"

echo "  BASE_RPC_URL      = $BASE_RPC_URL"
echo "  DEPLOYER_PRIVATE_KEY = (set, redacted)"
echo "  NEOSAFE_ADDRESS   = $NEOSAFE_ADDRESS"
echo ""

# Verify jq is available
if ! command -v jq &>/dev/null; then
    echo "ERROR: jq is required but not installed. Install it with:"
    echo "  brew install jq   (macOS)"
    echo "  apt-get install jq (Debian/Ubuntu)"
    exit 1
fi

# ---------------------------------------------------------------------------
# 2. Deploy all contracts
# ---------------------------------------------------------------------------

echo "==> Running contract deployment (python scripts/deploy_all.py)..."

export MATRIX_RPC_URL="$BASE_RPC_URL"
export MATRIX_PRIVATE_KEY="$DEPLOYER_PRIVATE_KEY"
export MATRIX_NEOSAFE_ADDRESS="$NEOSAFE_ADDRESS"

cd "$PROJECT_ROOT"
python scripts/deploy_all.py

echo ""

# ---------------------------------------------------------------------------
# 3. Read the deployment manifest and extract every contract address
# ---------------------------------------------------------------------------

echo "==> Reading deployment manifest from $MANIFEST_PATH..."

if [[ ! -f "$MANIFEST_PATH" ]]; then
    echo "ERROR: Deployment manifest not found at $MANIFEST_PATH"
    echo "  deploy_all.py should have created it. Check the output above."
    exit 1
fi

declare -A CONTRACT_ADDRESSES

while IFS='=' read -r name addr; do
    CONTRACT_ADDRESSES["$name"]="$addr"
    echo "  Found: $name = $addr"
done < <(jq -r '.contracts | to_entries[] | "\(.key)=\(.value.contract_address)"' "$MANIFEST_PATH")

if [[ ${#CONTRACT_ADDRESSES[@]} -eq 0 ]]; then
    echo "ERROR: No contracts found in the manifest. Deployment may have failed."
    exit 1
fi

echo "  Total contracts deployed: ${#CONTRACT_ADDRESSES[@]}"
echo ""

# ---------------------------------------------------------------------------
# 3b. Refuse a manifest that names a retired contract
#
# DO NOT DEPLOY — this step exists because this script used to map
# MatrixPaymaster into the config and send it 0.1 ETH the moment a manifest
# named it. That contract's sponsoredCall(address,bytes) reaches any address
# with any calldata from any authorized key, nothing in the runtime calls it,
# and the platform's paymaster is the ERC-4337 MatrixVerifyingPaymaster. The
# list and the reason live in scripts/refuse_legacy_contracts.py, which
# contracts/deploy.py imports as well, so there is one table and not two.
#
# BEFORE the config is written and before anything is funded: a refusal that
# fires after the address is already in matrix.config.json has not refused
# anything.
# ---------------------------------------------------------------------------

echo "==> Checking the manifest for retired contracts..."
if ! python3 "$PROJECT_ROOT/scripts/refuse_legacy_contracts.py" "$MANIFEST_PATH"; then
    echo "ERROR: the deployment manifest names a contract this repository does not deploy."
    echo "  Nothing was configured and nothing was funded."
    exit 1
fi
echo "  None named."
echo ""

# ---------------------------------------------------------------------------
# 4. Update matrix.config.json with every deployed address
# ---------------------------------------------------------------------------

echo "==> Updating $CONFIG_PATH with deployed addresses..."

declare -A SERVICE_KEY_MAP=(
    ["MatrixMarketplace"]="marketplace"
    ["MatrixStaking"]="staking"
    ["MatrixDAO"]="dao_management"
    ["MatrixInsurance"]="insurance"
    ["MatrixDEX"]="dex"
    ["MatrixNFT"]="nft_services"
    ["MatrixRewards"]="brand_rewards"
    ["MatrixDID"]="did_identity"
)

TMP_CONFIG="$(mktemp)"
cp "$CONFIG_PATH" "$TMP_CONFIG"

for contract_name in "${!CONTRACT_ADDRESSES[@]}"; do
    address="${CONTRACT_ADDRESSES[$contract_name]}"

    if [[ -n "${SERVICE_KEY_MAP[$contract_name]:-}" ]]; then
        svc_key="${SERVICE_KEY_MAP[$contract_name]}"
    else
        svc_key="$(echo "$contract_name" | sed 's/^Matrix//' | tr '[:upper:]' '[:lower:]')"
    fi

    jq --arg key "$svc_key" --arg addr "$address" \
        '.services[$key] = (.services[$key] // {}) | .services[$key].contract_address = $addr' \
        "$TMP_CONFIG" > "${TMP_CONFIG}.new" && mv "${TMP_CONFIG}.new" "$TMP_CONFIG"

    echo "  services.$svc_key.contract_address = $address"
done

# Update blockchain config
CHAIN_ID="$(jq -r '.chain_id // 8453' "$MANIFEST_PATH")"
jq --arg rpc "$BASE_RPC_URL" --arg neosafe "$NEOSAFE_ADDRESS" \
    '.blockchain.rpc_url = $rpc | .blockchain.neosafe_address = $neosafe' \
    "$TMP_CONFIG" > "${TMP_CONFIG}.new" && mv "${TMP_CONFIG}.new" "$TMP_CONFIG"

mv "$TMP_CONFIG" "$CONFIG_PATH"
echo "  Config updated successfully."
echo ""

# ---------------------------------------------------------------------------
# 5. Paymaster funding — not done here
#
# DO NOT DEPLOY — this step used to send 0.1 ETH to whatever address the
# manifest carried under MatrixPaymaster. The refusal in step 3b means no
# manifest reaching this line names that contract at all, so the step is gone
# rather than left behind a condition that can never be true.
#
# The paymaster the platform actually uses is funded differently, and not by
# this script: MatrixVerifyingPaymaster pays gas out of its own EntryPoint
# DEPOSIT — `deposit()` forwards to `entryPoint.depositTo(address(this))` and
# `addStake(unstakeDelaySec)` stakes it. A plain transfer to the contract would
# sit in its balance and sponsor nothing. It is a deliberate, amount-bearing
# step for an operator; scripts/prepare_aa_deploy.py prints it as a post-deploy
# human step, which is where it belongs rather than inside a pipeline.
# ---------------------------------------------------------------------------

echo "==> Paymaster funding is not performed by this script."
echo "    MatrixVerifyingPaymaster is funded through its EntryPoint deposit"
echo "    (deposit() / addStake) — see scripts/prepare_aa_deploy.py."
echo ""

# ---------------------------------------------------------------------------
# 6. Restart the gateway
# ---------------------------------------------------------------------------

echo "==> Restarting gateway (docker compose down && docker compose up -d)..."

cd "$PROJECT_ROOT"
docker compose down
docker compose up -d

echo "  Gateway restarted."
echo ""

# ---------------------------------------------------------------------------
# 7. Health check with retry logic (3 attempts, 10s apart)
# ---------------------------------------------------------------------------

echo "==> Running health check against https://openmatrix-ai.com/health..."

HEALTH_URL="https://openmatrix-ai.com/health"
MAX_RETRIES=3
RETRY_DELAY=10
HEALTHY=false

for attempt in $(seq 1 "$MAX_RETRIES"); do
    echo "  Attempt $attempt/$MAX_RETRIES..."
    if curl -sf --max-time 15 "$HEALTH_URL" > /dev/null 2>&1; then
        HEALTHY=true
        echo "  Health check passed."
        break
    else
        echo "  Health check failed."
        if [[ "$attempt" -lt "$MAX_RETRIES" ]]; then
            echo "  Retrying in ${RETRY_DELAY}s..."
            sleep "$RETRY_DELAY"
        fi
    fi
done

if [[ "$HEALTHY" != "true" ]]; then
    echo ""
    echo "WARNING: Health check did not pass after $MAX_RETRIES attempts."
    echo "  The gateway may still be starting. Check logs with: docker compose logs -f"
fi

echo ""

# ---------------------------------------------------------------------------
# 8. Print deployment summary
# ---------------------------------------------------------------------------

echo "============================================================"
echo "  DEPLOYMENT & CONFIGURATION COMPLETE"
echo "============================================================"
echo ""
echo "RPC URL:         $BASE_RPC_URL"
echo "NeoSafe Address: $NEOSAFE_ADDRESS"
echo ""
echo "Deployed Contracts:"
echo "------------------------------------------------------------"

for contract_name in $(echo "${!CONTRACT_ADDRESSES[@]}" | tr ' ' '\n' | sort); do
    address="${CONTRACT_ADDRESSES[$contract_name]}"
    printf "  %-30s %s\n" "$contract_name" "$address"
done

echo "------------------------------------------------------------"
echo ""
echo "Config file: $CONFIG_PATH"
echo "Manifest:    $MANIFEST_PATH"
echo ""

if [[ "$HEALTHY" == "true" ]]; then
    echo "Platform is UP and healthy."
else
    echo "Platform health check inconclusive -- verify manually."
fi

echo "============================================================"
