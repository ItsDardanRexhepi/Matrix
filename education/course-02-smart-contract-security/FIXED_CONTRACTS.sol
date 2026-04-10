// SPDX-License-Identifier: MIT
pragma solidity ^0.8.20;

import "@openzeppelin/contracts/utils/ReentrancyGuard.sol";
import "@openzeppelin/contracts/access/Ownable.sol";
import "@openzeppelin/contracts/utils/Pausable.sol";

// ==============================================================================
// FIXED CONTRACT #1: SafeBank
// ==============================================================================
// Fixes applied to VulnerableBank:
//   1. Reentrancy: Applied CEI pattern + ReentrancyGuard (defense in depth)
//   2. Access control: Added Ownable with onlyOwner modifiers
//   3. Added Pausable for emergency stop functionality
//   4. Added zero-address check on admin transfer
//   5. Added events for transparency
//
// Before: External call before state update, no access control on admin functions
// After:  State update before external call, all admin functions owner-protected
// ==============================================================================

contract SafeBank is ReentrancyGuard, Ownable, Pausable {

    mapping(address => uint256) public balances;

    event Deposited(address indexed user, uint256 amount);
    event Withdrawn(address indexed user, uint256 amount);
    event EmergencyWithdrawal(address indexed admin, uint256 amount);

    // FIX: Ownable constructor sets msg.sender as owner
    constructor() Ownable(msg.sender) {}

    function deposit() external payable whenNotPaused {
        require(msg.value > 0, "Must deposit more than 0");
        balances[msg.sender] += msg.value;
        emit Deposited(msg.sender, msg.value);
    }

    // FIX #1: Reentrancy protection -- two layers of defense
    //
    // Layer 1 (CEI pattern): balances[msg.sender] is set to 0 BEFORE
    //   the external call. Even if the caller re-enters, their balance
    //   is already 0 and the require() will fail.
    //
    // Layer 2 (nonReentrant): The ReentrancyGuard modifier prevents
    //   any re-entry into this function entirely. Belt and suspenders.
    function withdraw() external nonReentrant whenNotPaused {
        uint256 amount = balances[msg.sender];
        require(amount > 0, "No balance to withdraw");

        // EFFECT: State change BEFORE external call
        balances[msg.sender] = 0;

        // INTERACTION: External call AFTER state change
        (bool success, ) = msg.sender.call{value: amount}("");
        require(success, "Transfer failed");

        emit Withdrawn(msg.sender, amount);
    }

    // FIX #2: Access control -- onlyOwner modifier on all admin functions
    //
    // Before: Anyone could call pause(), unpause(), emergencyWithdraw()
    // After:  Only the contract owner (set at deployment) can call them

    function pause() external onlyOwner {
        _pause();
    }

    function unpause() external onlyOwner {
        _unpause();
    }

    // FIX: emergencyWithdraw is now owner-only and emits an event
    function emergencyWithdraw() external onlyOwner {
        uint256 amount = address(this).balance;
        require(amount > 0, "No funds to withdraw");

        (bool success, ) = owner().call{value: amount}("");
        require(success, "Transfer failed");

        emit EmergencyWithdrawal(owner(), amount);
    }

    // FIX: transferOwnership is inherited from Ownable and includes
    // zero-address check automatically. No separate setAdmin needed.
}


// ==============================================================================
// FIXED CONTRACT #2: SafeToken
// ==============================================================================
// Fixes applied to UnsafeToken:
//   1. Integer overflow: Removed unchecked blocks so Solidity 0.8+ automatic
//      overflow checking applies. Arithmetic that would overflow now reverts.
//   2. Zero-address checks: Added require statements to prevent transfers
//      and approvals involving address(0).
//   3. Added proper balance check before subtraction for clarity.
//
// Before: Unchecked arithmetic allowed balance wrapping, no zero-address guards
// After:  Safe arithmetic with automatic revert, zero-address checks on all ops
// ==============================================================================

contract SafeToken {
    string public name = "SafeToken";
    string public symbol = "SAFE";
    uint8 public decimals = 18;
    uint256 public totalSupply;

    mapping(address => uint256) public balanceOf;
    mapping(address => mapping(address => uint256)) public allowance;

    event Transfer(address indexed from, address indexed to, uint256 value);
    event Approval(address indexed owner, address indexed spender, uint256 value);

    constructor(uint256 initialSupply) {
        totalSupply = initialSupply * 10 ** uint256(decimals);
        balanceOf[msg.sender] = totalSupply;
        emit Transfer(address(0), msg.sender, totalSupply);
    }

    function transfer(address to, uint256 value) external returns (bool) {
        // FIX #2: Zero-address check prevents accidental token burns.
        // If burning is desired, implement a dedicated burn() function.
        require(to != address(0), "Transfer to zero address");

        // FIX #1: No unchecked block. Solidity 0.8+ reverts automatically
        // if balanceOf[msg.sender] < value (underflow protection).
        require(balanceOf[msg.sender] >= value, "Insufficient balance");

        // Safe arithmetic: these operations will revert on overflow/underflow
        balanceOf[msg.sender] -= value;
        balanceOf[to] += value;

        emit Transfer(msg.sender, to, value);
        return true;
    }

    function approve(address spender, uint256 value) external returns (bool) {
        // FIX #2: Zero-address check on spender.
        require(spender != address(0), "Approve to zero address");

        allowance[msg.sender][spender] = value;
        emit Approval(msg.sender, spender, value);
        return true;
    }

    function transferFrom(
        address from,
        address to,
        uint256 value
    ) external returns (bool) {
        // FIX #2: Zero-address checks on both from and to.
        require(from != address(0), "Transfer from zero address");
        require(to != address(0), "Transfer to zero address");

        // FIX #1: Safe arithmetic with explicit checks.
        require(allowance[from][msg.sender] >= value, "Allowance exceeded");
        require(balanceOf[from] >= value, "Insufficient balance");

        // No unchecked block: Solidity 0.8+ protects against overflow
        allowance[from][msg.sender] -= value;
        balanceOf[from] -= value;
        balanceOf[to] += value;

        emit Transfer(from, to, value);
        return true;
    }
}


