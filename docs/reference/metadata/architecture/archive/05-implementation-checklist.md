# Implementation Checklist

> Part of [Metadata Architecture Documentation](README.md)

---

## Phase 0: Package Scaffolding (Do First!)

> **Status:** ✅ Complete | **Code Verified:** 2026-01-05
>
> **Critical:** Python won't allow both `metadata.py` and `metadata/` to coexist.

- [x] Create `src/shelfr/metadata/` directory
- [x] Move `metadata.py` → `metadata/__init__.py` (contents unchanged)
- [x] Update any internal imports that referenced `metadata.py` as a module (no behavior change)
- [x] Verify import still works: `python -c "import shelfr.metadata; print(shelfr.metadata.__file__)"`
- [x] Run full test suite

**Code Verification (2026-01-05):**

- ✅ `src/shelfr/metadata/__init__.py` exists (~334 lines)
- ✅ Package imports work in production

**Why separate phase?** This is pure scaffolding — no behavior change, no refactoring, just enabling the package structure. Ship this first before any extraction.

> **Note:** After Phase 0, there is no `metadata.py` — the facade becomes `metadata/__init__.py`.
>
> **Reminder:** When creating new subpackages in later phases, add `__init__.py` files to each directory (unless intentionally using namespace packages).

---

## Phase 1: Extract MediaInfo (Leaf Module)

> **Status:** ✅ Complete | **Code Verified:** 2026-01-05 | **Production Wired:** ✅ YES
>
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

**Code Verification (2026-01-05):**

- ✅ `metadata/mediainfo/extractor.py` exists with `run_mediainfo()` at line 299
- ✅ Production path: `workflow.py` → `fetch_metadata()` → `fetch_metadata_legacy()` → `run_mediainfo()`
- ✅ `orchestration.py` line 37: `from shelfr.metadata.mediainfo import run_mediainfo`
- ✅ `orchestration.py` line 80: `mediainfo_data = run_mediainfo(m4b_path)`

**Test Migration:**

- Update imports: `from metadata.mediainfo import AudioFormat` → `from shelfr.metadata.mediainfo import AudioFormat`
- Update patch targets: `@patch("metadata.run_mediainfo")` → `@patch("shelfr.metadata.mediainfo.run_mediainfo")`
- Verify re-exports work: tests using `from shelfr.metadata import detect_audio_format` should still pass

---

## Phase 2: Extract Formatting (Presentation Layer)

> **Status:** ✅ Complete | **Code Verified:** 2026-01-05 | **Production Wired:** ✅ YES

- [x] Create `metadata/formatting/bbcode.py`:
  - **Public:** `render_bbcode_description()`
  - **Private:** `_convert_newlines_for_mam()`, `_format_release_date()`, `_parse_chapters_from_audnex()`
  - Import `Chapter` from `metadata/models.py` (not mediainfo)
- [x] Create `metadata/formatting/html.py`:
  - **Public:** `html_to_bbcode()` (no underscore — used externally)
  - **Private:** `_clean_html()`
- [x] Update re-exports

**Code Verification (2026-01-05):**

- ✅ `metadata/formatting/bbcode.py` exists with `render_bbcode_description()` at line 126
- ✅ Production path: `commands/mam.py` line 132 calls `render_bbcode_description()`
- ✅ Import verified: `from shelfr.metadata import render_bbcode_description`

**Test Migration:**

- Update imports: `from metadata import render_bbcode_description` → `from shelfr.metadata.formatting.bbcode import render_bbcode_description`
- Update mocks: Replace `metadata._format_duration` patches with `shelfr.metadata.formatting.bbcode._format_duration`
- Verify `Chapter` imports from `metadata.models` (not `mediainfo`)

---

## Phase 3: Extract Audnex Client (Network Boundary)

> **Status:** ✅ Complete | **Code Verified:** 2026-01-05 | **Production Wired:** ✅ YES

- [x] Create `metadata/audnex/client.py` with:
  - `fetch_audnex_book()`, `fetch_audnex_author()`
  - `fetch_audnex_chapters()`, `_parse_chapters_from_audnex()`
  - `save_audnex_json()`
  - All `_fetch_audnex_*_region()` helpers
