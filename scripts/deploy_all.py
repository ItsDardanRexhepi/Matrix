"""Deploy all contracts to Base Sepolia and attest each deployment."""

import asyncio
import json
import logging
import os
import subprocess
import sys
import time
from pathlib import Path
from typing import Any

# Ensure project root is importable
PROJECT_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(PROJECT_ROOT))

from contracts.deployer import ContractDeployer
from contracts.eas_deployer import attest_action
from contracts.neosafe_verifier import verify_revenue_route

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Contract registry — name, source file, constructor args builder
# ---------------------------------------------------------------------------

CONTRACTS: list[dict[str, Any]] = [
    {
        "name": "OpenMatrixMarketplace",
        "source": "contracts/OpenMatrixMarketplace.sol",
        "constructor_args": lambda cfg: [cfg["neosafe_address"]],
    },
    {
        "name": "OpenMatrixStaking",
        "source": "contracts/OpenMatrixStaking.sol",
        "constructor_args": lambda cfg: [cfg["neosafe_address"]],
    },
    {
        "name": "OpenMatrixDAO",
        "source": "contracts/OpenMatrixDAO.sol",
        "constructor_args": lambda cfg: [cfg["neosafe_address"]],
    },
    {
        "name": "OpenMatrixInsurance",
        "source": "contracts/OpenMatrixInsurance.sol",
        "constructor_args": lambda cfg: [
            cfg["neosafe_address"],
            cfg.get("oracle_address", cfg["neosafe_address"]),
        ],
    },
    {
        "name": "OpenMatrixDEX",
        "source": "contracts/OpenMatrixDEX.sol",
        "constructor_args": lambda cfg: [cfg["neosafe_address"]],
    },
    {
        "name": "OpenMatrixNFT",
        "source": "contracts/OpenMatrixNFT.sol",
        "constructor_args": lambda cfg: [
            cfg["neosafe_address"],
            int(cfg.get("default_royalty_bps", 500)),  # 5%
            int(cfg.get("mint_price_wei", 0)),
        ],
    },
    {
        "name": "OpenMatrixDID",
        "source": "contracts/OpenMatrixDID.sol",
        "constructor_args": lambda cfg: [cfg["neosafe_address"]],
    },
]


# ---------------------------------------------------------------------------
# Solidity compilation helper (solcx / solc fallback)
# ---------------------------------------------------------------------------

def compile_contract(source_path: str, contract_name: str) -> tuple[list, str]:
    """
    Compile a Solidity file and return (abi, bytecode).

    Attempts to use py-solc-x first, then falls back to a pre-compiled
    artifact directory at ``artifacts/<ContractName>.json``.
    """
    artifacts_dir = PROJECT_ROOT / "artifacts"
    artifact_file = artifacts_dir / f"{contract_name}.json"

    # Check for pre-compiled artifact first
    if artifact_file.exists():
        logger.info("Using pre-compiled artifact: %s", artifact_file)
        with open(artifact_file) as f:
            artifact = json.load(f)
        return artifact["abi"], artifact["bytecode"]

    # Try solcx
    try:
        import solcx  # type: ignore[import-untyped]

        solcx.install_solc("0.8.20", show_progress=False)
        solcx.set_solc_version("0.8.20")

        source_full = PROJECT_ROOT / source_path
        with open(source_full) as f:
            source_code = f.read()

        # Resolve OpenZeppelin imports via node_modules or remappings
        import_remappings = []
        node_modules = PROJECT_ROOT / "node_modules"
        if node_modules.exists():
            import_remappings.append(
                f"@openzeppelin/={node_modules / '@openzeppelin'}/"
            )

        compiled = solcx.compile_source(
            source_code,
            output_values=["abi", "bin"],
            import_remappings=import_remappings or None,
            base_path=str(PROJECT_ROOT),
            allow_paths=[str(PROJECT_ROOT)],
        )

        # solcx keys are like "<source>:ContractName"
        key = None
        for k in compiled:
            if k.endswith(f":{contract_name}"):
                key = k
                break
        if key is None:
            raise RuntimeError(
                f"Contract {contract_name} not found in compiled output. "
                f"Keys: {list(compiled.keys())}"
            )

        abi = compiled[key]["abi"]
        bytecode = compiled[key]["bin"]
        if not bytecode.startswith("0x"):
            bytecode = "0x" + bytecode

        # Cache artifact
        artifacts_dir.mkdir(exist_ok=True)
        with open(artifact_file, "w") as f:
            json.dump({"abi": abi, "bytecode": bytecode}, f, indent=2)

        logger.info("Compiled %s via solcx", contract_name)
        return abi, bytecode

    except ImportError:
        pass

    # Fallback: try solc CLI
    try:
        source_full = PROJECT_ROOT / source_path
        result = subprocess.run(
            [
                "solc",
                "--combined-json",
                "abi,bin",
                "--base-path",
                str(PROJECT_ROOT),
                str(source_full),
            ],
            capture_output=True,
            text=True,
            check=True,
        )
        combined = json.loads(result.stdout)
        key = None
        for k in combined.get("contracts", {}):
            if k.endswith(f":{contract_name}"):
                key = k
                break
        if key is None:
            raise RuntimeError(f"Contract {contract_name} not found in solc output")

        entry = combined["contracts"][key]
        abi = json.loads(entry["abi"]) if isinstance(entry["abi"], str) else entry["abi"]
        bytecode = entry["bin"]
        if not bytecode.startswith("0x"):
            bytecode = "0x" + bytecode

        artifacts_dir.mkdir(exist_ok=True)
        with open(artifact_file, "w") as f:
            json.dump({"abi": abi, "bytecode": bytecode}, f, indent=2)

        logger.info("Compiled %s via solc CLI", contract_name)
        return abi, bytecode

    except (FileNotFoundError, subprocess.CalledProcessError) as exc:
        raise RuntimeError(
            f"Cannot compile {contract_name}: no solcx, no solc CLI, "
            f"and no pre-compiled artifact at {artifact_file}. "
            f"Place artifacts/<ContractName>.json or install py-solc-x / solc."
        ) from exc


