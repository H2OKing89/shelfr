# Metadata Sidecar Discovery Document

> **Feature:** Unified metadata sidecar generation (JSON + OPF) for ABS import
> **Status:** Discovery → Design Phase
> **Related:** OPF sidecar (PR #63), [Metadata Architecture](../reference/metadata/architecture/README.md), [Naming System](../reference/metadata/naming/NAMING.md)

---

## 1. Overview

Implement a unified `src/shelfr/metadata/` module for generating both `metadata.json` and `metadata.opf` sidecars. This refactors the existing OPF module and adds JSON support with shared cleaning/normalization logic.

### Goals

1. Generate `metadata.json` and/or `metadata.opf` alongside audiobook folders
2. Match ABS schema exactly for seamless import
3. **DRY architecture** - shared `CanonicalMetadata`, cleaning, and helpers
4. **Modular & optional** - each sidecar type independently enabled/disabled
5. Primary use case: `abs import` command
6. Secondary use case: `abs organize` command (future)

---

## 2. Discovery Findings

### 2.1 Authoritative ABS Source

**File:** `server/models/Book.js` → `getAbsMetadataJson()`
**Repo:** [advplyr/audiobookshelf](https://github.com/advplyr/audiobookshelf)

```javascript
// server/models/Book.js lines 337-362
getAbsMetadataJson() {
  return {
    tags: this.tags || [],
    chapters: this.chapters?.map((c) => ({ ...c })) || [],
    title: this.title,
    subtitle: this.subtitle,
    authors: this.authors.map((a) => a.name),
    narrators: this.narrators,
    series: this.series.map((se) => {
      const sequence = se.bookSeries?.sequence || ''
      if (!sequence) return se.name
      return `${se.name} #${sequence}`
    }),
    genres: this.genres || [],
    publishedYear: this.publishedYear,
    publishedDate: this.publishedDate,
    publisher: this.publisher,
    description: this.description,
    isbn: this.isbn,
    asin: this.asin,
    language: this.language,
    explicit: !!this.explicit,
    abridged: !!this.abridged
  }
}
```

### 2.2 Full Schema (from ABS-generated samples)

```json
{
  "tags": ["Science Fiction & Fantasy", "Fantasy"],
  "chapters": [
    {"id": 0, "start": 0, "end": 16.393, "title": "Opening Credits"},
    {"id": 1, "start": 16, "end": 995.928, "title": "Prologue"}
  ],
  "title": "Mark of the Founder: A litRPG Saga",
  "subtitle": "Beastborne, Book 1",
  "authors": ["James T. Callum"],
  "narrators": ["Eric Michael Summerer"],
  "series": ["Beastborne #1"],
  "genres": ["Science Fiction & Fantasy", "Fantasy", "Action & Adventure"],
  "publishedYear": "2021",
  "publishedDate": "2021-03-16",
  "publisher": "Podium Audio",
  "description": "<p><b>A new Founder...</b></p>...",
  "isbn": null,
  "asin": "1774247291",
  "language": "English",
  "explicit": false,
  "abridged": false
}
```

### 2.3 Field Analysis

| Field | Type | Source | Notes |
|-------|------|--------|-------|
| `tags` | `string[]` | Audnex genres | **Merged with genres** (see Decision 3.6) |
| `chapters` | `object[]` | Audio files | **Omitted** - ABS generates from audio |
| `title` | `string` | Audnex `title` | Required, **cleaned** |
| `subtitle` | `string\|null` | Audnex `subtitle` | Optional, **cleaned** of redundant series info |
| `authors` | `string[]` | Audnex `authors[].name` | **Cleaned** (normalization) |
| `narrators` | `string[]` | Audnex `narrators[].name` | **Cleaned** (normalization) |
| `series` | `string[]` | Audnex series | Format: `"Series Name #N"` |
| `genres` | `string[]` | Audnex `genres[].name` | **Merged with tags** |
| `publishedYear` | `string\|int` | Audnex `releaseDate` | Extract year |
| `publishedDate` | `string\|null` | Audnex `releaseDate` | ISO format |
| `publisher` | `string\|null` | Audnex `publisherName` | |
| `description` | `string\|null` | Audnex `description`/`summary` | Keep HTML |
| `isbn` | `string\|null` | Audnex (if available) | |
| `asin` | `string\|null` | Audnex `asin` | Critical for matching |
| `language` | `string` | Audnex `language` | Full name ("English") |
| `explicit` | `bool` | Audnex `isAdult` | Default: false |
| `abridged` | `bool` | Audnex (if available) | Default: false |

### 2.4 Existing Code in Shelfr

> **Status (Phase 7):** `AbsMetadataSchema` was removed and consolidated into `AbsMetadataJson` in `schemas/abs_metadata.py`.

**`src/shelfr/schemas/abs_metadata.py`** has `AbsMetadataJson`:

```python
class AbsMetadataJson(BaseModel):
    title: str | None = None  # Optional for reading existing metadata
    subtitle: str | None = None
    authors: list[str] = Field(default_factory=list)
    narrators: list[str] = Field(default_factory=list)
    series: list[str] = Field(default_factory=list)  # ["Series Name #N"]
    genres: list[str] = Field(default_factory=list)
    tags: list[str] = Field(default_factory=list)
    published_year: str | int | None = Field(default=None, validation_alias="publishedYear")
    publisher: str | None = None
    asin: str | None = None
    isbn: str | None = None
    language: str | None = None
    explicit: bool = False
    abridged: bool = False
    description: str | None = None
    chapters: list[AbsChapter] = Field(default_factory=list)

    model_config = {"extra": "ignore"}
