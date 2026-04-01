// SPDX-License-Identifier: MIT
pragma solidity ^0.8.20;

/**
 * @title 0pnMatrx Insurance
 * @notice Decentralized insurance pools for on-chain protection.
 *         Users can create and join insurance pools, file claims,
 *         and receive payouts — all through conversation with Trinity.
 *
 *         Features:
 *         - Pool creation with configurable terms
 *         - Premium collection
 *         - Claim filing and assessment
 *         - Payout distribution
 */
contract Insurance {
    enum ClaimStatus { Filed, Approved, Denied, Paid }

    struct Pool {
        uint256 id;
        string name;
        address creator;
        uint256 premiumAmount;
        uint256 maxCoverage;
        uint256 totalFunds;
        uint256 memberCount;
        bool active;
    }

    struct Claim {
        uint256 id;
        uint256 poolId;
        address claimant;
        uint256 amount;
        string reason;
        ClaimStatus status;
        uint256 filedAt;
    }

    Pool[] public pools;
    Claim[] public claims;

    mapping(uint256 => mapping(address => bool)) public poolMembers;
    mapping(uint256 => mapping(address => uint256)) public premiumsPaid;

    address public admin;

    event PoolCreated(uint256 indexed id, string name, address indexed creator);
    event MemberJoined(uint256 indexed poolId, address indexed member);
    event ClaimFiled(uint256 indexed claimId, uint256 indexed poolId, address indexed claimant);
    event ClaimResolved(uint256 indexed claimId, ClaimStatus status);

    modifier onlyAdmin() {
        require(msg.sender == admin, "Only admin");
        _;
    }

    constructor() {
        admin = CONFIGURE_BEFORE_DEPLOY;
    }

    address constant CONFIGURE_BEFORE_DEPLOY = address(0);

    function createPool(
        string calldata _name,
        uint256 _premiumAmount,
        uint256 _maxCoverage
    ) external returns (uint256) {
        uint256 id = pools.length;

        pools.push(Pool({
            id: id,
            name: _name,
            creator: msg.sender,
            premiumAmount: _premiumAmount,
            maxCoverage: _maxCoverage,
            totalFunds: 0,
            memberCount: 0,
            active: true
        }));

        emit PoolCreated(id, _name, msg.sender);
        return id;
    }

    function joinPool(uint256 _poolId) external payable {
        require(_poolId < pools.length, "Invalid pool");
        Pool storage pool = pools[_poolId];
        require(pool.active, "Pool inactive");
        require(!poolMembers[_poolId][msg.sender], "Already a member");
        require(msg.value >= pool.premiumAmount, "Insufficient premium");

        poolMembers[_poolId][msg.sender] = true;
        premiumsPaid[_poolId][msg.sender] = msg.value;
        pool.totalFunds += msg.value;
        pool.memberCount++;

        emit MemberJoined(_poolId, msg.sender);
    }

    function fileClaim(
        uint256 _poolId,
        uint256 _amount,
        string calldata _reason
    ) external returns (uint256) {
        require(_poolId < pools.length, "Invalid pool");
        require(poolMembers[_poolId][msg.sender], "Not a member");
        require(_amount <= pools[_poolId].maxCoverage, "Exceeds max coverage");

        uint256 claimId = claims.length;

        claims.push(Claim({
            id: claimId,
            poolId: _poolId,
            claimant: msg.sender,
            amount: _amount,
            reason: _reason,
            status: ClaimStatus.Filed,
            filedAt: block.timestamp
        }));

        emit ClaimFiled(claimId, _poolId, msg.sender);
        return claimId;
    }

    function resolveClaim(uint256 _claimId, bool _approved) external onlyAdmin {
        require(_claimId < claims.length, "Invalid claim");
        Claim storage claim = claims[_claimId];
        require(claim.status == ClaimStatus.Filed, "Already resolved");

        if (_approved) {
            Pool storage pool = pools[claim.poolId];
            require(pool.totalFunds >= claim.amount, "Insufficient funds");

            claim.status = ClaimStatus.Approved;
            pool.totalFunds -= claim.amount;

            (bool sent, ) = payable(claim.claimant).call{value: claim.amount}("");
            require(sent, "Payout failed");

            claim.status = ClaimStatus.Paid;
        } else {
            claim.status = ClaimStatus.Denied;
        }

        emit ClaimResolved(_claimId, claim.status);
    }

    function poolCount() external view returns (uint256) {
        return pools.length;
    }

    function claimCount() external view returns (uint256) {
        return claims.length;
    }
}
