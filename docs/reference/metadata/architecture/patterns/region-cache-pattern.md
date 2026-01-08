# Region Cache Pattern

> Code reference for ASIN → region caching with smart invalidation

---

## The Problem

Without caching, we re-race regions every time we look up the same ASIN. If we know `B08G9PRS1K` is in `uk`, we should try `uk` first next time.

## Data Model

```python
from dataclasses import dataclass, field
from datetime import datetime
from enum import Enum

class FailureType(Enum):
    NOT_FOUND = "not_found"      # 404 - definitive miss
    TRANSIENT = "transient"      # timeout/5xx - might recover

@dataclass
class RegionCacheEntry:
    region: str
    discovered_at: datetime
    hits: int = 0
    last_failed_at: datetime | None = None
    fail_count: int = 0
    last_failure_type: FailureType | None = None
```

---

## Smart Invalidation

Different failure types have different thresholds:

```python
# Invalidation thresholds
INVALIDATION_THRESHOLD_404 = 2      # Fast: 404 means "definitely not here"
INVALIDATION_THRESHOLD_TRANSIENT = 5  # Slow: timeouts/5xx might recover

def should_invalidate(entry: RegionCacheEntry) -> bool:
    """Check if entry should be invalidated based on failure history."""
    if entry.last_failure_type == FailureType.NOT_FOUND:
        return entry.fail_count >= INVALIDATION_THRESHOLD_404
    elif entry.last_failure_type == FailureType.TRANSIENT:
        return entry.fail_count >= INVALIDATION_THRESHOLD_TRANSIENT
    return False
```

**Why the difference?**

- 404 = "This ASIN doesn't exist in this region" → probably won't change
- Timeout/5xx = "Server is slow/overloaded" → might work later

---

## Cache Implementation

```python
class RegionCache:
    """Async-safe ASIN → region cache with persistence."""

    def __init__(self, cache_file: Path):
        self._cache: dict[str, RegionCacheEntry] = {}
        self._cache_file = cache_file
        self._lock = asyncio.Lock()  # Protect concurrent access
        self._dirty = False

    async def get(self, asin: str) -> str | None:
        """Get cached region for ASIN, or None if not cached/invalidated."""
        async with self._lock:
            entry = self._cache.get(asin.upper())
            if entry is None:
                return None
            if should_invalidate(entry):
                del self._cache[asin.upper()]
                self._dirty = True
                return None
            entry.hits += 1
            return entry.region

    async def set(self, asin: str, region: str) -> None:
        """Cache successful region lookup."""
        async with self._lock:
            self._cache[asin.upper()] = RegionCacheEntry(
                region=region,
                discovered_at=datetime.now(UTC),
            )
            self._dirty = True

    async def record_failure(
        self, asin: str, failure_type: FailureType
    ) -> None:
        """Record a failure for cached region."""
        async with self._lock:
            entry = self._cache.get(asin.upper())
            if entry:
                entry.fail_count += 1
                entry.last_failed_at = datetime.now(UTC)
                entry.last_failure_type = failure_type
                self._dirty = True
```

---

## Atomic Persistence

```python
async def save(self) -> None:
    """Persist cache to disk atomically."""
    if not self._dirty:
        return

    async with self._lock:
        # Serialize to JSON
        data = {
            asin: {
                "region": entry.region,
                "discovered_at": entry.discovered_at.isoformat(),
                "hits": entry.hits,
                "fail_count": entry.fail_count,
            }
            for asin, entry in self._cache.items()
        }

        # Atomic write: temp file + rename
        temp_file = self._cache_file.with_suffix(".tmp")
        temp_file.write_text(json.dumps(data, indent=2))
        temp_file.rename(self._cache_file)
        self._dirty = False

async def load(self) -> None:
    """Load cache from disk."""
    if not self._cache_file.exists():
        return

    async with self._lock:
        data = json.loads(self._cache_file.read_text())
        for asin, entry_data in data.items():
            self._cache[asin] = RegionCacheEntry(
                region=entry_data["region"],
                discovered_at=datetime.fromisoformat(entry_data["discovered_at"]),
                hits=entry_data.get("hits", 0),
                fail_count=entry_data.get("fail_count", 0),
            )
```

---

## Statistics

```python
def get_stats(self) -> dict[str, Any]:
    """Get cache statistics for observability."""
    region_counts: dict[str, int] = {}
    total_hits = 0

    for entry in self._cache.values():
        region_counts[entry.region] = region_counts.get(entry.region, 0) + 1
        total_hits += entry.hits

    return {
        "total_asins": len(self._cache),
        "total_hits": total_hits,
        "region_distribution": region_counts,
    }
```

---

## Usage in Client

```python
async def fetch_book_parallel(
    self, asin: str, cached_region: str | None = None
) -> tuple[dict | None, str | None]:
    """Fetch with cache-first strategy."""
    # Try cached region first (from RegionCache)
    data, region, stage, requests, elapsed = await self._staged_race(
        asin, cached_region=cached_region
    )

    # Update cache on success
    if data and region:
        await self._region_cache.set(asin, region)

    return data, region
```

---

## Key Gotchas

1. **Use `asyncio.Lock()`** — Multiple coroutines may access cache concurrently
2. **Atomic writes** — Write to temp file, then rename (prevents corruption)
3. **Different thresholds** — 404 invalidates fast, transient errors are forgiving
4. **Track hits** — Useful for observability and debugging
