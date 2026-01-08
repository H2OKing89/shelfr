# Phase 10: Parallel Region Lookup & Source Provenance

> **Status:** ✅ Complete | **All 7 sub-phases implemented**

## Overview

| Sub-phase | Description | Status |
| ----------- | ------------- | -------- |
| 10.1 | Async Client with Staged Racing | ✅ PR #86 |
| 10.2 | Region Cache with Smart Invalidation | ✅ PR #87 |
| 10.3 | Source Provenance Fields | ✅ PR #88 |
| 10.4 | Provider Lifecycle (AsyncExitStack) | ✅ PR #89 |
| 10.5 | Template Integration | ✅ PR #90 |
| 10.6 | Concurrency Hardening | ✅ PR #91 |
| 10.7 | Observability (CLI stats command) | ✅ PR #92 |

---

## Problem Statement

### Sequential Region Fallback (Before)

The Audnex client tried regions **sequentially** (us → uk → au → ca → ...) until one succeeded:

- **Slow:** 10 regions × ~1-3s each = up to 30s worst case
- **Wasteful:** Most ASINs are US-only but we still try all 10
- **No learning:** Every lookup repeats the full scan

### Hardcoded URLs (Before)

Templates hardcoded `audible.com` even when metadata came from `audible.co.uk`.

---

## Solution Architecture

### 1. Staged Race Strategy

Instead of racing all 10 regions (great for latency, terrible for rate limits), use two stages:

```
Cache hit  → 1 request (fast path)
Cache miss → Stage 1: race top 3 (us, uk, de) with 1.5s timeout
           → Stage 2: race ALL regions if Stage 1 fails
```

**Why Stage 2 races ALL regions:** If Stage 1 timed out (not 404), the correct region might have been us/uk/de but slow. Only skip regions with definitive 404s.

→ See [async-race-pattern.md](patterns/async-race-pattern.md) for implementation

### 2. Region Cache

Once we know `B0XXXXXX` belongs to `uk`, cache it:

- Try cached region first (single request)
- Track failures with `FailureType` enum: `NOT_FOUND` vs `TRANSIENT`
- Invalidate thresholds: 404 → 2 failures, transient → 5 failures

→ See [region-cache-pattern.md](patterns/region-cache-pattern.md) for implementation

### 3. Source Provenance

Split "retrieval provider" (API) from "source platform" (storefront):

| Field | Purpose | Example |
| ------- | --------- | --------- |
| `retrieved_via` | API that supplied data | `audnex` |
| `source_platform` | Storefront metadata represents | `Audible` |
| `source_region` | Region where ID resolved | `uk` |
| `source_id` | Primary identifier | `B0XXXXXX` |
| `source_id_type` | Type of identifier | `asin` |
| `source_url` | Pre-built canonical URL | `https://audible.co.uk/pd/B0XXXXXX` |

### 4. Rate Limiting

Dual limiters protect against both minute-scale and burst violations:

- **Minute limiter:** 90 req/min (under 100/min API limit)
- **Burst limiter:** 10 req/5s (protects against fixed-window limits)

→ See [rate-limiting-pattern.md](patterns/rate-limiting-pattern.md) for implementation

### 5. Provider Lifecycle

Providers manage shared resources (HTTP client, rate limiter) with explicit lifecycle:

- `startup()` → Initialize once per process
- `shutdown()` → Clean up at process end
- `AsyncExitStack` → Manages multiple async context managers

→ See [provider-lifecycle-pattern.md](patterns/provider-lifecycle-pattern.md) for implementation

---

## Key Design Decisions

### Why `as_completed()` Over `gather()`?

`gather()` waits for ALL tasks. `as_completed()` lets us:

1. Return immediately when first valid response arrives
2. Cancel remaining tasks (save bandwidth + rate limit budget)

### Why Track 404 vs Transient Failures?

| Failure Type | Meaning | Cache Action |
| -------------- | --------- | --------- |
| 404 | Mapping is wrong | Fast invalidation (2 failures) |
| Transient (5xx, timeout) | Temporary issue | Slow invalidation (5 failures) |

### Why NOT Race All 10 Regions?

- 100 req/min limit ÷ 10 regions = only 10 ASINs/min
- Staged race: typically 1-3 requests/ASIN = 30-90 ASINs/min

### Why Split `retrieved_via` vs `source_platform`?

Avoids semantic confusion:

- `retrieved_via="audnex"` + `source_url="audible.co.uk"` makes sense
- Template shows public source (Audible UK)
- Debug logs show retrieval path (Audnex API)

---

## CLI Commands

```bash
# View region cache statistics
shelfr audnex region-stats

# Example output:
# Region Distribution:
#   us: 1,234 (65.2%)
#   uk: 456 (24.1%)
#   de: 203 (10.7%)
# Total cached: 1,893
```

---

## Testing Strategy

| Test Category | Coverage |
| -------------- | --------- |
| Race mechanics | Timeout handling, 404 tracking, cancellation |
| Cache operations | Hit/miss/invalidation, atomic writes |
| Rate limiting | Dual limiter coordination |
| Provider lifecycle | Startup/shutdown, error recovery |
| Integration | End-to-end with mocked HTTP |

---

## Files Modified

| File | Changes |
| ------ | --------- |
| `audnex/async_client.py` | New `AudnexAsyncClient` with staged racing |
| `audnex/region_cache.py` | New `RegionCache` with failure tracking |
| `providers/audnex.py` | Uses shared client, populates provenance |
| `schemas/canonical.py` | Source provenance fields |
| `utils/audible_urls.py` | Region-correct URL builder |
| `cli/audnex.py` | `region-stats` command |
| `types.py` | `FailureType` enum |

---

## Migration Notes

- Old synchronous `fetch_audnex_book()` removed
- All Audnex lookups now go through `AudnexAsyncClient`
- Region cache auto-populates on first lookup
- Templates automatically use `source_url` when available

### Internal API Changes (Phase 10.7)

- `_race_regions()` returns 3 values: `(winner_tuple, definitive_404s, request_count)`
- `_staged_race()` returns 5 values: `(data, region, stage, total_requests, elapsed)`
- These signatures support observability instrumentation—do not revert
