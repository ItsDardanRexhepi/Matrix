#!/usr/bin/env python3
"""
0pnMatrx Contract Deployment — deploys OpenMatrixPaymaster and OpenMatrixAttestation
to Base Sepolia testnet.

Usage:
    python contracts/deploy.py

Requires:
    - openmatrix.config.json with blockchain config (rpc_url, paymaster_private_key, platform_wallet)
    - py-solc-x and web3 packages installed
    - Base Sepolia testnet ETH in the platform wallet (get from faucet)

All gas for deployment is paid by the platform wallet.
"""

import json
import logging
import sys
import time
from pathlib import Path

logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s")
logger = logging.getLogger(__name__)


def load_config() -> dict:
    config_path = Path("openmatrix.config.json")
    if not config_path.exists():
        logger.error("openmatrix.config.json not found. Run ./install.sh first.")
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
    print("  │  0pnMatrx — Contract Deployment       │")
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
        logger.error("Set these in openmatrix.config.json before deploying.")
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

    results = {}

    # 1. Deploy OpenMatrixPaymaster
    print()
    logger.info("═══ Deploying OpenMatrixPaymaster ═══")
    try:
        abi, bytecode = compile_contract("contracts/OpenMatrixPaymaster.sol", "OpenMatrixPaymaster")
        result = deploy_contract(web3, account, abi, bytecode, [platform_wallet], chain_id)
        results["paymaster"] = result
        logger.info(f"  Address: {result['contract_address']}")
        logger.info(f"  Gas used: {result['gas_used']}")
        logger.info(f"  Block: {result['block_number']}")

        # Save ABI
        Path("contracts/OpenMatrixPaymaster.abi.json").write_text(json.dumps(abi, indent=2))
    except Exception as e:
        logger.error(f"  Deployment failed: {e}")
        results["paymaster"] = {"status": "failed", "error": str(e)}

    # 2. Deploy OpenMatrixAttestation
    print()
    logger.info("═══ Deploying OpenMatrixAttestation ═══")
    try:
        abi, bytecode = compile_contract("contracts/OpenMatrixAttestation.sol", "OpenMatrixAttestation")
        result = deploy_contract(web3, account, abi, bytecode, [], chain_id)
        results["attestation"] = result
        logger.info(f"  Address: {result['contract_address']}")
        logger.info(f"  Gas used: {result['gas_used']}")
        logger.info(f"  Block: {result['block_number']}")

        # Save ABI
        Path("contracts/OpenMatrixAttestation.abi.json").write_text(json.dumps(abi, indent=2))
    except Exception as e:
        logger.error(f"  Deployment failed: {e}")
        results["attestation"] = {"status": "failed", "error": str(e)}

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
