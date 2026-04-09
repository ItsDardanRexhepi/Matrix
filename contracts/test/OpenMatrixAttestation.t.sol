// SPDX-License-Identifier: MIT
pragma solidity ^0.8.20;

import "forge-std/Test.sol";
import "../OpenMatrixAttestation.sol";

/// @title OpenMatrixAttestation.t.sol
/// @notice Unit tests for the on-chain attestation registry.
contract OpenMatrixAttestationTest is Test {
    OpenMatrixAttestation internal registry;

    address internal owner;
    address internal attester;
    address internal stranger;

    event AttestationCreated(uint256 indexed id, address indexed attester, string agent, string action);
    event AttestationRevoked(uint256 indexed id);

    function setUp() public {
        owner = address(this);
        attester = makeAddr("attester");
        stranger = makeAddr("stranger");
        registry = new OpenMatrixAttestation();
    }

    function test_Constructor_AuthorizesOwner() public view {
        assertEq(registry.owner(), owner);
        assertTrue(registry.authorizedAttesters(owner));
    }

    function test_Attest_CreatesEntry() public {
        vm.expectEmit(true, true, false, true);
        emit AttestationCreated(0, owner, "neo", "deploy");
        uint256 id = registry.attest("neo", "deploy", "first-deploy");
        assertEq(id, 0);
        assertEq(registry.totalAttestations(), 1);

        (
            address attester_,
            string memory agentOut,
            string memory action,
            string memory details,
            uint256 ts,
            bool revoked
        ) = registry.getAttestation(0);
        assertEq(attester_, owner);
        assertEq(agentOut, "neo");
        assertEq(action, "deploy");
        assertEq(details, "first-deploy");
        assertEq(ts, block.timestamp);
        assertFalse(revoked);
    }

    function test_Attest_RevertsForStranger() public {
        vm.prank(stranger);
        vm.expectRevert("Not authorized");
        registry.attest("neo", "deploy", "");
    }

    function test_AuthorizeAttester_GrantsAccess() public {
        registry.authorizeAttester(attester);
        vm.prank(attester);
        registry.attest("trinity", "swap", "dex-trade");
        assertEq(registry.totalAttestations(), 1);
    }

    function test_Revoke_MarksAsRevoked() public {
        uint256 id = registry.attest("neo", "mint", "nft");
        vm.expectEmit(true, false, false, false);
        emit AttestationRevoked(id);
        registry.revoke(id);
        (, , , , , bool revoked) = registry.getAttestation(id);
        assertTrue(revoked);
    }

    function test_Revoke_RevertsOnInvalidId() public {
        vm.expectRevert("Invalid ID");
        registry.revoke(999);
    }

    function test_Revoke_RevertsIfAlreadyRevoked() public {
        uint256 id = registry.attest("neo", "x", "y");
        registry.revoke(id);
        vm.expectRevert("Already revoked");
        registry.revoke(id);
    }

    function test_ActionIndex_GroupsByAction() public {
        registry.attest("neo", "deploy", "one");
        registry.attest("morpheus", "deploy", "two");
        registry.attest("trinity", "swap", "three");
        assertEq(registry.getActionCount("deploy"), 2);
        assertEq(registry.getActionCount("swap"), 1);
        assertEq(registry.getActionCount("nonexistent"), 0);
    }

    function test_TransferOwnership_UpdatesOwner() public {
        address newOwner = makeAddr("newOwner");
        registry.transferOwnership(newOwner);
        assertEq(registry.owner(), newOwner);
    }

    function test_TransferOwnership_RevertsOnZero() public {
        vm.expectRevert("Invalid address");
        registry.transferOwnership(address(0));
    }

    function testFuzz_AttestAcceptsArbitraryStrings(
        string calldata agentName,
        string calldata action,
        string calldata details
    ) public {
        uint256 id = registry.attest(agentName, action, details);
        (, string memory agentOut, string memory actionOut, string memory detailsOut, , ) =
            registry.getAttestation(id);
        assertEq(agentOut, agentName);
        assertEq(actionOut, action);
        assertEq(detailsOut, details);
    }
}
