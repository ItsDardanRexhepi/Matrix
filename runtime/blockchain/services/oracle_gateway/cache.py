from __future__ import annotations

"""
TTL-based cache for oracle responses.

Each oracle type has a configurable TTL. VRF results are never cached
(TTL=0) since randomness must be fresh. Price feeds cache briefly to
avoid hammering RPC nodes on repeated reads within the same block.
"""

import asyncio
import logging
import time
from dataclasses import dataclass, field
from typing import Any

logger = logging.getLogger(__name__)

# Default TTLs in seconds per oracle type
DEFAULT_TTLS: dict[str, int] = {
    "price_feed": 60,
    "weather": 300,
    "sports": 30,
    "random_vrf": 0,   # never cache
    "custom": 120,
}


@dataclass(slots=True)
class _CacheEntry:
    """Single cached value with expiration metadata."""

    value: Any
    expires_at: float
    created_at: float = field(default_factory=time.monotonic)

    @property
    def is_expired(self) -> bool:
        return time.monotonic() >= self.expires_at


class OracleCache:
    """Async-safe, TTL-based in-memory cache for oracle data.

    Parameters
    ----------
    ttls : dict[str, int] | None
        Mapping of oracle type to TTL in seconds.  Falls back to
        ``DEFAULT_TTLS`` for any type not specified.
    max_entries : int
        Upper bound on total cached items.  Oldest entries are evicted
        when the limit is reached.
    """

    def __init__(
        self,
        ttls: dict[str, int] | None = None,
        max_entries: int = 10_000,
    ) -> None:
        self._ttls: dict[str, int] = {**DEFAULT_TTLS, **(ttls or {})}
        self._max_entries = max_entries
        self._store: dict[str, _CacheEntry] = {}
        self._lock = asyncio.Lock()
        self._hits = 0
        self._misses = 0

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    async def get(self, oracle_type: str, key: str) -> Any | None:
        """Return cached value or ``None`` if missing / expired."""
        cache_key = self._make_key(oracle_type, key)

        async with self._lock:
            entry = self._store.get(cache_key)
            if entry is None:
                self._misses += 1
                return None
            if entry.is_expired:
                del self._store[cache_key]
                self._misses += 1
                return None
            self._hits += 1
            return entry.value

    async def set(self, oracle_type: str, key: str, value: Any) -> None:
        """Store *value* with the TTL configured for *oracle_type*.

        If the TTL for the oracle type is 0 the value is **not** stored.
        """
        ttl = self._ttls.get(oracle_type, DEFAULT_TTLS.get(oracle_type, 0))
        if ttl <= 0:
            return

        cache_key = self._make_key(oracle_type, key)
        now = time.monotonic()

        async with self._lock:
            self._store[cache_key] = _CacheEntry(
                value=value,
                expires_at=now + ttl,
                created_at=now,
            )
            # Evict oldest entries when over capacity
            if len(self._store) > self._max_entries:
                self._evict_oldest(len(self._store) - self._max_entries)

    async def invalidate(self, oracle_type: str, key: str) -> bool:
        """Remove a specific entry.  Returns ``True`` if it existed."""
        cache_key = self._make_key(oracle_type, key)
        async with self._lock:
            return self._store.pop(cache_key, None) is not None

    async def invalidate_type(self, oracle_type: str) -> int:
        """Remove **all** entries for a given oracle type.  Returns count removed."""
        prefix = f"{oracle_type}:"
        async with self._lock:
            keys = [k for k in self._store if k.startswith(prefix)]
            for k in keys:
                del self._store[k]
            return len(keys)

    async def clear(self) -> None:
        """Remove every entry from the cache."""
        async with self._lock:
            self._store.clear()
            self._hits = 0
            self._misses = 0

    @property
    def stats(self) -> dict[str, int]:
        """Return basic cache statistics."""
        return {
            "size": len(self._store),
            "hits": self._hits,
            "misses": self._misses,
        }

    # ------------------------------------------------------------------
    # Internal helpers
    # ------------------------------------------------------------------

    @staticmethod
    def _make_key(oracle_type: str, key: str) -> str:
        return f"{oracle_type}:{key}"

    def _evict_oldest(self, count: int) -> None:
        """Evict *count* entries with the earliest ``created_at``."""
        sorted_keys = sorted(
            self._store,
            key=lambda k: self._store[k].created_at,
        )
        for k in sorted_keys[:count]:
            del self._store[k]
            logger.debug("Cache evicted key %s", k)
