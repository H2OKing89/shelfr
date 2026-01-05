"""
Caching layer for metadata providers.

This module provides a schema-versioned cache to avoid repeated network calls
for the same metadata lookups. Cache keys auto-invalidate when schema changes.

Design principles:
- Schema-versioned keys (cache invalidates on CanonicalMetadata changes)
- Provider-agnostic (works with any MetadataProvider)
- Atomic writes to prevent corruption
- Configurable TTL and max size

Usage:
    cache = FileCache(cache_dir=Path("~/.cache/shelfr/metadata"))

    # Check cache before provider fetch
    key = make_cache_key("audnex", "asin", "B08G9PRS1K")
    cached = await cache.get(key)
    if cached and not cached.is_expired(ttl_seconds=30*24*3600):
        return ProviderResult.from_cached(cached)

    # Cache successful results
    result = await provider.fetch(ctx, id_type)
    if result.success:
        await cache.set(key, CachedResult.from_provider_result(result))
"""

from __future__ import annotations

import asyncio
import json
import logging
from dataclasses import asdict, dataclass
from datetime import UTC, datetime
from pathlib import Path
from typing import Any, Protocol

from shelfr.metadata.providers.types import FieldName, IdType

logger = logging.getLogger(__name__)

# Schema version for cache invalidation
# Increment when CanonicalMetadata or ProviderResult structure changes
SCHEMA_VERSION = "1.0.0"


def make_cache_key(
    provider: str,
    id_type: IdType,
    identifier: str,
    region: str = "us",
) -> str:
    """Build versioned cache key.

    Cache keys include schema version so they auto-invalidate when
    CanonicalMetadata or ProviderResult structure changes.

    Args:
        provider: Provider name (e.g., "audnex", "hardcover")
        id_type: Identifier type ("asin", "isbn", etc.)
        identifier: Actual identifier value
        region: Region code for region-aware APIs (default "us")

    Returns:
        Cache key string (e.g., "1.0.0:audnex:asin:B08G9PRS1K:us")
    """
    return f"{SCHEMA_VERSION}:{provider}:{id_type}:{identifier}:{region}"


@dataclass(frozen=True)
class CachedResult:
    """What we store in cache — enough to reconstruct ProviderResult.

    Attributes:
        provider: Provider name
        fields: Field values returned by provider
        confidence: Confidence scores per field
        fetched_at: When this was cached (ISO 8601 timestamp)
        schema_version: Schema version when cached (for migration)
    """

    provider: str
    fields: dict[FieldName, Any]
    confidence: dict[FieldName, float]
    fetched_at: str  # ISO 8601 timestamp
    schema_version: str = SCHEMA_VERSION

    def is_expired(self, ttl_seconds: int) -> bool:
        """Check if cache entry has expired.

        Args:
            ttl_seconds: Time-to-live in seconds

        Returns:
            True if expired, False if still valid
        """
        fetched = datetime.fromisoformat(self.fetched_at)
        age_seconds = (datetime.now(UTC) - fetched).total_seconds()
        return age_seconds > ttl_seconds

    def to_dict(self) -> dict[str, Any]:
        """Convert to JSON-serializable dict."""
        return asdict(self)

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> CachedResult:
        """Reconstruct from dict (cache read).

        Handles missing schema_version for old cache entries.
        """
        return cls(
            provider=data["provider"],
            fields=data["fields"],
            confidence=data["confidence"],
            fetched_at=data["fetched_at"],
            schema_version=data.get("schema_version", "0.0.0"),  # Legacy fallback
        )


class MetadataCache(Protocol):
    """Abstract caching interface.

    This protocol allows different cache backends (file, SQLite, Redis)
    without changing provider code.
    """

    async def get(self, key: str) -> CachedResult | None:
        """Retrieve cached result.

        Args:
            key: Cache key from make_cache_key()

        Returns:
            CachedResult if found, None if miss or error
        """
        ...

    async def set(self, key: str, result: CachedResult) -> None:
        """Store result in cache.

        Args:
            key: Cache key from make_cache_key()
            result: Result to cache
        """
        ...

    async def invalidate(self, key: str) -> None:
        """Remove specific cache entry.

        Args:
            key: Cache key to invalidate
        """
        ...

    async def invalidate_pattern(self, pattern: str) -> None:
        """Remove all cache entries matching pattern.

        Args:
            pattern: Glob pattern (e.g., "1.0.0:audnex:*")
        """
        ...

    async def clear(self) -> None:
        """Clear entire cache."""
        ...


