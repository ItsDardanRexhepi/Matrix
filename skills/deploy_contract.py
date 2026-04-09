from __future__ import annotations

"""
Deploy Contract — compiles and deploys a Solidity contract with full audit pipeline.

Runs security audit, gas estimation, and deployment through the
Glasswing-protected pipeline. Critical vulnerabilities block deployment.
"""

SKILL_NAME = "deploy_contract"
SKILL_DESCRIPTION = (
    "Compile and deploy a Solidity smart contract. Runs a full Glasswing "
    "security audit before deployment. Critical findings block the deploy. "
    "Use when the user wants to deploy a contract to the blockchain."
)
SKILL_PARAMETERS = {
    "type": "object",
    "properties": {
        "source_code": {
            "type": "string",
            "description": "The Solidity source code to compile and deploy.",
        },
        "contract_name": {
            "type": "string",
            "description": "Name of the contract to deploy.",
        },
        "constructor_args": {
            "type": "array",
            "description": "Constructor arguments for the contract.",
            "items": {},
        },
        "network": {
            "type": "string",
            "description": "Target network (e.g. 'base-sepolia', 'base'). Defaults to configured network.",
        },
    },
    "required": ["source_code", "contract_name"],
}


async def execute(
    source_code: str = "",
    contract_name: str = "",
    constructor_args: list | None = None,
    network: str = "",
    **kwargs,
) -> str:
    """Execute the full deploy pipeline."""
    if not source_code.strip() or not contract_name:
        return "Both source_code and contract_name are required."

    try:
        from runtime.security.audit import ContractAuditor
        from runtime.blockchain.smart_contracts import SmartContractManager

        config = kwargs.get("config", {})

        # Step 1: Audit
        auditor = ContractAuditor(config)
        report = auditor.audit(source_code)

        if not report.passed:
            critical = [f for f in report.findings if f.severity.name == "CRITICAL"]
            return (
                f"**Deployment BLOCKED** by Glasswing audit.\n\n"
                f"{len(critical)} critical vulnerabilities found:\n"
                + "\n".join(f"- [{f.check_id}] {f.title}: {f.description}" for f in critical)
                + "\n\nResolve all critical findings before deploying."
            )

        # Step 2: Compile and deploy
        manager = SmartContractManager(config)
        result = await manager.deploy(
            source_code=source_code,
            contract_name=contract_name,
            constructor_args=constructor_args or [],
        )

        if result.get("status") == "blocked":
            return f"Deployment blocked: {result.get('reason', 'unknown')}"

        return (
            f"**Contract Deployed Successfully**\n\n"
            f"- **Contract**: {contract_name}\n"
            f"- **Address**: `{result.get('address', 'pending')}`\n"
            f"- **Transaction**: `{result.get('tx_hash', 'pending')}`\n"
            f"- **Network**: {network or 'default'}\n"
            f"- **Gas Used**: {result.get('gas_used', 'N/A')}\n"
            f"- **Audit**: PASSED ({len(report.findings)} non-critical findings)\n"
        )
    except Exception as e:
        return f"Deployment failed: {e}"
