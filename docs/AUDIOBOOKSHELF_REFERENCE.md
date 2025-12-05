# Audiobookshelf Import - Technical Reference

> **Document Version:** 1.1.0 | **Last Updated:** 2025-12-05

This document contains technical reference material, testing strategy, and historical changelog for the ABS import feature.

---

## Table of Contents

1. [ASIN Extraction Patterns](#asin-extraction-patterns)
2. [Folder Name Parsing](#folder-name-parsing)
3. [Testing Strategy](#testing-strategy)
4. [Implementation Progress](#implementation-progress)
5. [Library Analysis Report](#library-analysis-report)
6. [Changelog](#changelog)

---

## ASIN Extraction Patterns

The library contains audiobooks from multiple import eras with different ASIN formats:

### Pattern Priority (Cascade)

```python
ASIN_PATTERNS = [
    # 1. Current MAMFast format: {ASIN.B0xxx}
    r"\{ASIN\.([A-Z0-9]{10})\}",

    # 2. Old bracket format: [ASIN.B0xxx]
    r"\[ASIN\.([A-Z0-9]{10})\]",

    # 3. Bare ASIN in brackets: [B0xxxxxxxx]
    r"\[([B][A-Z0-9]{9})\]",

    # 4. Fallback: bare ASIN anywhere (must start with B0)
    r"\b(B0[A-Z0-9]{8})\b",
]
```

### Examples by Format

| Format | Example | Extracted ASIN |
|--------|---------|----------------|
| Current | `Sword Art Online vol_16 (2025) {ASIN.B0DK9TS6D9}` | `B0DK9TS6D9` |
| Old Bracket | `Mushoku Tensei vol_03 [ASIN.B0CNTY7LVH]` | `B0CNTY7LVH` |
| Bare Bracket | `Azarinth Healer vol_04 [B0DMQ2WP9F]` | `B0DMQ2WP9F` |
| Bare Anywhere | `Project Hail Mary B08G9PRS1K` | `B08G9PRS1K` |

### ASIN Validation

```python
def is_valid_asin(asin: str) -> bool:
    """Validate ASIN format (Amazon Standard Identification Number)."""
    if not asin or len(asin) != 10:
        return False
    # Book ASINs start with B0
    if not asin.startswith("B0"):
        return False
    # Rest is alphanumeric
    return asin[2:].isalnum()
```

---

## Folder Name Parsing

### MAM-Style Folder Name Format

```
{Series} vol_{NN} {Arc} ({Year}) ({Author}) {ASIN.xxxxx} [{Tag}]
```

Or for standalone books:
```
{Title} ({Year}) ({Author}) {ASIN.xxxxx} [{Tag}]
```

### ParsedFolderName Dataclass

```python
@dataclass
class ParsedFolderName:
    """Parsed components from MAM-style folder name."""
    author: str
    title: str
    series: str | None
    series_position: str | None
    asin: str | None
    year: str | None
    narrator: str | None
    ripper_tag: str | None
    is_standalone: bool  # True if no series info
```

### Parsing Examples

| Folder Name | Parsed |
|-------------|--------|
| `Sword Art Online vol_16 Alicization (2025) (Reki Kawahara) {ASIN.B0DK9TS6D9} [H2OKing]` | series=`Sword Art Online`, position=`16`, title=`Alicization`, author=`Reki Kawahara`, asin=`B0DK9TS6D9`, tag=`H2OKing` |
| `Project Hail Mary (2021) (Andy Weir) {ASIN.B08G9PRS1K}` | series=`None`, title=`Project Hail Mary`, author=`Andy Weir`, asin=`B08G9PRS1K`, standalone=`True` |

---

## Testing Strategy

### Test Modules

| Test Module | Test Count | Coverage |
|-------------|------------|----------|
| `test_abs_asin.py` | 26 | ASIN extraction + in-memory index |
| `test_abs_client.py` | 23 | ABS API client + caching |
| `test_abs_importer.py` | 38 | Import workflow |
| `test_abs_paths.py` | 37 | Path mapping |
| `test_abs_schemas.py` | 35 | Pydantic schemas |
| `test_cli_abs.py` | 27 | CLI commands |
| **Total ABS Tests** | **186** | |

### Unit Test Categories

```python
class TestASINExtraction:
    def test_new_format_curly_braces(self): ...
    def test_old_format_brackets(self): ...
    def test_bare_asin_brackets(self): ...
    def test_bare_asin_anywhere(self): ...
    def test_no_asin_returns_none(self): ...

class TestFolderNameParsing:
    def test_parse_series_with_arc(self): ...
    def test_parse_series_no_arc(self): ...
    def test_parse_standalone(self): ...
    def test_parse_with_tag(self): ...
    def test_parse_without_tag(self): ...

class TestTargetPathBuilder:
    def test_series_book_path(self): ...
    def test_standalone_book_path(self): ...
    def test_creates_parent_dirs(self): ...

class TestDuplicateDetection:
    def test_asin_exists_in_library(self): ...
    def test_no_duplicate(self): ...

class TestAtomicMove:
    def test_move_same_filesystem(self): ...
    def test_cross_device_fails_validation(self): ...
```

### Test Fixtures

Test fixtures are stored in `tests/fixtures/abs_responses/`:

```
tests/fixtures/abs_responses/
├── authorize.json          # User auth response
├── libraries.json          # Library list response
├── library_items.json      # Library items response
├── library_item_detail.json # Single item detail
└── scan_response.json      # Library scan response
```

---

## Implementation Progress

### PR Summary

| PR | Branch | Status | Description |
|----|--------|--------|-------------|
| **PR 1** | `feature/abs-import-foundations` | ✅ Merged (#15) | Config, schemas, CLI stubs, test fixtures |
| **PR 2** | `feature/abs-import-client` | ✅ Merged (#16) | `AbsClient`, path mapping, `abs-init` wired |
| **PR 3** | `feature/abs-import-index` | ✅ Merged (#19) | ASIN extraction, in-memory index |
| **PR 4** | `feature/abs-import-workflow` | ✅ Complete (#20) | Import workflow, CLI tests, file renaming |

### PR 1 Deliverables
- [x] `docs/AUDIOBOOKSHELF_API.md` - API reference
- [x] `config.yaml` audiobookshelf section + Pydantic schemas
- [x] `.env.example` with `AUDIOBOOKSHELF_HOST`, `AUDIOBOOKSHELF_API_KEY`
- [x] `AudiobookshelfConfig` dataclass in `config.py`
- [x] `mamfast abs-init` CLI stub
- [x] Test fixtures: `tests/fixtures/abs_responses/*.json`

### PR 2 Deliverables
- [x] `src/mamfast/abs/client.py` - `AbsClient` with httpx
- [x] `src/mamfast/abs/paths.py` - Path mapping utilities
- [x] `mamfast abs-init` wired to real API

### PR 3 Deliverables
- [x] `src/mamfast/abs/asin.py` - ASIN extraction + in-memory index
- [x] `build_asin_index()` - Build dict from ABS API
- [x] `asin_exists()` - O(1) duplicate check

### PR 4 Deliverables
- [x] `src/mamfast/abs/importer.py` - Import workflow
- [x] `mamfast abs-import` CLI command
- [x] `mamfast abs-check-duplicate` CLI command
- [x] File renaming on import

---

## Library Analysis Report

> **Note:** This section documents the library state as of initial analysis (2025-12-03).

### Naming Format Inventory

| Format | Pattern | Count | Example |
|--------|---------|-------|---------|
| **Current (MAMFast)** | `{ASIN.B0xxx}` | Majority | `Sword Art Online vol_16 (2025) (Reki Kawahara) {ASIN.B0DK9TS6D9} [H2OKing]` |
| **Old Bracket** | `[ASIN.B0xxx]` | Some | `Mushoku Tensei - vol_03 [2024] [Author] [ASIN.B0CNTY7LVH]` |
| **Old Bare ASIN** | `[B0xxxxxxxx]` | Some | `Azarinth Healer - vol_04 [Rhaegar] [B0DMQ2WP9F]` |
| **Legacy** | No ASIN | Few | `Project Hail Mary.m4b` |

### Directory Structure Patterns

| Type | Structure | Status |
|------|-----------|--------|
| **Series (new)** | `Author/Series/Book Folder/files` | ✅ Consistent |
| **Series (old)** | `Author/Series/Book Folder/files` | ⚠️ Varied naming |
| **Standalone (new)** | `Author/Title Folder/files` | ✅ With ASIN |
| **Standalone (old)** | `Author/Title/files` | ⚠️ No ASIN |

### Author Name Variations Found

| Folder Name | Book `(Author)` | Issue Type |
|-------------|-----------------|------------|
| `J R Mathews` | `J.R. Mathews` | Periods vs spaces |
| `Nekoko` | `Necoco` | Spelling variation |
| `Pirateaba` | `pirateaba` | Case variation |

---

## Changelog

### Version 4.1.0 (2025-12-05) — Current

**Architecture Simplification:**
- Import builds in-memory ASIN index directly from ABS API
- No pre-indexing step required

**CLI Improvements:**
- Dry-run now shows file rename previews
- Better tree output for import results

### Version 4.0.0 (2025-12-04) — Feature Complete

**PR 4 Complete:**
- All import workflow features implemented
- File renaming on import
- Series/author folder matching

**New Functions:**
- `build_clean_folder_name()` - Normalizes folder names (Vol. 7 → vol_07)
- `build_clean_file_name()` - Cleans file names to match folder
- `rename_files_in_folder()` - Renames all files after import

### Version 3.3.x (2025-12-03)

- Fixed enum conflicts (`ImportStage` vs `ImportStatus`)
- Cross-filesystem imports fail validation (protects hardlinks)
- Path mapping uses longest-prefix matching

### Version 3.0.0 (2025-12-03)

**Architecture Pivot:**
- Use ABS API instead of filesystem parsing
- Docker path mapping for container ↔ host translation
- In-memory ASIN index for duplicate detection

**New CLI Commands:**
- `mamfast abs-init` - Validate ABS connection
- `mamfast abs-import` - Import staged books
- `mamfast abs-check-duplicate` - Quick ASIN lookup

### Historical Versions (v1.x - v2.x)

Earlier versions used different approaches that have been superseded.

---

## Related Documentation

- [AUDIOBOOKSHELF_IMPORT.md](AUDIOBOOKSHELF_IMPORT.md) - User guide
- [AUDIOBOOKSHELF_FUTURE.md](AUDIOBOOKSHELF_FUTURE.md) - Future enhancements
- [AUDIOBOOKSHELF_API.md](AUDIOBOOKSHELF_API.md) - ABS API reference
