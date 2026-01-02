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

> **Status (Phase 7):** ✅ **AbsMetadataSchema unified.** AudnexAuthor/AudnexSeries remain as documented duplicates (circular import constraint).

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

# Read paths: title optional (permissive, handles incomplete real-world files)
# Write paths: title REQUIRED (enforced by validate_abs_metadata_for_write())
```

**Write path enforcement:**

- **`write_abs_metadata_json()`** is the single canonical write gate
- **`strict=True` (default):** calls `validate_abs_metadata_for_write()`, raises `ValueError` if title is missing/empty/whitespace
- **`strict=False`:** escape hatch for debug dumps or partial scrape workflows
- **`JsonExporter.export()`** uses `write_abs_metadata_json(strict=True)` by default

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

> **Status:** Cannot be unified *today* due to circular import constraints. This is a near-term refactor limitation (initialization order + eager imports), not a fundamental design requirement.

We currently have two structurally-identical models:

#### Canonical types (internal truth)

**`metadata/schemas/canonical.py` → `Person`, `Series`**

```python
class Person(BaseModel):
    name: str
    asin: str | None = None
```

```python
class Series(BaseModel):
    name: str
    position: str | None = None
    asin: str | None = None
```

#### Audnex validation types (API parsing boundary)

**`schemas/audnex.py` → `AudnexAuthor`, `AudnexSeries`**

```python
class AudnexAuthor(BaseModel):
    name: str
    asin: str | None = None
```

```python
class AudnexSeries(BaseModel):
    name: str
    position: str | None = None
    asin: str | None = None
```

These are duplicated *only* because importing the canonical types inside `schemas/audnex.py` triggers a circular import at runtime.

---

#### Why the duplication exists (in plain English)

- `schemas/audnex.py` is a validation layer (Pydantic schema definitions for raw Audnex API responses).
- Canonical types live under `shelfr.metadata.schemas.canonical`.
- Importing canonical types from within `schemas/audnex.py` sounds harmless… until Python realizes importing `shelfr.metadata.schemas.canonical` implicitly executes `shelfr.metadata.__init__`, which eagerly imports the aggregator/providers, which import the Audnex client, which imports `schemas.audnex` again.

At that point Python is holding two open doors in a hallway and tries to walk through both at once. The universe collapses into a singularity. (A.k.a. "partially initialized module" error.)

---

#### Import Cycle Diagram (edges that form the loop)

This is the cycle that occurs if `schemas/audnex.py` tries to import canonical `Person/Series`:

```text
┌───────────────────────────────┐
│ shelfr/schemas/audnex.py       │
│  (AudnexBook validation)       │
└───────────────┬───────────────┘
                │ 1) wants canonical Person/Series
                ▼
┌───────────────────────────────┐
│ shelfr/metadata/schemas/       │
│   canonical.py                 │
└───────────────┬───────────────┘
                │ 2) importing canonical touches package init
                ▼
┌───────────────────────────────┐
│ shelfr/metadata/__init__.py    │
│  (exports / facade)            │
└───────────────┬───────────────┘
                │ 3) eager import of aggregator/providers
                ▼
┌───────────────────────────────┐
│ shelfr/metadata/aggregator.py  │
└───────────────┬───────────────┘
                │ 4) loads providers
                ▼
┌───────────────────────────────┐
│ shelfr/metadata/providers/     │
│   audnex.py                    │
└───────────────┬───────────────┘
                │ 5) imports audnex client
                ▼
┌───────────────────────────────┐
│ shelfr/metadata/audnex/        │
│   client.py                    │
└───────────────┬───────────────┘
                │ 6) imports audnex validators
                ▼
┌───────────────────────────────┐
│ shelfr/schemas/audnex.py       │
│  (still initializing!)         │
└───────────────┴───────────────┘
             ▲
             └─────────────── CYCLE ────────────────
