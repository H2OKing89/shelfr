"""
Region cache for ASIN → region mappings.

Phase 10.2: Caches which Audible region an ASIN was found in.
This enables single-request fast paths for subsequent lookups.

Cache entries track:
- Discovered region and timestamp
- Hit count for observability
- Failure tracking with type-aware invalidation:
  - NOT_FOUND (404): Fast invalidation (2 failures)
  - TRANSIENT (timeout/5xx): Slower invalidation (5 failures)
"""

from __future__ import annotations

import asyncio
import json
import logging
import os
from dataclasses import asdict, dataclass, field
from datetime import UTC, datetime
from enum import Enum
from pathlib import Path
from typing import Any

logger = logging.getLogger(__name__)


# =============================================================================
# Constants
# =============================================================================

# Invalidation thresholds
MAX_404_FAILURES = 2  # Fast invalidation for definitive 404s
MAX_TRANSIENT_FAILURES = 5  # Slower invalidation for transient errors

# Cache size limits
DEFAULT_MAX_ENTRIES = 50_000  # Maximum entries before LRU eviction
DEFAULT_TTL_DAYS = 90  # Entries older than this can be evicted


# =============================================================================
# Types
# =============================================================================


class FailureType(Enum):
    """Type of failure for cache invalidation decisions.

    NOT_FOUND: Definitive 404 - the mapping is probably wrong.
    TRANSIENT: Timeout/5xx/429 - might recover, don't invalidate immediately.
    """

    NOT_FOUND = "404"
    TRANSIENT = "transient"


@dataclass
class RegionCacheEntry:
    """Cache entry for ASIN → region mapping.

    Attributes:
        region: The Audible region code (us, uk, de, etc.)
        discovered_at: ISO 8601 timestamp when region was discovered
        last_accessed_at: ISO 8601 timestamp of last access (for LRU eviction)
        hits: Number of successful cache hits
        last_failed_at: ISO 8601 timestamp of last failure (if any)
        fail_count: Consecutive failure count (resets on success)
        last_failure_type: Type of last failure for invalidation decisions
    """

    region: str
    discovered_at: str = field(default_factory=lambda: datetime.now(UTC).isoformat())
    last_accessed_at: str = field(default_factory=lambda: datetime.now(UTC).isoformat())
    hits: int = 0
    last_failed_at: str | None = None
    fail_count: int = 0
    last_failure_type: str | None = None

    def to_dict(self) -> dict[str, Any]:
        """Convert to dictionary for JSON serialization."""
        return asdict(self)

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> RegionCacheEntry:
        """Create entry from dictionary."""
        now = datetime.now(UTC).isoformat()
        return cls(
            region=data["region"],
            discovered_at=data.get("discovered_at", now),
            last_accessed_at=data.get("last_accessed_at", now),
            hits=data.get("hits", 0),
            last_failed_at=data.get("last_failed_at"),
            fail_count=data.get("fail_count", 0),
            last_failure_type=data.get("last_failure_type"),
        )


# =============================================================================
# RegionCache Class
# =============================================================================


