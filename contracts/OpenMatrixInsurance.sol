// SPDX-License-Identifier: MIT
pragma solidity ^0.8.20;

import "@openzeppelin/contracts/utils/ReentrancyGuard.sol";
import "@openzeppelin/contracts/access/Ownable.sol";

/**
 * @title OpenMatrixInsurance
 * @notice Parametric insurance with oracle triggers, tiered premiums, and reserve fund.
 *         Payouts are automatic when oracle reports a trigger event.
 */
contract OpenMatrixInsurance is ReentrancyGuard, Ownable {

    // ---------------------------------------------------------------
    // Enums & Structs
    // ---------------------------------------------------------------
    enum RiskTier {
        Low,       // 2% premium rate
        Medium,    // 5% premium rate
        High       // 10% premium rate
    }

    enum PolicyState {
        Active,
        Claimed,
        Expired,
        Cancelled
    }

    struct Policy {
        uint256 id;
        address holder;
        uint256 coverageAmount;
        uint256 premiumPaid;
        RiskTier tier;
        PolicyState policyState;
        uint256 startTime;
        uint256 endTime;
        bytes32 triggerCondition;  // keccak256 of the parametric trigger description
    }

    struct TriggerEvent {
        bytes32 conditionHash;
        uint256 timestamp;
        address reporter;          // oracle address
        bool validated;
    }

    // ---------------------------------------------------------------
    // Constants
    // ---------------------------------------------------------------
    uint256 public constant MIN_COVERAGE = 0.01 ether;
    uint256 public constant MAX_COVERAGE = 100 ether;
    uint256 public constant DEFAULT_POLICY_DURATION = 30 days;
    uint256 public constant RESERVE_RATIO_BPS = 2_000; // 20% of premiums go to reserve
    /// @notice A trigger must occur at least this long after a policy starts.
    ///         Without it (audit entry B3-INS-SAME-BLOCK-BACKRUN) a policy bought
    ///         in the trigger's own block — backrunning the oracle — claimed at
    ///         up to 50:1, repeatedly, until the pool was empty.
    uint256 public constant MIN_POLICY_AGE = 1 days;
    /// @notice Open policies one address may hold at once.
    uint256 public constant MAX_ACTIVE_POLICIES_PER_HOLDER = 5;
    uint256 private constant BPS_DENOMINATOR = 10_000;

    // ---------------------------------------------------------------
    // State
    // ---------------------------------------------------------------
    address public platformFeeRecipient; // NeoSafe
    address public oracle;               // trusted oracle address

    uint256 private _nextPolicyId;
    mapping(uint256 => Policy) public policies;
    mapping(bytes32 => TriggerEvent) public triggerEvents;

    uint256 public totalPremiumsCollected;
    uint256 public totalPayoutsMade;
    uint256 public reserveFund;
    uint256 public activePoliciesCount;
    /// @notice Coverage the pool owes if every active policy triggered — a
    ///         liability: no policy is sold beyond what the pool holds, and the
    ///         owner cannot withdraw into it (B3-INS-UNBACKED-COVERAGE,
    ///         B3-INS-OWNER-SWEEP).
    uint256 public totalOutstandingCoverage;
    mapping(address => uint256) public activePoliciesOf;

    // ---------------------------------------------------------------
    // Events
    // ---------------------------------------------------------------
    event PolicyCreated(
        uint256 indexed policyId,
        address indexed holder,
        uint256 coverageAmount,
        uint256 premiumPaid,
        RiskTier tier
    );
    event PolicyClaimed(uint256 indexed policyId, address indexed holder, uint256 payout);
    event PolicyExpired(uint256 indexed policyId);
    event PolicyCancelled(uint256 indexed policyId, uint256 refund);
    event TriggerReported(bytes32 indexed conditionHash, address indexed reporter, uint256 timestamp);
    event OracleUpdated(address oldOracle, address newOracle);

    // ---------------------------------------------------------------
    // Constructor
    // ---------------------------------------------------------------
    constructor(address _platformFeeRecipient, address _oracle) Ownable(msg.sender) {
        require(_platformFeeRecipient != address(0), "Zero fee recipient");
        require(_oracle != address(0), "Zero oracle");
        platformFeeRecipient = _platformFeeRecipient;
        oracle = _oracle;
    }

    // ---------------------------------------------------------------
    // Premium calculation
    // ---------------------------------------------------------------

    function calculatePremium(uint256 coverageAmount, RiskTier tier)
        public
        pure
        returns (uint256 premium)
    {
        uint256 rateBps;
        if (tier == RiskTier.Low) {
            rateBps = 200;   // 2%
        } else if (tier == RiskTier.Medium) {
            rateBps = 500;   // 5%
        } else {
            rateBps = 1_000; // 10%
        }
        premium = (coverageAmount * rateBps) / BPS_DENOMINATOR;
    }

    // ---------------------------------------------------------------
    // Policy management
    // ---------------------------------------------------------------

    /**
     * @notice Purchase an insurance policy by paying the premium.
     * @param coverageAmount Desired coverage (paid out on trigger).
     * @param tier           Risk tier determining premium rate.
     * @param triggerCondition keccak256 of the parametric trigger description.
     */
    function purchasePolicy(
        uint256 coverageAmount,
        RiskTier tier,
        bytes32 triggerCondition
    ) external payable nonReentrant returns (uint256 policyId) {
        require(coverageAmount >= MIN_COVERAGE, "Below min coverage");
        require(coverageAmount <= MAX_COVERAGE, "Exceeds max coverage");

        uint256 premium = calculatePremium(coverageAmount, tier);
        require(msg.value >= premium, "Insufficient premium");

        // Refund overpayment
        if (msg.value > premium) {
            (bool refunded, ) = msg.sender.call{value: msg.value - premium}("");
            require(refunded, "Refund failed");
        }

        // Coverage is sold only against what the pool actually holds (the
        // premium just paid included): outstanding coverage is a liability.
        require(
            totalOutstandingCoverage + coverageAmount <= address(this).balance,
            "Coverage exceeds backing"
        );
        require(
            activePoliciesOf[msg.sender] < MAX_ACTIVE_POLICIES_PER_HOLDER,
            "Too many active policies"
        );

        // Allocate premium: reserve + platform pool
        uint256 reserveAlloc = (premium * RESERVE_RATIO_BPS) / BPS_DENOMINATOR;
        reserveFund += reserveAlloc;
        totalPremiumsCollected += premium;
        totalOutstandingCoverage += coverageAmount;
        activePoliciesOf[msg.sender]++;

        policyId = _nextPolicyId++;
        policies[policyId] = Policy({
            id: policyId,
            holder: msg.sender,
            coverageAmount: coverageAmount,
            premiumPaid: premium,
            tier: tier,
            policyState: PolicyState.Active,
            startTime: block.timestamp,
            endTime: block.timestamp + DEFAULT_POLICY_DURATION,
            triggerCondition: triggerCondition
        });

        activePoliciesCount++;

        emit PolicyCreated(policyId, msg.sender, coverageAmount, premium, tier);
    }

    /**
     * @notice Claim a policy payout after an oracle-reported trigger event.
     */
    function claimPolicy(uint256 policyId) external nonReentrant {
        Policy storage p = policies[policyId];
        require(p.holder == msg.sender, "Not policy holder");
        require(p.policyState == PolicyState.Active, "Not active");
        require(block.timestamp <= p.endTime, "Policy expired");

        TriggerEvent storage te = triggerEvents[p.triggerCondition];
        require(te.validated, "No validated trigger event");
        require(te.timestamp > p.startTime, "Trigger not after policy start");
        require(te.timestamp >= p.startTime + MIN_POLICY_AGE, "Policy too new for this trigger");

        p.policyState = PolicyState.Claimed;
        activePoliciesCount--;
        activePoliciesOf[p.holder]--;
        totalOutstandingCoverage -= p.coverageAmount;
        totalPayoutsMade += p.coverageAmount;

        // Pay from contract balance (premiums + reserve)
        require(address(this).balance >= p.coverageAmount, "Insufficient contract balance");

        (bool sent, ) = p.holder.call{value: p.coverageAmount}("");
        require(sent, "Payout failed");

        emit PolicyClaimed(policyId, p.holder, p.coverageAmount);
    }

    /**
     * @notice Mark a policy as expired (callable by anyone after endTime).
     */
    function expirePolicy(uint256 policyId) external {
        Policy storage p = policies[policyId];
        require(p.policyState == PolicyState.Active, "Not active");
        require(block.timestamp > p.endTime, "Not yet expired");

        p.policyState = PolicyState.Expired;
        activePoliciesCount--;
        activePoliciesOf[p.holder]--;
        totalOutstandingCoverage -= p.coverageAmount;

        emit PolicyExpired(policyId);
    }

    /**
     * @notice Cancel a policy and receive a partial refund (50% of premium).
     */
    function cancelPolicy(uint256 policyId) external nonReentrant {
        Policy storage p = policies[policyId];
        require(p.holder == msg.sender, "Not policy holder");
        require(p.policyState == PolicyState.Active, "Not active");

        p.policyState = PolicyState.Cancelled;
        activePoliciesCount--;
        activePoliciesOf[p.holder]--;
        totalOutstandingCoverage -= p.coverageAmount;

        uint256 refund = p.premiumPaid / 2;
        if (refund > 0 && address(this).balance >= refund) {
            (bool sent, ) = p.holder.call{value: refund}("");
            require(sent, "Refund failed");
        }

        emit PolicyCancelled(policyId, refund);
    }

    // ---------------------------------------------------------------
    // Oracle
    // ---------------------------------------------------------------

    /**
     * @notice Oracle reports a trigger event (e.g., price drop, weather event).
     */
    function reportTrigger(bytes32 conditionHash) external {
        require(msg.sender == oracle, "Only oracle");
        require(!triggerEvents[conditionHash].validated, "Already reported");

        triggerEvents[conditionHash] = TriggerEvent({
            conditionHash: conditionHash,
            timestamp: block.timestamp,
            reporter: msg.sender,
            validated: true
        });

        emit TriggerReported(conditionHash, msg.sender, block.timestamp);
    }

    // ---------------------------------------------------------------
    // Admin
    // ---------------------------------------------------------------

    function updateOracle(address newOracle) external onlyOwner {
        require(newOracle != address(0), "Zero address");
        address old = oracle;
        oracle = newOracle;
        emit OracleUpdated(old, newOracle);
    }

    function updateFeeRecipient(address newRecipient) external onlyOwner {
        require(newRecipient != address(0), "Zero address");
        platformFeeRecipient = newRecipient;
    }

    /**
     * @notice Withdraw excess funds — beyond the reserve AND beyond the coverage
     *         the pool still owes — to the platform fee recipient.
     */
    function withdrawExcess() external onlyOwner nonReentrant {
        uint256 liabilities = reserveFund + totalOutstandingCoverage;
        uint256 excess = address(this).balance > liabilities
            ? address(this).balance - liabilities
            : 0;
        require(excess > 0, "No excess");

        (bool sent, ) = platformFeeRecipient.call{value: excess}("");
        require(sent, "Withdrawal failed");
    }

    receive() external payable {}
}
