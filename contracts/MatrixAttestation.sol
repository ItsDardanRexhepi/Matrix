// SPDX-License-Identifier: MIT
pragma solidity ^0.8.20;

/**
 * @title MatrixAttestation
 * @notice On-chain attestation registry for 0pnMatrx agent actions.
 *         Every blockchain action is recorded here for transparency
 *         and verifiability. Gas covered by the platform.
 */
contract MatrixAttestation {
    struct Attestation {
        address attester;
        string agent;
        string action;
        string details;
        uint256 timestamp;
        bool revoked;
    }

    address public owner;
    mapping(address => bool) public authorizedAttesters;

    Attestation[] public attestations;
    mapping(bytes32 => uint256[]) public actionIndex;
    mapping(address => uint256[]) public attesterIndex;

    uint256 public totalAttestations;

    event AttestationCreated(uint256 indexed id, address indexed attester, string agent, string action);
    event AttestationRevoked(uint256 indexed id);

    modifier onlyOwner() {
        require(msg.sender == owner, "Only owner");
        _;
    }

    modifier onlyAuthorized() {
        require(msg.sender == owner || authorizedAttesters[msg.sender], "Not authorized");
        _;
    }

    constructor() {
        owner = msg.sender;
        authorizedAttesters[msg.sender] = true;
    }

    /// @notice Create a new attestation
    function attest(
        string calldata agent,
        string calldata action,
        string calldata details
    ) external onlyAuthorized returns (uint256) {
        uint256 id = attestations.length;
        attestations.push(Attestation({
            attester: msg.sender,
            agent: agent,
            action: action,
            details: details,
            timestamp: block.timestamp,
            revoked: false
        }));

        bytes32 actionHash = keccak256(abi.encodePacked(action));
        actionIndex[actionHash].push(id);
        attesterIndex[msg.sender].push(id);
        totalAttestations++;

        emit AttestationCreated(id, msg.sender, agent, action);
        return id;
    }

    /// @notice Revoke an attestation
    function revoke(uint256 id) external onlyAuthorized {
        require(id < attestations.length, "Invalid ID");
        require(!attestations[id].revoked, "Already revoked");
        attestations[id].revoked = true;
        emit AttestationRevoked(id);
    }

    /// @notice Get attestation by ID
    function getAttestation(uint256 id) external view returns (
        address attester, string memory agent, string memory action,
        string memory details, uint256 timestamp, bool revoked
    ) {
        require(id < attestations.length, "Invalid ID");
        Attestation storage a = attestations[id];
        return (a.attester, a.agent, a.action, a.details, a.timestamp, a.revoked);
    }

    /// @notice Get attestation count by action
    function getActionCount(string calldata action) external view returns (uint256) {
        bytes32 actionHash = keccak256(abi.encodePacked(action));
        return actionIndex[actionHash].length;
    }

    /// @notice Authorize an attester
    function authorizeAttester(address attester) external onlyOwner {
        authorizedAttesters[attester] = true;
    }

    /// @notice Revoke attester authorization
    function revokeAttester(address attester) external onlyOwner {
        authorizedAttesters[attester] = false;
    }

    /// @notice Transfer ownership
    function transferOwnership(address newOwner) external onlyOwner {
        require(newOwner != address(0), "Invalid address");
        owner = newOwner;
    }
}
