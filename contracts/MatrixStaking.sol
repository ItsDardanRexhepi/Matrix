// SPDX-License-Identifier: MIT
pragma solidity ^0.8.20;

import "@openzeppelin/contracts/utils/ReentrancyGuard.sol";
import "@openzeppelin/contracts/access/Ownable.sol";

/**
 * @title MatrixStaking
 * @notice Staking with 5% commission on rewards, 1 ETH minimum stake.
 *         Commission is routed to platformFeeRecipient (NeoSafe).
 */
contract MatrixStaking is ReentrancyGuard, Ownable {

    // ---------------------------------------------------------------
    // Constants
    // ---------------------------------------------------------------
    uint256 public constant MINIMUM_STAKE = 1 ether;
    uint256 public constant COMMISSION_BPS = 500;        // 5%
    uint256 private constant BPS_DENOMINATOR = 10_000;
    uint256 public constant REWARD_RATE_PER_SECOND = 3_170_979_198; // ~10% APR in wei/sec per 1 ETH

    // ---------------------------------------------------------------
    // State
    // ---------------------------------------------------------------
    address public platformFeeRecipient;

    struct StakePosition {
        uint256 amount;
        uint256 startTime;
        uint256 lastClaimTime;
        uint256 totalClaimed;
    }

    mapping(address => StakePosition) public positions;

    uint256 public totalStaked;
    uint256 public totalRewardsPaid;
    uint256 public totalCommissionPaid;
    /// @notice ETH funded for rewards. Rewards are paid ONLY from here — never
    ///         from stakers' principal (audit entries B3-STAKE-PRINCIPAL-PAYS-REWARDS,
    ///         B3-STAKE-SHORTFALL-ERASES: rewards accrued unconditionally, were
    ///         paid from one pooled balance, and a shortfall erased a late
    ///         exit's principal with the transaction succeeding).
    uint256 public rewardReserve;
    /// @notice Rewards accrued but not yet funded, per staker — paid when the
    ///         reserve is refilled; nothing is erased.
    mapping(address => uint256) public owedRewards;
    /// @notice Commission a fee recipient could not receive (its call
    ///         reverted). Pulled later with withdrawFees(); an exit never
    ///         depends on the recipient (audit entry B3-STAKE-FEE-FREEZE).
    uint256 public pendingFees;

    // ---------------------------------------------------------------
    // Events
    // ---------------------------------------------------------------
    event Staked(address indexed user, uint256 amount, uint256 timestamp);
    event Unstaked(address indexed user, uint256 amount, uint256 rewardsPaid, uint256 commission);
    event RewardsClaimed(address indexed user, uint256 rewards, uint256 commission);
    event FeeRecipientUpdated(address oldRecipient, address newRecipient);

    // ---------------------------------------------------------------
    // Constructor
    // ---------------------------------------------------------------
    constructor(address _platformFeeRecipient) Ownable(msg.sender) {
        require(_platformFeeRecipient != address(0), "Zero fee recipient");
        platformFeeRecipient = _platformFeeRecipient;
    }

    // ---------------------------------------------------------------
    // Staking
    // ---------------------------------------------------------------

    /**
     * @notice Stake native ETH. Minimum 1 ETH.
     */
    function stake() external payable nonReentrant {
        require(msg.value >= MINIMUM_STAKE, "Below minimum stake of 1 ETH");

        StakePosition storage pos = positions[msg.sender];

        // Accrue on the OLD amount — the new stake has not been earning yet —
        // and hold the payout until every write below is done.
        uint256 netReward;
        uint256 commission;
        if (pos.amount > 0) {
            (netReward, commission) = _accrueRewards(msg.sender);
        }

        pos.amount += msg.value;
        if (pos.startTime == 0) {
            pos.startTime = block.timestamp;
        }
        pos.lastClaimTime = block.timestamp;

        totalStaked += msg.value;

        emit Staked(msg.sender, msg.value, block.timestamp);

        // Interactions last.
        _payRewards(msg.sender, netReward, commission);
    }

    /**
     * @notice Unstake all staked ETH and claim outstanding rewards.
     */
    function unstake() external nonReentrant {
        StakePosition storage pos = positions[msg.sender];
        require(pos.amount > 0, "No active position");

        uint256 stakedAmount = pos.amount;
        // Accrue from the reserve only; whatever it cannot pay is recorded as
        // owed, not erased. Nothing leaves the contract yet.
        (uint256 netReward, uint256 commission) = _accrueRewards(msg.sender);

        // Reset position
        pos.amount = 0;
        pos.startTime = 0;
        pos.lastClaimTime = 0;

        totalStaked -= stakedAmount;

        // Interactions last, with every write above already committed.
        _payRewards(msg.sender, netReward, commission);

        // Principal is always there: nothing but principal is ever paid from it.
        require(address(this).balance >= stakedAmount, "Insufficient pool");
        (bool sent, ) = msg.sender.call{value: stakedAmount}("");
        require(sent, "Unstake transfer failed");

        emit Unstaked(msg.sender, stakedAmount, netReward, commission);
    }

    /**
     * @notice Claim accrued rewards without unstaking.
     */
    function claimRewards() external nonReentrant {
        _claimRewards(msg.sender);
    }

    /**
     * @notice View current stake position and pending rewards.
     */
    function getPosition(address user)
        external
        view
        returns (
            uint256 stakedAmount,
            uint256 pendingGrossReward,
            uint256 pendingCommission,
            uint256 pendingNetReward,
            uint256 startTime,
            uint256 totalClaimedSoFar
        )
    {
        StakePosition storage pos = positions[user];
        (uint256 gross, uint256 comm, uint256 net) = _calculateRewards(user);
        return (pos.amount, gross, comm, net, pos.startTime, pos.totalClaimed);
    }

    // ---------------------------------------------------------------
    // Internal
    // ---------------------------------------------------------------

    function _calculateRewards(address user)
        internal
        view
        returns (uint256 grossReward, uint256 commission, uint256 netReward)
    {
        StakePosition storage pos = positions[user];
        if (pos.amount == 0 || pos.lastClaimTime == 0) {
            // No live position: only what is still owed from before.
            grossReward = owedRewards[user];
            commission = (grossReward * COMMISSION_BPS) / BPS_DENOMINATOR;
            netReward = grossReward - commission;
            return (grossReward, commission, netReward);
        }

        uint256 elapsed = block.timestamp - pos.lastClaimTime;
        grossReward = (pos.amount * REWARD_RATE_PER_SECOND * elapsed) / 1 ether + owedRewards[user];
        commission = (grossReward * COMMISSION_BPS) / BPS_DENOMINATOR;
        netReward = grossReward - commission;
    }

    function _claimRewards(address user) internal {
        (, , uint256 accrued) = _calculateRewards(user);
        require(accrued > 0, "No rewards to claim");
        (uint256 netReward, uint256 commission) = _accrueRewards(user);
        _payRewards(user, netReward, commission);
    }

    /// @dev Pay what the reserve can cover of the accrued gross reward (plus
    ///      anything owed from before); record the rest as owed. Commission is
    ///      taken from the paid part and pushed to the fee recipient, falling
    ///      back to `pendingFees` if that call fails. Never reverts on an empty
    ///      reserve, never touches principal.
    /// @dev ACCRUE ONLY — every state write, no transfer. Splitting this out is
    ///      the point: `_settleRewards` used to write the position and then send
    ///      ETH from inside itself, which meant `stake()` and `unstake()` made an
    ///      external call BEFORE they had finished updating their own state.
    ///      Exploiting that needed an unguarded way back in, and there was none —
    ///      every state-changing entry point carries `nonReentrant`, and
    ///      MatrixStakingReentrancy.t.sol proves an attacker re-entering on every
    ///      payout takes nothing. But that made one modifier the only thing
    ///      between the pool and a drain, and the next function added without it
    ///      would have been the hole. Now the ordering is safe on its own and the
    ///      guard is the second line rather than the only one.
    function _accrueRewards(address user) internal returns (uint256 netReward, uint256 commission) {
        (uint256 grossReward, , ) = _calculateRewards(user);
        StakePosition storage pos = positions[user];
        pos.lastClaimTime = block.timestamp;
        if (grossReward == 0) {
            return (0, 0);
        }
        uint256 payable_ = grossReward <= rewardReserve ? grossReward : rewardReserve;
        owedRewards[user] = grossReward - payable_;
        if (payable_ == 0) {
            return (0, 0);
        }
        rewardReserve -= payable_;
        commission = (payable_ * COMMISSION_BPS) / BPS_DENOMINATOR;
        netReward = payable_ - commission;
        pos.totalClaimed += netReward;
        if (commission > 0) {
            totalCommissionPaid += commission;
        }
        if (netReward > 0) {
            totalRewardsPaid += netReward;
        }
        emit RewardsClaimed(user, netReward, commission);
    }

    /// @dev PAY ONLY — no state write. Called last, after the caller has
    ///      finished every update it intends to make.
    // slither-disable-next-line arbitrary-send-eth
    function _payRewards(address user, uint256 netReward, uint256 commission) internal {
        if (commission > 0) {
            // Not arbitrary: platformFeeRecipient is set by the owner alone
            // (updateFeeRecipient is onlyOwner and rejects the zero address),
            // and `user` is the staker being paid their own accrued reward.
            // Neither address comes from a caller.
                (bool feeSent, ) = platformFeeRecipient.call{value: commission}("");
            if (!feeSent) {
                pendingFees += commission;   // pulled later; the staker is never blocked
            }
        }
        if (netReward > 0) {
            // slither-disable-next-line arbitrary-send-eth
            // `user` is the staker whose own accrued reward this is — the
            // address is read from the position being settled, never supplied
            // by a caller.
            (bool sent, ) = user.call{value: netReward}("");
            require(sent, "Reward transfer failed");
        }
    }

    /// @notice Send commission the fee recipient could not receive earlier.
    function withdrawFees() external nonReentrant {
        uint256 amount = pendingFees;
        require(amount > 0, "No pending fees");
        pendingFees = 0;
        // slither-disable-next-line arbitrary-send-eth
        // platformFeeRecipient is owner-set and non-zero; this pushes fees that
        // an earlier call could not deliver, and the balance is zeroed first.
        // slither-disable-next-line arbitrary-send-eth
        (bool sent, ) = platformFeeRecipient.call{value: amount}("");
        require(sent, "Fee transfer failed");
    }

    // ---------------------------------------------------------------
    // Admin
    // ---------------------------------------------------------------

    function updateFeeRecipient(address newRecipient) external onlyOwner {
        require(newRecipient != address(0), "Zero address");
        address old = platformFeeRecipient;
        platformFeeRecipient = newRecipient;
        emit FeeRecipientUpdated(old, newRecipient);
    }

    /**
     * @notice Fund the contract with ETH for reward payouts.
     */
    function fundRewards() external payable onlyOwner {
        rewardReserve += msg.value;
    }

    receive() external payable {
        rewardReserve += msg.value;
    }
}