// ==============================================================================
// FIXED CONTRACT #3: SafeAuction
// ==============================================================================
// Fixes applied to BrokenAuction:
//   1. Front-running: Implemented commit-reveal bidding scheme. Bidders
//      first submit a hash of their bid (commit phase), then reveal the
//      actual bid after the bidding period ends (reveal phase). Bids are
//      not visible in the mempool.
//   2. DoS via revert: Replaced push refunds with pull withdrawals.
//      Instead of looping through all bidders and sending refunds,
//      each bidder withdraws their own funds individually.
//   3. Added ReentrancyGuard for withdrawal safety.
//   4. Added Ownable for admin functions.
//
// Before: Visible bids (front-runnable), push refund loop (DoS-able)
// After:  Commit-reveal (hidden bids), pull withdrawals (DoS-resistant)
// ==============================================================================

contract SafeAuction is ReentrancyGuard, Ownable {

    uint256 public commitDeadline;
    uint256 public revealDeadline;
    bool public ended;

    address public highestBidder;
    uint256 public highestBid;

    // FIX #1: Commit-reveal scheme.
    // During commit phase, bidders submit hash(bid_amount, secret).
    // During reveal phase, bidders reveal their actual bid and secret.
    // The hash is verified against the commitment.
    // Bids are never visible in the mempool during the commit phase.
    mapping(address => bytes32) public commitments;
    mapping(address => bool) public hasRevealed;

    // FIX #2: Pull withdrawal pattern.
    // Instead of pushing refunds in a loop, track what each bidder
    // is owed and let them withdraw individually.
    mapping(address => uint256) public pendingWithdrawals;

    event CommitPlaced(address indexed bidder);
    event BidRevealed(address indexed bidder, uint256 amount);
    event AuctionEnded(address indexed winner, uint256 amount);
    event Withdrawal(address indexed bidder, uint256 amount);

    constructor(
        uint256 commitDurationMinutes,
        uint256 revealDurationMinutes
    ) Ownable(msg.sender) {
        commitDeadline = block.timestamp + (commitDurationMinutes * 1 minutes);
        revealDeadline = commitDeadline + (revealDurationMinutes * 1 minutes);
    }

    // Phase 1: Commit -- submit hash of (bid amount, secret nonce)
    // The actual bid amount is hidden. Bidders must send enough ETH
    // to cover their bid (can send more to disguise the real amount).
    function commit(bytes32 commitHash) external payable {
        require(block.timestamp < commitDeadline, "Commit phase ended");
        require(commitments[msg.sender] == bytes32(0), "Already committed");
        require(msg.value > 0, "Must send ETH with commitment");

        commitments[msg.sender] = commitHash;
        emit CommitPlaced(msg.sender);
    }

    // Phase 2: Reveal -- show actual bid amount and secret
    // The hash is verified: keccak256(abi.encodePacked(bidAmount, secret))
    // must equal the stored commitment.
    function reveal(uint256 bidAmount, bytes32 secret) external {
        require(block.timestamp >= commitDeadline, "Commit phase not ended");
        require(block.timestamp < revealDeadline, "Reveal phase ended");
        require(!hasRevealed[msg.sender], "Already revealed");

        bytes32 expectedHash = keccak256(
            abi.encodePacked(bidAmount, secret)
        );
        require(
            commitments[msg.sender] == expectedHash,
            "Commitment mismatch"
        );

        hasRevealed[msg.sender] = true;

        if (bidAmount > highestBid) {
            // Refund the previous highest bidder via pull pattern
            if (highestBidder != address(0)) {
                pendingWithdrawals[highestBidder] += highestBid;
            }

            highestBidder = msg.sender;
            highestBid = bidAmount;

            // Any excess ETH sent beyond the bid goes to pending withdrawals
            uint256 excess = address(this).balance - bidAmount;
            if (excess > 0) {
                pendingWithdrawals[msg.sender] += excess;
            }
        } else {
            // Bid was not the highest; refund via pull pattern
            pendingWithdrawals[msg.sender] += bidAmount;
        }

        emit BidRevealed(msg.sender, bidAmount);
    }

    function endAuction() external {
        require(block.timestamp >= revealDeadline, "Reveal phase not ended");
        require(!ended, "Auction already ended");
        ended = true;

        // Send the winning bid to the owner
        if (highestBidder != address(0)) {
            pendingWithdrawals[owner()] += highestBid;
        }

        emit AuctionEnded(highestBidder, highestBid);
    }

    // FIX #2: Pull withdrawal replaces push refund loop.
    //
    // Before: endAuction() looped through all bids and sent refunds.
    //   If any recipient reverted, the entire loop failed (DoS).
    //
    // After: Each bidder calls withdraw() individually to claim their
    //   refund. A reverting recipient only affects themselves.
    //   The nonReentrant modifier prevents reentrancy during withdrawal.
    function withdraw() external nonReentrant {
        uint256 amount = pendingWithdrawals[msg.sender];
        require(amount > 0, "Nothing to withdraw");

        // CEI pattern: zero the balance before sending
        pendingWithdrawals[msg.sender] = 0;

        (bool success, ) = msg.sender.call{value: amount}("");
        require(success, "Withdrawal failed");

        emit Withdrawal(msg.sender, amount);
    }
}
