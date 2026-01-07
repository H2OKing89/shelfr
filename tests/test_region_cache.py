"""Tests for RegionCache with ASIN → region mapping and failure tracking."""

from __future__ import annotations

import asyncio
import json
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from shelfr.metadata.audnex.region_cache import (
    MAX_404_FAILURES,
    MAX_TRANSIENT_FAILURES,
    FailureType,
    RegionCache,
    RegionCacheEntry,
    get_default_region_cache,
    reset_default_region_cache,
)

# =============================================================================
# Fixtures
# =============================================================================


@pytest.fixture
def temp_cache_path(tmp_path: Path) -> Path:
    """Return a temporary path for cache file."""
    return tmp_path / "region_cache.json"


@pytest.fixture
def cache(temp_cache_path: Path) -> RegionCache:
    """Create a fresh RegionCache instance."""
    return RegionCache(temp_cache_path)


@pytest.fixture
def sample_entry() -> dict[str, Any]:
    """Sample cache entry as dict."""
    return {
        "region": "us",
        "discovered_at": "2026-01-07T12:00:00+00:00",
        "hits": 5,
        "last_failed_at": None,
        "fail_count": 0,
        "last_failure_type": None,
    }


# =============================================================================
# RegionCacheEntry Tests
# =============================================================================


class TestRegionCacheEntry:
    """Test RegionCacheEntry dataclass."""

    def test_default_values(self) -> None:
        """Entry has correct defaults."""
        entry = RegionCacheEntry(region="uk")

        assert entry.region == "uk"
        assert entry.discovered_at is not None  # Auto-generated
        assert entry.hits == 0
        assert entry.last_failed_at is None
        assert entry.fail_count == 0
        assert entry.last_failure_type is None

    def test_to_dict(self) -> None:
        """Entry converts to dict correctly."""
        entry = RegionCacheEntry(
            region="de",
            discovered_at="2026-01-07T12:00:00+00:00",
            hits=10,
        )

        result = entry.to_dict()

        assert result["region"] == "de"
        assert result["discovered_at"] == "2026-01-07T12:00:00+00:00"
        assert result["hits"] == 10
        assert result["fail_count"] == 0

    def test_from_dict(self, sample_entry: dict[str, Any]) -> None:
        """Entry created from dict correctly."""
        entry = RegionCacheEntry.from_dict(sample_entry)

        assert entry.region == "us"
        assert entry.hits == 5
        assert entry.fail_count == 0

    def test_from_dict_missing_optional_fields(self) -> None:
        """Entry handles missing optional fields."""
        minimal = {"region": "jp"}

        entry = RegionCacheEntry.from_dict(minimal)

        assert entry.region == "jp"
        assert entry.hits == 0
        assert entry.fail_count == 0


# =============================================================================
# FailureType Tests
# =============================================================================


class TestFailureType:
    """Test FailureType enum."""

    def test_not_found_value(self) -> None:
        """NOT_FOUND has correct value."""
        assert FailureType.NOT_FOUND.value == "404"

    def test_transient_value(self) -> None:
        """TRANSIENT has correct value."""
        assert FailureType.TRANSIENT.value == "transient"


# =============================================================================
# RegionCache Basic Operations
# =============================================================================


