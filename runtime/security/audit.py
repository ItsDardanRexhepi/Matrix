"""
Contract Security Auditor — static analysis for generated Solidity.

Scans every contract before deployment for known vulnerability patterns.
Integrated into the contract conversion pipeline (Step 6) and the
SmartContracts deploy action. Morpheus surfaces audit findings to the user.

Vulnerability categories based on SWC Registry and common exploit patterns.
Glasswing-grade checks: reentrancy, unchecked calls, tx.origin, selfdestruct,
delegatecall, unbounded loops, integer overflow, floating pragma, locked ether,
missing access control, front-running, and timestamp dependence.
"""

from __future__ import annotations

import logging
import re
from dataclasses import dataclass, field
from enum import Enum
from typing import Any

logger = logging.getLogger(__name__)


class Severity(Enum):
    CRITICAL = "critical"
    HIGH = "high"
    MEDIUM = "medium"
    LOW = "low"
    INFO = "info"


@dataclass
class Finding:
    rule_id: str
    severity: Severity
    title: str
    description: str
    line: int | None = None
    snippet: str = ""

    def to_dict(self) -> dict[str, Any]:
        return {
            "rule_id": self.rule_id,
            "severity": self.severity.value,
            "title": self.title,
            "description": self.description,
            "line": self.line,
            "snippet": self.snippet,
        }


@dataclass
class AuditReport:
    contract_name: str
    findings: list[Finding] = field(default_factory=list)
    passed: bool = True
    summary: str = ""

    def to_dict(self) -> dict[str, Any]:
        return {
            "contract_name": self.contract_name,
            "passed": self.passed,
            "finding_count": len(self.findings),
            "critical_count": sum(1 for f in self.findings if f.severity == Severity.CRITICAL),
            "high_count": sum(1 for f in self.findings if f.severity == Severity.HIGH),
            "medium_count": sum(1 for f in self.findings if f.severity == Severity.MEDIUM),
            "findings": [f.to_dict() for f in self.findings],
            "summary": self.summary,
        }


