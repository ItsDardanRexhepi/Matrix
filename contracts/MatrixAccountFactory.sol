// SPDX-License-Identifier: MIT
pragma solidity ^0.8.20;

import "account-abstraction/interfaces/IEntryPoint.sol";
import "@openzeppelin/contracts/utils/Create2.sol";
import "./MatrixAccount.sol";

/// @title MatrixAccountFactory
/// @notice CREATE2 factory for MatrixAccount, keyed on the owner's P-256 PUBLIC
/// KEY rather than an address.
///
/// The signature changed, and it had to. The account's owner is a P-256 key
/// because the Secure Enclave cannot sign secp256k1, so there is no address to
/// key an account on — `createAccount(address,uint256)` had nothing truthful to
/// take. The iOS client derives its counterfactual address from
/// `initCode = factory ++ createAccount calldata`, so it must encode
/// (ownerX, ownerY, salt) the same way; `getAddress` is the definition and the
/// client is expected to match it, not the other way round.
///
/// Deploying the same account twice is a no-op (it returns the existing one), so
/// including initCode on the first UserOp only remains safe.
contract MatrixAccountFactory {
    IEntryPoint public immutable entryPoint;

    /// @notice The P-256 verifier every account this factory creates will use.
    /// address(0) means the accounts rely on the RIP-7212 precompile alone.
    address public immutable p256Verifier;

    constructor(IEntryPoint _entryPoint, address _p256Verifier) {
        entryPoint = _entryPoint;
        p256Verifier = _p256Verifier;
    }

    function createAccount(uint256 ownerX, uint256 ownerY, uint256 salt)
        public
        returns (MatrixAccount ret)
    {
        address addr = getAddress(ownerX, ownerY, salt);
        if (addr.code.length > 0) {
            return MatrixAccount(payable(addr));
        }
        ret = new MatrixAccount{salt: bytes32(salt)}(entryPoint, ownerX, ownerY, p256Verifier);
    }

    function getAddress(uint256 ownerX, uint256 ownerY, uint256 salt)
        public
        view
        returns (address)
    {
        return Create2.computeAddress(
            bytes32(salt),
            keccak256(abi.encodePacked(
                type(MatrixAccount).creationCode,
                abi.encode(entryPoint, ownerX, ownerY, p256Verifier)
            ))
        );
    }
}