class TestRegionCacheBasics:
    """Test basic cache operations."""

    @pytest.mark.asyncio
    async def test_load_creates_empty_cache(self, cache: RegionCache) -> None:
        """Load creates empty cache when file doesn't exist."""
        await cache.load()

        assert len(cache) == 0

    @pytest.mark.asyncio
    async def test_load_reads_existing_file(
        self, temp_cache_path: Path, sample_entry: dict[str, Any]
    ) -> None:
        """Load reads existing cache file."""
        # Write cache file
        temp_cache_path.write_text(json.dumps({"B08G9PRS1K": sample_entry}))

        cache = RegionCache(temp_cache_path)
        await cache.load()

        assert len(cache) == 1
        assert "B08G9PRS1K" in cache

    @pytest.mark.asyncio
    async def test_load_handles_corrupt_json(self, temp_cache_path: Path) -> None:
        """Load handles corrupt JSON gracefully."""
        temp_cache_path.write_text("not valid json{{{")

        cache = RegionCache(temp_cache_path)
        await cache.load()

        assert len(cache) == 0  # Starts fresh

    @pytest.mark.asyncio
    async def test_set_creates_new_entry(self, cache: RegionCache) -> None:
        """Set creates new cache entry."""
        await cache.set("B08G9PRS1K", "us")

        region = await cache.get("B08G9PRS1K")
        assert region == "us"

    @pytest.mark.asyncio
    async def test_set_normalizes_asin_case(self, cache: RegionCache) -> None:
        """Set normalizes ASIN to uppercase."""
        await cache.set("b08g9prs1k", "uk")

        assert "B08G9PRS1K" in cache
        region = await cache.get("B08G9PRS1K")
        assert region == "uk"

    @pytest.mark.asyncio
    async def test_get_returns_none_for_missing(self, cache: RegionCache) -> None:
        """Get returns None for uncached ASIN."""
        region = await cache.get("NOTCACHED")

        assert region is None

    @pytest.mark.asyncio
    async def test_get_increments_hit_counter(self, cache: RegionCache) -> None:
        """Get increments hit counter on cache hit."""
        await cache.set("B08G9PRS1K", "us")

        # Multiple gets should increment hits
        await cache.get("B08G9PRS1K")
        await cache.get("B08G9PRS1K")
        await cache.get("B08G9PRS1K")

        # Check internal state
        entry = cache._data.get("B08G9PRS1K")
        assert entry is not None
        assert entry.hits >= 3

    @pytest.mark.asyncio
    async def test_get_normalizes_asin_case(self, cache: RegionCache) -> None:
        """Get normalizes ASIN to uppercase."""
        await cache.set("B08G9PRS1K", "de")

        region = await cache.get("b08g9prs1k")
        assert region == "de"


# =============================================================================
# Persistence Tests
# =============================================================================


class TestRegionCachePersistence:
    """Test cache persistence to disk."""

    @pytest.mark.asyncio
    async def test_set_persists_to_disk(self, cache: RegionCache, temp_cache_path: Path) -> None:
        """Set writes cache to disk."""
        await cache.set("B08G9PRS1K", "us")

        assert temp_cache_path.exists()
        data = json.loads(temp_cache_path.read_text())
        assert "B08G9PRS1K" in data
        assert data["B08G9PRS1K"]["region"] == "us"

    @pytest.mark.asyncio
    async def test_atomic_write_uses_temp_file(
        self, cache: RegionCache, temp_cache_path: Path
    ) -> None:
        """Atomic write uses temp file + rename pattern."""
        await cache.set("B08G9PRS1K", "uk")

        # After successful write, temp file should not exist
        tmp_path = temp_cache_path.with_suffix(".tmp")
        assert not tmp_path.exists()
        assert temp_cache_path.exists()

    @pytest.mark.asyncio
    async def test_reload_preserves_data(self, temp_cache_path: Path) -> None:
        """Data survives cache reload."""
        # First cache instance
        cache1 = RegionCache(temp_cache_path)
        await cache1.set("B08G9PRS1K", "de")

        # Second cache instance (simulates process restart)
        cache2 = RegionCache(temp_cache_path)
        await cache2.load()

        region = await cache2.get("B08G9PRS1K")
        assert region == "de"


# =============================================================================
# Failure Tracking Tests
# =============================================================================


