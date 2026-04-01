// SPDX-License-Identifier: MIT
pragma solidity ^0.8.20;

import "@openzeppelin/contracts/access/Ownable.sol";
import "@openzeppelin/contracts/utils/ReentrancyGuard.sol";

/**
 * @title OpenMatrixDAO
 * @notice DAO Governor with 3 voting models, quorum, treasury.
 *         Tiered treasury fees: <10K = 1%, 10K-100K = 0.5%, >100K = 0.25%.
 */
contract OpenMatrixDAO is ReentrancyGuard, Ownable {

    // ---------------------------------------------------------------
    // Enums
    // ---------------------------------------------------------------
    enum VotingModel {
        SimpleMajority,     // >50% of votes cast
        SuperMajority,      // >=66.7% of votes cast
        QuadraticVoting     // sqrt(tokens) = voting power
    }

    enum ProposalState {
        Pending,
        Active,
        Defeated,
        Succeeded,
        Executed,
        Cancelled
    }

    // ---------------------------------------------------------------
    // Structs
    // ---------------------------------------------------------------
    struct Proposal {
        uint256 id;
        address proposer;
        string description;
        VotingModel votingModel;
        uint256 startBlock;
        uint256 endBlock;
        uint256 forVotes;
        uint256 againstVotes;
        uint256 abstainVotes;
        bool executed;
        bool cancelled;
        address[] targets;
        uint256[] values;
        bytes[] calldatas;
    }

    // ---------------------------------------------------------------
    // Constants & Config
    // ---------------------------------------------------------------
    uint256 public constant VOTING_PERIOD = 50_400;      // ~7 days at 12s blocks
    uint256 public constant VOTING_DELAY = 7_200;        // ~1 day
    uint256 public constant QUORUM_BPS = 400;            // 4% of total voting power
    uint256 private constant BPS_DENOMINATOR = 10_000;

    address public platformFeeRecipient; // NeoSafe

    // ---------------------------------------------------------------
    // State
    // ---------------------------------------------------------------
    uint256 private _nextProposalId;
    mapping(uint256 => Proposal) public proposals;
    mapping(uint256 => mapping(address => bool)) public hasVoted;
    mapping(address => uint256) public votingPower;      // token-style balances
    uint256 public totalVotingPower;

    // ---------------------------------------------------------------
    // Events
    // ---------------------------------------------------------------
    event ProposalCreated(
        uint256 indexed proposalId,
        address indexed proposer,
        VotingModel votingModel,
        uint256 startBlock,
        uint256 endBlock,
        string description
    );
    event VoteCast(
        uint256 indexed proposalId,
        address indexed voter,
        uint8 support,  // 0=against, 1=for, 2=abstain
        uint256 weight
    );
    event ProposalExecuted(uint256 indexed proposalId);
    event ProposalCancelled(uint256 indexed proposalId);
    event TreasuryWithdrawal(address indexed to, uint256 amount, uint256 fee);
    event VotingPowerDelegated(address indexed from, uint256 amount);

    // ---------------------------------------------------------------
    // Constructor
    // ---------------------------------------------------------------
    constructor(address _platformFeeRecipient) Ownable(msg.sender) {
        require(_platformFeeRecipient != address(0), "Zero fee recipient");
        platformFeeRecipient = _platformFeeRecipient;
    }

    // ---------------------------------------------------------------
    // Governance participation (simplified token-less model)
    // ---------------------------------------------------------------

    /**
     * @notice Deposit ETH to gain voting power (1 wei = 1 vote unit).
     */
    function depositVotingPower() external payable {
        require(msg.value > 0, "Must deposit > 0");
        votingPower[msg.sender] += msg.value;
        totalVotingPower += msg.value;
        emit VotingPowerDelegated(msg.sender, msg.value);
    }

    // ---------------------------------------------------------------
    // Proposal lifecycle
    // ---------------------------------------------------------------

    function propose(
        address[] calldata targets,
        uint256[] calldata values,
        bytes[] calldata calldatas,
        string calldata description,
        VotingModel votingModel
    ) external returns (uint256 proposalId) {
        require(votingPower[msg.sender] > 0, "No voting power");
        require(targets.length == values.length && values.length == calldatas.length, "Length mismatch");
        require(targets.length > 0, "Empty proposal");

        proposalId = _nextProposalId++;
        Proposal storage p = proposals[proposalId];
        p.id = proposalId;
        p.proposer = msg.sender;
        p.description = description;
        p.votingModel = votingModel;
        p.startBlock = block.number + VOTING_DELAY;
        p.endBlock = block.number + VOTING_DELAY + VOTING_PERIOD;
        p.targets = targets;
        p.values = values;
        p.calldatas = calldatas;

        emit ProposalCreated(proposalId, msg.sender, votingModel, p.startBlock, p.endBlock, description);
    }

    function castVote(uint256 proposalId, uint8 support) external {
        Proposal storage p = proposals[proposalId];
        require(state(proposalId) == ProposalState.Active, "Not active");
        require(!hasVoted[proposalId][msg.sender], "Already voted");
        require(support <= 2, "Invalid support value");

        uint256 weight = votingPower[msg.sender];
        require(weight > 0, "No voting power");

        // Apply quadratic voting if selected
        uint256 effectiveWeight = weight;
        if (p.votingModel == VotingModel.QuadraticVoting) {
            effectiveWeight = _sqrt(weight);
        }

        hasVoted[proposalId][msg.sender] = true;

        if (support == 0) {
            p.againstVotes += effectiveWeight;
        } else if (support == 1) {
            p.forVotes += effectiveWeight;
        } else {
            p.abstainVotes += effectiveWeight;
        }

        emit VoteCast(proposalId, msg.sender, support, effectiveWeight);
    }

    function execute(uint256 proposalId) external nonReentrant {
        require(state(proposalId) == ProposalState.Succeeded, "Not succeeded");

        Proposal storage p = proposals[proposalId];
        p.executed = true;

        for (uint256 i = 0; i < p.targets.length; i++) {
            (bool success, ) = p.targets[i].call{value: p.values[i]}(p.calldatas[i]);
            require(success, "Execution failed");
        }

        emit ProposalExecuted(proposalId);
    }

    function cancel(uint256 proposalId) external {
        Proposal storage p = proposals[proposalId];
        require(msg.sender == p.proposer || msg.sender == owner(), "Not authorized");
        require(!p.executed, "Already executed");

        p.cancelled = true;
        emit ProposalCancelled(proposalId);
    }

    // ---------------------------------------------------------------
    // Treasury with tiered fees
    // ---------------------------------------------------------------

    /**
     * @notice Withdraw ETH from the DAO treasury. Tiered fees apply:
     *         <10K gwei = 1%, 10K-100K gwei = 0.5%, >100K gwei = 0.25%.
     */
    function treasuryWithdraw(address to, uint256 amount) external onlyOwner nonReentrant {
        require(to != address(0), "Zero address");
        require(address(this).balance >= amount, "Insufficient treasury");

        uint256 feeBps = _tieredFeeBps(amount);
        uint256 fee = (amount * feeBps) / BPS_DENOMINATOR;
        uint256 netAmount = amount - fee;

        if (fee > 0) {
            (bool feeSent, ) = platformFeeRecipient.call{value: fee}("");
            require(feeSent, "Fee transfer failed");
        }

        (bool sent, ) = to.call{value: netAmount}("");
        require(sent, "Withdrawal failed");

        emit TreasuryWithdrawal(to, netAmount, fee);
    }

    // ---------------------------------------------------------------
    // View helpers
    // ---------------------------------------------------------------

    function state(uint256 proposalId) public view returns (ProposalState) {
        Proposal storage p = proposals[proposalId];
        if (p.cancelled) return ProposalState.Cancelled;
        if (p.executed) return ProposalState.Executed;
        if (block.number < p.startBlock) return ProposalState.Pending;
        if (block.number <= p.endBlock) return ProposalState.Active;

        // Voting ended — check quorum and majority
        uint256 totalCast = p.forVotes + p.againstVotes + p.abstainVotes;
        uint256 quorum = (totalVotingPower * QUORUM_BPS) / BPS_DENOMINATOR;

        if (totalCast < quorum) return ProposalState.Defeated;

        bool passed;
        if (p.votingModel == VotingModel.SuperMajority) {
            // 66.7%
            passed = p.forVotes * 3 > (p.forVotes + p.againstVotes) * 2;
        } else {
            // SimpleMajority or Quadratic — simple majority of for vs against
            passed = p.forVotes > p.againstVotes;
        }

        return passed ? ProposalState.Succeeded : ProposalState.Defeated;
    }

    // ---------------------------------------------------------------
    // Internal
    // ---------------------------------------------------------------

    function _tieredFeeBps(uint256 amount) internal pure returns (uint256) {
        if (amount < 10_000 gwei) {
            return 100; // 1%
        } else if (amount <= 100_000 gwei) {
            return 50;  // 0.5%
        } else {
            return 25;  // 0.25%
        }
    }

    function _sqrt(uint256 x) internal pure returns (uint256 y) {
        if (x == 0) return 0;
        uint256 z = (x + 1) / 2;
        y = x;
        while (z < y) {
            y = z;
            z = (x / z + z) / 2;
        }
    }

    receive() external payable {}
}
