// SPDX-License-Identifier: MIT
pragma solidity ^0.8.20;

/**
 * @title 0pnMatrx Identity
 * @notice On-chain identity management with attestation support.
 *         Users own their identity. No central authority can revoke it.
 *
 *         This contract works with EAS (Ethereum Attestation Service) for
 *         verifiable credential issuance and verification.
 */
contract Identity {
    struct UserIdentity {
        address owner;
        bytes32 identityHash;
        uint256 createdAt;
        uint256 updatedAt;
        bool active;
    }

    mapping(address => UserIdentity) public identities;
    mapping(bytes32 => address) public hashToOwner;

    address public admin;

    event IdentityCreated(address indexed owner, bytes32 identityHash, uint256 timestamp);
    event IdentityUpdated(address indexed owner, bytes32 newHash, uint256 timestamp);
    event IdentityDeactivated(address indexed owner, uint256 timestamp);

    modifier onlyAdmin() {
        require(msg.sender == admin, "Only admin");
        _;
    }

    modifier onlyIdentityOwner() {
        require(identities[msg.sender].active, "No active identity");
        _;
    }

    constructor() {
        admin = CONFIGURE_BEFORE_DEPLOY;
    }

    address constant CONFIGURE_BEFORE_DEPLOY = address(0);

    function createIdentity(bytes32 _identityHash) external {
        require(!identities[msg.sender].active, "Identity already exists");
        require(hashToOwner[_identityHash] == address(0), "Hash already registered");

        identities[msg.sender] = UserIdentity({
            owner: msg.sender,
            identityHash: _identityHash,
            createdAt: block.timestamp,
            updatedAt: block.timestamp,
            active: true
        });

        hashToOwner[_identityHash] = msg.sender;

        emit IdentityCreated(msg.sender, _identityHash, block.timestamp);
    }

    function updateIdentity(bytes32 _newHash) external onlyIdentityOwner {
        require(hashToOwner[_newHash] == address(0), "Hash already registered");

        bytes32 oldHash = identities[msg.sender].identityHash;
        delete hashToOwner[oldHash];

        identities[msg.sender].identityHash = _newHash;
        identities[msg.sender].updatedAt = block.timestamp;
        hashToOwner[_newHash] = msg.sender;

        emit IdentityUpdated(msg.sender, _newHash, block.timestamp);
    }

    function deactivateIdentity() external onlyIdentityOwner {
        bytes32 hash = identities[msg.sender].identityHash;
        delete hashToOwner[hash];
        identities[msg.sender].active = false;

        emit IdentityDeactivated(msg.sender, block.timestamp);
    }

    function verifyIdentity(address _user) external view returns (bool, bytes32) {
        UserIdentity memory id = identities[_user];
        return (id.active, id.identityHash);
    }

    function transferAdmin(address _newAdmin) external onlyAdmin {
        require(_newAdmin != address(0), "Invalid address");
        admin = _newAdmin;
    }
}