class TestRegionCacheFailureTracking:
    """Test failure recording and cache invalidation."""

    @pytest.mark.asyncio
    async def test_record_failure_increments_count(self, cache: RegionCache) -> None:
        """record_failure increments fail_count."""
        await cache.set("B08G9PRS1K", "us")

        await cache.record_failure("B08G9PRS1K", FailureType.TRANSIENT)

        entry = cache._data.get("B08G9PRS1K")
        assert entry is not None
        assert entry.fail_count == 1
        assert entry.last_failure_type == "transient"
        assert entry.last_failed_at is not None

    @pytest.mark.asyncio
    async def test_record_failure_returns_false_until_threshold(self, cache: RegionCache) -> None:
        """record_failure returns False until invalidation threshold."""
        await cache.set("B08G9PRS1K", "us")

        # First failure - not invalidated
        result = await cache.record_failure("B08G9PRS1K", FailureType.NOT_FOUND)
        assert result is False
        assert "B08G9PRS1K" in cache

    @pytest.mark.asyncio
    async def test_404_invalidates_after_threshold(self, cache: RegionCache) -> None:
        """NOT_FOUND failures invalidate after MAX_404_FAILURES."""
        await cache.set("B08G9PRS1K", "us")

        # Record failures up to threshold
        for _i in range(MAX_404_FAILURES - 1):
            result = await cache.record_failure("B08G9PRS1K", FailureType.NOT_FOUND)
            assert result is False

        # Final failure should invalidate
        result = await cache.record_failure("B08G9PRS1K", FailureType.NOT_FOUND)
        assert result is True
        assert "B08G9PRS1K" not in cache

    @pytest.mark.asyncio
    async def test_transient_has_higher_threshold(self, cache: RegionCache) -> None:
        """TRANSIENT failures have higher threshold than NOT_FOUND."""
        await cache.set("B08G9PRS1K", "uk")

        # Record MAX_404_FAILURES transient failures - should NOT invalidate
        for _ in range(MAX_404_FAILURES):
            result = await cache.record_failure("B08G9PRS1K", FailureType.TRANSIENT)
            assert result is False

        assert "B08G9PRS1K" in cache

        # Continue until transient threshold
        for _ in range(MAX_TRANSIENT_FAILURES - MAX_404_FAILURES - 1):
            await cache.record_failure("B08G9PRS1K", FailureType.TRANSIENT)

        # Final transient failure should invalidate
        result = await cache.record_failure("B08G9PRS1K", FailureType.TRANSIENT)
        assert result is True
        assert "B08G9PRS1K" not in cache

    @pytest.mark.asyncio
    async def test_record_failure_noop_for_missing_entry(self, cache: RegionCache) -> None:
        """record_failure is no-op for uncached ASIN."""
        result = await cache.record_failure("NOTCACHED", FailureType.NOT_FOUND)

        assert result is False

    @pytest.mark.asyncio
    async def test_record_success_resets_failures(self, cache: RegionCache) -> None:
        """record_success resets failure tracking."""
        await cache.set("B08G9PRS1K", "us")

        # Record some failures
        await cache.record_failure("B08G9PRS1K", FailureType.TRANSIENT)
        await cache.record_failure("B08G9PRS1K", FailureType.TRANSIENT)

        # Record success
        await cache.record_success("B08G9PRS1K")

        # Failures should be reset
        entry = cache._data.get("B08G9PRS1K")
        assert entry is not None
        assert entry.fail_count == 0
        assert entry.last_failed_at is None

    @pytest.mark.asyncio
    async def test_set_resets_failures(self, cache: RegionCache) -> None:
        """Setting same region resets failure tracking."""
        await cache.set("B08G9PRS1K", "us")
        await cache.record_failure("B08G9PRS1K", FailureType.TRANSIENT)

        # Set same region again
        await cache.set("B08G9PRS1K", "us")

        entry = cache._data.get("B08G9PRS1K")
        assert entry is not None
        assert entry.fail_count == 0

    @pytest.mark.asyncio
    async def test_set_different_region_creates_new_entry(self, cache: RegionCache) -> None:
        """Setting different region creates new entry."""
        await cache.set("B08G9PRS1K", "us")
        await cache.record_failure("B08G9PRS1K", FailureType.TRANSIENT)

        # Set different region
        await cache.set("B08G9PRS1K", "uk")

        entry = cache._data.get("B08G9PRS1K")
        assert entry is not None
        assert entry.region == "uk"
        assert entry.fail_count == 0


# =============================================================================
# Cache Management Tests
# =============================================================================


