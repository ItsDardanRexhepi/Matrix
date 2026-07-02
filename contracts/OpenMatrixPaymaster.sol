// SPDX-License-Identifier: MIT
pragma solidity ^0.8.20;

import "@openzeppelin/contracts/utils/ReentrancyGuard.sol";

/**
 * @title OpenMatrixPaymaster
 * @notice Gas sponsorship contract for the 0pnMatrx platform.
 *         The platform covers all gas fees for users — users never pay gas.
 *         This contract holds ETH and sponsors transactions on behalf of users.
 * @dev All ETH-moving functions are nonReentrant, matching every sibling
 *      contract. This matters because withdraw/sponsoredCall* now use `.call`
 *      (which forwards all gas) instead of `.transfer` (2300-gas stipend):
 *      the guard closes the reentrancy surface that the gas-forwarding opens.
 */
contract OpenMatrixPaymaster is ReentrancyGuard {
    address public owner;
    address public platform;

    mapping(address => bool) public authorizedAgents;

    uint256 public totalSponsored;
    uint256 public totalTransactions;

    event GasSponsored(address indexed user, uint256 amount, string action);
    event AgentAuthorized(address indexed agent);
    event AgentRevoked(address indexed agent);
    event FundsDeposited(address indexed from, uint256 amount);
    event FundsWithdrawn(address indexed to, uint256 amount);

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
    function sponsoredCallWithValue(address target, bytes calldata data, uint256 value) external onlyAuthorized nonReentrant returns (bytes memory) {
        require(address(this).balance >= value, "Insufficient balance");
        totalTransactions++;
        totalSponsored += tx.gasprice * gasleft();
        (bool success, bytes memory result) = target.call{value: value}(data);
        require(success, "Sponsored call failed");
        return result;
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
