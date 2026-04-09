// SPDX-License-Identifier: MIT
pragma solidity ^0.8.20;

import "forge-std/Test.sol";
import "../OpenMatrixNFT.sol";

/// @title OpenMatrixNFT.t.sol
/// @notice ERC-721 minting and royalty tests for the OpenMatrixNFT contract.
contract OpenMatrixNFTTest is Test {
    OpenMatrixNFT internal nft;
    address internal feeRecipient;
    address internal alice;
    address internal bob;

    function setUp() public {
        feeRecipient = makeAddr("feeRecipient");
        alice = makeAddr("alice");
        bob = makeAddr("bob");
        nft = new OpenMatrixNFT(feeRecipient, 500, 0.01 ether); // 5% default royalty
    }

    function test_Constructor_RevertsOnZeroRecipient() public {
        vm.expectRevert("Zero fee recipient");
        new OpenMatrixNFT(address(0), 500, 0.01 ether);
    }

    function test_Constructor_RevertsOnExcessiveRoyalty() public {
        vm.expectRevert("Royalty too high");
        new OpenMatrixNFT(feeRecipient, 2_000, 0.01 ether);
    }

    function test_Constructor_SetsDefaults() public view {
        assertEq(nft.platformFeeRecipient(), feeRecipient);
        assertEq(nft.mintPrice(), 0.01 ether);
    }

    function test_Mint_WithoutCustomRoyalty_UsesDefault() public {
        vm.deal(alice, 1 ether);
        vm.prank(alice);
        uint256 tokenId = nft.mint{value: 0.01 ether}(alice, "ipfs://a", 0);
        assertEq(tokenId, 0);
        assertEq(nft.ownerOf(tokenId), alice);
        (address recipient, uint256 amount) = nft.royaltyInfo(tokenId, 1 ether);
        assertEq(recipient, feeRecipient);
        assertEq(amount, 0.05 ether); // 5% of 1 ether
    }

    function test_Mint_WithCustomRoyalty_SendsToCreator() public {
        vm.deal(alice, 1 ether);
        vm.prank(alice);
        uint256 tokenId = nft.mint{value: 0.01 ether}(alice, "ipfs://b", 700);
        (address recipient, uint256 amount) = nft.royaltyInfo(tokenId, 1 ether);
        assertEq(recipient, alice);
        assertEq(amount, 0.07 ether);
    }

    function test_Mint_RevertsBelowMintPrice() public {
        vm.deal(alice, 1 ether);
        vm.prank(alice);
        vm.expectRevert("Insufficient mint fee");
        nft.mint{value: 0.005 ether}(alice, "ipfs://x", 0);
    }

    function test_Mint_RevertsOnExcessiveRoyalty() public {
        vm.deal(alice, 1 ether);
        vm.prank(alice);
        vm.expectRevert("Royalty too high");
        nft.mint{value: 0.01 ether}(alice, "ipfs://y", 2_000);
    }

    function test_SetMintPrice_UpdatesStorage() public {
        nft.setMintPrice(0.02 ether);
        assertEq(nft.mintPrice(), 0.02 ether);
    }

    function test_SetDefaultRoyalty_RevertsOnExcess() public {
        vm.expectRevert("Royalty too high");
        nft.setDefaultRoyalty(feeRecipient, 2_000);
    }
}
