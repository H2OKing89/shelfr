# Implementation Checklist

> Part of [Metadata Architecture Documentation](README.md)

---

## Phase 0: Package Scaffolding (Do First!)

> **Critical:** Python won't allow both `metadata.py` and `metadata/` to coexist.

- [ ] Create `src/shelfr/metadata/` directory
- [ ] Move `metadata.py` → `metadata/__init__.py` (contents unchanged)
- [ ] Update any internal imports that referenced `metadata.py` as a module (no behavior change)
- [ ] Verify import still works: `python -c "import shelfr.metadata; print(shelfr.metadata.__file__)"`
- [ ] Run full test suite

**Why separate phase?** This is pure scaffolding — no behavior change, no refactoring, just enabling the package structure. Ship this first before any extraction.

> **Note:** After Phase 0, there is no `metadata.py` — the facade becomes `metadata/__init__.py`.
>
> **Reminder:** When creating new subpackages in later phases, add `__init__.py` files to each directory (unless intentionally using namespace packages).

---

## Phase 1: Extract MediaInfo (Leaf Module)

> MediaInfo is the cleanest extraction: no network, no state, pure functions.

- [ ] Create `metadata/models.py` with shared `Chapter` dataclass
  - **Note:** Distinct from root-level `shelfr.models` (which holds `AudiobookRelease`, `NormalizedBook`, etc.)
  - Import as `from shelfr.metadata.models import Chapter` to avoid ambiguity
  - Verify after creation: `python -c "from shelfr.metadata.models import Chapter; from shelfr.models import AudiobookRelease"`
- [ ] Create `metadata/mediainfo/__init__.py` + `extractor.py` with:
  - `AudioFormat` dataclass (MediaInfo-specific, stays here)
  - `detect_audio_format()`, `detect_audio_format_from_file()`
  - `run_mediainfo()`, `save_mediainfo_json()`
  - `_parse_chapters_from_mediainfo()`, `_extract_audio_info()`
- [ ] Update `metadata/__init__.py` to re-export from new location
- [ ] Run tests

**Test Migration:**
- Update imports: `from metadata.mediainfo import AudioFormat` → `from shelfr.metadata.mediainfo import AudioFormat`
- Update patch targets: `@patch("metadata.run_mediainfo")` → `@patch("shelfr.metadata.mediainfo.run_mediainfo")`
- Verify re-exports work: tests using `from shelfr.metadata import detect_audio_format` should still pass

---

## Phase 2: Extract Formatting (Presentation Layer)

- [ ] Create `metadata/formatting/bbcode.py`:
  - **Public:** `render_bbcode_description()`
  - **Private:** `_convert_newlines_for_mam()`, `_format_release_date()`, `_format_duration()`, `_format_chapter_time()`
  - Import `Chapter` from `metadata/models.py` (not mediainfo)
- [ ] Create `metadata/formatting/html.py`:
  - **Public:** `html_to_bbcode()` (no underscore — used externally)
  - **Private:** `_clean_html()`
- [ ] Update re-exports

**Test Migration:**
- Update imports: `from metadata import render_bbcode_description` → `from shelfr.metadata.formatting.bbcode import render_bbcode_description`
- Update mocks: Replace `metadata._format_duration` patches with `shelfr.metadata.formatting.bbcode._format_duration`
- Verify `Chapter` imports from `metadata.models` (not `mediainfo`)

---

## Phase 3: Extract Audnex Client (Network Boundary)

- [ ] Create `metadata/audnex/client.py` with:
  - `fetch_audnex_book()`, `fetch_audnex_author()`
  - `fetch_audnex_chapters()`, `_parse_chapters_from_audnex()`
  - `save_audnex_json()`
  - All `_fetch_audnex_*_region()` helpers
- [ ] Keep chapters with client (shared HTTP/retry/circuit-breaker patterns)
- [ ] Update re-exports

**Test Migration:**
- Update HTTP mocks: `@patch("metadata.httpx.get")` → `@patch("shelfr.metadata.audnex.client.httpx.get")`
- Update circuit breaker patches to new module path
- Test chapter parsing: `_parse_chapters_from_audnex` now in `metadata.audnex.client`

---

## Phase 4: Extract MAM (Depends on Above)

> Do this later — `build_mam_json` touches everything (mediainfo, audnex, formatting).

- [ ] Create `metadata/mam/categories.py`:
  - `FICTION_GENRE_KEYWORDS`, `NONFICTION_GENRE_KEYWORDS`
  - `_infer_fiction_or_nonfiction()`, `_get_audiobook_category()`, `_map_genres_to_categories()`
- [ ] Create `metadata/mam/json_builder.py`:
  - `build_mam_json()`, `save_mam_json()`, `generate_mam_json_for_release()`
  - `_build_series_list()`, `_get_mediainfo_string()`

**Test Migration:**
- Update category test imports: `from metadata.mam.categories import _infer_fiction_or_nonfiction`
- Update MAM JSON golden tests: adjust import paths to `shelfr.metadata.mam.json_builder`
- Verify integration: MAM builder depends on mediainfo/audnex/formatting extracted in Phases 1-3

---

## Phase 5: Schemas + Provider System + JSON Sidecar

> Split into sub-phases for smaller, reviewable PRs.

### Phase 5a: Schemas + Cleaning (no behavior change)

> **Guardrail:** Phase 5a introduces schemas + cleaning facade only; no pipeline conversion yet.

