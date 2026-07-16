// SPDX-License-Identifier: MIT
pragma solidity ^0.8.20;

import "@openzeppelin/contracts/token/ERC721/ERC721.sol";
import "@openzeppelin/contracts/token/ERC721/extensions/ERC721URIStorage.sol";
import "@openzeppelin/contracts/token/ERC721/extensions/ERC721Enumerable.sol";
import "@openzeppelin/contracts/access/Ownable.sol";
import "@openzeppelin/contracts/utils/ReentrancyGuard.sol";

/**
 * @title PropertyDeed
 * @notice ERC-721 where each token represents a claim on a specific real
 *         property, minted by the platform operator after the property's
 *         document set is verified. The deed token is transferred atomically
 *         inside PropertyEscrow settlement — never separately from payment.
 *
 *         HONESTY BOUNDARY (do not confuse the token with the world): holding
 *         this token records the on-chain side of a transfer. Legal ownership
 *         additionally requires county recording — a real-world step the
 *         platform tracks explicitly off-chain and never pretends away.
 *
 *         Token URIs should point at the attested document bundle (content
 *         hashes on-chain via EAS; blobs in decentralized storage).
 */
contract PropertyDeed is
    ERC721,
    ERC721URIStorage,
    ERC721Enumerable,
    Ownable,
    ReentrancyGuard
{
    // ---------------------------------------------------------------
    // State
    // ---------------------------------------------------------------
    uint256 private _nextTokenId;

    /// @notice Off-chain property record id (platform id) per token, so the
    ///         chain side and the platform record can always be reconciled.
    mapping(uint256 => string) public propertyIdOf;

    /// @notice One deed per property record: platform property id -> token id
    ///         (+1, so 0 means "no deed minted"). Prevents duplicate deeds
    ///         for the same property record.
    mapping(bytes32 => uint256) private _tokenForProperty;

    // ---------------------------------------------------------------
    // Events
    // ---------------------------------------------------------------
    event DeedMinted(uint256 indexed tokenId, string propertyId, address indexed to);

    // ---------------------------------------------------------------
    // Constructor
    // ---------------------------------------------------------------
    constructor() ERC721("OpenMatrix Property Deed", "OMDEED") Ownable(msg.sender) {}

    // ---------------------------------------------------------------
    // Minting — platform operator only
    // ---------------------------------------------------------------

    /**
     * @notice Mint the deed token for a verified property record. Operator
     *         (contract owner) only; one deed per property id, ever.
     * @param to          Initial holder — the seller's wallet.
     * @param propertyId  The platform's property record id.
     * @param uri         Metadata URI (attested document bundle).
     */
    function mint(address to, string calldata propertyId, string calldata uri)
        external
        onlyOwner
        nonReentrant
        returns (uint256)
    {
        require(to != address(0), "Zero address");
        require(bytes(propertyId).length > 0, "Empty property id");
        bytes32 key = keccak256(bytes(propertyId));
        require(_tokenForProperty[key] == 0, "Deed already minted");

        uint256 tokenId = ++_nextTokenId; // token ids start at 1 (0 = none)
        _tokenForProperty[key] = tokenId;
        propertyIdOf[tokenId] = propertyId;
        _safeMint(to, tokenId);
        _setTokenURI(tokenId, uri);

        emit DeedMinted(tokenId, propertyId, to);
        return tokenId;
    }

    /// @notice Token id for a platform property id (0 = no deed minted).
    function tokenForProperty(string calldata propertyId) external view returns (uint256) {
        return _tokenForProperty[keccak256(bytes(propertyId))];
    }

    // ---------------------------------------------------------------
    // ERC-165 / Override resolution (OZ v5 diamond)
    // ---------------------------------------------------------------

    function supportsInterface(bytes4 interfaceId)
        public
        view
        override(ERC721, ERC721URIStorage, ERC721Enumerable)
        returns (bool)
    {
        return super.supportsInterface(interfaceId);
    }

    function tokenURI(uint256 tokenId)
        public
        view
        override(ERC721, ERC721URIStorage)
        returns (string memory)
    {
        return super.tokenURI(tokenId);
    }

    function _update(address to, uint256 tokenId, address auth)
        internal
        override(ERC721, ERC721Enumerable)
        returns (address)
    {
        return super._update(to, tokenId, auth);
    }

    function _increaseBalance(address account, uint128 value)
        internal
        override(ERC721, ERC721Enumerable)
    {
        super._increaseBalance(account, value);
    }
}
