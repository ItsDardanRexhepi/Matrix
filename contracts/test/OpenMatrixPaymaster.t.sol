// SPDX-License-Identifier: MIT
pragma solidity ^0.8.20;

import "forge-std/Test.sol";
import "../OpenMatrixPaymaster.sol";

/// @title OpenMatrixPaymaster.t.sol
/// @notice Unit tests for the gas sponsorship contract.
contract OpenMatrixPaymasterTest is Test {
    OpenMatrixPaymaster internal paymaster;

    address internal constant PLATFORM = address(0xP1A7);
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
}