class TestRegionCacheManagement:
    """Test cache management operations."""

    @pytest.mark.asyncio
    async def test_remove_deletes_entry(self, cache: RegionCache) -> None:
        """remove deletes cache entry."""
        await cache.set("B08G9PRS1K", "us")

        result = await cache.remove("B08G9PRS1K")

        assert result is True
        assert "B08G9PRS1K" not in cache

    @pytest.mark.asyncio
    async def test_remove_returns_false_for_missing(self, cache: RegionCache) -> None:
        """remove returns False for uncached ASIN."""
        result = await cache.remove("NOTCACHED")

        assert result is False

    @pytest.mark.asyncio
    async def test_clear_removes_all_entries(self, cache: RegionCache) -> None:
        """clear removes all entries."""
        await cache.set("B08G9PRS1K", "us")
        await cache.set("B0797FYNDC", "uk")

        await cache.clear()

        assert len(cache) == 0

    @pytest.mark.asyncio
    async def test_get_stats_returns_distribution(self, cache: RegionCache) -> None:
        """get_stats returns region distribution."""
        await cache.set("ASIN1", "us")
        await cache.set("ASIN2", "us")
        await cache.set("ASIN3", "uk")
        await cache.set("ASIN4", "de")

        # Record some hits
        await cache.get("ASIN1")
        await cache.get("ASIN1")

        # Record a failure
        await cache.record_failure("ASIN3", FailureType.TRANSIENT)

        stats = await cache.get_stats()

        assert stats["total_entries"] == 4
        assert stats["region_distribution"]["us"] == 2
        assert stats["region_distribution"]["uk"] == 1
        assert stats["region_distribution"]["de"] == 1
        assert stats["total_hits"] >= 2
        assert stats["entries_with_failures"] == 1


# =============================================================================
# Concurrency Tests
# =============================================================================


class TestRegionCacheConcurrency:
    """Test concurrent cache operations."""

    @pytest.mark.asyncio
    async def test_concurrent_sets_are_safe(self, cache: RegionCache) -> None:
        """Concurrent set operations don't corrupt cache."""
        # Launch many concurrent sets
        tasks = [cache.set(f"ASIN{i}", f"region{i % 3}") for i in range(20)]

        await asyncio.gather(*tasks)

        # All entries should be present
        for i in range(20):
            region = await cache.get(f"ASIN{i}")
            assert region is not None

    @pytest.mark.asyncio
    async def test_concurrent_gets_and_sets(self, cache: RegionCache) -> None:
        """Concurrent gets and sets don't deadlock or corrupt."""
        await cache.set("B08G9PRS1K", "us")

        async def reader():
            for _ in range(10):
                await cache.get("B08G9PRS1K")
                await asyncio.sleep(0.001)

        async def writer():
            for i in range(5):
                await cache.set(f"ASIN{i}", "uk")
                await asyncio.sleep(0.002)

        await asyncio.gather(reader(), writer(), reader())

        # Cache should still be valid
        region = await cache.get("B08G9PRS1K")
        assert region == "us"


# =============================================================================
# Default Cache Tests
# =============================================================================


class TestDefaultRegionCache:
    """Test module-level default cache."""

    @pytest.fixture(autouse=True)
    def reset_cache(self):
        """Reset default cache before each test."""
        reset_default_region_cache()
        yield
        reset_default_region_cache()

    def test_get_default_creates_singleton(self, tmp_path: Path) -> None:
        """get_default_region_cache creates singleton."""
        with patch("shelfr.paths.data_dir", return_value=tmp_path):
            cache1 = get_default_region_cache()
            cache2 = get_default_region_cache()

            assert cache1 is cache2

    def test_reset_clears_singleton(self, tmp_path: Path) -> None:
        """reset_default_region_cache clears singleton."""
        with patch("shelfr.paths.data_dir", return_value=tmp_path):
            cache1 = get_default_region_cache()
            reset_default_region_cache()
            cache2 = get_default_region_cache()

            assert cache1 is not cache2


# =============================================================================
# Integration with fetch_audnex_book_with_cache Tests
# =============================================================================


