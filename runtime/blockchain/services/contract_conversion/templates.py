"""
Contract templates — complete Solidity source for common patterns.

Each template is a fully deployable Solidity contract with OpenZeppelin
imports, constructor parameters, and gas-optimised patterns for Base L2.
Templates include placeholders (``{{NAME}}``, ``{{SYMBOL}}``, etc.)
that the generator fills at generation time.

Available templates:
  erc20, erc721, erc1155, governor, timelock, vesting, staking, marketplace
"""

from __future__ import annotations

TEMPLATES: dict[str, str] = {}

# ── ERC-20 Token ──────────────────────────────────────────────────────

TEMPLATES["erc20"] = '''\
// SPDX-License-Identifier: MIT
pragma solidity ^0.8.20;

import "@openzeppelin/contracts/token/ERC20/ERC20.sol";
import "@openzeppelin/contracts/token/ERC20/extensions/ERC20Burnable.sol";
import "@openzeppelin/contracts/token/ERC20/extensions/ERC20Permit.sol";
import "@openzeppelin/contracts/access/Ownable.sol";

/**
 * @title {{NAME}}
 * @notice ERC-20 token with burn, permit, and owner-only minting.
 *         Optimised for Base L2 deployment via 0pnMatrx.
 */
contract {{NAME}} is ERC20, ERC20Burnable, ERC20Permit, Ownable {
    uint256 public constant MAX_SUPPLY = {{MAX_SUPPLY}};

    constructor(
        address initialOwner,
        uint256 initialMint
    )
        ERC20("{{NAME}}", "{{SYMBOL}}")
        ERC20Permit("{{NAME}}")
        Ownable(initialOwner)
    {
        require(initialMint <= MAX_SUPPLY, "Exceeds max supply");
        _mint(initialOwner, initialMint);
    }

    function mint(address to, uint256 amount) external onlyOwner {
        require(totalSupply() + amount <= MAX_SUPPLY, "Exceeds max supply");
        _mint(to, amount);
    }
}
'''

# ── ERC-721 NFT ───────────────────────────────────────────────────────

TEMPLATES["erc721"] = '''\
// SPDX-License-Identifier: MIT
pragma solidity ^0.8.20;

import "@openzeppelin/contracts/token/ERC721/ERC721.sol";
import "@openzeppelin/contracts/token/ERC721/extensions/ERC721Enumerable.sol";
import "@openzeppelin/contracts/token/ERC721/extensions/ERC721URIStorage.sol";
import "@openzeppelin/contracts/token/common/ERC2981.sol";
import "@openzeppelin/contracts/access/Ownable.sol";
import "@openzeppelin/contracts/utils/Counters.sol";

/**
 * @title {{NAME}}
 * @notice ERC-721 NFT with enumeration, URI storage, and ERC-2981 royalties.
 *         Optimised for Base L2 deployment via 0pnMatrx.
 */
contract {{NAME}} is ERC721, ERC721Enumerable, ERC721URIStorage, ERC2981, Ownable {
    using Counters for Counters.Counter;
    Counters.Counter private _tokenIdCounter;

    string private _baseTokenURI;
    uint256 public maxSupply;

    constructor(
        address initialOwner,
        string memory baseURI,
        uint256 _maxSupply,
        uint96 royaltyBps
    )
        ERC721("{{NAME}}", "{{SYMBOL}}")
        Ownable(initialOwner)
    {
        _baseTokenURI = baseURI;
        maxSupply = _maxSupply;
        _setDefaultRoyalty(initialOwner, royaltyBps);
    }

    function mint(address to, string memory uri) external onlyOwner returns (uint256) {
        uint256 tokenId = _tokenIdCounter.current();
        require(tokenId < maxSupply, "Max supply reached");
        _tokenIdCounter.increment();
        _safeMint(to, tokenId);
        _setTokenURI(tokenId, uri);
        return tokenId;
    }

    function setBaseURI(string memory baseURI) external onlyOwner {
        _baseTokenURI = baseURI;
    }

    function _baseURI() internal view override returns (string memory) {
        return _baseTokenURI;
    }

    // Overrides required by Solidity
    function _update(address to, uint256 tokenId, address auth)
        internal override(ERC721, ERC721Enumerable) returns (address)
    {
        return super._update(to, tokenId, auth);
    }

    function _increaseBalance(address account, uint128 value)
        internal override(ERC721, ERC721Enumerable)
    {
        super._increaseBalance(account, value);
    }

    function tokenURI(uint256 tokenId)
        public view override(ERC721, ERC721URIStorage) returns (string memory)
    {
        return super.tokenURI(tokenId);
    }

    function supportsInterface(bytes4 interfaceId)
        public view override(ERC721, ERC721Enumerable, ERC721URIStorage, ERC2981) returns (bool)
    {
        return super.supportsInterface(interfaceId);
    }
}
'''