- [x] Keep chapters with client (shared HTTP/retry/circuit-breaker patterns)
- [x] Update re-exports

**Code Verification (2026-01-05):**

- ✅ `metadata/audnex/client.py` exists with `fetch_audnex_book()` at line 111
- ✅ Production path: `orchestration.py` line 32-35 imports from `shelfr.metadata.audnex`
- ✅ Production call: `orchestration.py` line 75: `audnex_data, _ = fetch_audnex_book(asin)`

**Test Migration:**

- Update HTTP mocks: `@patch("httpx.Client")` → `@patch("shelfr.metadata.audnex.client.httpx.Client")`
- Update settings patches: `@patch("shelfr.metadata.get_settings")` → `@patch("shelfr.metadata.audnex.client.get_settings")`
- Test chapter parsing: `_parse_chapters_from_audnex` remains in `metadata.formatting.bbcode` (presentation layer)

---

## Phase 4: Extract MAM (Depends on Above)

> **Status:** ✅ Complete | **Code Verified:** 2026-01-05 | **Production Wired:** ✅ YES
>
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

**Code Verification (2026-01-05):**

- ✅ `metadata/mam/json_builder.py` exists with `generate_mam_json_for_release()` at line 472
- ✅ Production path: `workflow.py` line 52 imports `generate_mam_json_for_release`
- ✅ Production call: `workflow.py` line 412: `mam_json_path = generate_mam_json_for_release(release, ...)`

**Test Migration:**

- Update category test imports: `from metadata.mam.categories import _infer_fiction_or_nonfiction`
- Update MAM JSON golden tests: adjust import paths to `shelfr.metadata.mam.json_builder`
- Verify integration: MAM builder depends on mediainfo/audnex/formatting extracted in Phases 1-3

---

## Phase 5: Schemas + Provider System + JSON Sidecar

> **Status:** ✅ Complete | **Code Verified:** 2026-01-05 | **Production Wired:** ✅ YES (Phase 8.5)
>
> Split into sub-phases for smaller, reviewable PRs.
>
> **✅ Provider system now wired to production** via `_fetch_audnex_with_provider()` in orchestration.py.
> Caching and rate limiting are active by default. Use `--no-cache` to bypass.

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

**Code Verification (2026-01-05):**

- ✅ `metadata/schemas/canonical.py` exists with `CanonicalMetadata`, `Person`, `Series`, `Genre`
- ✅ `metadata/cleaning.py` exists as facade over `utils/naming`

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

**Code Verification (2026-01-05):**

- ✅ `metadata/providers/audnex.py` exists with `AudnexProvider` class
- ✅ `metadata/providers/mock.py` exists with `MockProvider` class
- ✅ `metadata/providers/registry.py` exists with `ProviderRegistry` and `default_registry`
- ✅ `metadata/aggregator.py` exists with `MetadataAggregator` class
- ✅ **NOW in production path** - `AudnexProvider` called via `_fetch_audnex_with_provider()` (Phase 8.5)

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

**Code Verification (2026-01-05):**

- ✅ `metadata/orchestration.py` exists with both legacy and async APIs
- ✅ `metadata/exporters/json.py` exists with `JsonExporter` class
- ✅ `metadata/exporters/opf.py` exists with `OpfExporter` class
- ✅ **NOW in production path** - `workflow.py` → `fetch_metadata()` → `orchestration.fetch_metadata_legacy(use_cache=True)`
  → `_fetch_audnex_with_provider()` → `AudnexProvider.fetch()` (Phase 8.5 complete)
- ⚠️ Async API (`fetch_metadata_async`, `export_metadata_async`) exists but NOT called from CLI/workflow (not needed for current use case)

---

## Phase 6: Move OPF + Deprecations

> **Status:** ✅ Complete | **Code Verified:** 2026-01-05 | **Production Wired:** ✅ YES

- [x] Move `src/shelfr/opf/` → `metadata/opf/`
- [x] Create deprecation shim in `src/shelfr/opf/__init__.py`:
  - Old import path raises `DeprecationWarning` unless `SHELFR_ENABLE_LEGACY_OPF=1`
  - In legacy mode, old import path re-exports new functions