```

Key point: **the cycle is not "audnex ↔ canonical" directly** — it's **audnex → canonical → metadata package init → providers/client → audnex**. The "innocent" import of `Person` triggers the whole subsystem.

---

#### Concrete 9-step import path (exact chain)

This is a realistic trace of how the loop happens during runtime import:

1. `abs/rename.py` imports `AudnexBook` (or an Audnex schema) from `shelfr.schemas.audnex`
2. Python starts importing `shelfr/schemas/audnex.py`
3. `schemas/audnex.py` attempts `from shelfr.metadata.schemas.canonical import Person` (desired unification)
4. Python begins importing `shelfr.metadata` to resolve `shelfr.metadata.schemas.canonical`
5. Importing `shelfr.metadata` executes `shelfr/metadata/__init__.py`
6. `metadata/__init__.py` imports the `MetadataAggregator` (or other exports) from `metadata/aggregator.py`
7. `metadata/aggregator.py` imports provider modules (including the Audnex provider)
8. The Audnex provider imports `metadata/audnex/client.py`
9. `metadata/audnex/client.py` imports `shelfr.schemas.audnex` to validate responses → **but `schemas/audnex.py` is still initializing at step 2** → **circular import / partially initialized module**

This is why `schemas/audnex.py` cannot safely import canonical types right now.

---

#### Important clarification: not fundamental, just a near-term limitation

This duplication is **not** a conceptual necessity. It's a practical side-effect of:

- eager imports in `metadata/__init__.py` (package initialization pulls in aggregator/providers)
- "from canonical import …" being evaluated at import-time in a schema module
- the Audnex client importing validators from the schema module

With a refactor of import structure (or lazy import boundaries), this can be removed cleanly.

---

#### Current workaround (and why it's acceptable)

**Workaround:** Keep lightweight Audnex boundary models inside `schemas/audnex.py`:

- `AudnexAuthor`, `AudnexSeries`, `AudnexGenre` remain "API shapes"
- Canonical `Person/Series/Genre` remain "internal truth"
- Mapping happens after validation (provider boundary), not inside schema definitions

**Why this is reasonable today:**

- The duplication is tiny (a few small models)
- It isolates API parsing from internal domain models (a good boundary anyway)
- It avoids import-order landmines while the module layout is still in flux

---

#### Recommendation for new code

**Use canonical `Person` / `Series` everywhere beyond the raw Audnex parsing boundary.**

- ✅ Validation layer: `schemas/audnex.py` types (`AudnexAuthor`, `AudnexSeries`)
- ✅ Provider layer: converts to canonical (`Person`, `Series`)
- ✅ Everything else (exporters, cleaning, pipeline, aggregators): canonical only

A simple conversion helper keeps the boundary explicit:

```python
def audnex_author_to_person(a: AudnexAuthor) -> Person:
    return Person(name=a.name, asin=a.asin)

def audnex_series_to_series(s: AudnexSeries) -> Series:
    return Series(name=s.name, position=s.position, asin=s.asin)
```

This makes it impossible for the "API models" to leak into the rest of the codebase.

---

#### Possible future resolutions (ways to remove duplication)

Any of these could unify the types later. The right choice depends on how much refactor we're willing to do.

##### Option A) `TYPE_CHECKING` + forward references (low effort, partial win)

Use canonical types only for typing without importing at runtime.

```python
from typing import TYPE_CHECKING
if TYPE_CHECKING:
    from shelfr.metadata.schemas.canonical import Person
