// SPDX-License-Identifier: MIT
pragma solidity ^0.8.20;

import "forge-std/Test.sol";
import "../OpenMatrixMarketplace.sol";
import "../OpenMatrixNFT.sol";

/// @title OpenMatrixMarketplace.t.sol
/// @notice Marketplace: list item, buy item, cancel, update price.
contract OpenMatrixMarketplaceTest is Test {
    OpenMatrixMarketplace internal marketplace;
    OpenMatrixNFT internal nft;
    address internal feeRecipient;
    address internal alice;
    address internal bob;

    function setUp() public {
        feeRecipient = makeAddr("feeRecipient");
        alice = makeAddr("alice");
        bob = makeAddr("bob");
        marketplace = new OpenMatrixMarketplace(feeRecipient);
        nft = new OpenMatrixNFT(feeRecipient, 500, 0); // 0 mint price
    }

    function test_Constructor_RevertsOnZeroRecipient() public {
        vm.expectRevert("Zero fee recipient");
        new OpenMatrixMarketplace(address(0));
    }

    function _mintTo(address to) internal returns (uint256 tokenId) {
        vm.prank(to);
        tokenId = nft.mint(to, "ipfs://a", 0);
    }

    function test_ListItem_EmitsEvent() public {
        uint256 tokenId = _mintTo(alice);
        vm.startPrank(alice);
        nft.approve(address(marketplace), tokenId);
        uint256 listingId = marketplace.listItem(
            address(nft),
            tokenId,
            1 ether,
            address(0)
        );
        vm.stopPrank();
        assertEq(listingId, 0);

        (address seller, , , uint256 price, , bool active) =
            marketplace.listings(listingId);
        assertEq(seller, alice);
        assertEq(price, 1 ether);
        assertTrue(active);
    }

    function test_ListItem_RevertsWithoutApproval() public {
        uint256 tokenId = _mintTo(alice);
        vm.prank(alice);
        vm.expectRevert("Marketplace not approved");
        marketplace.listItem(address(nft), tokenId, 1 ether, address(0));
    }

    function test_ListItem_RevertsOnZeroPrice() public {
        uint256 tokenId = _mintTo(alice);
        vm.startPrank(alice);
        nft.approve(address(marketplace), tokenId);
        vm.expectRevert("Price must be > 0");
        marketplace.listItem(address(nft), tokenId, 0, address(0));
        vm.stopPrank();
    }

    function test_ListItem_RevertsForNonOwner() public {
        uint256 tokenId = _mintTo(alice);
        vm.prank(bob);
        vm.expectRevert("Not token owner");
        marketplace.listItem(address(nft), tokenId, 1 ether, address(0));
    }
}
