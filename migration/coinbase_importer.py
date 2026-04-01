"""
Coinbase Importer — imports transaction history from Coinbase CSV exports.

Reads Coinbase's standard CSV export format and creates transaction
records in 0pnMatrx.
"""

import argparse
import csv
import json
import logging
import sys
from pathlib import Path
from dataclasses import dataclass, asdict

logger = logging.getLogger(__name__)


@dataclass
class Transaction:
    timestamp: str
    transaction_type: str
    asset: str
    quantity: str
    spot_price: str
    subtotal: str
    total: str
    fees: str
    notes: str


def parse_coinbase_csv(filepath: Path) -> list[Transaction]:
    """Parse a Coinbase CSV export into transaction records."""
    transactions = []

    with open(filepath, "r", encoding="utf-8") as f:
        lines = f.readlines()

    header_idx = None
    for i, line in enumerate(lines):
        if "Timestamp" in line and "Transaction Type" in line:
            header_idx = i
            break

    if header_idx is None:
        for i, line in enumerate(lines):
            if not line.startswith("#") and "," in line:
                header_idx = i
                break

    if header_idx is None:
        logger.error("Could not find CSV header in Coinbase export")
        return []

    reader = csv.DictReader(lines[header_idx:])

    for row in reader:
        transactions.append(Transaction(
            timestamp=row.get("Timestamp", row.get("Date", "")),
            transaction_type=row.get("Transaction Type", row.get("Type", "")),
            asset=row.get("Asset", row.get("Currency", "")),
            quantity=row.get("Quantity Transacted", row.get("Amount", "")),
            spot_price=row.get("Spot Price at Transaction", row.get("Price", "")),
            subtotal=row.get("Subtotal", ""),
            total=row.get("Total (inclusive of fees and/or spread)", row.get("Total", "")),
            fees=row.get("Fees and/or Spread", row.get("Fees", "")),
            notes=row.get("Notes", ""),
        ))

    return transactions


def main():
    parser = argparse.ArgumentParser(description="Import Coinbase transaction history into 0pnMatrx")
    parser.add_argument("--input", required=True, help="Path to Coinbase CSV export")
    parser.add_argument("--output", default="imported/coinbase", help="Output directory")
    args = parser.parse_args()

    logging.basicConfig(level=logging.INFO)

    input_path = Path(args.input)
    if not input_path.exists():
        logger.error(f"File not found: {input_path}")
        sys.exit(1)

    transactions = parse_coinbase_csv(input_path)

    if not transactions:
        logger.warning("No transactions found in export")
        sys.exit(0)

    output_dir = Path(args.output)
    output_dir.mkdir(parents=True, exist_ok=True)

    output_file = output_dir / "transactions.json"
    output_file.write_text(json.dumps([asdict(t) for t in transactions], indent=2))

    logger.info(f"Imported {len(transactions)} transaction(s)")


if __name__ == "__main__":
    main()
