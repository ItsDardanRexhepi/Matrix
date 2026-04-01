// SPDX-License-Identifier: MIT
pragma solidity ^0.8.20;

import "@openzeppelin/contracts/token/ERC20/IERC20.sol";
import "@openzeppelin/contracts/token/ERC20/utils/SafeERC20.sol";
import "@openzeppelin/contracts/utils/ReentrancyGuard.sol";
import "@openzeppelin/contracts/access/Ownable.sol";

/**
 * @title OpenMatrixDEX
 * @notice Constant product AMM with zero fees to users.
 *         Platform absorbs gas costs.  x * y = k invariant.
 */
contract OpenMatrixDEX is ReentrancyGuard, Ownable {
    using SafeERC20 for IERC20;

    // ---------------------------------------------------------------
    // Structs
    // ---------------------------------------------------------------
    struct Pool {
        address tokenA;
        address tokenB;
        uint256 reserveA;
        uint256 reserveB;
        uint256 totalLiquidity;
        mapping(address => uint256) liquidity;
    }

    // ---------------------------------------------------------------
    // State
    // ---------------------------------------------------------------
    address public platformFeeRecipient; // NeoSafe — absorbs gas, no swap fees

    uint256 private _nextPoolId;
    mapping(uint256 => Pool) private _pools;
    mapping(bytes32 => uint256) public pairToPool; // keccak(tokenA, tokenB) => poolId + 1

    // ---------------------------------------------------------------
    // Events
    // ---------------------------------------------------------------
    event PoolCreated(uint256 indexed poolId, address tokenA, address tokenB);
    event LiquidityAdded(uint256 indexed poolId, address indexed provider, uint256 amountA, uint256 amountB, uint256 liquidity);
    event LiquidityRemoved(uint256 indexed poolId, address indexed provider, uint256 amountA, uint256 amountB, uint256 liquidity);
    event Swap(uint256 indexed poolId, address indexed user, address tokenIn, uint256 amountIn, address tokenOut, uint256 amountOut);

    // ---------------------------------------------------------------
    // Constructor
    // ---------------------------------------------------------------
    constructor(address _platformFeeRecipient) Ownable(msg.sender) {
        require(_platformFeeRecipient != address(0), "Zero fee recipient");
        platformFeeRecipient = _platformFeeRecipient;
    }

    // ---------------------------------------------------------------
    // Pool management
    // ---------------------------------------------------------------

    function _pairKey(address tokenA, address tokenB) internal pure returns (bytes32) {
        (address t0, address t1) = tokenA < tokenB ? (tokenA, tokenB) : (tokenB, tokenA);
        return keccak256(abi.encodePacked(t0, t1));
    }

    /**
     * @notice Create a new liquidity pool for a token pair.
     */
    function createPool(
        address tokenA,
        address tokenB,
        uint256 amountA,
        uint256 amountB
    ) external nonReentrant returns (uint256 poolId) {
        require(tokenA != tokenB, "Identical tokens");
        require(tokenA != address(0) && tokenB != address(0), "Zero address");
        require(amountA > 0 && amountB > 0, "Zero amounts");

        bytes32 key = _pairKey(tokenA, tokenB);
        require(pairToPool[key] == 0, "Pool exists");

        poolId = _nextPoolId++;
        Pool storage pool = _pools[poolId];
        pool.tokenA = tokenA < tokenB ? tokenA : tokenB;
        pool.tokenB = tokenA < tokenB ? tokenB : tokenA;

        // Normalise amounts to match sorted order
        (uint256 sortedA, uint256 sortedB) = tokenA < tokenB
            ? (amountA, amountB)
            : (amountB, amountA);

        IERC20(pool.tokenA).safeTransferFrom(msg.sender, address(this), sortedA);
        IERC20(pool.tokenB).safeTransferFrom(msg.sender, address(this), sortedB);

        pool.reserveA = sortedA;
        pool.reserveB = sortedB;

        uint256 liq = _sqrt(sortedA * sortedB);
        pool.totalLiquidity = liq;
        pool.liquidity[msg.sender] = liq;

        pairToPool[key] = poolId + 1; // store poolId+1 so 0 means "no pool"

        emit PoolCreated(poolId, pool.tokenA, pool.tokenB);
        emit LiquidityAdded(poolId, msg.sender, sortedA, sortedB, liq);
    }

    /**
     * @notice Add liquidity to an existing pool.
     */
    function addLiquidity(
        uint256 poolId,
        uint256 amountADesired,
        uint256 amountBDesired
    ) external nonReentrant returns (uint256 liquidity) {
        Pool storage pool = _pools[poolId];
        require(pool.reserveA > 0, "Pool not initialised");

        // Maintain ratio
        uint256 amountB = (amountADesired * pool.reserveB) / pool.reserveA;
        uint256 amountA = amountADesired;
        if (amountB > amountBDesired) {
            amountA = (amountBDesired * pool.reserveA) / pool.reserveB;
            amountB = amountBDesired;
        }

        require(amountA > 0 && amountB > 0, "Zero liquidity");

        IERC20(pool.tokenA).safeTransferFrom(msg.sender, address(this), amountA);
        IERC20(pool.tokenB).safeTransferFrom(msg.sender, address(this), amountB);

        liquidity = (amountA * pool.totalLiquidity) / pool.reserveA;

        pool.reserveA += amountA;
        pool.reserveB += amountB;
        pool.totalLiquidity += liquidity;
        pool.liquidity[msg.sender] += liquidity;

        emit LiquidityAdded(poolId, msg.sender, amountA, amountB, liquidity);
    }

    /**
     * @notice Remove liquidity from a pool.
     */
    function removeLiquidity(uint256 poolId, uint256 liquidityAmount)
        external
        nonReentrant
        returns (uint256 amountA, uint256 amountB)
    {
        Pool storage pool = _pools[poolId];
        require(pool.liquidity[msg.sender] >= liquidityAmount, "Insufficient liquidity");
        require(liquidityAmount > 0, "Zero amount");

        amountA = (liquidityAmount * pool.reserveA) / pool.totalLiquidity;
        amountB = (liquidityAmount * pool.reserveB) / pool.totalLiquidity;

        pool.liquidity[msg.sender] -= liquidityAmount;
        pool.totalLiquidity -= liquidityAmount;
        pool.reserveA -= amountA;
        pool.reserveB -= amountB;

        IERC20(pool.tokenA).safeTransfer(msg.sender, amountA);
        IERC20(pool.tokenB).safeTransfer(msg.sender, amountB);

        emit LiquidityRemoved(poolId, msg.sender, amountA, amountB, liquidityAmount);
    }

    // ---------------------------------------------------------------
    // Swap — zero fee to user
    // ---------------------------------------------------------------

    /**
     * @notice Swap tokens with zero fees.  Uses constant product formula.
     * @param poolId    The liquidity pool.
     * @param tokenIn   Address of the input token.
     * @param amountIn  Amount of input token.
     * @return amountOut Amount of output token received.
     */
    function swap(
        uint256 poolId,
        address tokenIn,
        uint256 amountIn
    ) external nonReentrant returns (uint256 amountOut) {
        Pool storage pool = _pools[poolId];
        require(amountIn > 0, "Zero input");
        require(
            tokenIn == pool.tokenA || tokenIn == pool.tokenB,
            "Token not in pool"
        );

        bool isAtoB = tokenIn == pool.tokenA;
        (uint256 reserveIn, uint256 reserveOut) = isAtoB
            ? (pool.reserveA, pool.reserveB)
            : (pool.reserveB, pool.reserveA);

        // Constant product: amountOut = reserveOut - (reserveIn * reserveOut) / (reserveIn + amountIn)
        // Zero fee: no fee deduction from amountIn
        amountOut = (amountIn * reserveOut) / (reserveIn + amountIn);
        require(amountOut > 0, "Insufficient output");
        require(amountOut < reserveOut, "Exceeds reserves");

        IERC20(tokenIn).safeTransferFrom(msg.sender, address(this), amountIn);

        address tokenOut = isAtoB ? pool.tokenB : pool.tokenA;
        IERC20(tokenOut).safeTransfer(msg.sender, amountOut);

        if (isAtoB) {
            pool.reserveA += amountIn;
            pool.reserveB -= amountOut;
        } else {
            pool.reserveB += amountIn;
            pool.reserveA -= amountOut;
        }

        emit Swap(poolId, msg.sender, tokenIn, amountIn, tokenOut, amountOut);
    }

    // ---------------------------------------------------------------
    // View
    // ---------------------------------------------------------------

    function getReserves(uint256 poolId) external view returns (uint256, uint256) {
        return (_pools[poolId].reserveA, _pools[poolId].reserveB);
    }

    function getQuote(uint256 poolId, address tokenIn, uint256 amountIn)
        external
        view
        returns (uint256 amountOut)
    {
        Pool storage pool = _pools[poolId];
        bool isAtoB = tokenIn == pool.tokenA;
        (uint256 reserveIn, uint256 reserveOut) = isAtoB
            ? (pool.reserveA, pool.reserveB)
            : (pool.reserveB, pool.reserveA);
        amountOut = (amountIn * reserveOut) / (reserveIn + amountIn);
    }

    function getUserLiquidity(uint256 poolId, address user) external view returns (uint256) {
        return _pools[poolId].liquidity[user];
    }

    // ---------------------------------------------------------------
    // Internal
    // ---------------------------------------------------------------

    function _sqrt(uint256 x) internal pure returns (uint256 y) {
        if (x == 0) return 0;
        uint256 z = (x + 1) / 2;
        y = x;
        while (z < y) {
            y = z;
            z = (x / z + z) / 2;
        }
    }
}
