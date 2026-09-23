#!/usr/bin/env python3
"""Refuse a deployment manifest that names a retired contract.

ONE TABLE, TWO CONSUMERS. `contracts/deploy.py` imports LEGACY_CONTRACTS so its
run prints what it will not deploy, and `scripts/deploy_and_configure.sh` runs
this file over the manifest before it writes an address into the config or sends
anything ETH. A second copy of the list is how one of them drifts.

Usage:
    python scripts/refuse_legacy_contracts.py <deployment_manifest.json>

Exit codes:
    0  the manifest names nothing retired
    2  it names something retired — the refusal, on stdout, says which and why
    3  the manifest could not be read. NOT a pass: a guard that treats an
       unreadable manifest as "nothing to refuse" is one that a typo in a path
       turns off silently.
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

#: Contract name -> why this repository's tooling will not put a new one on a
#: chain. The name is the key deployment manifests use (``.contracts.<name>``).
#
# DO NOT DEPLOY — every entry below is here because deploying it is the defect.
LEGACY_CONTRACTS: dict[str, str] = {
    "MatrixPaymaster": (
        "the pre-ERC-4337 paymaster. sponsoredCall(address,bytes) lets any "
        "authorized key reach ANY address with ANY calldata, and "
        "sponsoredCallWithValue does it carrying ETH. Nothing in the runtime "
        "calls it: the platform's paymaster is MatrixVerifyingPaymaster, an "
        "ERC-4337 v0.6 verifying paymaster that pays gas out of its own "
        "EntryPoint deposit and has no arbitrary-call surface, and "
        "blockchain.paymaster.address is the only paymaster address the server "
        "reads. A deployment that genuinely wants the old one deploys it "
        "deliberately and by hand, which is the point: it should not fall out "
        "of running the repository's own tooling."
    ),
}


def legacy_contracts_in(manifest: dict) -> list[tuple[str, str, str]]:
    """Return ``(name, address, reason)`` for every retired contract named.

    Reads the manifest shape ``scripts/deploy_all.py`` writes:
    ``{"contracts": {"<Name>": {"contract_address": "0x…"}}}``.
    """
    contracts = manifest.get("contracts")
    if not isinstance(contracts, dict):
        return []
    found: list[tuple[str, str, str]] = []
    for name, reason in LEGACY_CONTRACTS.items():
        entry = contracts.get(name)
        if entry is None:
            continue
        address = ""
        if isinstance(entry, dict):
            address = str(entry.get("contract_address") or entry.get("address") or "")
        elif isinstance(entry, str):
            address = entry
        found.append((name, address or "<no address in manifest>", reason))
    return found


def refusal_text(found: list[tuple[str, str, str]]) -> str:
    lines = [
        "",
        "  ╔══════════════════════════════════════════════════════════════╗",
        "  ║  REFUSED — the manifest names a retired contract             ║",
        "  ╚══════════════════════════════════════════════════════════════╝",
        "",
    ]
    for name, address, reason in found:
        lines.append(f"  {name}  at  {address}")
        lines.append(f"    {reason}")
        lines.append("")
    lines.append("  Nothing was configured and nothing was funded. Remove the entry")
    lines.append("  from the manifest, or deploy the replacement, and run this again.")
    lines.append("")
    return "\n".join(lines)


def main(argv: list[str]) -> int:
    if len(argv) != 2:
        print(__doc__ or "", file=sys.stderr)
        return 3
    path = Path(argv[1])
    try:
        manifest = json.loads(path.read_text())
    except (OSError, ValueError) as exc:
        print(f"  Could not read the deployment manifest at {path}: {exc}")
        print("  Refusing rather than assuming it names nothing retired.")
        return 3
    if not isinstance(manifest, dict):
        print(f"  The deployment manifest at {path} is not a JSON object.")
        return 3

    found = legacy_contracts_in(manifest)
    if found:
        print(refusal_text(found))
        return 2
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv))
