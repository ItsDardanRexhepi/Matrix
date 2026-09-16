// SPDX-License-Identifier: MIT
pragma solidity ^0.8.20;

import "account-abstraction/interfaces/IAccount.sol";
import "account-abstraction/interfaces/IEntryPoint.sol";
import "account-abstraction/core/Helpers.sol";
import "./P256.sol";

// ERC-4337 v0.6 sig-failure sentinel (matches BaseAccount's constant; we don't
// extend BaseAccount to avoid its OZ-v4 dependency chain).
uint256 constant SIG_VALIDATION_FAILED = 1;

/// @title MatrixAccount
/// @notice ERC-4337 v0.6 smart account owned by a P-256 (secp256r1) PUBLIC KEY —
/// the key Apple's Secure Enclave holds — with guardian social recovery.
///
/// WHY THE OWNER IS A PUBLIC KEY AND NOT AN ADDRESS. MTRX signs every
/// UserOperation with a Secure Enclave key. The Secure Enclave signs P-256 and
/// physically cannot produce the secp256k1 signatures `ecrecover` verifies, so
/// an account that validated with `ECDSA.recover` against an `address owner`
/// could never validate a signature this app produced. That is what this
/// contract used to do. The two are different elliptic curves, not two
/// encodings of one signature, and no client-side re-encoding bridges them: the
/// account had to move to the curve the hardware signs on.
///
/// The consequence is that the owner has NO ETHEREUM ADDRESS. A P-256 key cannot
/// send a transaction, pay gas, or be an `msg.sender`. So the owner-authorised
/// functions below are `onlySelf`: they are reachable only by the account
/// calling itself, which happens when the EntryPoint runs a UserOperation this
/// account's owner key signed. The authorisation is the SAME — a valid P-256
/// signature from the owner — it simply arrives through the EntryPoint rather
/// than from an EOA. `onlyEntryPointOrOwner` is gone because the second half of
/// it cannot exist.
///
/// WHAT IS SIGNED, exactly, because a mismatch here validates nothing:
///
///     userOpHash = keccak256(abi.encode(hash(userOp), entryPoint, chainId))   (EntryPoint)
///     digest     = sha256(userOpHash)                                          (CryptoKit)
///     signature  = P-256 ECDSA over `digest`, sent as RAW r ‖ s, 64 bytes
///
/// The sha256 is not decoration. CryptoKit's `signature(for:)` hashes its input
/// with SHA-256 before signing, so the enclave signs sha256(userOpHash) whether
/// or not the caller meant it to. The contract hashes the same way or nothing
/// verifies. The client must also send the RAW 64-byte representation rather
/// than CryptoKit's DER default, and must normalise s to the low half — P256
/// rejects the high-s form to keep signatures non-malleable.
///
/// The account never custodies platform funds. Only the owner key controls it;
/// the platform paymaster is a separate contract and only sponsors gas.
contract MatrixAccount is IAccount {
    /// @notice The owner's P-256 public key.
    uint256 public ownerX;
    uint256 public ownerY;

    /// @notice A P-256 verifier contract for chains without the RIP-7212
    /// precompile. address(0) means "precompile only". Immutable: a swappable
    /// verifier would be a swappable definition of a valid signature.
    address public immutable p256Verifier;

    IEntryPoint private immutable _entryPoint;

    // ── Guardian recovery ────────────────────────────────────────────────
    uint256 public constant RECOVERY_TIMELOCK = 48 hours;

    address[] public guardians;
    mapping(address => bool) public isGuardian;
    uint256 public recoveryThreshold;

    struct Recovery {
        uint256 proposedOwnerX;
        uint256 proposedOwnerY;
        uint256 executeAfter;   // 0 = no active recovery
        uint256 supportCount;
    }
    Recovery public recovery;
    mapping(address => bool) private _supportedCurrent; // guardian -> supported this round

    event MatrixAccountInitialized(IEntryPoint indexed entryPoint, uint256 ownerX, uint256 ownerY);
    event GuardiansUpdated(address[] guardians, uint256 threshold);
    event RecoveryInitiated(uint256 proposedOwnerX, uint256 proposedOwnerY, uint256 executeAfter);
    event RecoverySupported(address indexed guardian, uint256 supportCount);
    event RecoveryExecuted(uint256 oldOwnerX, uint256 oldOwnerY, uint256 newOwnerX, uint256 newOwnerY);
    event RecoveryCancelled();

    /// @dev The owner has no address, so "the owner is acting" means "this
    /// account is calling itself", which only happens via a UserOperation the
    /// owner key signed and the EntryPoint validated.
    modifier onlySelf() {
        require(msg.sender == address(this), "MA: not owner (call via EntryPoint)");
        _;
    }
    modifier onlyEntryPointOrSelf() {
        require(
            msg.sender == address(_entryPoint) || msg.sender == address(this),
            "MA: not EntryPoint"
        );
        _;
    }
    modifier onlyGuardian() {
        require(isGuardian[msg.sender], "MA: not guardian");
        _;
    }

    constructor(IEntryPoint anEntryPoint, uint256 anOwnerX, uint256 anOwnerY, address aVerifier) {
        require(anOwnerX != 0 || anOwnerY != 0, "MA: zero owner key");
        _entryPoint = anEntryPoint;
        ownerX = anOwnerX;
        ownerY = anOwnerY;
        p256Verifier = aVerifier;
        emit MatrixAccountInitialized(anEntryPoint, anOwnerX, anOwnerY);
    }

    receive() external payable {}

    function entryPoint() public view returns (IEntryPoint) {
        return _entryPoint;
    }

    // ── Execution (EntryPoint-driven) ────────────────────────────────────

    function execute(address dest, uint256 value, bytes calldata func) external onlyEntryPointOrSelf {
        (bool ok, bytes memory ret) = dest.call{value: value}(func);
        if (!ok) {
            assembly { revert(add(ret, 32), mload(ret)) }
        }
    }

    /// @notice Execute several calls in one operation, each able to send value.
    ///
    /// THE SIGNATURE CARRIES `value` BECAUSE THE CLIENT ALWAYS SENT IT. MTRX
    /// encodes `executeBatch(address[],uint256[],bytes[])` — DAOManager and
    /// NFTManager both build batches that way — while this contract implemented
    /// `executeBatch(address[],bytes[])`. Those are different selectors, so
    /// every batched operation the app produced would have hit no function here
    /// at all, and a batch that could not carry value could not have paid for
    /// the calls it made. The contract is brought up to what the app needs
    /// rather than the app cut down to what the contract had.
    function executeBatch(
        address[] calldata dest,
        uint256[] calldata value,
        bytes[] calldata func
    ) external onlyEntryPointOrSelf {
        require(dest.length == func.length && dest.length == value.length, "MA: length mismatch");
        for (uint256 i = 0; i < dest.length; i++) {
            (bool ok, bytes memory ret) = dest[i].call{value: value[i]}(func[i]);
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
        require(msg.sender == address(_entryPoint), "MA: not EntryPoint");

        // A 64-byte raw (r, s). A wrong length is a malformed signature, not a
        // reverting account: reverting inside validateUserOp makes the whole
        // bundle fail rather than this one operation.
        if (userOp.signature.length != 64) {
            validationData = SIG_VALIDATION_FAILED;
        } else {
            uint256 r = uint256(bytes32(userOp.signature[0:32]));
            uint256 s = uint256(bytes32(userOp.signature[32:64]));
            // sha256, because CryptoKit hashes before it signs. See the note on
            // the contract.
            bytes32 digest = sha256(abi.encodePacked(userOpHash));
            if (!P256.verify(digest, r, s, ownerX, ownerY, p256Verifier)) {
                validationData = SIG_VALIDATION_FAILED;
            }
        }

        // Repay the EntryPoint for missing prefund (owner's funds, not custodial).
        if (missingAccountFunds > 0) {
            (bool ok,) = payable(msg.sender).call{value: missingAccountFunds}("");
            (ok);
        }
    }

    // ── Guardian recovery ────────────────────────────────────────────────

    function setGuardians(address[] calldata newGuardians, uint256 threshold) external onlySelf {
        require(threshold > 0 && threshold <= newGuardians.length, "MA: bad threshold");
        for (uint256 i = 0; i < guardians.length; i++) {
            isGuardian[guardians[i]] = false;
        }
        delete guardians;
        for (uint256 i = 0; i < newGuardians.length; i++) {
            address g = newGuardians[i];
            require(g != address(0) && g != address(this) && !isGuardian[g], "MA: bad guardian");
            isGuardian[g] = true;
            guardians.push(g);
        }
        recoveryThreshold = threshold;
        _resetRecovery();
        emit GuardiansUpdated(newGuardians, threshold);
    }

    /// @notice Propose a new owner PUBLIC KEY. Recovery rotates to another
    /// P-256 key — a fresh Secure Enclave key on the user's new device — not to
    /// an address, for the same reason the owner is a key at all.
    function initiateRecovery(uint256 proposedOwnerX, uint256 proposedOwnerY) external onlyGuardian {
        require(proposedOwnerX != 0 || proposedOwnerY != 0, "MA: zero owner key");
        require(recoveryThreshold > 0, "MA: no guardians");
        _clearSupport();
        recovery = Recovery({
            proposedOwnerX: proposedOwnerX,
            proposedOwnerY: proposedOwnerY,
            executeAfter: block.timestamp + RECOVERY_TIMELOCK,
            supportCount: 1
        });
        _supportedCurrent[msg.sender] = true;
        emit RecoveryInitiated(proposedOwnerX, proposedOwnerY, recovery.executeAfter);
        emit RecoverySupported(msg.sender, 1);
    }

    function supportRecovery() external onlyGuardian {
        require(recovery.executeAfter != 0, "MA: no recovery");
        require(!_supportedCurrent[msg.sender], "MA: already supported");
        _supportedCurrent[msg.sender] = true;
        recovery.supportCount += 1;
        emit RecoverySupported(msg.sender, recovery.supportCount);
    }

    function executeRecovery() external {
        require(recovery.executeAfter != 0, "MA: no recovery");
        require(block.timestamp >= recovery.executeAfter, "MA: timelock");
        require(recovery.supportCount >= recoveryThreshold, "MA: threshold not met");
        uint256 oldX = ownerX;
        uint256 oldY = ownerY;
        ownerX = recovery.proposedOwnerX;
        ownerY = recovery.proposedOwnerY;
        _resetRecovery();
        emit RecoveryExecuted(oldX, oldY, ownerX, ownerY);
    }

    function cancelRecovery() external onlySelf {
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
