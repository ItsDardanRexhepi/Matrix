#!/usr/bin/env python3
"""P2-9: PREPARE EAS schema registrations (dry-run by default).

EAS schema UIDs are chain-specific keccak256 hashes emitted by the SchemaRegistry
when a schema string is registered. They cannot be guessed or reused across chains
(the Ethereum-mainnet "Schema #348" does NOT exist on Base). This script prints the
exact SchemaRegistry.register(...) calldata for every SCHEMA_DEFINITIONS entry so a
human can review and execute the registrations from a funded signer, then paste the
resulting bytes32 UIDs into config blockchain.schemas.

  python scripts/register_eas_schemas.py --chain base-sepolia            # dry-run (default)
  python scripts/register_eas_schemas.py --chain base                    # dry-run

--execute is intentionally refused unless BOTH --i-understand-this-spends-gas AND a
signer env var (EAS_REGISTRAR_PRIVATE_KEY) are present. Registration is a HUMAN
action (see HUMAN_ACTIONS.md) — this script never broadcasts on its own.
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from runtime.blockchain.services.attestation.schemas import (  # noqa: E402
    SCHEMA_DEFINITIONS,
    build_schema_registration_data,
)

# OP-stack predeploys (Base + Base Sepolia share these addresses).
SCHEMA_REGISTRY = {
    "base": "0x4200000000000000000000000000000000000020",
    "base-sepolia": "0x4200000000000000000000000000000000000020",
}
ZERO_RESOLVER = "0x0000000000000000000000000000000000000000"


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--chain", default="base-sepolia", choices=sorted(SCHEMA_REGISTRY))
    ap.add_argument("--dry-run", action="store_true", default=True)
    ap.add_argument("--execute", action="store_true",
                    help="Broadcast registrations (refused without the safety flags).")
    ap.add_argument("--i-understand-this-spends-gas", action="store_true")
    args = ap.parse_args()

    registry = SCHEMA_REGISTRY[args.chain]

    if args.execute:
        import os
        if not (args.i_understand_this_spends_gas and os.environ.get("EAS_REGISTRAR_PRIVATE_KEY")):
            print("REFUSED: --execute requires --i-understand-this-spends-gas AND "
                  "EAS_REGISTRAR_PRIVATE_KEY. Registration is a HUMAN action — do it "
                  "yourself from a funded signer. This script only prepares calldata.")
            return 2
        print("REFUSED: broadcasting is intentionally not implemented here. Review the "
              "dry-run payloads below and register from your own signer/tooling.")
        return 2

    print(f"# EAS schema registration — chain={args.chain}")
    print(f"# SchemaRegistry: {registry}")
    print(f"# Resolver: {ZERO_RESOLVER}  Revocable: true")
    print(f"# {len(SCHEMA_DEFINITIONS)} schemas. After registering, paste each returned")
    print(f"# bytes32 UID into config blockchain.schemas.<component>.\n")
    for component, definition in SCHEMA_DEFINITIONS.items():
        data = build_schema_registration_data(component, resolver=ZERO_RESOLVER, revocable=True)
        print(f"[{component}]")
        print(f"  register(")
        print(f"    schema:    \"{data['schema']}\",")
        print(f"    resolver:  {data['resolver']},")
        print(f"    revocable: {str(data['revocable']).lower()}")
        print(f"  )  ->  SchemaRegistry {registry}\n")
    print("# DRY RUN — nothing was broadcast.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
