// SPDX-License-Identifier: MIT
pragma solidity ^0.8.20;

import "forge-std/Test.sol";
import "../MatrixStaking.sol";

contract RevertingRecipient {
    receive() external payable { revert("no"); }
}

/// @title The register's sequences for B3-STAKE-SHORTFALL-ERASES,
///        B3-STAKE-PRINCIPAL-PAYS-REWARDS and B3-STAKE-FEE-FREEZE.
/// @notice Pre-fix API only: both tests FAIL at the previous head and pass now.
contract MatrixStakingShortfallTest is Test {
    MatrixStaking internal staking;
    address internal feeRecipient = makeAddr("feeRecipient");
    address internal a = makeAddr("a");
    address internal b = makeAddr("b");

    function setUp() public {
        staking = new MatrixStaking(feeRecipient);   // this contract is the owner
        vm.deal(a, 1 ether);
        vm.deal(b, 1 ether);
    }

    function test_TheLateExitKeepsItsPrincipal() public {
        vm.prank(a);
        staking.stake{value: 1 ether}();
        vm.prank(b);
        staking.stake{value: 1 ether}();
        vm.warp(block.timestamp + 365 days);   // rewards accrue; nobody funded them

        vm.prank(a);
        staking.unstake();
        uint256 bBefore = b.balance;
        vm.prank(b);
        staking.unstake();
        assertGe(b.balance - bBefore, 1 ether, "B's principal must come back in full");
        assertGe(a.balance, 1 ether, "A's principal too");
    }

    function test_ARevertingFeeRecipientFreezesNoExit() public {
        staking.updateFeeRecipient(address(new RevertingRecipient()));
        staking.fundRewards{value: 10 ether}();
        vm.deal(address(this), 0);
        vm.prank(a);
        staking.stake{value: 1 ether}();
        vm.warp(block.timestamp + 30 days);
        vm.prank(a);
        staking.unstake();
        assertGe(a.balance, 1 ether, "the exit went through");
    }

    receive() external payable {}
}
