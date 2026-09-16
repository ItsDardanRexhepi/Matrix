#!/usr/bin/env python3
"""
The Matrix Contract Deployment — deploys MatrixAttestation to Base Sepolia
testnet.

Usage:
    python contracts/deploy.py

Requires:
    - matrix.config.json with blockchain config (rpc_url, paymaster_private_key, platform_wallet)
    - py-solc-x and web3 packages installed
    - Base Sepolia testnet ETH in the platform wallet (get from faucet)

All gas for deployment is paid by the platform wallet.

WHAT THIS DEPLOYS IS DECLARED, in `CONTRACTS`, rather than written inline: a
tool that deploys inline cannot be read for what it deploys. The shape is
scripts/deploy_all.py's, which already worked this way.

DO NOT DEPLOY — this tool deployed MatrixPaymaster as its first step. It no
longer does. `legacy_notice_lines()` prints what it will not deploy and why on
every run, and scripts/refuse_legacy_contracts.py holds the one table and the
reason; a manifest that names it stops the pipeline there too.
"""

import json
import logging
import sys
import time
from pathlib import Path

# The retired-contract table lives in one place and is imported, not copied.
PROJECT_ROOT = Path(__file__).resolve().parent.parent
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from scripts.refuse_legacy_contracts import LEGACY_CONTRACTS  # noqa: E402

logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s")
logger = logging.getLogger(__name__)

#: Name, source file, config key and constructor arguments for everything this
#: tool deploys. Adding an entry is the only way to make it deploy something.
CONTRACTS: list[dict] = [
    {
        "name": "MatrixAttestation",
        "source": "contracts/MatrixAttestation.sol",
        "key": "attestation",
        "constructor_args": lambda cfg: [],
    },
]


def legacy_notice_lines() -> list[str]:
    """What this tool will NOT deploy, and why — printed on every run.

    Silence is not a gate. An operator who ran this tool expecting a paymaster
    has to be told it did not deploy one, and told which contract replaced it,
    or they will read the short run as a failure and reach for an older
    revision that still deploys the arbitrary-call contract.
    """
    lines = ["", "  Not deployed by this tool:"]
    for name, reason in LEGACY_CONTRACTS.items():
        lines.append(f"    {name} — {reason}")
    lines.append("")
    return lines


def load_config() -> dict:
    config_path = Path("matrix.config.json")
    if not config_path.exists():
        logger.error("matrix.config.json not found. Run ./install.sh first.")
        sys.exit(1)
    return json.loads(config_path.read_text())


def compile_contract(source_path: str, contract_name: str) -> tuple:
    """Compile a Solidity contract and return (abi, bytecode)."""
    from solcx import compile_source, install_solc

    logger.info(f"Installing Solidity compiler...")
    install_solc("0.8.24", show_progress=False)

    source = Path(source_path).read_text()
    logger.info(f"Compiling {contract_name}...")

    compiled = compile_source(
        source,
        output_values=["abi", "bin"],
        solc_version="0.8.24",
    )

    # Find the contract in compiled output
    for key, contract in compiled.items():
        if contract_name in key:
            return contract["abi"], contract["bin"]

    raise ValueError(f"Contract {contract_name} not found in compilation output")


def deploy_contract(web3, account, abi: list, bytecode: str, constructor_args: list, chain_id: int) -> dict:
    """Deploy a contract and return deployment info."""
    from web3 import Web3

    contract = web3.eth.contract(abi=abi, bytecode=bytecode)

    tx = contract.constructor(*constructor_args).build_transaction({
        "from": account.address,
        "chainId": chain_id,
        "gas": 3000000,
        "gasPrice": web3.eth.gas_price,
        "nonce": web3.eth.get_transaction_count(account.address),
    })

    signed = account.sign_transaction(tx)
    tx_hash = web3.eth.send_raw_transaction(signed.raw_transaction)
    logger.info(f"  Transaction sent: {tx_hash.hex()}")

    receipt = web3.eth.wait_for_transaction_receipt(tx_hash, timeout=120)

    return {
        "contract_address": receipt["contractAddress"],
        "tx_hash": tx_hash.hex(),
        "gas_used": receipt["gasUsed"],
        "block_number": receipt["blockNumber"],
        "status": "success" if receipt["status"] == 1 else "failed",
    }


