"""
ENS Importer — imports Ethereum Name Service records.

Resolves ENS names associated with an address and creates
local records of domain ownership in 0pnMatrx.
"""

import argparse
import json
import logging
import sys
from pathlib import Path

import aiohttp
import asyncio

logger = logging.getLogger(__name__)

ENS_SUBGRAPH = "https://api.thegraph.com/subgraphs/name/ensdomains/ens"


async def fetch_ens_names(address: str) -> list[dict]:
    """Fetch ENS names owned by an address via The Graph."""
    query = """
    query($owner: String!) {
        domains(where: {owner: $owner}, first: 100) {
            name
            labelName
            createdAt
            expiryDate
            resolver {
                address
            }
            owner {
                id
            }
        }
    }
    """

    async with aiohttp.ClientSession() as session:
        try:
            async with session.post(
                ENS_SUBGRAPH,
                json={"query": query, "variables": {"owner": address.lower()}},
                timeout=aiohttp.ClientTimeout(total=15),
            ) as resp:
                if resp.status != 200:
                    logger.error(f"ENS subgraph error: {resp.status}")
                    return []

                data = await resp.json()
        except Exception as e:
            logger.error(f"Failed to query ENS subgraph: {e}")
            return []

    domains = data.get("data", {}).get("domains", [])

    records = []
    for domain in domains:
        records.append({
            "name": domain.get("name", ""),
            "label": domain.get("labelName", ""),
            "created_at": domain.get("createdAt", ""),
            "expiry_date": domain.get("expiryDate", ""),
            "resolver": (domain.get("resolver") or {}).get("address", ""),
            "owner": (domain.get("owner") or {}).get("id", ""),
        })

    return records


def main():
    parser = argparse.ArgumentParser(description="Import ENS names into 0pnMatrx")
    parser.add_argument("--address", required=True, help="Ethereum address to look up ENS names for")
    parser.add_argument("--output", default="imported/ens", help="Output directory")
    args = parser.parse_args()

    logging.basicConfig(level=logging.INFO)

    records = asyncio.run(fetch_ens_names(args.address))

    if not records:
        logger.warning("No ENS names found for this address")
        sys.exit(0)

    output_dir = Path(args.output)
    output_dir.mkdir(parents=True, exist_ok=True)

    output_file = output_dir / f"{args.address[:10]}_ens.json"
    output_file.write_text(json.dumps(records, indent=2))

    logger.info(f"Imported {len(records)} ENS name(s)")


if __name__ == "__main__":
    main()
