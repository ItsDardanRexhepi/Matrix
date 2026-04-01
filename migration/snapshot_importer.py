"""
Snapshot Importer — imports governance voting history from Snapshot.

Fetches voting records for an address from the Snapshot GraphQL API
and creates local records in 0pnMatrx.
"""

import argparse
import json
import logging
import sys
from pathlib import Path

import aiohttp
import asyncio

logger = logging.getLogger(__name__)

SNAPSHOT_API = "https://hub.snapshot.org/graphql"


async def fetch_votes(address: str) -> list[dict]:
    """Fetch voting history for an address from Snapshot."""
    query = """
    query($voter: String!) {
        votes(
            where: {voter: $voter},
            first: 1000,
            orderBy: "created",
            orderDirection: desc
        ) {
            id
            voter
            created
            choice
            space {
                id
                name
            }
            proposal {
                id
                title
                state
                choices
            }
        }
    }
    """

    async with aiohttp.ClientSession() as session:
        try:
            async with session.post(
                SNAPSHOT_API,
                json={"query": query, "variables": {"voter": address}},
                timeout=aiohttp.ClientTimeout(total=15),
            ) as resp:
                if resp.status != 200:
                    logger.error(f"Snapshot API error: {resp.status}")
                    return []

                data = await resp.json()
        except Exception as e:
            logger.error(f"Failed to query Snapshot: {e}")
            return []

    votes = data.get("data", {}).get("votes", [])

    records = []
    for vote in votes:
        proposal = vote.get("proposal") or {}
        space = vote.get("space") or {}
        choices = proposal.get("choices", [])
        choice_value = vote.get("choice")

        choice_text = ""
        if isinstance(choice_value, int) and 1 <= choice_value <= len(choices):
            choice_text = choices[choice_value - 1]
        elif isinstance(choice_value, str):
            choice_text = choice_value

        records.append({
            "vote_id": vote.get("id", ""),
            "space": space.get("name", space.get("id", "")),
            "proposal_title": proposal.get("title", ""),
            "proposal_state": proposal.get("state", ""),
            "choice": choice_text,
            "created": vote.get("created", 0),
        })

    return records


def main():
    parser = argparse.ArgumentParser(description="Import Snapshot voting history into 0pnMatrx")
    parser.add_argument("--address", required=True, help="Ethereum address to import votes for")
    parser.add_argument("--output", default="imported/snapshot", help="Output directory")
    args = parser.parse_args()

    logging.basicConfig(level=logging.INFO)

    records = asyncio.run(fetch_votes(args.address))

    if not records:
        logger.warning("No voting records found for this address")
        sys.exit(0)

    output_dir = Path(args.output)
    output_dir.mkdir(parents=True, exist_ok=True)

    output_file = output_dir / f"{args.address[:10]}_votes.json"
    output_file.write_text(json.dumps(records, indent=2))

    logger.info(f"Imported {len(records)} vote(s)")


if __name__ == "__main__":
    main()
