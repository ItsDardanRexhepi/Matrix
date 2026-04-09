// SPDX-License-Identifier: MIT
pragma solidity ^0.8.20;

import "forge-std/Test.sol";
import "../OpenMatrixDEX.sol";
import "./mocks/MockERC20.sol";

/// @title OpenMatrixDEX.t.sol
/// @notice Constant product AMM end-to-end: create pool, add liquidity, swap.
contract OpenMatrixDEXTest is Test {
    OpenMatrixDEX internal dex;
    MockERC20 internal tokenA;
    MockERC20 internal tokenB;
    address internal feeRecipient;
    address internal alice;

    function setUp() public {
        feeRecipient = makeAddr("feeRecipient");
        alice = makeAddr("alice");
        dex = new OpenMatrixDEX(feeRecipient);
        tokenA = new MockERC20("TokenA", "AAA");
        tokenB = new MockERC20("TokenB", "BBB");
    }

    function test_Constructor_RevertsOnZeroRecipient() public {
        vm.expectRevert("Zero fee recipient");
        new OpenMatrixDEX(address(0));
    }

    function test_CreatePool_HappyPath() public {
        tokenA.mint(alice, 1_000 ether);
        tokenB.mint(alice, 2_000 ether);
        vm.startPrank(alice);
        tokenA.approve(address(dex), type(uint256).max);
        tokenB.approve(address(dex), type(uint256).max);
        uint256 poolId = dex.createPool(
            address(tokenA),
            address(tokenB),
            100 ether,
            200 ether
        );
        vm.stopPrank();

        assertEq(poolId, 0);
        assertEq(tokenA.balanceOf(address(dex)), 100 ether);
        assertEq(tokenB.balanceOf(address(dex)), 200 ether);
    }

    function test_CreatePool_RevertsOnIdenticalTokens() public {
        vm.prank(alice);
        vm.expectRevert("Identical tokens");
        dex.createPool(address(tokenA), address(tokenA), 1 ether, 1 ether);
    }

    function test_CreatePool_RevertsOnZeroAddress() public {
        vm.prank(alice);
        vm.expectRevert("Zero address");
        dex.createPool(address(tokenA), address(0), 1 ether, 1 ether);
    }

    function test_CreatePool_RevertsOnDuplicate() public {
        tokenA.mint(alice, 1_000 ether);
        tokenB.mint(alice, 2_000 ether);
        vm.startPrank(alice);
        tokenA.approve(address(dex), type(uint256).max);
        tokenB.approve(address(dex), type(uint256).max);
        dex.createPool(address(tokenA), address(tokenB), 10 ether, 20 ether);
        vm.expectRevert("Pool exists");
        dex.createPool(address(tokenA), address(tokenB), 5 ether, 5 ether);
        vm.stopPrank();
    }

    function test_Swap_MovesTokens() public {
        tokenA.mint(alice, 1_000 ether);
        tokenB.mint(alice, 1_000 ether);
        vm.startPrank(alice);
        tokenA.approve(address(dex), type(uint256).max);
        tokenB.approve(address(dex), type(uint256).max);
        uint256 poolId =
            dex.createPool(address(tokenA), address(tokenB), 100 ether, 100 ether);

        uint256 aliceBIn = tokenB.balanceOf(alice);
        dex.swap(poolId, address(tokenA), 10 ether);
        uint256 aliceBOut = tokenB.balanceOf(alice);
        vm.stopPrank();

        assertGt(aliceBOut, aliceBIn, "should receive tokenB on swap");
    }
}
