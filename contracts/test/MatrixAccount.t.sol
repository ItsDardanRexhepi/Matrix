// SPDX-License-Identifier: MIT
pragma solidity ^0.8.20;

import "forge-std/Test.sol";
import "../MatrixAccount.sol";
import "../MatrixAccountFactory.sol";
import "../P256.sol";

/// A stand-in P-256 verifier. It answers 1 only for one exact 160-byte input,
/// so a test that passes proves the account built EXACTLY the right
/// (digest, r, s, x, y) — not merely that something returned true.
contract ExactInputVerifier {
    bytes public expected;
    constructor(bytes memory e) { expected = e; }
    fallback(bytes calldata input) external returns (bytes memory) {
        if (keccak256(input) == keccak256(expected)) return abi.encode(uint256(1));
        return "";
    }
}

/// Answers 1 to anything. Used only where the point of the test is something
/// other than the signature maths.
contract AlwaysValidVerifier {
    fallback(bytes calldata) external returns (bytes memory) {
        return abi.encode(uint256(1));
    }
}

contract MatrixAccountTest is Test {
    address constant ENTRY_POINT = address(0x5FF137D4b0FDCD49DcA30c7CF57E578a026d2789);

    // A NIST P-256 public key and signature are not needed to prove the wiring;
    // these are structurally valid field elements used as the owner key.
    uint256 constant OWNER_X = 0x1ccbe91c075fc7f4f033bfa248db8fccd3565de94bbfb12f3c59ff46c271bf83;
    uint256 constant OWNER_Y = 0xce4014c68811f9a21a1fdb2c0e6113e06db7ca93b7404e78dc7ccd5ca89a4ca9;

    MatrixAccountFactory factory;

    function setUp() public {
        factory = new MatrixAccountFactory(IEntryPoint(ENTRY_POINT), address(0));
    }

    // ── the account is owned by a key, not an address ────────────────────

    function test_OwnerIsAP256PublicKey() public {
        MatrixAccount a = factory.createAccount(OWNER_X, OWNER_Y, 0);
        assertEq(a.ownerX(), OWNER_X);
        assertEq(a.ownerY(), OWNER_Y);
    }

    function test_Factory_IsDeterministicAndIdempotent() public {
        address predicted = factory.getAddress(OWNER_X, OWNER_Y, 0);
        MatrixAccount a = factory.createAccount(OWNER_X, OWNER_Y, 0);
        assertEq(address(a), predicted, "getAddress must equal what createAccount deploys");
        MatrixAccount again = factory.createAccount(OWNER_X, OWNER_Y, 0);
        assertEq(address(again), predicted, "redeploy is a no-op");
    }

    function test_ADifferentKeyIsADifferentAccount() public {
        assertTrue(
            factory.getAddress(OWNER_X, OWNER_Y, 0) != factory.getAddress(OWNER_X, OWNER_Y + 1, 0),
            "the owner key must be part of the address derivation"
        );
    }

    function test_ZeroOwnerKeyIsRefused() public {
        vm.expectRevert(bytes("MA: zero owner key"));
        factory.createAccount(0, 0, 0);
    }

    // ── what is actually verified ────────────────────────────────────────

    /// THE CONTROL THIS FILE EXISTS FOR. The account must verify P-256 over
    /// sha256(userOpHash), with the owner's key — the exact thing the Secure
    /// Enclave produces. The verifier answers only for that one input, so if any
    /// component is wrong the signature fails.
    function test_ValidatesP256OverSha256OfTheUserOpHash() public {
        bytes32 userOpHash = keccak256("a user operation");
        uint256 r = 0x2ba3a8be6b94d5ec80a6d9d1190a436effe50d85a1eee859b8cc6af9bd5c2e18;
        uint256 s = 0x4cd60b855d442f5b3c7b11eb6c4e0ae7525fe710fab9aa7c77a67f79e6fadd76;

        bytes memory exact = abi.encodePacked(sha256(abi.encodePacked(userOpHash)), r, s, OWNER_X, OWNER_Y);
        ExactInputVerifier v = new ExactInputVerifier(exact);
        MatrixAccountFactory f = new MatrixAccountFactory(IEntryPoint(ENTRY_POINT), address(v));
        MatrixAccount a = f.createAccount(OWNER_X, OWNER_Y, 0);

        UserOperation memory op = _op(address(a), abi.encodePacked(bytes32(r), bytes32(s)));
        vm.prank(ENTRY_POINT);
        assertEq(a.validateUserOp(op, userOpHash, 0), 0, "a correct P-256 signature must validate");
    }

    function test_AKeccakDigestDoesNotValidate() public {
        // Guards the sha256 specifically: CryptoKit hashes with SHA-256 before
        // signing, so an account that verified over keccak256(userOpHash) — the
        // obvious Ethereum choice — would never validate a real enclave
        // signature. This fails if someone "simplifies" the digest.
        bytes32 userOpHash = keccak256("a user operation");
        uint256 r = 1234; uint256 s = 5678;
        bytes memory wrong = abi.encodePacked(keccak256(abi.encodePacked(userOpHash)), r, s, OWNER_X, OWNER_Y);
        ExactInputVerifier v = new ExactInputVerifier(wrong);
        MatrixAccountFactory f = new MatrixAccountFactory(IEntryPoint(ENTRY_POINT), address(v));
        MatrixAccount a = f.createAccount(OWNER_X, OWNER_Y, 0);

        UserOperation memory op = _op(address(a), abi.encodePacked(bytes32(r), bytes32(s)));
        vm.prank(ENTRY_POINT);
        assertEq(a.validateUserOp(op, userOpHash, 0), 1, "the digest must be sha256, not keccak256");
    }

    function test_NoVerifierAndNoPrecompileFailsClosed() public {
        MatrixAccount a = factory.createAccount(OWNER_X, OWNER_Y, 0);  // verifier == address(0)
        UserOperation memory op = _op(address(a), abi.encodePacked(uint256(1234), uint256(5678)));
        vm.prank(ENTRY_POINT);
        assertEq(a.validateUserOp(op, keccak256("x"), 0), 1,
            "an unverifiable signature must be refused, never passed");
    }

    function test_HighSIsRejectedForMalleability() public {
        AlwaysValidVerifier v = new AlwaysValidVerifier();
        MatrixAccountFactory f = new MatrixAccountFactory(IEntryPoint(ENTRY_POINT), address(v));
        MatrixAccount a = f.createAccount(OWNER_X, OWNER_Y, 0);
        // s just above n/2 — the mirror of a valid signature. Even with a
        // verifier that says yes to everything, P256 must refuse it.
        uint256 highS = P256.HALF_N + 1;
        UserOperation memory op = _op(address(a), abi.encodePacked(uint256(1), highS));
        vm.prank(ENTRY_POINT);
        assertEq(a.validateUserOp(op, keccak256("x"), 0), 1, "high-s must be refused");
    }

    function test_OutOfRangeAndMalformedSignaturesAreRefused() public {
        AlwaysValidVerifier v = new AlwaysValidVerifier();
        MatrixAccountFactory f = new MatrixAccountFactory(IEntryPoint(ENTRY_POINT), address(v));
        MatrixAccount a = f.createAccount(OWNER_X, OWNER_Y, 0);

        UserOperation memory zeroR = _op(address(a), abi.encodePacked(uint256(0), uint256(1)));
        vm.prank(ENTRY_POINT);
        assertEq(a.validateUserOp(zeroR, keccak256("x"), 0), 1, "r = 0 must be refused");

        UserOperation memory bigR = _op(address(a), abi.encodePacked(P256.N, uint256(1)));
        vm.prank(ENTRY_POINT);
        assertEq(a.validateUserOp(bigR, keccak256("x"), 0), 1, "r >= n must be refused");

        UserOperation memory short = _op(address(a), hex"1234");
        vm.prank(ENTRY_POINT);
        assertEq(a.validateUserOp(short, keccak256("x"), 0), 1,
            "a malformed signature is refused, and does NOT revert the bundle");
    }

    function test_OnlyTheEntryPointMayValidate() public {
        MatrixAccount a = factory.createAccount(OWNER_X, OWNER_Y, 0);
        UserOperation memory op = _op(address(a), abi.encodePacked(uint256(1), uint256(2)));
        vm.expectRevert(bytes("MA: not EntryPoint"));
        a.validateUserOp(op, keccak256("x"), 0);
    }

    // ── the owner has no address, so owner-only means through the EntryPoint ──

    function test_OwnerOnlyFunctionsAreNotReachableFromAnEOA() public {
        MatrixAccount a = factory.createAccount(OWNER_X, OWNER_Y, 0);
        address[] memory gs = new address[](1);
        gs[0] = address(0xBEEF);
        vm.expectRevert(bytes("MA: not owner (call via EntryPoint)"));
        a.setGuardians(gs, 1);
    }

    function test_GuardianRecoveryRotatesToANewKey() public {
        MatrixAccount a = factory.createAccount(OWNER_X, OWNER_Y, 0);
        address g1 = address(0xB0B);
        address[] memory gs = new address[](1);
        gs[0] = g1;
        vm.prank(address(a));
        a.setGuardians(gs, 1);

        uint256 newX = 0x11; uint256 newY = 0x22;
        vm.prank(g1);
        a.initiateRecovery(newX, newY);

        vm.expectRevert(bytes("MA: timelock"));
        a.executeRecovery();

        vm.warp(block.timestamp + 48 hours);
        a.executeRecovery();
        assertEq(a.ownerX(), newX);
        assertEq(a.ownerY(), newY);
    }

    function test_RecoveryToAZeroKeyIsRefused() public {
        MatrixAccount a = factory.createAccount(OWNER_X, OWNER_Y, 0);
        address g1 = address(0xB0B);
        address[] memory gs = new address[](1);
        gs[0] = g1;
        vm.prank(address(a));
        a.setGuardians(gs, 1);
        vm.prank(g1);
        vm.expectRevert(bytes("MA: zero owner key"));
        a.initiateRecovery(0, 0);
    }

    // ── helper ───────────────────────────────────────────────────────────

    function _op(address sender, bytes memory sig) internal pure returns (UserOperation memory) {
        return UserOperation({
            sender: sender, nonce: 0, initCode: "", callData: "",
            callGasLimit: 0, verificationGasLimit: 0, preVerificationGas: 0,
            maxFeePerGas: 0, maxPriorityFeePerGas: 0, paymasterAndData: "",
            signature: sig
        });
    }
}
