# Phase 12: Hardcover Provider

> **Status:** 📋 Planned
> **Goal:** Add Hardcover as metadata source for richer content warnings and genres
> **Priority:** Medium
> **Depends on:** Phase 9.2 (FlagResolver) for multi-source content flags

---

## Overview

Hardcover is a book discovery platform with community-sourced metadata including **content warnings** — the key data missing from Audnex. This phase implements `HardcoverProvider` as a pluggable metadata source.

### Why Hardcover?

| Data | Audnex | Hardcover |
| ---- | ------ | --------- |
| ASIN/ISBN | ✅ | ✅ |
| Title/Author | ✅ | ✅ |
| Chapters | ✅ | ❌ |
| Content warnings | ❌ (only `isAdult`) | ✅ (60+ granular warnings) |
| Genres/Moods | Limited | ✅ Rich |
| Ratings | ❌ | ✅ |

**Key value:** Granular content warnings → accurate MAM flags (`vio`, `cLang`, `sSex`, `eSex`, `lgbt`).

---

## Sub-phases

### 12.1: Hardcover API Client

**File:** `src/shelfr/metadata/hardcover/client.py`

**Scope:**

- GraphQL client for Hardcover API
- Search by title + author
- Fetch book details by Hardcover ID
- Rate limiting (60 req/min)

**API Details:**

```text
Endpoint: https://api.hardcover.app/v1/graphql
Auth:     HARDCOVER_API_KEY environment variable
Limit:    60 requests/minute
```

**Key queries:**

```graphql
# Search for books
query SearchBooks($query: String!) {
  search(query: $query, limit: 10) {
    books {
      id
      title
      authors { name }
      genres { name }
      moods { name }
      content_warnings { name }
    }
  }
}

# Get book by ID
query GetBook($id: ID!) {
  book(id: $id) {
    id
    title
    # ... full fields
  }
}
```

---

### 12.2: Search & Match Logic

**File:** `src/shelfr/metadata/hardcover/search.py`

**Scope:**

- Title + author fuzzy matching with rapidfuzz
- Configurable match threshold (default 70%)
- Handle edge cases: light novels, omnibuses, audiobook-only releases

**Matching strategy:**

```python
from rapidfuzz import fuzz

def find_best_match(
    title: str,
    author: str,
    candidates: list[HardcoverBook],
    threshold: float = 0.70,
) -> HardcoverBook | None:
    """Find best matching book from search results."""
    search_query = f"{title} {author}".lower()

    best_match = None
    best_score = 0.0

    for candidate in candidates:
        candidate_str = f"{candidate.title} {candidate.authors[0].name}".lower()
        score = fuzz.ratio(search_query, candidate_str) / 100.0

        if score > best_score and score >= threshold:
            best_score = score
            best_match = candidate

    return best_match
```

---

### 12.3: HardcoverProvider

**File:** `src/shelfr/metadata/providers/hardcover.py`

**Scope:**

- Implement `MetadataProvider` protocol
- Map Hardcover fields → `CanonicalMetadata`
- Async `fetch()` with caching

**Provider config:**

```python
class HardcoverProvider:
    name = "hardcover"
    kind = "network"
    precedence = 70  # Local (95) > Hardcover (70) > Audnex (60)

    supported_ids = ["isbn", "hardcover_id"]
    # Note: ASIN lookup requires search (no direct ASIN→Hardcover mapping)
```

**Lifecycle:**

```python
async def startup(self) -> None:
    """Initialize HTTP client and rate limiter."""

async def shutdown(self) -> None:
    """Close HTTP client."""

async def fetch(self, context: LookupContext) -> ProviderResult:
    """Fetch metadata from Hardcover."""
```

---

### 12.4: Content Warning → MAM Flag Mapping

**File:** `config/content_flags.json` (extend existing)

**Scope:**

- Map 60+ Hardcover warnings → 6 MAM flags
- Handle severity levels (e.g., "Sexual content" → `sSex`, "Rape" → `eSex`)
- Document mapping rationale

**Mapping excerpt:**

```json
{
  "hardcover_to_mam": {
    "Violence": "vio",
    "Gore": "vio",
    "Strong language": "cLang",
    "Cursing": "cLang",
    "Sexual content": "sSex",
    "Spicy": "sSex",
    "Rape": "eSex",
    "Sexual assault": "eSex"
  }
}
```

**Full mapping:** See [archive/07-content-flags.md](../archive/07-content-flags.md#hardcover-content-warnings--mam-flags)

---

### 12.5: Integration & Caching

**Scope:**

- Register `HardcoverProvider` in provider registry
- Add FileCache with 7-day TTL (book metadata changes slowly)
- Wire into `MetadataAggregator`
- Add config options to `config.yaml`

**Config:**

```yaml
# config/config.yaml
hardcover:
  enabled: true
  api_key: ${HARDCOVER_API_KEY}
  match_threshold: 0.70
  cache_ttl_days: 7
```

---

## Prerequisites

Before starting Phase 12, complete:

| Item | Phase | Status | Why Needed |
| ---- | ----- | ------ | ---------- |
| FlagResolver | 9.2 | 📋 | Merge flags from Hardcover + Audnex |
| LocalFlagsProvider | 9.2 | 📋 | User overrides for incorrect flags |

**Alternative:** Implement Phase 12 with simple flag precedence (Hardcover wins over Audnex), then add FlagResolver later when needed.

---

## Exploratory Work Completed

| Artifact | Location | Purpose |
| -------- | -------- | ------- |
| Data gathering script | `scripts/data_gathering/hardcover_enrich.py` | API exploration |
| Enriched books | `data/hardcover_enriched_books.jsonl` | Test fixtures |
| Keyword vocabulary | `data/hardcover_keywords.json` | 60 warnings catalogued |
| API schemas | `docs/reference/hardcover/api/GraphQL/Schemas/` | GraphQL schema docs |

---

## Test Strategy

1. **Unit tests:** Mock GraphQL responses, test mapping logic
2. **Golden tests:** Verify flag mapping produces expected results
3. **Integration tests:** Real API calls against known books (rate-limited)

---

## Acceptance Criteria

- [ ] `HardcoverProvider` passes all unit tests
- [ ] Content warnings correctly map to MAM flags
- [ ] Fuzzy matching handles edge cases (threshold tuning)
- [ ] Cache reduces API calls on repeated lookups
- [ ] CLI shows Hardcover as source when used
- [ ] Documentation updated

---

## Related Documentation

- [providers/hardcover.md](../../providers/hardcover.md) — Provider design doc
- [archive/07-content-flags.md](../archive/07-content-flags.md) — Content flags mapping rules
- [archive/03-plugin-architecture.md](../archive/03-plugin-architecture.md) — Provider protocol