def main():
    print()
    print("  ┌──────────────────────────────────────┐")
    print("  │  The Matrix — Contract Deployment       │")
    print("  │  Network: Base Sepolia Testnet         │")
    print("  └──────────────────────────────────────┘")
    print()

    config = load_config()
    bc = config.get("blockchain", {})

    rpc_url = bc.get("rpc_url", "")
    private_key = bc.get("paymaster_private_key", "")
    platform_wallet = bc.get("platform_wallet", "")

    # Validate config
    missing = []
    if not rpc_url or rpc_url.startswith("YOUR_"):
        missing.append("rpc_url")
    if not private_key or private_key.startswith("YOUR_"):
        missing.append("paymaster_private_key")
    if not platform_wallet or platform_wallet.startswith("YOUR_"):
        missing.append("platform_wallet")

    if missing:
        logger.error(f"Missing blockchain config: {', '.join(missing)}")
        logger.error("Set these in matrix.config.json before deploying.")
        logger.error("Get Base Sepolia ETH from: https://www.coinbase.com/faucets/base-ethereum-goerli-faucet")
        sys.exit(1)

    # Connect
    from web3 import Web3
    from eth_account import Account

    web3 = Web3(Web3.HTTPProvider(rpc_url))
    if not web3.is_connected():
        logger.error(f"Cannot connect to {rpc_url}")
        sys.exit(1)

    account = Account.from_key(private_key)
    balance = web3.eth.get_balance(account.address)
    balance_eth = web3.from_wei(balance, "ether")
    chain_id = bc.get("chain_id", 84532)

    logger.info(f"Network: {bc.get('network', 'base-sepolia')}")
    logger.info(f"Chain ID: {chain_id}")
    logger.info(f"Deployer: {account.address}")
    logger.info(f"Balance: {balance_eth} ETH")

    if balance == 0:
        logger.error("No ETH in deployer wallet. Get testnet ETH from a faucet.")
        sys.exit(1)

    # Say what will not be deployed BEFORE deploying anything, so the line sits
    # above the run in the operator's scrollback rather than under it.
    for line in legacy_notice_lines():
        print(line)

    results = {}

    for entry in CONTRACTS:
        name = entry["name"]
        print()
        logger.info(f"═══ Deploying {name} ═══")
        try:
            abi, bytecode = compile_contract(entry["source"], name)
            result = deploy_contract(
                web3, account, abi, bytecode,
                entry["constructor_args"](bc), chain_id,
            )
            results[entry["key"]] = result
            logger.info(f"  Address: {result['contract_address']}")
            logger.info(f"  Gas used: {result['gas_used']}")
            logger.info(f"  Block: {result['block_number']}")

            # Save ABI
            Path(f"contracts/{name}.abi.json").write_text(json.dumps(abi, indent=2))
        except Exception as e:
            logger.error(f"  Deployment failed: {e}")
            results[entry["key"]] = {"status": "failed", "error": str(e)}

    # Save deployment results
    deployment_file = Path("contracts/deployment.json")
    deployment_data = {
        "network": bc.get("network", "base-sepolia"),
        "chain_id": chain_id,
        "deployer": account.address,
        "deployed_at": int(time.time()),
        "contracts": results,
    }
    deployment_file.write_text(json.dumps(deployment_data, indent=2))

    # Summary
    print()
    print("  ┌──────────────────────────────────────┐")
    print("  │  Deployment Summary                    │")
    print("  └──────────────────────────────────────┘")

    for name, result in results.items():
        status = result.get("status", "unknown")
        addr = result.get("contract_address", "N/A")
        gas = result.get("gas_used", "N/A")
        print(f"  {name}: {status}")
        if status == "success":
            print(f"    Address: {addr}")
            print(f"    Gas: {gas}")

    remaining = web3.eth.get_balance(account.address)
    print(f"\n  Remaining balance: {web3.from_wei(remaining, 'ether')} ETH")
    print(f"  Results saved to: {deployment_file}")
    print()


if __name__ == "__main__":
    main()
