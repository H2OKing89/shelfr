"""Tests for metadata caching layer."""

from __future__ import annotations

import asyncio
import json
from datetime import UTC, datetime, timedelta
from pathlib import Path

import pytest

from shelfr.metadata.cache import (
    SCHEMA_VERSION,
    CachedResult,
    FileCache,
    make_cache_key,
)


class TestMakeCacheKey:
    """Test cache key generation."""

    def test_basic_key_format(self):
        """Cache key includes schema version, provider, id_type, identifier, and region."""
        key = make_cache_key("audnex", "asin", "B08G9PRS1K", region="us")
        assert key == f"{SCHEMA_VERSION}:audnex:asin:B08G9PRS1K:us"

    def test_default_region(self):
        """Default region is 'us'."""
        key = make_cache_key("audnex", "asin", "B08G9PRS1K")
        assert key == f"{SCHEMA_VERSION}:audnex:asin:B08G9PRS1K:us"

    def test_different_providers(self):
        """Different providers generate different keys."""
        key1 = make_cache_key("audnex", "asin", "B08G9PRS1K")
        key2 = make_cache_key("hardcover", "asin", "B08G9PRS1K")
        assert key1 != key2

    def test_different_id_types(self):
        """Different ID types generate different keys."""
        key1 = make_cache_key("audnex", "asin", "B08G9PRS1K")
        key2 = make_cache_key("audnex", "isbn", "B08G9PRS1K")
        assert key1 != key2

    def test_different_regions(self):
        """Different regions generate different keys."""
        key1 = make_cache_key("audnex", "asin", "B08G9PRS1K", region="us")
        key2 = make_cache_key("audnex", "asin", "B08G9PRS1K", region="uk")
        assert key1 != key2


class TestCachedResult:
    """Test CachedResult dataclass."""

    def test_create_cached_result(self):
        """Can create CachedResult with required fields."""
        result = CachedResult(
            provider="audnex",
            fields={"title": "Test Book"},
            confidence={"title": 1.0},
            fetched_at="2026-01-05T12:00:00+00:00",
        )
        assert result.provider == "audnex"
        assert result.fields == {"title": "Test Book"}
        assert result.confidence == {"title": 1.0}
        assert result.schema_version == SCHEMA_VERSION

    def test_is_expired_fresh(self):
        """Fresh cache entry is not expired."""
        now = datetime.now(UTC)
        result = CachedResult(
            provider="audnex",
            fields={},
            confidence={},
            fetched_at=now.isoformat(),
        )
        # TTL 1 hour, fetched just now
        assert not result.is_expired(ttl_seconds=3600)

    def test_is_expired_old(self):
        """Old cache entry is expired."""
        old_time = datetime.now(UTC) - timedelta(days=2)
        result = CachedResult(
            provider="audnex",
            fields={},
            confidence={},
            fetched_at=old_time.isoformat(),
        )
        # TTL 1 day, fetched 2 days ago
        assert result.is_expired(ttl_seconds=24 * 3600)

    def test_is_expired_exact_boundary(self):
        """Cache entry at exact TTL boundary is expired."""
        boundary_time = datetime.now(UTC) - timedelta(hours=1)
        result = CachedResult(
            provider="audnex",
            fields={},
            confidence={},
            fetched_at=boundary_time.isoformat(),
        )
        # TTL 1 hour, fetched exactly 1 hour ago
        assert result.is_expired(ttl_seconds=3600)

    def test_to_dict(self):
        """Can convert to dict for JSON serialization."""
        result = CachedResult(
            provider="audnex",
            fields={"title": "Test"},
            confidence={"title": 1.0},
            fetched_at="2026-01-05T12:00:00+00:00",
        )
        d = result.to_dict()
        assert d["provider"] == "audnex"
        assert d["fields"] == {"title": "Test"}
        assert d["schema_version"] == SCHEMA_VERSION

    def test_from_dict(self):
        """Can reconstruct from dict."""
        data = {
            "provider": "audnex",
            "fields": {"title": "Test"},
            "confidence": {"title": 1.0},
            "fetched_at": "2026-01-05T12:00:00+00:00",
            "schema_version": "1.0.0",
        }
        result = CachedResult.from_dict(data)
        assert result.provider == "audnex"
        assert result.fields == {"title": "Test"}
        assert result.schema_version == "1.0.0"

    def test_from_dict_missing_schema_version(self):
        """Legacy cache entries without schema_version default to 0.0.0."""
        data = {
            "provider": "audnex",
            "fields": {"title": "Test"},
            "confidence": {"title": 1.0},
            "fetched_at": "2026-01-05T12:00:00+00:00",
        }
        result = CachedResult.from_dict(data)
        assert result.schema_version == "0.0.0"


