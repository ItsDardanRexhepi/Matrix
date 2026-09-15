# Module 04: Using Glasswing

## What Glasswing Is

Glasswing is the automated security auditing engine built into 0pnMatrx. A contract tool call that carries source code passes through Glasswing automatically, and a deployment whose source fails it is refused. There is no standalone audit submission: the gateway's audit routes answer `503` (below), so an existing contract is audited by asking for it in chat, where Neo's `security_audit` tool runs Glasswing on the source you paste. Glasswing runs 12 pattern checks over the source; they are listed below, and they are all it checks.

## The 12-Point Vulnerability Scan

Glasswing runs these checks, in this order, with the rule id and severity each emits (`runtime/security/audit.py`; `SWC-` ids are SWC Registry entries, the others are Glasswing's own):

| # | Check | Rule id | Severity if found |
|---|-------|---------|-------------------|
| 1 | Reentrancy | SWC-107 | Critical |
| 2 | Unchecked external call return values | SWC-104 | High |
| 3 | tx.origin used for authorization | SWC-115 | High |
| 4 | Unprotected selfdestruct | SWC-106 | Critical |
| 5 | Delegatecall usage | SWC-112 | High |
| 6 | Unbounded loop over a dynamic array | GAS-001 | Medium |
| 7 | Integer overflow (Solidity below 0.8.0) | SWC-101 | High |
| 8 | Floating pragma version | SWC-103 | Low |
| 9 | Unprotected ether: ETH received but not withdrawable | SWC-105 | High |
| 10 | Missing access control on state-changing functions | AC-001 | High |
| 11 | Front-running exposure | FR-001 | Medium |
| 12 | Block timestamp dependence | SWC-116 | Low |

Each check adds zero or more findings at its severity. The report's `verdict` is `passed` when nothing was found that blocks, `failed` when a critical finding exists (or a high one, when `security.block_on_high` is set), and `not_auditable` when the source has no executable logic to judge — which also blocks a deployment.

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

### The Audit Endpoint Is Not Available

The gateway registers `POST /audit/request` and `GET /audit/{audit_id}`, but no
audit service is wired to them, so both answer `503` with
`{"status": "not_available"}` whatever you send, and no report is produced. Use
the chat path above: Neo's `security_audit` tool runs Glasswing on the source
and returns its report. Glasswing also runs on its own when a contract tool call
carries source code, and a deployment whose source fails it is refused.

## Reading the Audit Report

### Severity Levels

**Critical**: The contract has a vulnerability that can be exploited to steal funds or permanently break functionality. Deployment is blocked. You must fix the issue before deploying.

**High**: The contract has a significant vulnerability that could be exploited under specific conditions. Deployment is strongly discouraged, but it is blocked only when `security.block_on_high` is enabled (off by default). Fix before deploying.

**Medium**: The contract has a potential issue that may or may not be exploitable depending on how the contract is used. Deployment is allowed, but you should understand the risk and fix if possible.

**Low**: A minor issue or code quality concern. Deployment is allowed. Consider fixing for best practices.

**Informational**: Suggestions for improvement that do not represent vulnerabilities. Things like floating pragma versions, unused variables, or missing events.

### What to Do with Each Finding

1. **Read the description carefully** -- it tells you exactly what the issue is
2. **Check the location** -- the function name and line number point you directly to the problem
3. **Understand the recommendation** -- Glasswing suggests a specific fix
4. **Fix and re-audit** -- after making changes, submit the contract again to verify the fix

## Getting a Glasswing Security Badge

A contract whose source passes the platform's own Glasswing audit can be issued a **Glasswing Security Badge** with `POST /badge/issue` (the gateway's API key is required where one is set). The gateway audits the source itself; a request cannot supply the verdict. The badge is:

- A record in the gateway's database, not an on-chain attestation
- Stored with a hash of the audit report it was issued on
- Looked up by badge id at `GET /badge/{badge_id}/status`, and listed at `GET /badges`
- Valid for one year

The badge does not guarantee the contract is bug-free -- no audit can promise that. It certifies that the contract passed automated screening for the most common vulnerability patterns.

To earn the badge, your contract must:
- Declare at least one function with a body (a source with nothing to examine is refused)
- Have zero Critical findings
- Have zero High findings only if the operator enabled `security.block_on_high` (it is off by default, so by default High findings do not stop a badge)
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
- Submit contracts via Trinity (`/chat`); `/audit/request` answers 503 because no audit service is wired
- Critical findings block deployment; High findings block only when `security.block_on_high` is enabled (off by default); Medium and below are advisory
- The Glasswing Security Badge is a gateway record of passing the platform's own audit, not an on-chain attestation
- Re-audit after every significant code change

---

**Next:** [Pre-Deployment Checklist](./05-pre-deployment-checklist.md) -- the complete checklist before going to mainnet.