- [x] Create `metadata/exporters/opf.py`:
  - `OpfExporter` wrapping existing OPF generation
- [x] Add tests for OpfExporter (12 tests)

**Code Verification (2026-01-05):**

- ✅ `metadata/opf/generator.py` exists with `write_opf()` function
- ✅ `abs/importer.py` line 1835 calls `write_opf()` in production
- ✅ Production path confirmed: `import_to_audiobookshelf()` → `write_opf()`

---

## Phase 7: Cleanup & Hygiene

> **Status:** ✅ Complete | **Code Verified:** 2026-01-05 | **Production Wired:** ✅ YES

### Schema Consolidation

- [x] ✅ **COMPLETE** Unify `AbsMetadataSchema` (`abs/rename.py`) with `AbsMetadataJson` (`schemas/abs_metadata.py`):
  - ✅ Audited differences (optional fields, naming conventions)
  - ✅ Migrated `abs/rename.py` to use `AbsMetadataJson`
  - ✅ Updated tests in `test_abs_rename.py`
  - ✅ Removed duplicate `AbsMetadataSchema` class
  - ✅ Tags field populated with Adult flag for consistency
  - **Completed in:** PR #78 (Phase 7 - Schema Consolidation, validated by `test_abs_metadata_write_validation.py` — 22 tests)

**Code Verification (2026-01-05):**

- ✅ `abs/rename.py` line 38: `from shelfr.schemas.abs_metadata import AbsMetadataJson`
- ✅ `abs/rename.py` line 230: `schema = AbsMetadataJson.model_validate(data)`
- ✅ No `class AbsMetadataSchema` found in codebase (grep verified)
- ✅ All `abs/rename.py` validation uses unified `AbsMetadataJson` schema

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

## Phase 8: Infrastructure (Cache + Rate Limiting)

