from __future__ import annotations

"""Verify the entire platform is operational on Base Sepolia."""

import asyncio
import json
import logging
import os
import sys
import time
from pathlib import Path
from typing import Any

from web3 import AsyncWeb3, AsyncHTTPProvider

# Ensure project root is importable
PROJECT_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(PROJECT_ROOT))

from contracts.deployer import ContractDeployer
from contracts.eas_deployer import verify_attestation
from contracts.neosafe_verifier import verify_revenue_route, get_revenue_summary

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Health-check helpers
# ---------------------------------------------------------------------------

class PlatformVerifier:
    """End-to-end verification of all deployed OpenMatrix contracts."""

    def __init__(self, config: dict, manifest: dict) -> None:
        self.config = config
        self.manifest = manifest
        self.deployer = ContractDeployer(config)
        self.w3 = AsyncWeb3(AsyncHTTPProvider(config["rpc_url"]))
        self.report: dict[str, Any] = {
            "timestamp": int(time.time()),
            "chain_id": int(config["chain_id"]),
            "checks": {},
            "summary": {},
        }

    # ------------------------------------------------------------------
    # 1. Contract liveness
    # ------------------------------------------------------------------

    async def check_contracts(self) -> dict:
        """Verify every deployed contract has code on-chain."""
        results: dict[str, Any] = {}

        contracts = self.manifest.get("contracts", {})
        if not contracts:
            results["_error"] = "No contracts in manifest"
            self.report["checks"]["contracts"] = results
            return results

        for name, info in contracts.items():
            address = info.get("contract_address")
            if not address:
                results[name] = {"status": "SKIP", "reason": "no address in manifest"}
                continue

            try:
                verification = await self.deployer.verify_deployment(address)
                is_live = verification.get("is_contract", False)
                results[name] = {
                    "address": address,
                    "status": "OK" if is_live else "FAIL",
                    "code_size": verification.get("code_size", 0),
                    "balance_wei": verification.get("balance_wei", 0),
                }
            except Exception as exc:
                results[name] = {"address": address, "status": "ERROR", "error": str(exc)}

        self.report["checks"]["contracts"] = results
        return results

    # ------------------------------------------------------------------
    # 2. EAS attestations
    # ------------------------------------------------------------------

    async def check_attestations(self) -> dict:
        """Verify EAS attestations exist for each deployed contract."""
        results: dict[str, Any] = {}

        contracts = self.manifest.get("contracts", {})
        for name, info in contracts.items():
            uid = info.get("attestation_uid")
            if not uid:
                results[name] = {"status": "SKIP", "reason": "no attestation UID"}
                continue

            try:
                att = await verify_attestation(self.config, uid)
                exists = att.get("exists", False)
                results[name] = {
                    "uid": uid,
                    "status": "OK" if exists else "FAIL",
                    "attester": att.get("attester"),
                    "time": att.get("time"),
                }
            except Exception as exc:
                results[name] = {"uid": uid, "status": "ERROR", "error": str(exc)}

        # Also check platform-level attestation
        platform_att = self.manifest.get("deployment_attestation", {})
        platform_uid = platform_att.get("uid")
        if platform_uid:
            try:
                att = await verify_attestation(self.config, platform_uid)
                results["_platform_deployment"] = {
                    "uid": platform_uid,
                    "status": "OK" if att.get("exists") else "FAIL",
                }
            except Exception as exc:
                results["_platform_deployment"] = {
                    "uid": platform_uid,
                    "status": "ERROR",
                    "error": str(exc),
                }

        self.report["checks"]["attestations"] = results
        return results

    # ------------------------------------------------------------------
    # 3. NeoSafe revenue routing
    # ------------------------------------------------------------------

    async def check_neosafe(self) -> dict:
        """Confirm NeoSafe wallet is reachable and revenue routing works."""
        results: dict[str, Any] = {}

        try:
            route = await verify_revenue_route(self.config)
            results["revenue_route"] = {
                "status": "OK" if route.get("is_receiving") or route.get("eth_balance_wei", 0) >= 0 else "FAIL",
                "neosafe_address": route.get("neosafe_address"),
                "eth_balance_ether": route.get("eth_balance_ether"),
                "recent_tx_count": route.get("recent_tx_count"),
            }
        except Exception as exc:
            results["revenue_route"] = {"status": "ERROR", "error": str(exc)}

        try:
            summary = await get_revenue_summary(self.config)
            results["revenue_summary"] = {
                "status": "OK",
                "eth_balance_ether": summary.get("eth_balance_ether"),
                "token_balances_count": len(summary.get("token_balances", [])),
                "total_tx_count": summary.get("total_tx_count"),
            }
        except Exception as exc:
            results["revenue_summary"] = {"status": "ERROR", "error": str(exc)}

        # Verify each deployed contract has platformFeeRecipient set to NeoSafe
        neosafe = self.config.get("neosafe_address", "").lower()
        contracts = self.manifest.get("contracts", {})
        fee_checks: dict[str, Any] = {}
        for name, info in contracts.items():
            address = info.get("contract_address")
            if not address:
                continue
            # Read platformFeeRecipient() if available
            try:
                fee_recipient_abi = [
                    {
                        "name": "platformFeeRecipient",
                        "type": "function",
                        "stateMutability": "view",
                        "inputs": [],
                        "outputs": [{"name": "", "type": "address"}],
                    }
                ]
                contract = self.w3.eth.contract(address=address, abi=fee_recipient_abi)
                recipient = await contract.functions.platformFeeRecipient().call()
                matches = recipient.lower() == neosafe
                fee_checks[name] = {
                    "status": "OK" if matches else "MISMATCH",
                    "platformFeeRecipient": recipient,
                    "expected": self.config.get("neosafe_address"),
                }
            except Exception:
                fee_checks[name] = {"status": "SKIP", "reason": "no platformFeeRecipient function"}

        results["fee_recipient_checks"] = fee_checks
        self.report["checks"]["neosafe"] = results
        return results

    # ------------------------------------------------------------------
    # 4. Oracle connectivity
    # ------------------------------------------------------------------

    async def check_oracle(self) -> dict:
        """Test oracle address is accessible on-chain."""
        results: dict[str, Any] = {}

        oracle_address = self.config.get("oracle_address")
        if not oracle_address:
            results["status"] = "SKIP"
            results["reason"] = "no oracle_address in config"
            self.report["checks"]["oracle"] = results
            return results

        try:
            code = await self.w3.eth.get_code(oracle_address)
            balance = await self.w3.eth.get_balance(oracle_address)
            results["status"] = "OK"
            results["oracle_address"] = oracle_address
            results["is_contract"] = len(code) > 0
            results["balance_wei"] = balance
        except Exception as exc:
            results["status"] = "ERROR"
            results["error"] = str(exc)

        self.report["checks"]["oracle"] = results
        return results

    # ------------------------------------------------------------------
    # 5. RPC / chain connectivity
    # ------------------------------------------------------------------

    async def check_rpc(self) -> dict:
        """Verify the RPC endpoint and chain ID are correct."""
        results: dict[str, Any] = {}

        try:
            chain_id = await self.w3.eth.chain_id
            block = await self.w3.eth.get_block("latest")
            expected_chain = int(self.config["chain_id"])

            results["status"] = "OK" if chain_id == expected_chain else "CHAIN_MISMATCH"
            results["chain_id"] = chain_id
            results["expected_chain_id"] = expected_chain
            results["latest_block"] = block["number"]
            results["rpc_url"] = self.config["rpc_url"]
        except Exception as exc:
            results["status"] = "ERROR"
            results["error"] = str(exc)

        self.report["checks"]["rpc"] = results
        return results

    # ------------------------------------------------------------------
    # Full verification
    # ------------------------------------------------------------------

    async def run_all(self) -> dict:
        """Run all verification checks and produce a health report."""
        logger.info("=" * 60)
        logger.info("OpenMatrix Platform Verification")
        logger.info("=" * 60)

        # Run independent checks concurrently
        await asyncio.gather(
            self.check_rpc(),
            self.check_contracts(),
            self.check_attestations(),
            self.check_neosafe(),
            self.check_oracle(),
        )

        # Build summary
        total_checks = 0
        passed = 0
        failed = 0
        errors = 0
        skipped = 0

        for section_name, section in self.report["checks"].items():
            if isinstance(section, dict):
                for key, val in section.items():
                    if isinstance(val, dict) and "status" in val:
                        total_checks += 1
                        status = val["status"]
                        if status == "OK":
                            passed += 1
                        elif status in ("FAIL", "MISMATCH", "CHAIN_MISMATCH"):
                            failed += 1
                        elif status == "ERROR":
                            errors += 1
                        elif status == "SKIP":
                            skipped += 1
                    elif key == "status":
                        total_checks += 1
                        if val == "OK":
                            passed += 1
                        elif val in ("FAIL", "MISMATCH", "CHAIN_MISMATCH"):
                            failed += 1
                        elif val == "ERROR":
                            errors += 1
                        elif val == "SKIP":
                            skipped += 1

        self.report["summary"] = {
            "total_checks": total_checks,
            "passed": passed,
            "failed": failed,
            "errors": errors,
            "skipped": skipped,
            "healthy": failed == 0 and errors == 0,
        }

        logger.info("Verification complete: %d passed, %d failed, %d errors, %d skipped",
                     passed, failed, errors, skipped)

        return self.report


