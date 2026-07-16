// SPDX-License-Identifier: MIT
pragma solidity ^0.8.20;

import "forge-std/Test.sol";
import "../PropertyEscrow.sol";
import "../PropertyDeed.sol";

/// @notice A rogue ERC-721 whose transferFrom is a SILENT NO-OP — proves the
///         escrow refuses to pay unless the buyer genuinely receives the deed.
contract NoOpDeed {
    address public fixedOwner;

    constructor(address _owner) {
        fixedOwner = _owner;
    }

    // never actually transfers — ownerOf stays the original holder
    function transferFrom(address, address, uint256) external {}

    function ownerOf(uint256) external view returns (address) {
        return fixedOwner;
    }

    function approve(address, uint256) external {}
}

/// @notice Seller wallet that rejects ETH — proves settlement is atomic in
///         the payment direction (deed cannot move if payment fails).
contract RejectingSeller {
    receive() external payable {
        revert("no thanks");
    }

    function onERC721Received(address, address, uint256, bytes calldata)
        external
        pure
        returns (bytes4)
    {
        return this.onERC721Received.selector; // can HOLD a deed, rejects ETH
    }
}

/// @notice Seller wallet that tries to re-enter the escrow during payment —
///         proves reentrancy cannot double-move funds or corrupt state.
contract ReentrantSeller {
    PropertyEscrow public escrow;
    bytes32 public targetId;
    bool public reentered;

    function arm(PropertyEscrow _escrow, bytes32 _id) external {
        escrow = _escrow;
        targetId = _id;
    }

    receive() external payable {
        reentered = true;
        // Attempt to re-enter settle on the SAME escrow mid-payment. Must not
        // succeed: state is already Settled (CEI) and the guard is held.
        escrow.settle(targetId, bytes32(uint256(1)));
    }

    function onERC721Received(address, address, uint256, bytes calldata)
        external
        pure
        returns (bytes4)
    {
        return this.onERC721Received.selector;
    }
}