# ── ERC-1155 Multi-Token ──────────────────────────────────────────────

TEMPLATES["erc1155"] = '''\
// SPDX-License-Identifier: MIT
pragma solidity ^0.8.20;

import "@openzeppelin/contracts/token/ERC1155/ERC1155.sol";
import "@openzeppelin/contracts/token/ERC1155/extensions/ERC1155Supply.sol";
import "@openzeppelin/contracts/token/common/ERC2981.sol";
import "@openzeppelin/contracts/access/Ownable.sol";

/**
 * @title {{NAME}}
 * @notice ERC-1155 multi-token with supply tracking and ERC-2981 royalties.
 *         Optimised for Base L2 deployment via 0pnMatrx.
 */
contract {{NAME}} is ERC1155, ERC1155Supply, ERC2981, Ownable {
    string public name;
    string public symbol;

    mapping(uint256 => uint256) public maxSupplyPerToken;
    mapping(uint256 => string) private _tokenURIs;

    constructor(
        address initialOwner,
        string memory _name,
        string memory _symbol,
        string memory uri,
        uint96 royaltyBps
    )
        ERC1155(uri)
        Ownable(initialOwner)
    {
        name = _name;
        symbol = _symbol;
        _setDefaultRoyalty(initialOwner, royaltyBps);
    }

    function mint(address to, uint256 id, uint256 amount, bytes memory data)
        external onlyOwner
    {
        if (maxSupplyPerToken[id] > 0) {
            require(totalSupply(id) + amount <= maxSupplyPerToken[id], "Exceeds max supply");
        }
        _mint(to, id, amount, data);
    }

    function mintBatch(address to, uint256[] memory ids, uint256[] memory amounts, bytes memory data)
        external onlyOwner
    {
        for (uint256 i = 0; i < ids.length; i++) {
            if (maxSupplyPerToken[ids[i]] > 0) {
                require(
                    totalSupply(ids[i]) + amounts[i] <= maxSupplyPerToken[ids[i]],
                    "Exceeds max supply"
                );
            }
        }
        _mintBatch(to, ids, amounts, data);
    }

    function setMaxSupply(uint256 id, uint256 _maxSupply) external onlyOwner {
        maxSupplyPerToken[id] = _maxSupply;
    }

    function setTokenURI(uint256 id, string memory tokenURI_) external onlyOwner {
        _tokenURIs[id] = tokenURI_;
    }

    function uri(uint256 id) public view override returns (string memory) {
        string memory tokenURI_ = _tokenURIs[id];
        if (bytes(tokenURI_).length > 0) {
            return tokenURI_;
        }
        return super.uri(id);
    }

    function _update(address from, address to, uint256[] memory ids, uint256[] memory values)
        internal override(ERC1155, ERC1155Supply)
    {
        super._update(from, to, ids, values);
    }

    function supportsInterface(bytes4 interfaceId)
        public view override(ERC1155, ERC2981) returns (bool)
    {
        return super.supportsInterface(interfaceId);
    }
}
'''

# ── Governor (DAO Voting) ────────────────────────────────────────────

