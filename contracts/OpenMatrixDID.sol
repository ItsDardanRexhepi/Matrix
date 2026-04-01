// SPDX-License-Identifier: MIT
pragma solidity ^0.8.20;

import "@openzeppelin/contracts/access/Ownable.sol";

/**
 * @title OpenMatrixDID
 * @notice W3C DID Method: did:openmatrix:base:<address>
 *         Create, resolve, update, and deactivate DIDs on-chain.
 *         Each Ethereum address can control exactly one DID document.
 */
contract OpenMatrixDID is Ownable {

    // ---------------------------------------------------------------
    // Structs
    // ---------------------------------------------------------------
    struct DIDDocument {
        address controller;          // address that controls this DID
        string  documentURI;         // off-chain DID Document JSON (IPFS / HTTPS)
        bytes32 documentHash;        // keccak256 of the document for integrity
        uint256 created;
        uint256 updated;
        bool    active;
        // Service endpoints stored on-chain for quick resolution
        string[] serviceTypes;
        string[] serviceEndpoints;
        // Verification methods
        bytes[] verificationMethods; // encoded public keys
    }

    // ---------------------------------------------------------------
    // State
    // ---------------------------------------------------------------
    address public platformFeeRecipient;

    // did:openmatrix:base:<address> => DIDDocument
    mapping(address => DIDDocument) private _dids;

    uint256 public totalDIDs;
    uint256 public activeDIDs;

    // ---------------------------------------------------------------
    // Events
    // ---------------------------------------------------------------
    event DIDCreated(address indexed subject, string documentURI, bytes32 documentHash);
    event DIDUpdated(address indexed subject, string documentURI, bytes32 documentHash);
    event DIDDeactivated(address indexed subject);
    event DIDReactivated(address indexed subject);
    event ServiceAdded(address indexed subject, string serviceType, string endpoint);
    event ServiceRemoved(address indexed subject, uint256 index);
    event VerificationMethodAdded(address indexed subject, bytes publicKey);
    event ControllerChanged(address indexed subject, address oldController, address newController);

    // ---------------------------------------------------------------
    // Constructor
    // ---------------------------------------------------------------
    constructor(address _platformFeeRecipient) Ownable(msg.sender) {
        require(_platformFeeRecipient != address(0), "Zero fee recipient");
        platformFeeRecipient = _platformFeeRecipient;
    }

    // ---------------------------------------------------------------
    // Modifiers
    // ---------------------------------------------------------------
    modifier onlyController(address subject) {
        require(
            _dids[subject].controller == msg.sender,
            "Not DID controller"
        );
        _;
    }

    modifier didExists(address subject) {
        require(_dids[subject].created > 0, "DID does not exist");
        _;
    }

    modifier didActive(address subject) {
        require(_dids[subject].active, "DID is deactivated");
        _;
    }

    // ---------------------------------------------------------------
    // Create
    // ---------------------------------------------------------------

    /**
     * @notice Create a DID for msg.sender.
     *         Resulting DID: did:openmatrix:base:<msg.sender>
     * @param documentURI  URI of the off-chain DID Document JSON.
     * @param documentHash keccak256 hash of the document content.
     */
    function createDID(string calldata documentURI, bytes32 documentHash) external {
        require(_dids[msg.sender].created == 0, "DID already exists");
        require(bytes(documentURI).length > 0, "Empty document URI");

        DIDDocument storage doc = _dids[msg.sender];
        doc.controller = msg.sender;
        doc.documentURI = documentURI;
        doc.documentHash = documentHash;
        doc.created = block.timestamp;
        doc.updated = block.timestamp;
        doc.active = true;

        totalDIDs++;
        activeDIDs++;

        emit DIDCreated(msg.sender, documentURI, documentHash);
    }

    // ---------------------------------------------------------------
    // Resolve
    // ---------------------------------------------------------------

    /**
     * @notice Resolve a DID to its on-chain document metadata.
     * @param subject The Ethereum address of the DID subject.
     */
    function resolve(address subject)
        external
        view
        didExists(subject)
        returns (
            address controller,
            string memory documentURI,
            bytes32 documentHash,
            uint256 created,
            uint256 updated,
            bool active,
            string[] memory serviceTypes,
            string[] memory serviceEndpoints,
            bytes[] memory verificationMethods
        )
    {
        DIDDocument storage doc = _dids[subject];
        return (
            doc.controller,
            doc.documentURI,
            doc.documentHash,
            doc.created,
            doc.updated,
            doc.active,
            doc.serviceTypes,
            doc.serviceEndpoints,
            doc.verificationMethods
        );
    }

    /**
     * @notice Build the full DID string for an address.
     */
    function didFor(address subject) external pure returns (string memory) {
        return string(
            abi.encodePacked(
                "did:openmatrix:base:",
                _toHexString(subject)
            )
        );
    }

    // ---------------------------------------------------------------
    // Update
    // ---------------------------------------------------------------

    /**
     * @notice Update the DID Document URI and hash.
     */
    function updateDocument(
        address subject,
        string calldata newDocumentURI,
        bytes32 newDocumentHash
    ) external onlyController(subject) didActive(subject) {
        require(bytes(newDocumentURI).length > 0, "Empty document URI");

        DIDDocument storage doc = _dids[subject];
        doc.documentURI = newDocumentURI;
        doc.documentHash = newDocumentHash;
        doc.updated = block.timestamp;

        emit DIDUpdated(subject, newDocumentURI, newDocumentHash);
    }

    /**
     * @notice Add a service endpoint.
     */
    function addService(
        address subject,
        string calldata serviceType,
        string calldata endpoint
    ) external onlyController(subject) didActive(subject) {
        DIDDocument storage doc = _dids[subject];
        doc.serviceTypes.push(serviceType);
        doc.serviceEndpoints.push(endpoint);
        doc.updated = block.timestamp;

        emit ServiceAdded(subject, serviceType, endpoint);
    }

    /**
     * @notice Remove a service endpoint by index.
     */
    function removeService(address subject, uint256 index)
        external
        onlyController(subject)
        didActive(subject)
    {
        DIDDocument storage doc = _dids[subject];
        require(index < doc.serviceTypes.length, "Index out of bounds");

        // Swap-and-pop
        uint256 last = doc.serviceTypes.length - 1;
        if (index != last) {
            doc.serviceTypes[index] = doc.serviceTypes[last];
            doc.serviceEndpoints[index] = doc.serviceEndpoints[last];
        }
        doc.serviceTypes.pop();
        doc.serviceEndpoints.pop();
        doc.updated = block.timestamp;

        emit ServiceRemoved(subject, index);
    }

    /**
     * @notice Add a verification method (encoded public key).
     */
    function addVerificationMethod(address subject, bytes calldata publicKey)
        external
        onlyController(subject)
        didActive(subject)
    {
        DIDDocument storage doc = _dids[subject];
        doc.verificationMethods.push(publicKey);
        doc.updated = block.timestamp;

        emit VerificationMethodAdded(subject, publicKey);
    }

    /**
     * @notice Transfer control of a DID to a new controller.
     */
    function changeController(address subject, address newController)
        external
        onlyController(subject)
        didActive(subject)
    {
        require(newController != address(0), "Zero address");
        DIDDocument storage doc = _dids[subject];
        address old = doc.controller;
        doc.controller = newController;
        doc.updated = block.timestamp;

        emit ControllerChanged(subject, old, newController);
    }

    // ---------------------------------------------------------------
    // Deactivate / Reactivate
    // ---------------------------------------------------------------

    /**
     * @notice Deactivate a DID (soft delete — data preserved).
     */
    function deactivate(address subject)
        external
        onlyController(subject)
        didActive(subject)
    {
        _dids[subject].active = false;
        _dids[subject].updated = block.timestamp;
        activeDIDs--;

        emit DIDDeactivated(subject);
    }

    /**
     * @notice Reactivate a previously deactivated DID.
     */
    function reactivate(address subject)
        external
        onlyController(subject)
        didExists(subject)
    {
        require(!_dids[subject].active, "Already active");
        _dids[subject].active = true;
        _dids[subject].updated = block.timestamp;
        activeDIDs++;

        emit DIDReactivated(subject);
    }

    // ---------------------------------------------------------------
    // Admin
    // ---------------------------------------------------------------

    function updateFeeRecipient(address newRecipient) external onlyOwner {
        require(newRecipient != address(0), "Zero address");
        platformFeeRecipient = newRecipient;
    }

    // ---------------------------------------------------------------
    // Internal helpers
    // ---------------------------------------------------------------

    function _toHexString(address addr) internal pure returns (string memory) {
        bytes memory alphabet = "0123456789abcdef";
        bytes20 value = bytes20(addr);
        bytes memory str = new bytes(42);
        str[0] = "0";
        str[1] = "x";
        for (uint256 i = 0; i < 20; i++) {
            str[2 + i * 2] = alphabet[uint8(value[i] >> 4)];
            str[3 + i * 2] = alphabet[uint8(value[i] & 0x0f)];
        }
        return string(str);
    }
}
