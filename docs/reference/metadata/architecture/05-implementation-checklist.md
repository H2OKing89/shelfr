# Implementation Checklist

> Part of [Metadata Architecture Documentation](README.md)

---

## Phase 0: Package Scaffolding (Do First!)

> **Critical:** Python won't allow both `metadata.py` and `metadata/` to coexist.

- [x] Create `src/shelfr/metadata/` directory
- [x] Move `metadata.py` → `metadata/__init__.py` (contents unchanged)
- [x] Update any internal imports that referenced `metadata.py` as a module (no behavior change)
- [x] Verify import still works: `python -c "import shelfr.metadata; print(shelfr.metadata.__file__)"`
- [x] Run full test suite

**Why separate phase?** This is pure scaffolding — no behavior change, no refactoring, just enabling the package structure. Ship this first before any extraction.

> **Note:** After Phase 0, there is no `metadata.py` — the facade becomes `metadata/__init__.py`.
>
> **Reminder:** When creating new subpackages in later phases, add `__init__.py` files to each directory (unless intentionally using namespace packages).

---

## Phase 1: Extract MediaInfo (Leaf Module)

> MediaInfo is the cleanest extraction: no network, no state, pure functions.

- [x] Create `metadata/models.py` with shared `Chapter` dataclass
  - **Note:** Distinct from root-level `shelfr.models` (which holds `AudiobookRelease`, `NormalizedBook`, etc.)
  - Import as `from shelfr.metadata.models import Chapter` to avoid ambiguity
  - Verify after creation: `python -c "from shelfr.metadata.models import Chapter; from shelfr.models import AudiobookRelease"`
- [x] Create `metadata/mediainfo/__init__.py` + `extractor.py` with:
  - `AudioFormat` dataclass (MediaInfo-specific, stays here)
  - `detect_audio_format()`, `detect_audio_format_from_file()`
  - `run_mediainfo()`, `save_mediainfo_json()`
  - `_parse_chapters_from_mediainfo()`, `_extract_audio_info()`
- [x] Update `metadata/__init__.py` to re-export from new location
- [x] Run tests

**Test Migration:**

- Update imports: `from metadata.mediainfo import AudioFormat` → `from shelfr.metadata.mediainfo import AudioFormat`
- Update patch targets: `@patch("metadata.run_mediainfo")` → `@patch("shelfr.metadata.mediainfo.run_mediainfo")`
- Verify re-exports work: tests using `from shelfr.metadata import detect_audio_format` should still pass

---

## Phase 2: Extract Formatting (Presentation Layer)

- [x] Create `metadata/formatting/bbcode.py`:
  - **Public:** `render_bbcode_description()`
  - **Private:** `_convert_newlines_for_mam()`, `_format_release_date()`, `_parse_chapters_from_audnex()`
  - Import `Chapter` from `metadata/models.py` (not mediainfo)
- [x] Create `metadata/formatting/html.py`:
  - **Public:** `html_to_bbcode()` (no underscore — used externally)
  - **Private:** `_clean_html()`
- [x] Update re-exports

**Test Migration:**

- Update imports: `from metadata import render_bbcode_description` → `from shelfr.metadata.formatting.bbcode import render_bbcode_description`
- Update mocks: Replace `metadata._format_duration` patches with `shelfr.metadata.formatting.bbcode._format_duration`
- Verify `Chapter` imports from `metadata.models` (not `mediainfo`)

---

## Phase 3: Extract Audnex Client (Network Boundary)

- [x] Create `metadata/audnex/client.py` with:
  - `fetch_audnex_book()`, `fetch_audnex_author()`
  - `fetch_audnex_chapters()`, `_parse_chapters_from_audnex()`
  - `save_audnex_json()`
  - All `_fetch_audnex_*_region()` helpers
- [x] Keep chapters with client (shared HTTP/retry/circuit-breaker patterns)
- [x] Update re-exports

