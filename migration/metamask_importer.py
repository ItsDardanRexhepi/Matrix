"""
MetaMask Importer — imports wallet data from MetaMask exports.

Reads MetaMask's exported JSON format and creates corresponding
wallet records in 0pnMatrx. Only public data is imported.
"""

import argparse
import json
import logging
import sys
from pathlib import Path
from dataclasses import dataclass

logger = logging.getLogger(__name__)


@dataclass
class WalletRecord:
    address: str
    name: str
    network: str
    tokens: list[dict]
    transactions: list[dict]


def parse_metamask_export(data: dict) -> list[WalletRecord]:
    """Parse a MetaMask state export into wallet records."""
    records = []

    accounts = data.get("accounts", data.get("identities", {}))
    if isinstance(accounts, dict):
        accounts = list(accounts.values())

    for account in accounts:
        address = account.get("address", "")
        if not address:
            continue

        name = account.get("name", "Imported Wallet")

        tokens = []
        token_data = data.get("tokens", {})
        if isinstance(token_data, dict):
            for token_list in token_data.values():
                if isinstance(token_list, list):
                    for t in token_list:
                        tokens.append({
                            "symbol": t.get("symbol", ""),
                            "address": t.get("address", ""),
                            "decimals": t.get("decimals", 18),
                        })

        transactions = []
        tx_data = data.get("transactions", data.get("txHistory", []))
        if isinstance(tx_data, list):
            for tx in tx_data:
                if tx.get("from", "").lower() == address.lower() or \
                   tx.get("to", "").lower() == address.lower():
                    transactions.append({
                        "hash": tx.get("hash", ""),
                        "from": tx.get("from", ""),
                        "to": tx.get("to", ""),
                        "value": tx.get("value", "0"),
                        "status": tx.get("status", ""),
                    })

        records.append(WalletRecord(
            address=address,
            name=name,
            network=data.get("network", "ethereum"),
            tokens=tokens,
            transactions=transactions[:100],
        ))

    return records


def import_wallets(records: list[WalletRecord], output_dir: Path):
    """Write imported wallet records to the output directory."""
    output_dir.mkdir(parents=True, exist_ok=True)

    for record in records:
        output_file = output_dir / f"{record.address[:10]}.json"
        output_data = {
            "address": record.address,
            "name": record.name,
            "network": record.network,
            "tokens": record.tokens,
            "transaction_count": len(record.transactions),
            "transactions": record.transactions,
        }
        output_file.write_text(json.dumps(output_data, indent=2))
        logger.info(f"Imported wallet: {record.address[:10]}... ({record.name})")


def main():
    parser = argparse.ArgumentParser(description="Import MetaMask wallet data into 0pnMatrx")
    parser.add_argument("--input", required=True, help="Path to MetaMask export JSON")
    parser.add_argument("--output", default="imported/metamask", help="Output directory")
    args = parser.parse_args()

    logging.basicConfig(level=logging.INFO)

    input_path = Path(args.input)
    if not input_path.exists():
        logger.error(f"File not found: {input_path}")
        sys.exit(1)

    data = json.loads(input_path.read_text())
    records = parse_metamask_export(data)

    if not records:
        logger.warning("No wallet records found in export")
        sys.exit(0)

    import_wallets(records, Path(args.output))
    logger.info(f"Imported {len(records)} wallet(s)")


if __name__ == "__main__":
    main()