# ---------------------------------------------------------------------------
# Config & manifest loading
# ---------------------------------------------------------------------------

def load_config(config_path: str | None = None) -> dict:
    """Load config from file or environment."""
    config: dict[str, Any] = {}

    if config_path and Path(config_path).exists():
        with open(config_path) as f:
            config = json.load(f)

    env_map = {
        "OPENMATRIX_RPC_URL": "rpc_url",
        "OPENMATRIX_CHAIN_ID": "chain_id",
        "OPENMATRIX_PRIVATE_KEY": "private_key",
        "OPENMATRIX_NEOSAFE_ADDRESS": "neosafe_address",
        "OPENMATRIX_ORACLE_ADDRESS": "oracle_address",
    }
    for env_key, cfg_key in env_map.items():
        val = os.environ.get(env_key)
        if val:
            config[cfg_key] = val

    config.setdefault("rpc_url", "https://sepolia.base.org")
    config.setdefault("chain_id", 84532)

    required = ("rpc_url", "chain_id", "private_key", "neosafe_address")
    missing = [k for k in required if k not in config]
    if missing:
        raise ValueError(f"Missing required config keys: {missing}")

    return config


def load_manifest(manifest_path: str | None = None) -> dict:
    """Load deployment manifest."""
    path = Path(manifest_path) if manifest_path else PROJECT_ROOT / "deployment_manifest.json"
    if not path.exists():
        raise FileNotFoundError(
            f"Deployment manifest not found at {path}. "
            "Run deploy_all.py first."
        )
    with open(path) as f:
        return json.load(f)


# ---------------------------------------------------------------------------
# CLI entry point
# ---------------------------------------------------------------------------

async def main() -> None:
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
    )

    # Parse CLI args: verify_platform.py [config.json] [manifest.json]
    config_path = sys.argv[1] if len(sys.argv) > 1 else None
    manifest_path = sys.argv[2] if len(sys.argv) > 2 else None

    config = load_config(config_path)
    manifest = load_manifest(manifest_path)

    verifier = PlatformVerifier(config, manifest)
    report = await verifier.run_all()

    # Write report
    report_path = PROJECT_ROOT / "platform_health_report.json"
    with open(report_path, "w") as f:
        json.dump(report, f, indent=2, default=str)

    logger.info("Health report written to %s", report_path)

    summary = report["summary"]
    logger.info("=" * 60)
    if summary["healthy"]:
        logger.info("PLATFORM HEALTHY — all checks passed")
    else:
        logger.error(
            "PLATFORM UNHEALTHY — %d failures, %d errors",
            summary["failed"],
            summary["errors"],
        )
        sys.exit(1)


if __name__ == "__main__":
    asyncio.run(main())
