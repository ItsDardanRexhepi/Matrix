// SPDX-License-Identifier: MIT
pragma solidity ^0.8.20;

import "forge-std/Test.sol";
import "../PropertyEscrow.sol";
import "../PropertyDeed.sol";

/// @title The register's sequence for P4-4-DEED-1WEI, verbatim.
/// @notice Seller approves the escrow (the documented listing step); anyone
///         calls lockAndSettle{value: 1}(freshId, seller, deed, tokenId,
///         bytes32(1)). Before the fix the deed moved to the caller and the
///         seller received 1 wei. This file uses only the pre-fix API so it
///         compiles against both versions: it FAILS at the previous head and
///         passes now.
contract PropertyEscrowOneWeiTest is Test {
    PropertyEscrow internal escrow;
    PropertyDeed internal deed;
    address internal seller = makeAddr("seller");
    address internal anyone = makeAddr("anyone");
    uint256 internal tokenId;

    function setUp() public {
        escrow = new PropertyEscrow(7 days);
        deed = new PropertyDeed();
        tokenId = deed.mint(seller, "prop_1wei", "ipfs://x");
        vm.prank(seller);
        deed.approve(address(escrow), tokenId); // the listing-time approval the design requires
        vm.deal(anyone, 1 ether);
    }

    function test_AnyoneTakesTheDeedForOneWei_Reverts() public {
        uint256 sellerBefore = seller.balance;
        vm.prank(anyone);
        vm.expectRevert();
        escrow.lockAndSettle{ value: 1 }(
            keccak256("fresh"), seller, address(deed), tokenId, bytes32(uint256(1))
        );
        assertEq(deed.ownerOf(tokenId), seller, "the deed must stay with the seller");
        assertEq(seller.balance, sellerBefore, "the seller must not be paid 1 wei");
    }
}
