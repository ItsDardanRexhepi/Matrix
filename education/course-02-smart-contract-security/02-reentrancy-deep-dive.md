# Module 02: Reentrancy Deep Dive

## What Reentrancy Is

Reentrancy (SWC-107) occurs when a contract makes an external call to another contract, and that external contract calls back into the original contract before the first invocation has finished executing. If the original contract has not updated its state before the external call, the re-entrant call sees stale state and can exploit it.

The name comes from the concept of a function being "re-entered" before it completes. In traditional programming, this is similar to a race condition -- but in smart contracts, it is deterministic and exploitable every time.

## How a Reentrancy Attack Works

Consider a simple bank contract that lets users deposit and withdraw ETH:

```solidity
// VULNERABLE -- DO NOT USE
contract VulnerableBank {
    mapping(address => uint256) public balances;

    function deposit() external payable {
        balances[msg.sender] += msg.value;
    }

    function withdraw() external {
        uint256 amount = balances[msg.sender];
        require(amount > 0, "No balance");

        // VULNERABILITY: external call BEFORE state update
        (bool success, ) = msg.sender.call{value: amount}("");
        require(success, "Transfer failed");

        // State update happens AFTER the external call
        balances[msg.sender] = 0;
    }
}
```

Here is what happens step by step during an attack:

### Step 1: Setup
The attacker deploys a malicious contract:

```solidity
contract Attacker {
    VulnerableBank public target;

    constructor(address _target) {
        target = VulnerableBank(_target);
    }

    function attack() external payable {
        target.deposit{value: msg.value}();
        target.withdraw();
    }

    // This function is called when the bank sends ETH
    receive() external payable {
        if (address(target).balance >= 1 ether) {
            target.withdraw();  // Re-enter the withdraw function
        }
    }
}
```

### Step 2: Initial Deposit
The attacker calls `attack()` with 1 ETH. This deposits 1 ETH into the bank, then calls `withdraw()`.

### Step 3: First Withdrawal Begins
Inside `withdraw()`:
- `amount` is set to 1 ETH (the attacker's balance)
- The `require(amount > 0)` check passes
- The contract sends 1 ETH to `msg.sender` (the attacker contract)
- **The balance has NOT been set to 0 yet**

### Step 4: The Re-entry
When the attacker contract receives the 1 ETH, its `receive()` function executes. This function calls `withdraw()` again on the bank.

### Step 5: Second Withdrawal
Inside the second `withdraw()` call:
- `amount` is checked: it is still 1 ETH (because step 3 never updated it)
- The `require` passes again
- Another 1 ETH is sent to the attacker
- The `receive()` function fires again, calling `withdraw()` again

### Step 6: Loop Until Drained
This loop continues until either the bank runs out of ETH or the call stack depth limit is reached. With each iteration, the attacker extracts 1 ETH while their recorded balance remains unchanged.

### Step 7: Stack Unwinds
When the loop finally stops, execution returns up the call stack. Each `withdraw()` call sets `balances[msg.sender] = 0`, but the damage is done -- the ETH has already been sent.

## How Glasswing Detects It

Glasswing identifies reentrancy vulnerabilities by analyzing the order of operations within functions that make external calls. Specifically, it flags any function where:

1. A state variable is read (e.g., `balances[msg.sender]`)
2. An external call is made (e.g., `.call{value: amount}`)
3. The same state variable is written after the external call (e.g., `balances[msg.sender] = 0`)

This read-call-write pattern is the signature of reentrancy vulnerability. Glasswing reports it with severity "Critical" and identifies the specific line numbers involved.

It also detects cross-function reentrancy, where the external call re-enters through a different function that reads the same state variable, and cross-contract reentrancy in multi-contract protocols.

## Fix Pattern 1: Checks-Effects-Interactions (CEI)

The simplest and most fundamental fix. Reorder operations so that all state changes happen before any external calls:

```solidity
function withdraw() external {
    uint256 amount = balances[msg.sender];
    require(amount > 0, "No balance");         // CHECK

    balances[msg.sender] = 0;                   // EFFECT (state change)

    (bool success, ) = msg.sender.call{value: amount}(""); // INTERACTION
    require(success, "Transfer failed");
}
```

Now, even if the attacker's `receive()` function calls `withdraw()` again, the balance has already been set to 0. The second call fails at the `require(amount > 0)` check.

This pattern is free -- no gas overhead, no additional dependencies. It should be your default approach.

## Fix Pattern 2: ReentrancyGuard

OpenZeppelin's `ReentrancyGuard` provides a modifier that prevents any function from being re-entered:

```solidity
import "@openzeppelin/contracts/utils/ReentrancyGuard.sol";

contract SafeBank is ReentrancyGuard {
    mapping(address => uint256) public balances;

    function withdraw() external nonReentrant {
        uint256 amount = balances[msg.sender];
        require(amount > 0, "No balance");

        (bool success, ) = msg.sender.call{value: amount}("");
        require(success, "Transfer failed");

        balances[msg.sender] = 0;
    }
}
```

The `nonReentrant` modifier works by setting a lock variable to "entered" at the start of the function and resetting it at the end. If the function is called again while the lock is set, it reverts. This costs roughly 2,500 gas extra per call for the storage operations on the lock variable.

Use `ReentrancyGuard` as a safety net even when you follow CEI. Defense in depth.

## Fix Pattern 3: Pull Payments

Instead of sending funds directly, record what is owed and let recipients withdraw:

```solidity
import "@openzeppelin/contracts/security/PullPayment.sol";

contract PullBank is PullPayment {
    function withdraw() external {
        uint256 amount = balances[msg.sender];
        require(amount > 0, "No balance");

        balances[msg.sender] = 0;
        _asyncTransfer(msg.sender, amount);
    }

    // User calls this separately to claim their funds
    // Inherited from PullPayment: withdrawPayments(address payable payee)
}
```

The pull payment pattern eliminates the external call from the withdraw function entirely. Funds are held in an escrow contract, and the recipient calls a separate function to claim them. This completely eliminates the reentrancy surface but changes the user experience -- users must make two transactions instead of one.

## Which Pattern to Use

| Pattern | Gas Cost | Complexity | Protection Level |
|---------|----------|------------|------------------|
| CEI | None | Low | Prevents single-function reentrancy |
| ReentrancyGuard | ~2,500 gas | Low | Prevents single and cross-function reentrancy |
| Pull Payments | ~5,000 gas | Medium | Eliminates the attack surface entirely |

**Recommendation**: Always use CEI ordering. Add `ReentrancyGuard` on any function that makes external calls. Consider pull payments for high-value contracts or when the user experience tradeoff is acceptable.

## Key Takeaways

- Reentrancy exploits the gap between sending ETH and updating state
- The attack creates a loop: call -> receive -> re-enter -> call -> receive -> ...
- CEI pattern (Checks-Effects-Interactions) is the baseline defense
- `ReentrancyGuard` adds defense in depth at minimal gas cost
- Pull payments eliminate the attack surface entirely
- Glasswing detects the read-call-write pattern automatically

---

**Next:** [Access Control Patterns](./03-access-control-patterns.md) -- protect who can do what in your contracts.
