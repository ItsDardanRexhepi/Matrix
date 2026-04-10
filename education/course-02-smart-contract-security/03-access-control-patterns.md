# Module 03: Access Control Patterns

## Why Access Control Matters

Every smart contract function is public by default on the blockchain. Anyone can call any external function on any contract. If your contract has a `withdrawAll()` function and it does not check who is calling it, anyone in the world can drain your contract. Access control is not a feature -- it is a survival requirement.

## Pattern 1: The onlyOwner Pattern

The simplest form of access control: a single address has admin privileges.

```solidity
import "@openzeppelin/contracts/access/Ownable.sol";

contract SimpleVault is Ownable {
    constructor() Ownable(msg.sender) {}

    function withdraw(uint256 amount) external onlyOwner {
        payable(owner()).transfer(amount);
    }
}
```

The `onlyOwner` modifier checks that `msg.sender == owner()`. If not, the transaction reverts. OpenZeppelin's `Ownable` also provides `transferOwnership()` and `renounceOwnership()` functions.

**When onlyOwner is sufficient**: Simple contracts with a single admin, personal projects, contracts where one entity has full authority.

**When onlyOwner is insufficient**: Any contract managing significant value, multi-party contracts, protocols where no single person should have unilateral control. If one private key is compromised, the entire contract is compromised.

## Pattern 2: Role-Based Access Control

OpenZeppelin's `AccessControl` lets you define multiple roles, each with different permissions:

```solidity
import "@openzeppelin/contracts/access/AccessControl.sol";

contract Treasury is AccessControl {
    bytes32 public constant TREASURER_ROLE = keccak256("TREASURER_ROLE");
    bytes32 public constant AUDITOR_ROLE = keccak256("AUDITOR_ROLE");

    constructor() {
        _grantRole(DEFAULT_ADMIN_ROLE, msg.sender);
        _grantRole(TREASURER_ROLE, msg.sender);
    }

    function withdraw(uint256 amount) external onlyRole(TREASURER_ROLE) {
        payable(msg.sender).transfer(amount);
    }

    function freeze() external onlyRole(AUDITOR_ROLE) {
        // Pause all operations
    }
}
```

Roles are identified by `bytes32` values (typically keccak256 hashes of role names). The `DEFAULT_ADMIN_ROLE` can grant and revoke all other roles. You can set up role hierarchies where specific roles can manage other roles.

Key advantages over `onlyOwner`:
- **Separation of concerns**: Different people can have different permissions
- **Least privilege**: Grant each address only the permissions it needs
- **Auditable**: Role assignments are tracked on-chain via events
- **Revocable**: Roles can be revoked without transferring full ownership

## Pattern 3: Multisig

A multisig (multi-signature) wallet requires multiple private keys to approve a transaction. Instead of one person controlling a contract, a group must agree.

Common configurations:
- **2-of-3**: Any two of three keyholders must approve
- **3-of-5**: Any three of five keyholders must approve
- **4-of-7**: Common for high-value protocol treasuries

The process works like this:

1. One keyholder proposes a transaction
2. Other keyholders review and sign
3. Once the threshold is met, anyone can execute the transaction
4. If the threshold is not met within a timeframe, the proposal expires

**Why single-key ownership is dangerous**: If one person controls a contract holding millions of dollars, their private key becomes the single point of failure. Phishing attacks, compromised hardware, lost seed phrases, or even coercion can lead to total loss. A 3-of-5 multisig means an attacker would need to compromise three separate individuals using three separate key storage methods.

### The 0pnMatrx NeoSafe Multisig

0pnMatrx uses a multisig called **NeoSafe** for its own protocol contracts. NeoSafe is a purpose-built multisig that integrates with the agent system:

- **Proposal via Trinity**: Authorized members propose transactions through the chat interface
- **Morpheus confirmation**: Each signer sees the exact transaction details through Morpheus before approving
- **On-chain execution**: Once the threshold is met, Neo executes the transaction
- **Audit trail**: Every proposal, approval, and execution is logged with EAS attestations

NeoSafe demonstrates a practical pattern: the multisig does not just protect the contract -- it integrates with the workflow that people actually use.

## Pattern 4: Timelock Contracts

A timelock adds a mandatory delay between proposing an action and executing it. This gives stakeholders time to review and potentially veto dangerous changes.

```solidity
import "@openzeppelin/contracts/governance/TimelockController.sol";
```

Typical flow:
1. Admin proposes a transaction (e.g., upgrading a contract)
2. The timelock starts a countdown (e.g., 48 hours)
3. During the delay, anyone can review the proposed change
4. If no one cancels, the transaction becomes executable after the delay
5. The transaction must be explicitly executed (it does not auto-execute)

Timelocks are standard practice for DeFi protocols. If a protocol's admin can change interest rates, swap fee percentages, or contract logic instantly, users have no time to exit if they disagree with a change. A 48-hour timelock means users can always withdraw their funds before an unwanted change takes effect.

**Combining multisig and timelock**: The strongest pattern. A 3-of-5 multisig proposes changes, and a 48-hour timelock gives the community time to review. This is the gold standard for DeFi protocol governance.

## Anti-Patterns to Avoid

**Unprotected initializers**: Proxy contracts that use `initialize()` instead of constructors must ensure the function can only be called once, by the deployer. An unprotected initializer lets an attacker call it and set themselves as the owner.

**tx.origin for authentication**: `tx.origin` returns the original external caller, not the immediate caller. If a user interacts with a malicious contract that then calls your contract, `tx.origin` is the user, not the malicious contract. Always use `msg.sender`.

**Hardcoded addresses**: Hardcoding admin addresses makes key rotation impossible. Use `Ownable` or `AccessControl` with transfer/grant functions instead.

**Missing zero-address checks**: Transferring ownership or granting roles to `address(0)` effectively locks the function permanently. Always validate that addresses are not zero before assigning permissions.

## Key Takeaways

- Every external function needs explicit access control -- public by default means callable by anyone
- `onlyOwner` is a starting point, not a complete solution
- Role-based access control separates concerns and follows the principle of least privilege
- Multisigs eliminate single points of failure for high-value contracts
- Timelocks give stakeholders time to review and exit before changes take effect
- The NeoSafe multisig in 0pnMatrx integrates access control with the agent workflow

---

**Next:** [Using Glasswing](./04-using-glasswing.md) -- automate vulnerability detection with the 0pnMatrx auditing engine.