TEMPLATES["governor"] = '''\
// SPDX-License-Identifier: MIT
pragma solidity ^0.8.20;

import "@openzeppelin/contracts/governance/Governor.sol";
import "@openzeppelin/contracts/governance/extensions/GovernorSettings.sol";
import "@openzeppelin/contracts/governance/extensions/GovernorCountingSimple.sol";
import "@openzeppelin/contracts/governance/extensions/GovernorVotes.sol";
import "@openzeppelin/contracts/governance/extensions/GovernorVotesQuorumFraction.sol";
import "@openzeppelin/contracts/governance/extensions/GovernorTimelockControl.sol";

/**
 * @title {{NAME}}
 * @notice DAO Governor with configurable voting parameters, quorum fraction,
 *         and timelock execution.  Optimised for Base L2.
 */
contract {{NAME}} is
    Governor,
    GovernorSettings,
    GovernorCountingSimple,
    GovernorVotes,
    GovernorVotesQuorumFraction,
    GovernorTimelockControl
{
    constructor(
        IVotes _token,
        TimelockController _timelock,
        uint48 _votingDelay,
        uint32 _votingPeriod,
        uint256 _proposalThreshold,
        uint256 _quorumPercent
    )
        Governor("{{NAME}}")
        GovernorSettings(_votingDelay, _votingPeriod, _proposalThreshold)
        GovernorVotes(_token)
        GovernorVotesQuorumFraction(_quorumPercent)
        GovernorTimelockControl(_timelock)
    {}

    // Overrides required by Solidity
    function votingDelay() public view override(Governor, GovernorSettings) returns (uint256) {
        return super.votingDelay();
    }

    function votingPeriod() public view override(Governor, GovernorSettings) returns (uint256) {
        return super.votingPeriod();
    }

    function quorum(uint256 blockNumber)
        public view override(Governor, GovernorVotesQuorumFraction) returns (uint256)
    {
        return super.quorum(blockNumber);
    }

    function state(uint256 proposalId)
        public view override(Governor, GovernorTimelockControl) returns (ProposalState)
    {
        return super.state(proposalId);
    }

    function proposalNeedsQueuing(uint256 proposalId)
        public view override(Governor, GovernorTimelockControl) returns (bool)
    {
        return super.proposalNeedsQueuing(proposalId);
    }

    function proposalThreshold()
        public view override(Governor, GovernorSettings) returns (uint256)
    {
        return super.proposalThreshold();
    }

    function _queueOperations(
        uint256 proposalId, address[] memory targets, uint256[] memory values,
        bytes[] memory calldatas, bytes32 descriptionHash
    ) internal override(Governor, GovernorTimelockControl) returns (uint48) {
        return super._queueOperations(proposalId, targets, values, calldatas, descriptionHash);
    }

    function _executeOperations(
        uint256 proposalId, address[] memory targets, uint256[] memory values,
        bytes[] memory calldatas, bytes32 descriptionHash
    ) internal override(Governor, GovernorTimelockControl) {
        super._executeOperations(proposalId, targets, values, calldatas, descriptionHash);
    }

    function _cancel(
        address[] memory targets, uint256[] memory values,
        bytes[] memory calldatas, bytes32 descriptionHash
    ) internal override(Governor, GovernorTimelockControl) returns (uint256) {
        return super._cancel(targets, values, calldatas, descriptionHash);
    }

    function _executor()
        internal view override(Governor, GovernorTimelockControl) returns (address)
    {
        return super._executor();
    }
}
'''

# ── Timelock Controller ──────────────────────────────────────────────

TEMPLATES["timelock"] = '''\
// SPDX-License-Identifier: MIT
pragma solidity ^0.8.20;

import "@openzeppelin/contracts/governance/TimelockController.sol";

/**
 * @title {{NAME}}
 * @notice Timelock controller for DAO governance execution delays.
 *         Optimised for Base L2 deployment via 0pnMatrx.
 */
contract {{NAME}} is TimelockController {
    constructor(
        uint256 minDelay,
        address[] memory proposers,
        address[] memory executors,
        address admin
    )
        TimelockController(minDelay, proposers, executors, admin)
    {}
}
'''

# ── Token Vesting ────────────────────────────────────────────────────

