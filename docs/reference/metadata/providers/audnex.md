# Audnex Provider

> **Status:** ✅ Production | **Roadmap Priority:** Foundation | **Type:** Network Provider
>
> **Resolver Precedence:** 70 (higher = wins conflicts; Local=95, Hardcover=70, Audnex=70)

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

**Future work:** Phase 10 will wire the aggregator to call all providers via registry, removing direct client imports.

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

## Related Documentation

- [Content Flags](../architecture/07-content-flags.md) - How Audnex signals map to MAM flags
- [Hardcover Provider](hardcover.md) - Supplementary content warnings
- [Plugin Architecture](../architecture/03-plugin-architecture.md) - Provider protocol
- [Implementation Checklist](../architecture/05-implementation-checklist.md) - Phase tracking

## Source Code

| File | Purpose |
|------|---------|
| [`metadata/audnex/client.py`](../../../../src/shelfr/metadata/audnex/client.py) | Raw HTTP client |
| [`metadata/providers/audnex.py`](../../../../src/shelfr/metadata/providers/audnex.py) | Provider plugin |
| [`schemas/audnex.py`](../../../../src/shelfr/schemas/audnex.py) | Pydantic validation schemas |
