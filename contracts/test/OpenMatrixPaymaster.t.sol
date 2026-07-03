// SPDX-License-Identifier: MIT
pragma solidity ^0.8.20;

import "forge-std/Test.sol";
import "../OpenMatrixPaymaster.sol";

/// @title OpenMatrixPaymaster.t.sol
/// @notice Unit tests for the gas sponsorship contract.
contract OpenMatrixPaymasterTest is Test {
    OpenMatrixPaymaster internal paymaster;

    address internal constant PLATFORM = address(0x1A7) /* was invalid literal 0xP1A7 — "P" is not hex (P0-3 adjacent fix) */;
    address internal owner;
    address internal agent;
    address internal stranger;
    address internal user;

    event GasSponsored(address indexed user, uint256 amount, string action);
    event AgentAuthorized(address indexed agent);
    event AgentRevoked(address indexed agent);
    event FundsDeposited(address indexed from, uint256 amount);
    event FundsWithdrawn(address indexed to, uint256 amount);

    function setUp() public {
        owner = address(this);
        agent = makeAddr("agent");
        stranger = makeAddr("stranger");
        user = makeAddr("user");
        paymaster = new OpenMatrixPaymaster(PLATFORM);
    }

    /// The test contract is the paymaster owner (deployer); without this it
    /// cannot accept ETH and every withdraw reverts at the value transfer.
    receive() external payable {}

    function test_Constructor_SetsOwnerAndPlatform() public view {
        assertEq(paymaster.owner(), owner);
        assertEq(paymaster.platform(), PLATFORM);
        assertTrue(paymaster.authorizedAgents(owner));
    }

    function test_Receive_EmitsDepositEvent() public {
        vm.deal(user, 1 ether);
        vm.prank(user);
        vm.expectEmit(true, false, false, true);
        emit FundsDeposited(user, 0.5 ether);
        (bool ok, ) = address(paymaster).call{value: 0.5 ether}("");
        assertTrue(ok);
        assertEq(paymaster.balance(), 0.5 ether);
    }

    function test_AuthorizeAgent_UpdatesMapping() public {
        vm.expectEmit(true, false, false, false);
        emit AgentAuthorized(agent);
        paymaster.authorizeAgent(agent);
        assertTrue(paymaster.authorizedAgents(agent));
    }

    function test_RevokeAgent_ClearsMapping() public {
        paymaster.authorizeAgent(agent);
        assertTrue(paymaster.authorizedAgents(agent));
        vm.expectEmit(true, false, false, false);
        emit AgentRevoked(agent);
        paymaster.revokeAgent(agent);
        assertFalse(paymaster.authorizedAgents(agent));
    }

    function test_AuthorizeAgent_RevertsForStranger() public {
        vm.prank(stranger);
        vm.expectRevert("Only owner");
        paymaster.authorizeAgent(agent);
    }

    function test_SponsorGas_IncrementsCounter() public {
        paymaster.authorizeAgent(agent);
        vm.prank(agent);
        paymaster.sponsorGas(user, "test-action");
        assertEq(paymaster.totalTransactions(), 1);
    }

    function test_SponsorGas_RevertsForUnauthorized() public {
        vm.prank(stranger);
        vm.expectRevert("Not authorized");
        paymaster.sponsorGas(user, "anything");
    }

    function test_Withdraw_MovesFundsToOwner() public {
        vm.deal(address(paymaster), 1 ether);
        uint256 before = owner.balance;
        paymaster.withdraw(0.25 ether);
        assertEq(owner.balance - before, 0.25 ether);
        assertEq(paymaster.balance(), 0.75 ether);
    }

    function test_Withdraw_RevertsOnInsufficientBalance() public {
        vm.deal(address(paymaster), 0.1 ether);
        vm.expectRevert("Insufficient balance");
        paymaster.withdraw(1 ether);
    }

    function test_Withdraw_RevertsForStranger() public {
        vm.deal(address(paymaster), 1 ether);
        vm.prank(stranger);
        vm.expectRevert("Only owner");
        paymaster.withdraw(0.1 ether);
    }

    /// Proof for the .transfer -> .call fix: a smart-contract owner whose
    /// receive() needs more than the 2300-gas stipend can still withdraw.
    /// Under the old payable(owner).transfer(...) this test fails.
    function test_Withdraw_WorksForContractWalletOwner() public {
        GasHungryWallet wallet = new GasHungryWallet();
        paymaster.transferOwnership(address(wallet));
        vm.deal(address(paymaster), 1 ether);
        wallet.pullFromPaymaster(paymaster, 0.25 ether);
        assertEq(address(wallet).balance, 0.25 ether);
        assertEq(paymaster.balance(), 0.75 ether);
    }

    /// Honest failure: if the owner cannot accept ETH the withdraw reverts
    /// ("Withdraw failed") — funds stay in the paymaster, no silent loss.
    function test_Withdraw_RevertsWhenOwnerRejectsEth() public {
        RejectingWallet wallet = new RejectingWallet();
        paymaster.transferOwnership(address(wallet));
        vm.deal(address(paymaster), 1 ether);
        vm.expectRevert("Withdraw failed");
        wallet.pullFromPaymaster(paymaster, 0.25 ether);
        assertEq(paymaster.balance(), 1 ether);
    }

    function test_TransferOwnership_UpdatesOwner() public {
        address newOwner = makeAddr("newOwner");
        paymaster.transferOwnership(newOwner);
        assertEq(paymaster.owner(), newOwner);
    }

    function test_TransferOwnership_RevertsOnZero() public {
        vm.expectRevert("Invalid address");
        paymaster.transferOwnership(address(0));
    }

    function test_Stats_ReportsCurrentValues() public {
        vm.deal(address(paymaster), 2 ether);
        (uint256 sponsored, uint256 txs, uint256 bal) = paymaster.stats();
        assertEq(sponsored, 0);
        assertEq(txs, 0);
        assertEq(bal, 2 ether);
    }

    // ── sponsoredCallWithValue agent policy (per-agent daily cap + allowlist) ──

    function test_AgentValueCall_BlockedByDefault() public {
        // Default cap is 0 → a compromised/authorized agent cannot move value.
        vm.deal(address(paymaster), 1 ether);
        paymaster.authorizeAgent(agent);
        address target = makeAddr("target");
        vm.prank(agent);
        vm.expectRevert("Agent daily cap exceeded");
        paymaster.sponsoredCallWithValue(target, "", 0.1 ether);
    }

    function test_AgentValueCall_WithinCapSucceeds_ThenCumulativeCapReverts() public {
        vm.deal(address(paymaster), 2 ether);
        paymaster.authorizeAgent(agent);
        paymaster.setAgentDailyCap(1 ether);
        address target = makeAddr("target");
        vm.prank(agent);
        paymaster.sponsoredCallWithValue(target, "", 0.6 ether); // ok
        assertEq(paymaster.agentSpentToday(agent), 0.6 ether);
        vm.prank(agent);
        vm.expectRevert("Agent daily cap exceeded"); // 0.6 + 0.6 > 1.0
        paymaster.sponsoredCallWithValue(target, "", 0.6 ether);
    }

    function test_AgentValueCall_DailyCapResetsNextDay() public {
        vm.deal(address(paymaster), 3 ether);
        paymaster.authorizeAgent(agent);
        paymaster.setAgentDailyCap(1 ether);
        address target = makeAddr("target");
        vm.prank(agent);
        paymaster.sponsoredCallWithValue(target, "", 1 ether); // fills the cap
        vm.warp(block.timestamp + 1 days + 1);
        vm.prank(agent);
        paymaster.sponsoredCallWithValue(target, "", 1 ether); // new day, ok
        assertEq(paymaster.agentSpentToday(agent), 1 ether);
    }

    function test_AgentValueCall_TargetAllowlistEnforced() public {
        vm.deal(address(paymaster), 2 ether);
        paymaster.authorizeAgent(agent);
        paymaster.setAgentDailyCap(1 ether);
        paymaster.setTargetAllowlistEnabled(true);
        address bad = makeAddr("bad");
        address good = makeAddr("good");
        vm.prank(agent);
        vm.expectRevert("Target not allowlisted");
        paymaster.sponsoredCallWithValue(bad, "", 0.1 ether);
        paymaster.setTargetAllowed(good, true);
        vm.prank(agent);
        paymaster.sponsoredCallWithValue(good, "", 0.1 ether); // ok
    }

    function test_OwnerValueCall_IsUnrestricted() public {
        // The owner is trusted: no cap, no allowlist — even with defaults.
        vm.deal(address(paymaster), 1 ether);
        address target = makeAddr("target");
        paymaster.sponsoredCallWithValue(target, "", 0.5 ether); // owner, ok
        assertEq(target.balance, 0.5 ether);
    }

    function test_PolicySetters_OnlyOwner() public {
        vm.prank(stranger);
        vm.expectRevert("Only owner");
        paymaster.setAgentDailyCap(1 ether);
        vm.prank(stranger);
        vm.expectRevert("Only owner");
        paymaster.setTargetAllowlistEnabled(true);
        vm.prank(stranger);
        vm.expectRevert("Only owner");
        paymaster.setTargetAllowed(makeAddr("t"), true);
    }
}

/// Owner stand-in whose receive() costs more than the 2300-gas transfer
/// stipend (SSTORE) — models a multisig / ERC-4337 smart-contract wallet.
contract GasHungryWallet {
    uint256 public received;

    receive() external payable {
        received += msg.value; // SSTORE: > 2300 gas, breaks .transfer()
    }

    function pullFromPaymaster(OpenMatrixPaymaster paymaster, uint256 amount) external {
        paymaster.withdraw(amount);
    }
}

/// Owner stand-in that refuses ETH entirely.
contract RejectingWallet {
    receive() external payable {
        revert("no ETH");
    }

    function pullFromPaymaster(OpenMatrixPaymaster paymaster, uint256 amount) external {
        paymaster.withdraw(amount);
    }
}