TEMPLATES["vesting"] = '''\
// SPDX-License-Identifier: MIT
pragma solidity ^0.8.20;

import "@openzeppelin/contracts/token/ERC20/IERC20.sol";
import "@openzeppelin/contracts/token/ERC20/utils/SafeERC20.sol";
import "@openzeppelin/contracts/access/Ownable.sol";
import "@openzeppelin/contracts/utils/ReentrancyGuard.sol";

/**
 * @title {{NAME}}
 * @notice Linear token vesting with cliff period and revocability.
 *         Optimised for Base L2 deployment via 0pnMatrx.
 */
contract {{NAME}} is Ownable, ReentrancyGuard {
    using SafeERC20 for IERC20;

    struct VestingSchedule {
        address beneficiary;
        uint256 totalAmount;
        uint256 released;
        uint256 start;
        uint256 cliff;
        uint256 duration;
        bool revocable;
        bool revoked;
    }

    IERC20 public immutable token;
    mapping(bytes32 => VestingSchedule) public schedules;
    bytes32[] public scheduleIds;

    event ScheduleCreated(bytes32 indexed scheduleId, address indexed beneficiary, uint256 amount);
    event TokensReleased(bytes32 indexed scheduleId, uint256 amount);
    event ScheduleRevoked(bytes32 indexed scheduleId);

    constructor(address _token, address initialOwner) Ownable(initialOwner) {
        token = IERC20(_token);
    }

    function createSchedule(
        address beneficiary,
        uint256 totalAmount,
        uint256 start,
        uint256 cliffDuration,
        uint256 vestingDuration,
        bool revocable
    ) external onlyOwner returns (bytes32) {
        require(beneficiary != address(0), "Zero address");
        require(totalAmount > 0, "Zero amount");
        require(vestingDuration > 0, "Zero duration");
        require(cliffDuration <= vestingDuration, "Cliff > duration");

        bytes32 scheduleId = keccak256(
            abi.encodePacked(beneficiary, totalAmount, start, scheduleIds.length)
        );

        schedules[scheduleId] = VestingSchedule({
            beneficiary: beneficiary,
            totalAmount: totalAmount,
            released: 0,
            start: start,
            cliff: start + cliffDuration,
            duration: vestingDuration,
            revocable: revocable,
            revoked: false
        });

        scheduleIds.push(scheduleId);
        token.safeTransferFrom(msg.sender, address(this), totalAmount);
        emit ScheduleCreated(scheduleId, beneficiary, totalAmount);
        return scheduleId;
    }

    function release(bytes32 scheduleId) external nonReentrant {
        VestingSchedule storage schedule = schedules[scheduleId];
        require(schedule.beneficiary != address(0), "Invalid schedule");
        require(!schedule.revoked, "Schedule revoked");

        uint256 vested = _vestedAmount(schedule);
        uint256 releasable = vested - schedule.released;
        require(releasable > 0, "Nothing to release");

        schedule.released += releasable;
        token.safeTransfer(schedule.beneficiary, releasable);
        emit TokensReleased(scheduleId, releasable);
    }

    function revoke(bytes32 scheduleId) external onlyOwner {
        VestingSchedule storage schedule = schedules[scheduleId];
        require(schedule.revocable, "Not revocable");
        require(!schedule.revoked, "Already revoked");

        uint256 vested = _vestedAmount(schedule);
        uint256 refund = schedule.totalAmount - vested;

        schedule.revoked = true;
        if (refund > 0) {
            token.safeTransfer(owner(), refund);
        }
        emit ScheduleRevoked(scheduleId);
    }

    function _vestedAmount(VestingSchedule memory schedule) internal view returns (uint256) {
        if (block.timestamp < schedule.cliff) {
            return 0;
        }
        uint256 elapsed = block.timestamp - schedule.start;
        if (elapsed >= schedule.duration) {
            return schedule.totalAmount;
        }
        return (schedule.totalAmount * elapsed) / schedule.duration;
    }

    function getScheduleCount() external view returns (uint256) {
        return scheduleIds.length;
    }
}
'''

# ── Staking ──────────────────────────────────────────────────────────

