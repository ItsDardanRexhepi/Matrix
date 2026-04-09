"""Tests for runtime.security.audit.ContractAuditor."""

import pytest

from runtime.security.audit import ContractAuditor, AuditReport, Finding, Severity


# -- Solidity snippets for each vulnerability check --

REENTRANCY_CODE = """
pragma solidity 0.8.20;
contract Vuln {
    mapping(address => uint) balances;
    function withdraw() public {
        (bool ok,) = msg.sender.call{value: balances[msg.sender]}("");
        balances[msg.sender] = 0;
    }
}
"""

UNCHECKED_CALL_CODE = """
pragma solidity 0.8.20;
contract Vuln {
    function send(address to) public {
        to.call{value: 1 ether}("");
    }
}
"""

TX_ORIGIN_CODE = """
pragma solidity 0.8.20;
contract Vuln {
    function check() public view {
        require(tx.origin == msg.sender);
    }
}
"""

SELFDESTRUCT_CODE = """
pragma solidity 0.8.20;
contract Vuln {
    function kill() public {
        selfdestruct(payable(msg.sender));
    }
}
"""

DELEGATECALL_CODE = """
pragma solidity 0.8.20;
contract Vuln {
    function forward(address target) public {
        target.delegatecall(abi.encodeWithSignature("run()"));
    }
}
"""

UNBOUNDED_LOOP_CODE = """
pragma solidity 0.8.20;
contract Vuln {
    uint[] items;
    function process() public {
        for (uint i = 0; i < items.length; i++) {}
    }
}
"""

INTEGER_OVERFLOW_CODE = """
pragma solidity ^0.7.0;
contract Vuln {
    uint public count;
    function inc() public { count += 1; }
}
"""

FLOATING_PRAGMA_CODE = """
pragma solidity ^0.8.0;
contract Vuln {}
"""

LOCKED_ETHER_CODE = """
pragma solidity 0.8.20;
contract Vuln {
    receive() external payable {}
}
"""

MISSING_ACCESS_CONTROL_CODE = """
pragma solidity 0.8.20;
contract Vuln {
    function mint(address to, uint amount) public {
        // no access control
    }
}
"""

FRONT_RUNNING_CODE = """
pragma solidity 0.8.20;
contract Vuln {
    function swap(address tokenA, address tokenB, uint amount) public {
        // vulnerable to MEV
        IERC20(tokenA).transfer(msg.sender, amount);
    }
}
"""

TIMESTAMP_CODE = """
pragma solidity 0.8.20;
contract Vuln {
    function isExpired() public view returns (bool) {
        return block.timestamp > 1000;
    }
}
"""

CLEAN_CODE = """
pragma solidity 0.8.20;
import "@openzeppelin/contracts/access/Ownable.sol";
import "@openzeppelin/contracts/security/ReentrancyGuard.sol";
contract Safe is Ownable, ReentrancyGuard {
    mapping(address => uint) public balances;
    function withdraw() external nonReentrant {
        uint amount = balances[msg.sender];
        balances[msg.sender] = 0;
        (bool ok,) = msg.sender.call{value: amount}("");
        require(ok, "transfer failed");
    }
    function mint(address to, uint amount) public onlyOwner {
        balances[to] += amount;
    }
}
"""


