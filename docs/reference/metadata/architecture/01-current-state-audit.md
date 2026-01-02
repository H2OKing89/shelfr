# Current State Audit

> Part of [Metadata Architecture Documentation](README.md)

---

## 1. Current File Inventory

### 1.1 Core Metadata Files

| File | Lines | Purpose | Issues |
| --- | --- | --- | --- |
| `metadata.py` | **2040** | Audnex API, MediaInfo, BBCode, MAM JSON | God module, does too much |
| `models.py` | 316 | Core dataclasses (`AudiobookRelease`, `NormalizedBook`) | OK, but mixed concerns |
| `discovery.py` | ~200 | Libation folder parsing, `LibationMetadata` | OK |

### 1.2 OPF Module (New, Well-Structured)

| File | Lines | Purpose |
| --- | --- | --- |
| `opf/__init__.py` | 102 | Public API exports |
| `opf/schemas.py` | 328 | `CanonicalMetadata`, `OPFMetadata`, `Person`, `Series` |
| `opf/generator.py` | 373 | XML generation |
| `opf/helpers.py` | 150 | Name cleaning, role detection |
| `opf/mappings.py` | 281 | Language ISO codes, MARC relators |

**Total OPF:** ~1,234 lines (well-organized, modular)

### 1.3 Schema Definitions (schemas/ directory)

| File | Lines | Purpose | Overlaps With |
| --- | --- | --- | --- |
| `schemas/audnex.py` | ~150 | Audnex API validation | - |
| `schemas/abs_metadata.py` | ~130 | ABS metadata.json validation | ✅ Single source |
| `schemas/abs.py` | 357 | ABS API schemas | - |
| `schemas/naming.py` | 269 | Naming config schemas | `config.py` |

### 1.4 ABS Module (abs/ directory)

| File | Key Classes/Functions | Metadata Role |
| --- | --- | --- |
| `abs/rename.py` | `parse_abs_metadata()`, `AbsMetadata` dataclass | ✅ Uses `AbsMetadataJson` from schemas |
| `abs/asin.py` | ASIN extraction/resolution | Uses metadata.json |
| `abs/importer.py` | Import logic, calls `write_opf()` | Coordinates metadata |

---

## 2. Duplicate Definitions Found

> **Status (Phase 7 Complete):** Most duplicates have been resolved. See notes below.

### 2.1 ABS JSON vs Canonical Schema (Two Layers, Currently Mixed)

There are two distinct concerns being conflated:

| Layer | Purpose | Should Be |
| --- | --- | --- |
| **ABS Output Schema** | What we write to `metadata.json` for ABS import | `AbsMetadataJson` |
| **Canonical Schema** | Internal truth we export FROM (richer than ABS) | `CanonicalMetadata` |

**Important:** `CanonicalMetadata` is NOT an ABS schema. It should be richer than ABS JSON and exporter-driven. `CanonicalMetadata` should not be forced to match ABS JSON; exporters map canonical → ABS.

**✅ RESOLVED (Phase 7):**

**ABS Output Schema: `schemas/abs_metadata.py` → `AbsMetadataJson`**

```python
class AbsMetadataJson(BaseModel):
    title: str | None = None  # Optional for reading existing metadata
    subtitle: str | None = None
    authors: list[str] = Field(default_factory=list)
    published_year: str | int | None = Field(default=None, validation_alias="publishedYear")
    chapters: list[AbsChapter] = Field(default_factory=list)

# For writing, use validate_abs_metadata_for_write() to ensure title is present
```

**~~ABS Compat Schema (DUPLICATE, should die): `abs/rename.py` → `AbsMetadataSchema`~~**

✅ **REMOVED in Phase 7.** Now uses `AbsMetadataJson` from `schemas/abs_metadata.py`.

**Canonical Schema: `metadata/schemas/canonical.py` → `CanonicalMetadata`**

```python
class CanonicalMetadata(BaseModel):
    asin: str  # Required
    title: str  # Required
    authors: list[Person] = Field(default_factory=list)  # Person objects!
    # ... uses Audnex naming (series_primary, release_date)
```

### 2.2 Person/Author Schema (2 versions)

> **Status:** Cannot be unified due to circular import constraints. See note below.

**Version 1: `metadata/schemas/canonical.py` → `Person`** (canonical, single source of truth)

```python
class Person(BaseModel):
    name: str
    asin: str | None = None
```

**Version 2: `schemas/audnex.py` → `AudnexAuthor`** (API parsing layer)

```python
class AudnexAuthor(BaseModel):
    name: str
    asin: str | None = None
```

**Structurally identical** but kept separate due to circular import:
`schemas/audnex.py` → `metadata/schemas/canonical.py` → `metadata/__init__.py` → providers → `schemas/audnex.py`

`AudnexAuthor` is documented as equivalent to `Person`. Use canonical `Person` for internal processing.

### 2.3 Series Schema (2 versions)

> **Status:** Same circular import constraint as Person/Author.

