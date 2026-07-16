// SPDX-License-Identifier: MIT
pragma solidity ^0.8.20;

import "@openzeppelin/contracts/token/ERC721/IERC721.sol";
import "@openzeppelin/contracts/utils/ReentrancyGuard.sol";

/**
 * @title PropertyEscrow
 * @notice Escrow for one-tap real-estate settlement: buyer funds lock and
 *         settle ATOMICALLY against the property's deed token — funds release
 *         to the seller ONLY in the same transaction that transfers the deed
 *         to the buyer, with the transaction-readiness attestation UID bound
 *         into the settlement event. All-or-nothing: if any leg fails, the
 *         whole transaction reverts and the buyer's funds never move.
 *
 *         NO OWNER, NO BACKDOOR — deliberately. This contract has no owner,
 *         no operator role, no pause switch, and no function that can move a
 *         buyer's locked funds anywhere except (a) to the seller inside a
 *         successful atomic settlement executed by the BUYER, or (b) back to
 *         the buyer via the refund path after the lock deadline. The platform
 *         cannot touch escrowed money, structurally.
 *
 *         Two flows share one settlement core:
 *           • lockAndSettle — the one-tap: lock + deed transfer + release in
 *             ONE transaction (the platform verifies readiness server-side
 *             and supplies the attestation UID before preparing the call).
 *           • lockFunds → settle — the two-step: funds sit locked (deadline-
 *             bounded); settlement is buyer-triggered when conditions green;
 *             refund is buyer-only after the deadline if never settled.
 *
 *         The seller must have approved this contract on the deed token
 *         BEFORE settlement (part of listing). If approval is missing, the
 *         deed transfer reverts and — atomically — so does the payment.
 */