# ---------------------------------------------------------------------------
# Load config
# ---------------------------------------------------------------------------

def load_config(config_path: str | None = None) -> dict:
    """
    Load deployment config from JSON file or environment variables.

    Environment variable overrides:
        OPENMATRIX_RPC_URL, OPENMATRIX_CHAIN_ID, OPENMATRIX_PRIVATE_KEY,
        OPENMATRIX_NEOSAFE_ADDRESS, OPENMATRIX_ORACLE_ADDRESS
    """
    config: dict[str, Any] = {}

    if config_path and Path(config_path).exists():
        with open(config_path) as f:
            config = json.load(f)

    # Environment overrides
    env_map = {
        "OPENMATRIX_RPC_URL": "rpc_url",
        "OPENMATRIX_CHAIN_ID": "chain_id",
        "OPENMATRIX_PRIVATE_KEY": "private_key",
        "OPENMATRIX_NEOSAFE_ADDRESS": "neosafe_address",
        "OPENMATRIX_ORACLE_ADDRESS": "oracle_address",
        "OPENMATRIX_EAS_SCHEMA_UID": "eas_schema_uid",
    }
    for env_key, cfg_key in env_map.items():
        val = os.environ.get(env_key)
        if val:
            config[cfg_key] = val

    # Defaults for Base Sepolia
    config.setdefault("rpc_url", "https://sepolia.base.org")
    config.setdefault("chain_id", 84532)

    # Validate required keys
    required = ("rpc_url", "chain_id", "private_key", "neosafe_address")
    missing = [k for k in required if k not in config]
    if missing:
        raise ValueError(
            f"Missing required config keys: {missing}. "
            "Set them in config JSON or via OPENMATRIX_* env vars."
        )

    return config


# ---------------------------------------------------------------------------
# Main deployment orchestrator
# ---------------------------------------------------------------------------

async def deploy_all(config: dict) -> dict:
    """
    Compile, deploy, and attest all platform contracts.

    Returns a deployment manifest dict.
    """
    deployer = ContractDeployer(config)
    manifest: dict[str, Any] = {
        "chain_id": int(config["chain_id"]),
        "deployer": deployer.deployer_address,
        "neosafe_address": config["neosafe_address"],
        "timestamp": int(time.time()),
        "contracts": {},
        "errors": [],
    }

    for entry in CONTRACTS:
        name = entry["name"]
        logger.info("=" * 60)
        logger.info("Processing %s", name)
        logger.info("=" * 60)

        try:
            # Compile
            abi, bytecode = compile_contract(entry["source"], name)

            # Build constructor args
            ctor_args = entry["constructor_args"](config)

            # Deploy
            result = await deployer.deploy(
                contract_name=name,
                abi=abi,
                bytecode=bytecode,
                constructor_args=ctor_args,
            )

            # Verify
            verification = await deployer.verify_deployment(result["contract_address"])

            manifest["contracts"][name] = {
                **result,
                "verification": verification,
                "abi_hash": hex(hash(json.dumps(abi, sort_keys=True)) & 0xFFFFFFFFFFFFFFFF),
            }

            logger.info(
                "OK: %s deployed at %s", name, result["contract_address"]
            )

        except Exception as exc:
            error_msg = f"{name}: {exc}"
            manifest["errors"].append(error_msg)
            logger.exception("FAILED: %s", name)

    # Verify NeoSafe revenue routing is set up
    try:
        neosafe_status = await verify_revenue_route(config)
        manifest["neosafe_status"] = neosafe_status
    except Exception as exc:
        manifest["neosafe_status"] = {"error": str(exc)}

    # Attest the full deployment manifest
    try:
        att = await attest_action(
            config=config,
            action_type="platform_deployment",
            data={
                "contracts_deployed": len(manifest["contracts"]),
                "errors": len(manifest["errors"]),
                "deployer": deployer.deployer_address,
                "chain_id": int(config["chain_id"]),
            },
            recipient=config["neosafe_address"],
        )
        manifest["deployment_attestation"] = att
    except Exception as exc:
        manifest["deployment_attestation"] = {"error": str(exc)}

    return manifest


# ---------------------------------------------------------------------------
# CLI entry point
# ---------------------------------------------------------------------------

async def main() -> None:
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
    )

    config_path = sys.argv[1] if len(sys.argv) > 1 else None
    config = load_config(config_path)

    logger.info("Starting full platform deployment to chain %s", config["chain_id"])
    manifest = await deploy_all(config)

    # Write manifest
    output_path = PROJECT_ROOT / "deployment_manifest.json"
    with open(output_path, "w") as f:
        json.dump(manifest, f, indent=2, default=str)

    logger.info("Deployment manifest written to %s", output_path)

    # Summary
    deployed = len(manifest["contracts"])
    errors = len(manifest["errors"])
    logger.info("=" * 60)
    logger.info("DEPLOYMENT COMPLETE: %d deployed, %d errors", deployed, errors)
    logger.info("=" * 60)

    if errors:
        for err in manifest["errors"]:
            logger.error("  - %s", err)
        sys.exit(1)


if __name__ == "__main__":
    asyncio.run(main())