**Version 1: `metadata/schemas/canonical.py` → `Series`** (canonical)

```python
class Series(BaseModel):
    name: str
    position: str | None = None
    asin: str | None = None
```

**Version 2: `schemas/audnex.py` → `AudnexSeries`** (API parsing layer)

```python
class AudnexSeries(BaseModel):
    name: str
    position: str | None = None
    asin: str | None = None
```

**Structurally identical** but kept separate due to circular import (same as Person/Author).

### 2.4 Single Source of Truth (Target State)

> **Status (Phase 7):** ✅ Canonical types now live in `metadata/schemas/canonical.py`.

All shared types now live in ONE place:

| Path | Contents |
| --- | --- |
| `metadata/schemas/canonical.py` | Types: `Person`, `Series`, `Genre`, `CanonicalMetadata` |
| `metadata/opf/schemas.py` | Re-exports canonical + OPF-specific: `OPFCreator`, `OPFMetadata`, etc. |

Audnex schemas (`AudnexAuthor`, `AudnexSeries`, `AudnexGenre`) remain separate due to circular imports but are documented as structurally identical to canonical types.

### 2.5 Model Layers (Why Both Pydantic and Dataclasses Exist)

| Layer | Type | Purpose | Examples |
| --- | --- | --- | --- |
| **Validation Schemas** | Pydantic | Raw API response validation | `AudnexBook`, `AbsMetadataJson` |
| **Canonical Schema** | Pydantic | Normalized truth (provider-merged) | `CanonicalMetadata`, `Person`, `Series` |
| **Pipeline Models** | dataclass | Workflow state, file paths, computed values | `AudiobookRelease`, `NormalizedBook` |

**Rule:** Don't add 18 fields to `NormalizedBook` because it's convenient. Keep layers separate:

- Validation = external API shapes
- Canonical = internal truth
- Pipeline = operational state

### 2.6 NormalizedBook vs CanonicalMetadata (Boundary)

