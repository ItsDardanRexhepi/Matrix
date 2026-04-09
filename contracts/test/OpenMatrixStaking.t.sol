// SPDX-License-Identifier: MIT
pragma solidity ^0.8.20;

import "forge-std/Test.sol";
import "../OpenMatrixStaking.sol";

/// @title OpenMatrixStaking.t.sol
/// @notice Unit tests for the ETH staking contract.
contract OpenMatrixStakingTest is Test {
    OpenMatrixStaking internal staking;

    address internal owner;
    address internal feeRecipient;
    address internal alice;
    address internal bob;

    event Staked(address indexed user, uint256 amount, uint256 timestamp);
    event Unstaked(address indexed user, uint256 amount, uint256 rewardsPaid, uint256 commission);

    function setUp() public {
        owner = address(this);
        feeRecipient = makeAddr("feeRecipient");
        alice = makeAddr("alice");
        bob = makeAddr("bob");
        staking = new OpenMatrixStaking(feeRecipient);
        // Fund the reward pool generously so unstake paths don't starve.
        vm.deal(owner, 1000 ether);
        staking.fundRewards{value: 100 ether}();
    }

    function test_Constructor_RevertsOnZeroRecipient() public {
        vm.expectRevert("Zero fee recipient");
        new OpenMatrixStaking(address(0));
    }

    function test_Stake_CreatesPosition() public {
        vm.deal(alice, 5 ether);
        vm.prank(alice);
        vm.expectEmit(true, false, false, false);
        emit Staked(alice, 2 ether, block.timestamp);
        staking.stake{value: 2 ether}();

        (uint256 amount, , , , uint256 startTime, ) = staking.getPosition(alice);
        assertEq(amount, 2 ether);
        assertEq(startTime, block.timestamp);
        assertEq(staking.totalStaked(), 2 ether);
    }

    function test_Stake_RevertsBelowMinimum() public {
        vm.deal(alice, 1 ether);
        vm.prank(alice);
        vm.expectRevert("Below minimum stake of 1 ETH");
        staking.stake{value: 0.5 ether}();
    }

    function test_Unstake_RevertsWithoutPosition() public {
        vm.prank(alice);
        vm.expectRevert("No active position");
        staking.unstake();
    }

    function test_Unstake_ReturnsPrincipal() public {
        vm.deal(alice, 5 ether);
        vm.prank(alice);
        staking.stake{value: 2 ether}();

        // Warp forward slightly so rewards accrue.
        vm.warp(block.timestamp + 1 days);

        uint256 aliceBefore = alice.balance;
        vm.prank(alice);
        staking.unstake();

        uint256 delta = alice.balance - aliceBefore;
        assertGt(delta, 2 ether, "should at least return principal + some reward");
        assertEq(staking.totalStaked(), 0);

        (uint256 amount, , , , , ) = staking.getPosition(alice);
        assertEq(amount, 0);
    }

    function test_ClaimRewards_PaysCommission() public {
        vm.deal(alice, 5 ether);
        vm.prank(alice);
        staking.stake{value: 4 ether}();

        vm.warp(block.timestamp + 30 days);

        uint256 feeBefore = feeRecipient.balance;
        vm.prank(alice);
        staking.claimRewards();
        assertGt(feeRecipient.balance, feeBefore, "commission should flow to feeRecipient");
    }

    function test_UpdateFeeRecipient_UpdatesStorage() public {
        address next = makeAddr("next");
        staking.updateFeeRecipient(next);
        assertEq(staking.platformFeeRecipient(), next);
    }

    function test_UpdateFeeRecipient_RevertsForNonOwner() public {
        vm.prank(alice);
        vm.expectRevert();
        staking.updateFeeRecipient(alice);
    }

    function test_UpdateFeeRecipient_RevertsOnZero() public {
        vm.expectRevert("Zero address");
        staking.updateFeeRecipient(address(0));
    }

    function test_ConstantRewardRateDeterministic() public {
        // Two stakers with equal principal over equal time should earn
        // (within rounding) equal rewards.
        vm.deal(alice, 10 ether);
        vm.deal(bob, 10 ether);

        vm.prank(alice);
        staking.stake{value: 5 ether}();
        vm.prank(bob);
        staking.stake{value: 5 ether}();

        vm.warp(block.timestamp + 7 days);

        (, , , uint256 aliceNet, , ) = staking.getPosition(alice);
        (, , , uint256 bobNet, , ) = staking.getPosition(bob);
        // Same deposit, same duration — rewards must match.
        assertEq(aliceNet, bobNet);
    }
}
