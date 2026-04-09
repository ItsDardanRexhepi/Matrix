from __future__ import annotations

"""
OpenSea Importer — imports NFT collection data from OpenSea.

Fetches NFT ownership records for a given address using the
OpenSea API and creates local records in 0pnMatrx.
"""

import argparse
import json
import logging
import sys
from pathlib import Path

import aiohttp
import asyncio

logger = logging.getLogger(__name__)

OPENSEA_API = "https://api.opensea.io/api/v2"


async def fetch_nfts(address: str, api_key: str | None = None) -> list[dict]:
    """Fetch NFTs owned by an address from OpenSea."""
    headers = {"Accept": "application/json"}
    if api_key:
        headers["X-API-KEY"] = api_key

    nfts = []
    next_cursor = None

    async with aiohttp.ClientSession() as session:
        for _ in range(10):  # max 10 pages
            params = {"owner": address, "limit": "50"}
            if next_cursor:
                params["next"] = next_cursor

            try:
                async with session.get(
                    f"{OPENSEA_API}/chain/ethereum/account/{address}/nfts",
                    headers=headers,
                    params=params,
                    timeout=aiohttp.ClientTimeout(total=15),
                ) as resp:
                    if resp.status == 401:
                        logger.error("OpenSea API key required for this endpoint")
                        break
                    if resp.status != 200:
                        logger.error(f"OpenSea API error: {resp.status}")
                        break

                    data = await resp.json()
            except Exception as e:
                logger.error(f"Failed to fetch from OpenSea: {e}")
                break

            for nft in data.get("nfts", []):
                nfts.append({
                    "identifier": nft.get("identifier", ""),
                    "collection": nft.get("collection", ""),
                    "contract": nft.get("contract", ""),
                    "name": nft.get("name", ""),
                    "description": nft.get("description", ""),
                    "image_url": nft.get("image_url", ""),
                    "token_standard": nft.get("token_standard", ""),
                })

            next_cursor = data.get("next")
            if not next_cursor:
                break

    return nfts


def main():
    parser = argparse.ArgumentParser(description="Import NFT data from OpenSea into 0pnMatrx")
    parser.add_argument("--address", required=True, help="Ethereum address to import NFTs for")
    parser.add_argument("--api-key", default=None, help="OpenSea API key (optional)")
    parser.add_argument("--output", default="imported/opensea", help="Output directory")
    args = parser.parse_args()

    logging.basicConfig(level=logging.INFO)

    nfts = asyncio.run(fetch_nfts(args.address, args.api_key))

    if not nfts:
        logger.warning("No NFTs found for this address")
        sys.exit(0)

    output_dir = Path(args.output)
    output_dir.mkdir(parents=True, exist_ok=True)

    output_file = output_dir / f"{args.address[:10]}_nfts.json"
    output_file.write_text(json.dumps(nfts, indent=2))

    logger.info(f"Imported {len(nfts)} NFT(s)")


if __name__ == "__main__":
    main()
