// SPDX-License-Identifier: MIT
pragma solidity ^0.8.20;

import "@openzeppelin/contracts/utils/ReentrancyGuard.sol";

/**
 * @title MatrixPaymaster
 * @custom:status SUPERSEDED — this repository's tooling does not deploy it.
 *         The platform's paymaster is MatrixVerifyingPaymaster (ERC-4337 v0.6),
 *         which pays gas out of its own EntryPoint deposit and is the only
 *         paymaster address the server reads (blockchain.paymaster.address).
 *         `sponsoredCall(address,bytes)` here reaches ANY address with ANY
 *         calldata from any authorized key, and `sponsoredCallWithValue` does it
 *         carrying ETH; nothing in the runtime calls either. contracts/deploy.py
 *         no longer deploys this, scripts/deploy_and_configure.sh no longer
 *         funds it, and a deployment manifest that names it is refused by
 *         scripts/refuse_legacy_contracts.py — see
 *         tests/test_the_legacy_paymaster_is_not_deployed.py. The source and its
 *         foundry test stay because an instance already on a chain still needs
 *         to be readable; putting a NEW one there is now a deliberate manual
 *         act, not a side effect of running the tools.
 * @notice Gas sponsorship contract for the Matrix platform.
 *         The platform covers all gas fees for users — users never pay gas.
 *         This contract holds ETH and sponsors transactions on behalf of users.
 * @dev All ETH-moving functions are nonReentrant, matching every sibling
 *      contract. This matters because withdraw/sponsoredCall* now use `.call`
 *      (which forwards all gas) instead of `.transfer` (2300-gas stipend):
 *      the guard closes the reentrancy surface that the gas-forwarding opens.
 */
