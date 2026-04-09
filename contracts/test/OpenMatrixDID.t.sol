// SPDX-License-Identifier: MIT
pragma solidity ^0.8.20;

import "forge-std/Test.sol";
import "../OpenMatrixDID.sol";

/// @title OpenMatrixDID.t.sol
/// @notice DID lifecycle: create, resolve, update, deactivate.
contract OpenMatrixDIDTest is Test {
    OpenMatrixDID internal did;
    address internal feeRecipient;
    address internal alice;
    address internal bob;

    function setUp() public {
        feeRecipient = makeAddr("feeRecipient");
        alice = makeAddr("alice");
        bob = makeAddr("bob");
        did = new OpenMatrixDID(feeRecipient);
    }

    function test_Constructor_RevertsOnZeroRecipient() public {
        vm.expectRevert("Zero fee recipient");
        new OpenMatrixDID(address(0));
    }

    function test_CreateDID_StoresDocument() public {
        vm.prank(alice);
        did.createDID("ipfs://doc1", keccak256("doc1"));
        assertEq(did.totalDIDs(), 1);
        assertEq(did.activeDIDs(), 1);

        (
            address controller,
            string memory uri,
            bytes32 hash,
            uint256 created,
            ,
            bool active,
            ,
            ,

        ) = did.resolve(alice);
        assertEq(controller, alice);
        assertEq(uri, "ipfs://doc1");
        assertEq(hash, keccak256("doc1"));
        assertGt(created, 0);
        assertTrue(active);
    }

    function test_CreateDID_RevertsOnEmptyURI() public {
        vm.prank(alice);
        vm.expectRevert("Empty document URI");
        did.createDID("", bytes32(0));
    }

    function test_CreateDID_RevertsOnDuplicate() public {
        vm.prank(alice);
        did.createDID("ipfs://a", bytes32(0));
        vm.prank(alice);
        vm.expectRevert("DID already exists");
        did.createDID("ipfs://b", bytes32(0));
    }

    function test_DidFor_ReturnsFormattedString() public view {
        string memory s = did.didFor(address(0x1234));
        // Can't easily match the full hex here but the prefix must be right.
        bytes memory raw = bytes(s);
        assertGt(raw.length, 20);
        // First 20 bytes should spell "did:openmatrix:base:"
        bytes memory expectedPrefix = bytes("did:openmatrix:base:");
        for (uint256 i = 0; i < expectedPrefix.length; i++) {
            assertEq(raw[i], expectedPrefix[i]);
        }
    }

    function test_Resolve_RevertsForUnknown() public {
        vm.expectRevert("DID does not exist");
        did.resolve(bob);
    }

    function test_UpdateDocument_OnlyController() public {
        vm.prank(alice);
        did.createDID("ipfs://v1", bytes32(0));
        vm.prank(bob);
        vm.expectRevert("Not DID controller");
        did.updateDocument(alice, "ipfs://v2", bytes32(0));

        vm.prank(alice);
        did.updateDocument(alice, "ipfs://v2", bytes32("newhash"));

        (, string memory uri, bytes32 hash, , , , , , ) = did.resolve(alice);
        assertEq(uri, "ipfs://v2");
        assertEq(hash, bytes32("newhash"));
    }

    function test_AddService_AppendsEndpoint() public {
        vm.prank(alice);
        did.createDID("ipfs://doc", bytes32(0));
        vm.prank(alice);
        did.addService(alice, "MessagingService", "https://msg.example");

        (, , , , , , string[] memory types, string[] memory endpoints, ) =
            did.resolve(alice);
        assertEq(types.length, 1);
        assertEq(types[0], "MessagingService");
        assertEq(endpoints[0], "https://msg.example");
    }
}