**Test Migration:**

- Update HTTP mocks: `@patch("httpx.Client")` → `@patch("shelfr.metadata.audnex.client.httpx.Client")`
- Update settings patches: `@patch("shelfr.metadata.get_settings")` → `@patch("shelfr.metadata.audnex.client.get_settings")`
- Test chapter parsing: `_parse_chapters_from_audnex` remains in `metadata.formatting.bbcode` (presentation layer)

---

## Phase 4: Extract MAM (Depends on Above)

> Do this later — `build_mam_json` touches everything (mediainfo, audnex, formatting).

- [x] Create `metadata/mam/categories.py`:
  - `FICTION_GENRE_KEYWORDS`, `NONFICTION_GENRE_KEYWORDS`
  - `_infer_fiction_or_nonfiction()`, `_get_audiobook_category()`, `_map_genres_to_categories()`
- [x] Create `metadata/mam/json_builder.py`:
  - `build_mam_json()`, `save_mam_json()`, `generate_mam_json_for_release()`
  - `_build_series_list()`, `_get_mediainfo_string()`
- [x] Update `metadata/__init__.py` to re-export from new location
- [x] Update test patch paths (`shelfr.metadata.mam.json_builder.get_settings`, `shelfr.metadata.mam.categories.get_settings`)
- [x] Run tests

**Test Migration:**

- Update category test imports: `from metadata.mam.categories import _infer_fiction_or_nonfiction`
- Update MAM JSON golden tests: adjust import paths to `shelfr.metadata.mam.json_builder`
- Verify integration: MAM builder depends on mediainfo/audnex/formatting extracted in Phases 1-3

---

## Phase 5: Schemas + Provider System + JSON Sidecar

> Split into sub-phases for smaller, reviewable PRs.

### Phase 5a: Schemas + Cleaning (no behavior change)

> **Guardrail:** Phase 5a introduces schemas + cleaning facade only; no pipeline conversion yet.

- [x] Create `metadata/schemas/__init__.py` + `canonical.py`:
  - `Person`, `Series`, `Genre`, `CanonicalMetadata` (ALL in one file)
  - **Design rationale:** Keep schema definitions co-located for easier updates and unified versioning (Phase 7). Circular imports are prevented by having aggregator import from schemas (not vice versa).
  - **Do NOT split into person.py/series.py/genre.py yet** (avoid circular import risk)
- [x] Create `metadata/cleaning.py` as **facade over existing functions**:
  - Re-export from `shelfr.utils.naming`: `filter_title`, `filter_subtitle`, etc.
  - **Don't duplicate** — wrap existing functions
- [x] Update `metadata/__init__.py` to re-export schemas and cleaning functions
- [x] Add tests for CanonicalMetadata schema and cleaning facade

### Phase 5b: Provider System (core architecture)

- [x] Create `metadata/providers/__init__.py` + `types.py`:
  - `LookupContext`, `ProviderResult`, `FieldName`, `IdType`, `ProviderKind`
- [x] Create `metadata/providers/base.py`:
  - `MetadataProvider` protocol
- [x] Create `metadata/providers/registry.py`:
  - `ProviderRegistry` (instance-based, stable ordering)
- [x] Create `metadata/providers/audnex.py`:
  - `AudnexProvider` (wraps client from Phase 3 in provider interface)
  - Ensure `kind = "network"` and `is_override = False` (required for two-stage fetch)
- [x] Create `metadata/providers/mock.py`:
  - `MockProvider` for testing (needed to test aggregator)
- [x] Create `metadata/aggregator.py`:
  - Basic `MetadataAggregator` with deterministic precedence
  - Two-stage fetch (local → network), `_safe_fetch()` error isolation
  - `_safe_fetch()` returns `ProviderResult(success=False, error=...)` on failure (never raises)

### Phase 5c: Orchestration + Exporters

