// SPDX-License-Identifier: MIT
pragma solidity ^0.8.20;

import "forge-std/Test.sol";
import "../MatrixDAO.sol";

/// @title The register's sequences for B3-DAO-OWNER-SWEEP and B3-DAO-4PCT-DRAIN.
/// @notice Pre-fix API only, so this compiles against both versions: both
///         tests FAIL at the previous head and pass now.
contract MatrixDAODrainTest is Test {
    MatrixDAO internal dao;
    address internal feeRecipient = makeAddr("feeRecipient");
    address internal attacker = makeAddr("attacker");
    address internal others = makeAddr("others");
    address internal ownerWallet = makeAddr("ownerWallet");

    receive() external payable {}

    function setUp() public {
        dao = new MatrixDAO(feeRecipient);   // this contract is the owner
        vm.deal(others, 23 ether);
        vm.deal(attacker, 1 ether);
        vm.prank(others);
        dao.depositVotingPower{value: 23 ether}();
        vm.prank(attacker);
        dao.depositVotingPower{value: 1 ether}();
        vm.roll(block.number + 1);
    }

    function test_OwnerSweep_Reverts() public {
        vm.expectRevert();
        dao.treasuryWithdraw(ownerWallet, 24 ether);
        assertEq(address(dao).balance, 24 ether, "the depositors' ETH stays");
        assertEq(ownerWallet.balance, 0);
    }

    function test_OneTwentyFourthUnopposed_CannotDrain() public {
        address[] memory targets = new address[](1);
        uint256[] memory values = new uint256[](1);
        bytes[] memory calldatas = new bytes[](1);
        targets[0] = attacker;
        values[0] = 24 ether;
        calldatas[0] = "";

        vm.prank(attacker);
        uint256 id = dao.propose(targets, values, calldatas, "pay me", MatrixDAO.VotingModel.SimpleMajority);
        vm.roll(block.number + dao.VOTING_DELAY() + 1);
        vm.prank(attacker);
        dao.castVote(id, 1);
        vm.roll(block.number + dao.VOTING_PERIOD() + 1);

        vm.expectRevert();
        dao.execute(id);
        assertEq(address(dao).balance, 24 ether, "the treasury did not move");
        assertEq(attacker.balance, 0);
    }
}
