// SPDX-License-Identifier: MIT
pragma solidity ^0.8.20;

import "forge-std/Test.sol";
import "../MatrixStaking.sol";

/// Re-enters on every ETH it receives, trying each state-changing entry point.
/// It records what got through, so the test asserts on BEHAVIOUR rather than on
/// the presence of a modifier.
contract ReentrantStaker {
    MatrixStaking public target;
    uint256 public reentryAttempts;
    uint256 public reentrySuccesses;
    bool public attacking;

    constructor(MatrixStaking t) payable { target = t; }

    function beginStake() external payable {
        attacking = true;
        target.stake{value: msg.value}();
        attacking = false;
    }

    function beginUnstake() external {
        attacking = true;
        target.unstake();
        attacking = false;
    }

    function beginClaim() external {
        attacking = true;
        target.claimRewards();
        attacking = false;
    }

    receive() external payable {
        if (!attacking) return;
        reentryAttempts += 1;
        // Try every guarded entry point. A success here is a drained contract.
        try target.claimRewards() { reentrySuccesses += 1; } catch {}
        try target.unstake() { reentrySuccesses += 1; } catch {}
        try target.withdrawFees() { reentrySuccesses += 1; } catch {}
    }
}

contract MatrixStakingReentrancyTest is Test {
    MatrixStaking staking;
    address feeRecipient = address(0xFEE);

    function setUp() public {
        staking = new MatrixStaking(feeRecipient);
        vm.deal(address(this), 1000 ether);
        staking.fundRewards{value: 100 ether}();
    }

    /// THE CONTROL. An attacker that re-enters on every payout must not be able
    /// to claim twice, unstake twice, or take more ETH out than it is owed.
    /// Asserted on the contract's BALANCE and the attacker's, not on whether a
    /// modifier is spelled somewhere.
    function test_ReentrancyCannotDrainTheStakingPool() public {
        ReentrantStaker attacker = new ReentrantStaker(staking);
        vm.deal(address(attacker), 10 ether);

        attacker.beginStake{value: 5 ether}();
        // Let rewards accrue so a payout actually happens on the next touch.
        vm.warp(block.timestamp + 365 days);

        uint256 poolBefore = address(staking).balance;
        uint256 attackerBefore = address(attacker).balance;

        attacker.beginUnstake();

        assertEq(attacker.reentrySuccesses(), 0,
            "a re-entrant call succeeded: the pool can be drained");
        assertGt(attacker.reentryAttempts(), 0,
            "the attacker never re-entered, so this test proved nothing");

        uint256 taken = address(attacker).balance - attackerBefore;
        assertLe(taken, poolBefore, "took more than the pool held");
        // 5 principal + at most one year of rewards on 5 ETH. Never twice.
        assertLt(taken, 5 ether + 5 ether, "paid out more than one settlement");
    }

    /// The same, entering through claimRewards rather than unstake.
    function test_ReentrancyThroughClaimCannotDoubleClaim() public {
        ReentrantStaker attacker = new ReentrantStaker(staking);
        vm.deal(address(attacker), 10 ether);
        attacker.beginStake{value: 5 ether}();
        vm.warp(block.timestamp + 180 days);

        uint256 poolBefore = address(staking).balance;
        attacker.beginClaim();

        assertEq(attacker.reentrySuccesses(), 0, "a re-entrant claim succeeded");
        assertGt(attacker.reentryAttempts(), 0, "no re-entry was attempted");
        assertLe(address(staking).balance, poolBefore, "the pool grew during an attack");
    }

    /// Accounting must survive the attempt: what the pool holds still covers
    /// what it owes in principal.
    function test_PoolStillCoversPrincipalAfterAnAttack() public {
        ReentrantStaker attacker = new ReentrantStaker(staking);
        vm.deal(address(attacker), 10 ether);
        address honest = address(0xA11CE);
        vm.deal(honest, 10 ether);

        vm.prank(honest);
        staking.stake{value: 3 ether}();
        attacker.beginStake{value: 5 ether}();

        vm.warp(block.timestamp + 365 days);
        attacker.beginUnstake();

        // The honest staker's principal must still be withdrawable.
        vm.prank(honest);
        staking.unstake();
        assertGe(honest.balance, 10 ether - 3 ether + 3 ether - 1 ether,
            "the honest staker could not get their principal back");
    }

    receive() external payable {}
}
