# Phase 10: Parallel Region Lookup & Source Provenance

> **Status:** � In Progress (10.3 Complete) | **Priority:** High
>
> **Progress:** Phase 10.3 (Source Provenance) implemented. Remaining: 10.1 (Staged Race), 10.2 (Region Cache), 10.4-10.7.
>
> **Goal:** Replace sequential region fallback with parallel "race" semantics, cache winning region, and make source URLs truly platform-agnostic.

## Problem Statement

### Current Behavior

The Audnex client tries regions **sequentially** (us → uk → au → ca → ...) until one succeeds:

```python
# Current: audnex/client.py lines 147-165
for r in regions:
    data = _fetch_audnex_book_region(asin, r, ...)
    if data:
        return data, r  # Stop on first success
```

**Issues:**

1. **Slow:** 10 regions × ~1-3s each = up to 30s worst case
2. **Wasteful:** We already know many ASINs are US-only (most common case)
3. **No learning:** We don't cache which region worked, so we repeat the full scan every time

### Template Hardcoding

The MAM description template hardcodes `audible.com`:

```jinja
• [b]Source:[/b] [url=https://www.audible.com/pd/{{ asin }}]...[/url]
```

This is wrong when:

- The ASIN was resolved from a different region (should use `audible.co.uk`, `audible.de`, etc.)
- Future providers (Hardcover, Google Books) have different URL patterns

---

## Solution Overview

### 1. Staged Region Race (Not "Race All 10")

Racing 10 regions per ASIN is great for latency, terrible for rate limits. Use a **staged race** instead:

```
Cache hit  → 1 request (fast path)
Cache miss → Stage 1: race top 2-3 regions (us, uk, de) with 1.5s timeout
           → Stage 2: race remaining regions if Stage 1 fails

Typical case: 1-3 requests per ASIN
Worst case:   10 requests (rare)
```

```
Before: us → (1.5s) → uk → (1.5s) → au → (1.5s) → found!  = ~4.5s
After:  cache hit → 1 req, or stage 1 race → ~1.5s
```

### 2. Region Cache (ASIN → Region)

Once we know `B0XXXXXX` belongs to `uk`, cache it. Next lookup:

- Try `uk` first (single request)
- Track failures: if cached region fails → fall back to staged race
- Invalidate cache if region fails repeatedly

### 3. Source Provenance Fields (Split Provider vs Platform)

Separate **retrieval provider** (API we fetched from) from **source platform** (what metadata represents):

```python
# Where the metadata came from
retrieved_via: str | None = None         # "audnex", "hardcover" (the API)
source_platform: str | None = None       # "Audible", "Hardcover" (the storefront)
source_region: str | None = None         # "us", "uk", etc.
source_id: str | None = None             # ASIN, ISBN, etc.
source_id_type: str | None = None        # "asin", "isbn", "hardcover_id"
source_url: str | None = None            # Pre-built canonical URL to storefront
```

**Why split?** Avoids semantic confusion: `retrieved_via="audnex"` + `source_url="audible.co.uk"` makes sense. Template shows the *public* source (Audible UK), debug logs show retrieval path.

### 4. Platform-Agnostic Templates

Templates use `source_url` if available, fall back gracefully:

```jinja
{% if source_url %}
• [b]Source:[/b] [url={{ source_url }}]{{ source_url }}[/url]
{% else %}
• [b]Source:[/b] {{ source_platform | default('Unknown') }}
{% endif %}
{# Debug only: Retrieved via {{ retrieved_via }} #}
```

---

## Implementation Plan

### Phase 10.1: Async Staged Race (Audnex Client)

**Estimated effort:** 2-3 hours

#### New Function: `fetch_audnex_book_parallel()`

```python
async def fetch_audnex_book_parallel(
    asin: str,
    regions: list[str] | None = None,
    client: AudnexClient | None = None,
) -> tuple[dict[str, Any] | None, str | None]:
    """
    Fetch book metadata from Audnex using staged region racing.

    Returns (metadata, winning_region) or (None, None) if all fail.
    """
```

#### Staged Race Pattern

```python
# Stage 1: common regions (covers ~95% of ASINs)
STAGE_1_REGIONS = ["us", "uk", "de"]
STAGE_1_TIMEOUT = 1.5  # seconds

# Stage 2: ALL regions (not just remaining!)
# If Stage 1 timed out, the correct region might have been us/uk/de but slow
ALL_REGIONS = ["us", "uk", "de", "au", "ca", "es", "fr", "in", "it", "jp"]
STAGE_2_TIMEOUT = 8.5  # seconds

async def _staged_race(asin: str, client: AudnexClient) -> tuple[dict | None, str | None]:
    """Two-stage race: common regions first, then ALL regions if needed.

    ⚠️ Stage 2 races ALL regions, not just remaining ones.
    If Stage 1 timed out (vs 404), the correct region might still be us/uk/de.
    """
    # Stage 1: race common regions
    winner, stage1_definitive_404s = await _race_regions(
        asin, STAGE_1_REGIONS, client, timeout=STAGE_1_TIMEOUT
    )
    if winner[0] is not None:
        return winner

    # Stage 2: race ALL regions (timeout means Stage 1 might have had the answer)
    # Only skip regions that definitively returned 404 (not timeouts)
    stage2_regions = [r for r in ALL_REGIONS if r not in stage1_definitive_404s]
    return (await _race_regions(asin, stage2_regions, client, timeout=STAGE_2_TIMEOUT))[0]
```

#### Race Pattern with `asyncio.as_completed()`

⚠️ **Critical:** `as_completed()` yields new coroutine wrappers, NOT the original tasks.
You cannot use `tasks[coro]` to look up the region. Instead, include region in the result.