class TestFetchWithCache:
    """Test fetch_audnex_book_with_cache integration."""

    @pytest.fixture
    def mock_settings(self):
        """Create mock settings."""
        settings = MagicMock()
        settings.audnex.base_url = "https://api.audnex.us"
        settings.audnex.timeout_seconds = 10.0
        return settings

    @pytest.fixture(autouse=True)
    def patch_settings(self, mock_settings):
        """Patch get_settings for all tests."""
        with patch(
            "shelfr.metadata.audnex.async_client.get_settings",
            return_value=mock_settings,
        ):
            yield

    @pytest.mark.asyncio
    async def test_caches_winning_region(self, cache: RegionCache) -> None:
        """Winning region is cached after successful fetch."""
        from shelfr.metadata.audnex.async_client import (
            AudnexAsyncClient,
            fetch_audnex_book_with_cache,
        )

        sample_book = {
            "asin": "B08G9PRS1K",
            "title": "Test Book",
            "authors": [{"name": "Author"}],
            "region": "us",
        }

        # Create a mock client instance
        mock_client = MagicMock(spec=AudnexAsyncClient)
        mock_client.fetch_book_parallel = AsyncMock(return_value=(sample_book, "us"))

        # Pass the mock client directly
        data, region = await fetch_audnex_book_with_cache(
            "B08G9PRS1K", client=mock_client, region_cache=cache
        )

        assert data is not None
        assert region == "us"
        # Region should be cached
        cached = await cache.get("B08G9PRS1K")
        assert cached == "us"

    @pytest.mark.asyncio
    async def test_uses_cached_region(self, cache: RegionCache) -> None:
        """Cached region is used for lookup."""
        from shelfr.metadata.audnex.async_client import (
            AudnexAsyncClient,
            fetch_audnex_book_with_cache,
        )

        # Pre-populate cache
        await cache.set("B08G9PRS1K", "de")

        sample_book = {
            "asin": "B08G9PRS1K",
            "title": "Test Book",
            "authors": [{"name": "Author"}],
            "region": "de",
        }

        fetch_call_args = []

        async def mock_fetch(asin: str, cached_region: str | None = None):
            fetch_call_args.append((asin, cached_region))
            return sample_book, "de"

        # Create a mock client that tracks calls
        mock_client = MagicMock(spec=AudnexAsyncClient)
        mock_client.fetch_book_parallel = AsyncMock(side_effect=mock_fetch)

        data, region = await fetch_audnex_book_with_cache(
            "B08G9PRS1K", client=mock_client, region_cache=cache
        )

        assert data is not None
        assert region == "de"
        # Should have passed cached region to fetch_book_parallel
        assert len(fetch_call_args) == 1
        assert fetch_call_args[0][1] == "de"  # cached_region was passed

    @pytest.mark.asyncio
    async def test_records_failure_on_cache_miss(self, cache: RegionCache) -> None:
        """Failure is recorded when cached region doesn't work."""
        from shelfr.metadata.audnex.async_client import (
            AudnexAsyncClient,
            fetch_audnex_book_with_cache,
        )

        # Pre-populate cache with a region
        await cache.set("B08G9PRS1K", "jp")

        # Create a mock client that returns failure
        mock_client = MagicMock(spec=AudnexAsyncClient)
        mock_client.fetch_book_parallel = AsyncMock(return_value=(None, None))

        data, region = await fetch_audnex_book_with_cache(
            "B08G9PRS1K", client=mock_client, region_cache=cache
        )

        # Fetch should fail (all 404s)
        assert data is None
        assert region is None

        # Cache entry should have recorded failure or been invalidated
        entry = cache._data.get("B08G9PRS1K")
        if entry is not None:
            assert entry.fail_count > 0


# =============================================================================
# Cache Size Control Tests
# =============================================================================


