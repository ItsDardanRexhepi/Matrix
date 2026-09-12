// SPDX-License-Identifier: MIT
pragma solidity ^0.8.20;

import "forge-std/Test.sol";
import "@openzeppelin/contracts/token/ERC721/ERC721.sol";
import "../OpenMatrixMarketplace.sol";
import "./mocks/MockERC20.sol";

contract PlainNFT is ERC721 {
    uint256 public next = 1;
    constructor() ERC721("Plain", "PLN") {}
    function mint(address to) external returns (uint256 id) { id = next++; _mint(to, id); }
}

/// @title The register's sequence for B3-MKT-ERC20-NO-PRICE-BOUND.
/// @notice The buy is issued through the pre-fix selector buyItem(uint256) by a
///         low-level call, so this compiles against both versions: at the
///         previous head the call succeeded at the front-run price and the test
///         FAILS; now the unbounded entry point does not exist and the buyer's
///         tokens stay put.
contract OpenMatrixMarketplaceFrontrunTest is Test {
    OpenMatrixMarketplace internal market;
    PlainNFT internal nft;
    MockERC20 internal token;
    address internal feeRecipient = makeAddr("feeRecipient");
    address internal seller = makeAddr("seller");
    address internal buyer = makeAddr("buyer");

    function setUp() public {
        market = new OpenMatrixMarketplace(feeRecipient);
        nft = new PlainNFT();
        token = new MockERC20("Mock", "MCK");
        token.mint(buyer, 1000e18);
        uint256 id = nft.mint(seller);
        vm.prank(seller);
        nft.approve(address(market), id);
        vm.prank(seller);
        market.listItem(address(nft), id, 100e18, address(token));
        vm.prank(buyer);
        token.approve(address(market), type(uint256).max);   // the customary unlimited approval
    }

    function test_SellerFrontRunsThePrice_BuyerIsNotChargedTheNewPrice() public {
        vm.prank(seller);
        market.updatePrice(0, 1000e18);
        vm.prank(buyer);
        (bool ok, ) = address(market).call(abi.encodeWithSignature("buyItem(uint256)", 0));
        ok; // whether the old entry point answers is not the point — what the buyer paid is
        assertEq(token.balanceOf(buyer), 1000e18, "the buyer's whole balance was taken at the front-run price");
    }
}
