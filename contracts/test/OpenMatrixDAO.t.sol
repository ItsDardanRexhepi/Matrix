// SPDX-License-Identifier: MIT
pragma solidity ^0.8.20;

import "forge-std/Test.sol";
import "../OpenMatrixDAO.sol";

/// @title OpenMatrixDAO.t.sol
/// @notice Governance flow: deposit → propose → vote → execute.
contract OpenMatrixDAOTest is Test {
    OpenMatrixDAO internal dao;
    address internal feeRecipient;
    address internal alice;
    address internal bob;

    function setUp() public {
        feeRecipient = makeAddr("feeRecipient");
        alice = makeAddr("alice");
        bob = makeAddr("bob");
        dao = new OpenMatrixDAO(feeRecipient);
    }

    function test_Constructor_RevertsOnZeroRecipient() public {
        vm.expectRevert("Zero fee recipient");
        new OpenMatrixDAO(address(0));
    }

    function test_DepositVotingPower_AccruesWeight() public {
        vm.deal(alice, 10 ether);
        vm.prank(alice);
        dao.depositVotingPower{value: 3 ether}();
        assertEq(dao.votingPower(alice), 3 ether);
        assertEq(dao.totalVotingPower(), 3 ether);
    }

    function test_DepositVotingPower_RevertsOnZero() public {
        vm.prank(alice);
        vm.expectRevert("Must deposit > 0");
        dao.depositVotingPower{value: 0}();
    }

    function test_Propose_RevertsWithoutPower() public {
        address[] memory targets = new address[](1);
        uint256[] memory values = new uint256[](1);
        bytes[] memory calldatas = new bytes[](1);
        targets[0] = address(0xBEEF);
        vm.prank(alice);
        vm.expectRevert("No voting power");
        dao.propose(
            targets,
            values,
            calldatas,
            "do the thing",
            OpenMatrixDAO.VotingModel.SimpleMajority
        );
    }

    function test_Propose_RevertsOnLengthMismatch() public {
        vm.deal(alice, 5 ether);
        vm.prank(alice);
        dao.depositVotingPower{value: 1 ether}();

        address[] memory targets = new address[](2);
        uint256[] memory values = new uint256[](1);
        bytes[] memory calldatas = new bytes[](1);
        vm.prank(alice);
        vm.expectRevert("Length mismatch");
        dao.propose(targets, values, calldatas, "", OpenMatrixDAO.VotingModel.SimpleMajority);
    }

    function test_Propose_CreatesProposal() public {
        vm.deal(alice, 5 ether);
        vm.prank(alice);
        dao.depositVotingPower{value: 1 ether}();

        address[] memory targets = new address[](1);
        uint256[] memory values = new uint256[](1);
        bytes[] memory calldatas = new bytes[](1);
        targets[0] = address(0xBEEF);

        vm.prank(alice);
        uint256 id = dao.propose(
            targets,
            values,
            calldatas,
            "first proposal",
            OpenMatrixDAO.VotingModel.SimpleMajority
        );
        assertEq(id, 0);
    }
}
