// SPDX-License-Identifier: MIT
pragma solidity ^0.8.20;

import "forge-std/Test.sol";
import "../MatrixDAO.sol";

/// @title MatrixDAO.t.sol
/// @notice Governance flow: deposit → propose → vote → execute.
contract MatrixDAOTest is Test {
    MatrixDAO internal dao;
    address internal feeRecipient;
    address internal alice;
    address internal bob;

    function setUp() public {
        feeRecipient = makeAddr("feeRecipient");
        alice = makeAddr("alice");
        bob = makeAddr("bob");
        dao = new MatrixDAO(feeRecipient);
    }

    function test_Constructor_RevertsOnZeroRecipient() public {
        vm.expectRevert("Zero fee recipient");
        new MatrixDAO(address(0));
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
            MatrixDAO.VotingModel.SimpleMajority
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
        dao.propose(targets, values, calldatas, "", MatrixDAO.VotingModel.SimpleMajority);
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
            MatrixDAO.VotingModel.SimpleMajority
        );
        assertEq(id, 0);
    }

    // ── B3-DAO-OWNER-SWEEP / B3-DAO-4PCT-DRAIN: the governed path ─────────

    function _proposal(address to, uint256 amount)
        internal view returns (address[] memory t, uint256[] memory v, bytes[] memory c)
    {
        t = new address[](1); v = new uint256[](1); c = new bytes[](1);
        t[0] = address(dao); v[0] = 0;
        c[0] = abi.encodeWithSelector(dao.treasuryWithdraw.selector, to, amount);
    }

    function test_Treasury_OnlyThroughAPassedQueuedTimelockedProposal() public {
        address big = makeAddr("big"); address to = makeAddr("to");
        vm.deal(big, 30 ether);
        vm.prank(big);
        dao.depositVotingPower{value: 30 ether}();
        vm.roll(block.number + 1);
        (address[] memory t, uint256[] memory v, bytes[] memory c) = _proposal(to, 10 ether);
        MatrixDAO.VotingModel model = dao.defaultVotingModel();
        vm.prank(big);
        uint256 id = dao.propose(t, v, c, "grant", model);
        vm.roll(block.number + dao.VOTING_DELAY() + 1);
        vm.prank(big);
        dao.castVote(id, 1);
        vm.roll(block.number + dao.VOTING_PERIOD() + 1);
        assertEq(uint8(dao.state(id)), uint8(MatrixDAO.ProposalState.Succeeded));

        vm.expectRevert("Not queued");
        dao.execute(id);
        dao.queue(id);
        vm.expectRevert("Timelock not elapsed");
        dao.execute(id);
        vm.warp(block.timestamp + dao.TIMELOCK_DELAY());
        dao.execute(id);
        assertGt(to.balance, 9.9 ether, "the grant, minus the tiered fee");
    }

    function test_VotingPower_CanBeWithdrawn() public {
        address a = makeAddr("a");
        vm.deal(a, 2 ether);
        vm.prank(a);
        dao.depositVotingPower{value: 2 ether}();
        vm.prank(a);
        dao.withdrawVotingPower(2 ether);
        assertEq(a.balance, 2 ether);
        assertEq(dao.totalVotingPower(), 0);
    }

    function test_PowerBoughtAfterTheProposal_DoesNotCount() public {
        address a = makeAddr("a"); address late = makeAddr("late");
        vm.deal(a, 1 ether); vm.deal(late, 100 ether);
        vm.prank(a);
        dao.depositVotingPower{value: 1 ether}();
        vm.roll(block.number + 1);
        (address[] memory t, uint256[] memory v, bytes[] memory c) = _proposal(late, 1 ether);
        MatrixDAO.VotingModel model = dao.defaultVotingModel();
        vm.prank(a);
        uint256 id = dao.propose(t, v, c, "x", model);
        vm.prank(late);
        dao.depositVotingPower{value: 100 ether}();   // after the snapshot
        vm.roll(block.number + dao.VOTING_DELAY() + 1);
        vm.prank(late);
        vm.expectRevert("No voting power at snapshot");
        dao.castVote(id, 1);
    }

    function test_ProposerCannotPickTheVotingModel() public {
        address a = makeAddr("a");
        vm.deal(a, 1 ether);
        vm.prank(a);
        dao.depositVotingPower{value: 1 ether}();
        vm.roll(block.number + 1);
        dao.setVotingModel(MatrixDAO.VotingModel.SuperMajority);
        (address[] memory t, uint256[] memory v, bytes[] memory c) = _proposal(a, 1);
        vm.prank(a);
        vm.expectRevert("Voting model is governance-set");
        dao.propose(t, v, c, "x", MatrixDAO.VotingModel.SimpleMajority);
    }
}
