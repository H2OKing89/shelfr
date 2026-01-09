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
import hashlib
import json
import logging
from dataclasses import asdict, dataclass, field
from datetime import UTC, datetime
from pathlib import Path
from typing import Any, Protocol

from shelfr.metadata.providers.types import FieldName, IdType
from shelfr.paths import cache_dir as get_platform_cache_dir
from shelfr.utils.permissions import fix_ownership

logger = logging.getLogger(__name__)

# Schema version for cache invalidation
# Increment when CanonicalMetadata or ProviderResult structure changes
# 1.0.0 - Initial schema
# 1.1.0 - Added source provenance fields (Phase 10.3)
SCHEMA_VERSION = "1.1.0"


class CacheUnavailableError(Exception):
    """Raised when cache cannot be initialized (e.g., permission denied)."""

    pass


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
        raw_data: Original API response for backward compatibility
    """

    provider: str
    fields: dict[FieldName, Any]
    confidence: dict[FieldName, float]
    fetched_at: str  # ISO 8601 timestamp
    schema_version: str = SCHEMA_VERSION
    raw_data: dict[str, Any] = field(default_factory=dict)

    def is_expired(self, ttl_seconds: int) -> bool:
        """Check if cache entry has expired.

        Args:
            ttl_seconds: Time-to-live in seconds

        Returns:
            True if expired, False if still valid
        """
        fetched = datetime.fromisoformat(self.fetched_at)
        # Handle naive datetimes from legacy/corrupted cache entries
        if fetched.tzinfo is None:
            fetched = fetched.replace(tzinfo=UTC)
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
            raw_data=data.get("raw_data", {}),  # Backward compat for old cache entries
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

        Raises:
            CacheUnavailableError: If cache directory cannot be created
        """
        self.cache_dir = cache_dir
        try:
            self.cache_dir.mkdir(parents=True, exist_ok=True)
        except OSError as e:
            logger.warning(f"Failed to create cache directory {cache_dir}: {e}")
            raise CacheUnavailableError(f"Cache directory unavailable: {e}") from e

        # Cleanup orphaned .tmp files from crashed processes
        self._cleanup_tmp_files()

    def _cleanup_tmp_files(self) -> None:
        """Remove orphaned .tmp files from crashed processes.

        Called during __init__ to clean up temporary files that were not
        renamed to their final .json names due to process crashes.
        """
        try:
            for tmp_file in self.cache_dir.glob("*.tmp"):
                try:
                    tmp_file.unlink()
                    logger.debug(f"Removed orphaned tmp file: {tmp_file.name}")
                except OSError as e:
                    logger.warning(f"Failed to remove tmp file {tmp_file.name}: {e}")
        except OSError as e:
            logger.warning(f"Failed to scan for tmp files in {self.cache_dir}: {e}")

    def _get_cache_path(self, key: str) -> Path:
        """Get filesystem path for cache key.

        Uses sanitization and hash-based truncation for long keys to ensure
        filenames stay within filesystem limits (255 chars).

        Args:
            key: Cache key

        Returns:
            Path to cache file
        """
        safe_key = key.replace(":", "_").replace("/", "_")

        # Use hash for long filenames to stay within 255 char filesystem limit
        if len(safe_key) > 200:
            # Use hash with short prefix for debugging
            key_hash = hashlib.sha256(key.encode()).hexdigest()
            prefix = safe_key[:50]  # Keep first 50 chars for readability
            safe_key = f"{prefix}_{key_hash}"

        return self.cache_dir / f"{safe_key}.json"

    def _fix_file_ownership(self, path: Path) -> None:
        """Fix ownership on a cache file to target UID:GID.

        Uses settings.target_uid/target_gid (defaults to 99:100 for Unraid).
        Fails silently if settings unavailable or chown fails.

        Args:
            path: Path to the file to fix ownership on
        """
        try:
            from shelfr.config import get_settings

            settings = get_settings()
            fix_ownership(path, settings.target_uid, settings.target_gid)
        except Exception:
            # Fail silently - ownership fix is best-effort for cache files
            pass

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
        Fixes ownership to target UID:GID for Unraid compatibility.

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

            # Fix ownership to target UID:GID (e.g., Unraid's nobody:users 99:100)
            await asyncio.to_thread(self._fix_file_ownership, cache_path)
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
            paths = await asyncio.to_thread(
                lambda: list(self.cache_dir.glob(f"{safe_pattern}.json"))
            )
        except OSError as e:
            logger.warning(f"Cache invalidate pattern error for {pattern}: {e}")
            return

        # Best-effort deletion: continue on per-file errors
        for path in paths:
            try:
                await asyncio.to_thread(path.unlink, missing_ok=True)
            except OSError as e:
                logger.warning(f"Failed to delete cache file {path} for pattern {pattern}: {e}")

    async def clear(self) -> None:
        """Clear entire cache directory."""
        await self.invalidate_pattern("*")


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

    async def invalidate_pattern(self, pattern: str) -> None:
        """No-op."""
        pass

    async def clear(self) -> None:
        """No-op."""
        pass


# Singleton instance for default cache (lazy-initialized)
_default_cache: FileCache | NoOpCache | None = None


def get_default_cache() -> FileCache | NoOpCache:
    """Get default cache instance (lazy-initialized).

    Uses platform-appropriate cache directory (respects SHELFR_CACHE_DIR).
    Falls back to NoOpCache if cache directory cannot be created.

    Returns:
        FileCache instance, or NoOpCache if initialization fails
    """
    global _default_cache
    if _default_cache is None:
        cache_path = get_platform_cache_dir() / "metadata"
        try:
            _default_cache = FileCache(cache_dir=cache_path)
        except CacheUnavailableError:
            logger.warning("Falling back to NoOpCache due to cache initialization failure")
            _default_cache = NoOpCache()
    return _default_cache
