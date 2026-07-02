// SPDX-License-Identifier: MIT
pragma solidity ^0.8.20;

import "forge-std/Test.sol";
import "../OpenMatrixVerifyingPaymaster.sol";
import "account-abstraction/interfaces/IEntryPoint.sol";
import "account-abstraction/interfaces/UserOperation.sol";
import "@openzeppelin/contracts/utils/cryptography/MessageHashUtils.sol";

/// The test contract stands in as the EntryPoint (paymaster.entryPoint == this),
/// so it may call validatePaymasterUserOp directly.
contract OpenMatrixVerifyingPaymasterTest is Test {
    OpenMatrixVerifyingPaymaster internal pm;
    uint256 internal signerPk = 0xA11CE;   // known key -> known verifyingSigner
    address internal signer;
    address internal owner = address(0x0011);

    // ── Fixed vector inputs (must equal tests/test_paymaster_digest.py) ──
    address internal constant V_SENDER = 0x000000000000000000000000000000000000dEaD;
    uint256 internal constant V_NONCE = 7;
    bytes32 internal constant V_INITCODE_HASH = keccak256("");        // empty initCode
    bytes32 internal constant V_CALLDATA_HASH = keccak256(hex"010203");
    uint256 internal constant V_CGL = 100000;
    uint256 internal constant V_VGL = 200000;
    uint256 internal constant V_PVG = 21000;
    uint256 internal constant V_MFPG = 1000000000;
    uint256 internal constant V_MPFPG = 1000000000;
    uint256 internal constant V_CHAINID = 84532;                     // Base Sepolia
    address internal constant V_PAYMASTER = 0x00000000000000000000000000000000caFe0001;
    uint48 internal constant V_VALID_UNTIL = 2000000000;
    uint48 internal constant V_VALID_AFTER = 1000000000;

    function setUp() public {
        signer = vm.addr(signerPk);
        pm = new OpenMatrixVerifyingPaymaster(IEntryPoint(address(this)), signer, owner);
    }

    /// HARD-GATE VECTOR: the digest for the fixed inputs above. The Python signer
    /// (tests/test_paymaster_digest.py) must reproduce this exact bytes32.
    function test_digest_vector() public view {
        bytes32 d = pm.digest(OpenMatrixVerifyingPaymaster.DigestInput({
            sender: V_SENDER, nonce: V_NONCE,
            initCodeHash: V_INITCODE_HASH, callDataHash: V_CALLDATA_HASH,
            callGasLimit: V_CGL, verificationGasLimit: V_VGL, preVerificationGas: V_PVG,
            maxFeePerGas: V_MFPG, maxPriorityFeePerGas: V_MPFPG,
            chainId: V_CHAINID, paymaster: V_PAYMASTER,
            validUntil: V_VALID_UNTIL, validAfter: V_VALID_AFTER
        }));
        console2.logBytes32(d);
        // Pinned vector — the Python signer (tests/test_paymaster_digest.py)
        // reproduces this exact bytes32 independently (hard cross-test gate).
        assertEq(d, 0x978d6c5d7846b0d99849405a912ceaeef2e8cfc6059f1befa7f0a7a6e273c3a4);
    }

    function _userOp(bytes memory pnd) internal pure returns (UserOperation memory op) {
        op.sender = V_SENDER;
        op.nonce = V_NONCE;
        op.initCode = "";
        op.callData = hex"010203";
        op.callGasLimit = V_CGL;
        op.verificationGasLimit = V_VGL;
        op.preVerificationGas = V_PVG;
        op.maxFeePerGas = V_MFPG;
        op.maxPriorityFeePerGas = V_MPFPG;
        op.paymasterAndData = pnd;
        op.signature = "";
    }

    function _sign(uint256 pk, UserOperation memory op) internal view returns (bytes memory) {
        bytes32 h = MessageHashUtils.toEthSignedMessageHash(
            pm.getHash(op, V_VALID_UNTIL, V_VALID_AFTER));
        (uint8 v, bytes32 r, bytes32 s) = vm.sign(pk, h);
        return abi.encodePacked(r, s, v);
    }

    function _pnd(bytes memory sig) internal view returns (bytes memory) {
        return abi.encodePacked(address(pm), abi.encode(V_VALID_UNTIL, V_VALID_AFTER), sig);
    }

    function test_valid_signature_accepted() public {
        // Two-pass: build op with empty pnd sig region sized correctly, sign, rebuild.
        UserOperation memory tmp = _userOp(_pnd(new bytes(65)));
        bytes memory sig = _sign(signerPk, tmp);
        UserOperation memory op = _userOp(_pnd(sig));
        (, uint256 validationData) = pm.validatePaymasterUserOp(op, bytes32(0), 0);
        // low bit (sigFailed) must be 0
        assertEq(validationData & 1, 0, "valid paymaster sig must pass");
    }

    function test_wrong_signer_rejected() public {
        uint256 wrongPk = 0xB0B;
        UserOperation memory tmp = _userOp(_pnd(new bytes(65)));
        bytes memory sig = _sign(wrongPk, tmp);
        UserOperation memory op = _userOp(_pnd(sig));
        (, uint256 validationData) = pm.validatePaymasterUserOp(op, bytes32(0), 0);
        assertEq(validationData & 1, 1, "wrong signer must set sigFailed bit");
    }

    function test_only_entrypoint_can_validate() public {
        UserOperation memory op = _userOp(_pnd(new bytes(65)));
        vm.prank(address(0xBAD));
        vm.expectRevert(bytes("OMVP: not EntryPoint"));
        pm.validatePaymasterUserOp(op, bytes32(0), 0);
    }
}
