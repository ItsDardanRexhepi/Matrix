# Course 02: Smart Contract Security with Glasswing

## Overview

Smart contracts are immutable once deployed. A bug in traditional software gets patched; a bug in a smart contract can drain millions of dollars permanently. This course teaches you how contracts get hacked, how to identify vulnerabilities before deployment, and how to use the Glasswing auditing engine to protect your contracts.

## Prerequisites

- **Solidity basics**: You should be able to read a simple Solidity contract (functions, state variables, modifiers)
- **Course 01 completion recommended**: Familiarity with 0pnMatrx, the gateway, and contract deployment
- No prior security experience required

## What You Will Learn

1. The most common vulnerability patterns that cause real-world exploits
2. How reentrancy attacks work at the bytecode level and three ways to prevent them
3. Access control patterns from basic to advanced (ownership, roles, multisig, timelocks)
4. How to use Glasswing's 12-point vulnerability scan
5. A pre-deployment checklist you can use for every contract

## Modules

| Module | Title | Duration |
|--------|-------|----------|
| [01](./01-why-contracts-get-hacked.md) | Why Contracts Get Hacked | ~20 min |
| [02](./02-reentrancy-deep-dive.md) | Reentrancy Deep Dive | ~25 min |
| [03](./03-access-control-patterns.md) | Access Control Patterns | ~20 min |
| [04](./04-using-glasswing.md) | Using Glasswing | ~20 min |
| [05](./05-pre-deployment-checklist.md) | Pre-Deployment Checklist | ~15 min |

## Hands-On Practice

This course includes two Solidity files for hands-on practice:

- [VULNERABLE_CONTRACTS.sol](./VULNERABLE_CONTRACTS.sol) -- Three intentionally vulnerable contracts. Try to identify every vulnerability before checking the fixes.
- [FIXED_CONTRACTS.sol](./FIXED_CONTRACTS.sol) -- Corrected versions with detailed comments explaining each fix.

## Estimated Total Time

Approximately 3-4 hours for all modules and contract analysis.

## Next Steps

After completing this course, you will be able to:
- Audit your own contracts for common vulnerabilities
- Use Glasswing as part of your deployment workflow
- Understand audit reports from professional security firms
- Make informed decisions about contract security tradeoffs
