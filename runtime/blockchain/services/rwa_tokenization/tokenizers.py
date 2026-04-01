"""
Asset-specific tokenizers for the RWA Tokenization component.

Each tokenizer validates and normalises metadata for a particular asset
class before producing a token record.
"""

import hashlib
import logging
import time
import uuid
from abc import ABC, abstractmethod
from typing import Any

logger = logging.getLogger(__name__)

VALID_ZONING_TYPES = {
    "residential", "commercial", "industrial", "agricultural", "mixed_use",
}


class BaseTokenizer(ABC):
    """Common interface for all asset tokenizers."""

    asset_type: str = "generic"

    @abstractmethod
    async def tokenize(self, owner: str, metadata: dict) -> dict:
        """Create a token record for the given asset metadata."""

    # ----- helpers -----

    @staticmethod
    def _token_id() -> str:
        return f"rwa_{uuid.uuid4().hex[:16]}"

    @staticmethod
    def _hash(data: str) -> str:
        return hashlib.sha256(data.encode()).hexdigest()

    @staticmethod
    def _now() -> float:
        return time.time()


class PropertyTokenizer(BaseTokenizer):
    """Tokenizer for real-estate / property assets.

    Required metadata keys
    ----------------------
    address : str
        Physical street address of the property.
    sq_footage : int | float
        Total area in square feet.
    zoning : str
        One of the recognised zoning categories.
    title_deed_hash : str
        SHA-256 hash of the scanned title deed document.
    """

    asset_type = "property"

    async def tokenize(self, owner: str, metadata: dict) -> dict:
        required = {"address", "sq_footage", "zoning", "title_deed_hash"}
        missing = required - set(metadata.keys())
        if missing:
            raise ValueError(f"PropertyTokenizer: missing metadata keys: {missing}")

        zoning = metadata["zoning"]
        if zoning not in VALID_ZONING_TYPES:
            raise ValueError(
                f"Invalid zoning type '{zoning}'. Must be one of {VALID_ZONING_TYPES}"
            )

        sq_footage = float(metadata["sq_footage"])
        if sq_footage <= 0:
            raise ValueError("sq_footage must be positive")

        token_id = self._token_id()
        now = self._now()

        token = {
            "token_id": token_id,
            "asset_type": self.asset_type,
            "owner": owner,
            "address": metadata["address"],
            "sq_footage": sq_footage,
            "zoning": zoning,
            "title_deed_hash": metadata["title_deed_hash"],
            "metadata_hash": self._hash(
                f"{metadata['address']}:{sq_footage}:{zoning}:{metadata['title_deed_hash']}"
            ),
            "created_at": now,
            "updated_at": now,
            "status": "active",
        }
        logger.info("Property tokenized: %s for owner %s", token_id, owner)
        return token


class VehicleTokenizer(BaseTokenizer):
    """Tokenizer for vehicle assets.

    Required metadata keys
    ----------------------
    vin : str
        17-character Vehicle Identification Number.
    make : str
        Manufacturer name.
    model : str
        Model designation.
    year : int
        Model year.
    title_hash : str
        SHA-256 hash of the vehicle title document.
    """

    asset_type = "vehicle"

    async def tokenize(self, owner: str, metadata: dict) -> dict:
        required = {"vin", "make", "model", "year", "title_hash"}
        missing = required - set(metadata.keys())
        if missing:
            raise ValueError(f"VehicleTokenizer: missing metadata keys: {missing}")

        vin = str(metadata["vin"]).strip().upper()
        if len(vin) != 17:
            raise ValueError(f"VIN must be 17 characters, got {len(vin)}")

        year = int(metadata["year"])
        if year < 1886 or year > 2100:
            raise ValueError(f"Invalid vehicle year: {year}")

        token_id = self._token_id()
        now = self._now()

        token = {
            "token_id": token_id,
            "asset_type": self.asset_type,
            "owner": owner,
            "vin": vin,
            "make": metadata["make"],
            "model": metadata["model"],
            "year": year,
            "title_hash": metadata["title_hash"],
            "metadata_hash": self._hash(f"{vin}:{metadata['make']}:{metadata['model']}:{year}"),
            "created_at": now,
            "updated_at": now,
            "status": "active",
        }
        logger.info("Vehicle tokenized: %s (VIN %s) for owner %s", token_id, vin, owner)
        return token


class GenericAssetTokenizer(BaseTokenizer):
    """Flexible tokenizer for art, commodities, equipment, and other asset types.

    Accepts any metadata dictionary.  A ``description`` key is recommended
    but not enforced.
    """

    def __init__(self, asset_type: str = "generic") -> None:
        self.asset_type = asset_type

    async def tokenize(self, owner: str, metadata: dict) -> dict:
        if not metadata:
            raise ValueError("GenericAssetTokenizer: metadata must not be empty")

        token_id = self._token_id()
        now = self._now()

        # Deterministic hash of all metadata key/value pairs
        sorted_items = sorted(metadata.items(), key=lambda kv: kv[0])
        raw = ":".join(f"{k}={v}" for k, v in sorted_items)

        token = {
            "token_id": token_id,
            "asset_type": self.asset_type,
            "owner": owner,
            "metadata": metadata,
            "metadata_hash": self._hash(raw),
            "created_at": now,
            "updated_at": now,
            "status": "active",
        }
        logger.info(
            "Generic asset (%s) tokenized: %s for owner %s",
            self.asset_type, token_id, owner,
        )
        return token


# Registry mapping asset type string -> tokenizer class
TOKENIZER_REGISTRY: dict[str, type[BaseTokenizer]] = {
    "property": PropertyTokenizer,
    "vehicle": VehicleTokenizer,
    "art": GenericAssetTokenizer,
    "commodity": GenericAssetTokenizer,
    "equipment": GenericAssetTokenizer,
}


def get_tokenizer(asset_type: str) -> BaseTokenizer:
    """Return an appropriate tokenizer instance for *asset_type*."""
    cls = TOKENIZER_REGISTRY.get(asset_type)
    if cls is None:
        raise ValueError(
            f"Unsupported asset type '{asset_type}'. "
            f"Supported: {sorted(TOKENIZER_REGISTRY.keys())}"
        )
    if cls is GenericAssetTokenizer:
        return GenericAssetTokenizer(asset_type=asset_type)
    return cls()