class TestVulnerabilityChecks:
    """Each of the 12 vulnerability checks should fire on known-bad code."""

    def setup_method(self):
        self.auditor = ContractAuditor()

    def test_reentrancy_detected(self):
        report = self.auditor.audit(REENTRANCY_CODE, "Vuln")
        rule_ids = [f.rule_id for f in report.findings]
        assert "SWC-107" in rule_ids

    def test_unchecked_call_detected(self):
        report = self.auditor.audit(UNCHECKED_CALL_CODE, "Vuln")
        rule_ids = [f.rule_id for f in report.findings]
        assert "SWC-104" in rule_ids

    def test_tx_origin_detected(self):
        report = self.auditor.audit(TX_ORIGIN_CODE, "Vuln")
        rule_ids = [f.rule_id for f in report.findings]
        assert "SWC-115" in rule_ids

    def test_selfdestruct_detected(self):
        report = self.auditor.audit(SELFDESTRUCT_CODE, "Vuln")
        rule_ids = [f.rule_id for f in report.findings]
        assert "SWC-106" in rule_ids

    def test_delegatecall_detected(self):
        report = self.auditor.audit(DELEGATECALL_CODE, "Vuln")
        rule_ids = [f.rule_id for f in report.findings]
        assert "SWC-112" in rule_ids

    def test_unbounded_loop_detected(self):
        report = self.auditor.audit(UNBOUNDED_LOOP_CODE, "Vuln")
        rule_ids = [f.rule_id for f in report.findings]
        assert "GAS-001" in rule_ids

    def test_integer_overflow_detected(self):
        report = self.auditor.audit(INTEGER_OVERFLOW_CODE, "Vuln")
        rule_ids = [f.rule_id for f in report.findings]
        assert "SWC-101" in rule_ids

    def test_floating_pragma_detected(self):
        report = self.auditor.audit(FLOATING_PRAGMA_CODE, "Vuln")
        rule_ids = [f.rule_id for f in report.findings]
        assert "SWC-103" in rule_ids

    def test_locked_ether_detected(self):
        report = self.auditor.audit(LOCKED_ETHER_CODE, "Vuln")
        rule_ids = [f.rule_id for f in report.findings]
        assert "SWC-105" in rule_ids

    def test_missing_access_control_detected(self):
        report = self.auditor.audit(MISSING_ACCESS_CONTROL_CODE, "Vuln")
        rule_ids = [f.rule_id for f in report.findings]
        assert "AC-001" in rule_ids

    def test_front_running_detected(self):
        report = self.auditor.audit(FRONT_RUNNING_CODE, "Vuln")
        rule_ids = [f.rule_id for f in report.findings]
        assert "FR-001" in rule_ids

    def test_timestamp_dependence_detected(self):
        report = self.auditor.audit(TIMESTAMP_CODE, "Vuln")
        rule_ids = [f.rule_id for f in report.findings]
        assert "SWC-116" in rule_ids


class TestCleanCode:
    """Clean, well-written code should pass the audit."""

    def test_clean_code_no_critical(self):
        auditor = ContractAuditor()
        report = auditor.audit(CLEAN_CODE, "Safe")
        critical = [f for f in report.findings if f.severity == Severity.CRITICAL]
        assert len(critical) == 0

    def test_clean_code_passes(self):
        auditor = ContractAuditor()
        report = auditor.audit(CLEAN_CODE, "Safe")
        assert report.passed is True


class TestBlockingLogic:
    """Blocking behaviour: critical blocks by default, high does not."""

    def test_critical_blocks_by_default(self):
        auditor = ContractAuditor({"security": {"block_on_critical": True, "block_on_high": False}})
        report = auditor.audit(REENTRANCY_CODE, "Vuln")
        # Reentrancy is CRITICAL
        assert report.passed is False
        assert auditor.should_block(report) is True

    def test_high_does_not_block_by_default(self):
        auditor = ContractAuditor({"security": {"block_on_critical": False, "block_on_high": False}})
        report = auditor.audit(TX_ORIGIN_CODE, "Vuln")
        # tx.origin is HIGH
        assert report.passed is True
        assert auditor.should_block(report) is False

    def test_high_blocks_when_configured(self):
        auditor = ContractAuditor({"security": {"block_on_critical": False, "block_on_high": True}})
        report = auditor.audit(TX_ORIGIN_CODE, "Vuln")
        assert report.passed is False

    def test_no_findings_always_passes(self):
        auditor = ContractAuditor({"security": {"block_on_critical": True, "block_on_high": True}})
        report = auditor.audit(CLEAN_CODE, "Safe")
        assert auditor.should_block(report) is False


class TestAuditReportSerialization:
    """AuditReport.to_dict() produces the expected structure."""

    def test_to_dict_structure(self):
        auditor = ContractAuditor()
        report = auditor.audit(REENTRANCY_CODE, "TestContract")
        d = report.to_dict()
        assert d["contract_name"] == "TestContract"
        assert isinstance(d["passed"], bool)
        assert isinstance(d["finding_count"], int)
        assert d["finding_count"] == len(d["findings"])
        assert "critical_count" in d
        assert "high_count" in d
        assert "medium_count" in d
        assert "summary" in d

    def test_finding_to_dict(self):
        f = Finding(
            rule_id="SWC-107",
            severity=Severity.CRITICAL,
            title="Reentrancy",
            description="Bad pattern",
            line=10,
            snippet="msg.sender.call",
        )
        d = f.to_dict()
        assert d["rule_id"] == "SWC-107"
        assert d["severity"] == "critical"
        assert d["line"] == 10

    def test_empty_report_summary(self):
        auditor = ContractAuditor()
        report = auditor.audit(CLEAN_CODE, "Safe")
        assert "No vulnerabilities" in report.summary or len(report.findings) == 0

    def test_counts_match_findings(self):
        auditor = ContractAuditor()
        report = auditor.audit(REENTRANCY_CODE, "Vuln")
        d = report.to_dict()
        actual_critical = sum(1 for f in report.findings if f.severity == Severity.CRITICAL)
        assert d["critical_count"] == actual_critical
