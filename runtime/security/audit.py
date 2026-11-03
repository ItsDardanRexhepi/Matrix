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
    #: Was there anything here this auditor could actually judge?
    #:
    #: §CT — a zero has more than one cause. "No findings" conflated two very
    #: different states: the contract was examined and is clean, and there was
    #: no executable logic to examine. Nine of the twelve checks in this class
    #: are about RUNTIME BEHAVIOUR (reentrancy, unchecked calls, delegatecall,
    #: ether handling); the other three read a pragma, a declaration or a
    #: signature, and still report on a source with no body. So a source with
    #: no function bodies produces zero behavioural findings, and used to come
    #: back
    #: `passed: true, "No vulnerabilities detected. Contract passed all
    #: security checks."` — an all-clear on an artifact nobody could judge.
    #:
    #: RUN-3 fixed this in the conversion service. It stayed true on the
    #: model-callable `security_audit` tool, on the Glasswing pre-action gate,
    #: and on the deploy gate, because each read the raw report. Putting the
    #: distinction in the report itself is what reaches all of them: `passed`
    #: is False when nothing was auditable, so `should_block` — which every one
    #: of those consumers already calls — blocks instead of certifying. The
    #: Glasswing gate holds that block for a call that deploys or signs; a
    #: compile or an audit of such a source deploys nothing and gets the
    #: report instead (runtime/protocols/integration.py).
    auditable: bool = True

    def to_dict(self) -> dict[str, Any]:
        return {
            "contract_name": self.contract_name,
            "passed": self.passed,
            "auditable": self.auditable,
            # An explicit three-state verdict, so a consumer that renders a
            # string cannot turn "could not judge" into "passed" by reading a
            # bool. §DL.4: never classify on a field the dangerous value is not
            # in — `passed: false` alone does not say WHY.
            "verdict": ("passed" if (self.auditable and self.passed)
                        else "not_auditable" if not self.auditable
                        else "failed"),
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
        sec_cfg = config.get("security")
        # A bare `security:` YAML key is None; read it as "no overrides" (the
        # blocking defaults below), not as a constructor fault.
        if not isinstance(sec_cfg, dict):
            sec_cfg = {}
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

        # §CT — qualify the zero, do not skip the work.
        #
        # A first draft of this returned early when there was no executable
        # logic, on the reasoning that every check examines runtime behaviour.
        # That was wrong for three of the twelve: floating pragma reads the
        # pragma line, locked ether reads payable/withdraw declarations, and
        # missing access control reads a function SIGNATURE. All three fire on
        # sources with no function body at all, and the early return threw
        # their findings away — tests/test_audit.py caught it on three fixtures
        # that are exactly those shapes.
        #
        # So the checks always run, and what changes is the meaning of an empty
        # result: on a source with no executable body, zero findings is "there
        # was nothing to examine", never an all-clear.
        report.auditable = self.has_executable_logic(source)
        if not report.auditable:
            report.passed = False

        if not report.auditable:
            found = (f" {len(report.findings)} structural issue(s) were still found."
                     if report.findings else "")
            report.summary = (
                "Not auditable: this source declares no executable function "
                "body, so the behavioural checks had nothing to examine. This "
                "is NOT an all-clear." + found
            )
        elif not report.findings:
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
        """Block on a failed audit AND on one that could not be performed.

        `passed` is already False in the unauditable case, so this reads the
        same as before — deliberately, because every existing consumer calls
        this and none of them had to change.
        """
        return not report.passed

    # ── is there anything here to judge? ─────────────────────────────

    _DECL = re.compile(r"\b(?:function|constructor|fallback|receive)\b")

    @classmethod
    def has_executable_logic(cls, source: str) -> bool:
        """Does this source declare at least one function with a real body?

        Deliberately source-level: the conversion service answers the same
        question from a parsed IR, but the tool, the gate and the deploy path
        all hold raw text and have no IR to consult.

        An interface, a bare struct, a constants-only library or an empty
        string all answer False — correctly. They are not "safe"; they are
        artifacts the BEHAVIOURAL checks say nothing about. The structural
        checks still run over them and their findings are still reported.

        Read on the code alone (``_code_only``): a comment, and the inside of a
        string literal, are not code, so a ``"//"`` in a string does not erase
        what follows it and a string that spells a function is not one. One
        pass over the source, whatever it holds (``_bodies``).
        """
        return any(body for _m, body in cls._bodies(source, cls._DECL))

    _FUNCTION_NAME = re.compile(r"\bfunction\s+(\w+)\s*\(")

    @classmethod
    def implemented_functions(cls, source: str) -> set[str]:
        """Names of the `function`s this source declares WITH a real body.

        The same brace rule as has_executable_logic, per function, so "this
        function is implemented" and "this source is auditable" can never be
        answered by two different readings of the same text. An overloaded name
        counts as implemented if any of its overloads has a body.
        """
        return {m.group(1) for m, body in cls._bodies(source, cls._FUNCTION_NAME) if body}

    # A comment, or a string literal with its escapes, in one alternation: the
    # scanner takes whichever starts first, so a comment mark inside a string
    # and a quote inside a comment are each read as what they sit in.
    _NOT_CODE = re.compile(
        r"//[^\n]*"
        r"|/\*.*?(?:\*/|\Z)"
        r'|"(?:\\.|[^"\\\n])*"?'
        r"|'(?:\\.|[^'\\\n])*'?",
        re.S,
    )
    _DELIMITER = re.compile(r"[{};]")
    _CODE_CHARACTER = re.compile(r"\S")

    @classmethod
    def _code_only(cls, source: str) -> str:
        """*source* with every comment and the inside of every string literal
        blanked (quotes kept, lengths and newlines kept): what is left is code."""
        def _blank(m: "re.Match[str]") -> str:
            text = m.group(0)
            if text[0] in "\"'":
                return text[0] + re.sub(r"[^\n]", " ", text[1:-1]) + text[-1] if len(text) > 1 else text
            return re.sub(r"[^\n]", " ", text)
        return cls._NOT_CODE.sub(_blank, source or "")

    @classmethod
    def _bodies(cls, source: str, declaration: "re.Pattern[str]"):
        """``(match, has_body)`` for each *declaration* in *source*'s code.

        A declaration's body is the brace-matched block after it; ending in
        ``;`` before any ``{`` (an interface method) or opening a brace that is
        never closed (unbalanced source) is no judgeable body. Linear: the
        braces are matched once with a stack over the delimiters alone, the
        delimiter after each declaration is found by bisection, and a body is
        non-empty when its first character that is not whitespace comes before
        its closing brace. The bodies' leading runs of whitespace never
        overlap, so those searches together read each character once. The
        reading this replaces scanned to the end of the source for every
        declaration whose braces never balanced.
        """
        import bisect

        code = cls._code_only(source)
        positions: list[int] = []
        kinds: list[str] = []
        closing: dict[int, int] = {}
        stack: list[int] = []
        for m in cls._DELIMITER.finditer(code):
            at, kind = m.start(), m.group(0)
            positions.append(at)
            kinds.append(kind)
            if kind == "{":
                stack.append(at)
            elif kind == "}" and stack:
                closing[stack.pop()] = at
        # The first `{` or `;` at or after each delimiter (a `}` opens nothing),
        # by one pass from the end.
        opener = [len(positions)] * (len(positions) + 1)
        for i in range(len(positions) - 1, -1, -1):
            opener[i] = i if kinds[i] != "}" else opener[i + 1]
        for m in declaration.finditer(code):
            i = opener[bisect.bisect_left(positions, m.end())]
            if i >= len(positions) or kinds[i] == ";":
                yield m, False
                continue
            start = positions[i]
            end = closing.get(start)
            if end is None:
                yield m, False
                continue
            first = cls._CODE_CHARACTER.search(code, start + 1, end)
            yield m, first is not None

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