```python
async def _race_regions(
    asin: str,
    regions: list[str],
    client: AudnexClient,
    timeout: float = 10.0,
) -> tuple[tuple[dict | None, str | None], set[str]]:
    """First valid response wins; cancel losers.

    Returns:
        - (data, region) tuple or (None, None)
        - Set of regions that definitively returned 404 (for Stage 2 exclusion)
    """
    definitive_404s: set[str] = set()

    async def _probe(region: str) -> tuple[str, dict | None, Exception | None]:
        """Probe a single region, returning (region, data, error)."""
        try:
            data = await client.fetch_region(asin, region)
            return region, data, None
        except httpx.HTTPStatusError as e:
            if e.response.status_code == 404:
                return region, None, e  # Definitive miss
            return region, None, e  # Transient error
        except Exception as e:
            return region, None, e

    tasks = [asyncio.create_task(_probe(r), name=f"audnex-{r}") for r in regions]

    winner = (None, None)
    try:
        for fut in asyncio.as_completed(tasks, timeout=timeout):
            region, data, err = await fut
            if err:
                logger.debug("Region %s failed: %s", region, err)
                # Track definitive 404s (not timeouts/5xx)
                if isinstance(err, httpx.HTTPStatusError) and err.response.status_code == 404:
                    definitive_404s.add(region)
                continue
            if data and _is_valid_for_race(data, asin):
                winner = (data, region)
                break
    except asyncio.TimeoutError:
        logger.debug("Race timeout for %s after %.1fs", asin, timeout)

    # Cancel remaining tasks AND await them to avoid "Task destroyed" warnings
    for task in tasks:
        if not task.done():
            task.cancel()
    await asyncio.gather(*tasks, return_exceptions=True)  # Drain cleanly

    return winner, definitive_404s
```

#### Two-Level Response Validation

**Level 1 (Race Acceptance)** — minimal, to pick a winner fast:

```python
def _is_valid_for_race(data: dict, expected_asin: str) -> bool:
    """Minimal validation for race winner selection.

    Be lenient: APIs sometimes violate their own spec.
    We just need enough to confirm this is the right book.
    """
    if not data:
        return False
    # ASIN must match (some APIs return different content on region mismatch)
    if data.get("asin", "").upper() != expected_asin.upper():
        return False
    # Must have title and at least one author
    if not data.get("title"):
        return False
    if not data.get("authors") or len(data["authors"]) == 0:
        return False
    return True
```

**Level 2 (Quality Checks)** — after winner is chosen:

```python
def _validate_and_log_quality(data: dict, asin: str) -> None:
    """Log warnings for missing optional fields (don't reject the response)."""
    expected_fields = [
        "description", "formatType", "language", "publisherName",
        "rating", "releaseDate", "runtimeLengthMin", "summary"
    ]
    missing = [f for f in expected_fields if not data.get(f)]
    if missing:
        logger.warning(
            "Audnex response for %s missing fields: %s (continuing anyway)",
            asin, missing
        )
```

#### AudnexClient Class (Proper Lifecycle)

⚠️ **Critical:** Create ONE client per process/run, not per-fetch.
Otherwise each call gets a fresh limiter that believes it's allowed 90/min → aggregate exceeds 100/min.

```python
# audnex/client.py

class AudnexClient:
    """Async client for Audnex API with proper lifecycle management.

    ⚠️ Create ONE instance per process and share it.
    The rate limiter is per-instance — multiple instances = multiple limiters = 429s.
    """

    def __init__(
        self,
        rate_limit_per_min: int = 90,
        burst_limit_per_sec: float = 2.0,  # Protect against fixed-window limits
    ):
        self._client: httpx.AsyncClient | None = None
        # Dual limiters: minute-scale AND second-scale (burst protection)
        self._minute_limiter = AsyncLimiter(rate_limit_per_min, 60.0)
        self._burst_limiter = AsyncLimiter(burst_limit_per_sec, 1.0)

    async def __aenter__(self) -> "AudnexClient":
        self._client = httpx.AsyncClient(
            http2=True,
            timeout=httpx.Timeout(connect=5.0, read=15.0, pool=5.0),
            limits=httpx.Limits(max_connections=20, max_keepalive_connections=10),
        )
        return self

    async def __aexit__(self, *args) -> None:
        if self._client:
            await self._client.aclose()
            self._client = None

    async def fetch_region(self, asin: str, region: str) -> dict | None:
        """Fetch book from specific region, respecting rate limits."""
        async with self._minute_limiter, self._burst_limiter:
            # ... make request ...

    async def fetch_chapters(self, asin: str, region: str) -> dict | None:
        """Fetch chapters using same region as book lookup."""
        # Re-use winning region from book fetch — don't re-race!
        async with self._minute_limiter, self._burst_limiter:
            # ... make request ...
```

**Usage pattern — ONE client per run:**

```python
# ✅ Correct: client created once, passed to all lookups
async with AudnexClient() as client:
    for asin in asins:
        data, region = await fetch_audnex_book_parallel(asin, client=client)
        if region:
            chapters = await client.fetch_chapters(asin, region)

# ❌ Wrong: new client per ASIN = new limiter per ASIN = 429s
for asin in asins:
    async with AudnexClient() as client:  # DON'T DO THIS
        ...
```

#### Tasks

- [ ] Create `AudnexClient` class with dual rate limiters (minute + burst)
- [ ] Ensure client is created ONCE per run (store on provider or context)
- [ ] Implement `_probe()` helper that returns `(region, data, error)` tuple
- [ ] Implement `_staged_race()` with Stage 2 racing ALL regions on timeout
- [ ] Implement `_race_regions()` with proper `as_completed` pattern
- [ ] Track definitive 404s vs timeouts for smart Stage 2 exclusion
- [ ] Add `_is_valid_for_race()` (Level 1 validation)
- [ ] Add `_validate_and_log_quality()` (Level 2 validation)
- [ ] Create `fetch_audnex_book_parallel()` public API
- [ ] Add proper cancellation handling (cancel + gather to drain)
- [ ] Unit tests with mocked responses (varied latencies, 404s, timeouts)

---

### Phase 10.2: Region Cache

**Estimated effort:** 1-2 hours

#### Cache Key Format

```
region:asin:{ASIN} → {region}
```

Separate from metadata cache (much smaller, longer TTL):