contract PropertyEscrowTest is Test {
    PropertyEscrow internal escrow;
    PropertyDeed internal deed;
    address internal seller;
    address internal buyer;
    address internal stranger;
    uint256 internal tokenId;
    bytes32 internal constant ESCROW_ID = keccak256("resc_test_1");
    bytes32 internal constant READINESS = keccak256("readiness_attestation_uid");
    uint256 internal constant PRICE = 1 ether;

    event FundsLocked(
        bytes32 indexed escrowId, address indexed buyer, address indexed seller,
        uint256 amount, uint64 deadline
    );
    event Settled(
        bytes32 indexed escrowId, address indexed buyer, address indexed seller,
        uint256 amount, uint256 deedTokenId, bytes32 readinessAttestation
    );
    event Refunded(bytes32 indexed escrowId, address indexed buyer, uint256 amount);

    receive() external payable {}

    function setUp() public {
        escrow = new PropertyEscrow(7 days);
        deed = new PropertyDeed();
        seller = makeAddr("seller");
        buyer = makeAddr("buyer");
        stranger = makeAddr("stranger");
        vm.deal(buyer, 10 ether);
        vm.deal(stranger, 10 ether);

        tokenId = deed.mint(seller, "prop_test", "ipfs://bundle");
        vm.prank(seller);
        deed.approve(address(escrow), tokenId); // listing-time approval
    }

    // ── One-tap atomic settlement ───────────────────────────────────────

    function test_LockAndSettle_AtomicHappyPath() public {
        uint256 sellerBefore = seller.balance;
        vm.prank(buyer);
        vm.expectEmit(true, true, true, true);
        emit Settled(ESCROW_ID, buyer, seller, PRICE, tokenId, READINESS);
        escrow.lockAndSettle{ value: PRICE }(
            ESCROW_ID, seller, address(deed), tokenId, READINESS
        );

        assertEq(deed.ownerOf(tokenId), buyer, "deed moved to buyer");
        assertEq(seller.balance, sellerBefore + PRICE, "funds moved to seller");
        assertEq(address(escrow).balance, 0, "escrow holds nothing after");
        assertEq(
            uint8(escrow.getEscrow(ESCROW_ID).state),
            uint8(PropertyEscrow.State.Settled)
        );
    }

    function test_LockAndSettle_ZeroReadinessAttestation_Reverts() public {
        vm.prank(buyer);
        vm.expectRevert("No readiness attestation");
        escrow.lockAndSettle{ value: PRICE }(
            ESCROW_ID, seller, address(deed), tokenId, bytes32(0)
        );
        // atomicity: nothing locked, buyer keeps funds, seller keeps deed
        assertEq(buyer.balance, 10 ether);
        assertEq(deed.ownerOf(tokenId), seller);
    }

    function test_LockAndSettle_WithoutDeedApproval_RevertsWholeTx() public {
        // revoke the approval — deed leg must fail and roll back the payment
        vm.prank(seller);
        deed.approve(address(0), tokenId);

        vm.prank(buyer);
        vm.expectRevert(); // ERC721InsufficientApproval
        escrow.lockAndSettle{ value: PRICE }(
            ESCROW_ID, seller, address(deed), tokenId, READINESS
        );
        assertEq(buyer.balance, 10 ether, "buyer funds never moved");
        assertEq(deed.ownerOf(tokenId), seller, "deed never moved");
        assertEq(address(escrow).balance, 0);
    }

    function test_Settle_RejectingSellerWallet_RevertsWholeTx() public {
        RejectingSeller bad = new RejectingSeller();
        uint256 badToken = deed.mint(address(bad), "prop_bad", "ipfs://x");
        vm.prank(address(bad));
        deed.approve(address(escrow), badToken);

        vm.prank(buyer);
        vm.expectRevert("Payment transfer failed");
        escrow.lockAndSettle{ value: PRICE }(
            keccak256("resc_bad"), address(bad), address(deed), badToken, READINESS
        );
        // atomic: payment failed, so the deed did NOT move either
        assertEq(deed.ownerOf(badToken), address(bad));
        assertEq(buyer.balance, 10 ether);
    }

    function test_Settle_RogueNoOpDeed_RevertsWholeTx() public {
        // A rogue deed whose transferFrom does nothing must NOT let funds
        // release: the post-transfer ownerOf check catches the missing move.
        NoOpDeed rogue = new NoOpDeed(seller);
        uint256 sellerBefore = seller.balance;
        vm.prank(buyer);
        vm.expectRevert("Deed not received");
        escrow.lockAndSettle{ value: PRICE }(
            keccak256("resc_rogue"), seller, address(rogue), 1, READINESS
        );
        assertEq(buyer.balance, 10 ether, "buyer funds never moved");
        assertEq(seller.balance, sellerBefore, "seller never paid");
        assertEq(address(escrow).balance, 0);
    }

    function test_Reentrancy_CannotDoubleSettleOrDrain() public {
        ReentrantSeller attacker = new ReentrantSeller();
        uint256 atkToken = deed.mint(address(attacker), "prop_atk", "ipfs://x");
        vm.prank(address(attacker));
        deed.approve(address(escrow), atkToken);
        bytes32 atkId = keccak256("resc_atk");
        attacker.arm(escrow, atkId);

        vm.prank(buyer);
        // The attacker's receive() re-enters settle(); the inner call reverts
        // (state already Settled + reentrancy guard), which makes the payment
        // call fail, which reverts the WHOLE settlement. No partial state.
        vm.expectRevert("Payment transfer failed");
        escrow.lockAndSettle{ value: PRICE }(
            atkId, address(attacker), address(deed), atkToken, READINESS
        );
        assertEq(deed.ownerOf(atkToken), address(attacker));
        assertEq(buyer.balance, 10 ether);
        assertEq(address(escrow).balance, 0, "nothing stranded, nothing drained");
    }

    // ── Two-step lock → settle / refund ─────────────────────────────────

    function test_LockFunds_HoldsBalanceUntilSettle() public {
        vm.prank(buyer);
        vm.expectEmit(true, true, true, false);
        emit FundsLocked(ESCROW_ID, buyer, seller, PRICE, 0);
        escrow.lockFunds{ value: PRICE }(ESCROW_ID, seller, address(deed), tokenId);

        assertEq(address(escrow).balance, PRICE, "escrow custody during lock");
        assertEq(
            uint8(escrow.getEscrow(ESCROW_ID).state),
            uint8(PropertyEscrow.State.Locked)
        );

        vm.prank(buyer);
        escrow.settle(ESCROW_ID, READINESS);
        assertEq(deed.ownerOf(tokenId), buyer);
        assertEq(address(escrow).balance, 0);
    }

    function test_Settle_OnlyBuyer() public {
        vm.prank(buyer);
        escrow.lockFunds{ value: PRICE }(ESCROW_ID, seller, address(deed), tokenId);
        vm.prank(stranger);
        vm.expectRevert("Only buyer");
        escrow.settle(ESCROW_ID, READINESS);
    }

    function test_Settle_Twice_Reverts() public {
        vm.prank(buyer);
        escrow.lockAndSettle{ value: PRICE }(
            ESCROW_ID, seller, address(deed), tokenId, READINESS
        );
        vm.prank(buyer);
        vm.expectRevert("Not locked");
        escrow.settle(ESCROW_ID, READINESS);
    }

    function test_Refund_BeforeDeadline_Reverts() public {
        vm.prank(buyer);
        escrow.lockFunds{ value: PRICE }(ESCROW_ID, seller, address(deed), tokenId);
        vm.prank(buyer);
        vm.expectRevert("Deadline not passed");
        escrow.refund(ESCROW_ID);
    }

    function test_Refund_AfterDeadline_BuyerOnly() public {
        vm.prank(buyer);
        escrow.lockFunds{ value: PRICE }(ESCROW_ID, seller, address(deed), tokenId);
        vm.warp(block.timestamp + 7 days + 1);

        vm.prank(stranger);
        vm.expectRevert("Only buyer");
        escrow.refund(ESCROW_ID);

        vm.prank(buyer);
        vm.expectEmit(true, true, false, true);
        emit Refunded(ESCROW_ID, buyer, PRICE);
        escrow.refund(ESCROW_ID);
        assertEq(buyer.balance, 10 ether, "full refund");
        assertEq(
            uint8(escrow.getEscrow(ESCROW_ID).state),
            uint8(PropertyEscrow.State.Refunded)
        );

        // refunded is terminal — settle can never run afterwards
        vm.prank(buyer);
        vm.expectRevert("Not locked");
        escrow.settle(ESCROW_ID, READINESS);
    }

    // ── No backdoor: nobody but the buyer's two paths can move funds ────

    function test_NoBackdoor_DeployerCannotTouchLockedFunds() public {
        vm.prank(buyer);
        escrow.lockFunds{ value: PRICE }(ESCROW_ID, seller, address(deed), tokenId);

        // the deployer (this test contract) is a stranger to the escrow:
        vm.expectRevert("Only buyer");
        escrow.settle(ESCROW_ID, READINESS);
        vm.warp(block.timestamp + 7 days + 1);
        vm.expectRevert("Only buyer");
        escrow.refund(ESCROW_ID);
        // and there is no owner(), withdraw(), sweep(), pause() — the ABI has
        // exactly lockAndSettle/lockFunds/settle/refund/getEscrow/escrows/
        // lockTimeout. Locked funds stay locked.
        assertEq(address(escrow).balance, PRICE);
    }

    // ── Input validation ────────────────────────────────────────────────

    function test_Lock_ZeroValue_Reverts() public {
        vm.prank(buyer);
        vm.expectRevert("No funds");
        escrow.lockFunds(ESCROW_ID, seller, address(deed), tokenId);
    }

    function test_Lock_DuplicateEscrowId_Reverts() public {
        vm.prank(buyer);
        escrow.lockFunds{ value: PRICE }(ESCROW_ID, seller, address(deed), tokenId);
        vm.prank(stranger);
        vm.expectRevert("Escrow exists");
        escrow.lockFunds{ value: PRICE }(ESCROW_ID, seller, address(deed), tokenId);
    }

    function test_Lock_SelfPurchase_Reverts() public {
        vm.deal(seller, 2 ether);
        vm.prank(seller);
        vm.expectRevert("Self purchase");
        escrow.lockFunds{ value: PRICE }(ESCROW_ID, seller, address(deed), tokenId);
    }

    function test_Lock_ZeroInputs_Revert() public {
        vm.startPrank(buyer);
        vm.expectRevert("Zero escrow id");
        escrow.lockFunds{ value: PRICE }(bytes32(0), seller, address(deed), tokenId);
        vm.expectRevert("Zero seller");
        escrow.lockFunds{ value: PRICE }(ESCROW_ID, address(0), address(deed), tokenId);
        vm.expectRevert("Zero deed contract");
        escrow.lockFunds{ value: PRICE }(ESCROW_ID, seller, address(0), tokenId);
        vm.stopPrank();
    }

    function test_Constructor_TimeoutFloor() public {
        vm.expectRevert("Timeout too short");
        new PropertyEscrow(30 minutes);
    }
}