- [x] Create `metadata/orchestration.py`:
  - Keep as **thin facade initially** (wire-through only, no new logic)
  - `fetch_metadata_legacy()`, `fetch_all_metadata_legacy()`, `save_metadata_files_legacy()`
  - New async API: `fetch_metadata_async()`, `export_metadata_async()`
- [x] Create `metadata/exporters/__init__.py` + `base.py`:
  - `MetadataExporter` protocol
  - Registry functions: `get_exporter()`, `list_exporters()`, `register_exporter()`
- [x] Create `metadata/exporters/json.py`:
  - `JsonExporter` for ABS metadata.json sidecar
  - Converts aggregated fields to ABS format with proper mappings
- [x] Add tests for orchestration and exporters (37 tests)

---

## Phase 6: Move OPF + Deprecations

- [x] Move `src/shelfr/opf/` → `metadata/opf/`
- [x] Create deprecation shim in `src/shelfr/opf/__init__.py`:
  - Old import path raises `DeprecationWarning` unless `SHELFR_ENABLE_LEGACY_OPF=1`
  - In legacy mode, old import path re-exports new functions
- [x] Create `metadata/exporters/opf.py`:
  - `OpfExporter` wrapping existing OPF generation
- [x] Add tests for OpfExporter (12 tests)

---

## Phase 7: Cleanup & Hygiene

> **Status:** ✅ Complete

### Schema Consolidation

- [x] ✅ **COMPLETE** Unify `AbsMetadataSchema` (`abs/rename.py`) with `AbsMetadataJson` (`schemas/abs_metadata.py`):
  - ✅ Audited differences (optional fields, naming conventions)
  - ✅ Migrated `abs/rename.py` to use `AbsMetadataJson`
  - ✅ Updated tests in `test_abs_rename.py`
  - ✅ Removed duplicate `AbsMetadataSchema` class
  - ✅ Tags field populated with Adult flag for consistency
  - **Completed in:** PR #78 (Phase 7 - Schema Consolidation, validated by `test_abs_metadata_write_validation.py` — 22 tests)
- [x] ✅ **DEFERRED** Unify `AudnexAuthor` / `AudnexSeries` with `Person` / `Series`:
  - **Rationale:** Circular import constraint prevents unification (see 01-current-state-audit.md § 2.2)
  - **Documentation:** Added detailed circular import explanation to audit doc
  - **Future work:** Can be unified after metadata package initialization refactor (Phase 8+)

### Documentation Updates

- [x] Update `01-current-state-audit.md` to reflect completed migration:
  - ✅ Marked duplicate schemas as resolved
  - ✅ Updated status annotations
  - ✅ Updated file inventory with new package structure
- [x] Update `02-recommendations.md`:
  - ✅ Marked all phases through Phase 7 as complete
  - ✅ Updated status summary
- [x] Review and update `README.md` in architecture folder:
  - ✅ Updated header to reflect "Migration Complete"
  - ✅ Updated executive summary with achievements
  - ✅ Updated file size summary

### Code Hygiene

- [x] Remove unused imports in migrated files:
  - ✅ Ran `ruff check --select F401` — all checks passed
  - Target: `metadata/` and `abs/` packages (production code only)
- [x] Run `ruff check --fix` across metadata package:
  - ✅ All checks passed
  - Target: `src/shelfr/metadata/` and `src/shelfr/abs/`
- [x] Verify all `__all__` exports are accurate in facade modules:
  - ✅ `metadata/__init__.py` — exports match imports
  - ✅ `metadata/exporters/__init__.py` — exports match imports
  - ✅ `metadata/providers/__init__.py` — exports match imports
- [x] Check for any TODO/FIXME comments in production code:
  - ✅ Found 1 TODO in `aggregator.py:371` (low priority, deferred to Phase 8+)
  - Target: Production code only (`metadata/`, `abs/` packages)

### Deprecation Tracking