```python
# metadata/region_cache.py
from enum import Enum

class FailureType(Enum):
    NOT_FOUND = "404"       # Definitive: mapping is wrong
    TRANSIENT = "transient" # Timeout/5xx/429: don't nuke mapping immediately

@dataclass
class RegionCacheEntry:
    region: str
    discovered_at: str  # ISO 8601
    hits: int = 1               # Track how often we've used this
    last_failed_at: str | None = None  # Track failures for cache invalidation
    fail_count: int = 0         # Consecutive failures
    last_failure_type: str | None = None  # "404" vs "transient"

class RegionCache:
    """Persistent ASIN → region mapping with failure tracking.

    ⚠️ JSON cache needs async lock + atomic writes to avoid corruption.
    """

    def __init__(self, cache_path: Path):
        self._path = cache_path
        self._lock = asyncio.Lock()  # Prevent concurrent writes

    async def get(self, asin: str) -> str | None: ...

    async def set(self, asin: str, region: str) -> None:
        async with self._lock:
            # Write to temp file + atomic rename
            await self._atomic_write()

    async def record_failure(self, asin: str, failure_type: FailureType) -> None:
        """Track failure; invalidate based on failure type.

        - 404: mapping is probably wrong → invalidate after 1-2 failures
        - transient: don't nuke mapping immediately → higher threshold
        """
        async with self._lock:
            entry = self._data.get(asin)
            if not entry:
                return
            entry.fail_count += 1
            entry.last_failure_type = failure_type.value

            # 404 = fast invalidation (mapping is wrong)
            # transient = slower invalidation (might recover)
            threshold = 2 if failure_type == FailureType.NOT_FOUND else 5
            if entry.fail_count >= threshold:
                del self._data[asin]

            await self._atomic_write()

    async def _atomic_write(self) -> None:
        """Write to temp file, then atomic rename."""
        tmp = self._path.with_suffix(".tmp")
        tmp.write_text(json.dumps(self._data, default=str))
        tmp.rename(self._path)  # Atomic on POSIX

    async def get_stats(self) -> dict[str, int]:
        """Return region distribution for debugging."""
```

#### Lookup Strategy with Smart Failure Tracking

```python
async def fetch_with_region_cache(asin: str, client: AudnexClient) -> tuple[dict | None, str | None]:
    # 1. Check region cache
    cached_region = await region_cache.get(asin)
    if cached_region:
        try:
            data = await client.fetch_region(asin, cached_region)
            if data and _is_valid_for_race(data, asin):
                return data, cached_region
            # Got response but invalid → treat as 404 (wrong mapping)
            await region_cache.record_failure(asin, FailureType.NOT_FOUND)
        except httpx.HTTPStatusError as e:
            if e.response.status_code == 404:
                await region_cache.record_failure(asin, FailureType.NOT_FOUND)
            else:
                await region_cache.record_failure(asin, FailureType.TRANSIENT)
        except Exception:
            await region_cache.record_failure(asin, FailureType.TRANSIENT)
        # Fall through to staged race

    # 2. Staged race
    data, region = await _staged_race(asin, client)

    # 3. Cache winner
    if region:
        await region_cache.set(asin, region)

    return data, region
```

#### Tasks

- [ ] Create `RegionCache` class with JSON file backend
- [ ] Add `asyncio.Lock()` for concurrent write protection
- [ ] Implement atomic writes (temp file + rename)
- [ ] Add `FailureType` enum: `NOT_FOUND` vs `TRANSIENT`
- [ ] Smart invalidation: 404 → fast (2 failures), transient → slow (5 failures)
- [ ] Add `discovered_at`, `hits`, `last_failed_at`, `fail_count` for observability
- [ ] Implement cache-first strategy in `fetch_audnex_book_parallel()`
- [ ] Add `shelfr audnex region-stats` command for debugging
- [ ] Tests for cache hit/miss/404/transient failure scenarios

---

### Phase 10.3: Source Provenance in Schema

**Estimated effort:** 1 hour

#### Extend `CanonicalMetadata`

```python
# schemas/canonical.py

class CanonicalMetadata(BaseModel):
    # ... existing fields ...

    # Source provenance (Phase 10)
    # Split "retrieval provider" (API) from "source platform" (storefront)
    retrieved_via: str | None = Field(
        default=None,
        description="API/provider that supplied this metadata (e.g., 'audnex', 'hardcover')"
    )
    source_platform: str | None = Field(
        default=None,
        description="Platform the metadata represents (e.g., 'Audible', 'Hardcover')"
    )
    source_region: Literal["au", "ca", "de", "es", "fr", "in", "it", "jp", "us", "uk"] | None = Field(
        default=None,
        description="Region where source ID was resolved (for region-locked IDs like ASINs)"
    )
    source_id: str | None = Field(
        default=None,
        description="Primary identifier from source (ASIN, ISBN, etc.)"
    )
    source_id_type: Literal["asin", "isbn", "hardcover_id"] | None = Field(
        default=None,
        description="Type of source_id"
    )
    source_url: str | None = Field(
        default=None,
        description="Canonical URL to source storefront (pre-built from platform + region + id)"
    )
```

#### Audible URL Builder

```python
# utils/audible_urls.py

AUDIBLE_DOMAINS = {
    "us": "www.audible.com",
    "uk": "www.audible.co.uk",
    "au": "www.audible.com.au",
    "ca": "www.audible.ca",
    "de": "www.audible.de",
    "es": "www.audible.es",
    "fr": "www.audible.fr",
    "in": "www.audible.in",
    "it": "www.audible.it",
    "jp": "www.audible.co.jp",
}

def build_audible_url(asin: str, region: str = "us") -> str:
    """Build region-correct Audible URL."""
    domain = AUDIBLE_DOMAINS.get(region, "www.audible.com")
    return f"https://{domain}/pd/{asin}"
```

#### Tasks

