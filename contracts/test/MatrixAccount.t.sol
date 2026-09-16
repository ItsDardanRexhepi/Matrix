// SPDX-License-Identifier: MIT
pragma solidity ^0.8.20;

import "forge-std/Test.sol";
import "../MatrixAccount.sol";
import "../MatrixAccountFactory.sol";
import "account-abstraction/interfaces/IEntryPoint.sol";

contract MatrixAccountTest is Test {
    // A stand-in EntryPoint address; the account only checks msg.sender == entryPoint.
    address internal constant ENTRY_POINT = address(0xEE);
    address internal owner = address(0xA11CE);
    address internal g1 = address(0x6001);
    address internal g2 = address(0x6002);
    address internal g3 = address(0x6003);
    address internal newOwner = address(0xB0B);

    MatrixAccountFactory internal factory;

    function setUp() public {
        factory = new MatrixAccountFactory(IEntryPoint(ENTRY_POINT));
    }

    function _account() internal returns (MatrixAccount a) {
        a = factory.createAccount(owner, 0);
    }

    // ── Factory determinism ──────────────────────────────────────────────
    function test_factory_counterfactual_matches_deploy() public {
        address predicted = factory.getAddress(owner, 0);
        MatrixAccount a = factory.createAccount(owner, 0);
        assertEq(address(a), predicted, "counterfactual != deployed");
        assertEq(a.owner(), owner);
    }

    function test_factory_createAccount_is_idempotent() public {
        MatrixAccount a = factory.createAccount(owner, 0);
        MatrixAccount b = factory.createAccount(owner, 0);
        assertEq(address(a), address(b), "second create should return existing");
    }

    // ── Guardian recovery ────────────────────────────────────────────────
    function _withGuardians(uint256 threshold) internal returns (MatrixAccount a) {
        a = _account();
        address[] memory gs = new address[](3);
        gs[0] = g1; gs[1] = g2; gs[2] = g3;
        vm.prank(owner);
        a.setGuardians(gs, threshold);
    }

    function test_recovery_happy_path_2of3_after_timelock() public {
        MatrixAccount a = _withGuardians(2);
        vm.prank(g1);
        a.initiateRecovery(newOwner);
        vm.prank(g2);
        a.supportRecovery();
        // Before timelock -> reverts
        vm.expectRevert(bytes("OMA: timelock"));
        a.executeRecovery();
        // After timelock -> owner rotated
        vm.warp(block.timestamp + 48 hours);
        a.executeRecovery();
        assertEq(a.owner(), newOwner, "owner not rotated");
    }

    function test_recovery_below_threshold_reverts() public {
        MatrixAccount a = _withGuardians(3);
        vm.prank(g1);
        a.initiateRecovery(newOwner);
        vm.prank(g2);
        a.supportRecovery();               // only 2 of 3
        vm.warp(block.timestamp + 48 hours);
        vm.expectRevert(bytes("OMA: threshold not met"));
        a.executeRecovery();
        assertEq(a.owner(), owner, "owner must not change below threshold");
    }

    function test_owner_can_cancel_recovery() public {
        MatrixAccount a = _withGuardians(2);
        vm.prank(g1);
        a.initiateRecovery(newOwner);
        vm.prank(owner);
        a.cancelRecovery();
        vm.warp(block.timestamp + 48 hours);
        vm.expectRevert(bytes("OMA: no recovery"));
        a.executeRecovery();
        assertEq(a.owner(), owner);
    }

    function test_non_guardian_cannot_initiate() public {
        MatrixAccount a = _withGuardians(2);
        vm.expectRevert(bytes("OMA: not guardian"));
        a.initiateRecovery(newOwner);
    }

    function test_double_support_reverts() public {
        MatrixAccount a = _withGuardians(2);
        vm.prank(g1);
        a.initiateRecovery(newOwner);
        vm.prank(g1);
        vm.expectRevert(bytes("OMA: already supported"));
        a.supportRecovery();
    }

    function test_setGuardians_bad_threshold_reverts() public {
        MatrixAccount a = _account();
        address[] memory gs = new address[](2);
        gs[0] = g1; gs[1] = g2;
        vm.prank(owner);
        vm.expectRevert(bytes("OMA: bad threshold"));
        a.setGuardians(gs, 3);  // threshold > guardians
    }

    function test_execute_only_entrypoint_or_owner() public {
        MatrixAccount a = _account();
        vm.deal(address(a), 1 ether);
        vm.prank(address(0xDEAD));
        vm.expectRevert(bytes("OMA: not EntryPoint/owner"));
        a.execute(address(0x1234), 0, "");
    }
}