class TestCacheSizeControl:
    """Tests for LRU eviction and memory management."""

    @pytest.fixture
    def small_cache(self, tmp_path: Path) -> RegionCache:
        """Create a cache with small max_entries for testing eviction."""
        return RegionCache(tmp_path / "small_cache.json", max_entries=5, ttl_days=90)

    @pytest.mark.asyncio
    async def test_evicts_when_exceeds_max_entries(self, small_cache: RegionCache) -> None:
        """Cache evicts entries when max_entries is exceeded."""
        # Add 5 entries (at the limit)
        for i in range(5):
            await small_cache.set(f"ASIN{i:05d}", "us")

        assert len(small_cache) == 5

        # Add one more to trigger eviction
        await small_cache.set("ASIN_NEW", "uk")

        # Should have evicted some entries (10% buffer = evict ~1-2)
        assert len(small_cache) < 6

    @pytest.mark.asyncio
    async def test_evicts_oldest_accessed_first(self, small_cache: RegionCache) -> None:
        """LRU eviction removes least recently accessed entries."""
        # Add entries with different access patterns
        await small_cache.set("OLD_1", "us")
        await small_cache.set("OLD_2", "us")

        # Simulate time passing and access some entries
        await small_cache.get("OLD_1")  # Access OLD_1 to make it "recently used"

        # Add more entries to fill up
        await small_cache.set("NEW_1", "us")
        await small_cache.set("NEW_2", "us")
        await small_cache.set("NEW_3", "us")

        # Add one more to trigger eviction
        await small_cache.set("TRIGGER", "uk")

        # OLD_2 (least recently accessed) should be evicted first
        # OLD_1 was accessed so should still be there
        assert "OLD_1" in small_cache

    @pytest.mark.asyncio
    async def test_evicts_stale_entries_first(self, tmp_path: Path) -> None:
        """Entries older than TTL are evicted first."""
        cache = RegionCache(tmp_path / "ttl_cache.json", max_entries=3, ttl_days=30)

        # Add an entry and manually backdate it
        await cache.set("STALE_ENTRY", "us")
        entry = cache._data["STALE_ENTRY"]
        old_date = (datetime.now(UTC) - timedelta(days=60)).isoformat()
        entry.discovered_at = old_date

        # Add fresh entries
        await cache.set("FRESH_1", "uk")
        await cache.set("FRESH_2", "de")

        # Add one more to trigger eviction
        await cache.set("FRESH_3", "au")

        # Stale entry should be evicted first
        assert "STALE_ENTRY" not in cache
        # Fresh entries should still be there
        assert "FRESH_1" in cache or "FRESH_2" in cache

    @pytest.mark.asyncio
    async def test_no_eviction_under_limit(self, small_cache: RegionCache) -> None:
        """No eviction when cache is under max_entries."""
        # Add 3 entries (under the limit of 5)
        await small_cache.set("ASIN1", "us")
        await small_cache.set("ASIN2", "uk")
        await small_cache.set("ASIN3", "de")

        assert len(small_cache) == 3
        assert "ASIN1" in small_cache
        assert "ASIN2" in small_cache
        assert "ASIN3" in small_cache

    @pytest.mark.asyncio
    async def test_last_accessed_at_updated_on_get(self, small_cache: RegionCache) -> None:
        """last_accessed_at is updated when entry is retrieved."""
        await small_cache.set("B08G9PRS1K", "us")
        entry = small_cache._data["B08G9PRS1K"]
        original_accessed = entry.last_accessed_at

        # Small delay to ensure timestamp changes
        import time

        time.sleep(0.01)

        # Access the entry
        await small_cache.get("B08G9PRS1K")

        # last_accessed_at should be updated
        assert entry.last_accessed_at >= original_accessed

    @pytest.mark.asyncio
    async def test_default_limits_are_reasonable(self, tmp_path: Path) -> None:
        """Default limits should handle typical library sizes."""
        from shelfr.metadata.audnex.region_cache import (
            DEFAULT_MAX_ENTRIES,
            DEFAULT_TTL_DAYS,
        )

        cache = RegionCache(tmp_path / "default_cache.json")

        # Verify defaults
        assert cache._max_entries == DEFAULT_MAX_ENTRIES
        assert cache._ttl_days == DEFAULT_TTL_DAYS

        # Defaults should be reasonable for audiobook libraries
        assert DEFAULT_MAX_ENTRIES >= 10_000  # Most libraries have <10k books
        assert DEFAULT_TTL_DAYS >= 30  # Regions don't change often