- [x] Add source provenance fields to `CanonicalMetadata`
- [x] Create `utils/audible_urls.py` with `build_audible_url()`
- [x] Update `AudnexProvider._map_to_result()` to populate source fields
- [x] Add validation that `source_url` is only set when `source_id` is set
- [x] Tests for URL building across all regions (19 tests in `test_audible_urls.py`)

---

### Phase 10.4: Update AudnexProvider

**Estimated effort:** 1-2 hours

#### Switch to Parallel Fetch

```python
# providers/audnex.py

class AudnexProvider:
    """Audnex metadata provider with shared client lifecycle."""

    def __init__(self):
        self._client: AudnexClient | None = None

    async def startup(self) -> None:
        """Initialize shared client. Call once at process start."""
        self._client = AudnexClient()
        await self._client.__aenter__()

    async def shutdown(self) -> None:
        """Close shared client. Call at process end."""
        if self._client:
            await self._client.__aexit__(None, None, None)
            self._client = None

    async def fetch(self, ctx: LookupContext, id_type: IdType) -> ProviderResult:
        # ... cache check ...

        if not self._client:
            raise RuntimeError("AudnexProvider not started. Call startup() first.")

        # Use shared client (rate limiter is shared across all lookups)
        data, region = await fetch_audnex_book_parallel(ctx.asin, client=self._client)

        if data is None:
            return ProviderResult.failure(self.name, f"ASIN {ctx.asin} not found")

        # Level 2 validation: log quality issues (don't reject)
        _validate_and_log_quality(data, ctx.asin)

        result = self._map_to_result(data, region)

        # Populate source provenance (split provider vs platform)
        result.set_field("retrieved_via", "audnex")           # The API we used
        result.set_field("source_platform", "Audible")        # What the data represents
        result.set_field("source_region", region)
        result.set_field("source_id", ctx.asin)
        result.set_field("source_id_type", "asin")
        result.set_field("source_url", build_audible_url(ctx.asin, region or "us"))

        # Fetch chapters using SAME region (don't re-race!)
        if ctx.include_chapters:
            chapters = await self._client.fetch_chapters(ctx.asin, region)
            if chapters:
                result.set_field("chapters", chapters)

        # ... cache store ...
        return result


# CLI entrypoint example
async def main():
    provider = AudnexProvider()
    await provider.startup()
    try:
        for asin in asins:
            result = await provider.fetch(ctx, IdType.ASIN)
    finally:
        await provider.shutdown()
```

#### Tasks