- [ ] Create `metadata/schemas/__init__.py` + `canonical.py`:
  - `Person`, `Series`, `Genre`, `CanonicalMetadata` (ALL in one file)
  - **Design rationale:** Keep schema definitions co-located for easier updates and unified versioning (Phase 7). Circular imports are prevented by having aggregator import from schemas (not vice versa).
  - **Do NOT split into person.py/series.py/genre.py yet** (avoid circular import risk)
- [ ] Create `metadata/cleaning.py` as **facade over existing functions**:
  - Re-export from `shelfr.utils.naming`: `filter_title`, `filter_subtitle`, etc.
  - **Don't duplicate** — wrap existing functions

### Phase 5b: Provider System (core architecture)

- [ ] Create `metadata/providers/__init__.py` + `types.py`:
  - `LookupContext`, `ProviderResult`, `FieldName`, `IdType`, `ProviderKind`
- [ ] Create `metadata/providers/base.py`:
  - `MetadataProvider` protocol
- [ ] Create `metadata/providers/registry.py`:
  - `ProviderRegistry` (instance-based, stable ordering)
- [ ] Create `metadata/providers/audnex.py`:
  - `AudnexProvider` (wraps client from Phase 3 in provider interface)
  - Ensure `kind = "network"` and `is_override = False` (required for two-stage fetch)
- [ ] Create `metadata/providers/mock.py`:
  - `MockProvider` for testing (needed to test aggregator)
- [ ] Create `metadata/aggregator.py`:
  - Basic `MetadataAggregator` with deterministic precedence
  - Two-stage fetch (local → network), `_safe_fetch()` error isolation
  - `_safe_fetch()` returns `ProviderResult(success=False, error=...)` on failure (never raises)

### Phase 5c: Orchestration + Exporters

- [ ] Create `metadata/orchestration.py`:
  - Keep as **thin facade initially** (wire-through only, no new logic)
  - `fetch_metadata()`, `fetch_all_metadata()`, `save_metadata_files()`
- [ ] Create `metadata/exporters/__init__.py` + `base.py`:
  - `MetadataExporter` protocol
- [ ] Create `metadata/exporters/json.py`:
  - `JsonExporter` for ABS metadata.json sidecar
  - Sidecar writing is an exporter responsibility (not separate generator)

---

## Phase 6: Move OPF + Deprecations

- [ ] Move `src/shelfr/opf/` → `metadata/opf/`
- [ ] Create deprecation shim in `src/shelfr/opf/__init__.py`:
  - Old import path raises `DeprecationWarning` unless `SHELFR_ENABLE_LEGACY_OPF=1`
  - In legacy mode, old import path re-exports new functions
- [ ] Create `metadata/exporters/opf.py`:
  - `OpfExporter` wrapping existing OPF generation

---

## Phase 7: Infrastructure (As Needed)

> These are optional enhancements — the core system works without them.

- [ ] Implement `MetadataCache` with `FileCache` default
- [ ] Implement `MetadataEvents` hook system
- [ ] Add schema versioning to `CanonicalMetadata`
- [ ] Per-provider rate limiting (`ProviderResilience` class)
- [ ] Circuit breaker integration (already have infrastructure)

> **Note:** If JSON sidecar needs multi-source deterministic merges (e.g., ABS override + Audnex) before Phase 5b is ready, pull Aggregator forward as needed.

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
|-------|--------|-------|
| Phase 0 | ⏳ Not Started | Package scaffolding |
| Phase 1 | ⏳ Not Started | MediaInfo (leaf module) |
| Phase 2 | ⏳ Not Started | Formatting (presentation) |
| Phase 3 | ⏳ Not Started | Audnex client |
| Phase 4 | ⏳ Not Started | MAM (depends on above) |
| Phase 5a | ⏳ Not Started | Schemas + Cleaning |
| Phase 5b | ⏳ Not Started | Provider system + Aggregator |
| Phase 5c | ⏳ Not Started | Orchestration + JSON exporter |
| Phase 6 | ⏳ Not Started | OPF move + deprecations |
| Phase 7 | ⏳ Not Started | Infrastructure (optional) |
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
Phase 7 (Infrastructure - optional)
```

**Critical Path for JSON sidecar:** Phase 0 → Phase 5a (schemas) → Phase 5c (JSON exporter)

> *Assumes existing metadata fetch logic still lives in `metadata/__init__.py` until Phase 3 extraction.*

**Alternative path:** Phase 5a (schemas) doesn't actually depend on Phase 1 extraction — you can do Phase 0 → Phase 5a → Phase 5c if you want JSON sidecar before extracting MediaInfo.

---

## Testing Strategy

### Per-Phase Testing

| Phase | Test Focus |
|-------|------------|
| Phase 0 | Import smoke test, full test suite passes |
| Phase 1 | MediaInfo parsing, AudioFormat detection |
| Phase 2 | BBCode output, HTML conversion |
| Phase 3 | Mock HTTP responses, circuit breaker |
| Phase 4 | Category mapping, MAM JSON golden tests |
| Phase 5a | Schema validation, cleaning idempotence |
| Phase 5b | MockProvider, aggregator merge logic, registry, deterministic tie-breaking (same confidence → priority wins), override provider behavior (empty values), two-stage fetch short-circuit |
| Phase 5c | Orchestration wire-through, JSON exporter golden tests |
| Phase 6 | OPF output, JSON sidecar golden tests |
| Phase 7 | Cache hit/miss, event emission |

### Integration Tests

- [ ] Full pipeline: Provider → CanonicalMetadata → Exporter
- [ ] Fallback chain: Primary fails → Secondary succeeds
- [ ] Cache integration: Cached vs fresh data
- [ ] Error handling: All providers fail gracefully
