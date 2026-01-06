# Audnex Provider

> **Status:** ✅ Production | **Roadmap Priority:** Foundation | **Type:** Network Provider
>
> **Resolver Precedence:** 70 (lower = higher priority; aggregator uses lowest priority number to win conflicts)

Audnex is an **audiobook-specific** API that powers metadata for Audible ASINs. It's the **foundation provider** for shelfr — the only source that provides narrator data, chapter timing, and audiobook runtime.

## Why Audnex is Special

| Feature | Audnex | Hardcover | OpenLibrary |
|---------|--------|-----------|-------------|
| Narrator data | ✅ Yes | ❌ No | ❌ No |
| Chapter timing | ✅ Yes | ❌ No | ❌ No |
| Audiobook runtime | ✅ Yes | ❌ No | ❌ No |
| ASIN lookup | ✅ Primary | ❌ Title search only | ❌ ISBN only |
| Content warnings | ⚠️ `isAdult` only | ✅ Rich vocabulary | ❌ No |
| Series info | ✅ Primary + Secondary | ✅ Yes | ⚠️ Limited |

**Bottom line:** You can't skip Audnex for audiobooks. Other providers *supplement* Audnex, not replace it.

## Data Available from Audnex

### Book Endpoint: `/books/{asin}`

| Field | Type | Example | Maps To |
|-------|------|---------|---------|
| `title` | `str` | `"The Final Empire"` | `title` |
| `subtitle` | `str \| None` | `"Mistborn, Book 1"` | `subtitle` |
| `authors` | `list[Author]` | `[{"name": "Brandon Sanderson", "asin": "B001IGFHW6"}]` | `authors` |
| `narrators` | `list[Author]` | `[{"name": "Michael Kramer", "asin": "B001H9RXS0"}]` | `narrators` |
| `seriesPrimary` | `Series \| None` | `{"name": "Mistborn", "position": "1"}` | `series_name`, `series_position` |
| `seriesSecondary` | `Series \| None` | `{"name": "Cosmere", "position": "6"}` | (not mapped yet) |
| `genres` | `list[Genre]` | `[{"name": "Fantasy", "type": "genre"}]` | `genres` |
| `description` | `str \| None` | Full HTML description | `description` |
| `summary` | `str \| None` | Plain text summary | `summary` |
| `publisherName` | `str \| None` | `"Recorded Books"` | `publisher` |
| `releaseDate` | `str \| None` | `"2008-07-29"` | `release_date` |
| `language` | `str \| None` | `"english"` | `language` |
| `image` | `str \| None` | Cover URL | `cover_url` |
| `runtimeLengthMin` | `int \| None` | `1418` (minutes) | `duration_seconds` (×60) |
| `formatType` | `str \| None` | `"unabridged"` or `"abridged"` | `format_type`, `content_flags` |
| `isAdult` | `bool \| None` | `true` | `content_flags` (weak signal) |
| `rating` | `str \| None` | `"4.8"` | `rating` |

### Chapters Endpoint: `/books/{asin}/chapters`

| Field | Type | Description |
|-------|------|-------------|
| `chapters` | `list[Chapter]` | Chapter timing data |
| `chapters[].title` | `str` | Chapter name |
| `chapters[].lengthMs` | `int` | Duration in milliseconds |
| `chapters[].startOffsetMs` | `int` | Start offset from beginning |
| `brandIntroDurationMs` | `int` | Audible intro length (for skipping) |
| `brandOutroDurationMs` | `int` | Audible outro length |
| `isAccurate` | `bool` | Whether chapter data is verified |

### Author Endpoint: `/authors/{asin}`

| Field | Type | Description |
|-------|------|-------------|
| `name` | `str` | Author name |
| `description` | `str \| None` | Author bio |
| `image` | `str \| None` | Author photo URL |
| `genres` | `list[Genre]` | Author's typical genres |

## Content Flag Mappings

Audnex provides limited content classification:

```python
audnex_to_mam = {
    "sSex": {
        "field": "isAdult",
        "value": True,
        "note": "Weak signal - maps to sSex (suggestive), NEVER eSex"
    },
    "abridged": {
        "field": "formatType",
        "value": "abridged"
    },
    "lgbt": {
        "field": "genres[].name",
        "match": "contains 'LGBTQ' or 'LGBT'",
        "note": "Audnex provides this as genre or tag type"
    }
}
```

### ⚠️ Critical: `isAdult` Mapping

**DO NOT map `isAdult: true` → `eSex`**

The `isAdult` flag is a blunt instrument. A book might be marked adult for:

- Violence (not sexual)
- Mature themes
- Language
- Or yes, sexual content