- [x] Document deprecation timeline for `shelfr.opf` shim (target: v2.0):
  - ✅ Shim in place at `src/shelfr/opf/__init__.py`
  - ✅ Emits `DeprecationWarning` unless `SHELFR_ENABLE_LEGACY_OPF=1`
- [x] Document deprecation timeline for `cli_argparse.py` (target: v2.0):
  - ✅ Deprecation warning in `build_parser()` function
  - ✅ Module docstring documents deprecation
- [x] Add deprecation notes to CHANGELOG:
  - ✅ Added "Deprecated" section to [Unreleased]

---

## Phase 8: Infrastructure (As Needed)

> **Status:** ✅ Tier 1 Complete (Infrastructure) | ⚠️ Production Integration Pending
>
> **What's done:** Cache + rate limiting implemented and tested (22 tests passing)
> **What's needed:** Wire provider system into production workflow (follow-up PR)
>
> These are optional enhancements — the core system works without them. Prioritize by ROI.

### ROI Analysis: Recommended Implementation Order

#### Tier 1: High ROI (Ship First) 🏆

**1. Caching Layer** — Estimated effort: 2-4 hours | **ROI: 100-300x speedup** ✅ **COMPLETE**

- [x] Create `metadata/cache.py` with `MetadataCache` protocol
- [x] Implement `FileCache` (JSON-based, ~50 lines)
- [x] Add schema-versioned cache keys (auto-invalidate on `CanonicalMetadata` changes)
- [x] Integrate cache into `AudnexProvider.fetch()`
- [x] Add cache config: TTL (default 30 days), max size, location

**Business case:**

- Network fetch: 1-3 seconds per book (Audnex API)
- Cached fetch: <10ms per book (disk read)
- **Massive time savings on re-runs, testing, corrections**
- Survives network outages and API downtime
- Reduces API rate limit risk

**Implementation notes:**

- Cache key format: `{schema_version}:{provider}:{id_type}:{identifier}:{region}`
- Store `CachedResult` dataclass (includes `fetched_at`, `confidence`, `fields`)
- Atomic writes to avoid corruption on crashes

**2. Per-Provider Rate Limiting** — Estimated effort: 1-2 hours | **ROI: Prevents API bans** ✅ **COMPLETE**

- [x] Add `aiolimiter` dependency
- [x] ~~Create `metadata/providers/resilience.py` with `ProviderResilience` class~~ (integrated directly into AudnexProvider)
- [x] Integrate rate limiter into `AudnexProvider` (default: 10 req/sec)
- [x] Add rate limit config per provider

**Business case:**

- Good API citizenship (prevents bans)
- Protects against accidental hammering during batch processing
- Completes resilience story (already have circuit breakers)

**Implementation notes:**

- Use `aiolimiter.AsyncLimiter` (token bucket algorithm)
- Config: `providers.audnex.rate_limit.max_rate = 10` (requests per second)
- Wrap `fetch()` calls with rate limiter context

---

#### Tier 2: Medium ROI (Build When Needed)

**3. Schema Versioning** — Estimated effort: 2-3 hours | **ROI: Future-proofs cache and migrations**

- [ ] Add `schema_version` field to `CanonicalMetadata`
- [ ] Create `metadata/schemas/versioning.py` with `SCHEMA_VERSION` constant
- [ ] Implement version migration helpers for old cached data
- [ ] Update cache read path to auto-migrate old versions

**Business case:**

- When `CanonicalMetadata` changes, old cached data becomes invalid
- Version-aware cache auto-invalidates outdated entries
- Enables gradual schema evolution without breaking changes

**Build when:** Adding/changing fields in `CanonicalMetadata`

**4. Performance Optimization (Two-Stage Fetch)** — Estimated effort: 1-2 hours | **ROI: Faster when locals have data**

- [ ] Audit current aggregator implementation of two-stage fetch
- [ ] Add timing metrics per provider (`provider_timings` in `AggregatedResult`)
- [ ] Optimize parallel execution of network providers
- [ ] Add logging for fetch performance analysis

