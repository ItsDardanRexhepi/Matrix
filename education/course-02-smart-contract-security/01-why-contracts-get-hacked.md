# Module 01: Why Contracts Get Hacked

## The Stakes

In traditional software, a bug means downtime or corrupted data. In smart contracts, a bug means money disappears. Permanently. Smart contracts are immutable once deployed -- there is no "push a fix" option. And because they hold real assets, they attract adversaries who spend weeks analyzing contract bytecode looking for a single exploitable flaw.

Understanding why contracts get hacked is the first step toward writing ones that do not.

## A Brief History of Exploits

### The DAO Hack (2016) -- Reentrancy

The most famous smart contract exploit in history. The DAO was a decentralized investment fund on Ethereum that held roughly $150 million in ETH. An attacker exploited a reentrancy vulnerability in the withdrawal function -- the contract sent ETH to the caller before updating the caller's balance. The attacker's contract had a fallback function that immediately called withdraw again, draining funds in a loop before the balance was ever decremented. The result: $60 million stolen. The Ethereum community eventually hard-forked the chain to reverse the damage, splitting Ethereum and Ethereum Classic.

### DeFi Reentrancy Exploits (2020-2023)

The DAO hack happened in 2016, but reentrancy attacks continued for years. Protocols like Fei Protocol, Rari Capital, and several others lost tens of millions to variations of the same pattern. In some cases, the reentrancy occurred through cross-function calls (calling a different function that shared the same state) or cross-contract calls (reentering through a different contract in the same protocol). The pattern evolved, but the root cause remained: external calls before state updates.

### Access Control Failures

Multiple protocols have lost funds because critical functions lacked proper access restrictions. In some cases, an "initialize" function meant to be called once by the deployer was left unprotected, allowing an attacker to call it and set themselves as the owner. In others, admin functions that could drain the treasury were callable by anyone. The Ronin Bridge hack ($625 million) involved compromised validator keys -- an access control failure at the infrastructure level.

## Common Vulnerability Patterns

Most contract exploits fall into a handful of categories:

**Reentrancy (SWC-107)**: An external call allows the called contract to re-enter the calling contract before state changes are finalized. This is the single most common vulnerability pattern in smart contract history.

**Integer Overflow/Underflow (SWC-101)**: In Solidity versions before 0.8.0, arithmetic operations could silently overflow or underflow. A token balance of 1 minus 2 would not revert -- it would wrap to the maximum uint256 value (approximately 1.15 * 10^77). Solidity 0.8+ adds automatic overflow checks, but contracts using `unchecked` blocks or older pragma versions remain vulnerable.

**Access Control (SWC-105/106)**: Functions that should be restricted to specific roles (owner, admin, authorized contracts) are left callable by anyone. This includes missing `onlyOwner` modifiers, unprotected initializer functions, and insecure delegatecall patterns.

**Front-Running (SWC-114)**: On public blockchains, pending transactions are visible in the mempool before they are mined. An attacker can see a profitable transaction, submit their own with a higher gas price to get mined first, and extract value. This affects DEX trades, auction bids, and any transaction where the order of execution matters.

**Denial of Service (SWC-113/128)**: An attacker makes a function unusable for legitimate users. Common patterns include: forcing a contract to send ETH to an address that reverts on receive (blocking a refund loop), unbounded loops that exceed the block gas limit, and griefing attacks that make state transitions prohibitively expensive.

**Unsafe External Calls (SWC-104/107)**: Low-level calls (`.call`, `.delegatecall`) that do not check return values, allowing silent failures. A token transfer that returns `false` instead of reverting gets treated as successful, but no tokens actually moved.

## Why Automated Auditing Matters

Manual code review is essential but not sufficient. Human reviewers catch logic errors, design flaws, and protocol-level issues that automated tools miss. But they also miss things. Automated scanners are tireless, consistent, and fast. They check every function against known vulnerability patterns in seconds.

Glasswing, the 0pnMatrx auditing engine, performs a 12-point scan against the most critical vulnerability categories. It does not replace human auditing for high-value contracts, but it catches the common patterns that cause the majority of exploits.

## The Cost of NOT Auditing

A professional smart contract audit costs $5,000 to $50,000 depending on complexity. That sounds expensive until you compare it to the alternative:

- The DAO: $60 million lost
- Ronin Bridge: $625 million lost
- Wormhole Bridge: $320 million lost
- Nomad Bridge: $190 million lost

The most expensive audit is still cheaper than the cheapest exploit. And with Glasswing integrated into 0pnMatrx, every contract gets a baseline audit for free as part of the deployment pipeline.

## Key Takeaways

- Smart contracts are immutable; bugs cannot be patched after deployment
- Reentrancy, integer overflow, and access control failures cause the majority of exploits
- The same vulnerability patterns have been exploited repeatedly over years
- Automated auditing catches common patterns; manual review catches logic errors
- Every contract deployed through 0pnMatrx passes a Glasswing audit automatically

---

**Next:** [Reentrancy Deep Dive](./02-reentrancy-deep-dive.md) -- understand exactly how the most common attack works.
