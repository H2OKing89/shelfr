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

> Post-migration cleanup — consolidate duplicates, update docs, remove dead code.

### Schema Consolidation

- [ ] Unify `AbsMetadataSchema` (`abs/rename.py`) with `AbsMetadataJson` (`schemas/abs_metadata.py`):
  - Audit differences (optional fields, naming conventions)
  - Migrate `abs/rename.py` to use `AbsMetadataJson`
  - Update tests in `test_abs_rename.py`
  - Remove duplicate `AbsMetadataSchema` class
- [ ] Unify `AudnexAuthor` / `AudnexSeries` with `Person` / `Series` from canonical schemas:
  - Update `schemas/audnex.py` to import from `metadata/schemas/canonical.py`
  - Verify Audnex validation still works with shared types

### Documentation Updates

- [ ] Update `01-current-state-audit.md` to reflect completed migration:
  - Mark duplicate schemas as resolved
  - Update file inventory with new structure
  - Add "Migration Complete" status
- [ ] Update `02-recommendations.md`:
  - Mark completed phases
  - Archive or annotate historical context
- [ ] Review and update `README.md` in architecture folder

### Code Hygiene

- [ ] Remove any unused imports in migrated files
- [ ] Run `ruff check --fix` across metadata package
- [ ] Verify all `__all__` exports are accurate
- [ ] Check for any TODO/FIXME comments to address

### Deprecation Tracking

- [ ] Document deprecation timeline for `shelfr.opf` shim (target: v2.0)
- [ ] Document deprecation timeline for `cli_argparse.py` (target: v2.0)
- [ ] Add deprecation notes to CHANGELOG

---

## Phase 8: Infrastructure (As Needed)

> These are optional enhancements — the core system works without them.

- [ ] Implement `MetadataCache` with `FileCache` default
- [ ] Implement `MetadataEvents` hook system
- [ ] Add schema versioning to `CanonicalMetadata`
- [ ] Per-provider rate limiting (`ProviderResilience` class)
- [ ] Circuit breaker integration (already have infrastructure)

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
| Phase 7 | ⏳ Not Started | Cleanup & Hygiene |
| Phase 8 | ⏳ Not Started | Infrastructure (optional) |
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
