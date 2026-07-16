// SPDX-License-Identifier: MIT
pragma solidity ^0.8.20;

import "forge-std/Test.sol";
import "@openzeppelin/contracts/access/Ownable.sol";
import "../PropertyDeed.sol";

contract PropertyDeedTest is Test {
    PropertyDeed internal deed;
    address internal seller;
    address internal buyer;
    address internal stranger;

    function setUp() public {
        deed = new PropertyDeed();
        seller = makeAddr("seller");
        buyer = makeAddr("buyer");
        stranger = makeAddr("stranger");
    }

    function test_Mint_ByOperator_AssignsTokenAndURI() public {
        uint256 id = deed.mint(seller, "prop_abc123", "ipfs://bundle1");
        assertEq(id, 1);
        assertEq(deed.ownerOf(1), seller);
        assertEq(deed.tokenURI(1), "ipfs://bundle1");
        assertEq(deed.propertyIdOf(1), "prop_abc123");
        assertEq(deed.tokenForProperty("prop_abc123"), 1);
        assertEq(deed.totalSupply(), 1);
    }

    function test_Mint_ByNonOperator_Reverts() public {
        vm.prank(stranger);
        vm.expectRevert(
            abi.encodeWithSelector(Ownable.OwnableUnauthorizedAccount.selector, stranger)
        );
        deed.mint(seller, "prop_abc123", "ipfs://x");
    }

    function test_Mint_DuplicateProperty_Reverts() public {
        deed.mint(seller, "prop_abc123", "ipfs://x");
        vm.expectRevert("Deed already minted");
        deed.mint(seller, "prop_abc123", "ipfs://y");
    }

    function test_Mint_ZeroAddress_Reverts() public {
        vm.expectRevert("Zero address");
        deed.mint(address(0), "prop_abc123", "ipfs://x");
    }

    function test_Mint_EmptyPropertyId_Reverts() public {
        vm.expectRevert("Empty property id");
        deed.mint(seller, "", "ipfs://x");
    }

    function test_TokenForProperty_UnknownIsZero() public view {
        assertEq(deed.tokenForProperty("prop_never"), 0);
    }

    function test_Transfer_WithApproval_Works() public {
        uint256 id = deed.mint(seller, "prop_abc123", "ipfs://x");
        vm.prank(seller);
        deed.approve(buyer, id);
        vm.prank(buyer);
        deed.transferFrom(seller, buyer, id);
        assertEq(deed.ownerOf(id), buyer);
    }

    function test_Transfer_WithoutApproval_Reverts() public {
        uint256 id = deed.mint(seller, "prop_abc123", "ipfs://x");
        vm.prank(stranger);
        vm.expectRevert(); // OZ v5 ERC721InsufficientApproval custom error
        deed.transferFrom(seller, stranger, id);
    }

    function test_TokenIdsStartAtOne_SoZeroMeansNone() public {
        uint256 first = deed.mint(seller, "prop_a", "ipfs://a");
        uint256 second = deed.mint(seller, "prop_b", "ipfs://b");
        assertEq(first, 1);
        assertEq(second, 2);
    }
}
