// SPDX-License-Identifier: MIT
pragma solidity ^0.8.20;

/**
 * @title 0pnMatrx Ownership Grant
 * @notice Grants verifiable ownership stakes in 0pnMatrx and MTRX.
 *         Ownership is permanent and recorded on-chain.
 *
 *         Each grant includes:
 *         - Owner address and name
 *         - Percentage stake (in basis points for precision)
 *         - Effective date
 *         - Irrevocability guarantee
 */
contract Ownership {
    struct OwnershipGrant {
        address grantee;
        string name;
        uint256 basisPoints; // 100 = 1%
        uint256 effectiveDate;
        bool active;
    }

    OwnershipGrant[] public grants;
    mapping(address => uint256) public grantIndex;
    mapping(address => bool) public hasGrant;

    address public grantor;
    uint256 public totalBasisPoints;
    string public platformName;

    event OwnershipGranted(
        address indexed grantee,
        string name,
        uint256 basisPoints,
        uint256 effectiveDate
    );

    modifier onlyGrantor() {
        require(msg.sender == grantor, "Only grantor");
        _;
    }

    constructor(string memory _platformName) {
        grantor = CONFIGURE_BEFORE_DEPLOY;
        platformName = _platformName;
    }

    address constant CONFIGURE_BEFORE_DEPLOY = address(0);

    function grantOwnership(
        address _grantee,
        string calldata _name,
        uint256 _basisPoints
    ) external onlyGrantor {
        require(!hasGrant[_grantee], "Already has grant");
        require(_basisPoints > 0, "Must be positive");
        require(totalBasisPoints + _basisPoints <= 10000, "Exceeds 100%");

        uint256 index = grants.length;
        grants.push(OwnershipGrant({
            grantee: _grantee,
            name: _name,
            basisPoints: _basisPoints,
            effectiveDate: block.timestamp,
            active: true
        }));

        grantIndex[_grantee] = index;
        hasGrant[_grantee] = true;
        totalBasisPoints += _basisPoints;

        emit OwnershipGranted(_grantee, _name, _basisPoints, block.timestamp);
    }

    function getGrant(address _grantee) external view returns (
        string memory name,
        uint256 basisPoints,
        uint256 effectiveDate,
        bool active
    ) {
        require(hasGrant[_grantee], "No grant found");
        OwnershipGrant memory g = grants[grantIndex[_grantee]];
        return (g.name, g.basisPoints, g.effectiveDate, g.active);
    }

    function totalGrants() external view returns (uint256) {
        return grants.length;
    }

    function ownershipPercentage(address _grantee) external view returns (uint256) {
        if (!hasGrant[_grantee]) return 0;
        return grants[grantIndex[_grantee]].basisPoints;
    }
}