**Business case:**

- Skip slow network calls if local providers (ABS sidecar, MediaInfo) have needed fields
- Useful when `stop_on_complete=True` and locals already have title/author/etc.

**Build when:** Batch processing becomes slow despite caching

---

#### Tier 3: Low ROI (Defer or Skip)

**5. Event Hooks / Middleware** — Estimated effort: 3-4 hours | **ROI: Debugging/alerts only**

- [ ] Create `metadata/events.py` with `EventBus` class
- [ ] Add event emission points in aggregator (conflicts, errors, overrides)
- [ ] Optional: Discord/webhook integrations for alerts

**Business case:**

- Structured logging covers 80% of use cases
- Only needed for external integrations (alerts, monitoring)

**Build when:** You actually need Discord alerts or monitoring webhooks

**YAGNI:** Likely unnecessary for single-user tool

**6. Batch Operations Support** — Estimated effort: 4-6 hours | **ROI: Only if API supports bulk**

- [ ] Add `supports_batch` + `fetch_batch()` to `MetadataProvider` protocol
- [ ] Update aggregator to use batch fetch when available
- [ ] Implement batch support in providers that offer it

**Business case:**

- Useful for APIs that support bulk lookups (e.g., pass 10 ASINs at once)
- **Problem:** Audnex doesn't support bulk queries (one ASIN per request)

**Build when:** Adding a provider with bulk API support (Hardcover, Goodreads)

**7. Data Provenance Enhancement** — Estimated effort: 2-3 hours | **ROI: Debugging tool only**

- [ ] Extend `AggregatedResult.provenance` with detailed field history
- [ ] Add UI/logging to show "why did this field win?"
- [ ] Track confidence scores and conflict resolution reasoning

**Business case:**

- Helpful for debugging aggregation rules
- Current `sources` dict + `conflicts` list already provide basic provenance

**Build when:** Debugging "why this value?" becomes frequent

---

### Recommended Phase 8 MVP (Total: 3-6 hours)

**Ship as "Phase 8 Tier 1 Complete":** ✅

1. ✅ Caching layer (FileCache + AudnexProvider integration) - **22 tests passing**
2. ✅ Rate limiting (aiolimiter + AudnexProvider)

**Status:** Infrastructure implemented and tested. Ready to use once production workflow switches to provider system.

**Production Integration Status:** ⚠️ **Pending**

The cache and rate limiting are fully implemented in `AudnexProvider`, but the production code path still uses the legacy `fetch_audnex_book()` function directly, bypassing the provider system.

**Current production flow:**

```python
# commands/mam.py → metadata/__init__.py
fetch_all_metadata()
  → fetch_all_metadata_legacy()
    → fetch_audnex_book()  # Legacy - NO cache, NO rate limiting
```

**Where cache/rate limiting live (tested, not used yet):**

```python
AudnexProvider.fetch()  # HAS cache + rate limiting, fully tested
```

**Next Step (Phase 8.5 - Production Integration):**

- [ ] Update `fetch_all_metadata_legacy()` to use provider system internally
- [ ] Or: Add cache/rate limiting directly to legacy `fetch_audnex_book()`
- [ ] Estimated effort: 2-4 hours

**Defer to future phases:**

