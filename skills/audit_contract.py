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
        report = auditor.audit(source_code, contract_name)
    except Exception as e:
        return f"Audit failed: {e}"

    # The report's own three-way verdict, not `passed` alone: a source with no
    # function body comes back `passed: False` with no findings, and reading
    # only the bool printed "Contract is clean" under a BLOCKED status.
    verdict = report.to_dict()["verdict"]
    status = {"passed": "PASSED", "failed": "BLOCKED",
              "not_auditable": "NOT AUDITABLE"}[verdict]

    lines = [f"## Glasswing Security Audit: {contract_name}\n"]
    lines.append(f"**Status**: {status}")
    lines.append(f"**Findings**: {len(report.findings)}\n")

    for f in report.findings:
        severity_icon = {
            "CRITICAL": "🔴",
            "HIGH": "🟠",
            "MEDIUM": "🟡",
            "LOW": "🔵",
            "INFO": "⚪",
        }.get(f.severity.name, "⚪")
        # `rule_id` is the Finding's field. This read `check_id`, which Finding
        # has never had, so every contract with a finding came back as
        # "Audit failed: 'Finding' object has no attribute 'check_id'".
        where = f" (line {f.line})" if f.line is not None else ""
        lines.append(
            f"- {severity_icon} **{f.severity.name}** [{f.rule_id}]: {f.title}{where}"
        )
        lines.append(f"  {f.description}")

    # The auditor's summary says which it was: clean, findings, or nothing
    # that could be judged.
    lines.append(("\n" if report.findings else "") + report.summary)

    if not report.passed:
        # The agent's deploy tool is not implemented and nothing deploys the
        # source audited here, so this is advice to whoever will.
        lines.append(
            "\n**Do not deploy this contract yet.** It has not passed the audit; "
            "the summary above says why."
        )

    return "\n".join(lines)