We map `isAdult → sSex` as a **weak fallback signal**. If Hardcover or LocalFlags provides more specific data, those win. See [Content Flags Architecture](../architecture/07-content-flags.md) for full rationale.

## API Details

```text
Base URL:  https://api.audnex.us
Endpoints:
  GET /books/{asin}           - Book metadata
  GET /books/{asin}/chapters  - Chapter timing
  GET /authors/{asin}         - Author profile

Region Parameter: ?region=us|uk|au|ca|de|es|fr|in|it|jp
Rate Limit:       ~10 requests/second (be polite)
Auth:             None required (public API)
```

**Upstream API Documentation:**

- [Audnex OpenAPI Spec](../../audnex/api/AUDNEXUS_SPEC.yaml) - Complete API specification
- [Audnex README](../../audnex/api/AUDNEX_README.md) - API documentation from upstream

### Region Fallback

Some ASINs are region-specific. The client tries regions in configured order:

```python
# config.yaml
audnex:
  regions: ["us", "uk", "au"]  # Try US first, then UK, then AU
  timeout_seconds: 30
```

**Example:** ASIN `B0BN2HMHZ8` only exists in US region. The fallback system handles this automatically.

## Integration Status

### Current: Production Provider ✅

The `AudnexProvider` is fully production-ready:

| Feature | Status |
|---------|--------|
| `MetadataProvider` protocol | ✅ Implemented |
| Priority | ✅ 70 (authoritative for audiobooks) |
| Caching (30-day TTL) | ✅ FileCache |
| Rate limiting | ✅ 10 req/sec via AsyncLimiter |
| Circuit breaker | ✅ Protects against cascading failures |
| Region fallback | ✅ Configurable via settings |
| Retry with backoff | ✅ 3 attempts, exponential backoff |

### Architecture Note: Legacy vs Plugin

Audnex exists in **two forms**:

| Layer | File | Purpose |
|-------|------|---------|
| **Raw Client** | `metadata/audnex/client.py` | Direct HTTP calls, used by orchestration |
| **Provider Plugin** | `metadata/providers/audnex.py` | Wraps client, adds cache/rate limiting |

The raw client is still imported directly in some places (legacy). The provider plugin is the preferred path and what `workflow.py` uses when `use_cache=True`.

**Current (Phase 8.5):** `AudnexProvider` is wired and active when `use_cache=True`; `workflow.py` uses the provider while some legacy code still imports `metadata/audnex/client.py` directly.

**Future work (Phase 10):** Will remove direct client imports entirely and add full multi-provider aggregation (e.g., Hardcover) via the registry.

## Sample API Response

```json
{
  "asin": "B002V0QK4C",
  "title": "The Final Empire",
  "subtitle": "Mistborn, Book 1",
  "authors": [
    {"name": "Brandon Sanderson", "asin": "B001IGFHW6"}
  ],
  "narrators": [
    {"name": "Michael Kramer", "asin": "B001H9RXS0"}
  ],
  "seriesPrimary": {
    "name": "Mistborn",
    "position": "1",
    "asin": "B006K1QJXS"
  },
  "genres": [
    {"name": "Fantasy", "asin": "...", "type": "genre"},
    {"name": "Epic Fantasy", "asin": "...", "type": "tag"}
  ],
  "publisherName": "Recorded Books",
  "releaseDate": "2008-07-29",
  "language": "english",
  "runtimeLengthMin": 1418,
  "formatType": "unabridged",
  "isAdult": false,
  "rating": "4.8",
  "image": "https://m.media-amazon.com/images/I/..."
}
```

## Known Limitations

| Limitation | Impact | Workaround |
|------------|--------|------------|
| No content warnings vocabulary | Can't detect `cLang`, `vio`, `eSex` | Use Hardcover or LocalFlags |
| `isAdult` is binary | No granularity between mild/extreme | Treat as weak signal only |
| Some ASINs region-locked | May not find book on first region | Region fallback handles this |
| No ISBN data | Can't cross-reference print editions | Use Hardcover for ISBN lookup |
| Author ASIN sometimes missing | Can't link to author profile | Fallback to name-based matching |
| Sequential region fallback is slow | Up to 30s worst case (10 regions) | Phase 10 parallel race (~1.5s) |
| No region memory | Repeats full scan every lookup | Phase 10 region cache |
| Hardcoded Audible URL | Wrong domain for non-US ASINs | Phase 10 source provenance |

---

## Planned: Phase 10 - Parallel Region Lookup & Source Provenance

> **Status:** 📋 Planning | **Priority:** High | **Estimated Effort:** 8-12 hours
>
> **Full specification:** [10-parallel-region-lookup.md](../architecture/10-parallel-region-lookup.md)

### Problem