- Schema versioning (add when cache needs migration)
- Performance optimization (add when caching isn't enough)
- Events, batch ops, provenance (add when actually needed)

**Why this scope is correct:**

- Solves biggest real-world bottleneck (slow network fetches)
- Low implementation risk (well-understood patterns)
- Infrastructure validated by comprehensive test suite
- Foundation for future work (cache enables offline operation)
- Clean separation: infrastructure vs production integration

---

### Testing Strategy for Phase 8

| Component | Test Focus |
| --- | --- |
| **FileCache** | Cache hit/miss, TTL expiration, schema versioning, atomic writes, disk I/O errors |
| **Rate Limiting** | Request throttling, burst handling, config-driven limits |
| **Schema Versioning** | Migration from old versions, version mismatch detection |
| **Integration** | Cached provider results, rate-limited network calls, end-to-end timing |

---

## Future (As Needed)

- [ ] Hardcover provider
- [ ] Goodreads provider
- [ ] NFO exporter
- [ ] Batch operations
- [ ] Custom user fields

---

## Progress Tracking

| Phase | Status | Notes |
| --- | --- | --- |
| Phase 0 | ✅ Complete | Package scaffolding (PR #66) |
| Phase 1 | ✅ Complete | MediaInfo extraction (PR #66) |
| Phase 2 | ✅ Complete | Formatting extraction (PR #67) |
| Phase 3 | ✅ Complete | Audnex client extraction (PR #68) |
| Phase 4 | ✅ Complete | MAM extraction (categories.py + json_builder.py) |
| Phase 5a | ✅ Complete | Schemas + Cleaning (PR #73) |
| Phase 5b | ✅ Complete | Provider system + Aggregator |
| Phase 5c | ✅ Complete | Orchestration + JSON exporter (PR #75) |
| Phase 6 | ✅ Complete | OPF move + deprecations + OpfExporter (PR #76) |
| Phase 7 | ✅ Complete | Cleanup & Hygiene (PR #78, PR #79) |
| Phase 8 | ✅ Tier 1 Complete | Infrastructure (cache + rate limiting) - Production integration pending |
| Future | ⏳ Not Started | As needed |

---

## Dependencies

```text
Phase 0 (Scaffolding) ← MUST BE FIRST
    │
    ▼
Phase 1 (MediaInfo) ──→ Phase 2 (Formatting) ──→ Phase 3 (Audnex)
    │                                                   │
    │                                                   ▼
    │                                            Phase 4 (MAM)
    │                                                   │
    ▼                                                   ▼
Phase 5a/5b/5c (Schemas/Providers/JSON) ←───────────────┘
    │
    ▼
Phase 6 (OPF + Deprecations)
    │
    ▼
Phase 7 (Cleanup & Hygiene)
    │
    ▼
Phase 8 (Infrastructure - optional)
```

**Critical Path for JSON sidecar:** Phase 0 → Phase 5a (schemas) → Phase 5c (JSON exporter)

> *Assumes existing metadata fetch logic still lives in `metadata/__init__.py` until Phase 3 extraction.*

**Alternative path:** Phase 5a (schemas) doesn't actually depend on Phase 1 extraction — you can do Phase 0 → Phase 5a → Phase 5c if you want JSON sidecar before extracting MediaInfo.

---

## Testing Strategy

### Per-Phase Testing

| Phase | Test Focus |
| --- | --- |
| Phase 0 | Import smoke test, full test suite passes |
| Phase 1 | MediaInfo parsing, AudioFormat detection |
| Phase 2 | BBCode output, HTML conversion |
| Phase 3 | Mock HTTP responses, circuit breaker |
| Phase 4 | Category mapping, MAM JSON golden tests |
| Phase 5a | Schema validation, cleaning idempotence |
| Phase 5b | MockProvider, aggregator merge logic, registry, deterministic tie-breaking (same confidence → priority wins), override provider behavior (empty values), two-stage fetch short-circuit |
| Phase 5c | Orchestration wire-through, JSON exporter golden tests |
| Phase 6 | OPF output, deprecation shim behavior |
| Phase 7 | Schema consolidation, import cleanup |
| Phase 8 | Cache hit/miss, event emission |

### Integration Tests

- [ ] Full pipeline: Provider → CanonicalMetadata → Exporter
- [ ] Fallback chain: Primary fails → Secondary succeeds
- [ ] Cache integration: Cached vs fresh data
- [ ] Error handling: All providers fail gracefully
