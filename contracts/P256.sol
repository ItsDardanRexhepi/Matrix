// SPDX-License-Identifier: MIT
pragma solidity ^0.8.20;

/// @title P256
/// @notice Verifies secp256r1 (P-256) ECDSA signatures — the curve Apple's
/// Secure Enclave signs on.
///
/// WHY THIS EXISTS. MTRX signs UserOperations with a Secure Enclave key, and the
/// Secure Enclave can only produce P-256 signatures; it cannot produce the
/// secp256k1 signatures Ethereum's `ecrecover` verifies. The account contract
/// used `ECDSA.recover`, so the chain
///     Secure Enclave -> P-256 signature -> UserOperation -> account
/// did not close: the signature was on a different curve from the one being
/// verified, and no amount of re-encoding bridges two curves. Nothing on chain
/// could ever have validated a signature this app produced.
///
/// NO ELLIPTIC-CURVE ARITHMETIC IS IMPLEMENTED HERE, deliberately. A hand-rolled
/// P-256 verifier is exactly the kind of code that is subtly wrong for years.
/// Verification is delegated:
///
///   1. RIP-7212, the P256VERIFY precompile at address 0x100. Where a chain has
///      it, this is the cheapest and most trustworthy path.
///   2. A verifier CONTRACT at an address the account carries, for chains that
///      do not implement RIP-7212 yet. The same call shape, so the caller does
///      not care which answered.
///
/// AND IT FAILS CLOSED. If neither is present the call returns false. It never
/// returns "valid" because it could not check — an unverifiable signature on a
/// wallet must be a refusal, not a pass.
library P256 {
    /// @dev The RIP-7212 precompile. Input is 160 bytes: hash ‖ r ‖ s ‖ x ‖ y.
    ///      It returns 32 bytes of 1 for a valid signature, and empty for an
    ///      invalid one. An address with no code returns empty with success=true,
    ///      which is why an empty return is treated as NOT verified.
    address internal constant PRECOMPILE = address(0x100);

    /// @dev n, the order of the P-256 group.
    uint256 internal constant N =
        0xFFFFFFFF00000000FFFFFFFFFFFFFFFFBCE6FAADA7179E84F3B9CAC2FC632551;
    /// @dev n/2, for the malleability check.
    uint256 internal constant HALF_N =
        0x7FFFFFFF800000007FFFFFFFFFFFFFFFDE737D56D38BCF4279DCE5617E3192A8;

    /// @notice True when (r, s) is a valid P-256 signature over `hash` by (x, y).
    /// @param verifier A verifier contract to use when the precompile is absent.
    ///                 Pass address(0) to use only the precompile.
    function verify(
        bytes32 hash,
        uint256 r,
        uint256 s,
        uint256 x,
        uint256 y,
        address verifier
    ) internal view returns (bool) {
        // Range checks first. These are cheap, and they are the difference
        // between rejecting a malformed signature and handing a malformed one to
        // a verifier whose behaviour on out-of-range input is its own business.
        if (r == 0 || r >= N || s == 0 || s >= N) return false;

        // REJECT THE HIGH-S HALF. For every valid (r, s) the pair (r, n-s) is
        // also valid, so accepting both makes a signature malleable: the same
        // authorisation appears under two distinct signatures. Callers that key
        // anything on the signature bytes — a replay cache, a dedupe, a log —
        // can then be shown two different records of one approval. CryptoKit
        // does not normalise s, so the CLIENT must send the low-s form; the
        // account documents that and this is where it is enforced.
        if (s > HALF_N) return false;

        bytes memory input = abi.encodePacked(hash, r, s, x, y);

        (bool ok, bytes memory ret) = PRECOMPILE.staticcall(input);
        if (ok && ret.length == 32 && abi.decode(ret, (uint256)) == 1) {
            return true;
        }
        // `ok && ret.length == 0` is the "no precompile on this chain" answer: a
        // staticcall to an address with no code succeeds and returns nothing.
        // It is NOT a verification result, so fall through rather than conclude.

        if (verifier == address(0)) return false;
        (ok, ret) = verifier.staticcall(input);
        return ok && ret.length == 32 && abi.decode(ret, (uint256)) == 1;
    }

    /// @notice Split a 64-byte signature into (r, s).
    /// @dev The client sends the RAW representation, r ‖ s, 32 bytes each — NOT
    ///      DER. DER is variable length and would have to be parsed on chain for
    ///      no benefit. CryptoKit exposes both as `rawRepresentation` and
    ///      `derRepresentation`; the raw one is what belongs here.
    function decode(bytes calldata signature) internal pure returns (uint256 r, uint256 s) {
        require(signature.length == 64, "P256: signature must be 64 bytes (r||s)");
        r = uint256(bytes32(signature[0:32]));
        s = uint256(bytes32(signature[32:64]));
    }
}