The current client tries regions **sequentially**:

```python
# Current behavior (slow)
for region in ["us", "uk", "au", "ca", "de", ...]:
    data = fetch_region(asin, region)
    if data:
        return data  # Stop on first success
# Worst case: 10 regions × 1-3s each = ~30s
```

ASINs are region-locked (e.g., `B0BN2HMHZ8` only exists in US), but we don't remember which region worked.

### Solution: Parallel Race + Region Cache + Source Provenance

#### 1. Parallel Region Race

Fire all regions simultaneously, take **first valid response**, cancel the rest:

```python
async def fetch_audnex_book_parallel(asin: str) -> tuple[dict | None, str | None]:
    """Race all regions in parallel. ~1.5s instead of ~30s."""
    tasks = {
        asyncio.create_task(_fetch_region_async(asin, region))
        for region in regions
    }

    for coro in asyncio.as_completed(tasks):
        result = await coro
        if result and _is_valid_response(result, asin):
            # Cancel remaining tasks
            for task in tasks:
                if not task.done():
                    task.cancel()
            return result, region

    return None, None
```

**Performance improvement:** ~20x faster (1.5s vs 30s worst case)

#### 2. Region Cache (ASIN → Region)

Cache which region worked so subsequent lookups are single-request:

```python
# First lookup: race all regions, cache winner
data, region = await fetch_parallel(asin)  # e.g., region="uk"
await region_cache.set(asin, "uk")

# Second lookup: try cached region first
cached_region = await region_cache.get(asin)  # "uk"
data = await fetch_region(asin, cached_region)  # Single request!
```

**Performance improvement:** ~10x faster on cache hit

#### 3. Source Provenance Fields

Add to `CanonicalMetadata` so templates can build correct URLs:

```python
class CanonicalMetadata(BaseModel):
    # ... existing fields ...

    # Source provenance (Phase 10)
    source_provider: str | None = None   # "audnex"
    source_region: str | None = None     # "uk"
    source_id: str | None = None         # "B002V0QK4C"
    source_id_type: str | None = None    # "asin"
    source_url: str | None = None        # "https://www.audible.co.uk/pd/B002V0QK4C"
```

#### 4. Region-Correct URLs

Build URLs from resolved region, not hardcoded `.com`:

```python
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
    domain = AUDIBLE_DOMAINS.get(region, "www.audible.com")
    return f"https://{domain}/pd/{asin}"
```

### Implementation Tasks

| Phase | Task | Effort |
|-------|------|--------|
| 10.1 | Async `fetch_audnex_book_parallel()` with `as_completed` race | 2-3h |
| 10.2 | `RegionCache` class (ASIN → region, JSON backend) | 1-2h |
| 10.3 | Source provenance fields in `CanonicalMetadata` | 1h |
| 10.4 | Update `AudnexProvider` to use parallel fetch | 1-2h |
| 10.5 | Update `mam_description.j2` with conditional `source_url` | 30m |
| 10.6 | Two-level concurrency limits (ASIN + rate limiting) | 1h |
| 10.7 | Observability (`shelfr audnex region-stats` command) | 30m |

### Config Changes

```yaml
# config.yaml additions
audnex:
  # Existing
  regions: [us, uk, au, ca, de, es, fr, in, it, jp]

  # New (Phase 10)
  parallel_fetch: true          # Enable parallel region racing
  region_cache_ttl_days: 90     # How long to cache ASIN → region
  race_timeout_seconds: 10      # Max time to wait for any region
```

### ROI Summary

| Metric | Before | After |
|--------|--------|-------|
| Worst-case lookup | ~30s | ~1.5s |
| Cached lookup | N/A | Single request |
| URL accuracy | Wrong domain for non-US | 100% correct |
| Visibility | None | Race logging + stats |

---

## Related Documentation

- [Content Flags](../architecture/07-content-flags.md) - How Audnex signals map to MAM flags
- [Hardcover Provider](hardcover.md) - Supplementary content warnings
- [Plugin Architecture](../architecture/03-plugin-architecture.md) - Provider protocol
- [Implementation Checklist](../architecture/05-implementation-checklist.md) - Phase tracking
- [Phase 10 Specification](../architecture/10-parallel-region-lookup.md) - Full parallel lookup design

## Source Code

| File | Purpose |
|------|---------|
| [`metadata/audnex/client.py`](../../../../src/shelfr/metadata/audnex/client.py) | Raw HTTP client |
| [`metadata/providers/audnex.py`](../../../../src/shelfr/metadata/providers/audnex.py) | Provider plugin |
| [`schemas/audnex.py`](../../../../src/shelfr/schemas/audnex.py) | Pydantic validation schemas |
