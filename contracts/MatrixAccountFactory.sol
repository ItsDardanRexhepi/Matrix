// SPDX-License-Identifier: MIT
pragma solidity ^0.8.20;

import "account-abstraction/interfaces/IEntryPoint.sol";
import "@openzeppelin/contracts/utils/Create2.sol";
import "./MatrixAccount.sol";

/// @title MatrixAccountFactory
/// @notice CREATE2 factory for MatrixAccount. The signatures
/// `createAccount(address owner, uint256 salt)` and `getAddress(address owner,
/// uint256 salt)` intentionally match SimpleAccountFactory so the iOS client's
/// counterfactual address derivation (initCode = factory ++ createAccount calldata)
/// keeps working unchanged. Deploying to a counterfactual address twice is a no-op
/// (returns the existing account), so it's safe to include initCode on the first
/// UserOp only.
contract MatrixAccountFactory {
    IEntryPoint public immutable entryPoint;

    constructor(IEntryPoint _entryPoint) {
        entryPoint = _entryPoint;
    }

    function createAccount(address owner, uint256 salt) public returns (MatrixAccount ret) {
        address addr = getAddress(owner, salt);
        if (addr.code.length > 0) {
            return MatrixAccount(payable(addr));
        }
        ret = new MatrixAccount{salt: bytes32(salt)}(entryPoint, owner);
    }

    function getAddress(address owner, uint256 salt) public view returns (address) {
        return Create2.computeAddress(
            bytes32(salt),
            keccak256(abi.encodePacked(
                type(MatrixAccount).creationCode,
                abi.encode(entryPoint, owner)
            ))
        );
    }
}
