#!/usr/bin/env bash
set -euo pipefail

# =============================================================================
# deploy_and_configure.sh
#
# Full deployment pipeline for the 0pnMatrx platform:
#   1. Validate environment variables
#   2. Deploy all smart contracts via deploy_all.py
#   3. Read the deployment manifest and extract contract addresses
#   4. Update openmatrix.config.json with every deployed address
#   5. Fund the paymaster contract with 0.1 ETH
#   6. Restart the gateway via docker compose
#   7. Health-check the platform with retry logic
#   8. Print a summary of all configured addresses
#
# Usage: bash scripts/deploy_and_configure.sh
# =============================================================================

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PROJECT_ROOT="$(cd "$SCRIPT_DIR/.." && pwd)"

MANIFEST_PATH="$PROJECT_ROOT/deployment_manifest.json"
CONFIG_PATH="$PROJECT_ROOT/openmatrix.config.json"

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

export OPENMATRIX_RPC_URL="$BASE_RPC_URL"
export OPENMATRIX_PRIVATE_KEY="$DEPLOYER_PRIVATE_KEY"
export OPENMATRIX_NEOSAFE_ADDRESS="$NEOSAFE_ADDRESS"

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
# 4. Update openmatrix.config.json with every deployed address
# ---------------------------------------------------------------------------

echo "==> Updating $CONFIG_PATH with deployed addresses..."

declare -A SERVICE_KEY_MAP=(
    ["OpenMatrixMarketplace"]="marketplace"
    ["OpenMatrixStaking"]="staking"
    ["OpenMatrixDAO"]="dao_management"
    ["OpenMatrixInsurance"]="insurance"
    ["OpenMatrixDEX"]="dex"
    ["OpenMatrixNFT"]="nft_services"
    ["OpenMatrixPaymaster"]="paymaster"
    ["OpenMatrixRewards"]="brand_rewards"
    ["OpenMatrixDID"]="did_identity"
)

TMP_CONFIG="$(mktemp)"
cp "$CONFIG_PATH" "$TMP_CONFIG"

for contract_name in "${!CONTRACT_ADDRESSES[@]}"; do
    address="${CONTRACT_ADDRESSES[$contract_name]}"

    if [[ -n "${SERVICE_KEY_MAP[$contract_name]:-}" ]]; then
        svc_key="${SERVICE_KEY_MAP[$contract_name]}"
    else
        svc_key="$(echo "$contract_name" | sed 's/^OpenMatrix//' | tr '[:upper:]' '[:lower:]')"
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
# 5. Fund the paymaster with 0.1 ETH
# ---------------------------------------------------------------------------

PAYMASTER_ADDR="${CONTRACT_ADDRESSES[OpenMatrixPaymaster]:-}"

if [[ -n "$PAYMASTER_ADDR" ]]; then
    echo "==> Funding paymaster ($PAYMASTER_ADDR) with 0.1 ETH..."

    python3 -c "
from web3 import Web3
w3 = Web3(Web3.HTTPProvider('$BASE_RPC_URL'))
acct = w3.eth.account.from_key('$DEPLOYER_PRIVATE_KEY')
tx = {
    'to': Web3.to_checksum_address('$PAYMASTER_ADDR'),
    'value': w3.to_wei(0.1, 'ether'),
    'gas': 21000,
    'gasPrice': w3.eth.gas_price,
    'nonce': w3.eth.get_transaction_count(acct.address),
    'chainId': w3.eth.chain_id,
}
signed = acct.sign_transaction(tx)
tx_hash = w3.eth.send_raw_transaction(signed.raw_transaction)
receipt = w3.eth.wait_for_transaction_receipt(tx_hash, timeout=120)
print(f'  Funded paymaster: tx {receipt.transactionHash.hex()} (status={receipt.status})')
"
    echo ""
else
    echo "==> WARN: OpenMatrixPaymaster not found in manifest; skipping funding step."
    echo ""
fi

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