class ContractAuditor:
    """Static security auditor for Solidity source code.

    Runs pattern-based checks against known vulnerability classes.
    Does not require network access or external services.
    """

    def __init__(self, config: dict | None = None) -> None:
        config = config or {}
        sec_cfg = config.get("security", {})
        self._block_critical: bool = sec_cfg.get("block_on_critical", True)
        self._block_high: bool = sec_cfg.get("block_on_high", False)

    def audit(self, source: str, contract_name: str = "") -> AuditReport:
        report = AuditReport(contract_name=contract_name or "unknown")
        lines = source.splitlines()

        checks = [
            self._check_reentrancy,
            self._check_unchecked_call,
            self._check_tx_origin,
            self._check_selfdestruct,
            self._check_delegatecall,
            self._check_unbounded_loop,
            self._check_integer_overflow,
            self._check_floating_pragma,
            self._check_unprotected_ether,
            self._check_missing_access_control,
            self._check_front_running,
            self._check_timestamp_dependence,
        ]

        for check in checks:
            findings = check(source, lines)
            report.findings.extend(findings)

        critical = sum(1 for f in report.findings if f.severity == Severity.CRITICAL)
        high = sum(1 for f in report.findings if f.severity == Severity.HIGH)

        if self._block_critical and critical > 0:
            report.passed = False
        if self._block_high and high > 0:
            report.passed = False

        if not report.findings:
            report.summary = "No vulnerabilities detected. Contract passed all security checks."
        else:
            report.summary = (
                f"Found {len(report.findings)} issue(s): "
                f"{critical} critical, {high} high, "
                f"{sum(1 for f in report.findings if f.severity == Severity.MEDIUM)} medium, "
                f"{sum(1 for f in report.findings if f.severity == Severity.LOW)} low."
            )

        logger.info("Audit complete: contract=%s passed=%s findings=%d",
                     report.contract_name, report.passed, len(report.findings))
        return report

    def should_block(self, report: AuditReport) -> bool:
        return not report.passed

    # ── Vulnerability checks ─────────────────────────────────────────

    @staticmethod
    def _check_reentrancy(source: str, lines: list[str]) -> list[Finding]:
        findings = []
        call_pattern = re.compile(r'\.(call|send|transfer)\s*[\({]')
        state_pattern = re.compile(r'(\w+\s*[\[\]]*\s*[-+]?=|balances?\[)')
        in_function = False
        call_line = None
        func_name = ""
        for i, line in enumerate(lines, 1):
            stripped = line.strip()
            if stripped.startswith("function "):
                in_function = True
                call_line = None
                func_name = stripped.split("(")[0].replace("function ", "")
            if in_function and call_pattern.search(stripped):
                call_line = i
            if call_line and state_pattern.search(stripped) and i > call_line:
                findings.append(Finding(
                    rule_id="SWC-107",
                    severity=Severity.CRITICAL,
                    title="Reentrancy vulnerability",
                    description=(
                        f"State modification after external call in '{func_name}'. "
                        "Apply checks-effects-interactions pattern or use ReentrancyGuard."
                    ),
                    line=call_line,
                    snippet=lines[call_line - 1].strip() if call_line <= len(lines) else "",
                ))
                call_line = None
        return findings

    @staticmethod
    def _check_unchecked_call(source: str, lines: list[str]) -> list[Finding]:
        findings = []
        for i, line in enumerate(lines, 1):
            stripped = line.strip()
            if ".call{" in stripped or ".call(" in stripped:
                if not re.match(r'\s*\(?\s*bool\s+\w+', stripped) and "require" not in stripped:
                    if "=" not in stripped.split(".call")[0] or "(bool" not in stripped:
                        findings.append(Finding(
                            rule_id="SWC-104",
                            severity=Severity.HIGH,
                            title="Unchecked external call",
                            description="Return value of .call() is not checked. Capture the bool and require success.",
                            line=i, snippet=stripped,
                        ))
        return findings

    @staticmethod
    def _check_tx_origin(source: str, lines: list[str]) -> list[Finding]:
        findings = []
        for i, line in enumerate(lines, 1):
            if "tx.origin" in line:
                findings.append(Finding(
                    rule_id="SWC-115", severity=Severity.HIGH,
                    title="tx.origin used for authorization",
                    description="tx.origin can be exploited via phishing contracts. Use msg.sender instead.",
                    line=i, snippet=line.strip(),
                ))
        return findings

    @staticmethod
    def _check_selfdestruct(source: str, lines: list[str]) -> list[Finding]:
        findings = []
        for i, line in enumerate(lines, 1):
            if "selfdestruct(" in line:
                context = "\n".join(lines[max(0, i - 5):i])
                if "onlyOwner" not in context and "require(" not in context and "msg.sender ==" not in context:
                    findings.append(Finding(
                        rule_id="SWC-106", severity=Severity.CRITICAL,
                        title="Unprotected selfdestruct",
                        description="selfdestruct without access control. Anyone can destroy this contract.",
                        line=i, snippet=line.strip(),
                    ))
        return findings

    @staticmethod
    def _check_delegatecall(source: str, lines: list[str]) -> list[Finding]:
        findings = []
        for i, line in enumerate(lines, 1):
            if "delegatecall(" in line:
                findings.append(Finding(
                    rule_id="SWC-112", severity=Severity.HIGH,
                    title="Delegatecall usage detected",
                    description="delegatecall executes in this contract's storage context. Ensure the target is trusted.",
                    line=i, snippet=line.strip(),
                ))
        return findings

    @staticmethod
    def _check_unbounded_loop(source: str, lines: list[str]) -> list[Finding]:
        findings = []
        for i, line in enumerate(lines, 1):
            if re.search(r'for\s*\(.+\.length', line.strip()):
                findings.append(Finding(
                    rule_id="GAS-001", severity=Severity.MEDIUM,
                    title="Unbounded loop over dynamic array",
                    description="Can exhaust gas if array grows large. Consider pagination.",
                    line=i, snippet=line.strip(),
                ))
        return findings

    @staticmethod
    def _check_integer_overflow(source: str, lines: list[str]) -> list[Finding]:
        findings = []
        pragma_match = re.search(r'pragma solidity\s+[\^~>=<]*\s*(0\.\d+\.\d+)', source)
        if pragma_match:
            version = pragma_match.group(1)
            _, minor, _ = version.split(".")
            if int(minor) < 8 and "SafeMath" not in source:
                findings.append(Finding(
                    rule_id="SWC-101", severity=Severity.HIGH,
                    title="Integer overflow possible (Solidity < 0.8.0)",
                    description=f"Pragma {version} lacks built-in overflow checks. Use SafeMath or upgrade.",
                    line=1, snippet=f"pragma solidity {version}",
                ))
        return findings

    @staticmethod
    def _check_floating_pragma(source: str, lines: list[str]) -> list[Finding]:
        findings = []
        for i, line in enumerate(lines, 1):
            if re.match(r'\s*pragma solidity\s*\^', line):
                findings.append(Finding(
                    rule_id="SWC-103", severity=Severity.LOW,
                    title="Floating pragma version",
                    description="Using ^ allows future breaking versions. Pin for production.",
                    line=i, snippet=line.strip(),
                ))
        return findings

    @staticmethod
    def _check_unprotected_ether(source: str, lines: list[str]) -> list[Finding]:
        findings = []
        has_payable = bool(re.search(r'\bpayable\b', source))
        has_withdraw = bool(re.search(r'function\s+withdraw', source, re.IGNORECASE))
        has_transfer = bool(re.search(r'\.(transfer|send|call\{value)', source))
        if has_payable and not has_withdraw and not has_transfer:
            findings.append(Finding(
                rule_id="SWC-105", severity=Severity.HIGH,
                title="ETH can be received but not withdrawn",
                description="Contract accepts ETH but has no withdrawal mechanism. Funds will be locked.",
            ))
        return findings

    @staticmethod
    def _check_missing_access_control(source: str, lines: list[str]) -> list[Finding]:
        findings = []
        sensitive = [
            (r'function\s+mint\s*\(', "mint"),
            (r'function\s+burn\s*\(', "burn"),
            (r'function\s+pause\s*\(', "pause"),
            (r'function\s+unpause\s*\(', "unpause"),
            (r'function\s+upgrade\s*\(', "upgrade"),
            (r'function\s+setOwner\s*\(', "setOwner"),
            (r'function\s+transferOwnership\s*\(', "transferOwnership"),
        ]
        for pattern, func_name in sensitive:
            for m in re.finditer(pattern, source):
                start = m.start()
                sig_block = source[start:start + 300]
                brace = sig_block.find("{")
                if brace == -1:
                    continue
                sig = sig_block[:brace]
                if "onlyOwner" not in sig and "onlyRole" not in sig and "require(msg.sender" not in sig:
                    line_num = source[:start].count("\n") + 1
                    findings.append(Finding(
                        rule_id="AC-001", severity=Severity.HIGH,
                        title=f"Missing access control on {func_name}()",
                        description=f"{func_name}() can be called by anyone. Add access control.",
                        line=line_num, snippet=sig.strip()[:80],
                    ))
        return findings

    @staticmethod
    def _check_front_running(source: str, lines: list[str]) -> list[Finding]:
        findings = []
        for i, line in enumerate(lines, 1):
            if re.search(r'function\s+(swap|trade|buy|sell|exchange)\s*\(', line.strip(), re.IGNORECASE):
                func_body = "\n".join(lines[i:min(i + 30, len(lines))])
                if "minAmount" not in func_body and "slippage" not in func_body.lower() and "deadline" not in func_body.lower():
                    findings.append(Finding(
                        rule_id="FR-001", severity=Severity.MEDIUM,
                        title="Potential front-running vulnerability",
                        description="Swap/trade without slippage protection or deadline. Add minAmountOut and deadline.",
                        line=i, snippet=line.strip(),
                    ))
        return findings

    @staticmethod
    def _check_timestamp_dependence(source: str, lines: list[str]) -> list[Finding]:
        findings = []
        for i, line in enumerate(lines, 1):
            if "block.timestamp" in line:
                stripped = line.strip()
                if any(op in stripped for op in ["<", ">", "==", ">=", "<="]):
                    findings.append(Finding(
                        rule_id="SWC-116", severity=Severity.LOW,
                        title="Block timestamp used in comparison",
                        description="block.timestamp can be manipulated by miners within ~15 seconds.",
                        line=i, snippet=stripped,
                    ))
        return findings
