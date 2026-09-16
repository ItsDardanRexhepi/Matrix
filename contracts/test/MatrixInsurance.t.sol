// SPDX-License-Identifier: MIT
pragma solidity ^0.8.20;

import "forge-std/Test.sol";
import "../MatrixInsurance.sol";

/// @title MatrixInsurance.t.sol
/// @notice Parametric insurance flows: purchase, claim, expire.
contract MatrixInsuranceTest is Test {
    MatrixInsurance internal insurance;
    address internal feeRecipient;
    address internal oracle;
    address internal alice;

    bytes32 internal constant TRIGGER = keccak256("DROUGHT_REGION_X");

    function setUp() public {
        feeRecipient = makeAddr("feeRecipient");
        oracle = makeAddr("oracle");
        alice = makeAddr("alice");
        insurance = new MatrixInsurance(feeRecipient, oracle);
        // Fund the pool so payouts succeed.
        vm.deal(address(this), 100 ether);
        (bool ok, ) = address(insurance).call{value: 50 ether}("");
        assertTrue(ok);
    }

    receive() external payable {}

    function test_Constructor_RevertsOnZeros() public {
        vm.expectRevert("Zero fee recipient");
        new MatrixInsurance(address(0), oracle);
        vm.expectRevert("Zero oracle");
        new MatrixInsurance(feeRecipient, address(0));
    }

    function test_CalculatePremium_LowTier() public view {
        uint256 premium = insurance.calculatePremium(10 ether, MatrixInsurance.RiskTier.Low);
        assertEq(premium, 0.2 ether); // 2%
    }

    function test_CalculatePremium_MediumTier() public view {
        uint256 premium =
            insurance.calculatePremium(10 ether, MatrixInsurance.RiskTier.Medium);
        assertEq(premium, 0.5 ether); // 5%
    }

    function test_CalculatePremium_HighTier() public view {
        uint256 premium =
            insurance.calculatePremium(10 ether, MatrixInsurance.RiskTier.High);
        assertEq(premium, 1 ether); // 10%
    }

    function test_PurchasePolicy_CreatesActivePolicy() public {
        vm.deal(alice, 10 ether);
        uint256 coverage = 1 ether;
        uint256 premium =
            insurance.calculatePremium(coverage, MatrixInsurance.RiskTier.Low);

        vm.prank(alice);
        uint256 id = insurance.purchasePolicy{value: premium}(
            coverage,
            MatrixInsurance.RiskTier.Low,
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
            MatrixInsurance.RiskTier.Low,
            TRIGGER
        );
    }

    function test_PurchasePolicy_RevertsAboveMaxCoverage() public {
        vm.deal(alice, 200 ether);
        vm.prank(alice);
        vm.expectRevert("Exceeds max coverage");
        insurance.purchasePolicy{value: 20 ether}(
            200 ether,
            MatrixInsurance.RiskTier.Low,
            TRIGGER
        );
    }

    function test_ExpirePolicy_AfterEndTime() public {
        vm.deal(alice, 10 ether);
        uint256 premium =
            insurance.calculatePremium(1 ether, MatrixInsurance.RiskTier.Low);
        vm.prank(alice);
        uint256 id = insurance.purchasePolicy{value: premium}(
            1 ether,
            MatrixInsurance.RiskTier.Low,
            TRIGGER
        );

        // Still active — expirePolicy must revert.
        vm.expectRevert("Not yet expired");
        insurance.expirePolicy(id);

        vm.warp(block.timestamp + 31 days);
        insurance.expirePolicy(id);
        assertEq(insurance.activePoliciesCount(), 0);
    }

    // ── B3-INS-SAME-BLOCK-BACKRUN / UNBACKED-COVERAGE / OWNER-SWEEP ──────

    function _buy(address who, uint256 coverage) internal returns (uint256 id) {
        uint256 premium = insurance.calculatePremium(coverage, MatrixInsurance.RiskTier.Low);
        vm.deal(who, who.balance + premium);
        vm.prank(who);
        id = insurance.purchasePolicy{value: premium}(coverage, MatrixInsurance.RiskTier.Low, TRIGGER);
    }

    function test_Claim_TriggerBeforeMinimumAge_Reverts_ThenPasses() public {
        uint256 id = _buy(alice, 1 ether);
        // A trigger one hour in: too new.
        vm.warp(block.timestamp + 1 hours);
        vm.prank(oracle);
        insurance.reportTrigger(TRIGGER);
        vm.prank(alice);
        vm.expectRevert("Policy too new for this trigger");
        insurance.claimPolicy(id);

        // A second condition, reported after the minimum age: the legitimate path pays.
        bytes32 later = keccak256("FLOOD_REGION_Z");
        uint256 id2 = _buyWith(alice, 1 ether, later);
        vm.warp(block.timestamp + insurance.MIN_POLICY_AGE());
        vm.prank(oracle);
        insurance.reportTrigger(later);
        uint256 before = alice.balance;
        vm.prank(alice);
        insurance.claimPolicy(id2);
        assertEq(alice.balance, before + 1 ether);
        assertEq(insurance.totalOutstandingCoverage(), 1 ether, "only the unclaimed policy remains outstanding");
    }

    function _buyWith(address who, uint256 coverage, bytes32 cond) internal returns (uint256 id) {
        uint256 premium = insurance.calculatePremium(coverage, MatrixInsurance.RiskTier.Low);
        vm.deal(who, who.balance + premium);
        vm.prank(who);
        id = insurance.purchasePolicy{value: premium}(coverage, MatrixInsurance.RiskTier.Low, cond);
    }

    function test_Purchase_BeyondBacking_Reverts() public {
        // The pool holds 50 ETH (setUp). 40 ETH of coverage sells; 20 more does not.
        _buy(alice, 40 ether);
        uint256 premium = insurance.calculatePremium(20 ether, MatrixInsurance.RiskTier.Low);
        vm.deal(alice, premium);
        vm.prank(alice);
        vm.expectRevert("Coverage exceeds backing");
        insurance.purchasePolicy{value: premium}(20 ether, MatrixInsurance.RiskTier.Low, TRIGGER);
    }

    function test_Purchase_PerHolderCap() public {
        for (uint256 i = 0; i < insurance.MAX_ACTIVE_POLICIES_PER_HOLDER(); i++) {
            _buy(alice, 0.01 ether);
        }
        uint256 premium = insurance.calculatePremium(0.01 ether, MatrixInsurance.RiskTier.Low);
        vm.deal(alice, premium);
        vm.prank(alice);
        vm.expectRevert("Too many active policies");
        insurance.purchasePolicy{value: premium}(0.01 ether, MatrixInsurance.RiskTier.Low, TRIGGER);
        // Expiry frees a slot.
        vm.warp(block.timestamp + 31 days);
        insurance.expirePolicy(0);
        _buy(alice, 0.01 ether);
    }

    function test_WithdrawExcess_NeverBelowOutstandingCoverage() public {
        _buy(alice, 30 ether);                       // pool 50 + premium, owes 30
        uint256 reserve = insurance.reserveFund();
        insurance.withdrawExcess();
        assertEq(address(insurance).balance, reserve + 30 ether, "reserve + outstanding coverage stay");
        vm.expectRevert("No excess");
        insurance.withdrawExcess();
    }
}