TEMPLATES["staking"] = '''\
// SPDX-License-Identifier: MIT
pragma solidity ^0.8.20;

import "@openzeppelin/contracts/token/ERC20/IERC20.sol";
import "@openzeppelin/contracts/token/ERC20/utils/SafeERC20.sol";
import "@openzeppelin/contracts/access/Ownable.sol";
import "@openzeppelin/contracts/utils/ReentrancyGuard.sol";

/**
 * @title {{NAME}}
 * @notice Staking contract with configurable reward rate, lock periods,
 *         and compound rewards.  Optimised for Base L2 via 0pnMatrx.
 */
contract {{NAME}} is Ownable, ReentrancyGuard {
    using SafeERC20 for IERC20;

    IERC20 public immutable stakingToken;
    IERC20 public immutable rewardToken;

    uint256 public rewardRatePerSecond;
    uint256 public lastUpdateTime;
    uint256 public rewardPerTokenStored;
    uint256 public totalStaked;
    uint256 public lockPeriod;

    struct StakeInfo {
        uint256 amount;
        uint256 rewardDebt;
        uint256 rewards;
        uint256 stakedAt;
    }

    mapping(address => StakeInfo) public stakes;
    mapping(address => uint256) public userRewardPerTokenPaid;

    event Staked(address indexed user, uint256 amount);
    event Withdrawn(address indexed user, uint256 amount);
    event RewardPaid(address indexed user, uint256 reward);
    event RewardRateUpdated(uint256 newRate);

    constructor(
        address _stakingToken,
        address _rewardToken,
        uint256 _rewardRate,
        uint256 _lockPeriod,
        address initialOwner
    ) Ownable(initialOwner) {
        stakingToken = IERC20(_stakingToken);
        rewardToken = IERC20(_rewardToken);
        rewardRatePerSecond = _rewardRate;
        lockPeriod = _lockPeriod;
        lastUpdateTime = block.timestamp;
    }

    modifier updateReward(address account) {
        rewardPerTokenStored = rewardPerToken();
        lastUpdateTime = block.timestamp;
        if (account != address(0)) {
            stakes[account].rewards = earned(account);
            userRewardPerTokenPaid[account] = rewardPerTokenStored;
        }
        _;
    }

    function stake(uint256 amount) external nonReentrant updateReward(msg.sender) {
        require(amount > 0, "Cannot stake 0");
        totalStaked += amount;
        stakes[msg.sender].amount += amount;
        stakes[msg.sender].stakedAt = block.timestamp;
        stakingToken.safeTransferFrom(msg.sender, address(this), amount);
        emit Staked(msg.sender, amount);
    }

    function withdraw(uint256 amount) external nonReentrant updateReward(msg.sender) {
        StakeInfo storage info = stakes[msg.sender];
        require(amount > 0, "Cannot withdraw 0");
        require(info.amount >= amount, "Insufficient stake");
        require(
            block.timestamp >= info.stakedAt + lockPeriod,
            "Lock period not elapsed"
        );
        totalStaked -= amount;
        info.amount -= amount;
        stakingToken.safeTransfer(msg.sender, amount);
        emit Withdrawn(msg.sender, amount);
    }

    function claimReward() external nonReentrant updateReward(msg.sender) {
        uint256 reward = stakes[msg.sender].rewards;
        if (reward > 0) {
            stakes[msg.sender].rewards = 0;
            rewardToken.safeTransfer(msg.sender, reward);
            emit RewardPaid(msg.sender, reward);
        }
    }

    function rewardPerToken() public view returns (uint256) {
        if (totalStaked == 0) {
            return rewardPerTokenStored;
        }
        return rewardPerTokenStored +
            ((block.timestamp - lastUpdateTime) * rewardRatePerSecond * 1e18) / totalStaked;
    }

    function earned(address account) public view returns (uint256) {
        return
            (stakes[account].amount * (rewardPerToken() - userRewardPerTokenPaid[account])) / 1e18
            + stakes[account].rewards;
    }

    function setRewardRate(uint256 newRate) external onlyOwner updateReward(address(0)) {
        rewardRatePerSecond = newRate;
        emit RewardRateUpdated(newRate);
    }

    function setLockPeriod(uint256 _lockPeriod) external onlyOwner {
        lockPeriod = _lockPeriod;
    }
}
'''

# ── NFT Marketplace ──────────────────────────────────────────────────