class RegionCache:
    """Persistent ASIN → region mapping cache with failure tracking.

    Thread-safe for asyncio: uses asyncio.Lock for concurrent write protection.
    Writes are atomic (temp file + rename) to prevent corruption.

    Usage:
        cache = RegionCache(Path("data/region_cache.json"))
        await cache.load()

        # Check cache
        region = await cache.get("B08G9PRS1K")

        # Store new mapping
        await cache.set("B08G9PRS1K", "us")

        # Record failure
        await cache.record_failure("B08G9PRS1K", FailureType.NOT_FOUND)

    Attributes:
        path: Path to the JSON cache file
    """

    def __init__(
        self,
        cache_path: Path,
        max_404_failures: int = MAX_404_FAILURES,
        max_transient_failures: int = MAX_TRANSIENT_FAILURES,
        max_entries: int = DEFAULT_MAX_ENTRIES,
        ttl_days: int = DEFAULT_TTL_DAYS,
    ):
        """Initialize region cache.

        Args:
            cache_path: Path to JSON cache file
            max_404_failures: Invalidation threshold for 404 errors
            max_transient_failures: Invalidation threshold for transient errors
            max_entries: Maximum entries before LRU eviction (default 50,000)
            ttl_days: Days after which entries can be evicted (default 90)
        """
        self._path = cache_path
        self._lock = asyncio.Lock()
        self._data: dict[str, RegionCacheEntry] = {}
        self._loaded = False
        self._max_404_failures = max_404_failures
        self._max_transient_failures = max_transient_failures
        self._max_entries = max_entries
        self._ttl_days = ttl_days

    async def load(self) -> None:
        """Load cache from disk.

        Creates empty cache file if it doesn't exist.
        Safe to call multiple times (no-op after first load).
        """
        if self._loaded:
            return

        async with self._lock:
            if self._loaded:  # Double-check after acquiring lock
                return

            if self._path.exists():
                try:
                    raw = self._path.read_text(encoding="utf-8")
                    data = json.loads(raw)
                    self._data = {
                        asin: RegionCacheEntry.from_dict(entry) for asin, entry in data.items()
                    }
                    logger.debug(
                        "Loaded region cache with %d entries from %s",
                        len(self._data),
                        self._path,
                    )
                except (json.JSONDecodeError, KeyError) as e:
                    logger.warning(
                        "Failed to load region cache from %s: %s (starting fresh)",
                        self._path,
                        e,
                    )
                    self._data = {}
            else:
                logger.debug("Region cache file not found, starting fresh: %s", self._path)
                self._data = {}
                # Create parent directories if needed
                self._path.parent.mkdir(parents=True, exist_ok=True)

            self._loaded = True

    async def get(self, asin: str) -> str | None:
        """Get cached region for ASIN.

        Increments hit counter and updates last_accessed_at on cache hit.

        Args:
            asin: ASIN to look up

        Returns:
            Region code or None if not cached
        """
        await self.load()

        asin_upper = asin.upper()

        async with self._lock:
            entry = self._data.get(asin_upper)

            if entry:
                # Update access tracking (for LRU eviction)
                entry.hits += 1
                entry.last_accessed_at = datetime.now(UTC).isoformat()
                logger.debug("Region cache hit: %s → %s (hits: %d)", asin, entry.region, entry.hits)
                return entry.region

        logger.debug("Region cache miss: %s", asin)
        return None

    async def set(self, asin: str, region: str) -> None:
        """Store or update ASIN → region mapping.

        Resets failure tracking on successful set.
        Triggers LRU eviction if cache exceeds max_entries.

        Args:
            asin: ASIN to cache
            region: Region where ASIN was found
        """
        await self.load()

        asin_upper = asin.upper()

        async with self._lock:
            existing = self._data.get(asin_upper)

            if existing and existing.region == region:
                # Same region, just reset failure tracking and update access time
                existing.fail_count = 0
                existing.last_failed_at = None
                existing.last_failure_type = None
                existing.last_accessed_at = datetime.now(UTC).isoformat()
                logger.debug("Region cache refreshed: %s → %s", asin, region)
            else:
                # New entry or region changed
                self._data[asin_upper] = RegionCacheEntry(region=region)
                if existing:
                    logger.info(
                        "Region cache updated: %s changed from %s → %s",
                        asin,
                        existing.region,
                        region,
                    )
                else:
                    logger.debug("Region cache set: %s → %s", asin, region)

            # Evict if over limit
            await self._maybe_evict()

            await self._atomic_write()

    async def record_failure(self, asin: str, failure_type: FailureType) -> bool:
        """Record a failure for cached ASIN.

        Increments failure counter and invalidates entry if threshold exceeded.
        Different thresholds for different failure types:
        - NOT_FOUND (404): Fast invalidation (mapping is wrong)
        - TRANSIENT (timeout/5xx): Slower invalidation (might recover)

        Args:
            asin: ASIN that failed
            failure_type: Type of failure

        Returns:
            True if entry was invalidated, False otherwise
        """
        await self.load()

        asin_upper = asin.upper()

        async with self._lock:
            entry = self._data.get(asin_upper)
            if not entry:
                return False

            entry.fail_count += 1
            entry.last_failed_at = datetime.now(UTC).isoformat()
            entry.last_failure_type = failure_type.value

            # Determine threshold based on failure type
            threshold = (
                self._max_404_failures
                if failure_type == FailureType.NOT_FOUND
                else self._max_transient_failures
            )

            if entry.fail_count >= threshold:
                del self._data[asin_upper]
                logger.info(
                    "Region cache invalidated: %s (region=%s, failure_type=%s, count=%d)",
                    asin,
                    entry.region,
                    failure_type.value,
                    entry.fail_count,
                )
                await self._atomic_write()
                return True

            logger.debug(
                "Region cache failure recorded: %s (region=%s, type=%s, count=%d/%d)",
                asin,
                entry.region,
                failure_type.value,
                entry.fail_count,
                threshold,
            )
            await self._atomic_write()
            return False

    async def record_success(self, asin: str) -> None:
        """Record a successful fetch, resetting failure tracking.

        Call this when a cached region lookup succeeds.

        Args:
            asin: ASIN that succeeded
        """
        await self.load()

        asin_upper = asin.upper()

        async with self._lock:
            entry = self._data.get(asin_upper)
            if entry and entry.fail_count > 0:
                entry.fail_count = 0
                entry.last_failed_at = None
                entry.last_failure_type = None
                await self._atomic_write()
                logger.debug("Region cache success recorded, failures reset: %s", asin)

    async def remove(self, asin: str) -> bool:
        """Remove an entry from the cache.

        Args:
            asin: ASIN to remove

        Returns:
            True if entry was removed, False if not found
        """
        await self.load()

        asin_upper = asin.upper()

        async with self._lock:
            if asin_upper in self._data:
                del self._data[asin_upper]
                await self._atomic_write()
                logger.debug("Region cache entry removed: %s", asin)
                return True
            return False

    async def clear(self) -> None:
        """Clear all cache entries."""
        async with self._lock:
            self._data = {}
            await self._atomic_write()
            logger.info("Region cache cleared")

    async def get_stats(self) -> dict[str, Any]:
        """Get cache statistics for debugging.

        Returns:
            Dictionary with cache stats including:
            - total_entries: Total cached ASINs
            - region_distribution: Count of ASINs per region
            - total_hits: Sum of all hit counters
            - entries_with_failures: Count of entries with non-zero fail_count
        """
        await self.load()

        region_counts: dict[str, int] = {}
        total_hits = 0
        entries_with_failures = 0

        for entry in self._data.values():
            region_counts[entry.region] = region_counts.get(entry.region, 0) + 1
            total_hits += entry.hits
            if entry.fail_count > 0:
                entries_with_failures += 1

        return {
            "total_entries": len(self._data),
            "region_distribution": region_counts,
            "total_hits": total_hits,
            "entries_with_failures": entries_with_failures,
        }

    async def _atomic_write(self) -> None:
        """Write cache to disk atomically.

        Uses temp file + rename pattern for atomic writes on POSIX.
        Must be called while holding self._lock.
        """
        # Convert entries to dicts
        data = {asin: entry.to_dict() for asin, entry in self._data.items()}

        # Write to temp file
        tmp_path = self._path.with_suffix(".tmp")
        try:
            tmp_path.write_text(
                json.dumps(data, indent=2, sort_keys=True),
                encoding="utf-8",
            )
            # Atomic replace (cross-platform: works on both POSIX and Windows)
            os.replace(tmp_path, self._path)
        except OSError as e:
            logger.error("Failed to write region cache: %s", e)
            # Clean up temp file if it exists
            if tmp_path.exists():
                tmp_path.unlink()
            raise

    async def _maybe_evict(self) -> None:
        """Evict entries if cache exceeds max_entries.

        Uses LRU strategy based on last_accessed_at.
        Also evicts entries older than TTL first.
        Must be called while holding self._lock.
        """
        if len(self._data) <= self._max_entries:
            return

        # Calculate how many to evict (evict 10% to avoid frequent evictions)
        num_to_evict = max(1, len(self._data) - self._max_entries + int(self._max_entries * 0.1))

        # Build list with (asin, last_accessed_at, is_stale) for sorting
        now = datetime.now(UTC)

        entries_with_age: list[tuple[str, str, bool]] = []
        for asin, entry in self._data.items():
            # Check if entry is stale (older than TTL)
            try:
                discovered = datetime.fromisoformat(entry.discovered_at.replace("Z", "+00:00"))
                is_stale = (now - discovered).days > self._ttl_days
            except (ValueError, AttributeError):
                is_stale = True  # Can't parse = treat as stale

            entries_with_age.append((asin, entry.last_accessed_at, is_stale))

        # Sort: stale entries first, then by last_accessed_at (oldest first)
        entries_with_age.sort(key=lambda x: (not x[2], x[1]))

        # Evict the oldest/stalest entries
        evicted = 0
        for asin, _last_accessed, _is_stale in entries_with_age[:num_to_evict]:
            del self._data[asin]
            evicted += 1

        if evicted > 0:
            logger.info(
                "Region cache evicted %d entries (size: %d → %d, max: %d)",
                evicted,
                evicted + len(self._data),
                len(self._data),
                self._max_entries,
            )

    def __len__(self) -> int:
        """Return number of cached entries."""
        return len(self._data)

    def __contains__(self, asin: str) -> bool:
        """Check if ASIN is in cache (sync, for testing)."""
        return asin.upper() in self._data


# =============================================================================
# Module-level Default Cache
# =============================================================================

# Default cache instance - lazily initialized
_default_cache: RegionCache | None = None


def get_default_region_cache() -> RegionCache:
    """Get or create the default region cache instance.

    Uses data/region_cache.json by default.

    Returns:
        Default RegionCache instance
    """
    global _default_cache
    if _default_cache is None:
        # Import here to avoid circular imports
        from shelfr.paths import data_dir

        cache_path = data_dir() / "region_cache.json"
        _default_cache = RegionCache(cache_path)
    return _default_cache


def reset_default_region_cache() -> None:
    """Reset the default cache instance (for testing)."""
    global _default_cache
    _default_cache = None
