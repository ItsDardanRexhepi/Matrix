"""
Audit Contract — runs Glasswing security audit on Solidity source code.

Performs a 12-point vulnerability scan covering SWC Registry patterns,
access control, front-running, and gas optimization issues.
"""

SKILL_NAME = "audit_contract"
SKILL_DESCRIPTION = (
    "Run a Glasswing security audit on Solidity smart contract source code. "
    "Checks for reentrancy, unchecked calls, tx.origin, selfdestruct, "
    "integer overflow, access control gaps, front-running, and more. "
    "Use when the user wants to audit or scan a contract for vulnerabilities."
)
SKILL_PARAMETERS = {
    "type": "object",
    "properties": {
        "source_code": {
            "type": "string",
            "description": "The Solidity source code to audit.",
        },
        "contract_name": {
            "type": "string",
            "description": "Name of the contract being audited.",
        },
    },
    "required": ["source_code"],
}


async def execute(source_code: str = "", contract_name: str = "Unknown", **kwargs) -> str:
    """Execute the security audit."""
    if not source_code.strip():
        return "No source code provided. Please provide Solidity code to audit."

    try:
        from runtime.security.audit import ContractAuditor

        config = kwargs.get("config", {})
        auditor = ContractAuditor(config)
        report = auditor.audit(source_code)

        lines = [f"## Glasswing Security Audit: {contract_name}\n"]
        lines.append(f"**Status**: {'BLOCKED' if not report.passed else 'PASSED'}")
        lines.append(f"**Findings**: {len(report.findings)}\n")

        if not report.findings:
            lines.append("No vulnerabilities detected. Contract is clean.")
        else:
            for f in report.findings:
                severity_icon = {
                    "CRITICAL": "🔴",
                    "HIGH": "🟠",
                    "MEDIUM": "🟡",
                    "LOW": "🔵",
                    "INFO": "⚪",
                }.get(f.severity.name, "⚪")
                lines.append(
                    f"- {severity_icon} **{f.severity.name}** [{f.check_id}]: "
                    f"{f.title} (line {f.line})"
                )
                lines.append(f"  {f.description}")

        if not report.passed:
            lines.append(
                "\n**Deployment blocked.** Critical vulnerabilities must be "
                "resolved before this contract can be deployed."
            )

        return "\n".join(lines)
    except Exception as e:
        return f"Audit failed: {e}"
