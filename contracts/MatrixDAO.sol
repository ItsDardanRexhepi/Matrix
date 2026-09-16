// SPDX-License-Identifier: MIT
pragma solidity ^0.8.20;

import "@openzeppelin/contracts/access/Ownable.sol";
import "@openzeppelin/contracts/utils/ReentrancyGuard.sol";

/**
 * @title MatrixDAO
 * @notice DAO Governor with 3 voting models, quorum, treasury.
 *         Tiered treasury fees: <10K = 1%, 10K-100K = 0.5%, >100K = 0.25%.
 */
contract MatrixDAO is ReentrancyGuard, Ownable {

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
        Cancelled,
        Queued      // passed, waiting out the timelock (appended: ordinals above are stable)
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
    /// @notice Quorum, in bps of the voting power at the proposal's snapshot.
    ///         4% let a proposer holding 1/24 of the power move the whole
    ///         treasury unopposed (audit entry B3-DAO-4PCT-DRAIN); 20% cannot
    ///         be met by that proposer alone.
    uint256 public constant QUORUM_BPS = 2_000;          // 20% of snapshot voting power
    /// @notice A passed proposal waits this long between queue and execute.
    uint256 public constant TIMELOCK_DELAY = 2 days;
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

    /// @dev Voting power is snapshotted per block so that power bought after a
    ///      proposal exists cannot vote on it (B3-DAO-4PCT-DRAIN: castVote read
    ///      live balances). Checkpoints in the ERC20Votes shape.
    struct Checkpoint {
        uint64 fromBlock;
        uint192 votes;
    }
    mapping(address => Checkpoint[]) private _checkpoints;
    Checkpoint[] private _totalCheckpoints;
    /// @notice The block whose voting power counts for a proposal (the block
    ///         before it was created).
    mapping(uint256 => uint256) public snapshotBlockOf;
    /// @notice When a queued proposal may execute; 0 = not queued.
    mapping(uint256 => uint256) public etaOf;
    /// @notice The voting model every proposal uses — set by governance
    ///         (the owner), never chosen by the proposer.
    VotingModel public defaultVotingModel;

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
    event VotingPowerWithdrawn(address indexed to, uint256 amount);
    event ProposalQueued(uint256 indexed proposalId, uint256 eta);
    event VotingModelSet(VotingModel model);

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
        _writeCheckpoint(_checkpoints[msg.sender], votingPower[msg.sender]);
        _writeCheckpoint(_totalCheckpoints, totalVotingPower);
        emit VotingPowerDelegated(msg.sender, msg.value);
    }

    /**
     * @notice Withdraw deposited ETH. Voting power was bought with ETH that could
     *         never leave (audit entry B3-DAO-OWNER-SWEEP: no exit even from an
     *         honest owner). Snapshots make this safe at any time: votes already
     *         cast on a live proposal were counted at its snapshot.
     */
    function withdrawVotingPower(uint256 amount) external nonReentrant {
        require(amount > 0, "Must withdraw > 0");
        require(votingPower[msg.sender] >= amount, "Insufficient voting power");
        votingPower[msg.sender] -= amount;
        totalVotingPower -= amount;
        _writeCheckpoint(_checkpoints[msg.sender], votingPower[msg.sender]);
        _writeCheckpoint(_totalCheckpoints, totalVotingPower);
        (bool sent, ) = msg.sender.call{value: amount}("");
        require(sent, "Withdrawal failed");
        emit VotingPowerWithdrawn(msg.sender, amount);
    }

    /// @notice Voting power of `account` as of `blockNumber` (must be past).
    function getPastVotes(address account, uint256 blockNumber) public view returns (uint256) {
        require(blockNumber < block.number, "Block not yet mined");
        return _lookup(_checkpoints[account], blockNumber);
    }

    /// @notice Total voting power as of `blockNumber` (must be past).
    function getPastTotalSupply(uint256 blockNumber) public view returns (uint256) {
        require(blockNumber < block.number, "Block not yet mined");
        return _lookup(_totalCheckpoints, blockNumber);
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
        // The model is governance-set; a proposer picking SimpleMajority for a
        // treasury move was the audit's B3-DAO-4PCT-DRAIN. The parameter stays
        // for ABI compatibility and must name the configured model.
        require(votingModel == defaultVotingModel, "Voting model is governance-set");

        proposalId = _nextProposalId++;
        // Power as of the block BEFORE the proposal: nothing bought in reaction
        // to it can vote on it.
        snapshotBlockOf[proposalId] = block.number - 1;
        Proposal storage p = proposals[proposalId];
        p.id = proposalId;
        p.proposer = msg.sender;
        p.description = description;
        p.votingModel = votingModel;
        p.startBlock = block.number + VOTING_DELAY;
        p.endBlock = block.number + VOTING_DELAY + VOTING_PERIOD;
        p.targets = targets;
        p.values = values;
        // Element-wise copy: the legacy code generator (via_ir=false, foundry.toml)
        // cannot copy a nested calldata dynamic array (bytes[]) straight into
        // storage — it raises UnimplementedFeatureError. targets/values are
        // value-type arrays and copy fine; only calldatas needs the loop (P0-3).
        for (uint256 i = 0; i < calldatas.length; i++) {
            p.calldatas.push(calldatas[i]);
        }

        emit ProposalCreated(proposalId, msg.sender, votingModel, p.startBlock, p.endBlock, description);
    }

    function castVote(uint256 proposalId, uint8 support) external {
        Proposal storage p = proposals[proposalId];
        require(state(proposalId) == ProposalState.Active, "Not active");
        require(!hasVoted[proposalId][msg.sender], "Already voted");
        require(support <= 2, "Invalid support value");

        uint256 weight = getPastVotes(msg.sender, snapshotBlockOf[proposalId]);
        require(weight > 0, "No voting power at snapshot");

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

    /// @notice Start the timelock on a passed proposal. Anyone may queue.
    function queue(uint256 proposalId) external {
        require(state(proposalId) == ProposalState.Succeeded, "Not succeeded");
        uint256 eta = block.timestamp + TIMELOCK_DELAY;
        etaOf[proposalId] = eta;
        emit ProposalQueued(proposalId, eta);
    }

    function execute(uint256 proposalId) external nonReentrant {
        require(state(proposalId) == ProposalState.Queued, "Not queued");
        require(block.timestamp >= etaOf[proposalId], "Timelock not elapsed");

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
     *         Reachable ONLY through a passed, queued and timelocked proposal
     *         whose target is this contract — the owner could sweep every
     *         depositor's ETH in one call (audit entry B3-DAO-OWNER-SWEEP).
     */
    function treasuryWithdraw(address to, uint256 amount) external {
        // Not nonReentrant: it is reachable only from execute(), which holds
        // the guard already; a second guard here would refuse its own caller.
        require(msg.sender == address(this), "Only via a passed proposal");
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

        // Voting ended — check quorum and majority against the snapshot
        uint256 totalCast = p.forVotes + p.againstVotes + p.abstainVotes;
        uint256 quorum = (_lookup(_totalCheckpoints, snapshotBlockOf[proposalId]) * QUORUM_BPS) / BPS_DENOMINATOR;

        if (totalCast < quorum) return ProposalState.Defeated;

        bool passed;
        if (p.votingModel == VotingModel.SuperMajority) {
            // 66.7%
            passed = p.forVotes * 3 > (p.forVotes + p.againstVotes) * 2;
        } else {
            // SimpleMajority or Quadratic — simple majority of for vs against
            passed = p.forVotes > p.againstVotes;
        }

        if (!passed) return ProposalState.Defeated;
        return etaOf[proposalId] != 0 ? ProposalState.Queued : ProposalState.Succeeded;
    }

    /// @notice Governance sets the voting model every proposal must use.
    function setVotingModel(VotingModel model) external onlyOwner {
        defaultVotingModel = model;
        emit VotingModelSet(model);
    }

    // ---------------------------------------------------------------
    // Checkpoints
    // ---------------------------------------------------------------

    function _writeCheckpoint(Checkpoint[] storage ckpts, uint256 newValue) internal {
        uint256 n = ckpts.length;
        if (n > 0 && ckpts[n - 1].fromBlock == uint64(block.number)) {
            ckpts[n - 1].votes = uint192(newValue);
        } else {
            ckpts.push(Checkpoint({fromBlock: uint64(block.number), votes: uint192(newValue)}));
        }
    }

    function _lookup(Checkpoint[] storage ckpts, uint256 blockNumber) internal view returns (uint256) {
        uint256 high = ckpts.length;
        uint256 low = 0;
        while (low < high) {
            uint256 mid = (low + high) / 2;
            if (ckpts[mid].fromBlock > blockNumber) {
                high = mid;
            } else {
                low = mid + 1;
            }
        }
        return high == 0 ? 0 : ckpts[high - 1].votes;
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
