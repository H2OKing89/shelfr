# Recommendations & Migration Plan

> Part of [Metadata Architecture Documentation](README.md)
>
> **Migration Status:** Phases 0-7 complete ✅ | Phase 8+ planned 📋

---

## Migration Progress Summary

| Phase | Status | Completion |
| ------- | -------- | ------------ |
| Phase 0: Package Scaffolding | ✅ Complete | Merged to main |
| Phase 1: Extract MediaInfo | ✅ Complete | Merged to main |
| Phase 2: Extract Formatting | ✅ Complete | Merged to main |
| Phase 3: Extract Audnex | ✅ Complete | Merged to main |
| Phase 4: Extract MAM | ✅ Complete | Merged to main |
| Phase 5: Schemas + Providers + Exporters | ✅ Complete | Merged to main |
| Phase 6: Move OPF + Deprecations | ✅ Complete | Merged to main |
| Phase 7: Cleanup & Hygiene | ✅ Complete | Schema consolidation (PR #78), docs/hygiene (PR #79) |
| Phase 8: Infrastructure (future) | 📋 Planned | Cache, events, batch operations |

---

## 1. Phase 0: Package Scaffolding ✅ COMPLETE

> **Python constraint:** You cannot have both `metadata.py` and `metadata/` directory.

**Action:** Convert module to package without changing behavior

```bash
# Before
src/shelfr/metadata.py

# After
src/shelfr/metadata/__init__.py  # Same content, now a package
```

**Steps:**

1. Create `src/shelfr/metadata/` directory
2. Move contents of `metadata.py` → `metadata/__init__.py`
3. Verify `import shelfr.metadata` still works
4. Run full test suite

**Why separate step?** This is pure scaffolding. Ship it alone before any extraction.

> **Note:** After Phase 0, there is no `metadata.py` — the facade becomes `metadata/__init__.py`.

---

## 2. Phase 1: Extract MediaInfo ✅ COMPLETE

> Extract first because it's a **leaf module** — no network, no state, pure functions.

**Action:** Create `metadata/mediainfo/extractor.py`

Move from `metadata/__init__.py`:

- `AudioFormat` dataclass
- `detect_audio_format()`, `detect_audio_format_from_file()`
- `run_mediainfo()`, `save_mediainfo_json()`
- `_parse_chapters_from_mediainfo()`, `_extract_audio_info()`
- `_format_duration()`, `_format_chapter_time()`

Update `metadata/__init__.py` to re-export from new location.

---

## 3. Phase 2: Extract Formatting ✅ COMPLETE

**Action:** Create `metadata/formatting/`

```bash
metadata/formatting/
├── __init__.py
├── bbcode.py       # render_bbcode_description, _convert_newlines_for_mam
└── html.py         # _html_to_bbcode, _clean_html
```

Also move `_format_release_date()` here (only consumer is bbcode).

---

## 4. Phase 3: Extract Audnex ✅ COMPLETE

**Action:** Create `metadata/audnex/client.py`

Move:

- `fetch_audnex_book()`, `fetch_audnex_author()`
- `fetch_audnex_chapters()`, `_parse_chapters_from_audnex()`
- `save_audnex_json()`
- All `_fetch_audnex_*_region()` helpers

Keep chapters with client (shared HTTP/retry/circuit-breaker patterns).

---

## 5. Phase 4: Extract MAM ✅ COMPLETE

> ~~**Do this later**~~ — Done! `build_mam_json` now lives in organized structure.

**Action:** Create `metadata/mam/`

```bash
metadata/mam/
├── __init__.py
├── categories.py   # FICTION/NONFICTION keywords, _infer_*, _get_audiobook_category
└── json_builder.py # build_mam_json, save_mam_json, generate_mam_json_for_release
```

---

## 6. Phase 5: Schemas + Provider System + Exporters ✅ COMPLETE

### 6.1 Shared Types

**Action:** Create `metadata/models.py` for small shared types

```python
# metadata/models.py
@dataclass
class Chapter:
    title: str
    start_time: float
    end_time: float | None = None
```

> **Why?** `Chapter` is used by both `mediainfo/` and `formatting/bbcode.py`. Putting it in a shared location avoids circular imports (formatting → mediainfo → formatting nightmare).

Keep `AudioFormat` in `mediainfo/` — that's MediaInfo-specific.

### 6.2 Canonical Schemas

**Action:** Create `metadata/schemas/canonical.py`

```bash
metadata/schemas/
├── __init__.py
├── canonical.py    # Person, Series, Genre, CanonicalMetadata (ALL in one file)
├── abs_json.py     # ABSJsonMetadata (for output)
└── opf.py          # OPFMetadata, OPFCreator, etc.
```

### 6.3 Cleaning Layer

**Action:** Create `metadata/cleaning.py` as **facade over existing functions**

```python
# metadata/cleaning.py (v1 - facade, not duplicate)
from shelfr.utils.naming import (
    filter_title,
    filter_subtitle,
    filter_series,
    filter_authors,
    transliterate_text,
    normalize_audnex_book,
    resolve_series,
)

# Re-export for metadata module consumers
__all__ = [
    "filter_title",
    "filter_subtitle",
    "filter_series",
    "filter_authors",
    "transliterate_text",
    "normalize_audnex_book",
    "resolve_series",
]

# Later: migrate logic here if desired, but start as a wrapper
```

> **Why facade?** Cleaning functions already exist in `shelfr.utils.naming`. Don't create "two competing cleaners" during migration.

### 6.4 JSON Sidecar

**Action:** Create `metadata/json/generator.py` (new feature)

---

## 7. Phase 6: Move OPF + Deprecations ✅ COMPLETE

**Action:** Move `src/shelfr/opf/` → `metadata/opf/` with deprecation shim

```python
# src/shelfr/opf/__init__.py (old location, becomes shim)
import os, warnings

if os.getenv("SHELFR_WARN_LEGACY_IMPORTS") == "1":
    warnings.warn(
        "shelfr.opf is deprecated. Use shelfr.metadata.opf instead.",
        DeprecationWarning, stacklevel=2
    )
from shelfr.metadata.opf import *
```

**Alternative (best-in-class):** Use `__getattr__` for lazy deprecation warnings only when deprecated names are accessed — zero test noise, zero runtime spam until actual usage.

---

## 8. Final Target Structure

```bash
metadata/
├── __init__.py         # Public API (facade re-exports)
├── models.py           # Chapter (shared small types); avoids collision with providers/types.py
├── cleaning.py         # Facade over utils/naming
├── orchestration.py    # fetch_all_metadata, etc. (was pipeline.py)
├── schemas/
│   ├── canonical.py    # Person, Series, Genre, CanonicalMetadata
│   ├── abs_json.py     # ABS output schema
│   └── opf.py          # OPF output schema
├── audnex/
│   └── client.py       # API client + chapters
├── mediainfo/
│   └── extractor.py    # AudioFormat, run_mediainfo
├── formatting/
│   ├── bbcode.py       # render_bbcode_description
│   └── html.py         # HTML converters
├── mam/
│   ├── categories.py   # Category mapping
│   └── json_builder.py # build_mam_json
├── opf/                # Moved from src/shelfr/opf/
└── json/               # NEW JSON sidecar
```

> **Note:** Renamed `pipeline.py` → `orchestration.py` to avoid confusion with "Pipeline Models" language in the audit doc.

---

## 9. Migration Risk Assessment

| Risk | Mitigation |
| --- | --- |
| Breaking existing imports | Keep `metadata/__init__.py` as facade re-export layer |
| Test breakage | Run full test suite after each phase |
| Hidden dependencies | Use `grep` to find all usages before moving |
| Circular imports | Extract leaf modules first; use `types.py` for shared types |
| Two competing cleaners | Start `cleaning.py` as facade over `utils/naming` |
| Windows strftime bug | Fixed: use `f"{dt:%B} {dt.day}, {dt:%Y}"` instead of `%-d` |

---

## 10. Recommended Shipping Order

| PR | Phase | Status | Completion |
| --- | --- | --- | --- |
| 1 | Phase 0 | ✅ Complete | Package scaffolding shipped |
| 2 | Phase 1 | ✅ Complete | MediaInfo extraction shipped |
| 3 | Phase 2 | ✅ Complete | Formatting extraction shipped |
| 4 | Phase 3 | ✅ Complete | Audnex extraction shipped |
| 5 | Phase 4 | ✅ Complete | MAM extraction shipped |
| 6 | Phase 5 | ✅ Complete | Schemas + Providers + Exporters shipped |
| 7 | Phase 6 | ✅ Complete | OPF move + deprecations shipped |
| 8 | Phase 7 | ✅ Complete | Cleanup & hygiene shipped |
| 9 | Phase 8+ | 📋 Planned | Infrastructure (cache, events, batch operations) |

### Current Status: Phase 7 Complete ✅

**All Phase 7 tasks completed:**

- ✅ Schema consolidation (AbsMetadataSchema unified with AbsMetadataJson in PR #78)
- ✅ Strict validation enforcement on write paths
- ✅ Tags field population with Adult flag
- ✅ Documentation updates (file inventory, recommendations)
- ✅ Code hygiene checks (ruff, unused imports)
- ✅ `__all__` exports verification
- ✅ Deprecation timeline documented

### Future Work: Phase 8+ (Infrastructure)

1. 📋 Caching layer with schema versioning
2. 📋 Event hooks / middleware for instrumentation
3. 📋 Batch operations support
4. 📋 Rate limiting + circuit breaker improvements
5. 📋 Provider performance optimization
