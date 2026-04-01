// SPDX-License-Identifier: MIT
pragma solidity ^0.8.20;

import "@openzeppelin/contracts/token/ERC721/ERC721.sol";
import "@openzeppelin/contracts/token/ERC721/extensions/ERC721URIStorage.sol";
import "@openzeppelin/contracts/token/ERC721/extensions/ERC721Enumerable.sol";
import "@openzeppelin/contracts/interfaces/IERC2981.sol";
import "@openzeppelin/contracts/access/Ownable.sol";
import "@openzeppelin/contracts/utils/ReentrancyGuard.sol";

/**
 * @title OpenMatrixNFT
 * @notice ERC-721 with ERC-2981 royalties.
 *         Automatic royalty distribution on every sale through the
 *         marketplace or any ERC-2981-aware platform.
 */
contract OpenMatrixNFT is
    ERC721,
    ERC721URIStorage,
    ERC721Enumerable,
    IERC2981,
    Ownable,
    ReentrancyGuard
{
    // ---------------------------------------------------------------
    // State
    // ---------------------------------------------------------------
    uint256 private _nextTokenId;

    address public platformFeeRecipient; // NeoSafe

    // Per-token royalty info
    struct RoyaltyInfo {
        address receiver;
        uint96 feeBps; // basis points (e.g. 500 = 5%)
    }

    // Default royalty for new mints
    RoyaltyInfo private _defaultRoyalty;

    // Per-token override
    mapping(uint256 => RoyaltyInfo) private _tokenRoyalties;

    // Creator tracking
    mapping(uint256 => address) public creators;

    uint256 public constant MAX_ROYALTY_BPS = 1_000; // 10% cap
    uint256 public mintPrice;

    // ---------------------------------------------------------------
    // Events
    // ---------------------------------------------------------------
    event Minted(uint256 indexed tokenId, address indexed creator, string tokenURI);
    event RoyaltySet(uint256 indexed tokenId, address receiver, uint96 feeBps);
    event DefaultRoyaltySet(address receiver, uint96 feeBps);
    event MintPriceUpdated(uint256 oldPrice, uint256 newPrice);

    // ---------------------------------------------------------------
    // Constructor
    // ---------------------------------------------------------------
    constructor(
        address _platformFeeRecipient,
        uint96 defaultRoyaltyBps,
        uint256 _mintPrice
    ) ERC721("OpenMatrix NFT", "OMNFT") Ownable(msg.sender) {
        require(_platformFeeRecipient != address(0), "Zero fee recipient");
        require(defaultRoyaltyBps <= MAX_ROYALTY_BPS, "Royalty too high");

        platformFeeRecipient = _platformFeeRecipient;
        _defaultRoyalty = RoyaltyInfo({
            receiver: _platformFeeRecipient,
            feeBps: defaultRoyaltyBps
        });
        mintPrice = _mintPrice;
    }

    // ---------------------------------------------------------------
    // Minting
    // ---------------------------------------------------------------

    /**
     * @notice Mint a new NFT. Creator receives royalty rights.
     * @param to         Recipient of the minted token.
     * @param uri        Token metadata URI.
     * @param royaltyBps Royalty in basis points for this token (0 = use default).
     */
    function mint(address to, string calldata uri, uint96 royaltyBps)
        external
        payable
        nonReentrant
        returns (uint256 tokenId)
    {
        require(msg.value >= mintPrice, "Insufficient mint fee");
        require(royaltyBps <= MAX_ROYALTY_BPS, "Royalty too high");

        tokenId = _nextTokenId++;
        _safeMint(to, tokenId);
        _setTokenURI(tokenId, uri);

        creators[tokenId] = msg.sender;

        // Set per-token royalty if provided; otherwise default applies
        if (royaltyBps > 0) {
            _tokenRoyalties[tokenId] = RoyaltyInfo({
                receiver: msg.sender,
                feeBps: royaltyBps
            });
            emit RoyaltySet(tokenId, msg.sender, royaltyBps);
        }

        // Forward mint fee to platform
        if (msg.value > 0) {
            (bool sent, ) = platformFeeRecipient.call{value: msg.value}("");
            require(sent, "Fee transfer failed");
        }

        emit Minted(tokenId, msg.sender, uri);
    }

    /**
     * @notice Owner-only batch mint (no fee).
     */
    function batchMint(
        address to,
        string[] calldata uris
    ) external onlyOwner returns (uint256[] memory tokenIds) {
        tokenIds = new uint256[](uris.length);
        for (uint256 i = 0; i < uris.length; i++) {
            uint256 tokenId = _nextTokenId++;
            _safeMint(to, tokenId);
            _setTokenURI(tokenId, uris[i]);
            creators[tokenId] = msg.sender;
            tokenIds[i] = tokenId;
            emit Minted(tokenId, msg.sender, uris[i]);
        }
    }

    // ---------------------------------------------------------------
    // ERC-2981 Royalty
    // ---------------------------------------------------------------

    /**
     * @notice Returns royalty info for a given token and sale price.
     *         Implements ERC-2981.
     */
    function royaltyInfo(uint256 tokenId, uint256 salePrice)
        external
        view
        override
        returns (address receiver, uint256 royaltyAmount)
    {
        RoyaltyInfo memory info = _tokenRoyalties[tokenId];
        if (info.receiver == address(0)) {
            info = _defaultRoyalty;
        }
        receiver = info.receiver;
        royaltyAmount = (salePrice * info.feeBps) / 10_000;
    }

    function setDefaultRoyalty(address receiver, uint96 feeBps) external onlyOwner {
        require(receiver != address(0), "Zero address");
        require(feeBps <= MAX_ROYALTY_BPS, "Royalty too high");
        _defaultRoyalty = RoyaltyInfo({receiver: receiver, feeBps: feeBps});
        emit DefaultRoyaltySet(receiver, feeBps);
    }

    function setTokenRoyalty(uint256 tokenId, address receiver, uint96 feeBps) external {
        require(msg.sender == creators[tokenId] || msg.sender == owner(), "Not authorized");
        require(receiver != address(0), "Zero address");
        require(feeBps <= MAX_ROYALTY_BPS, "Royalty too high");
        _tokenRoyalties[tokenId] = RoyaltyInfo({receiver: receiver, feeBps: feeBps});
        emit RoyaltySet(tokenId, receiver, feeBps);
    }

    // ---------------------------------------------------------------
    // Admin
    // ---------------------------------------------------------------

    function setMintPrice(uint256 newPrice) external onlyOwner {
        uint256 old = mintPrice;
        mintPrice = newPrice;
        emit MintPriceUpdated(old, newPrice);
    }

    function updateFeeRecipient(address newRecipient) external onlyOwner {
        require(newRecipient != address(0), "Zero address");
        platformFeeRecipient = newRecipient;
    }

    // ---------------------------------------------------------------
    // ERC-165 / Override resolution
    // ---------------------------------------------------------------

    function supportsInterface(bytes4 interfaceId)
        public
        view
        override(ERC721, ERC721URIStorage, ERC721Enumerable, IERC165)
        returns (bool)
    {
        return
            interfaceId == type(IERC2981).interfaceId ||
            super.supportsInterface(interfaceId);
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