contract PropertyEscrow is ReentrancyGuard {
    // ---------------------------------------------------------------
    // Types + state
    // ---------------------------------------------------------------
    enum State {
        None,      // never used
        Locked,    // funds held, awaiting settle or refund
        Settled,   // deed transferred + funds released, terminal
        Refunded   // funds returned to buyer, terminal
    }

    struct Escrow {
        address buyer;
        address seller;
        address deedContract;
        uint256 deedTokenId;
        uint256 amount;
        uint64 deadline;   // after this, an unsettled lock is refundable
        State state;
    }

    /// @notice How long locked funds wait for settlement before the buyer can
    ///         reclaim them. Fixed at deploy; no one can change it after.
    uint64 public immutable lockTimeout;

    mapping(bytes32 => Escrow) public escrows;

    // ---------------------------------------------------------------
    // Events
    // ---------------------------------------------------------------
    event FundsLocked(
        bytes32 indexed escrowId,
        address indexed buyer,
        address indexed seller,
        uint256 amount,
        uint64 deadline
    );
    event Settled(
        bytes32 indexed escrowId,
        address indexed buyer,
        address indexed seller,
        uint256 amount,
        uint256 deedTokenId,
        bytes32 readinessAttestation
    );
    event Refunded(bytes32 indexed escrowId, address indexed buyer, uint256 amount);

    // ---------------------------------------------------------------
    // Constructor
    // ---------------------------------------------------------------
    constructor(uint64 _lockTimeout) {
        require(_lockTimeout >= 1 hours, "Timeout too short");
        lockTimeout = _lockTimeout;
    }

    // ---------------------------------------------------------------
    // One-tap: lock + settle atomically
    // ---------------------------------------------------------------

    /**
     * @notice The one-tap purchase: lock the attached funds AND settle in the
     *         same transaction. The deed moves seller -> buyer and the funds
     *         move buyer -> seller, all-or-nothing.
     * @param escrowId              Platform escrow record id (bytes32 hash).
     * @param seller                Deed holder being paid.
     * @param deedContract          The PropertyDeed (ERC-721) contract.
     * @param deedTokenId           The property's deed token.
     * @param readinessAttestation  EAS UID of the transaction-readiness
     *                              snapshot. Zero is refused — settlement
     *                              without a readiness attestation is not a
     *                              condition set, it's a hope.
     */
    function lockAndSettle(
        bytes32 escrowId,
        address seller,
        address deedContract,
        uint256 deedTokenId,
        bytes32 readinessAttestation
    ) external payable nonReentrant {
        _lock(escrowId, seller, deedContract, deedTokenId);
        _settle(escrowId, readinessAttestation);
    }

    // ---------------------------------------------------------------
    // Two-step: lock, then settle later
    // ---------------------------------------------------------------

    /// @notice Lock funds for a pending purchase. Refundable by the buyer
    ///         after the deadline if never settled.
    function lockFunds(
        bytes32 escrowId,
        address seller,
        address deedContract,
        uint256 deedTokenId
    ) external payable nonReentrant {
        _lock(escrowId, seller, deedContract, deedTokenId);
    }

    /// @notice Settle a previously locked escrow: deed -> buyer and funds ->
    ///         seller atomically. Buyer-only — the buyer is the party who
    ///         must be satisfied the condition set is green.
    function settle(bytes32 escrowId, bytes32 readinessAttestation)
        external
        nonReentrant
    {
        require(msg.sender == escrows[escrowId].buyer, "Only buyer");
        _settle(escrowId, readinessAttestation);
    }

    /// @notice Reclaim locked funds after the deadline. Buyer-only; only from
    ///         Locked; terminal. This is the ONLY path that moves funds other
    ///         than settlement-to-seller.
    function refund(bytes32 escrowId) external nonReentrant {
        Escrow storage e = escrows[escrowId];
        require(e.state == State.Locked, "Not locked");
        require(msg.sender == e.buyer, "Only buyer");
        require(block.timestamp > e.deadline, "Deadline not passed");

        e.state = State.Refunded; // effects before interaction (CEI)
        uint256 amount = e.amount;
        e.amount = 0;

        (bool ok, ) = payable(e.buyer).call{ value: amount }("");
        require(ok, "Refund transfer failed");
        emit Refunded(escrowId, e.buyer, amount);
    }

    // ---------------------------------------------------------------
    // Internal core
    // ---------------------------------------------------------------

    function _lock(
        bytes32 escrowId,
        address seller,
        address deedContract,
        uint256 deedTokenId
    ) internal {
        require(escrowId != bytes32(0), "Zero escrow id");
        require(seller != address(0), "Zero seller");
        require(deedContract != address(0), "Zero deed contract");
        require(msg.value > 0, "No funds");
        require(escrows[escrowId].state == State.None, "Escrow exists");
        require(seller != msg.sender, "Self purchase");

        escrows[escrowId] = Escrow({
            buyer: msg.sender,
            seller: seller,
            deedContract: deedContract,
            deedTokenId: deedTokenId,
            amount: msg.value,
            deadline: uint64(block.timestamp) + lockTimeout,
            state: State.Locked
        });
        emit FundsLocked(
            escrowId, msg.sender, seller, msg.value,
            uint64(block.timestamp) + lockTimeout
        );
    }

    function _settle(bytes32 escrowId, bytes32 readinessAttestation) internal {
        Escrow storage e = escrows[escrowId];
        require(e.state == State.Locked, "Not locked");
        require(readinessAttestation != bytes32(0), "No readiness attestation");

        e.state = State.Settled; // effects before interactions (CEI)
        uint256 amount = e.amount;
        e.amount = 0;

        // Leg 1: deed seller -> buyer. Reverts (and rolls back EVERYTHING,
        // including the funds lock in the one-tap flow) if the seller no
        // longer holds the deed or never approved this contract.
        IERC721(e.deedContract).transferFrom(e.seller, e.buyer, e.deedTokenId);

        // Leg 1b: PROVE the deed actually moved. A rogue/non-conforming ERC-721
        // whose transferFrom is a silent no-op would otherwise let funds release
        // with no real deed transfer — so we assert post-state ownership. Funds
        // can never reach the seller unless the buyer genuinely holds the deed.
        require(
            IERC721(e.deedContract).ownerOf(e.deedTokenId) == e.buyer,
            "Deed not received"
        );

        // Leg 2: funds -> seller. A rejecting seller wallet reverts the whole
        // settlement — funds can never be released without the deed moving,
        // and the deed can never move without the funds releasing.
        (bool ok, ) = payable(e.seller).call{ value: amount }("");
        require(ok, "Payment transfer failed");

        emit Settled(
            escrowId, e.buyer, e.seller, amount, e.deedTokenId,
            readinessAttestation
        );
    }

    // ---------------------------------------------------------------
    // Views
    // ---------------------------------------------------------------

    function getEscrow(bytes32 escrowId) external view returns (Escrow memory) {
        return escrows[escrowId];
    }
}