TEMPLATES["marketplace"] = '''\
// SPDX-License-Identifier: MIT
pragma solidity ^0.8.20;

import "@openzeppelin/contracts/token/ERC721/IERC721.sol";
import "@openzeppelin/contracts/token/common/ERC2981.sol";
import "@openzeppelin/contracts/access/Ownable.sol";
import "@openzeppelin/contracts/utils/ReentrancyGuard.sol";

/**
 * @title {{NAME}}
 * @notice NFT marketplace with ERC-2981 royalty enforcement, platform fees,
 *         and listing management.  Optimised for Base L2 via 0pnMatrx.
 */
contract {{NAME}} is Ownable, ReentrancyGuard {
    struct Listing {
        address seller;
        address nftContract;
        uint256 tokenId;
        uint256 price;
        bool active;
    }

    uint256 public platformFeeBps;
    address public feeRecipient;
    uint256 private _listingCounter;

    mapping(uint256 => Listing) public listings;

    event Listed(uint256 indexed listingId, address indexed seller, address nftContract, uint256 tokenId, uint256 price);
    event Sold(uint256 indexed listingId, address indexed buyer, uint256 price);
    event Cancelled(uint256 indexed listingId);
    event PlatformFeeUpdated(uint256 newFeeBps);

    constructor(
        address _feeRecipient,
        uint256 _platformFeeBps,
        address initialOwner
    ) Ownable(initialOwner) {
        require(_platformFeeBps <= 1000, "Fee too high"); // max 10%
        feeRecipient = _feeRecipient;
        platformFeeBps = _platformFeeBps;
    }

    function list(address nftContract, uint256 tokenId, uint256 price)
        external returns (uint256)
    {
        require(price > 0, "Price must be > 0");
        IERC721 nft = IERC721(nftContract);
        require(nft.ownerOf(tokenId) == msg.sender, "Not owner");
        require(
            nft.isApprovedForAll(msg.sender, address(this)) ||
            nft.getApproved(tokenId) == address(this),
            "Not approved"
        );

        uint256 listingId = _listingCounter++;
        listings[listingId] = Listing({
            seller: msg.sender,
            nftContract: nftContract,
            tokenId: tokenId,
            price: price,
            active: true
        });

        emit Listed(listingId, msg.sender, nftContract, tokenId, price);
        return listingId;
    }

    function buy(uint256 listingId) external payable nonReentrant {
        Listing storage listing = listings[listingId];
        require(listing.active, "Not active");
        require(msg.value >= listing.price, "Insufficient payment");

        listing.active = false;

        // Platform fee
        uint256 platformFee = (listing.price * platformFeeBps) / 10000;

        // Royalty (ERC-2981)
        uint256 royaltyAmount = 0;
        address royaltyRecipient;
        try IERC2981(listing.nftContract).royaltyInfo(listing.tokenId, listing.price)
            returns (address receiver, uint256 amount)
        {
            royaltyRecipient = receiver;
            royaltyAmount = amount;
        } catch {}

        // Seller proceeds
        uint256 sellerProceeds = listing.price - platformFee - royaltyAmount;

        // Transfer NFT
        IERC721(listing.nftContract).safeTransferFrom(listing.seller, msg.sender, listing.tokenId);

        // Distribute payments
        payable(feeRecipient).transfer(platformFee);
        if (royaltyAmount > 0 && royaltyRecipient != address(0)) {
            payable(royaltyRecipient).transfer(royaltyAmount);
        }
        payable(listing.seller).transfer(sellerProceeds);

        // Refund excess
        if (msg.value > listing.price) {
            payable(msg.sender).transfer(msg.value - listing.price);
        }

        emit Sold(listingId, msg.sender, listing.price);
    }

    function cancel(uint256 listingId) external {
        Listing storage listing = listings[listingId];
        require(listing.seller == msg.sender, "Not seller");
        require(listing.active, "Not active");
        listing.active = false;
        emit Cancelled(listingId);
    }

    function setFeeRecipient(address _feeRecipient) external onlyOwner {
        feeRecipient = _feeRecipient;
    }

    function setPlatformFee(uint256 _platformFeeBps) external onlyOwner {
        require(_platformFeeBps <= 1000, "Fee too high");
        platformFeeBps = _platformFeeBps;
        emit PlatformFeeUpdated(_platformFeeBps);
    }
}
'''


def get_template(name: str) -> str | None:
    """Return a template by name, or ``None`` if unknown."""
    return TEMPLATES.get(name.lower())


def list_templates() -> list[str]:
    """Return sorted list of available template names."""
    return sorted(TEMPLATES.keys())
