// SPDX-License-Identifier: MIT
pragma solidity ^0.8.20;

/**
 * @title 0pnMatrx Governance
 * @notice On-chain governance for DAOs and community decisions.
 *         Create proposals, vote, and execute — all through conversation.
 *
 *         Features:
 *         - Proposal creation with description and options
 *         - Time-bounded voting periods
 *         - Quorum requirements
 *         - Execution of passed proposals
 */
contract Governance {
    enum ProposalState { Pending, Active, Passed, Failed, Executed }

    struct Proposal {
        uint256 id;
        address proposer;
        string description;
        uint256 votesFor;
        uint256 votesAgainst;
        uint256 startTime;
        uint256 endTime;
        uint256 quorum;
        bool executed;
    }

    Proposal[] public proposals;
    mapping(uint256 => mapping(address => bool)) public hasVoted;
    mapping(address => bool) public members;
    uint256 public memberCount;

    address public admin;
    uint256 public defaultVotingPeriod;
    uint256 public defaultQuorum;

    event ProposalCreated(uint256 indexed id, address indexed proposer, string description);
    event Voted(uint256 indexed id, address indexed voter, bool support);
    event ProposalExecuted(uint256 indexed id);
    event MemberAdded(address indexed member);
    event MemberRemoved(address indexed member);

    modifier onlyAdmin() {
        require(msg.sender == admin, "Only admin");
        _;
    }

    modifier onlyMember() {
        require(members[msg.sender], "Not a member");
        _;
    }

    constructor(uint256 _votingPeriod, uint256 _quorum) {
        admin = CONFIGURE_BEFORE_DEPLOY;
        defaultVotingPeriod = _votingPeriod;
        defaultQuorum = _quorum;
    }

    address constant CONFIGURE_BEFORE_DEPLOY = address(0);

    function addMember(address _member) external onlyAdmin {
        require(!members[_member], "Already a member");
        members[_member] = true;
        memberCount++;
        emit MemberAdded(_member);
    }

    function removeMember(address _member) external onlyAdmin {
        require(members[_member], "Not a member");
        members[_member] = false;
        memberCount--;
        emit MemberRemoved(_member);
    }

    function createProposal(string calldata _description) external onlyMember returns (uint256) {
        uint256 id = proposals.length;

        proposals.push(Proposal({
            id: id,
            proposer: msg.sender,
            description: _description,
            votesFor: 0,
            votesAgainst: 0,
            startTime: block.timestamp,
            endTime: block.timestamp + defaultVotingPeriod,
            quorum: defaultQuorum,
            executed: false
        }));

        emit ProposalCreated(id, msg.sender, _description);
        return id;
    }

    function vote(uint256 _proposalId, bool _support) external onlyMember {
        require(_proposalId < proposals.length, "Invalid proposal");
        Proposal storage p = proposals[_proposalId];
        require(block.timestamp >= p.startTime, "Not started");
        require(block.timestamp <= p.endTime, "Voting ended");
        require(!hasVoted[_proposalId][msg.sender], "Already voted");

        hasVoted[_proposalId][msg.sender] = true;

        if (_support) {
            p.votesFor++;
        } else {
            p.votesAgainst++;
        }

        emit Voted(_proposalId, msg.sender, _support);
    }

    function getState(uint256 _proposalId) public view returns (ProposalState) {
        require(_proposalId < proposals.length, "Invalid proposal");
        Proposal memory p = proposals[_proposalId];

        if (p.executed) return ProposalState.Executed;
        if (block.timestamp < p.startTime) return ProposalState.Pending;
        if (block.timestamp <= p.endTime) return ProposalState.Active;

        uint256 totalVotes = p.votesFor + p.votesAgainst;
        if (totalVotes < p.quorum) return ProposalState.Failed;
        if (p.votesFor > p.votesAgainst) return ProposalState.Passed;
        return ProposalState.Failed;
    }

    function executeProposal(uint256 _proposalId) external onlyAdmin {
        require(getState(_proposalId) == ProposalState.Passed, "Not passed");
        proposals[_proposalId].executed = true;
        emit ProposalExecuted(_proposalId);
    }

    function proposalCount() external view returns (uint256) {
        return proposals.length;
    }
}