contract MatrixPaymaster is ReentrancyGuard {
    address public owner;
    address public platform;

    mapping(address => bool) public authorizedAgents;

    uint256 public totalSponsored;
    uint256 public totalTransactions;

    // ── Value-call policy (mirrors the server paymaster policy.allowed_actions) ──
    // A compromised/authorized AGENT key must not be able to drain funds or hit
    // an arbitrary target via sponsoredCallWithValue. The owner is trusted and
    // exempt; agents are constrained by a per-agent daily value cap and an
    // optional target allowlist. Both default to the tightest setting
    // (cap = 0 → agents cannot move value until the owner grants an allowance).
    uint256 public agentDailyCap;
    bool public targetAllowlistEnabled;
    mapping(address => bool) public allowedTargets;
    mapping(address => uint256) public agentSpentToday;
    mapping(address => uint256) public agentDayStart;

    event GasSponsored(address indexed user, uint256 amount, string action);
    event AgentAuthorized(address indexed agent);
    event AgentRevoked(address indexed agent);
    event FundsDeposited(address indexed from, uint256 amount);
    event FundsWithdrawn(address indexed to, uint256 amount);
    event AgentDailyCapSet(uint256 cap);
    event TargetAllowed(address indexed target, bool allowed);
    event TargetAllowlistEnabledSet(bool enabled);

    modifier onlyOwner() {
        require(msg.sender == owner, "Only owner");
        _;
    }

    modifier onlyAuthorized() {
        require(msg.sender == owner || authorizedAgents[msg.sender], "Not authorized");
        _;
    }

    constructor(address _platform) {
        owner = msg.sender;
        platform = _platform;
        authorizedAgents[msg.sender] = true;
    }

    /// @notice Deposit ETH to fund gas sponsorship
    receive() external payable {
        emit FundsDeposited(msg.sender, msg.value);
    }

    /// @notice Sponsor a transaction's gas for a user
    /// @param user The user whose gas is being covered
    /// @param action Description of the action being sponsored
    function sponsorGas(address user, string calldata action) external onlyAuthorized {
        totalTransactions++;
        emit GasSponsored(user, tx.gasprice * gasleft(), action);
    }

    /// @notice Execute a sponsored call to a target contract
    /// @param target Contract to call
    /// @param data Calldata to send
    function sponsoredCall(address target, bytes calldata data) external onlyAuthorized nonReentrant returns (bytes memory) {
        totalTransactions++;
        totalSponsored += tx.gasprice * gasleft();
        (bool success, bytes memory result) = target.call(data);
        require(success, "Sponsored call failed");
        return result;
    }

    /// @notice Execute a sponsored call with ETH value
    /// @dev The owner is unrestricted. A non-owner AGENT is bound by the target
    ///      allowlist (when enabled) and a per-agent daily value cap, so a
    ///      compromised agent key cannot drain funds or reach an arbitrary
    ///      target. The cap resets on a rolling 1-day bucket.
    function sponsoredCallWithValue(address target, bytes calldata data, uint256 value) external onlyAuthorized nonReentrant returns (bytes memory) {
        require(address(this).balance >= value, "Insufficient balance");
        if (msg.sender != owner && value > 0) {
            if (targetAllowlistEnabled) {
                require(allowedTargets[target], "Target not allowlisted");
            }
            // Not a random draw. This is the start of the current UTC day, used
            // to bucket a DAILY SPEND CAP. Nothing is selected by it and nothing
            // is won; a miner nudging the timestamp would only shift the cap
            // window slightly, which a daily cap already tolerates.
            // slither-disable-next-line weak-prng
            uint256 dayStart = block.timestamp - (block.timestamp % 1 days);
            if (agentDayStart[msg.sender] != dayStart) {
                agentDayStart[msg.sender] = dayStart;
                agentSpentToday[msg.sender] = 0;
            }
            require(agentSpentToday[msg.sender] + value <= agentDailyCap, "Agent daily cap exceeded");
            agentSpentToday[msg.sender] += value;
        }
        totalTransactions++;
        totalSponsored += tx.gasprice * gasleft();
        (bool success, bytes memory result) = target.call{value: value}(data);
        require(success, "Sponsored call failed");
        return result;
    }

    /// @notice Set the per-agent daily value cap (wei). Default 0 blocks all
    ///         agent value-calls until the owner grants an allowance.
    function setAgentDailyCap(uint256 cap) external onlyOwner {
        agentDailyCap = cap;
        emit AgentDailyCapSet(cap);
    }

    /// @notice Allow/deny a target for agent value-calls (used when the
    ///         allowlist is enabled).
    function setTargetAllowed(address target, bool allowed) external onlyOwner {
        allowedTargets[target] = allowed;
        emit TargetAllowed(target, allowed);
    }

    /// @notice Enable/disable the target allowlist for agent value-calls.
    function setTargetAllowlistEnabled(bool enabled) external onlyOwner {
        targetAllowlistEnabled = enabled;
        emit TargetAllowlistEnabledSet(enabled);
    }

    /// @notice Authorize an agent address to sponsor gas
    function authorizeAgent(address agent) external onlyOwner {
        authorizedAgents[agent] = true;
        emit AgentAuthorized(agent);
    }

    /// @notice Revoke an agent's authorization
    function revokeAgent(address agent) external onlyOwner {
        authorizedAgents[agent] = false;
        emit AgentRevoked(agent);
    }

    /// @notice Withdraw funds (owner only)
    /// @dev Uses call, not transfer: the 2300-gas stipend would permanently
    ///      strand funds if ownership moves to a smart-contract wallet
    ///      (multisig / ERC-4337 account) whose receive needs more gas.
    function withdraw(uint256 amount) external onlyOwner nonReentrant {
        require(address(this).balance >= amount, "Insufficient balance");
        (bool ok, ) = payable(owner).call{value: amount}("");
        require(ok, "Withdraw failed");
        emit FundsWithdrawn(owner, amount);
    }

    /// @notice Get contract balance
    function balance() external view returns (uint256) {
        return address(this).balance;
    }

    /// @notice Get sponsorship stats
    function stats() external view returns (uint256 _totalSponsored, uint256 _totalTransactions, uint256 _balance) {
        return (totalSponsored, totalTransactions, address(this).balance);
    }

    /// @notice Transfer ownership
    function transferOwnership(address newOwner) external onlyOwner {
        require(newOwner != address(0), "Invalid address");
        owner = newOwner;
    }
}
