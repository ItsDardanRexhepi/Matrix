// SPDX-License-Identifier: MIT
pragma solidity ^0.8.20;

import "forge-std/Test.sol";
import "../MatrixDAO.sol";

/// @title Voting power counts only while it stays deposited.
/// @notice The snapshot is the block before the proposal, so power bought in
///         reaction to a proposal cannot vote on it. But power deposited in
///         the block before and withdrawn in the block of the proposal kept
///         its whole snapshot weight for the vote: a proposer could borrow ETH
///         across one block boundary, propose, repay at once, and outvote the
///         depositors whose ETH the proposal pays out. A vote now weighs the
///         least power the voter held from the snapshot through the vote.
///         These tests use only the existing ABI, so they compile against the
///         previous version too, where the first three fail.
contract MatrixDAOHeldPowerTest is Test {
    MatrixDAO internal dao;
    address internal feeRecipient = makeAddr("feeRecipient");
    address internal honest = makeAddr("honest");
    address internal attacker = makeAddr("attacker");

    event VoteCast(uint256 indexed proposalId, address indexed voter, uint8 support, uint256 weight);

    receive() external payable {}

    function setUp() public {
        dao = new MatrixDAO(feeRecipient);   // this contract is the owner
        vm.deal(honest, 100 ether);
        vm.prank(honest);
        dao.depositVotingPower{value: 100 ether}();
        vm.roll(block.number + 1);
    }

    function _drain(address to, uint256 amount)
        internal view returns (address[] memory t, uint256[] memory v, bytes[] memory c)
    {
        t = new address[](1); v = new uint256[](1); c = new bytes[](1);
        t[0] = address(dao); v[0] = 0;
        c[0] = abi.encodeWithSelector(dao.treasuryWithdraw.selector, to, amount);
    }

    /// @dev Deposit in block N-1; propose and withdraw in block N.
    function _proposeOnBorrowedPower(uint256 amount) internal returns (uint256 id) {
        vm.deal(attacker, amount);
        vm.prank(attacker);
        dao.depositVotingPower{value: amount}();
        vm.roll(block.number + 1);
        (address[] memory t, uint256[] memory v, bytes[] memory c) = _drain(attacker, 100 ether);
        MatrixDAO.VotingModel model = dao.defaultVotingModel();
        vm.prank(attacker);
        id = dao.propose(t, v, c, "pay the attacker", model);
        vm.prank(attacker);
        dao.withdrawVotingPower(amount);    // the loan is repaid in the same block
        vm.roll(block.number + dao.VOTING_DELAY() + 1);
    }

    function test_PowerWithdrawnAfterTheSnapshot_DoesNotVote() public {
        uint256 id = _proposeOnBorrowedPower(101 ether);
        vm.prank(attacker);
        vm.expectRevert("Voting power withdrawn since the snapshot");
        dao.castVote(id, 1);
    }

    function test_TheBorrowedPowerDrain_IsDefeated() public {
        uint256 id = _proposeOnBorrowedPower(101 ether);
        vm.prank(attacker);
        try dao.castVote(id, 1) {} catch {}
        vm.prank(honest);
        dao.castVote(id, 0);
        vm.roll(block.number + dao.VOTING_PERIOD() + 1);
        assertEq(uint8(dao.state(id)), uint8(MatrixDAO.ProposalState.Defeated));
        vm.expectRevert("Not succeeded");
        dao.queue(id);
        assertEq(address(dao).balance, 100 ether, "the depositor's ETH stays");
    }

    function test_PowerPartlyWithdrawn_VotesWithWhatStayed() public {
        address a = makeAddr("a");
        vm.deal(a, 10 ether);
        vm.prank(a);
        dao.depositVotingPower{value: 10 ether}();
        vm.roll(block.number + 1);
        (address[] memory t, uint256[] memory v, bytes[] memory c) = _drain(a, 1 ether);
        MatrixDAO.VotingModel model = dao.defaultVotingModel();
        vm.prank(a);
        uint256 id = dao.propose(t, v, c, "x", model);
        vm.roll(block.number + 1);
        vm.prank(a);
        dao.withdrawVotingPower(6 ether);
        vm.roll(block.number + 1);
        vm.deal(a, 6 ether);
        vm.prank(a);
        dao.depositVotingPower{value: 6 ether}();   // back up again: the low point counts
        vm.roll(block.number + dao.VOTING_DELAY() + 1);
        vm.expectEmit(true, true, false, true, address(dao));
        emit VoteCast(id, a, 1, 4 ether);    // the least it held since the snapshot
        vm.prank(a);
        dao.castVote(id, 1);
    }

    function test_PowerHeldThroughout_VotesInFull() public {
        (address[] memory t, uint256[] memory v, bytes[] memory c) = _drain(honest, 1 ether);
        MatrixDAO.VotingModel model = dao.defaultVotingModel();
        vm.prank(honest);
        uint256 id = dao.propose(t, v, c, "x", model);
        vm.roll(block.number + dao.VOTING_DELAY() + 1);
        vm.expectEmit(true, true, false, true, address(dao));
        emit VoteCast(id, honest, 1, 100 ether);
        vm.prank(honest);
        dao.castVote(id, 1);
    }

    function test_PowerBoughtAfterTheProposal_StillDoesNotCount() public {
        address late = makeAddr("late");
        (address[] memory t, uint256[] memory v, bytes[] memory c) = _drain(late, 1 ether);
        MatrixDAO.VotingModel model = dao.defaultVotingModel();
        vm.prank(honest);
        uint256 id = dao.propose(t, v, c, "x", model);
        vm.deal(late, 500 ether);
        vm.prank(late);
        dao.depositVotingPower{value: 500 ether}();
        vm.roll(block.number + dao.VOTING_DELAY() + 1);
        vm.prank(late);
        vm.expectRevert("No voting power at snapshot");
        dao.castVote(id, 1);
    }
}
