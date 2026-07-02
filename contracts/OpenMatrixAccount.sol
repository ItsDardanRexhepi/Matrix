// SPDX-License-Identifier: MIT
pragma solidity ^0.8.20;

import "account-abstraction/interfaces/IAccount.sol";
import "account-abstraction/interfaces/IEntryPoint.sol";
import "account-abstraction/core/Helpers.sol";
import "@openzeppelin/contracts/utils/cryptography/ECDSA.sol";
import "@openzeppelin/contracts/utils/cryptography/MessageHashUtils.sol";

// ERC-4337 v0.6 sig-failure sentinel (matches BaseAccount's constant; we don't
// extend BaseAccount to avoid its OZ-v4 dependency chain).
uint256 constant SIG_VALIDATION_FAILED = 1;

/// @title OpenMatrixAccount
/// @notice ERC-4337 v0.6 smart account (SimpleAccount semantics) with owner-key
/// signing plus first-class GUARDIAN SOCIAL RECOVERY: a threshold of guardians can
/// rotate the owner after a 48h timelock. Non-upgradeable (no proxy) to keep the
/// recovery surface auditable. The account never custodies platform funds — only
/// the user's own owner key controls it; the platform paymaster (separate contract)
/// only sponsors gas.
contract OpenMatrixAccount is IAccount {
    using ECDSA for bytes32;

    address public owner;
    IEntryPoint private immutable _entryPoint;

    // ── Guardian recovery ────────────────────────────────────────────────
    uint256 public constant RECOVERY_TIMELOCK = 48 hours;

    address[] public guardians;
    mapping(address => bool) public isGuardian;
    uint256 public recoveryThreshold;

    struct Recovery {
        address proposedOwner;
        uint256 executeAfter;   // 0 = no active recovery
        uint256 supportCount;
    }
    Recovery public recovery;
    mapping(address => bool) private _supportedCurrent; // guardian -> supported this round

    event OpenMatrixAccountInitialized(IEntryPoint indexed entryPoint, address indexed owner);
    event GuardiansUpdated(address[] guardians, uint256 threshold);
    event RecoveryInitiated(address indexed proposedOwner, uint256 executeAfter);
    event RecoverySupported(address indexed guardian, uint256 supportCount);
    event RecoveryExecuted(address indexed oldOwner, address indexed newOwner);
    event RecoveryCancelled();

    modifier onlyOwner() {
        require(msg.sender == owner, "OMA: not owner");
        _;
    }
    modifier onlyEntryPointOrOwner() {
        require(msg.sender == address(_entryPoint) || msg.sender == owner, "OMA: not EntryPoint/owner");
        _;
    }
    modifier onlyGuardian() {
        require(isGuardian[msg.sender], "OMA: not guardian");
        _;
    }

    constructor(IEntryPoint anEntryPoint, address anOwner) {
        _entryPoint = anEntryPoint;
        owner = anOwner;
        emit OpenMatrixAccountInitialized(anEntryPoint, anOwner);
    }

    receive() external payable {}

    function entryPoint() public view returns (IEntryPoint) {
        return _entryPoint;
    }

    // ── Execution (EntryPoint-driven) ────────────────────────────────────

    function execute(address dest, uint256 value, bytes calldata func) external onlyEntryPointOrOwner {
        (bool ok, bytes memory ret) = dest.call{value: value}(func);
        if (!ok) {
            assembly { revert(add(ret, 32), mload(ret)) }
        }
    }

    function executeBatch(address[] calldata dest, bytes[] calldata func) external onlyEntryPointOrOwner {
        require(dest.length == func.length, "OMA: wrong array lengths");
        for (uint256 i = 0; i < dest.length; i++) {
            (bool ok, bytes memory ret) = dest[i].call(func[i]);
            if (!ok) {
                assembly { revert(add(ret, 32), mload(ret)) }
            }
        }
    }

    // ── ERC-4337 validation ──────────────────────────────────────────────

    function validateUserOp(UserOperation calldata userOp, bytes32 userOpHash, uint256 missingAccountFunds)
        external
        override
        returns (uint256 validationData)
    {
        require(msg.sender == address(_entryPoint), "OMA: not EntryPoint");
        // Owner ECDSA signature over the EntryPoint-provided userOpHash.
        bytes32 hash = MessageHashUtils.toEthSignedMessageHash(userOpHash);
        if (owner != ECDSA.recover(hash, userOp.signature)) {
            validationData = SIG_VALIDATION_FAILED;
        }
        // Repay the EntryPoint for missing prefund (owner's funds, not custodial).
        if (missingAccountFunds > 0) {
            (bool ok,) = payable(msg.sender).call{value: missingAccountFunds}("");
            (ok);
        }
    }

    // ── Guardian recovery ────────────────────────────────────────────────

    function setGuardians(address[] calldata newGuardians, uint256 threshold) external onlyOwner {
        require(threshold > 0 && threshold <= newGuardians.length, "OMA: bad threshold");
        // clear old
        for (uint256 i = 0; i < guardians.length; i++) {
            isGuardian[guardians[i]] = false;
        }
        delete guardians;
        for (uint256 i = 0; i < newGuardians.length; i++) {
            address g = newGuardians[i];
            require(g != address(0) && g != owner && !isGuardian[g], "OMA: bad guardian");
            isGuardian[g] = true;
            guardians.push(g);
        }
        recoveryThreshold = threshold;
        _resetRecovery();
        emit GuardiansUpdated(newGuardians, threshold);
    }

    function initiateRecovery(address proposedOwner) external onlyGuardian {
        require(proposedOwner != address(0), "OMA: zero owner");
        require(recoveryThreshold > 0, "OMA: no guardians");
        _clearSupport();
        recovery = Recovery({
            proposedOwner: proposedOwner,
            executeAfter: block.timestamp + RECOVERY_TIMELOCK,
            supportCount: 1
        });
        _supportedCurrent[msg.sender] = true;
        emit RecoveryInitiated(proposedOwner, recovery.executeAfter);
        emit RecoverySupported(msg.sender, 1);
    }

    function supportRecovery() external onlyGuardian {
        require(recovery.executeAfter != 0, "OMA: no recovery");
        require(!_supportedCurrent[msg.sender], "OMA: already supported");
        _supportedCurrent[msg.sender] = true;
        recovery.supportCount += 1;
        emit RecoverySupported(msg.sender, recovery.supportCount);
    }

    function executeRecovery() external {
        require(recovery.executeAfter != 0, "OMA: no recovery");
        require(block.timestamp >= recovery.executeAfter, "OMA: timelock");
        require(recovery.supportCount >= recoveryThreshold, "OMA: threshold not met");
        address old = owner;
        owner = recovery.proposedOwner;
        _resetRecovery();
        emit RecoveryExecuted(old, owner);
    }

    function cancelRecovery() external onlyOwner {
        _resetRecovery();
        emit RecoveryCancelled();
    }

    function guardianCount() external view returns (uint256) {
        return guardians.length;
    }

    function _clearSupport() private {
        for (uint256 i = 0; i < guardians.length; i++) {
            _supportedCurrent[guardians[i]] = false;
        }
    }

    function _resetRecovery() private {
        _clearSupport();
        delete recovery;
    }
}