class FileCache:
    """File-based JSON cache (simple, no dependencies).

    Each cache entry is a separate JSON file named by cache key hash.
    Supports concurrent access via atomic writes.

    Attributes:
        cache_dir: Directory for cache files
    """

    def __init__(self, cache_dir: Path):
        """Initialize file cache.

        Args:
            cache_dir: Directory to store cache files (created if needed)
        """
        self.cache_dir = cache_dir
        self.cache_dir.mkdir(parents=True, exist_ok=True)

    def _get_cache_path(self, key: str) -> Path:
        """Get filesystem path for cache key.

        Uses simple filename sanitization (replace : and / with _).
        For very long keys, could use hash instead.

        Args:
            key: Cache key

        Returns:
            Path to cache file
        """
        safe_key = key.replace(":", "_").replace("/", "_")
        return self.cache_dir / f"{safe_key}.json"

    async def get(self, key: str) -> CachedResult | None:
        """Retrieve cached result from JSON file.

        Args:
            key: Cache key

        Returns:
            CachedResult if found and valid JSON, None otherwise
        """
        cache_path = self._get_cache_path(key)
        if not cache_path.exists():
            return None

        try:
            # Read in thread pool to avoid blocking
            data = await asyncio.to_thread(cache_path.read_text, encoding="utf-8")
            parsed = json.loads(data)
            return CachedResult.from_dict(parsed)
        except (json.JSONDecodeError, KeyError, OSError) as e:
            logger.warning(f"Cache read error for {key}: {e}")
            # Delete corrupted cache file
            await asyncio.to_thread(cache_path.unlink, missing_ok=True)
            return None

    async def set(self, key: str, result: CachedResult) -> None:
        """Store result as JSON file with atomic write.

        Uses temp file + rename for atomicity (prevents corruption on crashes).

        Args:
            key: Cache key
            result: Result to cache
        """
        cache_path = self._get_cache_path(key)

        try:
            data = json.dumps(result.to_dict(), indent=2, ensure_ascii=False)

            # Atomic write: tmp file + rename
            tmp_path = cache_path.with_suffix(".tmp")
            await asyncio.to_thread(tmp_path.write_text, data, encoding="utf-8")
            await asyncio.to_thread(tmp_path.replace, cache_path)
        except OSError as e:
            logger.warning(f"Cache write error for {key}: {e}")

    async def invalidate(self, key: str) -> None:
        """Remove specific cache file.

        Args:
            key: Cache key to invalidate
        """
        cache_path = self._get_cache_path(key)
        try:
            await asyncio.to_thread(cache_path.unlink, missing_ok=True)
        except OSError as e:
            logger.warning(f"Cache invalidate error for {key}: {e}")

    async def invalidate_pattern(self, pattern: str) -> None:
        """Remove all cache files matching glob pattern.

        Args:
            pattern: Glob pattern (e.g., "1.0.0_audnex_*")
        """
        safe_pattern = pattern.replace(":", "_").replace("/", "_")
        try:
            for path in await asyncio.to_thread(
                lambda: list(self.cache_dir.glob(f"{safe_pattern}.json"))
            ):
                await asyncio.to_thread(path.unlink, missing_ok=True)
        except OSError as e:
            logger.warning(f"Cache invalidate pattern error for {pattern}: {e}")

    async def clear(self) -> None:
        """Clear entire cache directory."""
        await self.invalidate_pattern("*")


# Singleton instance for default cache (lazy-initialized)
class NoOpCache(MetadataCache):
    """Cache that doesn't store anything - for testing."""

    async def get(self, key: str) -> CachedResult | None:
        """Always return cache miss."""
        return None

    async def set(self, key: str, value: CachedResult) -> None:
        """No-op."""
        pass

    async def invalidate(self, key: str) -> None:
        """No-op."""
        pass


_default_cache: FileCache | None = None


def get_default_cache() -> FileCache:
    """Get default cache instance (lazy-initialized).

    Uses ~/.cache/shelfr/metadata by default.

    Returns:
        FileCache instance
    """
    global _default_cache
    if _default_cache is None:
        cache_dir = Path.home() / ".cache" / "shelfr" / "metadata"
        _default_cache = FileCache(cache_dir=cache_dir)
    return _default_cache
