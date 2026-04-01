// SPDX-License-Identifier: MIT
pragma solidity ^0.8.20;

import "@openzeppelin/contracts/token/ERC721/IERC721.sol";
import "@openzeppelin/contracts/token/ERC20/IERC20.sol";
import "@openzeppelin/contracts/token/ERC20/utils/SafeERC20.sol";
import "@openzeppelin/contracts/utils/ReentrancyGuard.sol";
import "@openzeppelin/contracts/access/Ownable.sol";

/**
 * @title OpenMatrixMarketplace
 * @notice Marketplace with 5% platform fee routed to NeoSafe.
 *         Supports ERC-721 listings paid in native ETH or ERC-20 tokens.
 */
contract OpenMatrixMarketplace is ReentrancyGuard, Ownable {
    using SafeERC20 for IERC20;

    // ---------------------------------------------------------------
    // Constants
    // ---------------------------------------------------------------
    uint256 public constant PLATFORM_FEE_BPS = 500; // 5%
    uint256 private constant BPS_DENOMINATOR = 10_000;

    // ---------------------------------------------------------------
    // State
    // ---------------------------------------------------------------
    address public platformFeeRecipient; // NeoSafe wallet

    struct Listing {
        address seller;
        address nftContract;
        uint256 tokenId;
        uint256 price;           // in wei (ETH) or token base units
        address paymentToken;    // address(0) = native ETH
        bool active;
    }

    uint256 private _nextListingId;
    mapping(uint256 => Listing) public listings;

    // ---------------------------------------------------------------
    // Events
    // ---------------------------------------------------------------
    event ItemListed(
        uint256 indexed listingId,
        address indexed seller,
        address nftContract,
        uint256 tokenId,
        uint256 price,
        address paymentToken
    );

    event ItemSold(
        uint256 indexed listingId,
        address indexed buyer,
        address indexed seller,
        uint256 price,
        uint256 platformFee
    );

    event ItemCancelled(uint256 indexed listingId, address indexed seller);

    event PriceUpdated(uint256 indexed listingId, uint256 oldPrice, uint256 newPrice);

    event FeeRecipientUpdated(address oldRecipient, address newRecipient);

    // ---------------------------------------------------------------
    // Constructor
    // ---------------------------------------------------------------
    constructor(address _platformFeeRecipient) Ownable(msg.sender) {
        require(_platformFeeRecipient != address(0), "Zero fee recipient");
        platformFeeRecipient = _platformFeeRecipient;
    }

    // ---------------------------------------------------------------
    // Listing management
    // ---------------------------------------------------------------

    /**
     * @notice List an ERC-721 NFT for sale.
     * @param nftContract The NFT contract address.
     * @param tokenId     Token ID to list.
     * @param price       Sale price (in paymentToken units, or wei if ETH).
     * @param paymentToken address(0) for native ETH; otherwise ERC-20 address.
     */
    function listItem(
        address nftContract,
        uint256 tokenId,
        uint256 price,
        address paymentToken
    ) external returns (uint256 listingId) {
        require(price > 0, "Price must be > 0");
        IERC721 nft = IERC721(nftContract);
        require(nft.ownerOf(tokenId) == msg.sender, "Not token owner");
        require(
            nft.isApprovedForAll(msg.sender, address(this)) ||
                nft.getApproved(tokenId) == address(this),
            "Marketplace not approved"
        );

        listingId = _nextListingId++;
        listings[listingId] = Listing({
            seller: msg.sender,
            nftContract: nftContract,
            tokenId: tokenId,
            price: price,
            paymentToken: paymentToken,
            active: true
        });

        emit ItemListed(listingId, msg.sender, nftContract, tokenId, price, paymentToken);
    }

    /**
     * @notice Buy a listed item. 5% fee goes to platformFeeRecipient.
     */
    function buyItem(uint256 listingId) external payable nonReentrant {
        Listing storage listing = listings[listingId];
        require(listing.active, "Not active");
        require(msg.sender != listing.seller, "Seller cannot buy own item");

        uint256 fee = (listing.price * PLATFORM_FEE_BPS) / BPS_DENOMINATOR;
        uint256 sellerProceeds = listing.price - fee;

        listing.active = false;

        if (listing.paymentToken == address(0)) {
            // Native ETH
            require(msg.value == listing.price, "Incorrect ETH amount");

            (bool feeSent, ) = platformFeeRecipient.call{value: fee}("");
            require(feeSent, "Fee transfer failed");

            (bool sellerSent, ) = listing.seller.call{value: sellerProceeds}("");
            require(sellerSent, "Seller transfer failed");
        } else {
            // ERC-20
            require(msg.value == 0, "ETH not accepted for token listings");
            IERC20 token = IERC20(listing.paymentToken);
            token.safeTransferFrom(msg.sender, platformFeeRecipient, fee);
            token.safeTransferFrom(msg.sender, listing.seller, sellerProceeds);
        }

        // Transfer NFT to buyer
        IERC721(listing.nftContract).safeTransferFrom(
            listing.seller,
            msg.sender,
            listing.tokenId
        );

        emit ItemSold(listingId, msg.sender, listing.seller, listing.price, fee);
    }

    /**
     * @notice Cancel an active listing. Only the seller can cancel.
     */
    function cancelListing(uint256 listingId) external {
        Listing storage listing = listings[listingId];
        require(listing.active, "Not active");
        require(listing.seller == msg.sender, "Not seller");

        listing.active = false;
        emit ItemCancelled(listingId, msg.sender);
    }

    /**
     * @notice Update the price of an active listing.
     */
    function updatePrice(uint256 listingId, uint256 newPrice) external {
        Listing storage listing = listings[listingId];
        require(listing.active, "Not active");
        require(listing.seller == msg.sender, "Not seller");
        require(newPrice > 0, "Price must be > 0");

        uint256 oldPrice = listing.price;
        listing.price = newPrice;
        emit PriceUpdated(listingId, oldPrice, newPrice);
    }

    // ---------------------------------------------------------------
    // Admin
    // ---------------------------------------------------------------

    function updateFeeRecipient(address newRecipient) external onlyOwner {
        require(newRecipient != address(0), "Zero address");
        address old = platformFeeRecipient;
        platformFeeRecipient = newRecipient;
        emit FeeRecipientUpdated(old, newRecipient);
    }
}