> **Status:** ✅ Implemented | **Code Verified:** 2026-01-05 | **Production Wired:** ✅ YES
>
> **What's done:** Cache + rate limiting implemented, tested (22 tests), and wired to production
> **Production path:** `workflow.py` → `fetch_metadata()` → `orchestration.fetch_metadata_legacy(use_cache=True)` → `_fetch_audnex_with_provider()` → `AudnexProvider.fetch()` (cached + rate-limited)
>
> ✅ **Phase 8.5 Complete:** Production workflow now uses `AudnexProvider` with caching and rate limiting.
> See [Phase 8.5 Implementation](#phase-85-production-integration--complete) for details.

**Code Verification (2026-01-05):**

- ✅ `metadata/cache.py` exists with `FileCache`, `NoOpCache`, `MetadataCache` protocol
- ✅ `metadata/providers/audnex.py` line 66: calls `get_default_cache()` in `__init__`
- ✅ `metadata/providers/audnex.py` lines 78-130: `fetch()` method uses cache
- ✅ **Production path now uses provider:**
  - `workflow.py` line 140 → `fetch_metadata()` (facade)
  - → `orchestration.fetch_metadata_legacy(use_cache=True)` line 139
  - → `_fetch_audnex_with_provider()` line 53 (uses `AudnexProvider`)

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

### Phase 8.5: Production Integration ✅ COMPLETE

> **Status:** ✅ Complete | **Code Verified:** 2026-01-05

**What was done:**

- [x] Updated `orchestration.fetch_metadata_legacy()` to use `AudnexProvider` (Option A: sync wrapper)
- [x] Added `use_cache` parameter to `fetch_metadata_legacy()`, `fetch_all_metadata_legacy()`, `fetch_metadata()`
- [x] Added `--no-cache` global CLI flag to disable caching
- [x] Wired `use_cache` through `workflow.py` → `process_single_release()` → `full_run()`
- [x] Updated `RuntimeContext` and `ArgsNamespace` to propagate `no_cache` flag

**Implementation details:**

- `_fetch_audnex_with_provider()` wraps `AudnexProvider.fetch()` for sync use
- Uses `asyncio.run()` when no event loop running, ThreadPoolExecutor when inside async context
- Cache is enabled by default; use `shelfr --no-cache run` to bypass
- All 2552 tests passing

**Files modified:**

- `orchestration.py` — Added `_fetch_audnex_with_provider()` and `use_cache` parameter
- `metadata/__init__.py` — Added `use_cache` to public API
- `workflow.py` — Propagated `use_cache` through pipeline
- `cli/_app.py` — Added `--no-cache` global flag
- `cli/_context.py` — Added `no_cache` to RuntimeContext
- `cli/_helpers.py` — Added `no_cache` to ArgsNamespace bridge

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
# workflow.py → metadata/__init__.py
fetch_metadata()
  → fetch_metadata_legacy()
    → fetch_audnex_book()  # Legacy - NO cache, NO rate limiting
```

**Where cache/rate limiting live (tested, not used yet):**

```python
AudnexProvider.fetch()  # HAS cache + rate limiting, fully tested
```

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

## Phase 8.5: Production Integration Wiring — Original Design Spec

> **Status:** ✅ Complete (see [Phase 8.5 Summary](#phase-85-production-integration--complete) above)
>
> **Prerequisite:** Phase 8 Tier 1 Complete ✅
>
> **Goal:** Wire the provider system (with cache + rate limiting) into production workflow.
>
> *Note: This section preserved as historical design spec. Implementation followed Option A.*

### Option A: Update Legacy Functions to Use Provider System (Recommended)

**Estimated effort:** 2-4 hours

- [ ] Update `fetch_metadata_legacy()` in `orchestration.py` to optionally use `AudnexProvider`
- [ ] Add `use_provider_system: bool = False` flag (feature flag for gradual rollout)
- [ ] Wire cache directory config from settings
- [ ] Add integration tests for provider-based fetch path
- [ ] Flip flag to `True` after validation

**Benefits:**

- Single code path eventually (provider system)
- Cache + rate limiting automatically enabled
- Foundation for adding more providers (MediaInfo, Libation, AbsSidecar)

### Option B: Add Cache to Legacy Client (Faster but Dead-End)

**Estimated effort:** 1-2 hours

- [ ] Add `FileCache` integration to `fetch_audnex_book()` in `audnex/client.py`
- [ ] Add rate limiting to legacy client

**Drawbacks:**

- Duplicates caching logic (provider + legacy)
- Doesn't advance toward unified provider system
- **Not recommended** unless urgent production need

### Future Providers (After Integration)

Once production integration is complete, these providers can be added:

| Provider | Priority | Effort | Notes |
| --- | --- | --- | --- |
| `MediaInfoProvider` | Medium | 1-2h | Wrap existing `run_mediainfo()` |
| `LibationProvider` | Low | 1-2h | Extract from discovery logic |
| `AbsSidecarProvider` | Low | 2h | Read existing metadata.json |

---

### Testing Strategy for Phase 8

| Component | Test Focus |
| --- | --- |
| **FileCache** | Cache hit/miss, TTL expiration, schema versioning, atomic writes, disk I/O errors |
| **Rate Limiting** | Request throttling, burst handling, config-driven limits |
| **Schema Versioning** | Migration from old versions, version mismatch detection |
| **Integration** | Cached provider results, rate-limited network calls, end-to-end timing |

---

## Phase 9: Content Flags & Platform-Agnostic Metadata

> **Status:** ✅ Complete | **Code Verified:** 2026-01-06 | **Production Wired:** ✅ YES
>
> **Goal:** Add platform-agnostic content classification flags to canonical schema for MAM and future platforms.
>
> **What's Shipped:** Full implementation with comprehensive test coverage.
>
> - Core: Schema, provider, MAM builder
> - Tests: 13 dedicated tests for content_flags
> - Docs: Architecture, provider docs updated

### Current Gap (RESOLVED ✅)

MAM upload requires content flags (`cLang`, `vio`, `sSex`, `eSex`, `abridged`, `lgbt`), but our canonical schema only has:

- `is_adult: bool` (too broad, maps to `eSex` but doesn't distinguish `sSex`)
- `format_type: str` (only handles `abridged`)

Missing: crude language, violence, sexual content granularity, LGBT themes.

### Implementation Tasks

**9.1: Extend Canonical Schema** — ✅ Complete

- [x] Add `content_flags` field to `CanonicalMetadata` in `schemas/canonical.py`
  - Type: `list[ContentFlag]` (where `ContentFlag = Literal["cLang", "vio", "sSex", "eSex", "abridged", "lgbt"]`)
  - Default: empty list `[]` (via `default_factory=list`)
  - Note: Order is not significant but may be preserved; duplicates are allowed and handled by consumers
  - Description: Platform-agnostic content warnings/classification
- [x] Add validation: flags are mutually exclusive where appropriate (e.g., can't have both `sSex` and `eSex`)
  - Implemented: `validate_mutually_exclusive_flags` validator (lines 157-167)
- [x] Update example/docstring showing usage
- [x] Add migration note for existing data

**Code Verification (2026-01-06):**

- ✅ `schemas/canonical.py` line 136: `content_flags` field with proper Literal type
- ✅ Field validator prevents `sSex` and `eSex` coexistence
- ✅ Production path: `CanonicalMetadata` used by all providers and exporters

**9.2: Update MAM JSON Builder** — ✅ Complete

- [x] Update `build_mam_json()` in `mam/json_builder.py` to use `content_flags` from canonical
  - Implemented: lines 420-445 check `content_flags` first
- [x] Deprecate old logic that infers from `is_adult`/`format_type` directly
  - Backward compatible: falls back to legacy fields if `content_flags` empty
- [x] Add backward compatibility: still populate from `is_adult` if `content_flags` is empty

**Code Verification (2026-01-06):**

- ✅ `mam/json_builder.py` lines 420-445: prefers explicit `content_flags`, falls back gracefully
- ✅ Uses `getattr()` for safer attribute access

**9.3: Provider Integration** — ✅ Complete

- [x] Update `AudnexProvider._map_to_result()` to map Audnex data to `content_flags`
  - Map `isAdult=True` → `["sSex"]` (weak signal - suggestive, not explicit)
  - Map `formatType="abridged"` → `["abridged"]`
  - Map `genres[].name` containing `"LGBTQ+"` or `"LGBT"` → `["lgbt"]`
  - Document what Audnex does NOT provide (crude language, violence)
- [x] Add note about manual override mechanisms for flags Audnex doesn't detect
- [x] Added type guards: `isinstance()` checks for `format_type` and `genre_name` (lines 221-234)
- [x] Priority updated from 10→70 to match documentation

**Code Verification (2026-01-06):**

- ✅ `providers/audnex.py` lines 214-235: content flag inference with type guards
- ✅ Production path: `orchestration.py` → `_fetch_audnex_with_provider()` → `AudnexProvider.fetch()`

**9.4: Tests** — ✅ Complete

- [x] Test canonical schema validation (valid flags, invalid flags, duplicates)
  - `test_metadata.py`: 6 content_flags tests for schema validation
- [x] Test MAM JSON generation with various flag combinations
  - `test_providers.py`: Tests cover flag inference paths
- [x] Test provider mapping from Audnex data
  - `test_providers.py`: 7 content_flags tests for AudnexProvider (isAdult→sSex, abridged, lgbt, type guards)
- [x] Golden test updates for new field
  - Not needed: content_flags doesn't affect existing golden files

**Current Test Status:**

- ✅ All 2565+ tests passing (no failures, no warnings)
- ✅ Schema validation working with mutual exclusivity checks
- ✅ Full coverage for content_flags feature (13 dedicated tests)

**9.5: Documentation** — ✅ Complete

- [x] Update architecture docs with content flags design
  - Updated: `07-content-flags.md` (fixed broken anchor, clarified shipped vs planned)
- [x] Document which providers populate which flags
  - Updated: `providers/audnex.md` (fixed typo, added priority field)
  - Updated: `providers/hardcover.md` (clarified priority meanings, provenance info)
- [x] Add example showing manual override workflow
  - Documented in architecture files
- [ ] Update CHANGELOG
  - **PENDING:** Need to add Phase 9 entry to `CHANGELOG.md`

### Design Decisions

**Why `content_flags` over separate boolean fields?**

- Matches MAM API structure (list of strings)
- Easier to extend with new flags (no schema change needed)
- Platform-agnostic (can add AO3 warnings, MPAA ratings, etc.)

**Why these specific flag names?**

- Start with MAM's vocabulary for immediate use case
- Can be aliased/mapped by exporters for other platforms

**Future extensibility:**

```python
# Phase 10+: Add more platform flags as needed
#
# ⚠️ Design note: content_flags are provider-scoped. When exporting to a
# specific platform (MAM, AO3, etc.), only use flags that platform understands.
# Exporters must map or filter flags by source/provider—don't send the mixed
# set as-is. Future AO3 and MPAA entries shown below are separate systems that
# require separate handling by exporters.
content_flags: list[Literal[
    # MAM flags (Phase 9 - shipped)
    "cLang", "vio", "sSex", "eSex", "abridged", "lgbt",
    # Future: AO3 archive warnings (separate tracking)
    "graphic-violence", "major-character-death", "underage",
    # Future: MPAA-style ratings (separate system)
    "rated-r", "rated-pg13"
]]
```

---

## Phase 10: Parallel Region Lookup & Source Provenance

> **Status:** 📋 Planning | **Priority:** High
>
> **Goal:** Replace sequential region fallback with parallel "race" semantics, cache winning region, and make source URLs truly platform-agnostic.
>
> **Full specification:** [10-parallel-region-lookup.md](10-parallel-region-lookup.md)

### Problem

Current Audnex client tries regions **sequentially** (up to 30s worst case). ASINs are region-locked, but we don't remember which region worked.

### Solution

1. **Parallel race:** Fire all regions at once, take first valid response, cancel rest (~1.5s)
2. **Region cache:** Remember `ASIN → region` mapping for next time (single request on cache hit)
3. **Source provenance:** Add `source_url`, `source_region`, `source_provider` to canonical schema
4. **Platform-agnostic templates:** Use `source_url` instead of hardcoded `audible.com`

### Key Tasks

- [x] **10.1:** Async `fetch_audnex_book_parallel()` with `as_completed` race pattern ✅ PR #86
- [x] **10.2:** `RegionCache` class (ASIN → region mapping with TTL) ✅ PR #87
- [x] **10.3:** Add source provenance fields to `CanonicalMetadata` ✅ Complete
- [x] **10.4:** Update `AudnexProvider` to use parallel fetch + populate source fields ✅ PR #89
- [x] **10.5:** Update `mam_description.j2` with conditional `source_url` ✅ PR #90
- [x] **10.6:** Two-level concurrency limits (ASIN semaphore + rate limiting) ✅ PR #91
- [ ] **10.7:** Observability (race logging, `shelfr audnex region-stats` command)

---

## Future (As Needed)

- [ ] Hardcover provider
- [ ] Goodreads provider
- [ ] NFO exporter
- [ ] Batch operations
- [ ] Custom user fields
- [ ] Additional content classification systems (MPAA, AO3, etc.)

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
| Phase 8 | ✅ Tier 1 Complete | Infrastructure (cache + rate limiting in AudnexProvider) |
| Phase 8.5 | ✅ Complete | Production integration (PR #82) |
| Phase 9 | ✅ Complete | Content flags (PR #83) - Core + tests shipped, CHANGELOG pending |
| Phase 10 | 🔄 In Progress | 10.1-10.6 ✅ complete (PRs #86, #87, #89, #90, #91); 10.7 remaining ([spec](10-parallel-region-lookup.md)) |
| Future | ⏳ Not Started | Additional providers, exporters, batch ops |

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
| Phase 9 | Content flags (sSex, abridged, lgbt), provider extraction, mutual exclusivity |

### Integration Tests

- [ ] Full pipeline: Provider → CanonicalMetadata → Exporter
- [ ] Fallback chain: Primary fails → Secondary succeeds
- [ ] Cache integration: Cached vs fresh data
- [ ] Error handling: All providers fail gracefully
