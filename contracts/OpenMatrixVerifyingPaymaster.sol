// SPDX-License-Identifier: MIT
pragma solidity ^0.8.20;

import "account-abstraction/interfaces/IPaymaster.sol";
import "account-abstraction/interfaces/IEntryPoint.sol";
import "account-abstraction/core/Helpers.sol";
import "@openzeppelin/contracts/access/Ownable.sol";
import "@openzeppelin/contracts/utils/cryptography/ECDSA.sol";
import "@openzeppelin/contracts/utils/cryptography/MessageHashUtils.sol";

/// @title OpenMatrixVerifyingPaymaster
/// @notice ERC-4337 v0.6 verifying paymaster. The platform's off-chain signer
/// (server, `POST /api/v1/paymaster/sign`) approves gas sponsorship by signing a
/// digest over the UserOperation's material fields; the paymaster validates that
/// signature on-chain. Non-custodial: the paymaster only pays gas from its own
/// EntryPoint deposit — it never touches user funds and never signs anything the
/// account does.
///
/// paymasterAndData layout (matches the client + WalletTests):
///   [0:20]   address(this)
///   [20:84]  abi.encode(uint48 validUntil, uint48 validAfter)
///   [84:]    signature (65 bytes) over toEthSignedMessageHash(digest(...))
///
/// The digest uses EXPLICIT fields (not a calldata-slice) so the server can mirror
/// it byte-for-byte with eth_abi — see tests/test_paymaster_digest.py, gated by a
/// foundry-produced vector.
contract OpenMatrixVerifyingPaymaster is IPaymaster, Ownable {
    using ECDSA for bytes32;

    IEntryPoint public immutable entryPoint;
    address public verifyingSigner;

    uint256 private constant VALID_TIMESTAMP_OFFSET = 20;
    uint256 private constant SIGNATURE_OFFSET = 84;

    /// Explicit digest inputs (a struct keeps the digest() signature to one stack
    /// slot — the legacy codegen, via_ir=false, can't take 13 loose params).
    struct DigestInput {
        address sender;
        uint256 nonce;
        bytes32 initCodeHash;
        bytes32 callDataHash;
        uint256 callGasLimit;
        uint256 verificationGasLimit;
        uint256 preVerificationGas;
        uint256 maxFeePerGas;
        uint256 maxPriorityFeePerGas;
        uint256 chainId;
        address paymaster;
        uint48 validUntil;
        uint48 validAfter;
    }

    event VerifyingSignerChanged(address indexed newSigner);

    constructor(IEntryPoint _entryPoint, address _verifyingSigner, address _owner) Ownable(_owner) {
        entryPoint = _entryPoint;
        verifyingSigner = _verifyingSigner;
    }

    function setVerifyingSigner(address newSigner) external onlyOwner {
        require(newSigner != address(0), "OMVP: zero signer");
        verifyingSigner = newSigner;
        emit VerifyingSignerChanged(newSigner);
    }

    /// Explicit-field digest, TWO-LEVEL to stay within the legacy codegen's stack
    /// (via_ir is false repo-wide). Deterministic and server-reproducible:
    ///   opHash = keccak256(abi.encode(sender, nonce, initCodeHash, callDataHash,
    ///                                 callGasLimit, verificationGasLimit,
    ///                                 preVerificationGas, maxFeePerGas,
    ///                                 maxPriorityFeePerGas))
    ///   digest = keccak256(abi.encode(opHash, chainId, paymaster,
    ///                                 validUntil, validAfter))
    function digest(DigestInput memory d) public pure returns (bytes32) {
        bytes32 opHash = keccak256(abi.encode(
            d.sender, d.nonce, d.initCodeHash, d.callDataHash,
            d.callGasLimit, d.verificationGasLimit, d.preVerificationGas,
            d.maxFeePerGas, d.maxPriorityFeePerGas
        ));
        return keccak256(abi.encode(opHash, d.chainId, d.paymaster, d.validUntil, d.validAfter));
    }

    function getHash(UserOperation calldata userOp, uint48 validUntil, uint48 validAfter)
        public
        view
        returns (bytes32)
    {
        return digest(DigestInput({
            sender: userOp.sender,
            nonce: userOp.nonce,
            initCodeHash: keccak256(userOp.initCode),
            callDataHash: keccak256(userOp.callData),
            callGasLimit: userOp.callGasLimit,
            verificationGasLimit: userOp.verificationGasLimit,
            preVerificationGas: userOp.preVerificationGas,
            maxFeePerGas: userOp.maxFeePerGas,
            maxPriorityFeePerGas: userOp.maxPriorityFeePerGas,
            chainId: block.chainid,
            paymaster: address(this),
            validUntil: validUntil,
            validAfter: validAfter
        }));
    }

    function parsePaymasterAndData(bytes calldata paymasterAndData)
        public
        pure
        returns (uint48 validUntil, uint48 validAfter, bytes calldata signature)
    {
        (validUntil, validAfter) = abi.decode(
            paymasterAndData[VALID_TIMESTAMP_OFFSET:SIGNATURE_OFFSET], (uint48, uint48));
        signature = paymasterAndData[SIGNATURE_OFFSET:];
    }

    function validatePaymasterUserOp(UserOperation calldata userOp, bytes32, uint256)
        external
        view
        override
        returns (bytes memory context, uint256 validationData)
    {
        require(msg.sender == address(entryPoint), "OMVP: not EntryPoint");
        (uint48 validUntil, uint48 validAfter, bytes calldata signature) =
            parsePaymasterAndData(userOp.paymasterAndData);
        require(signature.length == 64 || signature.length == 65,
            "OMVP: invalid signature length");
        bytes32 hash = MessageHashUtils.toEthSignedMessageHash(getHash(userOp, validUntil, validAfter));
        // Do NOT revert on a bad signature — return the SIG-failed validation bit
        // so the EntryPoint reports it cleanly.
        if (verifyingSigner != ECDSA.recover(hash, signature)) {
            return ("", _packValidationData(true, validUntil, validAfter));
        }
        return ("", _packValidationData(false, validUntil, validAfter));
    }

    function postOp(PostOpMode, bytes calldata, uint256) external {
        require(msg.sender == address(entryPoint), "OMVP: not EntryPoint");
        // No post-op accounting needed for a pure gas sponsor.
    }

    // ── EntryPoint deposit / stake management (owner) ────────────────────
    function deposit() external payable {
        entryPoint.depositTo{value: msg.value}(address(this));
    }

    function getDeposit() external view returns (uint256) {
        return entryPoint.balanceOf(address(this));
    }

    function withdrawTo(address payable to, uint256 amount) external onlyOwner {
        entryPoint.withdrawTo(to, amount);
    }

    function addStake(uint32 unstakeDelaySec) external payable onlyOwner {
        entryPoint.addStake{value: msg.value}(unstakeDelaySec);
    }

    function unlockStake() external onlyOwner {
        entryPoint.unlockStake();
    }

    function withdrawStake(address payable to) external onlyOwner {
        entryPoint.withdrawStake(to);
    }
}