```

**For writing metadata.json**, use `validate_abs_metadata_for_write()` to ensure required fields (title) are present.

### 2.5 Key Differences from OPF

| Aspect | OPF | JSON |
|--------|-----|------|
| Format | XML (Dublin Core) | JSON |
| Series format | `<calibre:series>` + `<calibre:series_index>` | `["Name #N"]` array |
| Description | Plain text (HTML stripped) | HTML preserved |
| Language | ISO 639-2/B code (`eng`) | Full name (`English`) |
| Chapters | Not included | Array of `{id, start, end, title}` |
| File name | `metadata.opf` | `metadata.json` |

---

## 3. Design Decisions

### 3.1 Chapter Handling

**Decision:** Omit `chapters` field entirely (or emit `[]`)

**Rationale:**

- Chapters require audio file analysis (durations, embedded chapter markers)
- ABS will generate chapters from audio files on import
- We don't have access to audio file metadata at sidecar generation time
- Providing empty/incorrect chapters could override good ABS detection

### 3.2 Reuse CanonicalMetadata

**Decision:** Use existing `CanonicalMetadata` (from OPF module) as input

**Rationale:**

- Single source of truth for Audnex → internal mapping
- Already handles all field normalization
- Ensures consistency between OPF and JSON outputs

### 3.3 Series Format

**Decision:** Format series as `["Series Name #N"]` strings

**Rationale:**

- This is exactly how ABS stores and expects series
- Simpler than OPF's separate index field
- Multiple series supported (common for crossover books)

### 3.4 Description Format

**Decision:** Preserve HTML in description (unlike OPF which strips)

**Rationale:**

- ABS stores and displays HTML descriptions
- No need to sanitize since we're not generating XML
- Matches what ABS itself writes

### 3.5 Language Format

**Decision:** Use full language name ("English") not ISO code

**Rationale:**

- ABS samples show "English", "Spanish", etc.
- Differs from OPF which uses ISO 639-2/B

### 3.6 Tags & Genres Handling

**Decision:** Merge `tags` and `genres` into single unified list

**Rationale:**

- ABS samples show these fields are duplicated/identical
- ABS doesn't treat them differently in practice
- Simplifies our data model - one `genres` field populates both
- Less confusion for users

### 3.7 Field Cleaning/Normalization

**Decision:** Clean title, subtitle, authors, and narrators

**Cleaning includes:**

- **Title:** Strip leading/trailing whitespace, normalize Unicode
- **Subtitle:** Remove redundant series/book info (e.g., "Beastborne, Book 1" → just subtitle text)
- **Authors:** Normalize name format, handle "Last, First" → "First Last"
- **Narrators:** Same normalization as authors

**Rationale:**

- Consistent with existing OPF cleaning behavior
- Prevents duplicate/redundant info (series in subtitle when we have series field)
- Shared cleaning logic for both JSON and OPF outputs

### 3.8 Sidecar Generation Options

**Decision:** Both sidecars are optional, independently configurable

**Options:**

- `--opf-sidecar` / `--no-opf-sidecar` (default: enabled)
- `--json-sidecar` / `--no-json-sidecar` (default: enabled)
- Config file options to set defaults

**Rationale:**

- Flexibility for different ABS setups
- Some users may prefer one format over another
- Both can coexist without conflict

---

## 4. Module Structure (DRY Architecture)

Unified `src/shelfr/metadata/` module with shared components:

```bash
src/shelfr/metadata/
├── __init__.py           # Top-level exports: generate_opf, generate_json, write_sidecars
├── canonical.py          # CanonicalMetadata schema (moved from opf/)
├── cleaning.py           # Shared cleaning/normalization for all fields
├── helpers.py            # Shared utilities (language mapping, series formatting)
│
├── opf/                  # OPF-specific (refactored from src/shelfr/opf/)
│   ├── __init__.py
│   ├── generator.py      # generate_opf(), write_opf()
│   └── schemas.py        # OPFMetadata schema
│
└── json/                 # JSON-specific (new)
    ├── __init__.py
    ├── generator.py      # generate_json(), write_json()
    └── schemas.py        # ABSJsonMetadata schema
