// SPDX-License-Identifier: MIT
pragma solidity ^0.8.20;

import "@openzeppelin/contracts/utils/ReentrancyGuard.sol";
import "@openzeppelin/contracts/access/Ownable.sol";

/**
 * @title OpenMatrixStaking
 * @notice Staking with 5% commission on rewards, 1 ETH minimum stake.
 *         Commission is routed to platformFeeRecipient (NeoSafe).
 */
contract OpenMatrixStaking is ReentrancyGuard, Ownable {

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

        // If existing position, auto-claim accrued rewards first
        if (pos.amount > 0) {
            _claimRewards(msg.sender);
        }

        pos.amount += msg.value;
        if (pos.startTime == 0) {
            pos.startTime = block.timestamp;
        }
        pos.lastClaimTime = block.timestamp;

        totalStaked += msg.value;

        emit Staked(msg.sender, msg.value, block.timestamp);
    }

    /**
     * @notice Unstake all staked ETH and claim outstanding rewards.
     */
    function unstake() external nonReentrant {
        StakePosition storage pos = positions[msg.sender];
        require(pos.amount > 0, "No active position");

        uint256 stakedAmount = pos.amount;
        (uint256 grossReward, uint256 commission, uint256 netReward) = _calculateRewards(msg.sender);

        // Reset position
        pos.amount = 0;
        pos.startTime = 0;
        pos.lastClaimTime = 0;

        totalStaked -= stakedAmount;

        // Pay commission
        if (commission > 0 && address(this).balance >= commission) {
            totalCommissionPaid += commission;
            (bool feeSent, ) = platformFeeRecipient.call{value: commission}("");
            require(feeSent, "Commission transfer failed");
        }

        // Pay staker (principal + net reward)
        uint256 payout = stakedAmount + netReward;
        if (payout > 0 && address(this).balance >= payout) {
            totalRewardsPaid += netReward;
            (bool sent, ) = msg.sender.call{value: payout}("");
            require(sent, "Unstake transfer failed");
        }

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
            return (0, 0, 0);
        }

        uint256 elapsed = block.timestamp - pos.lastClaimTime;
        grossReward = (pos.amount * REWARD_RATE_PER_SECOND * elapsed) / 1 ether;
        commission = (grossReward * COMMISSION_BPS) / BPS_DENOMINATOR;
        netReward = grossReward - commission;
    }

    function _claimRewards(address user) internal {
        (uint256 grossReward, uint256 commission, uint256 netReward) = _calculateRewards(user);
        require(netReward > 0, "No rewards to claim");

        StakePosition storage pos = positions[user];
        pos.lastClaimTime = block.timestamp;
        pos.totalClaimed += netReward;

        // Pay commission
        if (commission > 0 && address(this).balance >= commission) {
            totalCommissionPaid += commission;
            (bool feeSent, ) = platformFeeRecipient.call{value: commission}("");
            require(feeSent, "Commission transfer failed");
        }

        // Pay staker
        if (netReward > 0 && address(this).balance >= netReward) {
            totalRewardsPaid += netReward;
            (bool sent, ) = user.call{value: netReward}("");
            require(sent, "Reward transfer failed");
        }

        emit RewardsClaimed(user, netReward, commission);
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
        // ETH is received via msg.value; no logic needed.
    }

    receive() external payable {}
}
