# Module 04: Using Glasswing

## What Glasswing Is

Glasswing is the automated security auditing engine built into 0pnMatrx. Every contract deployed through the platform passes through Glasswing automatically, but you can also submit existing contracts for standalone audits. Glasswing performs a 12-point vulnerability scan that covers the most critical and commonly exploited vulnerability categories in smart contracts.

## The 12-Point Vulnerability Scan

Glasswing checks for the following vulnerability categories, mapped to their SWC Registry identifiers:

| # | Category | SWC ID | Severity if Found |
|---|----------|--------|--------------------|
| 1 | Reentrancy | SWC-107 | Critical |
| 2 | Integer overflow/underflow | SWC-101 | High |
| 3 | Unchecked external calls | SWC-104 | High |
| 4 | Access control violations | SWC-105/106 | Critical |
| 5 | Front-running vulnerability | SWC-114 | Medium |
| 6 | Denial of service vectors | SWC-113/128 | High |
| 7 | Timestamp dependence | SWC-116 | Low |
| 8 | Tx.origin authentication | SWC-115 | High |
| 9 | Uninitialized storage pointers | SWC-109 | High |
| 10 | Delegatecall to untrusted callee | SWC-112 | Critical |
| 11 | Floating pragma | SWC-103 | Informational |
| 12 | Unused variables / dead code | SWC-131 | Informational |

Each check produces one of four results: **Pass** (no vulnerability found), **Warning** (potential issue that may be intentional), **Fail** (confirmed vulnerability), or **Informational** (best practice suggestion).

## Submitting a Contract for Audit

### Via the Chat Interface

The simplest way -- ask Trinity to audit a contract:

```bash
curl -X POST http://localhost:18790/chat \
  -H "Content-Type: application/json" \
  -H "Authorization: Bearer YOUR_API_KEY" \
  -d '{
    "message": "Audit this contract for vulnerabilities: [paste Solidity code]"
  }'
```

Trinity hands the code to Neo, who invokes the Glasswing audit service. The response includes the full audit report.

### Via the Audit Endpoint

For programmatic access, use the dedicated audit endpoint:

```bash
curl -X POST http://localhost:18790/audit/request \
  -H "Content-Type: application/json" \
  -H "Authorization: Bearer YOUR_API_KEY" \
  -d '{
    "source_code": "pragma solidity ^0.8.20; ...",
    "contract_name": "MyContract",
    "compiler_version": "0.8.20"
  }'
```

The response includes:

```json
{
  "audit_id": "aud_abc123",
  "status": "complete",
  "summary": {
    "total_checks": 12,
    "passed": 10,
    "warnings": 1,
    "failures": 1,
    "informational": 0
  },
  "findings": [
    {
      "check": "reentrancy",
      "severity": "critical",
      "status": "fail",
      "location": {"function": "withdraw", "line": 24},
      "description": "State variable 'balances' is modified after external call on line 22",
      "recommendation": "Apply checks-effects-interactions pattern: update balances before the external call"
    }
  ]
}
```

## Reading the Audit Report

### Severity Levels

**Critical**: The contract has a vulnerability that can be exploited to steal funds or permanently break functionality. Deployment is blocked. You must fix the issue before deploying.

**High**: The contract has a significant vulnerability that could be exploited under specific conditions. Deployment is strongly discouraged. Fix before deploying.

**Medium**: The contract has a potential issue that may or may not be exploitable depending on how the contract is used. Deployment is allowed, but you should understand the risk and fix if possible.

**Low**: A minor issue or code quality concern. Deployment is allowed. Consider fixing for best practices.

**Informational**: Suggestions for improvement that do not represent vulnerabilities. Things like floating pragma versions, unused variables, or missing events.

### What to Do with Each Finding

1. **Read the description carefully** -- it tells you exactly what the issue is
2. **Check the location** -- the function name and line number point you directly to the problem
3. **Understand the recommendation** -- Glasswing suggests a specific fix
4. **Fix and re-audit** -- after making changes, submit the contract again to verify the fix

## Getting a Glasswing Security Badge

Contracts that pass all 12 checks with zero Critical or High findings receive a **Glasswing Security Badge**. This badge is:

- Recorded as an EAS attestation on-chain
- Verifiable by anyone using the attestation UID
- Linked to the specific version of the code that was audited
- Displayed alongside the contract on the 0pnMatrx dashboard

The badge does not guarantee the contract is bug-free -- no audit can promise that. It certifies that the contract passed automated screening for the most common vulnerability patterns.

To earn the badge, your contract must:
- Pass all 12 vulnerability checks
- Have zero Critical findings
- Have zero High findings
- Medium, Low, and Informational findings are allowed

## When to Re-Audit

**After every significant change.** A contract that passed audit yesterday may fail today after a code change. Specifically, re-audit when:

- You modify any function that handles funds (transfers, withdrawals, deposits)
- You change access control logic (adding/removing modifiers, changing role assignments)
- You add new external calls or change how existing ones work
- You modify state variables that are read in sensitive functions
- You upgrade dependencies (OpenZeppelin versions, library imports)
- You refactor code structure, even if the logic "should be the same"

The cost of re-auditing is near zero -- Glasswing runs in seconds. The cost of deploying an unaudited change is potentially catastrophic.

## Key Takeaways

- Glasswing performs a 12-point scan covering the most critical vulnerability categories
- Submit contracts via Trinity (`/chat`) or directly via `/audit/request`
- Critical and High findings block deployment; Medium and below are advisory
- The Glasswing Security Badge is an on-chain attestation of passing the audit
- Re-audit after every significant code change

---

**Next:** [Pre-Deployment Checklist](./05-pre-deployment-checklist.md) -- the complete checklist before going to mainnet.