These two models solve the same problem (Audible's inconsistent metadata) but for different purposes:

| Model | Purpose | Fields | Used By |
| --- | --- | --- | --- |
| `NormalizedBook` | Workflow artifact | Paths, computed filenames, local state | Naming pipeline (MAM paths) |
| `CanonicalMetadata` | Metadata truth | All metadata fields | OPF/JSON exporters |

**Recommended relationship (Option A):**

```python
@dataclass
class NormalizedBook:
    # Workflow state
    source_path: Path
    computed_folder_name: str
    computed_file_name: str

    # Reference to canonical metadata
    canonical: CanonicalMetadata  # Link to truth
```

**Why not collapse them?** Making `CanonicalMetadata` carry operational fields (paths, etc.) turns your domain model into "god object v2."

---

## 3. The `metadata.py` God Module

At **2,040 lines**, this file handles far too many responsibilities:

### 3.1 Responsibilities (should be separate)

| Section | Lines | Should Be |
| --- | --- | --- |
| `AudioFormat` detection | 60-280 | `metadata/audio_format.py` |
| Jinja BBCode templates | 290-350 | `metadata/bbcode/` |
| `render_bbcode_description()` | 500-650 | `metadata/bbcode/generator.py` |
| `fetch_audnex_*()` functions | 700-1000 | `metadata/audnex/client.py` |
| `run_mediainfo()` | 1080-1160 | `metadata/mediainfo.py` |
| `build_mam_json()` | 1640-1970 | `metadata/mam/json_builder.py` |
| HTML/BBCode converters | 1530-1640 | `metadata/formatting.py` |
| Category mapping | 1320-1480 | `metadata/mam/categories.py` |

### 3.2 Public API (41 functions!)

```python
# metadata.py exports (too many!)
Chapter, AudioFormat, detect_audio_format, detect_audio_format_from_file,
render_bbcode_description, fetch_audnex_book, fetch_audnex_author,
fetch_audnex_chapters, save_audnex_json, run_mediainfo, save_mediainfo_json,
fetch_metadata, save_metadata_files, fetch_all_metadata, build_mam_json,
save_mam_json, generate_mam_json_for_release, ...
```

### 3.3 Migration Strategy: Facade Pattern

**Don't break everything at once.** Keep `metadata.py` as a re-export facade during migration:

```python
# metadata.py (legacy facade - keeps old imports working)
from .metadata.mediainfo import run_mediainfo  # re-export
from .metadata.audnex.client import fetch_audnex_book  # re-export
from .metadata.bbcode.generator import render_bbcode_description  # re-export

# Gate warnings to avoid test noise and warning fatigue
import os, warnings

if os.getenv("SHELFR_WARN_LEGACY_IMPORTS") == "1":
    warnings.warn(
        "Importing from shelfr.metadata is deprecated. "
        "Use shelfr.metadata.audnex, shelfr.metadata.mediainfo, etc.",
        DeprecationWarning, stacklevel=2
    )
```

**This lets you:**

- Move code out of `metadata.py` incrementally
- Keep `workflow.py`, `abs/importer.py`, and tests working
- Add deprecation warnings in phases, not one big bang
- Avoid breaking test suites that treat warnings as errors

---

## 4. Data Flow Analysis

### 4.1 Current Flow (Fragmented)

```text
Audnex API
    │
    ├──→ metadata.py::fetch_audnex_book()
    │        │
    │        ├──→ NormalizedBook (models.py)
    │        └──→ build_mam_json() → MAM upload
    │
    └──→ opf/schemas.py::CanonicalMetadata.from_audnex()
             │
             └──→ OPFMetadata → generate_opf()

ABS metadata.json
    │
    ├──→ schemas/abs_metadata.py::AbsMetadataJson (validation)
    └──→ abs/rename.py::AbsMetadataSchema (different schema!)
```

### 4.2 Pipeline Contract (North Star)

> **Providers return partial canonical fragments → Aggregator merges deterministically → Cleaner normalizes once → Exporters render outputs.**

This sentence is the north star for all refactor PRs. Every component does exactly one thing.

### 4.3 Proposed Flow (Unified)

```text
Audnex API Response
    │
    ▼
┌─────────────────────────────────────┐
│   metadata/pipeline.py              │
│   → CanonicalMetadata (from schemas)│ ← Single source of truth
└─────────────────────────────────────┘
    │
    ├──→ metadata/cleaning.py (shared cleaners)
    │
    ├──→ metadata/opf/generator.py → metadata.opf
    ├──→ metadata/json/generator.py → metadata.json (NEW)
    └──→ metadata/mam/json_builder.py → MAM upload JSON
```

### 4.4 Aggregator Precedence Rules

When multiple providers have data, use deterministic precedence (prevents "whoever was called last wins"):

| Field Category | Priority Order | Rationale |
| --- | --- | --- |
| **Identifiers** (ASIN, ISBN) | Audnex > ABS local > Libation | Audnex is authoritative |
| **Title/Subtitle/Series** | Audnex > ABS local (if trusted) | Audnex normalizes Audible's mess |
| **Authors** | Audnex > ABS local > Libation | Audnex has author ASINs |
| **Runtime/Chapters** | MediaInfo > Audnex | MediaInfo is ground truth |
| **Cover** | Local folder > Audnex | Local may have higher-res |
| **Genres/Tags** | Merge all sources | More is better, dedupe later |

**"Trusted ABS local"** = explicitly enabled via config (`metadata.providers.abs_local.trust: true`) OR only trusted for user-edited fields (title corrections, manual series assignments). Without explicit trust, ABS local is treated as lower priority than Audnex.

---

## 5. Import Analysis

### 5.1 Who imports `metadata.py`?

- `tests/test_metadata.py` - heavy usage
- `tests/test_bbcode_signature.py` - `_convert_newlines_for_mam`
- `tests/test_series_resolution.py` - `build_mam_json`
- `workflow.py` - main pipeline
- `abs/importer.py` - enrichment

### 5.2 Who imports `opf/`?

- `abs/importer.py` - `CanonicalMetadata`, `write_opf`
- `tests/test_opf.py` - comprehensive tests

**OPF is cleanly isolated** - good foundation for unified module.

---

## 6. Current Schema Locations

> **Status (Phase 7 Complete):** Schema consolidation is done. `CanonicalMetadata` lives in `metadata/schemas/canonical.py`. OPF schemas re-export from canonical.

| Schema | Location | Notes |
| --- | --- | --- |
| `CanonicalMetadata` | `metadata/schemas/canonical.py` | ✅ Canonical (single source of truth) |
| `Person` | `metadata/schemas/canonical.py` | ✅ Canonical |
| `Series` | `metadata/schemas/canonical.py` | ✅ Canonical |
| `Genre` | `metadata/schemas/canonical.py` | ✅ Canonical |
| `OPFMetadata` | `opf/schemas.py` | ✅ OPF-specific export |
| `OPFCreator` | `opf/schemas.py` | ✅ OPF-specific |
| `AudnexBook` | `schemas/audnex.py` | ✅ Validation only |
| `AudnexAuthor` | `schemas/audnex.py` | ⚠️ Identical to `Person` (circular import) |
| `AudnexSeries` | `schemas/audnex.py` | ⚠️ Identical to `Series` (circular import) |
| `AudnexGenre` | `schemas/audnex.py` | ⚠️ Identical to `Genre` (circular import) |
| `AbsMetadataJson` | `schemas/abs_metadata.py` | ✅ ABS output schema (single source) |
| ~~`AbsMetadataSchema`~~ | ~~`abs/rename.py`~~ | ❌ Removed in Phase 7 |
| `AbsMetadata` | `abs/rename.py` | ✅ Dataclass for rename workflow |
| `NormalizedBook` | `models.py` | ✅ Pipeline model |
| `AudiobookRelease` | `models.py` | ✅ Pipeline model |
