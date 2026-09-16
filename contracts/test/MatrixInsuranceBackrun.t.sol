// SPDX-License-Identifier: MIT
pragma solidity ^0.8.20;

import "forge-std/Test.sol";
import "../MatrixInsurance.sol";

/// @title The register's sequence for B3-INS-SAME-BLOCK-BACKRUN, verbatim.
/// @notice The oracle reports a trigger; in the same block the attacker buys
///         100 ETH of Low-tier coverage for 2 ETH and claims 100 ETH. Uses only
///         the pre-fix API so it compiles against both versions: FAILS at the
///         previous head (the claim pays), passes now (the claim reverts).
contract MatrixInsuranceBackrunTest is Test {
    MatrixInsurance internal insurance;
    address internal oracle = makeAddr("oracle");
    address internal feeRecipient = makeAddr("feeRecipient");
    address internal attacker = makeAddr("attacker");
    bytes32 internal constant COND = keccak256("HURRICANE_REGION_Y");

    function setUp() public {
        insurance = new MatrixInsurance(feeRecipient, oracle);
        // Third parties' backing: 300 ETH in the pool.
        vm.deal(address(this), 300 ether);
        (bool ok, ) = address(insurance).call{value: 300 ether}("");
        assertTrue(ok);
        vm.deal(attacker, 10 ether);
    }

    receive() external payable {}

    function test_BuyAndClaimInTheTriggersBlock_Reverts() public {
        vm.prank(oracle);
        insurance.reportTrigger(COND);

        uint256 premium = insurance.calculatePremium(100 ether, MatrixInsurance.RiskTier.Low);
        assertEq(premium, 2 ether, "50:1 at Low");
        vm.prank(attacker);
        uint256 id = insurance.purchasePolicy{value: premium}(100 ether, MatrixInsurance.RiskTier.Low, COND);

        uint256 before = attacker.balance;
        vm.prank(attacker);
        vm.expectRevert();
        insurance.claimPolicy(id);
        assertEq(attacker.balance, before, "nothing paid out");
        assertEq(address(insurance).balance, 300 ether + premium, "the pool keeps its backing");
    }
}
