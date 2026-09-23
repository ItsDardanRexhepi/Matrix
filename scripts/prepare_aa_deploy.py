#!/usr/bin/env python3
"""P4: PREPARE the ERC-4337 account/factory/paymaster deployment (dry-run only).

Prints the deploy plan — order, constructor args, the canonical EntryPoint v0.6
address, and the config keys to fill afterwards — so a human can execute the
deployments from a funded signer and paste the resulting addresses into config.

  python scripts/prepare_aa_deploy.py --chain base-sepolia            # dry-run (default)

--execute is intentionally refused unless BOTH --i-understand-this-spends-gas AND
a signer env var (AA_DEPLOYER_PRIVATE_KEY) are present, and even then this script
does NOT broadcast — deploying is a HUMAN action (see HUMAN_ACTIONS.md). Compile
with `forge build` (which resolves the account-abstraction + OZ remappings);
py-solc-x in the legacy deploy.py cannot.
"""

from __future__ import annotations

import argparse

# EntryPoint v0.6 canonical (same address on Base + Base Sepolia).
ENTRY_POINT_V06 = "0x5FF137D4b0FDCD49DcA30c7CF57E578a026d2789"

CHAINS = {"base-sepolia": 84532, "base": 8453}


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--chain", default="base-sepolia", choices=sorted(CHAINS))
    ap.add_argument("--dry-run", action="store_true", default=True)
    ap.add_argument("--execute", action="store_true")
    ap.add_argument("--i-understand-this-spends-gas", action="store_true")
    ap.add_argument("--owner", default="<PLATFORM_OWNER_ADDRESS>")
    ap.add_argument("--p256-verifier", default="0x0000000000000000000000000000000000000000",
                    help="fallback P-256 verifier contract; 0x0 = rely on the "
                         "RIP-7212 precompile at 0x100")
    ap.add_argument("--verifying-signer", default="<PAYMASTER_SIGNER_ADDRESS>")
    args = ap.parse_args()

    if args.execute:
        import os
        if not (args.i_understand_this_spends_gas and os.environ.get("AA_DEPLOYER_PRIVATE_KEY")):
            print("REFUSED: --execute requires --i-understand-this-spends-gas AND "
                  "AA_DEPLOYER_PRIVATE_KEY.")
            return 2
        print("REFUSED: broadcasting is intentionally not implemented — deploying is a "
              "HUMAN action. Use the dry-run plan below with your own signer/tooling.")
        return 2

    ep = ENTRY_POINT_V06
    print(f"# ERC-4337 AA deploy plan — chain={args.chain} (id={CHAINS[args.chain]})")
    print(f"# EntryPoint v0.6 (canonical, pre-deployed): {ep}")
    print(f"# Compile first: forge build  (resolves account-abstraction + OZ)\n")

    print("[1] MatrixAccountFactory")
    print(f"    constructor(IEntryPoint _entryPoint = {ep},")
    print(f"                address _p256Verifier = {args.p256_verifier})")
    print("    -> config: blockchain.paymaster.account_factory = <deployed address>")
    print("    NOTE: accounts are owned by a P-256 (secp256r1) PUBLIC KEY, not an")
    print("    address, because the Secure Enclave signs P-256 and cannot produce")
    print("    secp256k1. Verification uses the RIP-7212 precompile at 0x100 where")
    print("    the chain has it. _p256Verifier is the fallback verifier CONTRACT for")
    print("    chains that do not; address(0) means precompile-only, and an account")
    print("    on a chain with neither will refuse every signature (fail closed).")
    print("    CONFIRM RIP-7212 IS LIVE ON THE TARGET CHAIN, or deploy a verifier")
    print("    and pass it here — this script cannot check that for you.\n")

    print("[2] MatrixVerifyingPaymaster")
    print(f"    constructor(IEntryPoint _entryPoint = {ep},")
    print(f"                address _verifyingSigner = {args.verifying_signer},")
    print(f"                address _owner = {args.owner})")
    print("    -> config: blockchain.paymaster.address = <deployed address>")
    print("    POST-DEPLOY (human, funded): paymaster.deposit{value: ...} + optionally")
    print("    addStake(unstakeDelaySec) so the EntryPoint accepts sponsored ops.\n")

    print("[3] MatrixAccount is NOT deployed directly — the factory CREATE2-deploys")
    print("    one per user on the first UserOp (initCode). Nothing to deploy here.")
    print("    The client's initCode must encode createAccount(ownerX, ownerY, salt)")
    print("    with the owner's P-256 public key, and its counterfactual sender must")
    print("    come from factory.getAddress(ownerX, ownerY, salt) — never from a")
    print("    locally reimplemented CREATE2 hash.\n")

    print("# After deploy, also set: blockchain.paymaster.entry_point =", ep)
    print("# and the same addresses in the wallet client's AA/paymaster settings.")
    print("# DRY RUN — nothing was broadcast.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
