// SPDX-License-Identifier: MIT
pragma solidity ^0.8.20;

import "forge-std/Test.sol";
import "../OpenMatrixInsurance.sol";

/// @title OpenMatrixInsurance.t.sol
/// @notice Parametric insurance flows: purchase, claim, expire.
contract OpenMatrixInsuranceTest is Test {
    OpenMatrixInsurance internal insurance;
    address internal feeRecipient;
    address internal oracle;
    address internal alice;

    bytes32 internal constant TRIGGER = keccak256("DROUGHT_REGION_X");

    function setUp() public {
        feeRecipient = makeAddr("feeRecipient");
        oracle = makeAddr("oracle");
        alice = makeAddr("alice");
        insurance = new OpenMatrixInsurance(feeRecipient, oracle);
        // Fund the pool so payouts succeed.
        vm.deal(address(this), 100 ether);
        (bool ok, ) = address(insurance).call{value: 50 ether}("");
        assertTrue(ok);
    }

    receive() external payable {}

    function test_Constructor_RevertsOnZeros() public {
        vm.expectRevert("Zero fee recipient");
        new OpenMatrixInsurance(address(0), oracle);
        vm.expectRevert("Zero oracle");
        new OpenMatrixInsurance(feeRecipient, address(0));
    }

    function test_CalculatePremium_LowTier() public view {
        uint256 premium = insurance.calculatePremium(10 ether, OpenMatrixInsurance.RiskTier.Low);
        assertEq(premium, 0.2 ether); // 2%
    }

    function test_CalculatePremium_MediumTier() public view {
        uint256 premium =
            insurance.calculatePremium(10 ether, OpenMatrixInsurance.RiskTier.Medium);
        assertEq(premium, 0.5 ether); // 5%
    }

    function test_CalculatePremium_HighTier() public view {
        uint256 premium =
            insurance.calculatePremium(10 ether, OpenMatrixInsurance.RiskTier.High);
        assertEq(premium, 1 ether); // 10%
    }

    function test_PurchasePolicy_CreatesActivePolicy() public {
        vm.deal(alice, 10 ether);
        uint256 coverage = 1 ether;
        uint256 premium =
            insurance.calculatePremium(coverage, OpenMatrixInsurance.RiskTier.Low);

        vm.prank(alice);
        uint256 id = insurance.purchasePolicy{value: premium}(
            coverage,
            OpenMatrixInsurance.RiskTier.Low,
            TRIGGER
        );
        assertEq(id, 0);
        assertEq(insurance.activePoliciesCount(), 1);
        assertGt(insurance.reserveFund(), 0);
    }

    function test_PurchasePolicy_RevertsBelowMinCoverage() public {
        vm.deal(alice, 1 ether);
        vm.prank(alice);
        vm.expectRevert("Below min coverage");
        insurance.purchasePolicy{value: 0.001 ether}(
            0.005 ether,
            OpenMatrixInsurance.RiskTier.Low,
            TRIGGER
        );
    }

    function test_PurchasePolicy_RevertsAboveMaxCoverage() public {
        vm.deal(alice, 200 ether);
        vm.prank(alice);
        vm.expectRevert("Exceeds max coverage");
        insurance.purchasePolicy{value: 20 ether}(
            200 ether,
            OpenMatrixInsurance.RiskTier.Low,
            TRIGGER
        );
    }

    function test_ExpirePolicy_AfterEndTime() public {
        vm.deal(alice, 10 ether);
        uint256 premium =
            insurance.calculatePremium(1 ether, OpenMatrixInsurance.RiskTier.Low);
        vm.prank(alice);
        uint256 id = insurance.purchasePolicy{value: premium}(
            1 ether,
            OpenMatrixInsurance.RiskTier.Low,
            TRIGGER
        );

        // Still active — expirePolicy must revert.
        vm.expectRevert("Not yet expired");
        insurance.expirePolicy(id);

        vm.warp(block.timestamp + 31 days);
        insurance.expirePolicy(id);
        assertEq(insurance.activePoliciesCount(), 0);
    }
}