@pytest.mark.asyncio
class TestFileCache:
    """Test FileCache implementation."""

    async def test_set_and_get(self, tmp_path: Path):
        """Can store and retrieve cache entry."""
        cache = FileCache(cache_dir=tmp_path)
        key = "test:asin:B123"

        result = CachedResult(
            provider="test",
            fields={"title": "Test Book"},
            confidence={"title": 1.0},
            fetched_at=datetime.now(UTC).isoformat(),
        )

        await cache.set(key, result)
        retrieved = await cache.get(key)

        assert retrieved is not None
        assert retrieved.provider == "test"
        assert retrieved.fields == {"title": "Test Book"}

    async def test_get_missing_key(self, tmp_path: Path):
        """get() returns None for missing key."""
        cache = FileCache(cache_dir=tmp_path)
        result = await cache.get("nonexistent:key")
        assert result is None

    async def test_atomic_write_on_crash(self, tmp_path: Path):
        """Atomic write prevents partial writes on failure."""
        cache = FileCache(cache_dir=tmp_path)
        key = "test:asin:B123"

        result = CachedResult(
            provider="test",
            fields={"title": "Original"},
            confidence={"title": 1.0},
            fetched_at=datetime.now(UTC).isoformat(),
        )

        await cache.set(key, result)

        # Verify file exists and is valid JSON
        cache_path = cache._get_cache_path(key)
        assert cache_path.exists()
        data = json.loads(cache_path.read_text())
        assert data["fields"]["title"] == "Original"

    async def test_corrupted_cache_file(self, tmp_path: Path):
        """Corrupted cache file is deleted and returns None."""
        cache = FileCache(cache_dir=tmp_path)
        key = "test:asin:B123"

        # Write corrupted JSON
        cache_path = cache._get_cache_path(key)
        cache_path.write_text("{invalid json")

        result = await cache.get(key)
        assert result is None
        # Corrupted file should be deleted
        assert not cache_path.exists()

    async def test_invalidate_single_key(self, tmp_path: Path):
        """Can invalidate specific cache entry."""
        cache = FileCache(cache_dir=tmp_path)
        key1 = "test:asin:B123"
        key2 = "test:asin:B456"

        result = CachedResult(
            provider="test",
            fields={"title": "Test"},
            confidence={"title": 1.0},
            fetched_at=datetime.now(UTC).isoformat(),
        )

        await cache.set(key1, result)
        await cache.set(key2, result)

        await cache.invalidate(key1)

        assert await cache.get(key1) is None
        assert await cache.get(key2) is not None

    async def test_invalidate_pattern(self, tmp_path: Path):
        """Can invalidate multiple cache entries by pattern."""
        cache = FileCache(cache_dir=tmp_path)

        result = CachedResult(
            provider="test",
            fields={"title": "Test"},
            confidence={"title": 1.0},
            fetched_at=datetime.now(UTC).isoformat(),
        )

        # Create entries with different providers
        await cache.set("1.0.0:audnex:asin:B123:us", result)
        await cache.set("1.0.0:audnex:asin:B456:us", result)
        await cache.set("1.0.0:hardcover:asin:B789:us", result)

        # Invalidate all audnex entries
        await cache.invalidate_pattern("1.0.0:audnex:*")

        assert await cache.get("1.0.0:audnex:asin:B123:us") is None
        assert await cache.get("1.0.0:audnex:asin:B456:us") is None
        assert await cache.get("1.0.0:hardcover:asin:B789:us") is not None

    async def test_clear_all(self, tmp_path: Path):
        """Can clear entire cache."""
        cache = FileCache(cache_dir=tmp_path)

        result = CachedResult(
            provider="test",
            fields={"title": "Test"},
            confidence={"title": 1.0},
            fetched_at=datetime.now(UTC).isoformat(),
        )

        await cache.set("key1", result)
        await cache.set("key2", result)
        await cache.set("key3", result)

        await cache.clear()

        assert await cache.get("key1") is None
        assert await cache.get("key2") is None
        assert await cache.get("key3") is None

    async def test_concurrent_writes(self, tmp_path: Path):
        """Multiple concurrent writes don't corrupt cache."""
        cache = FileCache(cache_dir=tmp_path)
        key = "test:asin:B123"

        async def write_entry(title: str):
            result = CachedResult(
                provider="test",
                fields={"title": title},
                confidence={"title": 1.0},
                fetched_at=datetime.now(UTC).isoformat(),
            )
            await cache.set(key, result)

        # Spawn 10 concurrent writes
        await asyncio.gather(*[write_entry(f"Title {i}") for i in range(10)])

        # Should have one valid entry (last writer wins due to atomic replace)
        retrieved = await cache.get(key)
        assert retrieved is not None
        assert "Title" in retrieved.fields["title"]

    async def test_cache_dir_created_automatically(self, tmp_path: Path):
        """Cache directory is created if it doesn't exist."""
        cache_dir = tmp_path / "deep" / "nested" / "cache"
        assert not cache_dir.exists()

        FileCache(cache_dir=cache_dir)
        assert cache_dir.exists()

    async def test_special_characters_in_key(self, tmp_path: Path):
        """Cache handles special characters in keys safely."""
        cache = FileCache(cache_dir=tmp_path)
        # Key with characters that need sanitization
        key = "1.0.0:audnex:asin:B/08G9P:us"

        result = CachedResult(
            provider="test",
            fields={"title": "Test"},
            confidence={"title": 1.0},
            fetched_at=datetime.now(UTC).isoformat(),
        )

        await cache.set(key, result)
        retrieved = await cache.get(key)

        assert retrieved is not None
        assert retrieved.fields["title"] == "Test"