```

Then schemas reference `"Person"` as a string, or use `Annotated` + Pydantic forward refs.

**Pros:**

- Minimal disruption
- Lets internal code type against canonical types without runtime import

**Cons:**

- Doesn't fully unify runtime models unless you redesign the schema layer
- Pydantic forward refs can be finicky if not resolved in the right module order

##### Option B) Lazy imports (move imports inside functions) (medium effort, reliable)

Stop importing heavy subsystems at module import time; import them only when needed.

Example: `metadata/__init__.py` should not import aggregator/providers eagerly. It can expose functions that import on demand.

**Pros:**

- Breaks cycle at the root (eager `__init__` behavior)
- Improves startup time and reduces side effects

**Cons:**

- Requires discipline and consistent patterns across the package
- Needs careful test coverage to avoid surprising import-time behavior changes

##### Option C) Split "schemas/types" into a dependency-free module (cleanest long-term)

Create a small `shelfr.metadata.types` (or `shelfr.domain.types`) module that contains only `Person/Series/Genre`, with **zero imports** from providers/clients.

Then:

- `schemas/audnex.py` can import from `types` safely
- canonical metadata can import from `types` safely
- providers/clients never imported from `types`

**Pros:**

- Canonical win: types become foundational and safe everywhere
- Very common pattern in larger Python codebases

**Cons:**

- Requires moving files and updating imports (but it's a "one-and-done" change)

##### Option D) Move `from_audnex()` factories out of canonical schemas (surgical fix)

If `canonical.py` currently imports anything "provider-ish" (directly or indirectly), move those mapping factories into a separate module:

- `canonical.py`: only models
- `mappers/audnex_to_canonical.py`: conversion logic
- `providers/audnex.py`: calls mapper

**Pros:**

- Preserves model purity
- Removes import pressure from canonical types

**Cons:**

- Requires adjusting call sites
- Needs clear ownership of mapping rules (provider vs mapper)

##### Option E) Provider registration restructuring (bigger refactor)

Decouple provider discovery/registration so `metadata/__init__.py` no longer imports providers at import time.

This is the "architectural" solution if the system is growing into a plugin-like design.

**Pros:**

- Most scalable
- Eliminates entire class of import-order problems

**Cons:**

- Bigger change, needs design time
- Not worth it unless provider ecosystem expands significantly

---

#### When it's worth fixing (signals, not vibes)

This duplication can remain until one of these becomes true:

- People keep accidentally using `AudnexAuthor` outside validation/provider boundary
- A change requires updating both models frequently (maintenance pain)
- Pydantic serialization/deserialization starts diverging between the two
- The metadata package's import-time side effects begin causing other cycles

Until then, documenting the constraint + enforcing the boundary is the pragmatic move.

---

#### Bottom line

- The duplication exists because **import-time side effects in `metadata/__init__.py`** pull in providers/clients which depend back on `schemas/audnex.py`.
- This is a **near-term refactor limitation**, not a fundamental design constraint.
- **New code should always prefer canonical `Person/Series`**; use `AudnexAuthor/AudnexSeries` only at the raw response validation boundary.
- There are clear future refactor paths (TYPE_CHECKING, lazy loading, types module split) if/when it becomes worth it.

### 2.3 Single Source of Truth (Target State)

> **Status (Phase 7):** ✅ Canonical types now live in `metadata/schemas/canonical.py`.

All shared types now live in ONE place:

| Path | Contents |
| --- | --- |
| `metadata/schemas/canonical.py` | Types: `Person`, `Series`, `Genre`, `CanonicalMetadata` |
| `metadata/opf/schemas.py` | Re-exports canonical + OPF-specific: `OPFCreator`, `OPFMetadata`, etc. |

Audnex schemas (`AudnexAuthor`, `AudnexSeries`, `AudnexGenre`) remain separate due to circular imports but are documented as structurally identical to canonical types.

### 2.4 Model Layers (Why Both Pydantic and Dataclasses Exist)

| Layer | Type | Purpose | Examples |
| --- | --- | --- | --- |
| **Validation Schemas** | Pydantic | Raw API response validation | `AudnexBook`, `AbsMetadataJson` |
| **Canonical Schema** | Pydantic | Normalized truth (provider-merged) | `CanonicalMetadata`, `Person`, `Series` |
| **Pipeline Models** | dataclass | Workflow state, file paths, computed values | `AudiobookRelease`, `NormalizedBook` |

**Rule:** Don't add 18 fields to `NormalizedBook` because it's convenient. Keep layers separate:

- Validation = external API shapes
- Canonical = internal truth
- Pipeline = operational state

### 2.5 NormalizedBook vs CanonicalMetadata (Boundary)

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