```

### 4.1 Shared Components

| File | Purpose |
|------|---------|
| `canonical.py` | `CanonicalMetadata` - internal schema from Audnex API |
| `cleaning.py` | `clean_title()`, `clean_subtitle()`, `clean_name()`, `clean_authors()`, `clean_narrators()` |
| `helpers.py` | `format_series_string()`, `language_to_iso()`, `language_to_name()`, `merge_genres_tags()` |

### 4.2 Public API

```python
from shelfr.metadata import (
    CanonicalMetadata,
    generate_opf,
    generate_json,
    write_opf,
    write_json,
    write_sidecars,  # Convenience: writes both if enabled
)

# From raw Audnex API response
audnex_data = fetch_audnex_book("1774248182")
meta = CanonicalMetadata.from_audnex(audnex_data)

# Generate individual sidecars
opf_xml = generate_opf(meta)
json_str = generate_json(meta)

# Write to directory
write_opf(meta, Path("/audiobooks/MyBook"))      # metadata.opf
write_json(meta, Path("/audiobooks/MyBook"))     # metadata.json

# Or write both at once (respects config/flags)
write_sidecars(meta, Path("/audiobooks/MyBook"), opf=True, json=True)
```

### 4.3 Migration from Existing OPF Module

Current `src/shelfr/opf/` will be refactored:

| Current Location | New Location |
|-----------------|--------------|
| `opf/__init__.py` | `metadata/__init__.py` + `metadata/opf/__init__.py` |
| `opf/schemas.py` (CanonicalMetadata) | `metadata/canonical.py` |
| `opf/schemas.py` (OPFMetadata) | `metadata/opf/schemas.py` |
| `opf/generator.py` | `metadata/opf/generator.py` |
| `opf/helpers.py` (shared) | `metadata/helpers.py` + `metadata/cleaning.py` |
| `opf/helpers.py` (OPF-specific) | `metadata/opf/generator.py` |
| `opf/mappings.py` | Split into format-specific generators |

### 4.4 Backward Compatibility

Temporary re-export from old path during transition:

```python
# src/shelfr/opf/__init__.py (deprecated, will warn)
import warnings
warnings.warn(
    "shelfr.opf is deprecated, use shelfr.metadata instead",
    DeprecationWarning
)
from shelfr.metadata import CanonicalMetadata, generate_opf, write_opf
from shelfr.metadata.opf import OPFMetadata, OPFGenerator
```

---

## 5. Implementation Checklist

### Phase 1: Refactor to `src/shelfr/metadata/`

- [ ] Create `src/shelfr/metadata/` directory structure
- [ ] Move `CanonicalMetadata` → `metadata/canonical.py`
- [ ] Extract shared helpers → `metadata/helpers.py`
- [ ] Create `metadata/cleaning.py` with normalization functions
- [ ] Refactor OPF code → `metadata/opf/`
- [ ] Add deprecation shim at `src/shelfr/opf/`
- [ ] Update all imports across codebase

### Phase 2: JSON Sidecar Implementation

- [ ] `metadata/json/schemas.py`: ABSJsonMetadata Pydantic model
- [ ] `metadata/json/generator.py`: generate_json(), write_json()
- [ ] `metadata/json/__init__.py`: exports
- [ ] Update `metadata/__init__.py` with JSON exports

### Phase 3: Cleaning Functions

- [ ] `clean_title()` - whitespace, Unicode normalization
- [ ] `clean_subtitle()` - remove redundant series/book info
- [ ] `clean_name()` - normalize person names
- [ ] `clean_authors()` / `clean_narrators()` - apply to lists
- [ ] `merge_genres_tags()` - unify into single list
- [ ] Unit tests for all cleaning functions

### Phase 4: CLI Integration

- [ ] Add `--opf-sidecar` / `--no-opf-sidecar` flags
- [ ] Add `--json-sidecar` / `--no-json-sidecar` flags
- [ ] Update `abs import` command
- [ ] Config options for defaults
- [ ] Update workflow.py to call write_sidecars()

### Phase 5: Testing

- [ ] Unit tests for JSON schemas
- [ ] Unit tests for JSON generator
- [ ] Golden tests comparing output to ABS samples
- [ ] Integration test with mock ABS library
- [ ] Ensure existing OPF tests still pass

### Phase 6: Documentation

- [ ] Update README with metadata sidecar info
- [ ] Add migration notes for opf → metadata
- [ ] Document config options
- [ ] Add to CHANGELOG

---

## 6. Sample Output (Expected)

Given Audnex response for ASIN `1774247291`:

```json
{
  "tags": ["Science Fiction & Fantasy", "Fantasy", "Action & Adventure", "Epic"],
  "title": "Mark of the Founder",
  "subtitle": "A litRPG Saga",
  "authors": ["James T. Callum"],
  "narrators": ["Eric Michael Summerer"],
  "series": ["Beastborne #1"],
  "genres": ["Science Fiction & Fantasy", "Fantasy", "Action & Adventure", "Epic"],
  "publishedYear": "2021",
  "publishedDate": "2021-03-16",
  "publisher": "Podium Audio",
  "description": "<p><b>A new Founder marked with otherworldly power...</b></p>",
  "isbn": null,
  "asin": "1774247291",
  "language": "English",
  "explicit": false,
  "abridged": false
}
```

**Notes:**

- `chapters` omitted (ABS generates from audio files)
- `tags` and `genres` are identical (merged)
- `subtitle` cleaned of redundant series info

---

## 7. Decisions Summary

| Question | Decision |
|----------|----------|
| Merge `tags` and `genres`? | ✅ Yes - same list for both fields |
| Clean subtitle? | ✅ Yes - remove redundant series/book info |
| Clean title/authors/narrators? | ✅ Yes - normalize all text fields |
| Module location? | `src/shelfr/metadata/` (DRY shared module) |
| Generate both by default? | ✅ Yes - both enabled, independently configurable |
| Primary use case? | `abs import` command |
| Secondary use case? | `abs organize` command (future) |

---

## 8. References

- ABS Source: [`server/models/Book.js#getAbsMetadataJson()`](https://github.com/advplyr/audiobookshelf/blob/main/server/models/Book.js#L337)
- ABS Scanner: [`server/scanner/AbsMetadataFileScanner.js`](https://github.com/advplyr/audiobookshelf/blob/main/server/scanner/AbsMetadataFileScanner.js)
- ABS Generator: [`server/utils/generators/abmetadataGenerator.js`](https://github.com/advplyr/audiobookshelf/blob/main/server/utils/generators/abmetadataGenerator.js)
- Current OPF Module: `src/shelfr/metadata/opf/` (refactored)
- ABS Metadata Schema: `src/shelfr/schemas/abs_metadata.py#AbsMetadataJson`
- Sample JSON files: `samples/abs_metadata/json_samples/`

---

## 9. Architecture Diagram

```text
┌─────────────────────────────────────────────────────────────┐
│                    Audnex API Response                       │
└─────────────────────────────────────────────────────────────┘
                              │
                              ▼
┌─────────────────────────────────────────────────────────────┐
│              CanonicalMetadata.from_audnex()                │
│                  (metadata/canonical.py)                     │
└─────────────────────────────────────────────────────────────┘
                              │
              ┌───────────────┴───────────────┐
              ▼                               ▼
┌──────────────────────────┐    ┌──────────────────────────┐
│   Cleaning & Helpers     │    │   Cleaning & Helpers     │
│ (metadata/cleaning.py)   │    │ (metadata/cleaning.py)   │
└──────────────────────────┘    └──────────────────────────┘
              │                               │
              ▼                               ▼
┌──────────────────────────┐    ┌──────────────────────────┐
│   OPF Generator          │    │   JSON Generator         │
│ (metadata/opf/)          │    │ (metadata/json/)         │
│                          │    │                          │
│ • XML/Dublin Core format │    │ • JSON format            │
│ • ISO language codes     │    │ • Full language names    │
│ • HTML stripped desc     │    │ • HTML preserved desc    │
│ • Series + index fields  │    │ • Series as "Name #N"    │
└──────────────────────────┘    └──────────────────────────┘
              │                               │
              ▼                               ▼
┌──────────────────────────┐    ┌──────────────────────────┐
│     metadata.opf         │    │     metadata.json        │
└──────────────────────────┘    └──────────────────────────┘
```
