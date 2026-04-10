// SPDX-License-Identifier: MIT
pragma solidity ^0.8.20;

// ==============================================================================
// VULNERABLE CONTRACT #1: VulnerableBank
// ==============================================================================
// This contract has TWO intentional vulnerabilities:
//   1. Reentrancy in the withdraw() function
//   2. Missing access control on admin functions
//
// DO NOT deploy this contract. It exists for educational purposes only.
// See FIXED_CONTRACTS.sol for the corrected version.
// ==============================================================================

contract VulnerableBank {
    mapping(address => uint256) public balances;
    address public admin;
    bool public paused;

    constructor() {
        admin = msg.sender;
    }

    function deposit() external payable {
        require(!paused, "Contract is paused");
        balances[msg.sender] += msg.value;
    }

    function withdraw() external {
        require(!paused, "Contract is paused");
        uint256 amount = balances[msg.sender];
        require(amount > 0, "No balance to withdraw");

        // VULNERABILITY: Reentrancy -- state updated after external call.
        // The balance is sent to msg.sender BEFORE setting it to zero.
        // If msg.sender is a contract, its receive() function can call
        // withdraw() again before balances[msg.sender] is set to 0.
        (bool success, ) = msg.sender.call{value: amount}("");
        require(success, "Transfer failed");

        // This line executes AFTER the external call.
        // During a reentrancy attack, this line runs multiple times
        // but always after the ETH has already been sent.
        balances[msg.sender] = 0;
    }

    // VULNERABILITY: No access control -- anyone can call these functions.
    // There is no modifier or require statement checking that msg.sender
    // is the admin. An attacker can pause the contract, change the admin
    // to themselves, or drain all funds via emergencyWithdraw.

    function pause() external {
        // Missing: require(msg.sender == admin, "Not admin");
        paused = true;
    }

    function unpause() external {
        // Missing: require(msg.sender == admin, "Not admin");
        paused = false;
    }

    function setAdmin(address newAdmin) external {
        // Missing: require(msg.sender == admin, "Not admin");
        // Missing: require(newAdmin != address(0), "Zero address");
        admin = newAdmin;
    }

    function emergencyWithdraw() external {
        // Missing: require(msg.sender == admin, "Not admin");
        // Anyone can drain the entire contract balance.
        (bool success, ) = msg.sender.call{value: address(this).balance}("");
        require(success, "Transfer failed");
    }
}


// ==============================================================================
// VULNERABLE CONTRACT #2: UnsafeToken
// ==============================================================================
// This contract has TWO intentional vulnerabilities:
//   1. Integer overflow simulation in transfer (using unchecked block
//      to mimic pre-0.8 behavior)
//   2. Missing zero-address checks on transfer and approve
//
// DO NOT deploy this contract. It exists for educational purposes only.
// See FIXED_CONTRACTS.sol for the corrected version.
// ==============================================================================

contract UnsafeToken {
    string public name = "UnsafeToken";
    string public symbol = "UNSAFE";
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
        // VULNERABILITY: Integer overflow via unchecked block.
        // This simulates pre-Solidity-0.8 behavior where arithmetic
        // did not revert on overflow. If a user with balance 0 calls
        // transfer with value 1, the subtraction wraps to type(uint256).max
        // instead of reverting.
        unchecked {
            // If balanceOf[msg.sender] < value, this wraps to a huge number
            // instead of reverting.
            balanceOf[msg.sender] = balanceOf[msg.sender] - value;
            balanceOf[to] = balanceOf[to] + value;
        }

        // VULNERABILITY: No zero-address check.
        // Tokens sent to address(0) are burned permanently with no way
        // to recover them. This should either be prevented or handled
        // through an explicit burn function.

        emit Transfer(msg.sender, to, value);
        return true;
    }

    function approve(address spender, uint256 value) external returns (bool) {
        // VULNERABILITY: No zero-address check on spender.
        // Approving address(0) as a spender is a no-op that wastes gas
        // and may indicate a bug in the calling code.
        allowance[msg.sender][spender] = value;
        emit Approval(msg.sender, spender, value);
        return true;
    }

    function transferFrom(
        address from,
        address to,
        uint256 value
    ) external returns (bool) {
        require(allowance[from][msg.sender] >= value, "Allowance exceeded");

        // VULNERABILITY: Same unchecked overflow issue as transfer().
        unchecked {
            allowance[from][msg.sender] = allowance[from][msg.sender] - value;
            balanceOf[from] = balanceOf[from] - value;
            balanceOf[to] = balanceOf[to] + value;
        }

        // VULNERABILITY: No zero-address check on 'to'.
        emit Transfer(from, to, value);
        return true;
    }
}


// ==============================================================================
// VULNERABLE CONTRACT #3: BrokenAuction
// ==============================================================================
// This contract has TWO intentional vulnerabilities:
//   1. Front-running vulnerability -- bids are visible in the mempool
//      before being mined, and there is no commit-reveal scheme
//   2. Denial of Service via revert in the refund loop -- if one bidder
//      is a contract that reverts on receive, the entire refund loop fails
//
// DO NOT deploy this contract. It exists for educational purposes only.
// See FIXED_CONTRACTS.sol for the corrected version.
// ==============================================================================

contract BrokenAuction {
    address public owner;
    address public highestBidder;
    uint256 public highestBid;
    uint256 public auctionEndTime;
    bool public ended;

    // VULNERABILITY: Front-running exposure.
    // All bids are stored publicly and new bids are visible in the mempool.
    // An attacker monitoring the mempool can see an incoming bid and submit
    // their own bid with a higher gas price to front-run it, always staying
    // one step ahead of legitimate bidders.
    struct Bid {
        address bidder;
        uint256 amount;
    }
    Bid[] public allBids;

    constructor(uint256 durationMinutes) {
        owner = msg.sender;
        auctionEndTime = block.timestamp + (durationMinutes * 1 minutes);
    }

    function bid() external payable {
        require(block.timestamp < auctionEndTime, "Auction has ended");
        require(msg.value > highestBid, "Bid not high enough");

        // Record the bid (publicly visible, enabling front-running)
        allBids.push(Bid({bidder: msg.sender, amount: msg.value}));

        highestBidder = msg.sender;
        highestBid = msg.value;
    }

    function endAuction() external {
        require(block.timestamp >= auctionEndTime, "Auction not yet ended");
        require(!ended, "Auction already ended");
        ended = true;

        // Send the winning bid to the owner
        (bool success, ) = owner.call{value: highestBid}("");
        require(success, "Transfer to owner failed");

        // VULNERABILITY: Denial of Service via revert in refund loop.
        // This loop iterates over ALL bids and sends refunds.
        // If ANY bidder is a contract that reverts in its receive()
        // function, the ENTIRE loop fails. No one gets refunded.
        // Additionally, if there are many bids, this loop may exceed
        // the block gas limit, making it impossible to end the auction.
        for (uint256 i = 0; i < allBids.length; i++) {
            if (allBids[i].bidder != highestBidder) {
                // If this call reverts (e.g., bidder is a contract
                // with a reverting receive), the entire transaction fails.
                (bool refundSuccess, ) = allBids[i].bidder.call{
                    value: allBids[i].amount
                }("");
                require(refundSuccess, "Refund failed");
            }
        }
    }

    function getBidCount() external view returns (uint256) {
        return allBids.length;
    }
}
