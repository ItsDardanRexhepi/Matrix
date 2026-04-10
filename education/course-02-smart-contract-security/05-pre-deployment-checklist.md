# Module 05: Pre-Deployment Checklist

## Why a Checklist Matters

Airline pilots use checklists before every flight, even after 10,000 hours of experience. Smart contract deployment deserves the same discipline. Once your contract is on mainnet, it is immutable. There is no "undo." This checklist covers the 15 items you should verify before every mainnet deployment.

## The 15-Point Pre-Deployment Checklist

### Code Quality

- [ ] **1. Compiler version is pinned.** Use `pragma solidity 0.8.20;`, not `pragma solidity ^0.8.20;`. A floating pragma means your contract could be compiled with a different version in the future, potentially introducing bugs. Lock it to the exact version you tested with.

- [ ] **2. All compiler warnings are resolved.** Warnings are not informational -- they often indicate real issues. Unused variables, shadowed declarations, and unreachable code all signal potential logic errors.

- [ ] **3. No TODO or FIXME comments remain.** Search the codebase. Every TODO is an unfinished task. If it was not important enough to finish, it was not important enough to deploy.

### Testing

- [ ] **4. Test coverage is above 90%.** Every external and public function should have tests. Every require/revert condition should be tested from both the passing and failing sides. Use `forge coverage` or `hardhat coverage` to measure.

- [ ] **5. Edge cases are tested.** Zero values, maximum values, empty arrays, the zero address, duplicate calls, reentrancy attempts, and calls from unauthorized addresses. The contract should handle every input gracefully, not just the expected ones.

- [ ] **6. Testnet deployment succeeded.** Deploy to Base Sepolia first. Interact with every function. Send real (testnet) transactions. Verify the contract behaves identically to your local tests. Fix any discrepancies before proceeding.

### Security

- [ ] **7. Glasswing audit passed.** Zero Critical and zero High findings. All Medium findings have been reviewed and are either fixed or documented as accepted risks with justification.

- [ ] **8. Access control is reviewed.** List every function and who can call it. Verify that privileged functions have appropriate modifiers. Check that the owner/admin cannot be set to the zero address accidentally. Confirm that role assignments follow the principle of least privilege.

- [ ] **9. External calls follow CEI pattern.** Every function that makes an external call should follow Checks-Effects-Interactions. State changes before external calls, never after. Add `nonReentrant` modifiers as defense in depth.

- [ ] **10. No hardcoded secrets or private keys.** Search for hex strings, private key patterns, and API keys. These are visible to everyone on the blockchain. Use environment variables or secure key management for anything sensitive.

### Operations

- [ ] **11. Emergency pause mechanism exists.** If something goes wrong after deployment, you need a way to stop the contract from processing further transactions while you assess the situation. OpenZeppelin's `Pausable` provides this. Make sure the pause function is protected by access control but accessible to the emergency response team.

- [ ] **12. Upgrade strategy is decided.** Choose one of three approaches and implement it before deployment:
  - **Immutable**: No upgrades possible. Simplest and most trustworthy, but bugs are permanent.
  - **Proxy pattern**: The contract logic can be upgraded via a proxy. More flexible, but introduces complexity and trust assumptions.
  - **Migration**: Deploy a new contract and migrate state. Most disruptive, but cleanest separation.
  Document your choice and the rationale.

- [ ] **13. Monitoring is configured.** Set up alerts for unexpected events: large transfers, admin function calls, paused/unpaused events, failed transactions. You need to know within minutes if something unusual happens, not days.

### Deployment

- [ ] **14. Contract source code is verified.** After deployment, verify the source code on the block explorer (Basescan for Base). This lets anyone read and audit your contract. Unverified contracts are treated with suspicion by users and integrators.

- [ ] **15. Deployment transaction is reviewed.** Before signing the deployment transaction, review: the constructor arguments, the gas limit, the network (confirm it is mainnet, not testnet), and the deployer address. Morpheus handles this confirmation step in 0pnMatrx, but double-check anyway.

## Using This Checklist

Copy this checklist into your project's deployment documentation. Before every mainnet deployment, go through each item sequentially. Do not skip items because "it worked on testnet." Testnet and mainnet are different environments with different economic incentives.

If any item fails, stop the deployment. Fix the issue. Re-run the checklist from the beginning. Partially checked deployments are how bugs ship to production.

## Integrating with 0pnMatrx

When deploying through 0pnMatrx, several checklist items are handled automatically:

- **Item 7**: Glasswing audit runs automatically before deployment
- **Item 6**: 0pnMatrx deploys to testnet first by default
- **Item 14**: Source verification can be requested through Trinity
- **Item 15**: Morpheus presents the deployment details for confirmation

The remaining items require your judgment and cannot be automated. They are your responsibility.

## Key Takeaways

- 15 items across five categories: code quality, testing, security, operations, deployment
- No item is optional for mainnet deployments
- Several items are automated by 0pnMatrx, but most require human judgment
- If any item fails, stop and fix before proceeding
- Copy and use this checklist for every deployment

---

**Course complete.** Review the [vulnerable contracts](./VULNERABLE_CONTRACTS.sol) and [fixed contracts](./FIXED_CONTRACTS.sol) for hands-on practice identifying and fixing vulnerabilities.