- [ ] Add `startup()` / `shutdown()` lifecycle methods to `AudnexProvider`
- [ ] Store shared `AudnexClient` on provider instance
- [ ] Update CLI entrypoint to call `startup()` / `shutdown()`
- [ ] Populate source provenance fields with split provider/platform semantics
- [ ] Use winning region for chapters endpoint (don't re-race!)
- [ ] Update cache key to include "parallel" schema version
- [ ] Add observability logging (race results, winning region)
- [ ] Integration tests with real Audnex API

---

### Phase 10.5: Template Updates

**Estimated effort:** 30 min

#### Update `mam_description.j2`

```jinja
{% if source_url %}
• [b]Source:[/b] [url={{ source_url }}]{{ source_url }}[/url][br]
{% elif asin %}
• [b]Source:[/b] ASIN {{ asin }}[br]
{% endif %}
{% if source_id and source_id_type == "asin" %}
• [b]Source ASIN:[/b] {{ source_id }}[br][br]
{% elif source_id %}
• [b]Source ID:[/b] {{ source_id }} ({{ source_id_type }})[br][br]
{% endif %}
{# Debug: Retrieved via {{ retrieved_via | default("unknown") }} from {{ source_platform | default("unknown") }} ({{ source_region | default("?") }}) #}
```

#### Update BBCode Renderer

```python
# formatting/bbcode.py - render_bbcode_description()

# Extract source provenance from canonical or build from Audnex
source_url = canonical.source_url if canonical else None
source_id = canonical.source_id if canonical else asin
source_id_type = canonical.source_id_type if canonical else "asin"
source_platform = canonical.source_platform if canonical else "Audible"
source_region = canonical.source_region if canonical else "us"
retrieved_via = canonical.retrieved_via if canonical else "audnex"

# Fallback URL building if not in canonical
if not source_url and asin:
    source_url = build_audible_url(asin, source_region or "us")
```

#### Tasks

- [ ] Update `mam_description.j2` with conditional source URL
- [ ] Update `render_bbcode_description()` to pass source fields to template
- [ ] Test with various source combinations
- [ ] Update golden tests if needed

---

### Phase 10.6: Concurrency Limits

**Estimated effort:** 1 hour

> **API Limit:** Audnex allows ~100 requests/minute per source IP (see [API Reference](#audnex-api-reference))

#### Global Rate Limiter (Correct Math)

⚠️ **Common mistake:** `AsyncLimiter(10, 1.0)` = 10 req/sec = **600/min** (way over limit!)

**Correct approach:** One global limiter at **90 req/min** (leaves 10% headroom for retries + chapters):

```python
# Global rate limiter — lives inside AudnexClient
# 90/min = 1.5 req/sec, but allows bursts
self._limiter = AsyncLimiter(max_rate=90, time_period=60.0)

async def fetch_region(self, asin: str, region: str) -> dict | None:
    async with self._limiter:  # All requests go through this gate
        return await self._client.get(f"/books/{asin}", params={"region": region})
```

#### Why Staged Race Helps

With staged race + region cache, actual request volume is much lower:

| Scenario | Requests/ASIN | At 90/min limit |
| --- | --- | --- |
| Cache hit | 1 | **90 ASINs/min** |
| Stage 1 hit (common) | 3 | **30 ASINs/min** |
| Stage 2 needed (rare) | 10 | **9 ASINs/min** |
| **Realistic average** | ~1.5-2.5 | **~40-60 ASINs/min** |

**⚠️ With chapters enabled**, add +1 request per ASIN:

| Scenario (+ chapters) | Requests/ASIN | At 90/min limit |
| --- | --- | --- |
| Cache hit + chapters | 2 | **45 ASINs/min** |
| Stage 1 hit + chapters | 4 | **22 ASINs/min** |
| Stage 2 + chapters | 11 | **8 ASINs/min** |
| **Realistic average** | ~2.5-3.5 | **~25-35 ASINs/min** |

**Recommendation:** Use `rate_limit_per_minute: 80` if chapters are frequently enabled.

The limiter + staged race means you're rarely near the ceiling.

#### Burst Protection (Dual Limiters)

Even with 90/min, some APIs use fixed-window limits. A burst of 30 requests in 2 seconds can trigger 429 even if you're under 90/min average.

**Solution: dual limiters** (minute-scale AND second-scale):

```python
# In AudnexClient.__init__()
self._minute_limiter = AsyncLimiter(90, 60.0)  # 90/min
self._burst_limiter = AsyncLimiter(2.0, 1.0)    # 2/sec burst cap

async def fetch_region(self, asin: str, region: str) -> dict | None:
    async with self._minute_limiter, self._burst_limiter:  # Both gates
        return await self._client.get(f"/books/{asin}", params={"region": region})
```

#### ASIN-Level Semaphore (Batch Safety)

For batch processing, limit concurrent ASIN lookups:

```python
ASIN_CONCURRENCY = 5  # Max ASINs in flight simultaneously

asin_semaphore = asyncio.Semaphore(ASIN_CONCURRENCY)

async def fetch_batch(asins: list[str], client: AudnexClient) -> list[tuple[dict | None, str | None]]:
    """Process multiple ASINs with proper rate limiting."""
    async def fetch_one(asin: str):
        async with asin_semaphore:  # Limit concurrent ASIN lookups
            return await fetch_audnex_book_parallel(asin, client=client)

    # Process all ASINs; semaphore + rate limiter ensure we don't exceed limits
    return await asyncio.gather(*[fetch_one(asin) for asin in asins])
```

**Math check:** 5 ASINs × 3 regions (Stage 1) = 15 concurrent requests max. With 90/min limiter, bursts are smoothed.

#### Tasks

- [ ] Use dual limiters: `AsyncLimiter(90, 60.0)` + `AsyncLimiter(2.0, 1.0)` for burst protection
- [ ] Adjust to 80/min if `include_chapters` is commonly enabled
- [ ] Add `asin_semaphore` for batch operations
- [ ] Document concurrency settings in config
- [ ] Add metrics/logging for concurrency stats

---

### Phase 10.7: Observability

**Estimated effort:** 30 min

#### Race Result Logging

```python
logger.info(
    "Audnex lookup for %s: source=%s stage=%d in %.2fs, requests=%d",
    asin,
    winning_region or "none",
    stage,  # 0=cache, 1=stage1, 2=stage2
    elapsed,
    request_count,
)
```

Example output:

```
Audnex lookup for B08G9PRS1K: source=us stage=1 in 0.89s, requests=3
Audnex lookup for B01H0IE2RQ: source=uk stage=0 in 0.23s, requests=1  # cache hit
```

#### Region Stats Command

```bash
$ shelfr audnex region-stats

Region Distribution (last 30 days):
┌────────┬───────┬─────────┐
│ Region │ Count │ Percent │
├────────┼───────┼─────────┤
│ us     │ 1,234 │ 78.5%   │
│ uk     │   245 │ 15.6%   │
│ de     │    58 │  3.7%   │
│ au     │    35 │  2.2%   │
└────────┴───────┴─────────┘

Cache Performance:
┌──────────────────┬─────────┐
│ Metric           │ Value   │
├──────────────────┼─────────┤
│ Cache hit rate   │ 67.3%   │
│ Avg req/ASIN     │ 1.8     │
│ Avg race latency │ 1.23s   │
└──────────────────┴─────────┘
```

#### Tasks

- [ ] Add structured logging for race results (stage, requests, latency)
- [ ] Create `shelfr audnex region-stats` CLI command
- [ ] Track cache hit rate as KPI ("did we actually improve?")
- [ ] Add avg requests/ASIN metric
- [ ] Add timing metrics to provider result

---

## Testing Strategy

| Component | Test Focus |
| --- | --- |
| **Staged race** | Stage 1 → Stage 2 fallback, timeout vs 404 handling |
| **Race correctness** | `_probe()` returns `(region, data, err)` tuple correctly |
| **Cancellation** | Tasks cancelled AND drained (no "Task destroyed" warnings) |
| **AudnexClient** | Context manager lifecycle, shared across run |
| **Region cache** | Hit/miss, 404 vs transient failure, atomic writes |
| **Source provenance** | Field population, provider vs platform split |
| **Templates** | Conditional rendering, missing fields |
| **Rate limiting** | Dual limiters (90/min + 2/sec burst) |
| **Two-level validation** | Level 1 acceptance, Level 2 warnings |

### Mock Latency Testing

```python
async def test_staged_race_stage1_wins():
    """Stage 1 wins when common region has the book."""
    # us: 0.5s valid, uk: 0.8s valid, de: 1.0s valid
    # Expected: us wins in Stage 1, no Stage 2 needed

async def test_staged_race_stage1_timeout_retries_in_stage2():
    """Stage 2 retries ALL regions when Stage 1 times out (not just remaining)."""
    # Stage 1: us/uk/de all timeout at 1.5s (no response yet)
    # Stage 2: us responds at 2.0s with valid data
    # Expected: us wins in Stage 2 (would fail if Stage 2 only tried remaining)

async def test_staged_race_404_excluded_from_stage2():
    """Stage 2 excludes regions that definitively returned 404."""
    # Stage 1: us=404, uk=404, de=404
    # Stage 2: should NOT retry us/uk/de (definitive miss)
    # au: 1.0s valid
    # Expected: au wins, only 4 total requests (not 7)

async def test_cache_404_fast_invalidation():
    """404 failures invalidate cache faster than transient errors."""
    # Setup: cache says "uk" for ASIN
    # Call 1: uk returns 404 → fail_count=1
    # Call 2: uk returns 404 → fail_count=2 → INVALIDATED (threshold=2 for 404)
    # Call 3: full race (cache empty)

async def test_cache_transient_slow_invalidation():
    """Transient failures (timeout/5xx) have higher threshold."""
    # Setup: cache says "uk" for ASIN
    # Calls 1-4: uk returns 503 → fail_count=4 (not yet invalidated)
    # Call 5: uk returns 503 → fail_count=5 → INVALIDATED (threshold=5 for transient)

async def test_cancellation_drains_cleanly():
    """Cancelled tasks are awaited to avoid warnings."""
    # Start race with 3 regions, us responds first
    # Verify: no "Task was destroyed but it is pending!" warnings
    # Verify: all httpx connections closed

async def test_shared_client_rate_limit():
    """Multiple fetch calls share the same rate limiter."""
    # Create ONE client, make 100 requests
    # Verify: requests are throttled to 90/min (not 90/min per call)
```

---

## Audnex API Reference

> **Source:** [AUDNEXUS_SPEC.yaml](../../audnex/api/AUDNEXUS_SPEC.yaml) | [AUDNEX_README.md](../../audnex/api/AUDNEX_README.md)

### Base URL & Authentication

```
Base URL: https://api.audnex.us
Auth:     None required (public API)
```

### Endpoints Used by Phase 10

#### GET `/books/{ASIN}`

Returns book metadata for a given ASIN and region.

| Parameter | In | Type | Required | Default | Description |
| ----------- | ----- | ------ | ---------- | --------- | ------------- |
| `ASIN` | path | string | ✅ | - | Audible ASIN (e.g., "B08G9PRS1K") |
| `region` | query | enum | ❌ | `us` | Region code |
| `seedAuthors` | query | 0\|1 | ❌ | 0 | Whether to seed authors of book |
| `update` | query | 0\|1 | ❌ | 0 | Force upstream data refresh |

**Region enum:** `au`, `ca`, `de`, `es`, `fr`, `in`, `it`, `jp`, `us`, `uk`

**Response codes:**

- `200 OK` - Book found, returns `Book` schema
- `400 Bad Request` - Invalid ASIN format
- `404 Not Found` - ASIN doesn't exist in this region

#### GET `/books/{ASIN}/chapters`

Returns chapter timing data for audiobook playback.

| Parameter | In | Type | Required | Default | Description |
|----------- | ----- | ------ | ---------- | --------- | ------------- |
| `ASIN` | path | string | ✅ | - | Audible ASIN |
| `region` | query | enum | ❌ | `us` | Region code |
| `update` | query | 0\|1 | ❌ | 0 | Force upstream data refresh |

### Book Schema (Response)

```yaml
# Required fields (per OpenAPI spec)
asin: string           # Audible ASIN
authors: Person[]      # At least one author
description: string    # Full book description
formatType: string     # "unabridged" | "abridged"
language: string       # e.g., "english"
publisherName: string  # Publisher name
rating: string         # e.g., "4.8"
region: string         # Region this data is from
releaseDate: datetime  # ISO 8601 date
runtimeLengthMin: int  # Duration in minutes
summary: string        # Short summary
title: string          # Book title

# Optional fields
subtitle: string | null
seriesPrimary: Series | null
seriesSecondary: Series | null
genres: Genre[]
image: string (URI)    # Cover image URL
isAdult: boolean
isbn: string | null
copyright: int | null  # Year
narrators: Person[]
literatureType: "fiction" | "nonfiction" | null
```

### Rate Limits

From [AUDNEX_README.md](../../audnex/api/AUDNEX_README.md):

> `NODE_MAX_REQUESTS`: Maximum number of requests per 1-minute period from a single source (default 100)

**Practical limits for Phase 10:**

| Scenario | Requests/ASIN | Throughput at 90/min |
| --- | --- | --- |
| Cache hit | 1 | **~90 ASINs/min** |
| Stage 1 race (common) | 3 | **~30 ASINs/min** |
| Stage 2 race (rare) | 10 | **~9 ASINs/min** |
| **Realistic average** | ~1.5-2.5 | **~40-60 ASINs/min** |

**Recommendation:** Use `AsyncLimiter(90, 60.0)` — leaves 10% headroom for retries and chapter fetches.

⚠️ **Common mistake:** `AsyncLimiter(10, 1.0)` = 10/sec = **600/min** = instant rate limit!

### Response Validation Strategy

Use **two-level validation** to avoid rejecting good data due to API quirks:

**Level 1 (Race Acceptance)** — minimal, to pick a winner fast:

```python
def _is_valid_for_race(data: dict, expected_asin: str) -> bool:
    """Minimal validation for race winner selection.

    Be lenient: APIs sometimes violate their own spec.
    We just need enough to confirm this is the right book.
    """
    if not data:
        return False
    # ASIN must match request
    if data.get("asin", "").upper() != expected_asin.upper():
        return False
    # Must have title and at least one author
    if not data.get("title"):
        return False
    if not data.get("authors") or len(data["authors"]) == 0:
        return False
    return True
```

**Level 2 (Quality Checks)** — after winner is chosen, log warnings but don't reject:

```python
def _validate_and_log_quality(data: dict, asin: str) -> None:
    """Log warnings for missing optional fields (don't reject the response)."""
    expected_fields = [
        "description", "formatType", "language", "publisherName",
        "rating", "releaseDate", "runtimeLengthMin", "summary"
    ]
    missing = [f for f in expected_fields if not data.get(f)]
    if missing:
        logger.warning(
            "Audnex response for %s missing fields: %s (continuing anyway)",
            asin, missing
        )
```

**Why two levels?** OpenAPI specs define "required" fields, but real APIs sometimes violate their own spec. Rejecting a 90% complete response because `rating` is null is worse than accepting it with a warning.

### Audible Domain Mapping

Maps Audnex region codes to Audible storefront URLs:

| Region Code | Audible Domain | Example URL |
|-------------|----------------|-------------|
| `us` | `www.audible.com` | `https://www.audible.com/pd/B08G9PRS1K` |
| `uk` | `www.audible.co.uk` | `https://www.audible.co.uk/pd/B08G9PRS1K` |
| `au` | `www.audible.com.au` | `https://www.audible.com.au/pd/B08G9PRS1K` |
| `ca` | `www.audible.ca` | `https://www.audible.ca/pd/B08G9PRS1K` |
| `de` | `www.audible.de` | `https://www.audible.de/pd/B08G9PRS1K` |
| `es` | `www.audible.es` | `https://www.audible.es/pd/B08G9PRS1K` |
| `fr` | `www.audible.fr` | `https://www.audible.fr/pd/B08G9PRS1K` |
| `in` | `www.audible.in` | `https://www.audible.in/pd/B08G9PRS1K` |
| `it` | `www.audible.it` | `https://www.audible.it/pd/B08G9PRS1K` |
| `jp` | `www.audible.co.jp` | `https://www.audible.co.jp/pd/B08G9PRS1K` |

---

## Migration Notes

### Backward Compatibility

1. **Sync wrapper remains:** `fetch_audnex_book()` still works (calls async internally)
2. **Cache versioning:** Bump `SCHEMA_VERSION` to invalidate old cache entries
3. **Template fallback:** Templates still work without source fields (fall back to ASIN)

### Config Changes

```yaml
# config.yaml additions
audnex:
  # Existing
  regions: [us, uk, au, ca, de, es, fr, in, it, jp]

  # New (Phase 10)
  parallel_fetch: true              # Enable staged region racing
  region_cache_ttl_days: 90         # How long to cache ASIN → region mappings
  stage_1_timeout_seconds: 1.5      # Timeout for common regions race
  stage_2_timeout_seconds: 8.5      # Timeout for ALL regions race
  stage_1_regions: [us, uk, de]     # Common regions to try first

  # Rate limiting
  rate_limit_per_minute: 90         # Leave 10% headroom below API limit
  burst_limit_per_second: 2.0       # Protect against fixed-window limits

  # Cache invalidation (404 vs transient)
  max_404_failures: 2               # Invalidate after N definitive 404s (wrong mapping)
  max_transient_failures: 5         # Invalidate after N timeouts/5xx (might recover)
```

---

## Dependencies

```
Phase 10.1 (Async client) ← MUST BE FIRST
    │
    ├── Phase 10.2 (Region cache)
    │
    ├── Phase 10.3 (Schema changes)
    │       │
    │       └── Phase 10.5 (Templates)
    │
    └── Phase 10.4 (Provider update)
            │
            └── Phase 10.6 (Concurrency limits)
                    │
                    └── Phase 10.7 (Observability)
```

---

## ROI Analysis

| Before | After | Improvement |
| --- | --- | --- |
| Sequential: up to 30s | Staged race: ~1.5s | **~20x faster** |
| No region memory | Cached: single request | **~10x faster (cache hit)** |
| 10 req/ASIN (worst case) | ~1.5-2.5 req/ASIN (avg) | **~4-6x fewer requests** |
| Hardcoded `.com` URL | Region-correct URL | **100% accuracy** |
| No visibility | Race logging + stats | **Full observability** |
| Module-global client | Context-managed client | **Proper lifecycle** |

---

## Known Gotchas (Don't Repeat These Mistakes)

### 1. `asyncio.as_completed()` Mapping Bug

❌ **Wrong:** `tasks[coro]` to look up region — `as_completed()` yields wrappers, not original tasks.

✅ **Fix:** Return `(region, data, error)` tuple from probe function.

### 2. Stage 2 Must Race ALL Regions (Not Just Remaining)

❌ **Wrong:** `remaining = [r for r in ALL if r not in STAGE_1]` — if Stage 1 *timed out*, correct region might have been us/uk/de.

✅ **Fix:** Track *definitive 404s* only, exclude those from Stage 2 (timeouts should retry).

### 3. Cancelled Tasks Must Be Awaited

❌ **Wrong:** `task.cancel()` without awaiting — causes "Task was destroyed but it is pending!" warnings.

✅ **Fix:** `await asyncio.gather(*tasks, return_exceptions=True)` after cancelling.

### 4. Rate Limiter Must Be Shared Per-Process

❌ **Wrong:** `async with AudnexClient() as client:` per-fetch — each gets fresh limiter → aggregate exceeds limit.

✅ **Fix:** Create ONE client at process start, store on provider, pass everywhere.

### 5. 10/sec ≠ 90/min

❌ **Wrong:** `AsyncLimiter(10, 1.0)` = 10/sec = **600/min** (instant 429).

✅ **Fix:** `AsyncLimiter(90, 60.0)` for minute-scale, plus `AsyncLimiter(2.0, 1.0)` for burst protection.

### 6. Cache Invalidation: 404 ≠ Timeout

❌ **Wrong:** Same threshold for all failures — transient errors nuke cache unnecessarily.

✅ **Fix:** 404 → fast invalidation (2 failures), timeout/5xx → slow (5 failures).

---

## Open Questions (Resolved)

1. **Scoring vs first-valid:** Should we wait for all regions and pick "best" metadata, or take first valid?
   - ✅ **Decision:** First valid with minimal validation. Add scoring only if we observe multiple valid regions returning different data in production logs (unlikely—Audnex returns identical data for same ASIN across regions).

2. **Region cache sharing:** Should region cache be shared across machines (Redis)?
   - ✅ **Decision:** Start with local JSON file. If we go distributed, we'll feel the pain and migrate then.

3. **Graceful degradation:** What if async client fails to initialize?
   - ✅ **Decision:** Keep sync sequential fallback. Also consider middle fallback: "Stage 1 only" if full staged race is disabled.

4. **Validation strictness:** Should we reject responses missing OpenAPI "required" fields?
   - ✅ **Decision:** No. Use two-level validation: Level 1 (race) accepts anything with ASIN + title + authors. Level 2 (quality) logs warnings but doesn't reject. APIs violate their own specs; don't throw away 90% complete data.

---

## Future Extensions

- **Hardcover provider:** Same staged race pattern (parallel lookup across sources)
- **ASIN prefetching:** Pre-warm region cache during batch scan
- **Adaptive region ordering:** Learn from stats which regions to try first in Stage 1
- **Stage 1 tuning:** Adjust Stage 1 regions based on observed distribution (if `au` becomes common, add it)

---

## Deployment & Rollout Plan

### Pre-Deployment Checklist

- [ ] All unit tests passing (mocked responses)
- [ ] Integration tests passing against real Audnex API (rate-limited)
- [ ] Golden tests updated for new source provenance fields
- [ ] Pre-commit hooks passing (`ruff`, `mypy`, `pytest`)
- [ ] Documentation updated:
  - [ ] CHANGELOG.md entry
  - [ ] README.md (if user-facing changes)
  - [ ] `config.yaml.example` updated with new settings
- [ ] PR reviewed by at least 1 maintainer

### Feature Flag Rollout

```yaml
# config.yaml - phased rollout
audnex:
  parallel_fetch: false  # Start disabled, flip per-environment
```

**Rollout stages:**

1. **Dev/CI** — Enable immediately, run full test suite
2. **Staging** — Enable, process 50-100 ASINs, verify logs + cache behavior
3. **Production (shadow)** — Run parallel fetch alongside sequential, compare results (don't use output)
4. **Production (full)** — Flip `parallel_fetch: true`, monitor for 24h

### Rollback Plan

If issues detected in production:

1. **Immediate:** Set `parallel_fetch: false` in config (no code deploy needed)
2. **Fallback code path:** `fetch_metadata_legacy()` still works unchanged
3. **Cache invalidation:** `shelfr cache clear --provider audnex` if cache corrupted

### Performance Benchmarks (Definition of Done)

Run against a corpus of 100 diverse ASINs (mix of regions):

| Metric | Target | Measurement |
| --- | --- | --- |
| P50 latency (cache miss) | < 2.0s | `shelfr audnex region-stats` |
| P95 latency (cache miss) | < 5.0s | Log analysis |
| Cache hit rate (warm) | > 60% | `region-stats` |
| Avg requests/ASIN | < 2.5 | `region-stats` |
| 429 errors | 0 | Log grep |
| "Task destroyed" warnings | 0 | stderr |

### Monitoring & Alerting

**Metrics to track (Observability phase 10.7):**

| Metric | Alert Threshold | Action |
| --- | --- | --- |
| `audnex_429_count` | > 5/hour | Reduce rate limit, check limiter sharing |
| `audnex_avg_latency` | > 10s | Check Audnex API status |
| `region_cache_corruption` | Any | Investigate atomic write failure |
| `task_destroyed_warnings` | Any | Check cancellation draining |

**Log queries to prepare:**

```bash
# 429 rate limit errors
grep "429" logs/shelfr.log | wc -l

# Task destroyed warnings
grep "Task was destroyed" logs/shelfr.log

# Race performance
grep "Audnex lookup" logs/shelfr.log | tail -100
```

---

## PR & Review Checklist

### For Each Sub-Phase PR

```markdown
## PR Checklist — Phase 10.X

### Code Quality
- [ ] No `# type: ignore` without comment explaining why
- [ ] All new functions have docstrings
- [ ] No hardcoded magic numbers (use constants)
- [ ] Error messages are actionable

### Testing
- [ ] Unit tests for happy path
- [ ] Unit tests for error cases (404, timeout, 5xx)
- [ ] Mock latency tests (verify race semantics)
- [ ] No flaky tests (run 3x locally)

### Integration
- [ ] Tested with real Audnex API (at least 10 ASINs)
- [ ] Verified rate limiter doesn't trigger 429s
- [ ] Verified cache persistence across runs

### Documentation
- [ ] Updated task checkboxes in 10-parallel-region-lookup.md
- [ ] Added CHANGELOG entry if user-visible
- [ ] Updated config.yaml.example if new settings
```

### Final Ship PR (Phase 10 Complete)

```markdown
## PR Checklist — Phase 10 Ship

### Feature Completeness
- [ ] All 10.1-10.7 sub-phase PRs merged
- [ ] Feature flag `parallel_fetch` works (enable/disable)
- [ ] Fallback to sequential still works when disabled

### Performance Validation
- [ ] Benchmark results meet targets (see table above)
- [ ] No regression in existing functionality
- [ ] Memory usage stable (no leaks from unclosed clients)

### Production Readiness
- [ ] Rollback documented and tested
- [ ] Monitoring queries documented
- [ ] On-call runbook updated (if applicable)

### Sign-off
- [ ] QA sign-off (if applicable)
- [ ] Maintainer approval
- [ ] Squash-merge to main
```

---

## Estimated Timeline

| Phase | Effort | Dependencies | Cumulative |
| --- | --- | --- | --- |
| 10.1 Async staged race | 2-3h | None | 2-3h |
| 10.2 Region cache | 1-2h | 10.1 | 4-5h |
| 10.3 Schema changes | 1h | None (parallel) | 5-6h |
| 10.4 Provider update | 1-2h | 10.1, 10.2 | 7-8h |
| 10.5 Template updates | 30min | 10.3 | 7.5-8.5h |
| 10.6 Concurrency limits | 1h | 10.4 | 8.5-9.5h |
| 10.7 Observability | 30min | 10.6 | 9-10h |
| **Integration testing** | 1-2h | All | 10-12h |
| **Documentation** | 30min | All | 10.5-12.5h |
| **Code review cycles** | 1-2h | All | **12-15h total** |

**Suggested PR batching:**

1. **PR #1:** 10.1 + 10.2 (core async + cache) — largest, needs most review
2. **PR #2:** 10.3 + 10.5 (schema + templates) — can parallel with PR #1
3. **PR #3:** 10.4 + 10.6 + 10.7 (provider + limits + observability) — ties it together
4. **PR #4:** Integration tests + feature flag + docs — ship it!
